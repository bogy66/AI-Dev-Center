"""Tests for CLAUDE-E2E-002 Real-System E2E ESPHome failure evidence.

These exercise the plain helper functions in
tests/real_system/real_system_e2e.py directly and carry no
@pytest.mark.real_system marker, so they run under a normal
``pytest -q`` invocation without --real-system-e2e and without touching
any real toolchain, network, or paid provider -- proving the diagnostic
path locally, per CLAUDE-E2E-002's explicit instruction not to rely on
another paid run to validate it.

The module under test is loaded by explicit file path (rather than a
package import) because tests/real_system/ has no __init__.py, and any
test physically placed inside that directory is treated by
tests/conftest.py's keyword-based skip logic as a real-system test
regardless of markers.
"""

import importlib.util
from dataclasses import dataclass
from pathlib import Path

from app.verification import FAIL, PASS, TIMEOUT

_MODULE_PATH = (
    Path(__file__).parent / "real_system" / "real_system_e2e.py"
)
_spec = importlib.util.spec_from_file_location(
    "real_system_e2e_verification_evidence_under_test", _MODULE_PATH,
)
real_system_e2e = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(real_system_e2e)

_esphome_failure_evidence_lines = real_system_e2e._esphome_failure_evidence_lines
_redact_secrets_preserving_layout = real_system_e2e._redact_secrets_preserving_layout


@dataclass
class _FakeStep:
    verification_kind: str
    status: str
    return_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    diagnostics: str = ""
    command: tuple = ()
    truncated_output: bool = False


def test_no_lines_for_all_passing_steps():
    steps = [_FakeStep(verification_kind="validate", status=PASS.value)]

    assert _esphome_failure_evidence_lines(steps) == []


def test_failed_step_reports_kind_status_return_code_and_tool():
    step = _FakeStep(
        verification_kind="validate", status=FAIL.value, return_code=1,
        command=("/usr/bin/esphome", "config", "hello-world.yaml"),
        stdout="INFO Reading configuration hello-world.yaml...",
        stderr="Error: 'board' is a required option",
        diagnostics=(
            "STDOUT:\nINFO Reading configuration hello-world.yaml...\n\n"
            "STDERR:\nError: 'board' is a required option"
        ),
    )

    lines = _esphome_failure_evidence_lines([step])

    header = lines[0]
    assert "kind=validate" in header
    assert "status=fail" in header
    assert "return_code=1" in header
    assert "/usr/bin/esphome" in header
    assert "stdout_present=True" in header
    assert "stderr_present=True" in header
    assert "truncated_output=False" in header


def test_failed_step_includes_diagnostics_with_both_streams():
    step = _FakeStep(
        verification_kind="validate", status=FAIL.value, return_code=1,
        command=("/usr/bin/esphome", "config", "."),
        stdout="INFO Reading configuration hello-world.yaml...",
        stderr="Error: 'board' is a required option",
        diagnostics=(
            "STDOUT:\nINFO Reading configuration hello-world.yaml...\n\n"
            "STDERR:\nError: 'board' is a required option"
        ),
    )

    lines = _esphome_failure_evidence_lines([step])
    body = "\n".join(lines)

    assert "INFO Reading configuration hello-world.yaml" in body
    assert "Error: 'board' is a required option" in body


def test_passing_steps_are_skipped_only_failures_reported():
    passing = _FakeStep(verification_kind="validate", status=PASS.value)
    failing = _FakeStep(
        verification_kind="compile", status=FAIL.value, return_code=1,
        diagnostics="STDERR:\nCompilation failed",
        stderr="Compilation failed",
    )

    lines = _esphome_failure_evidence_lines([passing, failing])
    body = "\n".join(lines)

    assert "kind=validate" not in body
    assert "kind=compile" in body


def test_timeout_step_reports_timed_out_status():
    step = _FakeStep(
        verification_kind="compile", status=TIMEOUT.value, return_code=-1,
        diagnostics="Execution timed out.\nSTDOUT:\nworking...",
        stdout="working...",
    )

    lines = _esphome_failure_evidence_lines([step])

    assert any("status=timeout" in line for line in lines)


def test_stdout_and_stderr_presence_flags_reflect_actual_content():
    stdout_only = _FakeStep(
        verification_kind="validate", status=FAIL.value,
        stdout="the error", stderr="", diagnostics="STDOUT:\nthe error",
    )
    stderr_only = _FakeStep(
        verification_kind="validate", status=FAIL.value,
        stdout="", stderr="the error", diagnostics="STDERR:\nthe error",
    )

    stdout_line = _esphome_failure_evidence_lines([stdout_only])[0]
    stderr_line = _esphome_failure_evidence_lines([stderr_only])[0]

    assert "stdout_present=True" in stdout_line
    assert "stderr_present=False" in stdout_line
    assert "stdout_present=False" in stderr_line
    assert "stderr_present=True" in stderr_line


def test_no_diagnostics_line_when_diagnostics_empty():
    step = _FakeStep(
        verification_kind="validate", status=FAIL.value, diagnostics="",
    )

    lines = _esphome_failure_evidence_lines([step])

    assert len(lines) == 1
    assert not any("diagnostics:" in line for line in lines)


def test_evidence_never_touches_environment_or_secrets_by_construction():
    """VerificationStepResult (the real, non-fake type) carries no
    environment variables, project file contents, or LLM prompt/response
    fields at all -- the evidence formatter reads only kind, status,
    return_code, command, stdout/stderr presence, truncated_output, and
    diagnostics, so there is structurally nothing else it could leak."""
    import dataclasses
    from app.verification import VerificationStepResult

    field_names = {f.name for f in dataclasses.fields(VerificationStepResult)}
    forbidden = {"environ", "env", "prompt", "response", "api_key", "secret"}
    assert not (field_names & forbidden)


def test_redact_secrets_preserves_newlines_and_length():
    text = "line one\nAPI_KEY=sk-should-be-redacted\nline three"

    redacted = _redact_secrets_preserving_layout(text)

    assert "sk-should-be-redacted" not in redacted
    assert "[REDACTED]" in redacted
    assert redacted.count("\n") == text.count("\n")


def test_redact_secrets_does_not_truncate_bounded_diagnostics():
    long_text = "STDOUT:\n" + ("x" * 2000)

    redacted = _redact_secrets_preserving_layout(long_text)

    assert len(redacted) == len(long_text)
