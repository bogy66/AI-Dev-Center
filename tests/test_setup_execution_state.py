"""CLAUDE-E2E-003H UNIT tests for app.setup_execution_state: the
generic, ecosystem-neutral, project/plan/step-scoped persisted
execution-state model and its state machine.
"""
import pytest

from app.setup_execution_state import (
    FAILED, IN_PROGRESS, NOT_STARTED, RECOVERY_REQUIRED, SUCCEEDED,
    SetupExecutionStateError, SetupExecutionStateStore, SetupStepIdentity,
    setup_step_content_snapshot,
)


def _identity(project_key="proj-a", generation_id="plan-1", step_id="step-1", content=("install", "python_package_install", "pip install x", "x", None, None, "/bin/python")):
    return SetupStepIdentity(project_key=project_key, generation_id=generation_id, step_id=step_id, content=content)


class TestValidTransitions:
    def test_not_started_to_in_progress(self, tmp_path):
        store = SetupExecutionStateStore(tmp_path / "state.json")
        identity = _identity()

        assert store.get(identity) is None
        record = store.begin(identity, "owner-1")

        assert record["status"] == IN_PROGRESS
        assert store.get(identity)["status"] == IN_PROGRESS

    def test_in_progress_to_succeeded(self, tmp_path):
        store = SetupExecutionStateStore(tmp_path / "state.json")
        identity = _identity()
        store.begin(identity, "owner-1")

        record = store.finish(identity, "owner-1", SUCCEEDED, {"success": True})

        assert record["status"] == SUCCEEDED
        assert store.get(identity)["status"] == SUCCEEDED

    def test_in_progress_to_failed(self, tmp_path):
        store = SetupExecutionStateStore(tmp_path / "state.json")
        identity = _identity()
        store.begin(identity, "owner-1")

        record = store.finish(identity, "owner-1", FAILED, {"success": False})

        assert record["status"] == FAILED
        assert store.get(identity)["status"] == FAILED


class TestIllegalTransitions:
    def test_succeeded_to_in_progress_blocked(self, tmp_path):
        store = SetupExecutionStateStore(tmp_path / "state.json")
        identity = _identity()
        store.begin(identity, "owner-1")
        store.finish(identity, "owner-1", SUCCEEDED, {"success": True})

        with pytest.raises(SetupExecutionStateError):
            store.begin(identity, "owner-2")

    def test_failed_to_automatic_in_progress_blocked(self, tmp_path):
        store = SetupExecutionStateStore(tmp_path / "state.json")
        identity = _identity()
        store.begin(identity, "owner-1")
        store.finish(identity, "owner-1", FAILED, {"success": False})

        with pytest.raises(SetupExecutionStateError):
            store.begin(identity, "owner-2")

    def test_stale_in_progress_to_automatic_in_progress_blocked(self, tmp_path):
        """A second begin() over a still-IN_PROGRESS record (the
        previous attempt never reached a terminal state -- interrupted)
        must fail closed with recovery_required, not silently restart."""
        store = SetupExecutionStateStore(tmp_path / "state.json")
        identity = _identity()
        store.begin(identity, "owner-1")  # never finished -- simulates a crash

        with pytest.raises(SetupExecutionStateError):
            store.begin(identity, "owner-2")

        assert store._load_raw()[identity.project_key][identity.generation_id][identity.step_id]["status"] == RECOVERY_REQUIRED

    def test_finish_without_matching_in_progress_record_is_rejected(self, tmp_path):
        store = SetupExecutionStateStore(tmp_path / "state.json")
        identity = _identity()

        with pytest.raises(SetupExecutionStateError):
            store.finish(identity, "owner-1", SUCCEEDED, {"success": True})

    def test_finish_with_wrong_owner_is_rejected(self, tmp_path):
        store = SetupExecutionStateStore(tmp_path / "state.json")
        identity = _identity()
        store.begin(identity, "owner-1")

        with pytest.raises(SetupExecutionStateError):
            store.finish(identity, "owner-2", SUCCEEDED, {"success": True})

    def test_finish_rejects_non_terminal_status(self, tmp_path):
        store = SetupExecutionStateStore(tmp_path / "state.json")
        identity = _identity()
        store.begin(identity, "owner-1")

        with pytest.raises(ValueError):
            store.finish(identity, "owner-1", IN_PROGRESS, {})


