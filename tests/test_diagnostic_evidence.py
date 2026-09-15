from types import SimpleNamespace

import pytest

from app.diagnostic_evidence import format_test_result_evidence
from app.project_test_runner import StepFailureEvidence, TestResult


def _result(**overrides):
    defaults = dict(
        passed=False,
        return_code=2,
        stdout="Failed config: something actionable went wrong",
        stderr="context: line 3 invalid",
        command=("some-tool", "check", "config.file"),
        timed_out=False,
    )
    defaults.update(overrides)
    return TestResult(**defaults)


def test_formatter_is_deterministic_for_the_same_input():
    result = _result()

    first = format_test_result_evidence(result)
    second = format_test_result_evidence(result)

    assert first == second


def test_command_return_code_and_timed_out_are_preserved():
    result = _result(return_code=2, timed_out=True, command=("tool", "arg1", "arg2"))

    rendered = format_test_result_evidence(result)

    assert "Return code: 2" in rendered
    assert "Timed out: True" in rendered
    assert "tool arg1 arg2" in rendered


def test_stdout_and_stderr_remain_distinguishable():
    result = _result(stdout="ACTIONABLE_STDOUT_MARKER", stderr="CONTEXTUAL_STDERR_MARKER")

    rendered = format_test_result_evidence(result)
    stdout_marker_idx = rendered.index("ACTIONABLE_STDOUT_MARKER")
    stderr_marker_idx = rendered.index("CONTEXTUAL_STDERR_MARKER")
    stdout_section_idx = rendered.index("--- stdout ---")
    stderr_section_idx = rendered.index("--- stderr ---")

    assert stdout_section_idx < stdout_marker_idx < stderr_section_idx
    assert stderr_section_idx < stderr_marker_idx


def test_large_diagnostic_output_is_truncated_deterministically_and_boundedly():
    huge_stdout = "X" * 500_000
    result = _result(stdout=huge_stdout, stderr="Y" * 500_000)

    rendered_once = format_test_result_evidence(result, max_field_chars=1000)
    rendered_again = format_test_result_evidence(result, max_field_chars=1000)

    assert rendered_once == rendered_again, "truncation must be deterministic"
    assert len(rendered_once) < 5000, "output must be bounded, not proportional to input size"
    assert "...[truncated]..." in rendered_once
    # Some of both the earliest and latest failure text must still be present.
    assert "X" in rendered_once
    assert rendered_once.count("X") < len(huge_stdout)


def test_missing_test_result_renders_a_safe_placeholder():
    rendered = format_test_result_evidence(None)

    assert "no previous test evidence" in rendered


def test_duck_typed_object_missing_fields_does_not_crash():
    partial = SimpleNamespace(stdout="only stdout present")

    rendered = format_test_result_evidence(partial)

    assert "only stdout present" in rendered
    assert "Return code: None" in rendered
    assert "Timed out: False" in rendered
    assert "(no command recorded)" in rendered


def test_no_command_recorded_placeholder_when_command_is_empty():
    result = _result(command=())

    rendered = format_test_result_evidence(result)

    assert "(no command recorded)" in rendered


# ---------------------------------------------------------------------
# CLAUDE-ADC-REWORK-DIAGNOSTIC-FIDELITY-FIX-008
# ---------------------------------------------------------------------

def _step(**overrides):
    defaults = dict(
        area="root", step_id="step", runner_type="generic_runner",
        verification_kind="check", status="fail",
        command=("tool", "check"), return_code=1, timed_out=False,
        error_category=None, diagnostics="", stdout="", stderr="",
    )
    defaults.update(overrides)
    return StepFailureEvidence(**defaults)


def _result_with_steps(steps, **overrides):
    defaults = dict(passed=False, return_code=1, stdout="", stderr="", command=("verification",), timed_out=False)
    defaults.update(overrides)
    return TestResult(**defaults, step_failures=tuple(steps))


# Regression 2: a BLOCKED step with empty stdout/stderr but diagnostics.

def test_blocked_step_diagnostics_only_evidence_is_not_lost():
    blocked = _step(
        area="root", step_id="compile", status="blocked",
        command=(), return_code=None, stdout="", stderr="",
        diagnostics="Blocked by failed dependency: root-validate",
    )
    result = _result_with_steps([blocked])

    rendered = format_test_result_evidence(result)

    assert "Blocked by failed dependency: root-validate" in rendered
    assert "status=blocked" in rendered


# Regression 3: an EXECUTION_ERROR step with error_category + diagnostics, no stdout/stderr.

def test_execution_error_step_preserves_error_category_and_diagnostics():
    execution_error = _step(
        area="root", step_id="flash", status="execution_error",
        command=(), return_code=None, stdout="", stderr="",
        error_category="OSError", diagnostics="device not found on /dev/ttyUSB0",
    )
    result = _result_with_steps([execution_error])

    rendered = format_test_result_evidence(result)

    assert "OSError" in rendered
    assert "device not found on /dev/ttyUSB0" in rendered


# Regression 4: a mixed FAIL + BLOCKED + EXECUTION_ERROR sequence stays
# separately attributable -- nothing is merged across steps.

