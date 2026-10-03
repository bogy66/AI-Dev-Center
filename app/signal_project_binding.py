"""Durable administrative binding between a Signal chat and one project."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import uuid


ACTIVE = "active"
SUPERSEDED = "superseded"
REVOKED = "revoked"


class SignalProjectBindingError(Exception):
    pass


class SignalConversationUnboundError(SignalProjectBindingError):
    pass


class SignalProjectReferenceError(SignalProjectBindingError):
    pass


@dataclass(frozen=True)
class SignalProjectBinding:
    id: str
    conversation_id: str
    project_id: str
    project_root: str
    status: str
    created_at: str
    updated_at: str
    supersedes: str | None = None


class SignalProjectBindingService:
    """Manage binding history inside the existing central workflow state."""

    def __init__(self, workflow_manager) -> None:
        self._workflow_manager = workflow_manager

    def create(self, conversation_id, project_id, project_root) -> SignalProjectBinding:
        conversation_id, project_id = self._validate_identity(conversation_id, project_id)
        root = self._valid_project_root(project_root)
        now = datetime.now(timezone.utc).isoformat()
        with self._workflow_manager.communication_state_transaction():
            state = self._workflow_manager.load()
            records = state.setdefault("signal_project_bindings", [])
            self._validate_records(records)
            active = [self._model(item) for item in records if item.get("status") == ACTIVE]
            same = next((
                item for item in active
                if self._same_pair(item, conversation_id, project_id, root)
            ), None)
            if same is not None:
                return same
            if any(item.conversation_id == conversation_id for item in active):
                raise SignalProjectBindingError(
                    "Signal conversation already has an active project binding"
                )
            if any(self._same_project(item, project_id, root) for item in active):
                raise SignalProjectBindingError(
                    "AI-Dev-Center project already has an active Signal conversation"
                )
            binding = SignalProjectBinding(
                id=f"signal-binding-{uuid.uuid4().hex}",
                conversation_id=conversation_id,
                project_id=project_id,
                project_root=root,
                status=ACTIVE,
                created_at=now,
                updated_at=now,
            )
            records.append(asdict(binding))
            self._workflow_manager.save(state)
            return binding

    def resolve(self, conversation_id: str) -> SignalProjectBinding:
        conversation_id, _ = self._validate_identity(conversation_id, "placeholder")
        state = self._workflow_manager.load()
        records = state.get("signal_project_bindings", [])
        self._validate_records(records)
        matching = [
            item for item in records
            if item.get("conversation_id") == conversation_id
        ]
        active = [item for item in matching if item.get("status") == ACTIVE]
        if not active:
            if matching:
                raise SignalProjectReferenceError(
                    "Signal project binding is inactive"
                )
            raise SignalConversationUnboundError(
                "Signal conversation is not bound to a project"
            )
        if len(active) != 1:
            raise SignalProjectReferenceError(
                "Signal conversation has invalid active project bindings"
            )
        binding = self._model(active[0])
        resolved = self._valid_project_root(binding.project_root)
        if resolved != binding.project_root:
            raise SignalProjectReferenceError("Signal project reference is invalid")
        return binding

    def rebind(self, conversation_id, project_id, project_root) -> SignalProjectBinding:
        conversation_id, project_id = self._validate_identity(conversation_id, project_id)
        root = self._valid_project_root(project_root)
        now = datetime.now(timezone.utc).isoformat()
        with self._workflow_manager.communication_state_transaction():
            state = self._workflow_manager.load()
            records = state.setdefault("signal_project_bindings", [])
            self._validate_records(records)
            active = [
                item for item in records
                if item.get("conversation_id") == conversation_id
                and item.get("status") == ACTIVE
            ]
            if len(active) != 1:
                raise SignalProjectBindingError(
                    "Rebind requires exactly one active project binding"
                )
            previous = active[0]
            previous_model = self._model(previous)
            if self._same_pair(previous_model, conversation_id, project_id, root):
                return previous_model
            other_active = [
                self._model(item) for item in records
                if item.get("status") == ACTIVE and item is not previous
            ]
            if any(self._same_project(item, project_id, root) for item in other_active):
                raise SignalProjectBindingError(
                    "AI-Dev-Center project already has an active Signal conversation"
                )
            previous["status"] = SUPERSEDED
            previous["updated_at"] = now
            binding = SignalProjectBinding(
                id=f"signal-binding-{uuid.uuid4().hex}",
                conversation_id=conversation_id,
                project_id=project_id,
                project_root=root,
                status=ACTIVE,
                created_at=now,
                updated_at=now,
                supersedes=previous["id"],
            )
            records.append(asdict(binding))
            self._workflow_manager.save(state)
            return binding

    def revoke(self, conversation_id: str) -> SignalProjectBinding:
        conversation_id, _ = self._validate_identity(conversation_id, "placeholder")
        now = datetime.now(timezone.utc).isoformat()
        with self._workflow_manager.communication_state_transaction():
            state = self._workflow_manager.load()
            records = state.setdefault("signal_project_bindings", [])
            self._validate_records(records)
            active = [
                item for item in records
                if item.get("conversation_id") == conversation_id
                and item.get("status") == ACTIVE
            ]
            if len(active) != 1:
                raise SignalProjectBindingError(
                    "Revoke requires exactly one active project binding"
                )
            active[0]["status"] = REVOKED
            active[0]["updated_at"] = now
            self._workflow_manager.save(state)
            return self._model(active[0])

    def history(self, conversation_id: str) -> tuple[SignalProjectBinding, ...]:
        conversation_id, _ = self._validate_identity(conversation_id, "placeholder")
        records = self._workflow_manager.load().get("signal_project_bindings", [])
        self._validate_records(records)
        return tuple(
            self._model(item) for item in records
            if item.get("conversation_id") == conversation_id
        )

    @staticmethod
    def _validate_identity(conversation_id, project_id):
        values = []
        for name, value in (("conversation_id", conversation_id), ("project_id", project_id)):
            if not isinstance(value, str) or not value.strip() or len(value.strip()) > 512:
                raise SignalProjectBindingError(f"{name} must be a bounded non-empty string")
            values.append(value.strip())
        return tuple(values)

    @staticmethod
    def _valid_project_root(project_root) -> str:
        if not isinstance(project_root, (str, Path)) or not str(project_root).strip():
            raise SignalProjectReferenceError("Project reference is invalid")
        try:
            root = Path(project_root).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise SignalProjectReferenceError("Project reference cannot be resolved") from error
        if not root.is_dir():
            raise SignalProjectReferenceError("Project reference is not a directory")
        return str(root)

    @staticmethod
    def _validate_records(records) -> None:
        if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
            raise SignalProjectBindingError("Signal project binding state is invalid")
        models = [SignalProjectBindingService._model(item) for item in records]
        if len({item.id for item in models}) != len(models):
            raise SignalProjectBindingError("Signal project binding ids are not unique")
        active = [item for item in models if item.status == ACTIVE]
        if len({item.conversation_id for item in active}) != len(active):
            raise SignalProjectBindingError("Signal conversations are not uniquely bound")
        project_ids = {item.project_id for item in active}
        project_roots = {item.project_root for item in active}
        if len(project_ids) != len(active) or len(project_roots) != len(active):
            raise SignalProjectBindingError("AI-Dev-Center projects are not uniquely bound")

    @staticmethod
    def _same_pair(binding, conversation_id, project_id, project_root) -> bool:
        return (
            binding.conversation_id == conversation_id
            and binding.project_id == project_id
            and binding.project_root == project_root
        )

    @staticmethod
    def _same_project(binding, project_id, project_root) -> bool:
        return binding.project_id == project_id or binding.project_root == project_root

    @staticmethod
    def _model(record) -> SignalProjectBinding:
        try:
            binding = SignalProjectBinding(**record)
        except (TypeError, ValueError) as error:
            raise SignalProjectBindingError("Signal project binding is invalid") from error
        if binding.status not in {ACTIVE, SUPERSEDED, REVOKED}:
            raise SignalProjectBindingError("Signal project binding status is invalid")
        SignalProjectBindingService._validate_identity(
            binding.conversation_id, binding.project_id,
        )
        if not isinstance(binding.id, str) or not binding.id:
            raise SignalProjectBindingError("Signal project binding id is invalid")
        try:
            created_at = datetime.fromisoformat(binding.created_at)
            updated_at = datetime.fromisoformat(binding.updated_at)
        except (TypeError, ValueError) as error:
            raise SignalProjectBindingError("Signal project binding timestamp is invalid") from error
        if created_at.tzinfo is None or updated_at.tzinfo is None:
            raise SignalProjectBindingError("Signal project binding timestamp is invalid")
        if binding.supersedes is not None and not isinstance(binding.supersedes, str):
            raise SignalProjectBindingError("Signal project binding history is invalid")
        return binding
