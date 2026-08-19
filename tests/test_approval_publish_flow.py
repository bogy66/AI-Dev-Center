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
