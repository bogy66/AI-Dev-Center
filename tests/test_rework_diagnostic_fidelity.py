"""Regressions for CLAUDE-ADC-REWORK-DIAGNOSTIC-FIDELITY-FIX-007/008.

Real-System-E2E showed a rework Developer receiving only the
DiagnosisReviewer's own paraphrase of a failure ("configuration
validation failed") while the actual, actionable evidence (the real
command, return code, stdout, stderr) from the previous controlled test
run never reached it. FIX-007 closed the plumbing gap for a single
failing step; an independent review then found two more gaps FIX-008
closes here: BLOCKED/EXECUTION_ERROR steps -- whose only explanation
lives in `diagnostics`, since their stdout/stderr are empty by
construction -- were silently dropped, and multiple failing steps were
flattened into one ambiguous command/return_code line. These tests prove
the deterministic evidence (including diagnostics-only failures) now
reaches the rework contract, stays individually attributable across
multiple failing steps, is bounded/truncated safely, remains
supplemental to (never a replacement for) the reviewer's interpretation,
and that the surrounding one-rework/fail-closed architecture is
unchanged. Nothing here is specific to any one verifier (ESPHome or
otherwise) -- a generic "config validator" stand-in is used throughout.
"""
import json
from types import SimpleNamespace
from unittest.mock import Mock

from app.controlled_rework_stage import ControlledReworkStage, ReworkDevelopmentRequest
from app.developer_file_applier import DeveloperFileApplier
from app.development_stage import DeveloperAgent, DevelopmentRequest, DevelopmentStage
from app.development_testing_stage import DevelopmentTestingStage, DevelopmentTestingResult
from app.test_change_generator import TestChangeGenerator
from app.testing_stage import (
    DiagnosisReviewer, ReviewDecision, ReviewResult, ReworkRequest, TestingStage,
)
from app.project_test_runner import TestResult
from app.verification import FAIL, VerificationResult, VerificationStepResult


def _previous_test_result(**overrides):
    defaults = dict(
        passed=False,
        return_code=2,
        stdout="Failed config: remove the deprecated key and use the new component block instead.",
        stderr="ERROR: schema violation at line 4",
        command=("generic-tool", "validate", "config.file"),
        timed_out=False,
    )
    defaults.update(overrides)
    return TestResult(**defaults)


def _rework_request(previous_test_result, diagnostics="configuration validation failed"):
    return ReworkDevelopmentRequest(
        original_request=DevelopmentRequest("project", "/project", "Build a thing"),
        previous_development_result=object(),
        previous_test_result=previous_test_result,
        previous_testing_stage_result=object(),
        rework_request=ReworkRequest(
            reason="tests require rework",
            diagnostics=diagnostics,
            development_result=object(),
            test_result=previous_test_result,
        ),
    )


# ---------------------------------------------------------------------
# A: deterministic failure evidence reaches the Developer task
# ---------------------------------------------------------------------

def test_a_previous_test_result_evidence_reaches_the_rework_developer_task():
    previous = _previous_test_result()
    request = _rework_request(previous)

    task = request.task

    assert "Failed config: remove the deprecated key" in task
    assert "ERROR: schema violation at line 4" in task
    assert "Return code: 2" in task


# ---------------------------------------------------------------------
# B: a generic reviewer summary does not erase the specific failure
# ---------------------------------------------------------------------

def test_b_generic_reviewer_summary_does_not_erase_specific_deterministic_failure():
    previous = _previous_test_result()
    request = _rework_request(previous, diagnostics="configuration validation failed")

    task = request.task

    assert "configuration validation failed" in task
    assert "Failed config: remove the deprecated key" in task


# ---------------------------------------------------------------------
# C: stdout / stderr remain distinguishable
# ---------------------------------------------------------------------

