"""Tests for CLAUDE-E2E-001 Real-System E2E live progress visibility.

These exercise the plain helper functions in
tests/real_system/real_system_e2e.py directly and carry no
@pytest.mark.real_system marker, so they run under a normal
``pytest -q`` invocation without --real-system-e2e and without touching
any real toolchain, network, or paid provider.

The module under test is loaded by explicit file path (rather than a
package import) because tests/real_system/ has no __init__.py, and any
test physically placed inside that directory is treated by
tests/conftest.py's keyword-based skip logic as a real-system test
regardless of markers.
"""

import importlib.util
from pathlib import Path

import pytest

from app.diagnostic_trace import DiagnosticTraceEvent

_MODULE_PATH = (
    Path(__file__).parent / "real_system" / "real_system_e2e.py"
)
_spec = importlib.util.spec_from_file_location(
    "real_system_e2e_progress_under_test", _MODULE_PATH,
)
real_system_e2e = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(real_system_e2e)

_E2EProgress = real_system_e2e._E2EProgress
_council_progress_line = real_system_e2e._council_progress_line
_render_new_trace_events = real_system_e2e._render_new_trace_events
_stage_interface_warnings = real_system_e2e._stage_interface_warnings
_emit_failure_diagnostics = real_system_e2e._emit_failure_diagnostics
_council_reached_complete = real_system_e2e._council_reached_complete
_validate_final_diagnostic_trace = real_system_e2e._validate_final_diagnostic_trace
_phase_later_recovered = real_system_e2e._phase_later_recovered
REAL_TASK = real_system_e2e.REAL_TASK


def _make_event(
    *,
    phase="engineering_council",
    status="started",
    summary="Agent A1 started",
    details=None,
    sequence=1,
):
    return DiagnosticTraceEvent(
        event_id=f"event-{sequence}",
        run_id="run-1",
        sequence=sequence,
        timestamp="2026-01-01T00:00:00+00:00",
        phase=phase,
        event_type=status,
        status=status,
        summary=summary,
        source="development_workflow",
        details=details if details is not None else {},
    )


def test_council_progress_line_reports_agent_started():
    event = _make_event(
        summary="Agent A1 started",
        details={"actor": "Agent A1", "runtime_state": "started"},
    )

    assert _council_progress_line(event) == "Engineering Council: Agent A1 started"


def test_council_progress_line_reports_chairman_completed():
    event = _make_event(
        status="completed",
        summary="Chairman completed",
        details={"actor": "Chairman", "runtime_state": "completed"},
    )

    assert _council_progress_line(event) == "Engineering Council: Chairman completed"


def test_council_progress_line_ignores_non_council_phase():
    event = _make_event(
        phase="requirement_discovery",
        summary="Requirement discovery provider completed",
        details={"actor": "Agent A1", "runtime_state": "completed"},
    )

    assert _council_progress_line(event) is None


def test_council_progress_line_requires_an_actor():
    event = _make_event(details={})

    assert _council_progress_line(event) is None


def test_render_new_trace_events_shows_council_progress_at_none_level(capsys):
    progress = _E2EProgress()
    event = _make_event(
        summary="Agent A2 started",
        details={"actor": "Agent A2", "runtime_state": "started"},
    )

    _render_new_trace_events(progress, [event], set(), diagnostic_level="NONE")

    out = capsys.readouterr().out
    assert "Engineering Council: Agent A2 started" in out


def test_render_new_trace_events_never_leaks_forbidden_content_at_none_level(capsys):
    """The bounded progress line is built only from actor + runtime_state;
    even if a caller (incorrectly) stuffed forbidden keys into details,
    those must never reach the printed progress line."""
    progress = _E2EProgress()
    event = _make_event(
        summary="Agent A3 started",
        details={
            "actor": "Agent A3",
            "runtime_state": "started",
            "prompt": "SECRET SYSTEM PROMPT",
            "raw_response": "SECRET LLM RESPONSE",
            "api_key": "sk-should-never-appear",
        },
    )

    _render_new_trace_events(progress, [event], set(), diagnostic_level="NONE")

    out = capsys.readouterr().out
    assert out.strip().endswith("Engineering Council: Agent A3 started")
    assert "SECRET" not in out
    assert "sk-should-never-appear" not in out


