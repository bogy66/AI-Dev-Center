"""Gate-1 proof meta-gate (KIA-ADC-TEST-ASSURANCE-MODEL-FIX-001 section 6).

GATE1_PROOF=IO is only meaningful when it mechanically implies ALL of:

  - every mandatory Gate-1 proof obligation is PROVEN (section 3);
  - every mandatory Gate-1 equivalence class has PASS-backed behavioral
    verification, not mere decorator registration (section 1);
  - no Pairwise/Three-Way claim in the combinatorial test suite is
    degenerate (section 4);
  - all mandatory Pairwise/Three-Way interactions are present, verified
    independently of the generator's own bookkeeping (section 5).

This module composes those three already-independently-tested checks
into one place instead of re-implementing any of them, and computes
GATE1_PROOF honestly from whatever their current combined state is --
it does not, and must not, special-case any specific obligation id to
force a green result.

Also requires current-run completion (KIA-ADC-GATE1-HARNESS-PROOF-FIX
-001 section 7, closing a masking gap KI-B identified): a mandatory
Gate-1 selector that this session deselected, skipped, failed, xfailed,
or never collected at all can no longer be masked by an older run's
persisted PASS -- see requirements/evidence/current_run_completion.py.
This means a genuinely COMPLETE current run is required for this gate
to ever reach IO; a narrower/partial pytest invocation is expected, and
required, to report real gaps here rather than a false IO.

Like tests/test_env_equivalence_classes.py, this module's own
assertions are only meaningful once every other covers()-declaring
test module has actually executed in the same session (session-scoped,
execution-order-dependent PASS-VERIFIED coverage -- see
tests/conftest.py::pytest_collection_modifyitems, which now also moves
this module's items to the very end, after
test_env_equivalence_classes.py).
"""
from __future__ import annotations

from requirements.evidence.proof_obligations import (
    build_proof_obligations, gate1_proof_summary, overall_gate1_proof_status,
)
from tests.env_scenarios import all_classes, coverage_report


def _current_run_store_root(pytestconfig):
    """The evidence store root THIS session is actually publishing to,
    when it is a genuine `--adc-evidence` run -- never silently
    defaulted away (KIA-ADC-GATE1-CONTAINMENT-GATE-SCOPING-FIX-001
    section 10, closing the masking path KI-A identified: a Gate-1
    meta-proof computed against the real, historical default store
    while the CURRENT session's own events were actually published to a
    custom/isolated --adc-evidence-store would silently never see this
    run's own results at all). Returns None only when this session
    itself never requested a non-default store (or the Evidence plugin
    is not even registered) -- in that one case, None correctly means
    "use the real default store", exactly matching every existing
    caller's pre-existing behavior for a genuine formal production run."""
    try:
        if not pytestconfig.getoption("--adc-evidence", default=False):
            return None
        return pytestconfig.getoption("--adc-evidence-store", default=None)
    except ValueError:
        return None


def test_gate1_proof_status_is_mechanically_computable_and_reported(pytestconfig):
    """Non-gating (like test_coverage_summary_is_reported): always
    passes, exists purely to print the current, real GATE1_PROOF
    breakdown for human/report consumption without asserting on it --
    the actual gate is the next test below."""
    live_report = coverage_report()
    obligations = build_proof_obligations(
        check_collectibility=True, live_equivalence_class_report=live_report,
        store_root=_current_run_store_root(pytestconfig),
    )
    summary = gate1_proof_summary(obligations)
    overall = overall_gate1_proof_status(summary)
    print(f"\nGATE1_PROOF={overall}")
    print(f"  PROVEN ({len(summary['proven'])}): {summary['proven']}")
    print(f"  PARTIAL ({len(summary['partial'])}): {summary['partial']}")
    print(f"  UNPROVEN ({len(summary['unproven'])}): {summary['unproven']}")


def test_gate1_proof_requires_every_mandatory_obligation_proven(pytestconfig):
    """The actual meta-gate. This is EXPECTED to fail whenever any real,
    currently-existing gap exists in the underlying obligations (stale
    selector-map traceability, a functionally NIO/NOT_RUN TEST_* id, or
    an uncovered high-risk equivalence class) -- that is the entire
    point of a mechanically trustworthy proof gate: it must not report
    IO while a real gap exists, and this task deliberately does not
    special-case any specific obligation id to force it green."""
    live_report = coverage_report()
    obligations = build_proof_obligations(
        check_collectibility=True, live_equivalence_class_report=live_report,
        require_current_run_completion=True,
        store_root=_current_run_store_root(pytestconfig),
    )
    summary = gate1_proof_summary(obligations)
    overall = overall_gate1_proof_status(summary)
    assert overall == "IO", (
        f"GATE1_PROOF={overall} (expected IO): "
        f"partial={summary['partial']!r}, unproven={summary['unproven']!r}"
    )


def test_gate1_owned_gate3_defect_regressions_are_contained(pytestconfig):
    """Gate-3 defect containment (requirements/evidence/
    gate3_defect_register.py): every Gate-1-owned regression of a defect
    a Real-System run exposed must still be collectible, mandatory in its
    owning TEST_* obligation, PASSED in THIS session, and that obligation
    must be PROVEN with current-run completion -- never a historical PASS
    and never a hand-set flag."""
    from requirements.evidence import current_run_completion
    from requirements.evidence.gate3_defect_register import (
        CLOSED, DEFECT_REGISTER, GATE1, evaluate_register, register_lines,
    )
    from requirements.evidence.product_runtime import collect_product_nodeids

    owned = [e for e in DEFECT_REGISTER if e.owning_gate == GATE1]
    assert owned, "the register names no Gate-1-owned defect regression"
    obligations = build_proof_obligations(
        check_collectibility=True, live_equivalence_class_report=coverage_report(),
        require_current_run_completion=True,
        store_root=_current_run_store_root(pytestconfig),
        obligation_ids=frozenset(e.owning_obligation for e in owned),
    )
    files = {s.split("::", 1)[0] for e in owned for s in e.selectors}
    files.update(s.split("::", 1)[0] for o in obligations for s in o.required_tests)
    collected = collect_product_nodeids(files)
    proofs = evaluate_register(
        GATE1, collected, current_run_completion.current_run_outcomes(),
        {o.obligation_id: o.status for o in obligations},
    )
    print("\n" + "\n".join(register_lines(proofs)))
    assert proofs and all(p.state == CLOSED for p in proofs), register_lines(proofs)


def test_no_high_risk_equivalence_class_is_uncovered_reused_from_section_1():
    """Composes (does not re-implement) the section 1 coverage gate
    already proven in tests/test_env_equivalence_classes.py, so this
    module's own failure message is self-contained without needing to
    cross-reference that file."""
    report = coverage_report()
    high_risk = {c.class_id for c in all_classes() if c.risk_category == "high"}
    uncovered_high_risk = high_risk & set(report["uncovered"])
    assert not uncovered_high_risk, (
        f"high-risk equivalence classes with no PASS-verified test: {sorted(uncovered_high_risk)}"
    )
