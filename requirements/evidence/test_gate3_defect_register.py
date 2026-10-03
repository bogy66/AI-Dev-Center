"""Fail-closed self-tests for the Gate-3 defect -> lower-gate register
(requirements/evidence/gate3_defect_register.py).

Synthetic current-run inputs drive the pure evaluation; the real-register
tests resolve the real selectors against a real, execution-free product
collection (requirements/evidence/product_runtime.py)."""
from __future__ import annotations

from dataclasses import replace

import pytest

from requirements.evidence.gate2_proof import mandatory_nodes
from requirements.evidence.gate3_defect_register import (
    CLOSED, DEFECT_REGISTER, EXECUTION_ERROR_CLASSIFICATION, FAILED_REVERIFICATION_CONTAINMENT,
    FINAL_CHILD_STATUS_FIDELITY, NO_VERDICT_AS_ABSENCE_CLASSIFICATION,
    GATE1, GATE2,
    INSTALLER_REGISTRY_RESOLUTION_DEFECT, MISSING_RECOVERY_COMPOSITION, OPEN,
    PROCESS_TIMEOUT_DESCENDANT_CLEANUP, RSE033_COMPILE_TIMEOUT_DEFECT_ID,
    RSE033_INSTALLER_RECOVERY_DEFECT_ID, TIMEOUT_REWORK_CLASSIFICATION,
    VERIFICATION_BUDGET_POLICY_ESCAPE, LowerGateRegression, MalformedDefectRegister,
    evaluate_entry, evaluate_register, mandatory_scope, validate_register,
)
from requirements.evidence.product_runtime import collect_product_nodeids
from requirements.evidence.selector_map import SELECTOR_MAP

_NODE = "tests/test_missing_toolchain_setup.py::test_failed_reverification_never_reports_recovery_completed"
_COLLECTED = (f"{_NODE}[fail]", f"{_NODE}[unsupported]",
              "tests/test_missing_toolchain_setup.py::test_setup_cannot_execute_before_approval")
_ENTRY = LowerGateRegression("DEF-X", FAILED_REVERIFICATION_CONTAINMENT, GATE1, "TEST_014", (_NODE,))


def _passed(nodes=_COLLECTED):
    return {n: "PASSED" for n in nodes}


def test_valid_mandatory_passing_regression_with_proven_owner_is_closed():
    proof = evaluate_entry(_ENTRY, _COLLECTED, _passed(), {"TEST_014": "PROVEN"})
    assert proof.state == CLOSED
    assert proof.reasons == ()
    assert [n for n, _ in proof.node_outcomes] == [f"{_NODE}[fail]", f"{_NODE}[unsupported]"]


def test_stale_node_is_open():
    entry = replace(_ENTRY, selectors=(_NODE, "tests/test_missing_toolchain_setup.py::test_renamed_away"))
    proof = evaluate_entry(entry, _COLLECTED, _passed(), {"TEST_014": "PROVEN"})
    assert proof.state == OPEN
    assert "stale or zero-node selector tests/test_missing_toolchain_setup.py::test_renamed_away" in proof.reasons


def test_zero_collected_selector_is_open():
    proof = evaluate_entry(_ENTRY, (), {}, {"TEST_014": "PROVEN"})
    assert proof.state == OPEN
    assert proof.node_outcomes == ()


@pytest.mark.parametrize("outcome", ["FAILED", "SKIPPED", "XFAIL", "DESELECTED"])
def test_failing_or_unexecuted_regression_is_not_closed(outcome):
    outcomes = {**_passed(), f"{_NODE}[unsupported]": outcome}
    proof = evaluate_entry(_ENTRY, _COLLECTED, outcomes, {"TEST_014": "PROVEN"})
    assert proof.state == OPEN
    assert f"{outcome} {_NODE}[unsupported]" in proof.reasons
    missing = dict(_passed())
    missing.pop(f"{_NODE}[fail]")
    assert evaluate_entry(_ENTRY, _COLLECTED, missing, {"TEST_014": "PROVEN"}).state == OPEN


@pytest.mark.parametrize("status", [{"TEST_014": "UNPROVEN"}, {"TEST_014": "PARTIAL"}, {}])
def test_missing_lower_gate_proof_is_not_closed(status):
    proof = evaluate_entry(_ENTRY, _COLLECTED, _passed(), status)
    assert proof.state == OPEN
    assert any("owning obligation TEST_014" in reason for reason in proof.reasons)


def test_node_outside_the_owning_mandatory_scope_is_not_closed():
    foreign = "tests/test_s5_subsubsystem_architecture.py::TestS5_to_S3_Boundary::test_x"
    entry = replace(_ENTRY, selectors=(foreign,))
    proof = evaluate_entry(entry, (*_COLLECTED, foreign), _passed((*_COLLECTED, foreign)), {"TEST_014": "PROVEN"})
    assert proof.state == OPEN
    assert f"not mandatory in TEST_014: {foreign}" in proof.reasons


