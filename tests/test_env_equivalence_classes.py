"""Coverage meta-test for tests/env_scenarios.py's equivalence-class
catalog (CLAUDE-ADC-TEST-ENVIRONMENT-FIDELITY-UPGRADE-001 section 2,
tightened by KIA-ADC-TEST-ASSURANCE-MODEL-FIX-001 section 1):
"The test infrastructure must make it possible to answer mechanically:
Which classes exist? Which classes have tests that actually PASSED?
Which classes remain uncovered?"

`covers(...)` only DECLARES a mapping at IMPORT/COLLECTION time; actual
coverage is PASS-VERIFIED at test 'call'-phase time by
tests/conftest.py::pytest_runtest_makereport, which observes each
test's real pytest outcome and calls
tests.env_scenarios.record_test_outcome(). A failed, skipped, or
xfailed test is therefore never promoted to covered (see
tests/test_env_coverage_pass_verification.py for the end-to-end
proof).

Because coverage now depends on EXECUTION order, not just import
order, this module must run AFTER every other test declaring coverage
via covers() has actually been executed by pytest in this session --
tests/conftest.py::pytest_collection_modifyitems moves this module's
items to the end of the run for exactly that reason. This means these
assertions are only meaningful for a session that actually ran the
covering test modules (e.g. the whole tests/ package, or at least
every tests/test_env_*.py file plus this one) -- running this file in
isolation will correctly report every class as uncovered, since none
of its covering tests will have executed.
"""
from __future__ import annotations

from tests.env_scenarios import ALL_DIMENSIONS, all_classes, coverage_report


def test_every_dimension_has_at_least_one_class():
    for dimension, classes in ALL_DIMENSIONS.items():
        assert len(classes) > 0, f"dimension {dimension} has no equivalence classes defined"


def test_no_duplicate_class_ids():
    ids = [c.class_id for c in all_classes()]
    assert len(ids) == len(set(ids)), "duplicate class_id values found"


def test_every_class_has_all_required_fields():
    for c in all_classes():
        assert c.class_id
        assert c.dimension
        assert c.representative
        assert c.expected_invariant
        assert c.risk_category in {"high", "medium", "low"}


def test_coverage_report_is_mechanically_queryable():
    report = coverage_report()
    assert set(report) == {
        "total", "covered", "uncovered", "declared_but_not_pass_verified", "sources",
    }
    assert report["total"] == len(all_classes())
    assert isinstance(report["covered"], list)
    assert isinstance(report["uncovered"], list)
    assert set(report["covered"]) | set(report["uncovered"]) == {c.class_id for c in all_classes()}
    # declared_but_not_pass_verified is a strict subset of uncovered: a class
    # can be declared (via covers()) yet still not PASS-VERIFIED, but it can
    # never be simultaneously covered AND flagged as not-pass-verified.
    assert set(report["declared_but_not_pass_verified"]) <= set(report["uncovered"])


def test_high_risk_classes_are_all_covered():
    """The mandatory bar this task sets: every HIGH-risk equivalence
    class must have at least one test exercising it, tracked via
    `covers(...)`. A class newly added to env_scenarios.py without a
    corresponding test will fail this exact assertion, by class_id, the
    moment it is collected -- this is the mechanical "no silently
    uncovered mandatory class" check."""
    report = coverage_report()
    high_risk = {c.class_id for c in all_classes() if c.risk_category == "high"}
    uncovered_high_risk = high_risk & set(report["uncovered"])
    assert not uncovered_high_risk, (
        f"high-risk equivalence classes with no covering test: {sorted(uncovered_high_risk)}"
    )


def test_coverage_summary_is_reported():
    """Not a pass/fail gate by itself -- prints the full coverage
    picture (including medium/low-risk gaps, which are legitimate
    TEST_COVERAGE_GAP territory, not failures) for human/report
    consumption."""
    report = coverage_report()
    print(f"\nEquivalence class coverage: {len(report['covered'])}/{report['total']} covered")
    if report["uncovered"]:
        print(f"Uncovered: {sorted(report['uncovered'])}")
