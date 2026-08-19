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
        mock_tester_agent.test.return_value = {"status": "completed", "result": "PASS"}

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

if __name__ == '__main__':
    unittest.main()
