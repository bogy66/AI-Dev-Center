"""Deterministic, bounded rendering of controlled test/verification evidence.

Any consumer that needs to hand a previous TestResult's real evidence to a
downstream LLM prompt (or log, or report) must go through here rather than
using the object's own repr or a reviewer's paraphrase of it. A dataclass
repr is not bounded (a huge stdout/stderr blows up the prompt) and is not a
deliberate contract (field order/labels can drift with the dataclass). This
module fixes both: the same TestResult always renders to the same bounded
text, with stdout/stderr kept separately labeled and truncated the same way
every time.

Generic by construction: it only reads the five fields every controlled
TestResult already exposes (command, return_code, timed_out, stdout,
stderr) -- nothing here is specific to any one verifier (pytest, a
compiler, a config validator, ...).
"""
from __future__ import annotations

_DEFAULT_MAX_FIELD_CHARS = 4000
_TRUNCATION_MARKER = "\n...[truncated]...\n"


def _truncate(text: str, limit: int) -> str:
    """Bound `text` to `limit` characters, deterministically.

    Keeps a head and a tail slice (favoring the tail slightly, since
    failure text is often at the end of a command's output) separated by
    a fixed marker, so the same input at the same limit always produces
    the same output and neither the earliest nor the latest failure
    context is discarded entirely.
    """
    if limit <= 0 or len(text) <= limit:
        return text
    marker_len = len(_TRUNCATION_MARKER)
    keep = max(limit - marker_len, 0)
    if keep <= 0:
        return text[:limit]
    head = keep // 2
    tail = keep - head
    return text[:head] + _TRUNCATION_MARKER + (text[-tail:] if tail else "")


def format_test_result_evidence(test_result, max_field_chars: int = _DEFAULT_MAX_FIELD_CHARS) -> str:
    """Render command/return_code/timed_out/stdout/stderr deterministically.

    Only the named TestResult fields are read (via getattr with explicit
    defaults) -- never `vars()`/`__dict__`/repr -- so no incidental or
    hidden object field ever leaks into a rework prompt, and nothing here
    depends on any particular verifier's output shape.
    """
    if test_result is None:
        return "(no previous test evidence available)"

    command = getattr(test_result, "command", None) or ()
    command_text = " ".join(str(part) for part in command) if command else "(no command recorded)"
    return_code = getattr(test_result, "return_code", None)
    timed_out = bool(getattr(test_result, "timed_out", False))
    stdout = _truncate(getattr(test_result, "stdout", "") or "", max_field_chars)
    stderr = _truncate(getattr(test_result, "stderr", "") or "", max_field_chars)

    return (
        f"Command: {command_text}\n"
        f"Return code: {return_code}\n"
        f"Timed out: {timed_out}\n"
        f"--- stdout ---\n"
        f"{stdout}\n"
        f"--- stderr ---\n"
        f"{stderr}"
    )