def test_c_stdout_and_stderr_remain_distinguishable_in_the_rework_task():
    previous = _previous_test_result(stdout="STDOUT_MARKER", stderr="STDERR_MARKER")
    request = _rework_request(previous)

    task = request.task
    stdout_section = task.index("--- stdout ---")
    stderr_section = task.index("--- stderr ---")
    stdout_marker = task.index("STDOUT_MARKER")
    stderr_marker = task.index("STDERR_MARKER")

    assert stdout_section < stdout_marker < stderr_section < stderr_marker


# ---------------------------------------------------------------------
# D: command, return_code and timed_out preserved
# ---------------------------------------------------------------------

def test_d_command_return_code_and_timed_out_preserved_in_the_rework_task():
    previous = _previous_test_result(return_code=2, timed_out=True, command=("tool", "a", "b"))
    request = _rework_request(previous)

    task = request.task

    assert "Return code: 2" in task
    assert "Timed out: True" in task
    assert "tool a b" in task


# ---------------------------------------------------------------------
# E: very large diagnostic output is truncated deterministically/safely
# ---------------------------------------------------------------------

def test_e_very_large_diagnostic_output_is_truncated_deterministically_and_safely():
    previous = _previous_test_result(stdout="Z" * 200_000, stderr="Y" * 200_000)
    request = _rework_request(previous)

    first = request.task
    second = request.task

    assert first == second, "the same rework request must render the same task twice"
    assert len(first) < 20_000, "task text must be bounded, not proportional to raw output size"


# ---------------------------------------------------------------------
# F: passing tests do not create a rework request
# ---------------------------------------------------------------------

def test_f_passing_test_result_does_not_create_a_rework_request():
    reviewer = Mock()
    reviewer.review.return_value = ReviewResult(ReviewDecision.ACCEPTED, "all good")
    passing = SimpleNamespace(passed=True, timed_out=False)

    result = TestingStage(reviewer).run("development", passing)

    assert result.status == "accepted"
    assert result.rework_request is None


# ---------------------------------------------------------------------
# G / H: one-rework maximum, fail-closed on a second failure
# ---------------------------------------------------------------------

def _development_testing_result(status, test_result):
    review = SimpleNamespace(status=status, rework_request=None)
    if status == "rework_required":
        review.rework_request = ReworkRequest(
            reason="tests require rework",
            diagnostics="configuration validation failed",
            development_result=object(),
            test_result=test_result,
        )
    return DevelopmentTestingResult(
        development_result=object(),
        test_changes={"changes": []},
        apply_result={"applied": [], "skipped": []},
        test_result=test_result,
        testing_stage_result=review,
    )


def test_g_controlled_rework_runs_at_most_one_rework_cycle():
    failing = _previous_test_result()
    initial = _development_testing_result("rework_required", failing)
    rework = _development_testing_result("rework_required", failing)
    stage = Mock()
    stage.run.side_effect = [initial, rework]

    result = ControlledReworkStage(stage).run(DevelopmentRequest("project", "/project", "Build a thing"))

    assert stage.run.call_count == 2
    assert result.rework_executed is True


def test_h_second_failure_after_rework_still_terminates_fail_closed():
    failing = _previous_test_result()
    initial = _development_testing_result("rework_required", failing)
    rework_again_failed = _development_testing_result("rework_required", failing)
    stage = Mock()
    stage.run.side_effect = [initial, rework_again_failed]

    result = ControlledReworkStage(stage).run(DevelopmentRequest("project", "/project", "Build a thing"))

    assert result.status == "rework_required"
    assert result.rework_result is rework_again_failed
    assert stage.run.call_count == 2, "a second failure must not trigger a third cycle"


# ---------------------------------------------------------------------
# Requirement 6: full productive boundary integration
#
# DevelopmentTestingStage -> TestingStage -> ControlledReworkStage ->
# rework DevelopmentStage, wired for real (only the LLM executor and the
# verification registry are faked -- no network, no live LLM).
# ---------------------------------------------------------------------

