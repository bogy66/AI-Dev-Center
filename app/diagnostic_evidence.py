"""Deterministic, bounded rendering of controlled test/verification evidence.

Any consumer that needs to hand a previous TestResult's real evidence to a
downstream LLM prompt (or log, or report) must go through here rather than
using the object's own repr or a reviewer's paraphrase of it. A dataclass
repr is not bounded (a huge stdout/stderr, or many failing steps, blows up
the prompt) and is not a deliberate contract (field order/labels can drift
with the dataclass). This module fixes both: the same TestResult always
renders to the same bounded text, with stdout/stderr kept separately
labeled, and -- when a TestResult carries `step_failures` (see
app.project_test_runner) -- each failing step rendered as its own
self-contained, attributable record rather than flattened into one
ambiguous command/return_code line.

Generic by construction: it only reads the deliberate TestResult and
StepFailureEvidence contract fields -- nothing here is specific to any one
verifier (pytest, a compiler, a config validator, ...).
"""
from __future__ import annotations

_DEFAULT_MAX_FIELD_CHARS = 4000
_MAX_STEP_STDOUT_CHARS = 2000
_MAX_STEP_STDERR_CHARS = 2000
_MAX_STEP_DIAGNOSTICS_CHARS = 1000
_MAX_STEP_COMMAND_CHARS = 500
_MAX_STEP_RECORDS = 10
_MAX_TOTAL_CHARS = 20000
_TRUNCATION_MARKER = "\n...[truncated]...\n"


def _truncate(text: str, limit: int) -> str:
    """Bound `text` to `limit` characters, deterministically.

    `limit` must never be negative -- there is no meaningful bound below
    zero, so that is rejected outright rather than silently treated as
    "unlimited". A `limit` of exactly zero is a valid (degenerate) bound
    and deterministically yields the empty string, never the original
    text.

    For a positive limit, keeps a head and a tail slice (favoring the
    tail slightly, since failure text is often at the end of a command's
    output) separated by a fixed marker, so the same input at the same
    limit always produces the same output and neither the earliest nor
    the latest failure context is discarded entirely.
    """
    if limit < 0:
        raise ValueError("truncation limit must not be negative")
    if limit == 0:
        return ""
    if len(text) <= limit:
        return text
    marker_len = len(_TRUNCATION_MARKER)
    keep = max(limit - marker_len, 0)
    if keep <= 0:
        return text[:limit]
    head = keep // 2
    tail = keep - head
    return text[:head] + _TRUNCATION_MARKER + (text[-tail:] if tail else "")


def _command_text(command) -> str:
    return " ".join(str(part) for part in command) if command else "(no command recorded)"


def _display(text: str) -> str:
    return text if text else "(empty)"


def _render_step_failure(step, index: int, command_limit: int, stdout_limit: int,
                          stderr_limit: int, diagnostics_limit: int) -> str:
    command_text = _truncate(_command_text(getattr(step, "command", None) or ()), command_limit)
    diagnostics_raw = getattr(step, "diagnostics", "") or ""
    diagnostics = _truncate(diagnostics_raw, diagnostics_limit) if diagnostics_raw else ""
    error_category = getattr(step, "error_category", None) or "(none)"
    stdout = _truncate(getattr(step, "stdout", "") or "", stdout_limit)
    stderr = _truncate(getattr(step, "stderr", "") or "", stderr_limit)
    return (
        f"[{index}] area={getattr(step, 'area', '')} step_id={getattr(step, 'step_id', '')} "
        f"runner={getattr(step, 'runner_type', '')} kind={getattr(step, 'verification_kind', '')} "
        f"status={getattr(step, 'status', '')}\n"
        f"    Command: {command_text}\n"
        f"    Return code: {getattr(step, 'return_code', None)}\n"
        f"    Timed out: {bool(getattr(step, 'timed_out', False))}\n"
        f"    Error category: {error_category}\n"
        f"    Diagnostics: {_display(diagnostics)}\n"
        f"    --- stdout ---\n"
        f"    {_display(stdout)}\n"
        f"    --- stderr ---\n"
        f"    {_display(stderr)}"
    )


def _format_step_failures(step_failures, max_field_chars: int) -> str:
    command_limit = min(max_field_chars, _MAX_STEP_COMMAND_CHARS)
    stdout_limit = min(max_field_chars, _MAX_STEP_STDOUT_CHARS)
    stderr_limit = min(max_field_chars, _MAX_STEP_STDERR_CHARS)
    diagnostics_limit = min(max_field_chars, _MAX_STEP_DIAGNOSTICS_CHARS)

    total = len(step_failures)
    shown = step_failures[:_MAX_STEP_RECORDS]
    blocks = [
        _render_step_failure(step, index, command_limit, stdout_limit, stderr_limit, diagnostics_limit)
        for index, step in enumerate(shown, start=1)
    ]
    footer = ""
    if total > len(shown):
        footer = f"\n\n... and {total - len(shown)} more failing step(s) not shown (truncated)."
    return f"{total} failing verification step(s):\n\n" + "\n\n".join(blocks) + footer


def _format_single_result(test_result, max_field_chars: int) -> str:
    command_text = _truncate(
        _command_text(getattr(test_result, "command", None) or ()),
        min(max_field_chars, _MAX_STEP_COMMAND_CHARS),
    )
    return_code = getattr(test_result, "return_code", None)
    timed_out = bool(getattr(test_result, "timed_out", False))
    stdout = _truncate(getattr(test_result, "stdout", "") or "", max_field_chars)
    stderr = _truncate(getattr(test_result, "stderr", "") or "", max_field_chars)
    return (
        f"Command: {command_text}\n"
        f"Return code: {return_code}\n"
        f"Timed out: {timed_out}\n"
        f"--- stdout ---\n"
        f"{_display(stdout)}\n"
        f"--- stderr ---\n"
        f"{_display(stderr)}"
    )


def format_test_result_evidence(test_result, max_field_chars: int = _DEFAULT_MAX_FIELD_CHARS) -> str:
    """Render a TestResult's real evidence deterministically and boundedly.

    Only the named TestResult/StepFailureEvidence fields are read (via
    getattr with explicit defaults) -- never `vars()`/`__dict__`/repr --
    so no incidental or hidden object field, and no raw provider
    response, ever leaks into a rework prompt.

    When `test_result.step_failures` is populated (a TestResult folded
    from a VerificationResult with one or more failing steps -- see
    app.development_testing_stage._test_result_from_verification), each
    failing step is rendered as its own attributable record, up to
    `_MAX_STEP_RECORDS` of them, so multiple failures are never flattened
    into one ambiguous command/return_code/stdout/stderr. Otherwise the
    plain scalar fields are rendered directly.

    `max_field_chars` must be non-negative: zero is a valid (degenerate)
    bound and yields empty text fields deterministically; a negative
    value has no meaningful bound and raises `ValueError` rather than
    being treated as "unlimited". The fully rendered block is, in every
    case, additionally capped to an absolute maximum length as a final
    deterministic safety net, independent of step count or field size.
    """
    if max_field_chars < 0:
        raise ValueError("max_field_chars must not be negative")
    if test_result is None:
        return "(no previous test evidence available)"

    step_failures = getattr(test_result, "step_failures", None) or ()
    if step_failures:
        rendered = _format_step_failures(step_failures, max_field_chars)
    else:
        rendered = _format_single_result(test_result, max_field_chars)

    return _truncate(rendered, _MAX_TOTAL_CHARS)
