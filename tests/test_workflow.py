import unittest
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


class TestWorkflow(unittest.TestCase):

    @patch("app.agent_orchestrator.WorkflowManager")
    @patch("app.agent_orchestrator.GitManager")
    @patch("app.agent_orchestrator.TesterAgent")
    @patch("app.agent_orchestrator.ReviewerAgent")
    @patch("app.agent_orchestrator.DeveloperFileApplier")
    def test_workflow_happy_path(
        self,
        MockDeveloperFileApplier,
        MockReviewerAgent,
        MockTesterAgent,
        MockGitManager,
        MockWorkflowManager
    ):
        workflow = MockWorkflowManager.return_value
        workflow.storage = "mock_workflow_state.json"

        state = {
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
            }
        }

        workflow.create.return_value = state
        workflow.load.return_value = state

        workflow.save.side_effect = (
            lambda new_state: workflow.load.return_value.update(new_state)
        )

        workflow.update_agent.side_effect = (
            lambda agent, status, commit=None:
            workflow.load.return_value[agent].update({
                "status": status,
                "commit": commit
            })
        )

        MockDeveloperFileApplier.return_value.apply.return_value = {
            "applied": ["app/example.py"]
        }

        MockGitManager.return_value.commit_and_get_hash.return_value = {
            "code": 0,
            "commit": "dev123",
            "message": "DEV commit"
        }

        MockTesterAgent.return_value.test.return_value = {
            "status": "completed",
            "tester": {
                "status": "completed",
                "result": "PASS"
            }
        }

        MockReviewerAgent.return_value.review.return_value = {
            "status": "approved"
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

        self.assertEqual(
            result["status"],
            "approval_waiting"
        )

        self.assertEqual(
            result["developer"]["commit"],
            "dev123"
        )

        MockDeveloperFileApplier.return_value.apply.assert_called_once()

        MockTesterAgent.return_value.test.assert_called_once()
        MockReviewerAgent.return_value.review.assert_called_once()

        MockGitManager.return_value.commit_and_get_hash.assert_called_once_with(
            "mock_project",
            "DEV: Development completed"
        )

    @patch("app.agent_orchestrator.WorkflowManager")
    @patch("app.agent_orchestrator.GitManager")
    @patch("app.agent_orchestrator.TesterAgent")
    @patch("app.agent_orchestrator.ReviewerAgent")
    @patch("app.agent_orchestrator.DeveloperFileApplier")
    def test_workflow_tester_failure(
        self,
        MockDeveloperFileApplier,
        MockReviewerAgent,
        MockTesterAgent,
        MockGitManager,
        MockWorkflowManager
    ):
        workflow = MockWorkflowManager.return_value
        workflow.storage = "mock_workflow_state.json"

        state = {
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
            }
        }

        workflow.create.return_value = state
        workflow.load.return_value = state

        MockDeveloperFileApplier.return_value.apply.return_value = {
            "applied": ["app/example.py"]
        }

        MockGitManager.return_value.commit_and_get_hash.return_value = {
            "code": 0,
            "commit": "dev123"
        }

        MockTesterAgent.return_value.test.return_value = {
            **state,
            "status": "tester_failed",
            "tester": {
                "status": "failed",
                "result": "Tests failed"
            }
        }

        orchestrator = AgentOrchestrator(
            MagicMock(),
            MagicMock()
        )

        orchestrator.agent_executor.run.return_value = DEVELOPER_RESPONSE

        result = orchestrator.run_workflow(
            "mock_project",
            "mock_task"
        )

        self.assertEqual(
            result["tester"]["status"],
            "failed"
        )

        MockReviewerAgent.return_value.review.assert_not_called()

    @patch("app.agent_orchestrator.WorkflowManager")
    @patch("app.agent_orchestrator.GitManager")
    @patch("app.agent_orchestrator.TesterAgent")
    @patch("app.agent_orchestrator.ReviewerAgent")
    @patch("app.agent_orchestrator.DeveloperFileApplier")
    def test_workflow_reviewer_failure(
        self,
        MockDeveloperFileApplier,
        MockReviewerAgent,
        MockTesterAgent,
        MockGitManager,
        MockWorkflowManager
    ):
        workflow = MockWorkflowManager.return_value
        workflow.storage = "mock_workflow_state.json"

        state = {
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
            }
        }

        workflow.create.return_value = state
        workflow.load.return_value = state

        MockDeveloperFileApplier.return_value.apply.return_value = {
            "applied": ["app/example.py"]
        }

        MockGitManager.return_value.commit_and_get_hash.return_value = {
            "code": 0,
            "commit": "dev123"
        }

        MockTesterAgent.return_value.test.return_value = {
            **state,
            "status": "completed",
            "tester": {
                "status": "completed",
                "result": "PASS"
            }
        }

        MockReviewerAgent.return_value.review.return_value = {
            **state,
            "status": "changes_required",
            "reviewer": {
                "status": "changes_required",
                "result": "Review failed"
            }
        }

        orchestrator = AgentOrchestrator(
            MagicMock(),
            MagicMock()
        )

        orchestrator.agent_executor.run.return_value = DEVELOPER_RESPONSE

        result = orchestrator.run_workflow(
            "mock_project",
            "mock_task"
        )

        self.assertEqual(
            result["reviewer"]["status"],
            "changes_required"
        )

        self.assertNotEqual(
            result["status"],
            "approval_waiting"
        )


if __name__ == "__main__":
    unittest.main()
