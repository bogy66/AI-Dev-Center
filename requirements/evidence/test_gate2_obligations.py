"""Tests for the Gate-2 obligation REPRESENTATION
(KIA-ADC-TEST-ASSURANCE-MODEL-FIX-001 section 7). These tests never run
Gate 2, Real-System-E2E, or any live workflow -- they only check the
catalog's own shape and this task's own constraint that no Gate-2
obligation may be marked proven here.
"""
from __future__ import annotations

import pytest

from requirements.evidence.gate2_obligations import (
    GATE2_OBLIGATIONS, GATE2_STATUS_NOT_YET_EXECUTED, Gate2Obligation,
    assert_none_marked_proven,
)


def test_every_obligation_id_is_unique():
    ids = [o.obligation_id for o in GATE2_OBLIGATIONS]
    assert len(ids) == len(set(ids))


def test_every_obligation_has_a_handoff_and_description():
    for o in GATE2_OBLIGATIONS:
        assert o.handoff
        assert o.description


def test_no_obligation_is_marked_proven_by_this_task():
    for o in GATE2_OBLIGATIONS:
        assert o.status == GATE2_STATUS_NOT_YET_EXECUTED
    assert_none_marked_proven()  # must not raise


def test_assert_none_marked_proven_detects_a_violation():
    tampered = GATE2_OBLIGATIONS[:1] + (
        Gate2Obligation("GATE2_FAKE", "X -> Y", "should never be proven here", status="PROVEN"),
    )
    with pytest.raises(AssertionError, match="GATE2_FAKE"):
        assert_none_marked_proven(tampered)


def test_the_named_pipeline_handoffs_from_the_task_spec_are_all_represented():
    handoffs = {o.handoff for o in GATE2_OBLIGATIONS}
    assert "S1 -> S2" in handoffs
    assert "S5 -> S6" in handoffs
    ids = {o.obligation_id for o in GATE2_OBLIGATIONS}
    for cross_cutting in ("GATE2_WEB", "GATE2_MCP", "GATE2_RETRY_IDEMPOTENCY", "GATE2_CROSS_PROCESS"):
        assert cross_cutting in ids
