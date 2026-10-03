"""Focused regression coverage for current-pytest-run Gate-1 completion
tracking (KIA-ADC-GATE1-HARNESS-PROOF-FIX-001 section 7, test item M):
a mandatory selector that is deselected/skipped/failed/xfailed/not
executed in the CURRENT session must prevent a COMPLETE Gate-1 proof
claim, even when historical PASS evidence exists elsewhere (tests.rst).

Uses a synthetic obligation-id map (never the real SELECTOR_MAP/tests.rst
data) so these tests are self-contained and never depend on this
session's own real, order-dependent test execution.
"""
from __future__ import annotations

import pytest

from requirements.evidence import current_run_completion as crc


_FAKE_MAP = {
    "TEST_FAKE_A": ["tests/test_fake.py::test_a"],
    "TEST_FAKE_B": ["tests/test_fake.py::test_b"],
    "TEST_FAKE_C": ["tests/test_fake.py::TestFakeClass"],
}


@pytest.fixture(autouse=True)
def _isolated_current_run_record(monkeypatch):
    """Every test in this module gets its own clean session-scoped
    record -- this module's tests must never see outcomes this same
    pytest session already recorded for its own real test items, and
    must never leak synthetic outcomes into the real session record.
    Also substitutes a synthetic obligation-id map so these tests never
    depend on (or corrupt) the real SELECTOR_MAP."""
    monkeypatch.setattr(crc, "SELECTOR_MAP", _FAKE_MAP)
    saved = crc.current_run_outcomes()
    crc.reset_current_run_outcomes()
    yield
    crc.reset_current_run_outcomes()
    for nodeid, outcome in saved.items():
        crc.record_outcome(nodeid, outcome)


def test_a_deselected_mandatory_selector_is_a_gap():
    crc.record_outcome("tests/test_fake.py::test_a", "PASSED")
    crc.record_outcome("tests/test_fake.py::test_b", "DESELECTED")
    gaps = crc.mandatory_current_run_gaps(frozenset(["TEST_FAKE_A", "TEST_FAKE_B"]))
    assert gaps == ("TEST_FAKE_B",)


def test_a_skipped_mandatory_selector_is_a_gap():
    crc.record_outcome("tests/test_fake.py::test_a", "SKIPPED")
    gaps = crc.mandatory_current_run_gaps(frozenset(["TEST_FAKE_A"]))
    assert gaps == ("TEST_FAKE_A",)


def test_a_failed_mandatory_selector_is_a_gap():
    crc.record_outcome("tests/test_fake.py::test_a", "FAILED")
    gaps = crc.mandatory_current_run_gaps(frozenset(["TEST_FAKE_A"]))
    assert gaps == ("TEST_FAKE_A",)


def test_an_xfailed_mandatory_selector_is_a_gap():
    crc.record_outcome("tests/test_fake.py::test_a", "XFAIL")
    gaps = crc.mandatory_current_run_gaps(frozenset(["TEST_FAKE_A"]))
    assert gaps == ("TEST_FAKE_A",)


def test_a_never_collected_mandatory_selector_is_a_gap():
    """Nothing at all was recorded for TEST_FAKE_A's selector this
    session (e.g. a narrower pytest invocation never touched that file)
    -- this is the exact masking-gap shape: silence must never be
    treated as evidence of a pass."""
    gaps = crc.mandatory_current_run_gaps(frozenset(["TEST_FAKE_A"]))
    assert gaps == ("TEST_FAKE_A",)


def test_historical_pass_never_masks_a_selector_this_session_never_ran():
    """The precise scenario section 7 names: tests.rst may still say
    IO from an old run, but this module only ever looks at THIS
    session's own record -- since nothing was recorded here, the gap is
    still reported regardless of what any historical store claims."""
    # No call to crc.record_outcome at all: simulates tests.rst's old,
    # unrelated persisted IO for TEST_FAKE_A being completely ignored.
    gaps = crc.mandatory_current_run_gaps(frozenset(["TEST_FAKE_A"]))
    assert "TEST_FAKE_A" in gaps


def test_a_fully_current_run_passed_selector_is_not_a_gap():
    crc.record_outcome("tests/test_fake.py::test_a", "PASSED")
    crc.record_outcome("tests/test_fake.py::test_b", "PASSED")
    gaps = crc.mandatory_current_run_gaps(frozenset(["TEST_FAKE_A", "TEST_FAKE_B"]))
    assert gaps == ()


def test_a_class_selector_requires_every_matched_nodeid_to_pass():
    crc.record_outcome("tests/test_fake.py::TestFakeClass::test_one", "PASSED")
    crc.record_outcome("tests/test_fake.py::TestFakeClass::test_two", "FAILED")
    gaps = crc.mandatory_current_run_gaps(frozenset(["TEST_FAKE_C"]))
    assert gaps == ("TEST_FAKE_C",)
