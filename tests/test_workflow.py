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
    # Initialize a new workflow
    state = orchestrator.run_workflow("test_project", "Test task")
    assert state["status"] == "approval_waiting"

    # Simulate approval
    approval_manager = ApprovalManager()
    approval_manager.approve()

    # Check that the state is updated to approved
    state = orchestrator.run_workflow("test_project", "Test task")
    assert state["status"] == "approved"
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
    # Initialize a new workflow
    state = orchestrator.run_workflow("test_project", "Test task")
    assert state["status"] == "approval_waiting"

    # Simulate rejection
    approval_manager = ApprovalManager()
    approval_manager.reject()

    # Check that the state is updated to rejected
    state = orchestrator.run_workflow("test_project", "Test task")
    assert state["status"] == "rejected"
    state = orchestrator.run_workflow("test_project", "Test task")
    assert state["status"] == "approval_waiting"

    # Simulate rejection
    state["status"] = "rejected"
    orchestrator.workflow_manager.save(state)

    # Check no GitHub upload
    with patch("app.github_manager.GitHubManager.upload") as mock_upload:
        orchestrator.run_workflow("test_project", "Test task")
        mock_upload.assert_not_called()
