from app.approval_manager import ApprovalManager


def test_workflow_approval_approved(tmp_path):
    storage = tmp_path / "workflow_state.json"

    storage.write_text(
        '{"status": "approval_waiting"}',
        encoding="utf-8"
    )

    manager = ApprovalManager(storage=storage)

    manager.approve(
        approved_by="Udo",
        comment="Sieht gut aus"
    )

    state = manager.load_state()

    assert state["status"] == "approval_waiting"
    assert state["user_approval"]["status"] == "approved"
    assert state["user_approval"]["approved_by"] == "Udo"
    assert state["user_approval"]["comment"] == "Sieht gut aus"


def test_workflow_approval_rejected(tmp_path):
    storage = tmp_path / "workflow_state.json"

    storage.write_text(
        '{"status": "approval_waiting"}',
        encoding="utf-8"
    )

    manager = ApprovalManager(storage=storage)

    manager.reject(
        approved_by="Udo",
        comment="Noch Änderungen notwendig"
    )

    state = manager.load_state()

    assert state["status"] == "approval_waiting"
    assert state["user_approval"]["status"] == "rejected"
    assert state["user_approval"]["approved_by"] == "Udo"
    assert state["user_approval"]["comment"] == "Noch Änderungen notwendig"