def test_there_is_no_manual_closed_escape_hatch():
    with pytest.raises(TypeError):
        LowerGateRegression("DEF-X", FAILED_REVERIFICATION_CONTAINMENT, GATE1, "TEST_014", (_NODE,), closed=True)
    assert not hasattr(_ENTRY, "state")


@pytest.mark.parametrize("bad", [
    (),
    (replace(_ENTRY, owning_gate="GATE3"),),
    (replace(_ENTRY, owning_obligation="TEST_999"),),
    (replace(_ENTRY, owning_obligation="TEST_033"),),
    (replace(_ENTRY, owning_gate=GATE2),),
    (replace(_ENTRY, selectors=()),),
    (replace(_ENTRY, selectors=(_NODE, _NODE)),),
    (replace(_ENTRY, selectors=(SELECTOR_MAP["TEST_033"][0],)),),
    (replace(_ENTRY, selectors=("tests/test_missing_toolchain_setup.py",)),),
])
def test_malformed_register_fails_closed(bad):
    with pytest.raises(MalformedDefectRegister):
        validate_register(bad)


@pytest.mark.parametrize("dropped", [
    MISSING_RECOVERY_COMPOSITION, VERIFICATION_BUDGET_POLICY_ESCAPE,
    PROCESS_TIMEOUT_DESCENDANT_CLEANUP, TIMEOUT_REWORK_CLASSIFICATION,
    EXECUTION_ERROR_CLASSIFICATION, NO_VERDICT_AS_ABSENCE_CLASSIFICATION, FINAL_CHILD_STATUS_FIDELITY,
])
def test_register_must_cover_every_proven_defect_class(dropped):
    without = tuple(e for e in DEFECT_REGISTER if e.defect_class != dropped)
    with pytest.raises(MalformedDefectRegister, match=dropped):
        validate_register(without)


# ---------------------------------------------------------------------------
# The real register.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def real_collection():
    from requirements.evidence.gate2_selector_map import GATE2_SELECTOR_MAP
    files = {s.split("::", 1)[0] for e in DEFECT_REGISTER for s in e.selectors}
    files.update(s.split("::", 1)[0] for s in SELECTOR_MAP["TEST_014"])
    files.update(s.split("::", 1)[0] for s in GATE2_SELECTOR_MAP["GATE2_S5_S3_BOUNDED_RECOVERY"])
    return collect_product_nodeids(files)


def test_real_register_covers_every_proven_defect_class_at_lower_gates():
    validate_register()
    by_class = {}
    for entry in DEFECT_REGISTER:
        by_class.setdefault((entry.defect_id, entry.defect_class), set()).add(entry.owning_gate)
    installer, timeout = RSE033_INSTALLER_RECOVERY_DEFECT_ID, RSE033_COMPILE_TIMEOUT_DEFECT_ID
    assert by_class == {
        (installer, INSTALLER_REGISTRY_RESOLUTION_DEFECT): {GATE1, GATE2},
        (installer, MISSING_RECOVERY_COMPOSITION): {GATE2},
        (installer, FAILED_REVERIFICATION_CONTAINMENT): {GATE1, GATE2},
        (timeout, VERIFICATION_BUDGET_POLICY_ESCAPE): {GATE1},
        (timeout, PROCESS_TIMEOUT_DESCENDANT_CLEANUP): {GATE1, GATE2},
        (timeout, TIMEOUT_REWORK_CLASSIFICATION): {GATE1, GATE2},
        (timeout, EXECUTION_ERROR_CLASSIFICATION): {GATE1, GATE2},
        # Deterministic boundary/fault classes: Gate 1 owns them; no new
        # Gate-2 obligation is created for them.
        (timeout, NO_VERDICT_AS_ABSENCE_CLASSIFICATION): {GATE1},
        (timeout, FINAL_CHILD_STATUS_FIDELITY): {GATE1},
    }


def test_real_registered_nodes_exist_and_are_mandatory_in_their_owning_obligation(real_collection):
    for entry in DEFECT_REGISTER:
        proof = evaluate_entry(
            entry, real_collection, _passed(real_collection), {entry.owning_obligation: "PROVEN"},
        )
        assert proof.state == CLOSED, (entry, proof.reasons)
        assert set(n for n, _ in proof.node_outcomes) <= mandatory_scope(entry, real_collection)
    gate2 = set(mandatory_nodes(real_collection))
    assert all(
        {n for n, _ in evaluate_entry(e, real_collection, {}, {}).node_outcomes} <= gate2
        for e in DEFECT_REGISTER if e.owning_gate == GATE2
    )


def test_real_register_is_open_when_a_current_run_misses_a_regression(real_collection):
    proven = {e.owning_obligation: "PROVEN" for e in DEFECT_REGISTER if e.owning_gate == GATE1}
    gate1 = evaluate_register(GATE1, real_collection, _passed(real_collection), proven)
    assert gate1 and all(p.state == CLOSED for p in gate1)
    for index, proof in enumerate(gate1):
        dropped = next(iter(proof.node_outcomes))[0]
        outcomes = {n: "PASSED" for n in real_collection if n != dropped}
        assert evaluate_register(GATE1, real_collection, outcomes, proven)[index].state == OPEN
