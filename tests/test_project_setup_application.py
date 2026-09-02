from pathlib import Path
from unittest.mock import Mock

import pytest

from app.common_request import RequestIntent
from app.dev_workflow import WorkflowBlockedError, WorkflowExecutionError
from app.diagnostic_trace import DiagnosticTrace, DiagnosticTraceStore
from app.project_intelligence import (
    ProjectIntelligence,
    ProjectArea,
    DetectedLanguage,
    Evidence,
)
from app.project_setup_application import ProjectSetupApplicationService
from app.workflow_manager import WorkflowManager


def _mock_intelligence(project_id, project_path, kind="existing"):
    return ProjectIntelligence(
        project_root=str(project_path),
        project_kind=kind,
        areas=(),
        languages=(),
        frameworks=(),
        package_systems=(),
        build_systems=(),
        test_systems=(),
        firmware_indicators=(),
        ci_indicators=(),
        doc_indicators=(),
        git_repository_present=False,
        sensitive_configuration_present=False,
        warnings=(),
        truncated=False,
        total_files_traversed=0,
        total_files_excluded=0,
        inspection_limit_exceeded=False,
    )


def test_service_inspects_once_and_delegates_canonical_planning(tmp_path):
    project_info = {"project_id": "demo", "project_path": str(tmp_path), "files": []}
    inspector = Mock()
    inspector.inspect.return_value = project_info
    inspector.build_intelligence.return_value = _mock_intelligence("demo", tmp_path)
    inspector.inspect_managed.return_value = (project_info, _mock_intelligence("demo", tmp_path))
    workflow_result = Mock()
    workflow = Mock()
    workflow.run.return_value = workflow_result
    service = ProjectSetupApplicationService(workflow, inspector)

    result = service.plan_project_setup("demo", tmp_path)

    assert result is workflow_result
    inspector.build_intelligence.assert_called_once_with(tmp_path)
    inspector.inspect_managed.assert_called_once_with("demo", tmp_path)
    workflow.run.assert_called_once()
    assert workflow.run.call_args.args[1] == "demo"


def test_service_builds_planning_intent_before_workflow_delegation(tmp_path):
    inspector = Mock()
    inspector.build_intelligence.return_value = _mock_intelligence("demo", tmp_path)
    inspector.inspect.return_value = {"project_id": "demo", "files": []}
    inspector.inspect_managed.return_value = (
        {"project_id": "demo", "project_path": str(tmp_path), "files": []},
        _mock_intelligence("demo", tmp_path),
    )
    workflow = Mock()
    service = ProjectSetupApplicationService(workflow, inspector)

    request = service.build_request("demo", tmp_path)

    assert request.project_id == "demo"
    assert request.intent is RequestIntent.PLAN_PROJECT_SETUP
    assert "project_kind" in request.project_info


def test_service_rejects_empty_project_id_before_inspection(tmp_path):
    inspector = Mock()
    service = ProjectSetupApplicationService(Mock(), inspector)

    with pytest.raises(ValueError, match="project_id"):
        service.plan_project_setup("", tmp_path)

    inspector.build_intelligence.assert_not_called()


def test_service_does_not_swallow_workflow_errors(tmp_path):
    inspector = Mock()
    inspector.build_intelligence.return_value = _mock_intelligence("demo", tmp_path)
    inspector.inspect_managed.return_value = (
        {"project_id": "demo", "project_path": str(tmp_path), "files": []},
        _mock_intelligence("demo", tmp_path),
    )
    workflow = Mock()
    workflow.run.side_effect = WorkflowExecutionError("council unavailable")
    service = ProjectSetupApplicationService(workflow, inspector)

    with pytest.raises(WorkflowExecutionError, match="council unavailable"):
        service.plan_project_setup("demo", tmp_path)


def test_service_preserves_existing_central_block_without_failed_terminal(tmp_path):
    inspector = Mock()
    intelligence = _mock_intelligence("demo", tmp_path)
    inspector.build_intelligence.return_value = intelligence
    inspector.inspect_managed.return_value = (
        {"project_id": "demo", "project_path": str(tmp_path), "files": []},
        intelligence,
    )
    workflow = Mock()
    trace = DiagnosticTrace(DiagnosticTraceStore(tmp_path / "trace.jsonl"))

    def blocked(*_args, **_kwargs):
        trace.record(
            "demo", "workflow_end", "blocked", "blocked",
            "Central planning policy blocked the workflow",
            related_result_id="workflow-end:demo:blocked",
        )
        raise WorkflowBlockedError("Planning was blocked safely.")

    workflow.run.side_effect = blocked
    service = ProjectSetupApplicationService(
        workflow, inspector,
        workflow_manager=WorkflowManager(tmp_path / "workflow-state.json"),
        diagnostic_trace=trace,
    )

    with pytest.raises(WorkflowBlockedError):
        service.plan_project_setup("demo", tmp_path)

    terminal = [event for event in trace.get_trace("demo") if event.phase == "workflow_end"]
    assert [event.status for event in terminal] == ["blocked"]


def test_service_has_no_direct_planner_council_materializer_or_executor_dependencies():
    source = Path("app/project_setup_application.py").read_text(encoding="utf-8")

    for forbidden_name in (
        "SetupPlanner",
        "EngineeringCouncil",
        "ToolchainMaterializer",
        "SetupExecutor",
    ):
        assert forbidden_name not in source
