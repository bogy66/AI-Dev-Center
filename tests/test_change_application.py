"""Regressions for CLAUDE-ADC-S3-CHANGE-GENERATION-APPLICATION-ARCH-FIX-001.

app.change_application is the single, central Change Application &
Provenance Attribution implementation used by BOTH development changes
(Development Change Generation's output) and test changes (Test Change
Generation's output), for both the initial and rework cycle. These
tests exercise it directly, independent of
DevelopmentStage/DevelopmentTestingStage.
"""
from unittest.mock import Mock

import pytest

from app.change_application import ChangeApplicationService, phase_for


# ---------------------------------------------------------------------
# Phase attribution
# ---------------------------------------------------------------------

@pytest.mark.parametrize("kind,is_rework,expected", [
    ("development", False, "development"),
    ("development", True, "rework_development"),
    ("test", False, "test"),
    ("test", True, "rework_test"),
])
def test_phase_for_matches_the_existing_productive_phase_contract(kind, is_rework, expected):
    assert phase_for(kind, is_rework) == expected


def test_phase_for_rejects_unknown_kind():
    with pytest.raises(ValueError, match="Unknown change kind"):
        phase_for("bogus", False)


# ---------------------------------------------------------------------
# Apply routing: direct applier path (no provenance recorder)
# ---------------------------------------------------------------------

def test_apply_uses_the_applier_directly_when_no_provenance_recorder(tmp_path):
    applier = Mock()
    applier.apply.return_value = {"applied": ["a.py"], "skipped": []}
    factory = Mock(return_value=applier)
    changes = {"changes": [{"file": "a.py", "action": "create", "content": "x"}]}

    result = ChangeApplicationService(factory).apply(tmp_path, changes, "development", False)

    factory.assert_called_once_with(tmp_path)
    applier.apply.assert_called_once_with(changes)
    assert result == {"applied": ["a.py"], "skipped": []}


def test_apply_never_calls_a_provenance_recorder_when_none_is_given(tmp_path):
    applier = Mock()
    applier.apply.return_value = {"applied": [], "skipped": []}
    factory = Mock(return_value=applier)

    ChangeApplicationService(factory).apply(tmp_path, {"changes": []}, "test", False, provenance_recorder=None)

    applier.apply.assert_called_once()


# ---------------------------------------------------------------------
# Apply routing: provenance path (recorder present)
# ---------------------------------------------------------------------

def test_apply_routes_through_the_provenance_recorder_when_present(tmp_path):
    applier = Mock()
    factory = Mock(return_value=applier)
    changes = {"changes": [{"file": "a.py", "action": "create", "content": "x"}]}
    recorder = Mock()
    recorder.apply.return_value = {"applied": ["a.py"], "skipped": []}

    result = ChangeApplicationService(factory).apply(
        tmp_path, changes, "development", False, provenance_recorder=recorder,
    )

    recorder.apply.assert_called_once_with(applier, changes, "development")
    applier.apply.assert_not_called()
    assert result == {"applied": ["a.py"], "skipped": []}


@pytest.mark.parametrize("kind,is_rework,expected_phase", [
    ("development", False, "development"),
    ("development", True, "rework_development"),
    ("test", False, "test"),
    ("test", True, "rework_test"),
])
def test_apply_passes_the_correct_phase_to_the_provenance_recorder(tmp_path, kind, is_rework, expected_phase):
    applier = Mock()
    factory = Mock(return_value=applier)
    recorder = Mock()
    recorder.apply.return_value = {"applied": [], "skipped": []}

    ChangeApplicationService(factory).apply(tmp_path, {"changes": []}, kind, is_rework, provenance_recorder=recorder)

    assert recorder.apply.call_args.args[2] == expected_phase


# ---------------------------------------------------------------------
# Apply-result -> status classification
# ---------------------------------------------------------------------

def test_status_is_success_only_when_something_applied_and_nothing_skipped():
    assert ChangeApplicationService.status_for({"applied": ["a.py"], "skipped": []}) == "success"


def test_status_is_apply_failed_for_an_empty_change_set():
    assert ChangeApplicationService.status_for({"applied": [], "skipped": []}) == "apply_failed"


def test_status_is_apply_failed_for_a_partially_applied_change_set():
    assert ChangeApplicationService.status_for({"applied": ["a.py"], "skipped": ["b.py"]}) == "apply_failed"


def test_status_is_apply_failed_when_everything_was_skipped():
    assert ChangeApplicationService.status_for({"applied": [], "skipped": ["a.py"]}) == "apply_failed"
