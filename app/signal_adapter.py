"""Signal transport adapter for the central application workflow."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Protocol

from app.common_request import RequestIntent
from app.dev_workflow import WorkflowExecutionError


class SignalTransportProvider(Protocol):
    """Replaceable external Signal boundary; no provider is implemented here."""

    def receive(self) -> Mapping[str, Any] | None: ...

    def send(self, response: "SignalAdapterResponse") -> None: ...


@dataclass(frozen=True)
class SignalIncomingMessage:
    sender_id: str
    conversation_id: str
    message_id: str
    received_at: datetime
    text: str
    intent: str
    project_id: str
    project_path: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SignalIncomingMessage":
        if not isinstance(value, Mapping):
            raise ValueError("Signal input must be a structured object")
        required = (
            "sender_id", "conversation_id", "message_id", "received_at",
            "text", "intent", "project_id", "project_path",
        )
        data: dict[str, str] = {}
        for name in required:
            item = value.get(name)
            if not isinstance(item, str) or not item.strip():
                raise ValueError(f"Signal field {name} must be a non-empty string")
            data[name] = item.strip()
        for name in ("sender_id", "conversation_id", "message_id", "intent", "project_id"):
            if len(data[name]) > 512:
                raise ValueError(f"Signal field {name} is too long")
        if len(data["text"]) > 4096 or len(data["project_path"]) > 4096:
            raise ValueError("Signal input is too long")
        try:
            received_at = datetime.fromisoformat(data.pop("received_at").replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("Signal received_at must be an ISO-8601 timestamp") from error
        if received_at.tzinfo is None:
            raise ValueError("Signal received_at must include a timezone")
        return cls(received_at=received_at, **data)


@dataclass(frozen=True)
class SignalAdapterResponse:
    status: str
    message: str
    conversation_id: str | None = None
    reply_destination: str | None = None
    in_reply_to: str | None = None
    project_id: str | None = None
    run_id: str | None = None
    plan_id: str | None = None

    def to_record(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "SignalAdapterResponse":
        return cls(**{name: value.get(name) for name in cls.__dataclass_fields__})


class SignalCommunicationAdapter:
    """Validate Signal envelopes and delegate planning to shared services."""

    def __init__(self, service, plan_store, workflow_manager) -> None:
        self._service = service
        self._plan_store = plan_store
        self._workflow_manager = workflow_manager

    def handle(self, raw_message: Mapping[str, Any]) -> SignalAdapterResponse:
        try:
            incoming = SignalIncomingMessage.from_mapping(raw_message)
        except (TypeError, ValueError):
            return SignalAdapterResponse("malformed_input", "The Signal request is malformed.")

        correlation = {
            "conversation_id": incoming.conversation_id,
            "reply_destination": incoming.conversation_id,
            "in_reply_to": incoming.message_id,
            "project_id": incoming.project_id,
        }
        try:
            claimed, record = self._workflow_manager.begin_communication_request(
                "signal", incoming.message_id, incoming.sender_id,
                incoming.conversation_id,
            )
        except ValueError:
            return SignalAdapterResponse(
                "workflow_rejection", "The Signal request was rejected.", **correlation,
            )
        except Exception:
            return SignalAdapterResponse(
                "workflow_failure", "The Signal request could not be recorded.",
                **correlation,
            )
        if not claimed:
            persisted = record.get("response")
            if isinstance(persisted, dict):
                return SignalAdapterResponse.from_record(persisted)
            return SignalAdapterResponse(
                "workflow_failure",
                "This Signal request is already being processed; recovery is required.",
                **correlation,
            )

        response = self._dispatch(incoming, correlation)
        try:
            self._workflow_manager.complete_communication_request(
                "signal", incoming.message_id, incoming.sender_id,
                incoming.conversation_id, response.to_record(),
            )
        except Exception:
            return SignalAdapterResponse(
                "workflow_failure", "The Signal response could not be recorded.",
                **correlation,
            )
        return response

    def send(self, raw_message: Mapping[str, Any], provider: SignalTransportProvider):
        """Format centrally produced output and pass it to the chosen provider."""
        response = self.handle(raw_message)
        provider.send(response)
        return response

    def process_next(self, provider: SignalTransportProvider):
        """Process at most one provider-delivered message through this adapter."""
        incoming = provider.receive()
        if incoming is None:
            return None
        return self.send(incoming, provider)

    def _dispatch(self, incoming, correlation) -> SignalAdapterResponse:
        if incoming.intent != RequestIntent.PLAN_PROJECT_SETUP.value:
            return SignalAdapterResponse(
                "unsupported_request", "This Signal request type is not supported.",
                **correlation,
            )
        run_id = self._run_id(incoming)
        try:
            result = self._service.plan_project_setup(
                incoming.project_id, Path(incoming.project_path), run_id=run_id,
            )
            self._plan_store.save(result.setup_plan)
        except (ValueError, WorkflowExecutionError):
            return SignalAdapterResponse(
                "workflow_rejection", "The central workflow rejected this request.",
                run_id=run_id, **correlation,
            )
        except Exception:
            return SignalAdapterResponse(
                "workflow_failure", "The central workflow could not complete the request.",
                run_id=run_id, **correlation,
            )
        approval_required = bool(result.setup_plan.requires_user_approval)
        return SignalAdapterResponse(
            "approval_required" if approval_required else "accepted",
            (
                "The request was accepted and requires separate Human Approval."
                if approval_required else "The request was accepted by the central workflow."
            ),
            run_id=run_id, plan_id=result.setup_plan.id, **correlation,
        )

    @staticmethod
    def _run_id(incoming: SignalIncomingMessage) -> str:
        identity = "\0".join((
            incoming.sender_id, incoming.conversation_id, incoming.message_id,
        )).encode("utf-8")
        return f"signal-{sha256(identity).hexdigest()[:24]}"