def test_render_new_trace_events_does_not_duplicate_at_normal_level(capsys):
    """At NORMAL+ diagnostic levels, render_diagnostic_trace_event already
    renders a non-empty TRACE line for the event, so the bounded
    council-progress helper must not also print a second, duplicate line."""
    progress = _E2EProgress()
    event = _make_event(
        status="completed",
        summary="Agent A3 completed",
        details={"actor": "Agent A3", "runtime_state": "completed"},
    )

    _render_new_trace_events(progress, [event], set(), diagnostic_level="NORMAL")

    out = capsys.readouterr().out
    assert "Engineering Council: Agent A3" not in out
    assert "Agent A3" in out


def test_render_new_trace_events_deduplicates_by_sequence():
    progress = _E2EProgress()
    seen = set()
    event = _make_event(
        summary="Agent A1 started",
        details={"actor": "Agent A1", "runtime_state": "started"},
        sequence=7,
    )

    _render_new_trace_events(progress, [event], seen, diagnostic_level="NONE")
    _render_new_trace_events(progress, [event], seen, diagnostic_level="NONE")

    assert seen == {7}


def _make_interface_event(*, stage, warnings, sequence=1):
    """Build a synthetic interface trace event matching the exact shape
    DevelopmentWorkflow._interface() produces for a given stage, so
    _stage_interface_warnings can be exercised against realistic data."""
    return DiagnosticTraceEvent(
        event_id=f"iface-{sequence}",
        run_id="run-1",
        sequence=sequence,
        timestamp="2026-01-01T00:00:00+00:00",
        phase=stage,
        event_type="completed",
        status="completed",
        summary="stage interface",
        source="development_workflow",
        details={
            "result_kind": "interface",
            "interface_stage": stage,
            "interface_data": {
                "verbose": {
                    "y": {
                        "type": "requirement_set",
                        "interface": "internal",
                        "source": stage,
                        "destination": "next_stage",
                        "data": {"warnings": list(warnings)},
                    },
                },
            },
        },
    )


def test_stage_interface_warnings_extracts_verbose_warnings_for_stage():
    event = _make_interface_event(
        stage="requirement_discovery",
        warnings=["LLM provider raised an exception: TimeoutError: read timed out"],
    )

    result = _stage_interface_warnings([event], "requirement_discovery")

    assert result == ["LLM provider raised an exception: TimeoutError: read timed out"]


def test_stage_interface_warnings_ignores_other_stages():
    event = _make_interface_event(stage="preflight", warnings=["some warning"])

    assert _stage_interface_warnings([event], "requirement_discovery") == []


def test_stage_interface_warnings_returns_empty_when_absent():
    event = _make_event(phase="requirement_discovery", details={})

    assert _stage_interface_warnings([event], "requirement_discovery") == []


def test_emit_failure_diagnostics_prints_discovery_warning(capsys):
    """CLAUDE-E2E-001 follow-up: when requirement_discovery falls back
    (e.g. an LLM provider error), the real cause -- previously silently
    discarded -- must now be visible in the E2E's failure diagnostics
    without needing a higher --diagnostic-level."""
    progress = _E2EProgress()
    progress.milestone(15, "greenfield project materialized")
    failed_event = _make_event(
        phase="requirement_discovery",
        status="blocked",
        summary="Requirement discovery fallback blocked planning",
        details={},
        sequence=1,
    )
    interface_event = _make_interface_event(
        stage="requirement_discovery",
        warnings=[
            "LLM provider raised an exception: TimeoutError: read timed out",
        ],
        sequence=2,
    )

    _emit_failure_diagnostics(
        Exception("planning was blocked"),
        progress,
        [failed_event, interface_event],
    )

    out = capsys.readouterr().out
    assert "stage: requirement_discovery" in out
    assert (
        "warning: LLM provider raised an exception: TimeoutError: read timed out"
        in out
    )


def test_emit_failure_diagnostics_redacts_secrets_in_warnings(capsys):
    progress = _E2EProgress()
    failed_event = _make_event(
        phase="requirement_discovery", status="blocked",
        summary="blocked", details={}, sequence=1,
    )
    interface_event = _make_interface_event(
        stage="requirement_discovery",
        warnings=["provider failed: api_key=sk-super-secret-value"],
        sequence=2,
    )

    _emit_failure_diagnostics(
        Exception("planning was blocked"), progress,
        [failed_event, interface_event],
    )

    out = capsys.readouterr().out
    assert "sk-super-secret-value" not in out


