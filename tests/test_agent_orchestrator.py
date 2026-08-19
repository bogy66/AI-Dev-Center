import unittest
from unittest.mock import MagicMock
from app.agent_orchestrator import AgentOrchestrator

class TestAgentOrchestrator(unittest.TestCase):
    def test_run(self):
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
