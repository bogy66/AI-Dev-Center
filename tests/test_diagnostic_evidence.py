from types import SimpleNamespace

from app.diagnostic_evidence import format_test_result_evidence
from app.project_test_runner import TestResult


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