def test_council_reached_complete_true_when_recorded_anywhere_in_trace():
    events = [
        _make_event(status="timeout", details={"actor": "Agent A1"}, sequence=1),
        _make_event(
            status="completed", summary="Chairman completed",
            details={"actor": "Chairman", "council_complete": True}, sequence=2,
        ),
    ]

    assert _council_reached_complete(events) is True


def test_council_reached_complete_false_when_never_recorded():
    events = [
        _make_event(status="failed", details={"actor": "Agent A2"}, sequence=1),
    ]

    assert _council_reached_complete(events) is False


def test_emit_failure_diagnostics_does_not_promote_a_recovered_council_agent_failure_as_the_terminal_cause(capsys):
    """CLAUDE-ADC-E2E-HUMAN-SELECTION-EMULATION-001: reproduces the
    verified secondary diagnostic signal -- Agent A1 failed JSON parsing
    (timeout) but the Council itself later recovered
    (council_complete=True). The terminal failure actually happened at a
    LATER stage entirely (here: the workflow correctly paused at
    human_engineering_authority, not a failure at all) -- A1's stale,
    already-recovered timeout must never be reported as the top-level
    stage/actor/failure_category, even though it is the only
    'failed'-status-family event anywhere in the trace."""
    progress = _E2EProgress()
    a1_timeout = _make_event(
        phase="engineering_council", status="timeout",
        summary="Agent A1 timed out",
        details={"actor": "Agent A1", "failure_category": "timeout"},
        sequence=1,
    )
    chairman_completed = _make_event(
        phase="engineering_council", status="completed",
        summary="Chairman completed",
        details={"actor": "Chairman", "council_complete": True},
        sequence=2,
    )
    pending_selection = _make_event(
        phase="human_engineering_authority", status="pending",
        summary="Human engineering selection is pending",
        details={},
        sequence=3,
    )

    _emit_failure_diagnostics(
        AssertionError("SetupPlan was not materialized"), progress,
        [a1_timeout, chairman_completed, pending_selection],
    )

    out = capsys.readouterr().out
    # The stale, recovered A1 failure must not be promoted to the
    # top-level terminal attribution...
    assert "actor: Agent A1" not in out
    assert "failure_category: timeout" not in out
    # ...but it must still be visible in the per-agent activity history,
    # never silently hidden.
    assert "Agent A1: status=timeout" in out


def test_emit_failure_diagnostics_still_reports_a_genuinely_unrecovered_council_failure(capsys):
    """The recovered-transient-failure fix must never hide a REAL,
    unrecovered Council agent failure -- when the Council never reaches
    council_complete=True, the failing agent's event is still correctly
    promoted as the terminal stage/actor/failure_category."""
    progress = _E2EProgress()
    a2_failed = _make_event(
        phase="engineering_council", status="failed",
        summary="Agent A2 failed",
        details={"actor": "Agent A2", "failure_category": "provider_failure"},
        sequence=1,
    )

    _emit_failure_diagnostics(
        Exception("Engineering Council did not reach a complete decision"),
        progress, [a2_failed],
    )

    out = capsys.readouterr().out
    assert "stage: engineering_council" in out
    assert "actor: Agent A2" in out
    assert "failure_category: provider_failure" in out


def test_emit_failure_diagnostics_still_reports_a_later_genuine_failure_after_council_recovers(capsys):
    """A recovered Council retry must not swallow a genuine LATER
    failure either -- e.g. toolchain materialization failing after a
    fully-recovered, complete Council result."""
    progress = _E2EProgress()
    a1_timeout = _make_event(
        phase="engineering_council", status="timeout",
        summary="Agent A1 timed out",
        details={"actor": "Agent A1", "failure_category": "timeout"},
        sequence=1,
    )
    chairman_completed = _make_event(
        phase="engineering_council", status="completed",
        summary="Chairman completed",
        details={"actor": "Chairman", "council_complete": True},
        sequence=2,
    )
    materialization_failed = _make_event(
        phase="toolchain_materialization", status="failed",
        summary="Toolchain materialization failed: NoEligibleEngineeringCandidateError",
        details={"failure_category": "no_eligible_candidate"},
        sequence=3,
    )

    _emit_failure_diagnostics(
        Exception("Toolchain materialization failed"), progress,
        [a1_timeout, chairman_completed, materialization_failed],
    )

    out = capsys.readouterr().out
    assert "stage: toolchain_materialization" in out
    assert "failure_category: no_eligible_candidate" in out
    assert "actor: Agent A1" not in out


