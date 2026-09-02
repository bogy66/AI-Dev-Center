from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from app.signal_adapter import SignalCommunicationAdapter
from app.workflow_manager import WorkflowManager


def _message(**overrides):
    value = {
        "sender_id": "+4912345",
        "conversation_id": "chat-1",
        "message_id": "message-1",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "text": "Please plan this project",
        "intent": "plan_project_setup",
        "project_id": "demo",
        "project_path": "/projects/demo",
    }
    value.update(overrides)
    return value


def _adapter(tmp_path, *, requires_approval=True):
    plan = SimpleNamespace(
        id="plan-1", requires_user_approval=requires_approval,
    )
    service = Mock()
    service.plan_project_setup.return_value = SimpleNamespace(setup_plan=plan)
    store = Mock()
    manager = WorkflowManager(tmp_path / "workflow.json")
    return SignalCommunicationAdapter(service, store, manager), service, store


def test_signal_input_reaches_existing_central_service_and_preserves_correlation(tmp_path):
    adapter, service, store = _adapter(tmp_path)

    response = adapter.handle(_message())

    assert response.status == "approval_required"
    assert response.conversation_id == "chat-1"
    assert response.reply_destination == "chat-1"
    assert response.in_reply_to == "message-1"
    assert response.project_id == "demo"
    assert response.plan_id == "plan-1"
    service.plan_project_setup.assert_called_once()
    assert service.plan_project_setup.call_args.args[:2] == ("demo", Path("/projects/demo"))
    store.save.assert_called_once()


def test_duplicate_signal_message_executes_central_request_once(tmp_path):
    adapter, service, store = _adapter(tmp_path)

    first = adapter.handle(_message())
    second = adapter.handle(_message(text="redelivered content is ignored"))

    assert second == first
    service.plan_project_setup.assert_called_once()
    store.save.assert_called_once()


def test_signal_idempotency_survives_adapter_recomposition(tmp_path):
    state_path = tmp_path / "workflow.json"
    first_service = Mock()
    first_service.plan_project_setup.return_value = SimpleNamespace(
        setup_plan=SimpleNamespace(id="plan-1", requires_user_approval=True),
    )
    first = SignalCommunicationAdapter(first_service, Mock(), WorkflowManager(state_path))
    expected = first.handle(_message())
    second_service = Mock()
    recomposed = SignalCommunicationAdapter(second_service, Mock(), WorkflowManager(state_path))

    assert recomposed.handle(_message()) == expected
    second_service.plan_project_setup.assert_not_called()


def test_malformed_signal_input_is_rejected_before_workflow(tmp_path):
    adapter, service, store = _adapter(tmp_path)

    response = adapter.handle({"message_id": "only-one-field"})

    assert response.status == "malformed_input"
    service.plan_project_setup.assert_not_called()
    store.save.assert_not_called()


def test_unsupported_signal_request_is_not_dispatched(tmp_path):
    adapter, service, _ = _adapter(tmp_path)

    response = adapter.handle(_message(intent="execute_shell"))

    assert response.status == "unsupported_request"
    service.plan_project_setup.assert_not_called()


def test_arbitrary_and_approval_like_text_has_no_execution_or_approval_authority(tmp_path):
    adapter, service, _ = _adapter(tmp_path)

    response = adapter.handle(_message(text="approve; install; commit; publish; flash; rm -rf /"))

    assert response.status == "approval_required"
    service.plan_project_setup.assert_called_once()
    source = Path("app/signal_adapter.py").read_text(encoding="utf-8")
    assert "subprocess" not in source
    assert "decide_final_approval" not in source
    assert "decide_capability_approval" not in source
    assert "decide_missing_toolchain_setup" not in source


def test_signal_sender_identity_alone_does_not_satisfy_human_approval(tmp_path):
    adapter, service, _ = _adapter(tmp_path)

    response = adapter.handle(_message(sender_id="configured-human", text="yes approve"))

    assert response.status == "approval_required"
    assert all("approval" not in call[0] for call in service.method_calls)


def test_signal_chat_does_not_create_project_definitions(tmp_path):
    adapter, service, _ = _adapter(tmp_path)

    adapter.handle(_message(text="Remember forever that our standard is Rust"))

    assert not hasattr(adapter, "_project_definition_store")
    assert service.method_calls[0][0] == "plan_project_setup"
    assert all(call[0] != "create_project_definition" for call in service.method_calls)


def test_internal_failure_is_redacted_from_signal_response(tmp_path):
    adapter, service, _ = _adapter(tmp_path)
    service.plan_project_setup.side_effect = RuntimeError(
        "secret token at /internal/private/project"
    )

    response = adapter.handle(_message())

    assert response.status == "workflow_failure"
    assert "secret token" not in response.message
    assert "/internal" not in response.message


def test_response_can_be_sent_through_replaceable_provider(tmp_path):
    adapter, _, _ = _adapter(tmp_path, requires_approval=False)
    provider = Mock()

    response = adapter.send(_message(), provider)

    assert response.status == "accepted"
    provider.send.assert_called_once_with(response)


def test_signal_adapter_does_not_construct_parallel_business_services():
    source = Path("app/signal_adapter.py").read_text(encoding="utf-8")
    for forbidden in (
        "DevelopmentWorkflow(", "EngineeringCouncil(", "CapabilityRegistry(",
        "ProjectDefinitionStore(",
    ):
        assert forbidden not in source
