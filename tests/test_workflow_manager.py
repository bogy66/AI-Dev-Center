import json

from app.workflow_manager import WorkflowManager


def test_load_returns_default_state_when_json_is_corrupted(tmp_path):
    storage = tmp_path / "workflow_state.json"
    storage.write_text("{not valid json", encoding="utf-8")

    manager = WorkflowManager(storage=storage)

    state = manager.load()

    assert state["status"] == "not_started"
    assert state["developer"]["status"] == "pending"
    assert state["tester"]["status"] == "pending"
    assert state["reviewer"]["status"] == "pending"
    assert state["user_approval"]["status"] == "waiting"


def test_load_returns_default_state_when_json_is_not_an_object(tmp_path):
    storage = tmp_path / "workflow_state.json"
    storage.write_text("[1, 2, 3]", encoding="utf-8")

    manager = WorkflowManager(storage=storage)

    state = manager.load()

    assert state["status"] == "not_started"


def test_load_fills_missing_fields_but_preserves_existing_values(tmp_path):
    storage = tmp_path / "workflow_state.json"

    partial_state = {
        "status": "approval_waiting",
        "task": "Original task",
        "developer": {
            "commit": "abc123"
        },
        "user_approval": {
            "status": "approved",
            "approved_by": "Udo"
        }
    }

    storage.write_text(
        json.dumps(partial_state),
        encoding="utf-8"
    )

    manager = WorkflowManager(storage=storage)

    state = manager.load()

    assert state["status"] == "approval_waiting", (
        "Expected the existing status to be preserved, not reset to "
        "a default value."
    )
    assert state["task"] == "Original task"
    assert state["branch"] is None

    assert state["developer"]["commit"] == "abc123", (
        "Expected the existing developer.commit to be preserved."
    )
    assert state["developer"]["status"] == "pending", (
        "Expected the missing developer.status to be filled with "
        "its default value."
    )

    assert state["tester"] == {
        "status": "pending",
        "commit": None,
        "result": None
    }, "Expected the entirely-missing tester block to be defaulted."

    assert state["reviewer"] == {
        "status": "pending",
        "result": None
    }, "Expected the entirely-missing reviewer block to be defaulted."

    assert state["user_approval"]["status"] == "approved", (
        "Expected the existing user_approval.status to be preserved."
    )
    assert state["user_approval"]["approved_by"] == "Udo"
    assert state["user_approval"]["approved_at"] is None
    assert state["user_approval"]["comment"] is None


def test_save_is_atomic_and_leaves_no_temp_file(tmp_path):
    storage = tmp_path / "workflow_state.json"

    manager = WorkflowManager(storage=storage)

    manager.save({"status": "started"})

    remaining_files = list(tmp_path.iterdir())

    assert remaining_files == [storage], (
        "Expected save() to leave exactly the target file behind, "
        "with no leftover temporary file."
    )

    loaded = json.loads(storage.read_text(encoding="utf-8"))
    assert loaded["status"] == "started"


def test_save_overwrites_existing_file_completely(tmp_path):
    storage = tmp_path / "workflow_state.json"

    manager = WorkflowManager(storage=storage)

    manager.save({"status": "started", "extra": "x" * 1000})
    manager.save({"status": "completed"})

    loaded = json.loads(storage.read_text(encoding="utf-8"))

    assert loaded == {"status": "completed"}


def test_create_and_load_roundtrip_unchanged(tmp_path):
    storage = tmp_path / "workflow_state.json"

    manager = WorkflowManager(storage=storage)

    created = manager.create("mock_task", "dev_branch")

    loaded = manager.load()

    assert loaded["status"] == created["status"]
    assert loaded["task"] == "mock_task"
    assert loaded["branch"] == "dev_branch"
    assert loaded["created"] == created["created"]
