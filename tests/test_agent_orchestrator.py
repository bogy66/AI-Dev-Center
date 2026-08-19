import unittest
from unittest.mock import MagicMock, patch
from app.agent_orchestrator import AgentOrchestrator
from app.workflow_manager import WorkflowManager
from app.git_manager import GitManager
from app.tester_agent import TesterAgent
from app.reviewer_agent import ReviewerAgent

class TestAgentOrchestrator(unittest.TestCase):
    def test_run_workflow(self):
        # Mock dependencies
        mock_agent_manager = MagicMock()
        mock_agent_executor = MagicMock()
        mock_workflow_manager = MagicMock()
        mock_git_manager = MagicMock()
        mock_tester_agent = MagicMock()
        mock_reviewer_agent = MagicMock()

        # Mock dependencies with patch
        with patch('app.agent_orchestrator.GitManager', return_value=mock_git_manager), \
             patch('app.agent_orchestrator.TesterAgent', return_value=mock_tester_agent), \
             patch('app.agent_orchestrator.ReviewerAgent', return_value=mock_reviewer_agent):

            # Setup mock return values
            mock_agent_manager.load_agents.return_value = {
                "project_manager": MagicMock(),
                "architect": MagicMock(),
                "developer": MagicMock(),
                "tester": MagicMock(),
                "reviewer": MagicMock()
            }
            mock_agent_executor.run.return_value = "mock_response"
            mock_reviewer_agent.review.return_value = "success"

            # Initialize AgentOrchestrator with mocks
            orchestrator = AgentOrchestrator(mock_agent_manager, mock_agent_executor)

            # Run the workflow
            result = orchestrator.run_workflow("mock_project", "mock_task")

            # Assert the workflow result
            self.assertEqual(result, "Workflow completed")

            # Verify the sequence of operations
            mock_workflow_manager.create.assert_called_once_with("mock_task", "dev_branch")
            mock_git_manager.commit.assert_any_call("mock_project", "Development changes")
            mock_git_manager.commit.assert_any_call("mock_project", "Testing changes")
            mock_tester_agent.test.assert_called_once_with("mock_project", "workflow_file")
            mock_reviewer_agent.review.assert_called_once_with("mock_project", "workflow_file")
        mock_agent_manager = MagicMock()
        mock_agent_executor = MagicMock()
        mock_workflow_manager = MagicMock()
        mock_git_manager = MagicMock()
        mock_tester_agent = MagicMock()
        mock_reviewer_agent = MagicMock()

        # Setup mock return values
        mock_agent_manager.load_agents.return_value = {
            "project_manager": MagicMock(),
            "architect": MagicMock(),
            "developer": MagicMock(),
            "tester": MagicMock(),
            "reviewer": MagicMock()
        }
        mock_agent_executor.run.return_value = "mock_response"
        mock_reviewer_agent.review.return_value = "success"

        # Initialize AgentOrchestrator with mocks
        orchestrator = AgentOrchestrator(mock_agent_manager, mock_agent_executor)

        # Run the workflow
        result = orchestrator.run_workflow("mock_project", "mock_task")

        # Assert the workflow result
        self.assertEqual(result, "Workflow completed")

        # Verify the sequence of operations
        mock_workflow_manager.create.assert_called_once_with("mock_task", "dev_branch")
        mock_git_manager.commit.assert_any_call("mock_project", "Development changes")
        mock_git_manager.commit.assert_any_call("mock_project", "Testing changes")
        mock_tester_agent.test.assert_called_once_with("mock_project", "workflow_file")
        mock_reviewer_agent.review.assert_called_once_with("mock_project", "workflow_file")
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