class _FakeExecutor:
    """Deterministic stand-in for ProviderAgentExecutor. Records every
    call so the test can inspect exactly what the rework Developer was
    asked to do."""

    def __init__(self):
        self.calls = []
        self._developer_calls = 0
        self._tester_calls = 0

    def run(self, role, content, context, role_again):
        self.calls.append((role, content, context, role_again))
        if role == "developer":
            self._developer_calls += 1
            return json.dumps({
                "changes": [{
                    "file": f"generated_{self._developer_calls}.py",
                    "action": "create",
                    "content": "print('generated')",
                }],
                "tests": [],
            })
        if role == "tester":
            self._tester_calls += 1
            return json.dumps({
                "changes": [{
                    "file": f"generated_test_{self._tester_calls}.py",
                    "action": "create",
                    "content": "def test_generated(): pass",
                }],
                "tests": [],
            })
        if role == "reviewer":
            return json.dumps({
                "decision": "rework_required",
                "summary": "configuration validation failed",
            })
        raise AssertionError(f"unexpected role: {role}")

    def calls_for(self, role):
        return [c for c in self.calls if c[0] == role]


class _FakeVerificationRegistry:
    """Always reports one concrete, actionable failure -- generic, not
    tied to any specific verifier technology."""

    def __init__(self, result):
        self._result = result
        self.execute_plan_calls = 0

    def execute_plan(self, plan):
        self.execute_plan_calls += 1
        return self._result


class _FakeProjectInspector:
    def build_intelligence(self, project_path):
        return None


def _failing_verification_result():
    step = VerificationStepResult(
        step_id="validate",
        area="root",
        status=FAIL.value,
        verification_kind="validate",
        runner_type="generic_config_validator",
        passed=False,
        return_code=2,
        stdout="Failed config: remove the deprecated key and use the new component block instead.",
        stderr="ERROR: config schema violation at line 4",
        command=("generic-tool", "validate", "config.file"),
        timed_out=False,
    )
    return VerificationResult(run_id="run-1", steps=(step,), aggregate_status=FAIL.value)


def test_productive_rework_boundary_preserves_deterministic_evidence_and_reviewer_interpretation(tmp_path):
    executor = _FakeExecutor()
    development_stage = DevelopmentStage(DeveloperAgent(executor))
    test_change_generator = TestChangeGenerator(executor)
    project_test_runner = Mock()
    testing_stage = TestingStage(DiagnosisReviewer(executor))
    verification_registry = _FakeVerificationRegistry(_failing_verification_result())
    project_inspector = _FakeProjectInspector()

    development_testing_stage = DevelopmentTestingStage(
        development_stage, test_change_generator, DeveloperFileApplier,
        project_test_runner, testing_stage,
        verification_registry=verification_registry, project_inspector=project_inspector,
    )
    controlled_rework_stage = ControlledReworkStage(development_testing_stage)
    request = DevelopmentRequest("project", tmp_path, "Create a generic validated config project")

    result = controlled_rework_stage.run(request)

    # No live LLM/network: the fake registry/executor never touch either.
    project_test_runner.run.assert_not_called()

    # One initial cycle, exactly one rework cycle -- never a third.
    assert verification_registry.execute_plan_calls == 2
    developer_calls = executor.calls_for("developer")
    reviewer_calls = executor.calls_for("reviewer")
    assert len(developer_calls) == 2
    assert len(reviewer_calls) == 2

    # Fail-closed: the rework cycle also failed, so the boundary stops
    # at rework_required rather than retrying again.
    assert result.rework_executed is True
    assert result.status == "rework_required"

    rework_developer_prompt = developer_calls[1][1]

    # Deterministic evidence from the actual failing verifier step.
    assert "Failed config: remove the deprecated key" in rework_developer_prompt
    assert "ERROR: config schema violation at line 4" in rework_developer_prompt
    assert "Return code: 2" in rework_developer_prompt
    assert "Timed out: False" in rework_developer_prompt

    # The reviewer's generic interpretation is present too, but supplemental --
    # it never replaced the specific evidence above.
    assert "configuration validation failed" in rework_developer_prompt


