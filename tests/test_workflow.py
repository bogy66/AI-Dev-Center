import pytest
from unittest.mock import patch
from app.agent_orchestrator import AgentOrchestrator
from app.agent_manager import AgentManager
from app.agent_executor import AgentExecutor
from app.workflow_manager import WorkflowManager

@pytest.fixture
def orchestrator():
    return AgentOrchestrator(AgentManager(), AgentExecutor())

def test_workflow_approve(orchestrator):
    with patch("app.git_manager.GitManager.commit_and_get_hash") as mock_commit:
        mock_commit.return_value = {"code": 0, "commit": "abc123", "message": "Commit message"}
        state = orchestrator.run_workflow("test_project", "Test task")
        assert state["status"] == "approval_waiting"

        # Simulate approval
        state["status"] = "approved"
        orchestrator.workflow_manager.save(state)

        # Check GitHub upload
        with patch("app.github_manager.GitHubManager.upload") as mock_upload:
            orchestrator.run_workflow("test_project", "Test task")
            mock_upload.assert_called_once()

def test_workflow_reject(orchestrator):
    state = orchestrator.run_workflow("test_project", "Test task")
    assert state["status"] == "approval_waiting"

    # Simulate rejection
    state["status"] = "rejected"
    orchestrator.workflow_manager.save(state)

    # Check no GitHub upload
    with patch("app.github_manager.GitHubManager.upload") as mock_upload:
        orchestrator.run_workflow("test_project", "Test task")
        mock_upload.assert_not_called()
