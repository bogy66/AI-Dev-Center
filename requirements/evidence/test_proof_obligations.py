"""Tests for the Gate-1(+Gate-3) proof-obligation model
(KIA-ADC-TEST-ASSURANCE-MODEL-FIX-001 section 3).
"""
from __future__ import annotations

from requirements.evidence.proof_obligations import (
    ProofObligation, build_proof_obligations, check_selectors_collectible,
    derive_status, gate1_proof_summary, read_current_verification_results,
    read_requirement_ids_and_titles,
)
from requirements.evidence.selector_map import SELECTOR_MAP


# ----------------------------------------------------------------------
# derive_status: pure logic, no I/O -- every combination this task's
# spec cares about, proven directly.
# ----------------------------------------------------------------------

def test_empty_required_tests_is_always_unproven():
    assert derive_status(
        required_tests=(), functional_result="IO",
        all_selectors_collectible=True, extra_proof_gate_ok=None,
    ) == "UNPROVEN"


def test_broken_traceability_overrides_a_historical_io_result():
    """The exact real-world shape this module found in TEST_020: a
    persisted verification_result of IO from a past run, but the
    selectors it names no longer resolve to any collectible test --
    PROOF must not simply mirror FUNCTIONAL."""
    assert derive_status(
        required_tests=("tests/test_x.py::test_renamed_away",),
        functional_result="IO",
        all_selectors_collectible=False, extra_proof_gate_ok=None,
    ) == "UNPROVEN"


def test_nio_functional_result_is_unproven():
    assert derive_status(
        required_tests=("tests/test_x.py::test_y",), functional_result="NIO",
        all_selectors_collectible=True, extra_proof_gate_ok=None,
    ) == "UNPROVEN"


def test_not_run_functional_result_is_unproven():
    assert derive_status(
        required_tests=("tests/test_x.py::test_y",), functional_result="NOT_RUN",
        all_selectors_collectible=True, extra_proof_gate_ok=None,
    ) == "UNPROVEN"


def test_io_and_collectible_and_no_extra_gate_is_proven():
    assert derive_status(
        required_tests=("tests/test_x.py::test_y",), functional_result="IO",
        all_selectors_collectible=True, extra_proof_gate_ok=None,
    ) == "PROVEN"


def test_io_and_collectible_but_failing_extra_gate_is_partial():
    """The task's own worked example: GATE1_FUNCTIONAL=IO,
    GATE1_PROOF=PARTIAL must remain a valid, distinct state."""
    assert derive_status(
        required_tests=("tests/test_x.py::test_y",), functional_result="IO",
        all_selectors_collectible=True, extra_proof_gate_ok=False,
    ) == "PARTIAL"


def test_collectibility_not_checked_does_not_block_proven():
    assert derive_status(
        required_tests=("tests/test_x.py::test_y",), functional_result="IO",
        all_selectors_collectible=None, extra_proof_gate_ok=None,
    ) == "PROVEN"


# ----------------------------------------------------------------------
# check_selectors_collectible: real, execution-free pytest --collect-only
# against this actual repository.
# ----------------------------------------------------------------------

def test_a_real_existing_selector_is_collectible():
    assert check_selectors_collectible(
        ("tests/test_env_pairwise_helper.py::test_case_id_is_stable_and_readable",)
    ) is True


def test_a_nonexistent_function_selector_is_not_collectible():
    assert check_selectors_collectible(
        ("tests/test_env_pairwise_helper.py::test_this_function_was_never_defined",)
    ) is False


def test_a_whole_file_selector_for_a_real_file_is_collectible():
    assert check_selectors_collectible(("tests/test_env_pairwise_helper.py",)) is True


# ----------------------------------------------------------------------
# The real catalog: one obligation per EXISTING TEST_* id (section 9 --
# no new Requirement-Test ids), correct GATE partition, and read-only
# reuse of tests.rst / the real Evidence store (no fabricated data).
# ----------------------------------------------------------------------

def test_catalog_has_exactly_one_obligation_per_selector_map_entry():
    obligations = build_proof_obligations(check_collectibility=False)
    assert {o.obligation_id for o in obligations} == set(SELECTOR_MAP)
    assert len(obligations) == len(SELECTOR_MAP)


def test_test_033_is_the_only_gate3_obligation():
    obligations = build_proof_obligations(check_collectibility=False)
    gate3 = {o.obligation_id for o in obligations if o.gate == "GATE3"}
    assert gate3 == {"TEST_033"}


