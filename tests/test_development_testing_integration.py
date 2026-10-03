from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, Mock

import pytest

from app.dev_workflow import DevelopmentWorkflow, SetupDevelopmentTestingResult, WorkflowExecutionError
from app.project_setup_application import ProjectSetupApplicationService
from app.requirement_model import SetupEffect, SetupPlan, SetupStep
from app.setup_execution_state import SetupExecutionStateStore
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
                setup_effect=SetupEffect.PYTHON_PACKAGE_INSTALL,
            ),
        ),
    )


def _workflow(stage, success=True):
    import tempfile

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
        execution_state_store=SetupExecutionStateStore(
            Path(tempfile.mkdtemp()) / "exec-state.json"
        ),
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

    result = workflow.execute_approved_and_run_development(_plan(), SimpleNamespace(project_path=None))

    assert result.status == status
    executor.execute.assert_called_once()
    stage.run.assert_called_once()


def test_terminal_rework_exception_traces_preserved_initial_result_before_reraising(tmp_path):
    """CLAUDE-E2E-NIO-007A: a real Real-System-E2E lost the last
    meaningful engineering failure (a real ESPHome validate/compile
    failure) that caused rework to be attempted, the moment the rework
    attempt's own provider call raised a terminal exception. The
    preserved initial_result/rework_request ControlledReworkStage.run()
    attaches to such an exception must still be traced here, into the
    real DiagnosticTrace, before the original exception is re-raised
    completely unchanged."""
    from app.diagnostic_trace import DiagnosticTrace, DiagnosticTraceStore
    from app.testing_stage import ReworkRequest

    initial_development = SimpleNamespace(status="success", applied_changes=None)
    initial_test = SimpleNamespace(timed_out=False, passed=False, return_code=1)
    rework_request = ReworkRequest(
        reason="esphome-validate failed and esphome-compile was blocked",
        diagnostics="esphome-validate failed and esphome-compile was blocked",
        development_result=initial_development, test_result=initial_test,
    )
    initial_result = SimpleNamespace(
        status="rework_required",
        development_result=initial_development,
        test_changes={"changes": []},
        apply_result={"applied": [], "skipped": []},
        test_result=initial_test,
        testing_stage_result=SimpleNamespace(status="rework_required", rework_request=rework_request),
    )
    provider_error = RuntimeError("Connection error")
    provider_error.controlled_rework_initial_result = initial_result
    provider_error.controlled_rework_request = rework_request

    stage = Mock()
    stage.run.side_effect = provider_error
    workflow, executor = _workflow(stage)
    trace = DiagnosticTrace(DiagnosticTraceStore(tmp_path / "trace.jsonl"))
    workflow.set_diagnostic_trace(trace)

    with pytest.raises(RuntimeError, match="Connection error"):
        workflow.execute_approved_and_run_development(
            _plan(), SimpleNamespace(project_path=None, run_id="run-1"),
        )

    events = trace.get_trace("run-1")
    assert any(
        event.phase == "controlled_rework" and event.status == "failed"
        and "esphome-validate failed and esphome-compile was blocked" in event.summary
        for event in events
    )
    assert any(
        event.phase == "controlled_rework"
        and event.details.get("diagnostics") == "esphome-validate failed and esphome-compile was blocked"
        for event in events
    )
    # The precursor testing/diagnosis_review cycle itself is also traced.
    assert any(event.phase == "diagnosis_review" and event.status == "rework_required" for event in events)


def test_unapproved_setup_never_starts_development_testing():
    stage = Mock()
    workflow, executor = _workflow(stage)

    with pytest.raises(WorkflowExecutionError, match="not approved"):
        workflow.execute_approved_and_run_development(_plan("pending_approval"), SimpleNamespace(project_path=None))

    executor.execute.assert_not_called()
    stage.run.assert_not_called()


def test_failed_setup_never_starts_development_testing():
    stage = Mock()
    workflow, executor = _workflow(stage, success=False)

    with pytest.raises(WorkflowExecutionError, match="did not complete successfully"):
        workflow.execute_approved_and_run_development(_plan(), SimpleNamespace(project_path=None))

    executor.execute.assert_called_once()
    stage.run.assert_not_called()


def test_development_testing_error_fails_fast_without_synthetic_result():
    stage = Mock()
    stage.run.side_effect = RuntimeError("runner unavailable")
    workflow, executor = _workflow(stage)

    with pytest.raises(RuntimeError, match="runner unavailable"):
        workflow.execute_approved_and_run_development(_plan(), SimpleNamespace(project_path=None))

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

    result = workflow.execute_approved_and_run_development(_plan(), SimpleNamespace(project_path=None))

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
