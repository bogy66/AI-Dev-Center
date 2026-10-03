"""Governance self-tests for the mechanical Gate-2 proof
(requirements/evidence/gate2_selector_map.py + gate2_proof.py).

The evaluator tests feed synthetic current-run outcomes to the pure
evaluation functions; they never execute the Gate-2 scope itself (that
is `python -m requirements.evidence.gate2_proof verify`). The mapping
tests resolve the real map against a real, execution-free collection.
"""
from __future__ import annotations

import pytest

from requirements.evidence.gate2_obligations import GATE2_OBLIGATIONS, Gate2Obligation
from requirements.evidence.gate2_proof import (
    PARTIAL, PROVEN, UNPROVEN, MalformedGate2SelectorMap, collect_selector_scope,
    evaluate_gate2, evaluate_obligation, expand_selector, gate2_summary,
    mandatory_nodes, validate_gate2_selector_map,
)
from requirements.evidence.gate2_selector_map import (
    GATE2_SELECTOR_MAP, RSE033_PRODUCTIVE_PATH_SELECTOR, S5_S3_PRODUCTIVE_IDENTITY_SELECTOR,
    S5_S3_PRODUCTIVE_PATH_SELECTOR, S5_S6_PRODUCTIVE_PATH_SELECTOR,
)

_CATALOG_IDS = [o.obligation_id for o in GATE2_OBLIGATIONS]
_F = "tests/test_x.py"
_COLLECTED = (f"{_F}::TestA::test_one", f"{_F}::TestA::test_two", f"{_F}::test_param[a]", f"{_F}::test_param[b]")


@pytest.fixture(scope="module")
def real_collection():
    return collect_selector_scope()


def _evaluate(outcomes, selectors=(f"{_F}::TestA", f"{_F}::test_param")):
    return evaluate_obligation("GATE2_X", selectors, _COLLECTED, outcomes)


def _all(outcome):
    return {n: outcome for n in _COLLECTED}


# A / B / C: exactly the current catalog, no unknown, no empty scope.
def test_a_every_current_obligation_is_mapped_exactly_once():
    assert len(_CATALOG_IDS) == 19
    assert sorted(GATE2_SELECTOR_MAP) == sorted(_CATALOG_IDS)
    validate_gate2_selector_map()


def test_b_unknown_or_missing_obligation_fails_closed():
    with pytest.raises(MalformedGate2SelectorMap, match="GATE2_UNKNOWN"):
        validate_gate2_selector_map({**GATE2_SELECTOR_MAP, "GATE2_UNKNOWN": (f"{_F}::t",)})
    reduced = dict(GATE2_SELECTOR_MAP)
    reduced.pop("GATE2_S5_S6")
    with pytest.raises(MalformedGate2SelectorMap, match="GATE2_S5_S6"):
        validate_gate2_selector_map(reduced)


@pytest.mark.parametrize("bad", [(), [f"{_F}::t"], (f"{_F}::t", f"{_F}::t"), ("not_a_test_path",), (f"{_F}::a b",)])
def test_c_empty_duplicate_or_malformed_scope_fails_closed(bad):
    with pytest.raises(MalformedGate2SelectorMap):
        validate_gate2_selector_map({**GATE2_SELECTOR_MAP, "GATE2_S1_S2": bad})


# D / E: stale and zero-collected selectors.
def test_d_stale_selector_fails_closed_even_if_everything_else_passed():
    proof = _evaluate(_all("PASSED"), selectors=(f"{_F}::TestA", f"{_F}::TestRenamed"))
    assert proof.status == UNPROVEN
    assert proof.stale_selectors == (f"{_F}::TestRenamed",)


def test_e_selector_collecting_zero_tests_fails_closed():
    proof = _evaluate({}, selectors=("tests/test_nothing.py",))
    assert proof.status == UNPROVEN
    assert proof.node_outcomes == ()


def test_e_the_real_map_has_no_stale_selector(real_collection):
    stale = [(o, s) for o, sels in GATE2_SELECTOR_MAP.items() for s in sels
             if not expand_selector(s, real_collection)]
    assert stale == []


# F / G / H / I: current-run gaps never become PROVEN.
def test_f_missing_current_run_result_cannot_be_proven():
    outcomes = _all("PASSED")
    outcomes.pop(f"{_F}::test_param[b]")
    proof = _evaluate(outcomes)
    assert proof.status == PARTIAL
    assert (f"{_F}::test_param[b]", "MISSING") in proof.gaps
    assert _evaluate({}).status == UNPROVEN


def test_g_failed_mandatory_node_is_unproven():
    outcomes = {**_all("PASSED"), f"{_F}::TestA::test_two": "FAILED"}
    assert _evaluate(outcomes).status == UNPROVEN


@pytest.mark.parametrize("outcome", ["SKIPPED", "XFAIL"])
def test_h_unexpected_mandatory_skip_is_not_proven(outcome):
    outcomes = {**_all("PASSED"), f"{_F}::test_param[a]": outcome}
    assert _evaluate(outcomes).status == PARTIAL


