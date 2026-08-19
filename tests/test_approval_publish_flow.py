from unittest.mock import MagicMock

from app.approval_manager import ApprovalManager
from app.git_manager import GitManager
from app.workflow_manager import WorkflowManager
from app.workflow_publisher import WorkflowPublisher


def test_approved_workflow_can_be_published(tmp_path):
    storage = tmp_path / "workflow_state.json"

    workflow = WorkflowManager(storage=storage)

    workflow.create(
        "mock_task",
        "master"
    )

    state = workflow.load()
    state["status"] = "approval_waiting"
    workflow.save(state)

    approval = ApprovalManager(storage=storage)

    approval.approve(
        approved_by="Udo",
        comment="Sieht gut aus"
    )

    git = MagicMock(spec=GitManager)

    git.push.return_value = {
        "code": 0,
        "stdout": "Everything up-to-date",
        "stderr": ""
    }

    publisher = WorkflowPublisher(
        workflow_manager=workflow,
        git_manager=git
    )

    result = publisher.publish("mock_project")

    git.push.assert_called_once_with("mock_project")

    assert result["user_approval"]["status"] == "approved"
    assert result["status"] == "completed"

def test_workflow_cannot_be_published_without_approval(tmp_path):
    storage = tmp_path / "workflow_state.json"

    workflow = WorkflowManager(storage=storage)

    workflow.create(
        "mock_task",
        "master"
    )

    state = workflow.load()
    state["status"] = "approval_waiting"
    workflow.save(state)

    git = MagicMock(spec=GitManager)

    publisher = WorkflowPublisher(
        workflow_manager=workflow,
        git_manager=git
    )

    result = publisher.publish("mock_project")

    git.push.assert_not_called()

    assert result["status"] == "approval_waiting"
    assert result["user_approval"]["status"] == "waiting"

def test_rejected_workflow_cannot_be_published(tmp_path):
    storage = tmp_path / "workflow_state.json"

    workflow = WorkflowManager(storage=storage)

    workflow.create(
        "mock_task",
        "master"
    )

    state = workflow.load()
    state["status"] = "approval_waiting"
    workflow.save(state)

    approval = ApprovalManager(storage=storage)

    approval.reject(
        approved_by="Udo",
        comment="Änderungen erforderlich"
    )

    git = MagicMock(spec=GitManager)

    publisher = WorkflowPublisher(
        workflow_manager=workflow,
        git_manager=git
    )

    result = publisher.publish("mock_project")

    git.push.assert_not_called()

    assert result["status"] == "approval_waiting"
    assert result["user_approval"]["status"] == "rejected"

def test_rejected_workflow_preserves_comment(tmp_path):
    storage = tmp_path / "workflow_state.json"

    workflow = WorkflowManager(storage=storage)

    workflow.create(
        "mock_task",
        "master"
    )

    state = workflow.load()
    state["status"] = "approval_waiting"
    workflow.save(state)

    approval = ApprovalManager(storage=storage)

    approval.reject(
        approved_by="Udo",
        comment="Needs changes"
    )

    result = workflow.load()

    assert result["status"] == "approval_waiting"
    assert result["user_approval"]["status"] == "rejected"
    assert result["user_approval"]["approved_by"] == "Udo"
    assert result["user_approval"]["comment"] == "Needs changes"