def test_mixed_failure_sequence_remains_separately_attributable():
    fail_step = _step(
        area="root", step_id="validate", status="fail",
        command=("tool", "validate"), return_code=2,
        stdout="Failed config: actionable message", stderr="stderr detail",
    )
    blocked_step = _step(
        area="root", step_id="compile", status="blocked",
        command=(), return_code=None,
        diagnostics="Blocked by failed dependency: root-validate",
    )
    error_step = _step(
        area="root", step_id="flash", status="execution_error",
        command=(), return_code=None, error_category="OSError",
        diagnostics="device not found on /dev/ttyUSB0",
    )
    result = _result_with_steps([fail_step, blocked_step, error_step])

    rendered = format_test_result_evidence(result)

    validate_idx = rendered.index("step_id=validate")
    compile_idx = rendered.index("step_id=compile")
    flash_idx = rendered.index("step_id=flash")
    assert validate_idx < compile_idx < flash_idx, "steps must appear in plan order, each as its own record"

    assert "Failed config: actionable message" in rendered
    assert "Blocked by failed dependency: root-validate" in rendered
    assert "device not found on /dev/ttyUSB0" in rendered
    assert "OSError" in rendered
    # Each record states its own return_code -- not the aggregate.
    assert rendered.count("Return code: 2") == 1
    assert rendered.count("Return code: None") == 2


# Regression 5: multiple distinct commands/return codes are never flattened
# into one ambiguous line.

def test_multiple_commands_and_return_codes_are_not_flattened():
    step_a = _step(step_id="a", command=("tool-a", "check", "x"), return_code=2)
    step_b = _step(step_id="b", command=("tool-b", "build", "y"), return_code=7)
    result = _result_with_steps([step_a, step_b])

    rendered = format_test_result_evidence(result)

    # Each command line is scoped to its own record, immediately followed
    # by its own return code -- never a flat "cmd-a cmd-b" join.
    assert "tool-a check x" in rendered
    assert "tool-b build y" in rendered
    lines = rendered.splitlines()
    command_a_line = next(l for l in lines if "tool-a check x" in l)
    command_b_line = next(l for l in lines if "tool-b build y" in l)
    assert "tool-b" not in command_a_line
    assert "tool-a" not in command_b_line
    assert rendered.count("Return code: 2") == 1
    assert rendered.count("Return code: 7") == 1


# Regression 6: very large command evidence is deterministically bounded.

def test_very_large_command_evidence_is_bounded():
    huge_command = tuple(f"arg-{i}" * 50 for i in range(200))
    step = _step(command=huge_command)
    result = _result_with_steps([step])

    rendered_once = format_test_result_evidence(result)
    rendered_again = format_test_result_evidence(result)

    assert rendered_once == rendered_again
    assert len(rendered_once) < 3000, "a single huge command must not dominate the rendered evidence"


def test_very_large_command_evidence_is_bounded_on_the_legacy_single_result_path():
    huge_command = tuple(f"arg-{i}" * 50 for i in range(200))
    result = _result(command=huge_command)

    rendered = format_test_result_evidence(result)

    assert len(rendered) < 3000


# Regression 7: very many failing verification steps stay bounded.

def test_very_many_failing_steps_remain_deterministically_bounded():
    steps = [_step(step_id=f"step-{i}", stdout=f"failure {i}" * 100) for i in range(500)]
    result = _result_with_steps(steps)

    rendered_once = format_test_result_evidence(result)
    rendered_again = format_test_result_evidence(result)

    assert rendered_once == rendered_again, "bounding many steps must still be deterministic"
    assert len(rendered_once) < 25_000
    assert "500 failing verification step(s)" in rendered_once
    assert "more failing step(s) not shown (truncated)" in rendered_once


# Regression 8: very large diagnostics/stdout/stderr on a per-step record
# are bounded with deterministic truncation.

def test_very_large_per_step_diagnostics_stdout_stderr_are_truncated_deterministically():
    step = _step(
        diagnostics="D" * 100_000,
        stdout="O" * 100_000,
        stderr="E" * 100_000,
    )
    result = _result_with_steps([step])

    rendered_once = format_test_result_evidence(result)
    rendered_again = format_test_result_evidence(result)

    assert rendered_once == rendered_again
    assert len(rendered_once) < 10_000
    assert "...[truncated]..." in rendered_once


# Regression 9 & 10: max_field_chars <= 0 must never mean "unlimited".

def test_max_field_chars_zero_yields_explicit_bounded_empty_fields():
    result = _result(stdout="A" * 10_000, stderr="B" * 10_000)

    rendered = format_test_result_evidence(result, max_field_chars=0)

    assert "A" * 10_000 not in rendered
    assert "B" * 10_000 not in rendered
    assert len(rendered) < 200


def test_max_field_chars_zero_also_bounds_step_failures_path():
    step = _step(stdout="A" * 10_000, stderr="B" * 10_000, diagnostics="C" * 10_000)
    result = _result_with_steps([step])

    rendered = format_test_result_evidence(result, max_field_chars=0)

    assert "A" * 10_000 not in rendered
    assert "B" * 10_000 not in rendered
    assert "C" * 10_000 not in rendered


def test_negative_max_field_chars_raises_explicitly():
    result = _result()

    with pytest.raises(ValueError):
        format_test_result_evidence(result, max_field_chars=-1)
