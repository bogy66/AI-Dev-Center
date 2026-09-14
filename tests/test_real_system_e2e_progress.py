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
