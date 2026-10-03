"""Focused regression coverage for selector-level Gate-1/Gate-3 scoping
and the current-run completion setup-phase-skip fix
(KIA-ADC-GATE1-CONTAINMENT-GATE-SCOPING-FIX-001 sections 6-11).

TEST_032 is the one existing TEST_* id (never a new one -- section 1)
that legitimately verifies both a deterministic Gate-1 obligation and a
Gate-3 Real-System smoke test in the same Requirement-Test object. These
tests prove the mixed-gate invariant holds without deleting the smoke
test's own traceability and without ever letting its Gate-3 NOT_RUN
degrade TEST_032's Gate-1 completion.
"""
from __future__ import annotations

import os
import subprocess
import uuid

import pytest

from requirements.evidence import current_run_completion as crc
from requirements.evidence.product_runtime import product_pytest_command
from requirements.evidence.selector_map import (
    GATE3_ONLY_SELECTORS,
    SELECTOR_MAP,
    is_gate3_only_nodeid,
    resolve_selector,
    resolve_selector_all,
)

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

_SMOKE_NODEID = "tests/test_interactive_terminal.py::TestRealTerminalSmoke::test_real_terminal_smoke_check"
_GATE1_NODEID_A = "tests/test_interactive_terminal.py::TestInteractiveTerminalLauncherSuccess::test_x"
_GATE1_NODEID_B = "tests/test_execution_boundary.py::TestSoftwareInstallationRoutesThroughVisibleTerminal::test_y"


@pytest.fixture(autouse=True)
def _isolated_current_run():
    """Every test here uses its own synthetic outcomes -- never real
    session data from the actual pytest run in progress."""
    saved = crc.current_run_outcomes()
    crc.reset_current_run_outcomes()
    yield
    crc.reset_current_run_outcomes()
    for nodeid, outcome in saved.items():
        crc.record_outcome(nodeid, outcome)


# ----------------------------------------------------------------------
# A/B. TEST_032 retains both Gate-1 and Gate-3 traceability; the smoke
# test remains classified Gate-3 (never deleted, never re-mapped).
# ----------------------------------------------------------------------

def test_test_032_selector_map_entry_is_unchanged_and_still_covers_the_smoke_test():
    assert SELECTOR_MAP["TEST_032"] == [
        "tests/test_execution_boundary.py::TestSoftwareInstallationRoutesThroughVisibleTerminal",
        "tests/test_interactive_terminal.py",
    ], "no new TEST_* id / no Requirement-Test mapping change is authorized for this task"
    assert resolve_selector(_SMOKE_NODEID) == "TEST_032"
    assert resolve_selector_all(_SMOKE_NODEID) == ["TEST_032"]


def test_real_terminal_smoke_is_explicitly_gate3_only():
    assert any(_selector_covers(sel, _SMOKE_NODEID) for sel in GATE3_ONLY_SELECTORS)
    assert is_gate3_only_nodeid(_SMOKE_NODEID)
    assert not is_gate3_only_nodeid(_GATE1_NODEID_A)
    assert not is_gate3_only_nodeid(_GATE1_NODEID_B)


def _selector_covers(selector, nodeid):
    return nodeid == selector or nodeid.startswith(selector + "::")


# ----------------------------------------------------------------------
# C/D. All deterministic TEST_032 selectors PASS + smoke NOT_RUN ->
# Gate-1 PROVEN (never degraded by the smoke's own correct Gate-3 skip).
# ----------------------------------------------------------------------

def test_smoke_not_run_does_not_prevent_test_032_gate1_completion():
    crc.record_outcome(_GATE1_NODEID_A, "PASSED")
    crc.record_outcome(_GATE1_NODEID_B, "PASSED")
    # The smoke test recorded nothing at all this session (the ordinary,
    # correct Gate-1 shape) -- current_run_gate3_status must read this
    # as NOT_RUN, and it must not appear as a Gate-1 gap.
    assert crc.current_run_gate3_status(_SMOKE_NODEID) == "NOT_RUN"
    gaps = crc.mandatory_current_run_gaps()
    assert "TEST_032" not in gaps, f"TEST_032 must be Gate-1-complete when smoke is merely NOT_RUN: gaps={gaps!r}"


