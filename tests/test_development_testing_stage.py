from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.development_stage import DevelopmentRequest
from app.development_testing_stage import DevelopmentTestingStage, DevelopmentTestingResult
from app.verification import FAIL, PASS, VerificationResult, VerificationStepResult


def _request(tmp_path):
    return DevelopmentRequest("project", tmp_path, "add a feature")


def _stage(status="accepted", order=None):
    order = order if order is not None else []
    development_result = SimpleNamespace(status="success")
    test_changes = {"changes": [{"file": "test_feature.py", "action": "create", "content": ""}]}
    apply_result = {"applied": ["test_feature.py"], "skipped": []}
    test_result = SimpleNamespace(passed=True, timed_out=False)
    testing_result = SimpleNamespace(status=status, rework_request=object() if status == "rework_required" else None)

    development_stage = Mock()
    development_stage.run.side_effect = lambda request: (order.append("development"), development_result)[1]
    generator = Mock()
    generator.generate.side_effect = lambda request: (order.append("test_generation"), test_changes)[1]
    applier = Mock()
    applier.apply.side_effect = lambda changes: (order.append("test_apply"), apply_result)[1]
    factory = Mock(return_value=applier)
    runner = Mock()
    runner.run.side_effect = lambda request: (order.append("test_run"), test_result)[1]
    testing_stage = Mock()
    testing_stage.run.side_effect = lambda development, test: (order.append("testing_review"), testing_result)[1]

    return (
        DevelopmentTestingStage(development_stage, generator, factory, runner, testing_stage),
        development_stage,
        generator,
        factory,
        applier,
        runner,
        testing_stage,
        development_result,
        test_changes,
        apply_result,
        test_result,
        testing_result,
    )


def test_runs_canonical_stages_once_in_order_and_preserves_real_results(tmp_path):
    order = []
    values = _stage(order=order)
    stage, development, generator, factory, applier, runner, testing, dev_result, changes, apply_result, test_result, testing_result = values
    request = _request(tmp_path)

    result = stage.run(request)

    assert isinstance(result, DevelopmentTestingResult)
    assert order == ["development", "test_generation", "test_apply", "test_run", "testing_review"]
    development.run.assert_called_once_with(request)
    generator.generate.assert_called_once_with(request)
    factory.assert_called_once_with(tmp_path)
    applier.apply.assert_called_once_with(changes)
    runner.run.assert_called_once()
    assert runner.run.call_args.args[0].project_root == tmp_path
    testing.run.assert_called_once_with(dev_result, test_result)
    assert result.development_result is dev_result
    assert result.test_changes is changes
    assert result.apply_result is apply_result
    assert result.test_result is test_result
    assert result.testing_stage_result is testing_result
    assert result.status == "accepted"


def test_uses_the_same_project_root_for_test_changes_and_test_execution(tmp_path):
    values = _stage()
    stage, _, _, factory, _, runner, *_ = values

    stage.run(_request(tmp_path))

    assert factory.call_args.args[0] == tmp_path
    assert runner.run.call_args.args[0].project_root == tmp_path


def test_rework_result_is_returned_without_retrying_any_stage(tmp_path):
    values = _stage(status="rework_required")
    stage, development, generator, _, applier, runner, testing, *_, testing_result = values

    result = stage.run(_request(tmp_path))

    assert result.status == "rework_required"
    assert result.testing_stage_result.rework_request is testing_result.rework_request
    for call in (development.run, generator.generate, applier.apply, runner.run, testing.run):
        assert call.call_count == 1


def test_review_failed_is_returned_without_accepted_fallback_or_retry(tmp_path):
    values = _stage(status="review_failed")
    stage, development, generator, _, applier, runner, testing, *_, testing_result = values

    result = stage.run(_request(tmp_path))

    assert result.status == "review_failed"
    for call in (development.run, generator.generate, applier.apply, runner.run, testing.run):
        assert call.call_count == 1


@pytest.mark.parametrize("failing_component", ["development", "generator", "applier", "runner"])
def test_upstream_failure_stops_without_synthesizing_results(tmp_path, failing_component):
    values = _stage()
    stage, development, generator, _, applier, runner, testing, *_ = values
    failures = {
        "development": development.run,
        "generator": generator.generate,
        "applier": applier.apply,
        "runner": runner.run,
    }
    failures[failing_component].side_effect = RuntimeError(f"{failing_component} failed")

    with pytest.raises(RuntimeError, match=f"{failing_component} failed"):
        stage.run(_request(tmp_path))

    expected_calls = {
        "development": (1, 0, 0, 0, 0),
        "generator": (1, 1, 0, 0, 0),
        "applier": (1, 1, 1, 0, 0),
        "runner": (1, 1, 1, 1, 0),
    }[failing_component]
    actual_calls = (development.run.call_count, generator.generate.call_count, applier.apply.call_count, runner.run.call_count, testing.run.call_count)
    assert actual_calls == expected_calls


# ---------------------------------------------------------------------
# CLAUDE-ADC-REWORK-DIAGNOSTIC-FIDELITY-FIX-007/008: the verification_registry
# branch synthesizes a TestResult from a VerificationResult. Previously
# this discarded every failing step's real stdout/stderr/return_code (and,
# separately, its `diagnostics`/`error_category` -- the only explanation
# BLOCKED/EXECUTION_ERROR steps ever populate) and kept only a bare
# "area/step: status" summary line -- these tests prove the real,
# actionable per-step evidence now survives into the TestResult that
# feeds TestingStage/ControlledReworkStage, for any verifier kind, and
# that multiple failing steps remain individually attributable rather
# than flattened into one ambiguous command/return_code.
# ---------------------------------------------------------------------

