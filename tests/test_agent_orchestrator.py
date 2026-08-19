import unittest
from unittest.mock import MagicMock, patch
from app.agent_orchestrator import AgentOrchestrator
from app.workflow_manager import WorkflowManager
from app.git_manager import GitManager
from app.reviewer_agent import ReviewerAgent

class TestAgentOrchestrator(unittest.TestCase):
    def test_run_workflow(self):
        with patch('app.agent_orchestrator.WorkflowManager') as MockWorkflowManager, \
             patch('app.agent_orchestrator.GitManager') as MockGitManager, \
             patch('app.agent_orchestrator.TesterAgent') as MockTesterAgent, \
             patch('app.agent_orchestrator.ReviewerAgent') as MockReviewerAgent:
            
            # Mock instances
            mock_workflow_manager = MockWorkflowManager.return_value
            mock_git_manager = MockGitManager.return_value
            mock_tester_agent = MockTesterAgent.return_value
            mock_reviewer_agent = MockReviewerAgent.return_value

            # Configure mock return values
            mock_workflow_manager.create.return_value = {"status": "started"}
            mock_workflow_manager.update_agent.return_value = {"status": "approval_waiting"}
            mock_workflow_manager.save.return_value = None
            mock_workflow_manager.load.return_value = {"status": "approval_waiting"}
            mock_git_manager.commit.return_value = {"code": 0, "stdout": "commit_hash", "stderr": ""}
            mock_tester_agent.test.return_value = {"status": "completed"}
            mock_reviewer_agent.review.return_value = "success"

            # Initialize AgentOrchestrator with mocks
            orchestrator = AgentOrchestrator(mock_agent_manager, mock_agent_executor)

            # Run the workflow
            result = orchestrator.run_workflow("mock_project", "mock_task")

            # Assert the workflow result
            self.assertEqual(result["status"], "approval_waiting")

            # Verify the sequence of operations
            mock_workflow_manager.create.assert_called_once_with("mock_task", "dev_branch")
            mock_git_manager.commit.assert_any_call("mock_project", "Development changes")
            mock_git_manager.commit.assert_any_call("mock_project", "Testing changes")
            mock_tester_agent.test.assert_called_once_with("mock_project", str(mock_workflow_manager.storage))
            mock_reviewer_agent.review.assert_called_once_with("mock_project", str(mock_workflow_manager.storage))
            mock_workflow_manager.update_agent.assert_any_call("reviewer", "approved")
        # Mock AgentManager and AgentExecutor
        mock_agent_manager = MagicMock()
        mock_agent_executor = MagicMock()

        # Setup mock return values
        mock_agent_manager.load_agents.return_value = {
            "project_manager": MagicMock(),
            "architect": MagicMock(),
            "developer": MagicMock(),
            "tester": MagicMock(),
            "reviewer": MagicMock()
        }
        mock_agent_manager.load_project_context.return_value = "mock_project_context"
        mock_agent_executor.run.return_value = "mock_response"

        # Initialize AgentOrchestrator
        orchestrator = AgentOrchestrator(mock_agent_manager, mock_agent_executor)

        # Run orchestrator
        responses = orchestrator.run("mock_project", "mock_task")

        # Assert responses
        expected_responses = {
            "project_manager": "mock_response",
            "architect": "mock_response",
            "developer": "mock_response",
            "tester": "mock_response",
            "reviewer": "mock_response"
        }
        self.assertEqual(responses, expected_responses)

if __name__ == '__main__':
    unittest.main()
