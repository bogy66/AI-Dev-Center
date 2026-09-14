from unittest.mock import Mock

import pytest

from app.mcp_server import MCPCentralServiceRequiredError, MCPServer, ToolDefinition
from app.requirement_model import SetupPlan
from app.setup_approval import SetupApprovalError


def make_server(service="default"):
    """A real central ProjectSetupApplicationService (as a Mock) is
    injected by default -- CLAUDE-E2E-003G removed the old, untraced,
    unauthorized fallback path for plan/approve/execute, so a
    productive-shaped test must supply one. Pass service=None
    explicitly to test the fail-closed behavior when it is absent.
    """
    return MCPServer(
        project_scanner=Mock(),
        discovery=Mock(),
        preflight=Mock(),
        planner=Mock(),
        plan_store=Mock(),
        approval=Mock(),
        development_workflow=Mock(),
        service=Mock() if service == "default" else service,
    )


def test_inspect_project_calls_scanner():
    server = make_server()
    scanner_result = ["a.py", "b.yaml"]
    server._project_scanner.scan.return_value = scanner_result

    result = server.inspect_project("/tmp/project")

    server._project_scanner.scan.assert_called_once_with("/tmp/project")
    assert result == {"project_path": "/tmp/project", "files": scanner_result}


def test_discover_requirements_calls_discovery():
    server = make_server()
    discovery_result = object()
    server._discovery.discover.return_value = discovery_result

    result = server.discover_requirements("/tmp/project")

    server._discovery.discover.assert_called_once_with("/tmp/project")
    assert result is discovery_result


def test_get_preflight_calls_preflight():
    server = make_server()
    preflight_result = object()
    server._preflight.check.return_value = preflight_result

    requirements = object()
    result = server.get_preflight(requirements, "project-123")

    server._preflight.check.assert_called_once_with(requirements, "project-123")
    assert result is preflight_result


def test_create_setup_plan_calls_planner_and_store():
    server = make_server()
    plan = object()
    saved_path = object()
    server._planner.plan.return_value = plan
    server._plan_store.save.return_value = saved_path

    requirements = object()
    preflight_result = object()
    result = server.create_setup_plan(requirements, preflight_result, "project-123")

    server._planner.plan.assert_called_once_with(
        requirements, preflight_result, "project-123"
    )
    server._plan_store.save.assert_called_once_with(plan)
    assert result is saved_path


def test_plan_project_setup_uses_central_service_and_store(tmp_path):
    server = make_server()
    setup_plan = Mock(id="plan-456", status="pending_approval", project_id="project-123")
    server._service.plan_project_setup.return_value = Mock(
        setup_plan=setup_plan, council_result=None,
    )

    result = server.plan_project_setup("project-123", str(tmp_path))

    server._service.plan_project_setup.assert_called_once_with(
        "project-123", str(tmp_path.resolve()),
        entry_interface="mcp", entry_data={"project_id": "project-123"},
    )
    server._development_workflow.run.assert_not_called()
    server._planner.plan.assert_not_called()
    server._plan_store.save.assert_called_once_with(setup_plan)
    server._plan_store.save_project_root.assert_called_once_with(
        "project-123", str(tmp_path.resolve()),
    )
    assert result is setup_plan


def test_plan_project_setup_passes_task_description_when_supplied(tmp_path):
    server = make_server()
    setup_plan = Mock(id="plan-456", status="pending_approval", project_id="project-123")
    server._service.plan_project_setup.return_value = Mock(
        setup_plan=setup_plan, council_result=None,
    )

    server.plan_project_setup("project-123", str(tmp_path), task_description="Build a widget")

    server._service.plan_project_setup.assert_called_once_with(
        "project-123", str(tmp_path.resolve()),
        entry_interface="mcp",
        entry_data={"project_id": "project-123", "task_description": "Build a widget"},
    )


def test_plan_project_setup_rejects_nonexistent_project_root(tmp_path):
    server = make_server()

    with pytest.raises(FileNotFoundError):
        server.plan_project_setup("project-123", str(tmp_path / "does-not-exist"))

    server._service.plan_project_setup.assert_not_called()
    server._plan_store.save.assert_not_called()