# ============================================================================
# KIB-ADC-RSE-DIAGNOSTIC-TRACE-TC-FIX-001: shared final DiagnosticTrace
# validation helper -- the exact contract the RSE's Central Diagnostic
# Trace block now delegates to, exercised here with real
# DiagnosticTraceEvent instances and no Real-System-E2E execution.
# ============================================================================

def _typed(data, data_type, source, destination):
    """Mirrors app.engineering_council's own typed() closure exactly --
    the real x/y endpoint shape ADC actually produces."""
    return {
        "type": data_type, "interface": "internal",
        "source": source, "destination": destination, "data": data,
    }


def _execution_identity(entity, **extra):
    """Mirrors app.execution_identity.execution_identity()'s real
    return shape exactly."""
    identity = {
        "entity": entity, "entity_version": 1,
        "implementation_version": "adc-python-1",
    }
    identity.update(extra)
    return identity


def _make_full_trace(real_task=REAL_TASK):
    """A realistic, minimal-but-complete trace: one event per required
    Council agent/Chairman, each carrying real-shaped interface_data
    (x/f/y with type/interface/source/destination) and a top-level
    execution_identity -- exactly what app.engineering_council actually
    records, reproduced here structurally rather than imported, so this
    test never depends on running the real Council."""
    events = []
    for i, actor in enumerate(("Agent A1", "Agent A2", "Agent A3", "Chairman"), start=1):
        entity = "chairman" if actor == "Chairman" else f"council_agent_{actor[-1].lower()}_proposal"
        events.append(_make_event(
            phase="engineering_council", status="completed",
            summary=f"{actor} completed: {real_task}",
            sequence=i,
            details={
                "actor": actor, "actor_role": "proposer",
                "council_phase": "phase1",
                "council_complete": actor == "Chairman",
                "execution_identity": _execution_identity(
                    entity, provider="anthropic", model="claude", actor=actor, phase="phase1",
                ),
                "interface_data": {
                    "info": {
                        "x": _typed({"task": real_task}, "council_input", "engineering_council", entity),
                        "f": _execution_identity(entity, provider="anthropic", model="claude"),
                        "y": _typed({"available": True}, "proposal", entity, "engineering_council"),
                    },
                },
            },
        ))
    return events


def test_validate_final_diagnostic_trace_accepts_a_realistic_real_shaped_trace():
    """1. real DiagnosticTraceEvent objects can be validated."""
    import json
    trace = _make_full_trace()
    serialized = _validate_final_diagnostic_trace(trace, REAL_TASK)
    # REAL_TASK contains literal double quotes, which genuine JSON
    # serialization escapes inside string values -- check for its own
    # json-escaped form (see _validate_final_diagnostic_trace's own
    # docstring for why the raw, unescaped text is never expected to
    # appear byte-for-byte inside real JSON output).
    assert json.dumps(REAL_TASK)[1:-1] in serialized


def test_validate_final_diagnostic_trace_never_calls_to_record():
    """2. no nonexistent to_record() dependency exists -- proven both by
    the mechanical former-AttributeError reproduction (a real
    DiagnosticTraceEvent genuinely has no to_record attribute) and by
    inspecting the helper's own executable statements (its docstring
    legitimately explains to_record() never existed as a product API,
    so the check below looks only at the function body, not the
    docstring text)."""
    import ast
    import inspect
    import textwrap

    event = _make_event()
    assert not hasattr(event, "to_record")
    with pytest.raises(AttributeError):
        event.to_record()

    source = inspect.getsource(_validate_final_diagnostic_trace)
    tree = ast.parse(textwrap.dedent(source))
    func_node = tree.body[0]
    body_without_docstring = func_node.body[1:]  # [0] is the docstring Expr
    body_source = "\n".join(ast.unparse(stmt) for stmt in body_without_docstring)
    assert "to_record" not in body_source
    assert "asdict" in body_source
    # And the helper succeeds against real events despite to_record()
    # never existing -- mechanically covering the exact former crash path.
    _validate_final_diagnostic_trace(_make_full_trace(), REAL_TASK)