def test_smoke_recorded_skipped_still_does_not_prevent_test_032_gate1_completion():
    """After the section-9 setup-phase-skip fix, the smoke test's own
    skip IS now genuinely recorded (rather than silently absent) --
    this must still never count against TEST_032's Gate-1 completion."""
    crc.record_outcome(_GATE1_NODEID_A, "PASSED")
    crc.record_outcome(_GATE1_NODEID_B, "PASSED")
    crc.record_outcome(_SMOKE_NODEID, "SKIPPED")
    assert crc.current_run_gate3_status(_SMOKE_NODEID) == "NOT_RUN"
    gaps = crc.mandatory_current_run_gaps()
    assert "TEST_032" not in gaps, f"gaps={gaps!r}"


def test_smoke_genuinely_passed_is_reported_as_gate3_passed():
    """The Gate-3 axis is still real and inspectable -- an explicit
    --real-system-e2e run where the smoke genuinely passes must be
    reportable as such, distinctly from Gate-1."""
    crc.record_outcome(_GATE1_NODEID_A, "PASSED")
    crc.record_outcome(_GATE1_NODEID_B, "PASSED")
    crc.record_outcome(_SMOKE_NODEID, "PASSED")
    assert crc.current_run_gate3_status(_SMOKE_NODEID) == "PASSED"
    assert "TEST_032" not in crc.mandatory_current_run_gaps()


# ----------------------------------------------------------------------
# E/F/G/H. A mandatory GATE-1 selector (never the Gate-3-only one)
# skipped/failed/deselected/never-collected DOES still prevent Gate-1
# PROVEN. Historical PASS never masks this (mandatory_current_run_gaps
# reads only the in-memory current-session record, never tests.rst).
# ----------------------------------------------------------------------

@pytest.mark.parametrize("bad_outcome", ["SKIPPED", "FAILED", "XFAIL", "DESELECTED"])
def test_mandatory_gate1_selector_bad_outcome_still_blocks_test_032(bad_outcome):
    crc.record_outcome(_GATE1_NODEID_A, bad_outcome)
    crc.record_outcome(_GATE1_NODEID_B, "PASSED")
    # smoke left unrecorded -- irrelevant to this assertion either way.
    gaps = crc.mandatory_current_run_gaps()
    assert "TEST_032" in gaps, (
        f"a mandatory Gate-1 selector outcome of {bad_outcome!r} must still block "
        f"TEST_032 Gate-1 completion: gaps={gaps!r}"
    )


def test_mandatory_gate1_selector_never_collected_still_blocks_test_032():
    crc.record_outcome(_GATE1_NODEID_B, "PASSED")
    # _GATE1_NODEID_A never recorded at all -- "silence is not evidence".
    gaps = crc.mandatory_current_run_gaps()
    assert "TEST_032" in gaps, f"gaps={gaps!r}"


def test_historical_pass_cannot_mask_a_current_run_gap():
    """derive_status composes functional_result (the historical/
    persisted axis) with current_run_backed (the session-live axis from
    mandatory_current_run_gaps). Even a stale historical IO must never
    stand in for a real current-session gap -- current_run_backed=False
    forces UNPROVEN unconditionally, exactly proving item I."""
    from requirements.evidence.proof_obligations import derive_status

    status = derive_status(
        required_tests=("some::selector",),
        functional_result="IO",  # a stale, fully-passing HISTORICAL result
        all_selectors_collectible=True,
        extra_proof_gate_ok=None,
        current_run_backed=False,  # but THIS session has a real, live gap
    )
    assert status == "UNPROVEN", "a real current-session gap must never be masked by historical IO"


# ----------------------------------------------------------------------
# K/L. TEST_033 remains an independent, entirely Gate-3-only obligation;
# accounting identity (expected == proven+partial+unproven) is untouched
# by this task (still exactly enforced in proof_obligations.py, reused
# here, not reimplemented).
# ----------------------------------------------------------------------

def test_test_033_remains_entirely_gate3_only_and_unaffected_by_gate3_only_selectors():
    from requirements.evidence.current_run_completion import _REAL_SYSTEM_ONLY_OBLIGATIONS

    assert _REAL_SYSTEM_ONLY_OBLIGATIONS == frozenset({"TEST_033"})
    assert not any(is_gate3_only_nodeid(sel) for sel in SELECTOR_MAP["TEST_033"])


def test_accounting_identity_still_holds_reused_not_reimplemented():
    from requirements.evidence.proof_obligations import GATE1_OBLIGATION_IDS

    assert GATE1_OBLIGATION_IDS == frozenset(SELECTOR_MAP) - frozenset({"TEST_033"})
    assert "TEST_032" in GATE1_OBLIGATION_IDS