def test_plan_project_setup_rejects_empty_project_root():
    server = make_server()

    with pytest.raises(ValueError):
        server.plan_project_setup("project-123", "   ")

    server._service.plan_project_setup.assert_not_called()


def test_plan_project_setup_fails_closed_without_central_service(tmp_path):
    server = make_server(service=None)

    with pytest.raises(MCPCentralServiceRequiredError):
        server.plan_project_setup("project-123", str(tmp_path))


def test_get_setup_plan_loads_from_store():
    server = make_server()
    plan = object()
    server._plan_store.load.return_value = plan

    result = server.get_setup_plan("project-123", "plan-456")

    server._plan_store.load.assert_called_once_with("project-123", "plan-456")
    assert result is plan


def test_approve_setup_plan_uses_central_service():
    server = make_server()
    plan = SetupPlan(id="plan-456", project_id="project-123", status="pending_approval")
    server._plan_store.load.return_value = plan

    result = server.approve_setup_plan("project-123", "plan-456")

    server._plan_store.load.assert_called_once_with("project-123", "plan-456")
    server._plan_store.save.assert_called_once()
    server._service.record_setup_approval_event.assert_called_once_with(
        "project-123", "plan-456", result.generation_id, None,
    )
    server._approval.approve.assert_not_called()
    assert result.status == "approved"


def test_approve_setup_plan_fails_closed_without_central_service():
    server = make_server(service=None)

    with pytest.raises(MCPCentralServiceRequiredError):
        server.approve_setup_plan("project-123", "plan-456")

    server._plan_store.load.assert_not_called()
    server._approval.approve.assert_not_called()


def test_execute_setup_plan_loads_checks_approval_and_executes(tmp_path):
    server = make_server()
    plan = Mock(status="approved")
    execution_result = object()
    server._plan_store.load.return_value = plan
    server._plan_store.load_project_root.return_value = str(tmp_path)
    server._plan_store.load_council_reference.return_value = None
    server._service._development_workflow.execute_approved.return_value = execution_result

    result = server.execute_setup_plan("project-123", "plan-456")

    server._plan_store.load.assert_called_with("project-123", "plan-456")
    server._plan_store.load_project_root.assert_called_once_with("project-123")
    server._service._development_workflow.execute_approved.assert_called_once_with(
        plan, str(tmp_path),
    )
    server._development_workflow.execute_approved.assert_not_called()
    assert result is execution_result


def test_execute_setup_plan_raises_when_not_approved():
    server = make_server()
    plan = Mock(status="pending_approval")
    server._plan_store.load.return_value = plan

    with pytest.raises(SetupApprovalError):
        server.execute_setup_plan("project-123", "plan-456")

    server._service._development_workflow.execute_approved.assert_not_called()


def test_execute_setup_plan_fails_closed_without_associated_project_root():
    """A plan with no persisted project_root must never fall back to
    unconfined execution — it must refuse outright."""
    server = make_server()
    plan = Mock(status="approved")
    server._plan_store.load.return_value = plan
    server._plan_store.load_project_root.return_value = None

    with pytest.raises(SetupApprovalError):
        server.execute_setup_plan("project-123", "plan-456")

    server._service._development_workflow.execute_approved.assert_not_called()


def test_execute_setup_plan_fails_closed_without_central_service():
    server = make_server(service=None)

    with pytest.raises(MCPCentralServiceRequiredError):
        server.execute_setup_plan("project-123", "plan-456")

    server._plan_store.load.assert_not_called()


def test_list_tools_contains_all_expected_names():
    server = make_server()
    tool_names = {tool.name for tool in server.list_tools()}

    assert tool_names == {
        "inspect_project",
        "discover_requirements",
        "get_preflight",
        "create_setup_plan",
        "plan_project_setup",
        "get_setup_plan",
        "approve_setup_plan",
        "execute_setup_plan",
    }