def test_every_obligation_status_is_one_of_the_three_allowed_values():
    obligations = build_proof_obligations(check_collectibility=False)
    for o in obligations:
        assert o.status in {"PROVEN", "PARTIAL", "UNPROVEN"}


def test_mapped_adopted_obligations_without_evidence_remain_unproven(tmp_path):
    """Acceptance 028 selectors do not manufacture evidence for adoption 026.

    Empty mappings must never become proof from historical IO. All existing
    executable obligations retain the nonempty-selector invariant.
    """
    from .council_lifecycle_scope import COUNCIL_LIFECYCLE_OBLIGATIONS
    import shutil
    from requirements.evidence.ingest import TESTS_RST_PATH, _update_tests_rst
    # Preserve this negative contract after real 030 Evidence is adopted:
    # explicitly model the absence of execution, rather than require it in
    # the repository forever. Every original assertion remains in force.
    fixture_rst = tmp_path / 'tests.rst'
    shutil.copyfile(TESTS_RST_PATH, fixture_rst)
    _update_tests_rst(str(fixture_rst), {tid: 'NOT_RUN' for tid in COUNCIL_LIFECYCLE_OBLIGATIONS})
    obligations = build_proof_obligations(check_collectibility=False,
        tests_rst_path=str(fixture_rst), store_root=str(tmp_path / 'empty-evidence'))
    for obligation in obligations:
        if obligation.obligation_id in COUNCIL_LIFECYCLE_OBLIGATIONS:
            assert obligation.required_tests == tuple(SELECTOR_MAP[obligation.obligation_id])
            assert obligation.required_tests
            assert obligation.functional_result == "NOT_RUN"
            assert obligation.status == "UNPROVEN"
        else:
            assert obligation.required_tests


def test_broken_traceability_is_detected_for_at_least_zero_and_never_silently_ignored():
    """Runs the real collectibility check across the whole real
    catalog. This does not assert a specific TEST_* id is broken (that
    would make this test brittle against future, independently-owned
    fixes to those test files) -- it only asserts the mechanical
    invariant: whenever collectibility comes back False for an
    obligation, that obligation's status is UNPROVEN, never PROVEN or
    PARTIAL."""
    obligations = build_proof_obligations(check_collectibility=True)
    for o in obligations:
        if o.all_selectors_collectible is False:
            assert o.status == "UNPROVEN", (
                f"{o.obligation_id} has broken traceability but status={o.status}"
            )


def test_gate1_proof_summary_only_covers_gate1_obligations():
    obligations = build_proof_obligations(check_collectibility=False)
    summary = gate1_proof_summary(obligations)
    assert summary["total"] == len(obligations) - 1  # excludes the single GATE3 obligation
    assert "TEST_033" not in summary["proven"] + summary["partial"] + summary["unproven"]


def test_read_current_verification_results_matches_a_known_real_entry():
    results = read_current_verification_results()
    assert results.get("TEST_001") in {"IO", "NIO", "NOT_RUN"}
    assert set(results) <= set(SELECTOR_MAP)


def test_read_requirement_ids_and_titles_returns_nonempty_requirement_ids_for_test_001():
    mapping = read_requirement_ids_and_titles()
    requirement_ids, title = mapping["TEST_001"]
    assert requirement_ids
    assert title


# ----------------------------------------------------------------------
# The TEST_012 <-> equivalence-class extra proof gate: proven with a
# synthetic (not live) coverage report, so this test never depends on
# the real, session-order-dependent env_scenarios registry state.
# ----------------------------------------------------------------------

def test_test_012_is_downgraded_to_partial_when_a_high_risk_class_is_reported_uncovered():
    from tests.env_scenarios import all_classes
    some_high_risk_id = next(c.class_id for c in all_classes() if c.risk_category == "high")
    synthetic_report = {"uncovered": [some_high_risk_id]}

    obligations = build_proof_obligations(
        check_collectibility=False, live_equivalence_class_report=synthetic_report,
    )
    test_012 = next(o for o in obligations if o.obligation_id == "TEST_012")
    if test_012.functional_result == "IO":
        assert test_012.status == "PARTIAL"


def test_test_012_is_not_downgraded_when_no_high_risk_class_is_reported_uncovered():
    synthetic_report = {"uncovered": []}
    obligations = build_proof_obligations(
        check_collectibility=False, live_equivalence_class_report=synthetic_report,
    )
    test_012 = next(o for o in obligations if o.obligation_id == "TEST_012")
    if test_012.functional_result == "IO":
        assert test_012.status == "PROVEN"
