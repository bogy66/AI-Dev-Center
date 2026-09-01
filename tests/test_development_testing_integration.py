from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, Mock

import pytest

from app.dev_workflow import DevelopmentWorkflow, SetupDevelopmentTestingResult, WorkflowExecutionError
from app.project_setup_application import ProjectSetupApplicationService
from app.requirement_model import SetupPlan, SetupStep
from app.setup_executor import ExecutionResult
from app.workflow_manager import WorkflowManager


def _plan(status="approved"):
    return SetupPlan(
        id="plan-1",
        project_id="project",
        status=status,
        steps=(
            SetupStep(
                id="step-1",
                requirement_id="requirement-1",
                action="install",
                install_method="python_package",
                package="example-package",
                is_approved=status == "approved",
            ),
        ),
    )


def _workflow(stage, success=True):
    executor = Mock()
    executor.execute.return_value = ExecutionResult(
        step_id="step-1",
        success=success,
        message="ok" if success else "failed",
    )
    return DevelopmentWorkflow(
        discovery=Mock(),
        validator=Mock(),
        preflight=Mock(),
        executor=executor,
        controlled_rework_stage=stage,
    ), executor


def test_successful_approved_setup_runs_development_testing_once():
    stage = Mock()
    development_testing_result = SimpleNamespace(status="accepted")
    stage.run.return_value = SimpleNamespace(
        status="accepted",
        final_result=development_testing_result,
    )
    workflow, executor = _workflow(stage)
    request = SimpleNamespace(project_path="/project", task="add feature")

    result = workflow.execute_approved_and_run_development(_plan(), request)

    executor.execute.assert_called_once()
    stage.run.assert_called_once_with(request)
    assert result.setup_execution_results[0].success is True
    assert result.development_testing_result is development_testing_result
    assert result.status == "accepted"


@pytest.mark.parametrize("status", ["rework_required", "review_failed"])
def test_canonical_testing_status_is_returned_without_retry(status):
    stage = Mock()
    stage.run.return_value = SimpleNamespace(
        status=status,
        final_result=SimpleNamespace(status=status),
    )
    workflow, executor = _workflow(stage)

    result = workflow.execute_approved_and_run_development(_plan(), Mock())

    assert result.status == status
    executor.execute.assert_called_once()
    stage.run.assert_called_once()


def test_unapproved_setup_never_starts_development_testing():
    stage = Mock()
    workflow, executor = _workflow(stage)

    with pytest.raises(WorkflowExecutionError, match="not approved"):
        workflow.execute_approved_and_run_development(_plan("pending_approval"), Mock())

    executor.execute.assert_not_called()
    stage.run.assert_not_called()


def test_failed_setup_never_starts_development_testing():
    stage = Mock()
    workflow, executor = _workflow(stage, success=False)

    with pytest.raises(WorkflowExecutionError, match="did not complete successfully"):
        workflow.execute_approved_and_run_development(_plan(), Mock())

    executor.execute.assert_called_once()
    stage.run.assert_not_called()


def test_development_testing_error_fails_fast_without_synthetic_result():
    stage = Mock()
    stage.run.side_effect = RuntimeError("runner unavailable")
    workflow, executor = _workflow(stage)

    with pytest.raises(RuntimeError, match="runner unavailable"):
        workflow.execute_approved_and_run_development(_plan(), Mock())

    executor.execute.assert_called_once()
    stage.run.assert_called_once()


def test_workflow_uses_one_controlled_rework_cycle_when_the_initial_stage_requires_it():
    initial = SimpleNamespace(
        status="rework_required",
        development_result=Mock(),
        test_result=Mock(),
        testing_stage_result=SimpleNamespace(
            rework_request=SimpleNamespace(
                reason="tests require rework",
                diagnostics="failure",
            ),
        ),
    )
    final = SimpleNamespace(status="accepted")
    stage = Mock()
    stage.run.side_effect = [initial, final]
    executor = Mock()
    executor.execute.return_value = ExecutionResult("step-1", True, "ok")
    workflow = DevelopmentWorkflow(
        discovery=Mock(),
        validator=Mock(),
        preflight=Mock(),
        executor=executor,
        development_testing_stage=stage,
    )

    result = workflow.execute_approved_and_run_development(_plan(), Mock())

    assert result.status == "accepted"
    executor.execute.assert_called_once()
    assert stage.run.call_count == 2


def test_outer_workflow_uses_only_the_development_testing_boundary():
    source = Path("app/dev_workflow.py").read_text(encoding="utf-8")

    for forbidden_name in (
        "DevelopmentStage(",
        "TestChangeGenerator(",
        "DeveloperFileApplier(",
        "ProjectTestRunner(",
        "TestingStage(",
    ):
        assert forbidden_name not in source


def test_application_service_preserves_explicit_project_root_for_stage_request(tmp_path):
    workflow = Mock()
    expected = SetupDevelopmentTestingResult(
        (), SimpleNamespace(status="review_failed", final_result=SimpleNamespace()),
    )
    workflow.execute_approved_and_run_development.return_value = expected
    service = ProjectSetupApplicationService(
        workflow, Mock(), WorkflowManager(tmp_path / "workflow_state.json")
    )
    plan = _plan()

    result = service.execute_approved_setup_and_development(
        plan,
        "project",
        tmp_path,
        "add feature",
    )

    assert result.controlled_rework_result is expected.controlled_rework_result
    workflow.execute_approved_and_run_development.assert_called_once_with(
        plan,
        ANY,
    )
    request = workflow.execute_approved_and_run_development.call_args.args[1]
    assert request.project_id == "project"
    assert request.project_path == tmp_path
    assert request.task == "add feature"