# ---------------------------------------------------------------------
# FIX-008 productive boundary regression: the initial VerificationResult
# now contains a FAIL step (with stdout/stderr) AND a dependent BLOCKED
# step (diagnostics only) AND a sibling EXECUTION_ERROR step -- exactly
# the shape of the triggering Real-System-E2E's own "validate failed,
# compile blocked" sequence, generalized with one more failure mode.
# ---------------------------------------------------------------------

def _mixed_failure_verification_result():
    validate_step = VerificationStepResult(
        step_id="validate", area="root", status=FAIL.value,
        verification_kind="validate", runner_type="generic_config_validator",
        passed=False, return_code=2,
        stdout="Failed config: remove the deprecated key and use the new component block instead.",
        stderr="ERROR: config schema violation at line 4",
        command=("generic-tool", "validate", "config.file"), timed_out=False,
    )
    compile_step = VerificationStepResult(
        step_id="compile", area="root", status="blocked",
        verification_kind="compile", runner_type="generic_builder",
        passed=False,
        diagnostics="Blocked by failed dependency: root-validate",
    )
    flash_step = VerificationStepResult(
        step_id="flash", area="root", status="execution_error",
        verification_kind="flash", runner_type="generic_flasher",
        passed=False, error_category="OSError",
        diagnostics="device not found on /dev/ttyUSB0",
    )
    return VerificationResult(
        run_id="run-1", steps=(validate_step, compile_step, flash_step), aggregate_status=FAIL.value,
    )


def test_productive_rework_boundary_preserves_evidence_from_every_failing_step(tmp_path):
    executor = _FakeExecutor()
    development_stage = DevelopmentStage(DeveloperAgent(executor))
    test_change_generator = TestChangeGenerator(executor)
    project_test_runner = Mock()
    testing_stage = TestingStage(DiagnosisReviewer(executor))
    verification_registry = _FakeVerificationRegistry(_mixed_failure_verification_result())
    project_inspector = _FakeProjectInspector()

    development_testing_stage = DevelopmentTestingStage(
        development_stage, test_change_generator, DeveloperFileApplier,
        project_test_runner, testing_stage,
        verification_registry=verification_registry, project_inspector=project_inspector,
    )
    controlled_rework_stage = ControlledReworkStage(development_testing_stage)
    request = DevelopmentRequest("project", tmp_path, "Create a generic validated config project")

    result = controlled_rework_stage.run(request)

    project_test_runner.run.assert_not_called()
    assert result.rework_executed is True
    assert result.status == "rework_required"

    developer_calls = executor.calls_for("developer")
    assert len(developer_calls) == 2
    rework_developer_prompt = developer_calls[1][1]

    # The FAIL step's real stdout/stderr/return_code.
    assert "Failed config: remove the deprecated key" in rework_developer_prompt
    assert "ERROR: config schema violation at line 4" in rework_developer_prompt

    # The BLOCKED step's ONLY evidence -- its diagnostics -- must still
    # arrive, even though its stdout/stderr are both empty.
    assert "Blocked by failed dependency: root-validate" in rework_developer_prompt

    # The EXECUTION_ERROR step's error_category and diagnostics.
    assert "OSError" in rework_developer_prompt
    assert "device not found on /dev/ttyUSB0" in rework_developer_prompt

    # Each failing step remains its own, separately identifiable record.
    validate_idx = rework_developer_prompt.index("step_id=validate")
    compile_idx = rework_developer_prompt.index("step_id=compile")
    flash_idx = rework_developer_prompt.index("step_id=flash")
    assert validate_idx < compile_idx < flash_idx

    # The reviewer's generic interpretation remains present, supplementally.
    assert "configuration validation failed" in rework_developer_prompt
