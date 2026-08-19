import pytest
import json
from app.approval_manager import ApprovalManager
from pathlib import Path


@pytest.fixture
def approval_manager(tmp_path):
    storage = tmp_path / "workflow_state.json"
    manager = ApprovalManager(storage=storage)
    return manager


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
