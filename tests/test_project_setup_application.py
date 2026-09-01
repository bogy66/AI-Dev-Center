from pathlib import Path
from unittest.mock import Mock

import pytest

from app.common_request import RequestIntent
from app.dev_workflow import WorkflowExecutionError
from app.project_setup_application import ProjectSetupApplicationService


def test_service_inspects_once_and_delegates_canonical_planning(tmp_path):
    project_info = {"project_id": "demo", "project_path": str(tmp_path), "files": []}
    inspector = Mock()
    inspector.inspect.return_value = project_info
    workflow_result = Mock()
    workflow = Mock()
    workflow.run.return_value = workflow_result
    service = ProjectSetupApplicationService(workflow, inspector)

    result = service.plan_project_setup("demo", tmp_path)

    assert result is workflow_result
    inspector.inspect.assert_called_once_with("demo", tmp_path)
    workflow.run.assert_called_once_with(project_info, "demo")


def test_service_builds_planning_intent_before_workflow_delegation(tmp_path):
    inspector = Mock()
    inspector.inspect.return_value = {"project_id": "demo", "files": []}
    workflow = Mock()
    service = ProjectSetupApplicationService(workflow, inspector)

    request = service.build_request("demo", tmp_path)

    assert request.project_id == "demo"
    assert request.project_info == {"project_id": "demo", "files": []}
    assert request.intent is RequestIntent.PLAN_PROJECT_SETUP


def test_service_rejects_empty_project_id_before_inspection(tmp_path):
    inspector = Mock()
    service = ProjectSetupApplicationService(Mock(), inspector)

    with pytest.raises(ValueError, match="project_id"):
        service.plan_project_setup("", tmp_path)

    inspector.inspect.assert_not_called()


def test_service_does_not_swallow_workflow_errors(tmp_path):
    inspector = Mock()
    inspector.inspect.return_value = {"project_id": "demo", "files": []}
    workflow = Mock()
    workflow.run.side_effect = WorkflowExecutionError("council unavailable")
    service = ProjectSetupApplicationService(workflow, inspector)

    with pytest.raises(WorkflowExecutionError, match="council unavailable"):
        service.plan_project_setup("demo", tmp_path)


def test_service_has_no_direct_planner_council_materializer_or_executor_dependencies():
    source = Path("app/project_setup_application.py").read_text(encoding="utf-8")

    for forbidden_name in (
        "SetupPlanner",
        "EngineeringCouncil",
        "ToolchainMaterializer",
        "SetupExecutor",
    ):
        assert forbidden_name not in source
