from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import app


client = TestClient(app)


@patch("app.api.workflow_publisher")
def test_publish_approved_workflow(mock_publisher):

    mock_publisher.publish.return_value = {
        "status": "completed",
        "user_approval": {
            "status": "approved"
        }
    }

    response = client.post(
        "/workflow/publish",
        json={
            "project": "mock_project"
        }
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"

    mock_publisher.publish.assert_called_once_with(
        "mock_project"
    )


@patch("app.api.workflow_publisher")
def test_publish_failed_workflow(mock_publisher):

    mock_publisher.publish.return_value = {
        "status": "approval_waiting",
        "user_approval": {
            "status": "approved"
        }
    }

    response = client.post(
        "/workflow/publish",
        json={
            "project": "mock_project"
        }
    )

    assert response.status_code == 200
    assert response.json()["status"] == "approval_waiting"

    mock_publisher.publish.assert_called_once_with(
        "mock_project"
    )

@patch("app.api.WorkflowManager")
def test_get_workflow_status(mock_workflow_manager):

    mock_workflow_manager.return_value.load.return_value = {
        "status": "approval_waiting",
        "task": "mock_task",
        "user_approval": {
            "status": "approved"
        }
    }

    response = client.get("/workflow")

    assert response.status_code == 200
    assert response.json()["status"] == "approval_waiting"
    assert response.json()["task"] == "mock_task"

@patch("app.api.orchestrator")
def test_run_workflow(mock_orchestrator):

    mock_orchestrator.run_workflow.return_value = {
        "status": "approval_waiting",
        "task": "mock_task",
        "user_approval": {
            "status": "waiting"
        }
    }

    response = client.post(
        "/workflow/run",
        json={
            "project": "mock_project",
            "task": "mock_task"
        }
    )

    assert response.status_code == 200
    assert response.json()["status"] == "approval_waiting"

    mock_orchestrator.run_workflow.assert_called_once_with(
        "mock_project",
        "mock_task"
    )