def test_i_unexpected_mandatory_deselect_is_not_proven():
    outcomes = {**_all("PASSED"), f"{_F}::TestA::test_one": "DESELECTED"}
    assert _evaluate(outcomes).status == PARTIAL


# J / K: full passes prove; a complete current run proves exactly 19.
def test_j_all_mandatory_nodes_passed_is_proven():
    proof = _evaluate(_all("PASSED"))
    assert proof.status == PROVEN
    assert len(proof.node_outcomes) == 4


def test_k_complete_current_run_proves_exactly_19(real_collection):
    nodes = mandatory_nodes(real_collection)
    proofs = evaluate_gate2(real_collection, {n: "PASSED" for n in nodes})
    summary = gate2_summary(proofs)
    assert summary["total"] == 19
    assert len(summary["proven"]) == 19
    assert summary["partial"] == summary["unproven"] == []
    assert summary["result"] == "IO"
    # ... and one missing node anywhere breaks IO.
    drop = expand_selector(S5_S6_PRODUCTIVE_PATH_SELECTOR, real_collection)[0]
    proofs = evaluate_gate2(real_collection, {n: "PASSED" for n in nodes if n != drop})
    assert gate2_summary(proofs)["result"] == "NIO"


def test_no_manual_proven_input_exists():
    tampered = GATE2_OBLIGATIONS[:-1] + (
        Gate2Obligation("GATE2_FAULT_PERMUTATIONS", "cross-cutting", "x", status="PROVEN"),
    )
    with pytest.raises(AssertionError):
        evaluate_gate2(_COLLECTED, _all("PASSED"), obligations=tampered)


# L / M: the accepted productive paths are owned and resolve to real nodes.
def test_l_s5_s6_owns_the_real_productive_composition(real_collection):
    assert GATE2_SELECTOR_MAP["GATE2_S5_S6"] == (S5_S6_PRODUCTIVE_PATH_SELECTOR,)
    nodes = expand_selector(S5_S6_PRODUCTIVE_PATH_SELECTOR, real_collection)
    assert {n.rsplit("::", 1)[1] for n in nodes} == {
        "test_accepted_real_s5_result_opens_real_s6_final_approval",
        "test_real_deterministic_s5_failure_never_reaches_s6",
    }


def test_m_fault_permutations_owns_the_rse033_defect_shape(real_collection):
    assert RSE033_PRODUCTIVE_PATH_SELECTOR in GATE2_SELECTOR_MAP["GATE2_FAULT_PERMUTATIONS"]
    nodes = expand_selector(RSE033_PRODUCTIVE_PATH_SELECTOR, real_collection)
    assert {n.rsplit("[", 1)[1] for n in nodes} == {"repaired]", "fail-closed]"}
    assert set(nodes) <= set(mandatory_nodes(real_collection))


def test_n_s5_s3_recovery_owns_the_real_productive_path(real_collection):
    """GATE2_S5_S3_BOUNDED_RECOVERY is never proven by artifact/status-only
    tests alone: the Web -> execute_approved_plan_from_store -> S5 ->
    S3.5 Productive-Path is part of its mandatory scope, and the distinct
    identity roundtrip is owned by the existing S2.5 -> S3 identity
    obligation -- no new Gate-2 obligation."""
    assert len(GATE2_OBLIGATIONS) == 19
    scope = GATE2_SELECTOR_MAP["GATE2_S5_S3_BOUNDED_RECOVERY"]
    assert scope[0] == S5_S3_PRODUCTIVE_PATH_SELECTOR
    nodes = expand_selector(S5_S3_PRODUCTIVE_PATH_SELECTOR, real_collection)
    assert {n.rsplit("::", 1)[1] for n in nodes} == {
        "test_web_execution_routes_tool_unavailable_to_approval_bound_recovery_with_distinct_identities",
        "test_failed_reverification_ends_recovery_fail_closed_without_a_second_cycle",
        "test_missing_planning_provenance_fails_closed_before_any_recovery",
    }
    assert set(nodes) <= set(mandatory_nodes(real_collection))
    assert S5_S3_PRODUCTIVE_IDENTITY_SELECTOR in GATE2_SELECTOR_MAP["GATE2_S2_5_S3_IDENTITY"]
    # Dropping the productive node leaves the recovery obligation unproven.
    drop = expand_selector(S5_S3_PRODUCTIVE_IDENTITY_SELECTOR, real_collection)[0]
    proofs = evaluate_gate2(real_collection, {n: "PASSED" for n in mandatory_nodes(real_collection) if n != drop})
    by_id = {p.obligation_id: p.status for p in proofs}
    assert by_id["GATE2_S5_S3_BOUNDED_RECOVERY"] != PROVEN
    assert by_id["GATE2_S2_5_S3_IDENTITY"] != PROVEN
