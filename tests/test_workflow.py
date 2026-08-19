import unittest
from unittest.mock import MagicMock, patch
from app.agent_orchestrator import AgentOrchestrator

class TestWorkflow(unittest.TestCase):
    @patch('app.agent_orchestrator.WorkflowManager')
    @patch('app.agent_orchestrator.GitManager')
    @patch('app.agent_orchestrator.TesterAgent')
    @patch('app.agent_orchestrator.ReviewerAgent')
    def test_workflow_happy_path(self, MockReviewerAgent, MockTesterAgent, MockGitManager, MockWorkflowManager):
        # Mock WorkflowManager
        mock_workflow_manager = MockWorkflowManager.return_value
        mock_workflow_manager.storage = "mock_workflow_state.json"
        mock_workflow_manager.create.return_value = {}
        mock_workflow_manager.load.return_value = {"developer": {}, "status": ""}
        mock_workflow_manager.save.side_effect = lambda state: mock_workflow_manager.load.return_value.update(state)
        mock_workflow_manager.update_agent.side_effect = lambda agent, status, commit=None: mock_workflow_manager.load.return_value["developer"].update({"commit": commit})

        # Mock GitManager
        mock_git_manager = MockGitManager.return_value
        mock_git_manager.commit_and_get_hash.return_value = {"code": 0, "commit": "dev123", "message": "DEV commit"}

        # Mock TesterAgent
        mock_tester_agent = MockTesterAgent.return_value
        mock_tester_agent.test.return_value = {
            "status": "completed",
            "tester": {
                "status": "completed",
                "result": "PASS"
            }
        }
        # Mock ReviewerAgent
        mock_reviewer_agent = MockReviewerAgent.return_value
        mock_reviewer_agent.review.return_value = {"status": "approved"}

        # Initialize AgentOrchestrator
        orchestrator = AgentOrchestrator(MagicMock(), MagicMock())

        # Run workflow
        state = orchestrator.run_workflow("mock_project", "mock_task")

        # Assertions
        self.assertEqual(state["status"], "approval_waiting")
        self.assertEqual(state["developer"]["commit"], "dev123")
        mock_tester_agent.test.assert_called_once()
        mock_reviewer_agent.review.assert_called_once()
        mock_git_manager.commit_and_get_hash.assert_called_once_with("mock_project", "DEV: Development completed")

    @patch("app.agent_orchestrator.WorkflowManager")
    @patch("app.agent_orchestrator.GitManager")
    @patch("app.agent_orchestrator.TesterAgent")
    @patch("app.agent_orchestrator.ReviewerAgent")
    def test_workflow_tester_failure(
        self,
        MockReviewerAgent,
        MockTesterAgent,
        MockGitManager,
        MockWorkflowManager
    ):
        mock_workflow = MockWorkflowManager.return_value
        mock_workflow.storage = "mock_workflow_state.json"

        state = {
            "status": "started",
            "developer": {
                "status": "completed",
                "commit": "dev123"
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

        mock_workflow.create.return_value = state
        mock_workflow.load.return_value = state
        mock_workflow.update_agent.return_value = state

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

        orchestrator = AgentOrchestrator(MagicMock(), MagicMock())

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
    def test_workflow_reviewer_failure(
        self,
        MockReviewerAgent,
        MockTesterAgent,
        MockGitManager,
        MockWorkflowManager
    ):
        mock_workflow = MockWorkflowManager.return_value
        mock_workflow.storage = "mock_workflow_state.json"

        state = {
            "status": "started",
            "developer": {
                "status": "completed",
                "commit": "dev123"
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

        mock_workflow.create.return_value = state
        mock_workflow.load.return_value = state

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

        orchestrator = AgentOrchestrator(MagicMock(), MagicMock())

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

    @patch("app.agent_orchestrator.WorkflowManager")
    @patch("app.agent_orchestrator.GitManager")
    @patch("app.agent_orchestrator.TesterAgent")
    @patch("app.agent_orchestrator.ReviewerAgent")
    def test_workflow_no_development_changes(
        self,
        MockReviewerAgent,
        MockTesterAgent,
        MockGitManager,
        MockWorkflowManager
    ):
        mock_workflow = MockWorkflowManager.return_value
        mock_workflow.storage = "mock_workflow_state.json"

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

        mock_workflow.create.return_value = state
        mock_workflow.load.return_value = state

        MockGitManager.return_value.commit_and_get_hash.return_value = {
            "code": 1,
            "stdout": "On branch master\nnothing to commit, working tree clean",
            "stderr": ""
        }

        orchestrator = AgentOrchestrator(
            MagicMock(),
            MagicMock()
        )

        result = orchestrator.run_workflow(
            "mock_project",
            "mock_task"
        )

        self.assertEqual(
            result["status"],
            "development_no_changes"
        )

        MockTesterAgent.return_value.test.assert_not_called()
        MockReviewerAgent.return_value.review.assert_not_called()


if __name__ == '__main__':
    unittest.main()
