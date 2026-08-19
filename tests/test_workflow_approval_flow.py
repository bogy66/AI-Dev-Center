from unittest.mock import MagicMock, patch

from app.agent_orchestrator import AgentOrchestrator


DEVELOPER_RESPONSE = """
## Analyse

Teständerung.

## Dateien

### Datei:
app/example.py

### Aktion:
update

### Inhalt:
print("changed")

## Tests

python -m pytest -q
"""


@patch("app.agent_orchestrator.WorkflowManager")
@patch("app.agent_orchestrator.GitManager")
@patch("app.agent_orchestrator.TesterAgent")
@patch("app.agent_orchestrator.ReviewerAgent")
@patch("app.agent_orchestrator.DeveloperFileApplier")
def test_workflow_stops_at_approval(
    MockDeveloperFileApplier,
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

    MockDeveloperFileApplier.return_value.apply.return_value = {
        "applied": ["app/example.py"]
    }

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

    executor = MagicMock()
    executor.run.return_value = DEVELOPER_RESPONSE

    orchestrator = AgentOrchestrator(
        MagicMock(),
        executor
    )

    result = orchestrator.run_workflow(
        "mock_project",
        "mock_task"
    )

    assert result["status"] == "approval_waiting"

    MockDeveloperFileApplier.return_value.apply.assert_called_once()

    MockGitManager.return_value.commit_and_get_hash.assert_called_once_with(
        "mock_project",
        "DEV: Development completed"
    )

    MockTesterAgent.return_value.test.assert_called_once()

    MockReviewerAgent.return_value.review.assert_called_once()

    MockGitManager.return_value.push.assert_not_called()