class TestCorruptStateFailsClosed:
    def test_corrupt_json_file_raises_rather_than_defaulting(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text("{not-json")
        store = SetupExecutionStateStore(path)

        with pytest.raises(SetupExecutionStateError):
            store.get(_identity())

    def test_non_object_json_raises(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text("[1, 2, 3]")
        store = SetupExecutionStateStore(path)

        with pytest.raises(SetupExecutionStateError):
            store.get(_identity())

    def test_unknown_status_value_raises_not_treated_as_not_started(self, tmp_path):
        import json
        path = tmp_path / "state.json"
        identity = _identity()
        path.write_text(json.dumps({
            identity.project_key: {identity.generation_id: {identity.step_id: {
                "status": "totally_bogus_status", "content": list(identity.content),
            }}}
        }))
        store = SetupExecutionStateStore(path)

        with pytest.raises(SetupExecutionStateError):
            store.get(identity)


class TestProjectPlanStepBinding:
    def test_get_returns_none_for_never_recorded_identity(self, tmp_path):
        store = SetupExecutionStateStore(tmp_path / "state.json")
        assert store.get(_identity()) is None

    def test_different_project_does_not_see_the_record(self, tmp_path):
        store = SetupExecutionStateStore(tmp_path / "state.json")
        store.begin(_identity(project_key="proj-a"), "owner-1")

        assert store.get(_identity(project_key="proj-b")) is None

    def test_different_plan_does_not_see_the_record(self, tmp_path):
        store = SetupExecutionStateStore(tmp_path / "state.json")
        store.begin(_identity(generation_id="plan-1"), "owner-1")

        assert store.get(_identity(generation_id="plan-2")) is None

    def test_different_step_does_not_see_the_record(self, tmp_path):
        store = SetupExecutionStateStore(tmp_path / "state.json")
        store.begin(_identity(step_id="step-1"), "owner-1")

        assert store.get(_identity(step_id="step-2")) is None

    def test_changed_content_under_same_generation_fails_closed(self, tmp_path):
        """CLAUDE-E2E-003I-A / REQ-S3-GENERATION-CONTENT-IMMUTABILITY
        (TC1): execution-relevant content must not change within the
        same setup generation. A mismatch found under the SAME
        (project, generation, step) key must fail closed -- it must
        NEVER be silently reinterpreted as a fresh, freely-startable
        NOT_STARTED operation (CLAUDE-E2E-003I's original, incorrect
        behavior, confirmed by independent review and reproduced
        before this fix)."""
        store = SetupExecutionStateStore(tmp_path / "state.json")
        original = _identity(content=("install", "python_package_install", "pip install x", "x", None, None, "/bin/python"))
        store.begin(original, "owner-1")
        store.finish(original, "owner-1", SUCCEEDED, {"success": True})

        changed = _identity(content=("install", "python_package_install", "pip install y", "y", None, None, "/bin/python"))

        with pytest.raises(SetupExecutionStateError):
            store.get(changed)
        with pytest.raises(SetupExecutionStateError):
            store.begin(changed, "owner-2")


def test_setup_step_content_snapshot_is_generic_and_deterministic():
    from types import SimpleNamespace
    step = SimpleNamespace(
        action="install", setup_effect="python_package_install",
        install_method="pip install x", package="x", version=None,
        command=None, target_executable="/bin/python",
    )
    snapshot = setup_step_content_snapshot(step)
    assert snapshot == setup_step_content_snapshot(step)
    assert isinstance(snapshot, tuple)
