from unittest.mock import MagicMock

from app.workflow_publisher import WorkflowPublisher


def test_approved_workflow_is_published():
    workflow = MagicMock()
    workflow.load.return_value = {
        "status": "approval_waiting",
        "user_approval": {
            "status": "approved",
            "approved_by": "Udo",
            "comment": "Looks good"
        }
    }

    git = MagicMock()
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
    workflow.save.assert_called_once_with(result)

    assert result["status"] == "completed"


def test_rejected_workflow_is_not_published():
    workflow = MagicMock()
    workflow.load.return_value = {
        "status": "approval_waiting",
        "user_approval": {
            "status": "rejected",
            "approved_by": "Udo",
            "comment": "Needs changes"
        }
    }

    git = MagicMock()

    publisher = WorkflowPublisher(
        workflow_manager=workflow,
        git_manager=git
    )

    result = publisher.publish("mock_project")

    git.push.assert_not_called()
    workflow.save.assert_not_called()

    assert result["status"] != "completed"


def test_failed_push_does_not_complete_workflow():
    workflow = MagicMock()
    workflow.load.return_value = {
        "status": "approval_waiting",
        "user_approval": {
            "status": "approved",
            "approved_by": "Udo",
            "comment": "Looks good"
        }
    }

    git = MagicMock()
    git.push.return_value = {
        "code": 1,
        "stdout": "",
        "stderr": "Push failed"
    }

    publisher = WorkflowPublisher(
        workflow_manager=workflow,
        git_manager=git
    )

    result = publisher.publish("mock_project")

    git.push.assert_called_once_with("mock_project")
    workflow.save.assert_not_called()

    assert result["status"] != "completed"
