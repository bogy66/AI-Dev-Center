from unittest.mock import Mock

import pytest

from app.mcp_server import MCPServer, ToolDefinition
from app.setup_approval import SetupApprovalError


def make_server():
    return MCPServer(
        project_scanner=Mock(),
        discovery=Mock(),
        preflight=Mock(),
        planner=Mock(),
        plan_store=Mock(),
        approval=Mock(),
        development_workflow=Mock(),
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


def test_get_setup_plan_loads_from_store():
    server = make_server()
    plan = object()
    server._plan_store.load.return_value = plan

    result = server.get_setup_plan("project-123", "plan-456")

    server._plan_store.load.assert_called_once_with("project-123", "plan-456")
    assert result is plan


def test_approve_setup_plan_calls_approval_approve():
    server = make_server()
    plan = object()
    approved_plan = object()
    server._plan_store.load.return_value = plan
    server._approval.approve.return_value = approved_plan

    result = server.approve_setup_plan("project-123", "plan-456")

    server._plan_store.load.assert_called_once_with("project-123", "plan-456")
    server._approval.approve.assert_called_once_with(plan)
    server._plan_store.save.assert_called_once_with(approved_plan)
    assert result is approved_plan


def test_execute_setup_plan_loads_checks_approval_and_executes():
    server = make_server()
    plan = Mock(status="approved")
    execution_result = object()
    server._plan_store.load.return_value = plan
    server._development_workflow.execute_approved.return_value = execution_result

    result = server.execute_setup_plan("project-123", "plan-456")

    server._plan_store.load.assert_called_once_with("project-123", "plan-456")
    server._development_workflow.execute_approved.assert_called_once_with(plan)
    assert result is execution_result


def test_execute_setup_plan_raises_when_not_approved():
    server = make_server()
    plan = Mock(status="pending_approval")
    server._plan_store.load.return_value = plan

    with pytest.raises(SetupApprovalError):
        server.execute_setup_plan("project-123", "plan-456")

    server._development_workflow.execute_approved.assert_not_called()


def test_list_tools_contains_all_expected_names():
    server = make_server()
    tool_names = {tool.name for tool in server.list_tools()}

    assert tool_names == {
        "inspect_project",
        "discover_requirements",
        "get_preflight",
        "create_setup_plan",
        "get_setup_plan",
        "approve_setup_plan",
        "execute_setup_plan",
    }
