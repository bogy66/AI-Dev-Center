import pytest
import json
from app.approval_manager import ApprovalManager
from pathlib import Path


@pytest.fixture
def approval_manager(tmp_path):
    storage = tmp_path / "workflow_state.json"
    manager = ApprovalManager(storage=storage)
    return manager


def test_get_status_on_fresh_storage_returns_status_key(approval_manager):
    state = approval_manager.get_status()
    assert "status" in state
    assert state["status"] == "not_started"
    assert state["approved_by"] is None
    assert state["approved_at"] is None
    assert state["comment"] is None


def test_create_approval(approval_manager):
    approval_manager.create_approval()
    state = approval_manager.get_status()
    assert state["status"] == "waiting"
    assert state["approved_by"] is None
    assert state["approved_at"] is None
    assert state["comment"] is None


def test_approve(approval_manager):
    approval_manager.create_approval()
    approval_manager.approve(approved_by="Udo", comment="Looks good")
    state = approval_manager.get_status()
    assert state["status"] == "approved"
    assert state["approved_by"] == "Udo"
    assert state["comment"] == "Looks good"
    assert state["approved_at"] is not None


def test_reject(approval_manager):
    approval_manager.create_approval()
    approval_manager.reject(approved_by="Udo", comment="Needs changes")
    state = approval_manager.get_status()
    assert state["status"] == "rejected"
    assert state["approved_by"] == "Udo"
    assert state["comment"] == "Needs changes"
    assert state["approved_at"] is not None


def test_persistent_state_after_reload(tmp_path):
    storage = tmp_path / "workflow_state.json"
    manager = ApprovalManager(storage=storage)
    manager.create_approval()
    manager.approve(approved_by="Udo", comment="Approved")
    state_before = manager.get_status()

    # Simulate reloading by creating a new instance
    new_manager = ApprovalManager(storage=storage)
    state_after = new_manager.get_status()

    assert state_before == state_after


def test_optional_comment(approval_manager):
    approval_manager.create_approval()
    approval_manager.approve(approved_by="Udo")
    state = approval_manager.get_status()
    assert state["status"] == "approved"
    assert state["approved_by"] == "Udo"
    assert state["comment"] is None


def test_load_state_returns_empty_dict_when_json_is_corrupted(tmp_path):
    storage = tmp_path / "workflow_state.json"
    storage.write_text("{not valid json", encoding="utf-8")

    manager = ApprovalManager(storage=storage)

    state = manager.load_state()

    assert state == {}, (
        "Expected load_state() to fall back to an empty dict on "
        "corrupted JSON instead of raising JSONDecodeError."
    )


def test_load_state_returns_empty_dict_when_json_is_not_an_object(tmp_path):
    storage = tmp_path / "workflow_state.json"
    storage.write_text("[1, 2, 3]", encoding="utf-8")

    manager = ApprovalManager(storage=storage)

    state = manager.load_state()

    assert state == {}


def test_get_status_returns_default_when_json_is_corrupted(tmp_path):
    storage = tmp_path / "workflow_state.json"
    storage.write_text("{not valid json", encoding="utf-8")

    manager = ApprovalManager(storage=storage)

    status = manager.get_status()

    assert status["status"] == "not_started"
    assert status["approved_by"] is None
    assert status["approved_at"] is None
    assert status["comment"] is None


def test_save_state_is_atomic_and_leaves_no_temp_file(tmp_path):
    storage = tmp_path / "workflow_state.json"

    manager = ApprovalManager(storage=storage)

    manager.save_state({"user_approval": {"status": "waiting"}})

    remaining_files = list(tmp_path.iterdir())

    assert remaining_files == [storage], (
        "Expected save_state() to leave exactly the target file "
        "behind, with no leftover temporary file."
    )

    loaded = json.loads(storage.read_text(encoding="utf-8"))
    assert loaded["user_approval"]["status"] == "waiting"
