"""Focused regression coverage for the Gate-1 proof-accounting
fail-closed invariant (KIA-ADC-GATE1-HARNESS-PROOF-FIX-001 section 5/6,
test items J/K/L).
"""
from __future__ import annotations

import pytest

from requirements.evidence.proof_obligations import (
    GATE1_OBLIGATION_IDS, MalformedGate1ProofSummary, overall_gate1_proof_status,
)
from requirements.evidence.selector_map import SELECTOR_MAP


# ----------------------------------------------------------------------
# J. The exact historical defect shape: a total EXCEEDING the real
# Gate-1-filtered population (the historical case: unfiltered SELECTOR_MAP
# count 33 vs the then-32-entry proven list) -- must never yield IO.
# ----------------------------------------------------------------------

def test_malformed_total_exceeding_population_summary_cannot_yield_io():
    malformed_summary = {
        "total": len(GATE1_OBLIGATION_IDS) + 1,
        "proven": sorted(GATE1_OBLIGATION_IDS),
        "partial": [],
        "unproven": [],
    }
    with pytest.raises(MalformedGate1ProofSummary):
        overall_gate1_proof_status(malformed_summary)


def test_summary_with_mismatched_total_but_no_unproven_or_partial_still_fails_closed():
    """Even when unproven/partial are both empty (the shape that made
    the old bug look green), a total that doesn't match the real
    population must never be silently accepted."""
    malformed_summary = {
        "total": len(SELECTOR_MAP),  # the whole, UNFILTERED catalog (population + the Gate-3 TEST_033)
        "proven": sorted(GATE1_OBLIGATION_IDS),
        "partial": [],
        "unproven": [],
    }
    with pytest.raises(MalformedGate1ProofSummary):
        overall_gate1_proof_status(malformed_summary)


# ----------------------------------------------------------------------
# K. The correct, scoped Gate-1 summary yields IO.
# ----------------------------------------------------------------------

def test_correct_scoped_summary_matching_population_is_io():
    valid_summary = {
        "total": len(GATE1_OBLIGATION_IDS),
        "proven": sorted(GATE1_OBLIGATION_IDS),
        "partial": [],
        "unproven": [],
    }
    assert GATE1_OBLIGATION_IDS == frozenset({f"TEST_{i:03d}" for i in range(1, 35)} - {"TEST_033"}) | frozenset({f"TEST_{i:03d}" for i in range(36, 41)})
    assert overall_gate1_proof_status(valid_summary) == "IO"


def test_a_partial_obligation_prevents_io():
    ids = sorted(GATE1_OBLIGATION_IDS)
    summary = {
        "total": len(ids),
        "proven": ids[1:],
        "partial": [ids[0]],
        "unproven": [],
    }
    assert overall_gate1_proof_status(summary) == "PARTIAL"


def test_an_unproven_obligation_prevents_io_even_with_correct_total():
    ids = sorted(GATE1_OBLIGATION_IDS)
    summary = {
        "total": len(ids),
        "proven": ids[1:],
        "partial": [],
        "unproven": [ids[0]],
    }
    assert overall_gate1_proof_status(summary) == "NIO"


def test_a_fully_proven_but_incomplete_population_cannot_yield_io():
    """31 correct ids, structurally self-consistent (total matches the
    population), but missing one mandatory obligation -- must not be
    accepted as a complete Gate-1 IO claim."""
    ids = sorted(GATE1_OBLIGATION_IDS)[:-1]
    summary = {"total": len(ids), "proven": ids, "partial": [], "unproven": []}
    with pytest.raises(MalformedGate1ProofSummary):
        overall_gate1_proof_status(summary)


def test_non_collection_proven_value_is_rejected_as_malformed():
    """A bare count instead of an explicit id collection (another shape
    the historical ad-hoc diagnostic could have produced) must fail
    closed rather than being silently accepted."""
    summary = {"total": len(GATE1_OBLIGATION_IDS), "proven": len(GATE1_OBLIGATION_IDS), "partial": 0, "unproven": 0}
    with pytest.raises(MalformedGate1ProofSummary):
        overall_gate1_proof_status(summary)


# ----------------------------------------------------------------------
# L. TEST_033 remains excluded from Gate-1 / remains Gate-3.
# ----------------------------------------------------------------------

def test_test_033_is_excluded_from_the_gate1_obligation_population():
    assert "TEST_033" in SELECTOR_MAP
    assert "TEST_033" not in GATE1_OBLIGATION_IDS


def test_gate1_obligation_ids_includes_the_four_adopted_contracts():
    """CLAUDE-ADC-YELLOW-VERIFICATION-CLOSURE-IMPLEMENT-001: the
    mandatory Gate-1 population consciously grew from 32 to 33 when
    TEST_034 (IF_REQ_001 request identity + run-scoped correlation)
    joined the selector map. Adoption 026 added TEST_036–039 and TEST_040 (target-environment contract) joined later;
    acceptance 028 now requires their full selector scope as well."""
    assert GATE1_OBLIGATION_IDS == frozenset({f"TEST_{i:03d}" for i in range(1, 35)} - {"TEST_033"}) | frozenset({f"TEST_{i:03d}" for i in range(36, 41)})
