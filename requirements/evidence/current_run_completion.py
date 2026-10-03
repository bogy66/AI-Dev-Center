"""Current-pytest-session Gate-1 completion tracking
(KIA-ADC-GATE1-HARNESS-PROOF-FIX-001 section 7 -- closes the masking gap
identified by independent KI-B source inspection).

A TEST_*'s persisted `:verification_result:` in tests.rst can be IO from
an OLD run, while the CURRENT run never actually re-executed that TEST_*'s
own required_tests at all -- deselected, skipped, xfailed, failed, or
simply never collected because a narrower pytest invocation was used.
Composing that stale persisted IO into a claim that the CURRENT run is a
COMPLETE Gate-1 validation would be dishonest: a selector missing from
this run must never be silently replaced by historical PASS evidence.

This module tracks, for the CURRENT pytest session only -- in memory,
never persisted, never a second competing Evidence store -- which exact
nodeids among SELECTOR_MAP's own selectors actually reached a genuine
PASS THIS session, via the same pytest_runtest_makereport hookwrapper
shape tests/conftest.py already uses for tests/env_scenarios.py's own
session-scoped coverage recording, plus pytest's own `pytest_deselected`
hook for selectors a filtered/narrowed invocation dropped entirely.
Historical/persisted Evidence remains available elsewhere (ingest.py /
proof_obligations.read_current_verification_results) for traceability
and history -- this module never reads or writes it.
"""
from __future__ import annotations

from .selector_map import SELECTOR_MAP, is_gate3_only_nodeid

# The single established REAL_SYSTEM_ONLY TEST object (selector_map.py's
# own documented convention, reused -- not redefined independently here
# beyond this one frozenset, matching proof_obligations.py's own).
_REAL_SYSTEM_ONLY_OBLIGATIONS = frozenset({"TEST_033"})

# nodeid -> "PASSED" | "FAILED" | "SKIPPED" | "XFAIL" | "DESELECTED"
_CURRENT_RUN_OUTCOMES: dict[str, str] = {}

_PASSING_OUTCOME = "PASSED"


def reset_current_run_outcomes() -> None:
    """Test-only: clears the session-scoped record. Used by this
    module's own focused regression tests so one test's synthetic
    outcomes never leak into another's assertions."""
    _CURRENT_RUN_OUTCOMES.clear()


def record_outcome(nodeid: str, outcome: str) -> None:
    _CURRENT_RUN_OUTCOMES[nodeid] = outcome


def current_run_outcomes() -> dict[str, str]:
    return dict(_CURRENT_RUN_OUTCOMES)


def _selector_matches(nodeid: str, selector: str) -> bool:
    if "::" in selector:
        return nodeid == selector or nodeid.startswith(selector + "::") or nodeid.startswith(selector + "[")
    return nodeid.startswith(selector + "::") or nodeid == selector


def _selector_is_current_run_passed(selector: str) -> bool:
    """A selector is current-run PASS-backed only when at least one
    recorded CURRENT-session nodeid it names resolved to a genuine
    PASSED outcome, and no nodeid it names resolved to anything else
    disqualifying. A selector nothing was recorded for at all (never
    collected this session -- deselected, filtered out, or a narrower
    invocation) is never treated as passed: silence is not evidence.

    Nodeids that are explicitly Gate-3-only (selector_map.
    GATE3_ONLY_SELECTORS, e.g. TEST_032's own real_system-marked smoke
    test nested inside its otherwise-Gate-1 whole-file selector) are
    excluded from this computation entirely (KIA-ADC-GATE1-CONTAINMENT
    -GATE-SCOPING-FIX-001 sections 6-8): a whole-file Gate-1 selector
    must not be degraded to "not current-run passed" merely because its
    own explicitly Gate-3-only nested item was correctly skipped/
    NOT_RUN at Gate 1. See current_run_gate3_status() for that nested
    item's own, separately tracked status."""
    matches = {nodeid: outcome for nodeid, outcome in _CURRENT_RUN_OUTCOMES.items()
               if _selector_matches(nodeid, selector) and not is_gate3_only_nodeid(nodeid)}
    if not matches:
        return False
    return all(outcome == _PASSING_OUTCOME for outcome in matches.values())


def current_run_gate3_status(selector: str) -> str:
    """Best-effort CURRENT-session status for an explicitly Gate-3-only
    selector (never mandatory for Gate-1 completion -- see
    mandatory_current_run_gaps) -- 'NOT_RUN' both when this session
    never recorded any outcome for it at all AND when every recorded
    outcome was SKIPPED/XFAIL/DESELECTED (the expected, correct shape
    for an ordinary Gate-1 run, where the real_system marker causes a
    setup-phase skip -- 'NOT_RUN' matches this codebase's own existing
    IO/NIO/NOT_RUN vocabulary, e.g. pytest_plugin.py's _RESULT_MAP,
    rather than pytest's own internal 'skipped' terminology). 'PASSED'
    only when every nodeid it names reached a genuine PASSED outcome
    this session (an explicit --real-system-e2e invocation). 'FAILED'
    when at least one nodeid it names genuinely failed."""
    matches = {nodeid: outcome for nodeid, outcome in _CURRENT_RUN_OUTCOMES.items()
               if _selector_matches(nodeid, selector)}
    if not matches:
        return "NOT_RUN"
    outcomes = set(matches.values())
    if outcomes == {_PASSING_OUTCOME}:
        return "PASSED"
    if "FAILED" in outcomes:
        return "FAILED"
    return "NOT_RUN"


def mandatory_current_run_gaps(obligation_ids=None) -> tuple[str, ...]:
    """Mandatory Gate-1 (never Gate-3/TEST_033, unless explicitly
    included via *obligation_ids*; and, within an otherwise-Gate-1
    obligation, never its own explicitly Gate-3-only nested selectors --
    see selector_map.GATE3_ONLY_SELECTORS and
    _selector_is_current_run_passed) obligation ids whose required_tests
    are NOT fully current-run PASS-backed this session -- deselected,
    skipped, failed, xfailed, or never collected at all. Historical
    tests.rst evidence is never consulted here; this is a pure,
    synchronous read of the in-memory current-session record."""
    ids = obligation_ids if obligation_ids is not None else (
        frozenset(SELECTOR_MAP) - _REAL_SYSTEM_ONLY_OBLIGATIONS
    )
    gaps = []
    for obligation_id in sorted(ids):
        selectors = SELECTOR_MAP[obligation_id]
        if not all(_selector_is_current_run_passed(s) for s in selectors):
            gaps.append(obligation_id)
    return tuple(gaps)
