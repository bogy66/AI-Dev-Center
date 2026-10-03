"""Meta-proof for KIA-ADC-TEST-ASSURANCE-MODEL-FIX-001 section 1:
"An equivalence class may count as COVERED only when at least one
mapped behavioral test was collected, was actually executed, completed
with PASS, and is mapped to the declared behavioral contract. A
failed/skipped/xfailed/not-executed test must NOT satisfy coverage."

These tests run REAL, isolated pytest subprocesses (via the `pytester`
fixture) that reuse this repository's own production
tests/conftest.py::pytest_runtest_makereport hook object directly
(imported, not re-implemented) against small probe test files. This
proves the actual production wiring behaves correctly end-to-end,
rather than re-testing a parallel re-implementation of the same idea.
"""
from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TESTS_DIR = Path(__file__).resolve().parent


def test_no_class_level_covers_decorations():
    """Regression guard: covers() must decorate individual test
    FUNCTIONS/METHODS, never a whole class. A class-level covers() call
    is registered under the class's own qualname, which never matches
    any individual test method's item.function identity at
    'call'-phase report time -- so it can now never PASS-VERIFY
    anything (see tests/conftest.py::pytest_runtest_makereport), no
    matter how many of its methods actually pass. This exact pattern
    (previously on TestMissingToolchainRecoveryStateMachine in
    tests/test_env_state_machine.py and TestRealCrossProcessRace in
    tests/test_execution_target_authorization_cross_process.py) is why
    this check exists: catch it mechanically instead of relying on
    someone noticing silently-uncovered high-risk classes."""
    offenders = []
    for path in sorted(_TESTS_DIR.glob("test_*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for deco in node.decorator_list:
                call_target = deco.func if isinstance(deco, ast.Call) else deco
                name = getattr(call_target, "id", None) or getattr(call_target, "attr", None)
                if name == "covers":
                    offenders.append(f"{path.name}::{node.name}")
    assert not offenders, f"covers() must decorate test functions/methods, not classes: {offenders}"

_CHILD_CONFTEST = f"""
import sys
sys.path.insert(0, {str(_REPO_ROOT)!r})
from tests.conftest import pytest_runtest_makereport  # noqa: F401  (reuse, not reimplementation)
"""

_IMPORT_PREAMBLE = f"""
import sys
sys.path.insert(0, {str(_REPO_ROOT)!r})
"""


def test_failed_skipped_xfailed_never_promote_coverage(pytester):
    pytester.makeconftest(_CHILD_CONFTEST)
    pytester.makepyfile(test_probe_negative=_IMPORT_PREAMBLE + """
import pytest
from tests.env_scenarios import covers

@covers("ARGV_LONG_ARGUMENT")
def test_failing():
    assert False

@covers("ARGV_LONG_ARGUMENT")
@pytest.mark.skip(reason="probe: must not count as coverage")
def test_skipped():
    assert False

@covers("ARGV_LONG_ARGUMENT")
@pytest.mark.xfail(reason="probe: must not count as coverage", strict=False)
def test_xfailed():
    assert False

def test_report_shows_no_coverage():
    from tests.env_scenarios import coverage_report
    report = coverage_report()
    assert "ARGV_LONG_ARGUMENT" not in report["covered"], report
    assert "ARGV_LONG_ARGUMENT" in report["uncovered"], report
""")
    result = pytester.runpytest_subprocess("-p", "no:cacheprovider")
    result.assert_outcomes(failed=1, skipped=1, xfailed=1, passed=1)


def test_single_real_pass_among_failures_promotes_coverage(pytester):
    pytester.makeconftest(_CHILD_CONFTEST)
    pytester.makepyfile(test_probe_positive=_IMPORT_PREAMBLE + """
import pytest
from tests.env_scenarios import covers

@covers("ARGV_LONG_ARGUMENT")
def test_failing():
    assert False

@covers("ARGV_LONG_ARGUMENT")
@pytest.mark.skip(reason="probe")
def test_skipped():
    assert False

@covers("ARGV_LONG_ARGUMENT")
def test_passing():
    assert True

def test_report_shows_coverage_from_the_pass_alone():
    from tests.env_scenarios import coverage_report
    report = coverage_report()
    assert "ARGV_LONG_ARGUMENT" in report["covered"], report
""")
    result = pytester.runpytest_subprocess("-p", "no:cacheprovider")
    result.assert_outcomes(failed=1, skipped=1, passed=2)


def _dummy_probe_function():
    pass


def test_xpass_does_not_promote_coverage():
    """An XPASS (xfail-marked test that unexpectedly succeeds) is
    reported by pytest with report.outcome == "passed" but carries a
    non-None report.wasxfail attribute -- the hook must treat that as
    NOT a genuine pass, per section 1's ban on xfailed tests satisfying
    coverage. Drives the real production hookwrapper generator directly
    (not a reimplementation) with a synthetic XPASS-shaped report."""

    class _FakeReport:
        outcome = "passed"
        wasxfail = "unexpectedly passed"

    class _FakeOutcome:
        def get_result(self):
            return _FakeReport()

    class _FakeCall:
        when = "call"

    class _FakeItem:
        function = _dummy_probe_function

    from tests import env_scenarios
    from tests.conftest import pytest_runtest_makereport

    class_id = "ARGV_LONG_ARGUMENT"
    key = f"{_dummy_probe_function.__module__}::{_dummy_probe_function.__qualname__}"

    # Snapshot and restore every registry this probe touches, so it can
    # never leave a real (already-earned, or not-yet-earned) class's
    # PASS-VERIFIED status altered for the rest of this pytest session,
    # regardless of assertion outcome.
    declared_before = dict(env_scenarios._DECLARED_COVERAGE)
    pass_verified_before = set(env_scenarios._PASS_VERIFIED_CLASS_IDS)
    pass_sources_before = dict(env_scenarios._PASS_VERIFIED_SOURCES)
    try:
        env_scenarios._DECLARED_COVERAGE.setdefault(key, set()).add(class_id)
        was_already_pass_verified = class_id in env_scenarios._PASS_VERIFIED_CLASS_IDS

        gen = pytest_runtest_makereport(_FakeItem(), _FakeCall())
        next(gen)  # advance the hookwrapper generator to its "outcome = yield" point
        try:
            gen.send(_FakeOutcome())
        except StopIteration:
            pass

        if not was_already_pass_verified:
            assert class_id not in env_scenarios._PASS_VERIFIED_CLASS_IDS
    finally:
        env_scenarios._DECLARED_COVERAGE.clear()
        env_scenarios._DECLARED_COVERAGE.update(declared_before)
        env_scenarios._PASS_VERIFIED_CLASS_IDS.clear()
        env_scenarios._PASS_VERIFIED_CLASS_IDS.update(pass_verified_before)
        env_scenarios._PASS_VERIFIED_SOURCES.clear()
        env_scenarios._PASS_VERIFIED_SOURCES.update(pass_sources_before)