# ----------------------------------------------------------------------
# Section 9: the ROOT conftest.py's pytest_runtest_makereport hook must
# now record a SETUP-phase skip/error too (previously silently dropped
# by its own `if call.when != "call": return` filter). Proven via a
# real nested pytest session -- conftest.py auto-discovery requires the
# probe file to live inside this repository's own tree (unlike the
# sitecustomize-based inheritance tests in test_gate1_containment.py,
# which need no conftest.py discovery at all); the probe file is
# created and removed entirely within this one test.
# ----------------------------------------------------------------------

def test_root_conftest_records_a_setup_phase_skip_as_a_current_run_outcome():
    probe_path = os.path.join(
        _REPO_ROOT, "tests", f"_tmp_gate1_setup_skip_probe_{uuid.uuid4().hex}.py",
    )
    probe_source = '''
import pytest


@pytest.fixture
def _skip_at_setup():
    pytest.skip("synthetic Gate-3-style setup-phase skip for KIA-ADC-GATE1-CONTAINMENT-GATE-SCOPING-FIX-001 section 9 regression coverage")


def test_probe(_skip_at_setup):
    assert False, "must never reach call phase"


def test_probe_setup_error(_skip_at_setup_error):
    pass


@pytest.fixture
def _skip_at_setup_error():
    raise RuntimeError("synthetic setup-phase error for section 9 regression coverage")


def test_report_recorded_outcomes():
    from requirements.evidence import current_run_completion as _crc
    outcomes = _crc.current_run_outcomes()
    probe_ids = {nid: outcome for nid, outcome in outcomes.items() if "_tmp_gate1_setup_skip_probe" in nid}
    skip_ids = [nid for nid in probe_ids if nid.endswith("::test_probe")]
    error_ids = [nid for nid in probe_ids if nid.endswith("::test_probe_setup_error")]
    assert skip_ids and probe_ids[skip_ids[0]] == "SKIPPED", probe_ids
    assert error_ids and probe_ids[error_ids[0]] == "FAILED", probe_ids
'''
    try:
        with open(probe_path, "w", encoding="utf-8") as f:
            f.write(probe_source)
        result = subprocess.run(
            # The probe lives under tests/ (product conftest), so it runs
            # in the product runtime -- never .requirements-venv.
            product_pytest_command(probe_path, "-p", "no:cacheprovider", "-v"),
            cwd=_REPO_ROOT, capture_output=True, text=True, timeout=60,
        )
        # returncode is deliberately 1 here (test_probe_setup_error is an
        # intentional, synthetic setup-phase ERROR, not a harness bug) --
        # the actual assertion under test is test_report_recorded_outcomes,
        # which must itself have PASSED within this same nested session
        # (the in-memory current-run record is only shared within one
        # process, so the verification must run in the SAME invocation
        # as the probes it inspects).
        assert result.returncode in (0, 1), (
            f"nested pytest session did not complete normally:\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        assert "test_report_recorded_outcomes PASSED" in result.stdout, (
            f"setup-phase skip/error was not recorded as a current-run outcome:\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
    finally:
        if os.path.exists(probe_path):
            os.remove(probe_path)


# ----------------------------------------------------------------------
# Section 10: the current-run Gate-1 meta-proof must consume the ACTIVE
# session's own --adc-evidence-store, never silently default away from
# it. Proven directly against test_gate1_proof_meta_gate's own helper.
# ----------------------------------------------------------------------

def test_current_run_store_root_helper_never_silently_defaults_away_a_custom_store():
    from tests.test_gate1_proof_meta_gate import _current_run_store_root

    class _FakeConfig:
        def __init__(self, values):
            self._values = values

        def getoption(self, name, default=None):
            return self._values.get(name, default)

    # No --adc-evidence at all this session -- None is correct here (a
    # genuine formal run against the real default store).
    assert _current_run_store_root(_FakeConfig({})) is None

    # A genuine formal run: --adc-evidence with no store override --
    # None is STILL correct (that IS the real default store, by design).
    assert _current_run_store_root(_FakeConfig({"--adc-evidence": True})) is None

    # An isolated/diagnostic run using a custom store -- must be threaded
    # through explicitly, never silently dropped back to the default.
    fake_config = _FakeConfig({"--adc-evidence": True, "--adc-evidence-store": "/tmp/some-custom-store"})
    assert _current_run_store_root(fake_config) == "/tmp/some-custom-store"