def test_validate_final_diagnostic_trace_checks_x_f_y_semantics():
    """3. x/f/y semantics are checked."""
    trace = _make_full_trace()
    # Strip the "f" key from every event's nested x/f/y projection.
    stripped = []
    for event in trace:
        details = dict(event.details)
        interface_data = dict(details["interface_data"])
        info = dict(interface_data["info"])
        info.pop("f")
        interface_data["info"] = info
        details["interface_data"] = interface_data
        stripped.append(_make_event(
            phase=event.phase, status=event.status, summary=event.summary,
            details=details, sequence=event.sequence,
        ))
    with pytest.raises(AssertionError, match="x → f → y"):
        _validate_final_diagnostic_trace(stripped, REAL_TASK)


def test_validate_final_diagnostic_trace_checks_execution_identity_semantics():
    """4. execution_identity semantics are checked.

    Only the TOP-LEVEL details["execution_identity"] key (the literal
    string "execution_identity") is removed here -- the nested x/f/y
    "f" value (itself an execution_identity()-shaped dict, but never
    stored under a key literally named "execution_identity") is left
    untouched, so the earlier x/f/y assertion still passes and this
    test isolates exactly the execution_identity assertion."""
    trace = _make_full_trace()
    stripped = []
    for event in trace:
        details = dict(event.details)
        details.pop("execution_identity", None)
        stripped.append(_make_event(
            phase=event.phase, status=event.status, summary=event.summary,
            details=details, sequence=event.sequence,
        ))
    with pytest.raises(AssertionError, match="execution identity"):
        _validate_final_diagnostic_trace(stripped, REAL_TASK)


def test_validate_final_diagnostic_trace_checks_actor_phase_semantics():
    """5. actor/phase semantics are checked."""
    trace = _make_full_trace()
    missing_a2 = [event for event in trace if "Agent A2" not in event.summary]
    with pytest.raises(AssertionError, match="Council agents and Chairman"):
        _validate_final_diagnostic_trace(missing_a2, REAL_TASK)


def test_validate_final_diagnostic_trace_rejects_forbidden_data():
    """6. forbidden data is rejected."""
    trace = _make_full_trace()
    tainted = list(trace) + [_make_event(
        phase="engineering_council", status="completed",
        summary="leaked", sequence=99,
        details={"effective_prompt": "system_prompt: you are a helpful assistant"},
    )]
    with pytest.raises(AssertionError, match="system_prompt"):
        _validate_final_diagnostic_trace(tainted, REAL_TASK)


def test_diagnostic_detail_level_none_does_not_erase_persisted_audit_evidence():
    """7. DiagnosticDetailLevel.NONE does not erase persisted audit
    evidence: the human-readable projection is suppressed entirely at
    NONE, but the same raw trace still passes full validation, proving
    the underlying persisted details were never actually erased --
    only their presentation was suppressed."""
    from app.diagnostic_trace import DiagnosticDetailLevel, render_diagnostic_trace_event

    trace = _make_full_trace()
    for event in trace:
        assert render_diagnostic_trace_event(event, DiagnosticDetailLevel.NONE) == ""

    # The exact same events, inspected via the real persisted-data path
    # (asdict, independent of any DiagnosticDetailLevel), still contain
    # everything the acceptance contract requires.
    serialized = _validate_final_diagnostic_trace(trace, REAL_TASK)
    assert '"execution_identity"' in serialized
    assert '"x"' in serialized and '"f"' in serialized and '"y"' in serialized


def test_validate_final_diagnostic_trace_fails_clearly_on_missing_task_description():
    """8a. invalid/missing required trace structure fails clearly --
    missing REAL_TASK."""
    trace = [_make_event(
        phase="engineering_council", status="completed",
        summary="Agent A1 completed", sequence=1,
        details={"actor": "Agent A1"},
    )]
    with pytest.raises(AssertionError, match="original task description"):
        _validate_final_diagnostic_trace(trace, REAL_TASK)