def _verification_stage(verification_result, project_test_runner=None):
    development_stage = Mock()
    development_stage.run.return_value = SimpleNamespace(status="success")
    generator = Mock()
    generator.generate.return_value = {"changes": [{"file": "test_feature.py", "action": "create", "content": "x"}]}
    applier = Mock()
    applier.apply.return_value = {"applied": ["test_feature.py"], "skipped": []}
    factory = Mock(return_value=applier)
    runner = project_test_runner if project_test_runner is not None else Mock()
    testing_stage = Mock()
    testing_stage.run.side_effect = lambda development, test: SimpleNamespace(
        status="accepted" if test.passed else "rework_required", rework_request=None,
    )
    registry = Mock()
    registry.execute_plan.return_value = verification_result
    inspector = Mock()
    inspector.build_intelligence.return_value = None

    stage = DevelopmentTestingStage(
        development_stage, generator, factory, runner, testing_stage,
        verification_registry=registry, project_inspector=inspector,
    )
    return stage, runner, registry


def test_verification_failure_preserves_real_step_stdout_stderr_return_code(tmp_path):
    step = VerificationStepResult(
        step_id="validate", area="root", status=FAIL.value,
        verification_kind="validate", runner_type="generic_config_validator",
        passed=False, return_code=2,
        stdout="Failed config: actionable message", stderr="stderr detail",
        command=("tool", "validate", "config"), timed_out=False,
    )
    verification_result = VerificationResult(run_id="r", steps=(step,), aggregate_status=FAIL.value)
    stage, runner, registry = _verification_stage(verification_result)

    result = stage.run(_request(tmp_path))

    runner.run.assert_not_called()
    test_result = result.test_result
    assert test_result.passed is False
    assert test_result.return_code == 2
    assert test_result.timed_out is False
    assert test_result.stdout == "Failed config: actionable message"
    assert test_result.stderr == "stderr detail"
    assert test_result.command == ("tool", "validate", "config")

    # A single failing step is a faithful, unambiguous case: the scalar
    # fields above already describe it exactly, but step_failures still
    # carries the same evidence explicitly for attribution.
    assert len(test_result.step_failures) == 1
    only = test_result.step_failures[0]
    assert only.area == "root"
    assert only.step_id == "validate"
    assert only.return_code == 2
    assert only.stdout == "Failed config: actionable message"
    assert only.stderr == "stderr detail"


def test_verification_multiple_failures_remain_individually_attributable(tmp_path):
    passing_step = VerificationStepResult(
        step_id="unit", area="root", status=PASS.value, verification_kind="test",
        runner_type="pytest", passed=True, return_code=0,
        stdout="ok", stderr="", command=("pytest",), timed_out=False,
    )
    first_failure = VerificationStepResult(
        step_id="validate", area="root", status=FAIL.value, verification_kind="validate",
        runner_type="generic_config_validator", passed=False, return_code=2,
        stdout="first failure", stderr="first stderr", command=("tool", "validate"), timed_out=False,
    )
    second_failure = VerificationStepResult(
        step_id="compile", area="root", status="blocked", verification_kind="compile",
        runner_type="generic_builder", passed=False, return_code=None,
        stdout="", stderr="", command=(), timed_out=False,
        diagnostics="Blocked by failed dependency: root-validate",
    )
    verification_result = VerificationResult(
        run_id="r", steps=(passing_step, first_failure, second_failure), aggregate_status=FAIL.value,
    )
    stage, runner, registry = _verification_stage(verification_result)

    result = stage.run(_request(tmp_path))

    test_result = result.test_result
    assert test_result.passed is False
    # No single step's return_code may be presented as if it described
    # every failure -- the scalar aggregate is a neutral marker instead.
    assert test_result.return_code == 1
    assert test_result.command == ("verification",)

    failures = test_result.step_failures
    assert len(failures) == 2
    assert failures[0].step_id == "validate"
    assert failures[0].return_code == 2
    assert failures[0].stdout == "first failure"
    assert failures[0].stderr == "first stderr"
    assert failures[1].step_id == "compile"
    assert failures[1].return_code is None
    assert failures[1].diagnostics == "Blocked by failed dependency: root-validate"


def test_verification_all_steps_passing_yields_a_passed_test_result(tmp_path):
    step = VerificationStepResult(
        step_id="unit", area="root", status=PASS.value, verification_kind="test",
        runner_type="pytest", passed=True, return_code=0,
        stdout="", stderr="", command=("pytest",), timed_out=False,
    )
    verification_result = VerificationResult(run_id="r", steps=(step,), aggregate_status=PASS.value)
    stage, runner, registry = _verification_stage(verification_result)

    result = stage.run(_request(tmp_path))

    runner.run.assert_not_called()
    assert result.test_result.passed is True
    assert result.test_result.return_code == 0


def test_verification_no_executable_steps_falls_back_to_project_test_runner(tmp_path):
    step = VerificationStepResult(
        step_id="unit", area="root", status="not_applicable", verification_kind="test",
        runner_type="none", passed=True, return_code=None,
        stdout="", stderr="", command=(), timed_out=False,
    )
    verification_result = VerificationResult(run_id="r", steps=(step,), aggregate_status="not_applicable")
    fallback_result = SimpleNamespace(passed=True, timed_out=False)
    runner = Mock()
    runner.run.return_value = fallback_result
    stage, runner, registry = _verification_stage(verification_result, project_test_runner=runner)

    result = stage.run(_request(tmp_path))

    runner.run.assert_called_once()
    assert result.test_result is fallback_result
