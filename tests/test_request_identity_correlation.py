"""TEST_034 — deterministic verification of IF_REQ_001: every incoming
request carries a structured identity (project_id / intent /
source_interface) whose user_request is preserved unchanged without
adapter reinterpretation, and every artifact of one ADC run is
correlated by run_id and isolated from every other run.

Uses the real producers and consumers identified by IMPL_034:
app/common_request.py (CommonRequest), app/diagnostic_trace.py
(DiagnosticTrace/DiagnosticTraceStore), app/workflow_manager.py
(WorkflowManager) — asserting correlation SEMANTICS (exact per-run
assignment and cross-run isolation), never merely the presence of a
run_id field.
"""
from __future__ import annotations

import dataclasses
import uuid

import pytest

from app.common_request import CommonRequest, RequestIntent
from app.diagnostic_trace import DiagnosticTrace, DiagnosticTraceStore
from app.workflow_manager import WorkflowManager


def test_common_request_structured_identity_preserves_user_request_unchanged():
    """A. Structured request identity: the real adapter-neutral request
    carries project_id, intent and source_interface and preserves the
    user's request text byte-for-byte; being frozen, it structurally
    cannot be reinterpreted or reformulated by any adapter."""
    user_request = "Create an ESP32 project   with odd spacing\nand two lines"
    request = CommonRequest(
        project_id="proj-identity",
        project_info={"root": "/tmp/proj", "files": ["platformio.ini"]},
        intent=RequestIntent.PLAN_PROJECT_SETUP,
        user_request=user_request,
        source_interface="web",
    )

    assert request.project_id == "proj-identity"
    assert request.intent is RequestIntent.PLAN_PROJECT_SETUP
    assert request.source_interface == "web"
    assert request.user_request == user_request

    with pytest.raises(dataclasses.FrozenInstanceError):
        request.user_request = "mutated by an adapter"


def test_run_scoped_correlation_assigns_and_isolates_two_runs(tmp_path):
    """B. Run-scoped correlation: artifacts of two concurrent ADC runs
    sharing the same stores are assigned to exactly one run each and are
    fully isolated — a decision on one run never bleeds into the other,
    and per-run retrieval returns exactly that run's artifacts."""
    trace = DiagnosticTrace(DiagnosticTraceStore(tmp_path / "events.jsonl"))
    manager = WorkflowManager(storage=str(tmp_path / f"wf-{uuid.uuid4().hex}.json"))

    # Interleaved writes from two runs into the SAME stores.
    event_a1 = trace.record("run-a", "development", "started", "started", "Development started")
    event_b1 = trace.record("run-b", "testing", "started", "started", "Testing started")
    event_a2 = trace.record("run-a", "development", "completed", "completed", "Development completed")

    # Exact per-run assignment: get_trace(run_id) returns exactly that
    # run's artifacts, each stamped with its own run_id, nothing else.
    assert {event.event_id for event in trace.get_trace("run-a")} == {event_a1.event_id, event_a2.event_id}
    assert [event.event_id for event in trace.get_trace("run-b")] == [event_b1.event_id]
    assert all(event.run_id == "run-a" for event in trace.get_trace("run-a"))
    assert all(event.run_id == "run-b" for event in trace.get_trace("run-b"))

    # Run-scoped workflow records: independent final-approval lifecycle
    # per run_id in the same store, no cross-run state bleed.
    created_a = manager.create_final_approval("run-a", "accepted")
    created_b = manager.create_final_approval("run-b", "accepted")
    assert created_a.run_id == "run-a" and created_a.status == "pending"
    assert created_b.run_id == "run-b" and created_b.status == "pending"

    decided_a = manager.decide_final_approval("run-a", "approved", approved_by="operator")
    assert decided_a.status == "approved" and decided_a.ready_for_git is True

    # run-b is untouched by run-a's approval transition.
    still_pending_b = manager.create_final_approval("run-b", "accepted")
    assert still_pending_b.run_id == "run-b"
    assert still_pending_b.status == "pending" and still_pending_b.ready_for_git is False
