from unittest.mock import MagicMock, patch

from app.agent_orchestrator import AgentOrchestrator


@patch("app.agent_orchestrator.WorkflowManager")
@patch("app.agent_orchestrator.GitManager")
@patch("app.agent_orchestrator.TesterAgent")
@patch("app.agent_orchestrator.ReviewerAgent")
def test_workflow_stops_at_approval(
    MockReviewerAgent,
    MockTesterAgent,
    MockGitManager,
    MockWorkflowManager
):
    workflow = MockWorkflowManager.return_value
    workflow.storage = "mock_workflow_state.json"

    workflow_state = {
        "status": "started",
        "developer": {
            "status": "pending",
            "commit": None
        },
        "tester": {
            "status": "pending",
            "result": None
        },
        "reviewer": {
            "status": "pending",
            "result": None
        },
        "user_approval": {
            "status": "waiting"
        }
    }

    workflow.create.return_value = workflow_state
    workflow.load.return_value = workflow_state

    MockGitManager.return_value.commit_and_get_hash.return_value = {
        "code": 0,
        "commit": "dev123"
    }

    MockTesterAgent.return_value.test.return_value = {
        **workflow_state,
        "status": "completed",
        "tester": {
            "status": "completed",
            "result": "PASS"
        }
    }

    MockReviewerAgent.return_value.review.return_value = {
        **workflow_state,
        "status": "approved",
        "reviewer": {
            "status": "approved",
            "result": "Review passed"
        }
    }

    orchestrator = AgentOrchestrator(
        MagicMock(),
        MagicMock()
    )

    result = orchestrator.run_workflow(
        "mock_project",
        "mock_task"
    )

    assert result["status"] == "approval_waiting"

    MockTesterAgent.return_value.test.assert_called_once()
    MockReviewerAgent.return_value.review.assert_called_once()

    MockGitManager.return_value.push.assert_not_called()