def test_validate_final_diagnostic_trace_fails_clearly_on_empty_trace():
    """8b. invalid/missing required trace structure fails clearly --
    an empty trace (nothing persisted at all)."""
    with pytest.raises(AssertionError, match="original task description"):
        _validate_final_diagnostic_trace([], REAL_TASK)


# ============================================================================
# KIB-ADC-RSE-DIAGNOSTIC-TRACE-TC-FIX-001: failure-stage diagnostic fix.
# Reproduces the reported "[96%] local Git commit completed" /
# "stage: testing" mismatch mechanically, without running the RSE.
# ============================================================================

def test_emit_failure_diagnostics_does_not_promote_a_recovered_testing_phase_retry(capsys):
    """A transient 'testing'-phase retry that this SAME phase later
    recovered from, followed by real forward progress all the way
    through a successful controlled_git commit, must not be reported as
    'stage: testing' for an unrelated later (e.g. harness-level)
    failure -- this exactly reproduces the originally-reported
    '[96%] local Git commit completed' / 'stage: testing' mismatch."""
    progress = _E2EProgress()
    trace = [
        _make_event(phase="engineering_council", status="completed",
                    summary="Chairman completed", sequence=1,
                    details={"actor": "Chairman", "council_complete": True}),
        _make_event(phase="testing", status="failed",
                    summary="esphome compile attempt 1 failed", sequence=2),
        _make_event(phase="testing", status="completed",
                    summary="esphome compile attempt 2 passed", sequence=3),
        _make_event(phase="final_approval", status="approved",
                    summary="final approval", sequence=4),
        _make_event(phase="controlled_git", status="committed",
                    summary="git commit done", sequence=5),
    ]

    _emit_failure_diagnostics(
        AttributeError("'DiagnosticTraceEvent' object has no attribute 'to_record'"),
        progress, trace,
    )

    out = capsys.readouterr().out
    assert "stage: testing" not in out


def test_emit_failure_diagnostics_still_reports_a_genuinely_unrecovered_testing_failure(capsys):
    """The generalized same-phase-recovery fix must never hide a REAL,
    unrecovered failure on a non-council phase -- when 'testing' never
    succeeds again after failing, it is still correctly reported."""
    progress = _E2EProgress()
    trace = [
        _make_event(phase="engineering_council", status="completed",
                    summary="Chairman completed", sequence=1,
                    details={"actor": "Chairman", "council_complete": True}),
        _make_event(phase="testing", status="failed",
                    summary="esphome compile failed", sequence=2,
                    details={"failure_category": "compile_error"}),
    ]

    _emit_failure_diagnostics(Exception("compile failed"), progress, trace)

    out = capsys.readouterr().out
    assert "stage: testing" in out
    assert "failure_category: compile_error" in out


def test_emit_failure_diagnostics_still_reports_a_later_genuine_failure_on_a_different_phase_after_testing_recovers(capsys):
    """A recovered 'testing'-phase retry must not swallow a genuine
    LATER failure on a different phase either."""
    progress = _E2EProgress()
    trace = [
        _make_event(phase="testing", status="failed",
                    summary="esphome compile attempt 1 failed", sequence=1),
        _make_event(phase="testing", status="completed",
                    summary="esphome compile attempt 2 passed", sequence=2),
        _make_event(phase="final_approval", status="rejected",
                    summary="final approval rejected", sequence=3,
                    details={"failure_category": "verification_regressed"}),
    ]

    _emit_failure_diagnostics(Exception("final approval rejected"), progress, trace)

    out = capsys.readouterr().out
    assert "stage: final_approval" in out
    assert "failure_category: verification_regressed" in out


def test_phase_later_recovered_true_only_for_a_genuinely_later_same_phase_success():
    failed = _make_event(phase="testing", status="failed", sequence=1)
    later_same_phase_ok = _make_event(phase="testing", status="completed", sequence=2)
    later_other_phase_ok = _make_event(phase="final_approval", status="approved", sequence=2)
    earlier_same_phase_ok = _make_event(phase="testing", status="completed", sequence=0)

    assert _phase_later_recovered([failed, later_same_phase_ok], failed) is True
    assert _phase_later_recovered([failed, later_other_phase_ok], failed) is False
    assert _phase_later_recovered([earlier_same_phase_ok, failed], failed) is False
    assert _phase_later_recovered([failed], failed) is False
