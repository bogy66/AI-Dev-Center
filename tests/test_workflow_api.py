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
