from unittest.mock import MagicMock, patch

from app.agent_orchestrator import AgentOrchestrator


class TestAgentOrchestrator:

    def test_run(self):
        mock_agent_manager = MagicMock()
        mock_agent_executor = MagicMock()

        mock_agent_manager.load_agents.return_value = {
            "project_manager": MagicMock(),
            "architect": MagicMock(),
            "developer": MagicMock(),
            "tester": MagicMock(),
            "reviewer": MagicMock()
        }

        mock_agent_manager.load_project_context.return_value = (
            "mock_project_context"
        )

        mock_agent_executor.run.return_value = "mock_response"

        orchestrator = AgentOrchestrator(
            mock_agent_manager,
            mock_agent_executor
        )

        responses = orchestrator.run(
            "mock_project",
            "mock_task"
        )

        expected_responses = {
            "project_manager": "mock_response",
            "architect": "mock_response",
            "developer": "mock_response",
            "tester": "mock_response",
            "reviewer": "mock_response"
        }

        assert responses == expected_responses

    def test_run_workflow_reaches_approval_waiting(self):

        mock_agent_manager = MagicMock()
        mock_agent_executor = MagicMock()

        developer_response = """
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

        def executor_run(
            agent_role,
            task,
            project_context,
            role_name,
            max_tokens
        ):
            if role_name == "developer":
                return developer_response

            return "mock_response"

        mock_agent_executor.run.side_effect = executor_run

        orchestrator = AgentOrchestrator(
            mock_agent_manager,
            mock_agent_executor
        )

        git_manager = MagicMock()

        git_manager.commit_and_get_hash.return_value = {
            "code": 0,
            "commit": "abc123",
            "message": "DEV: Development completed"
        }

        tester_agent = MagicMock()

        tester_agent.test.return_value = {
            "status": "approval_waiting",
            "tester": {
                "status": "completed",
                "commit": "abc123",
                "result": "PASS"
            }
        }

        reviewer_agent = MagicMock()

        reviewer_agent.review.return_value = {
            "status": "approved"
        }

        file_applier = MagicMock()

        file_applier.apply.return_value = {
            "applied": ["app/example.py"]
        }

        with patch(
            "app.agent_orchestrator.GitManager",
            return_value=git_manager
        ), patch(
            "app.agent_orchestrator.TesterAgent",
            return_value=tester_agent
        ), patch(
            "app.agent_orchestrator.ReviewerAgent",
            return_value=reviewer_agent
        ), patch(
            "app.agent_orchestrator.WorkflowManager"
        ) as workflow_class, patch(
            "app.agent_orchestrator.DeveloperFileApplier",
            return_value=file_applier
        ):

            workflow_manager = workflow_class.return_value

            workflow_manager.storage = "mock_workflow_state.json"

            workflow_manager.load.return_value = {
                "status": "approval_waiting"
            }

            result = orchestrator.run_workflow(
                "mock_project",
                "mock_task"
            )

        file_applier.apply.assert_called_once()

        git_manager.commit_and_get_hash.assert_called_once_with(
            "mock_project",
            "DEV: Development completed"
        )

        tester_agent.test.assert_called_once()
        reviewer_agent.review.assert_called_once()

        assert result["status"] == "approval_waiting"

    def test_run_workflow_applies_developer_changes(self):

        mock_agent_manager = MagicMock()
        mock_agent_executor = MagicMock()

        developer_response = """
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

        def executor_run(
            agent_role,
            task,
            project_context,
            role_name,
            max_tokens
        ):
            if role_name == "developer":
                return developer_response

            return "mock_response"

        mock_agent_executor.run.side_effect = executor_run

        orchestrator = AgentOrchestrator(
            mock_agent_manager,
            mock_agent_executor
        )

        git_manager = MagicMock()

        git_manager.commit_and_get_hash.return_value = {
            "code": 0,
            "commit": "abc123",
            "message": "DEV: Development completed"
        }

        tester_agent = MagicMock()

        tester_agent.test.return_value = {
            "status": "approval_waiting",
            "tester": {
                "status": "completed",
                "commit": "abc123",
                "result": "PASS"
            }
        }

        reviewer_agent = MagicMock()

        reviewer_agent.review.return_value = {
            "status": "approved"
        }

        file_applier = MagicMock()

        file_applier.apply.return_value = {
            "applied": ["app/example.py"]
        }

        with patch(
            "app.agent_orchestrator.GitManager",
            return_value=git_manager
        ), patch(
            "app.agent_orchestrator.TesterAgent",
            return_value=tester_agent
        ), patch(
            "app.agent_orchestrator.ReviewerAgent",
            return_value=reviewer_agent
        ), patch(
            "app.agent_orchestrator.WorkflowManager"
        ) as workflow_class, patch(
            "app.agent_orchestrator.DeveloperFileApplier",
            return_value=file_applier
        ):

            workflow_manager = workflow_class.return_value

            workflow_manager.storage = "mock_workflow_state.json"

            workflow_manager.load.return_value = {
                "status": "started",
                "developer": {
                    "status": "pending",
                    "commit": None
                }
            }

            result = orchestrator.run_workflow(
                "mock_project",
                "mock_task"
            )

        file_applier.apply.assert_called_once()

        git_manager.commit_and_get_hash.assert_called_once_with(
            "mock_project",
            "DEV: Development completed"
        )

        assert result["status"] == "approval_waiting"
