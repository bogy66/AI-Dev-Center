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
    @patch("app.agent_orchestrator.WorkspaceManager")
    @patch("app.agent_orchestrator.TestBench")
    def test_workflow_happy_path(
        self,
        MockTestBench,
        MockWorkspaceManager,
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

        # Mock workspace manager
        workspace_manager = MockWorkspaceManager.return_value
        workspace_manager.create_developer_workspace.return_value = {
            "path": "/tmp/dev_workspace",
            "branch": "dev-branch"
        }
        workspace_manager.create_tester_workspace.return_value = {
            "path": "/tmp/test_workspace", 
            "branch": "test-branch"
        }

        # Mock test bench to succeed completely
        testbench_instance = MagicMock()
        MockTestBench.return_value = testbench_instance
        testbench_instance.setup_testbench.return_value = "/tmp/testbench"
        testbench_instance.merge_commits.return_value = True
        testbench_instance.run_tests.return_value = {"success": True, "output": "All tests passed"}
        testbench_instance.cleanup_testbench.return_value = None

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

        # Expect two apply calls: one for developer changes, one for tester changes
        self.assertEqual(MockDeveloperFileApplier.return_value.apply.call_count, 2)

        MockTesterAgent.return_value.test.assert_called_once()
        MockReviewerAgent.return_value.review.assert_called_once()

        # Expect two commit calls: one for developer workspace, one for tester workspace
        self.assertEqual(MockGitManager.return_value.commit_and_get_hash.call_count, 2)
        
        commit_calls = MockGitManager.return_value.commit_and_get_hash.call_args_list
        
        # Verify developer commit
        developer_commit_found = False
        tester_commit_found = False
        
        for call in commit_calls:
            workspace_path, commit_message = call[0]
            if workspace_path == "/tmp/dev_workspace" and commit_message == "DEV: Development completed":
                developer_commit_found = True
            elif workspace_path == "/tmp/test_workspace" and commit_message == "TEST: Added tests":
                tester_commit_found = True
        
        self.assertTrue(developer_commit_found, "Expected developer commit with '/tmp/dev_workspace' and 'DEV: Development completed'")
        self.assertTrue(tester_commit_found, "Expected tester commit with '/tmp/test_workspace' and 'TEST: Added tests'")

    @patch("app.agent_orchestrator.WorkflowManager")
    @patch("app.agent_orchestrator.GitManager")
    @patch("app.agent_orchestrator.TesterAgent")
    @patch("app.agent_orchestrator.ReviewerAgent")
    @patch("app.agent_orchestrator.DeveloperFileApplier")
    @patch("app.agent_orchestrator.WorkspaceManager")
    @patch("app.agent_orchestrator.TestBench")
    def test_workflow_tester_failure(
        self,
        MockTestBench,
        MockWorkspaceManager,
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

        # Mock workspace manager
        workspace_manager = MockWorkspaceManager.return_value
        workspace_manager.create_developer_workspace.return_value = {
            "path": "/tmp/dev_workspace",
            "branch": "dev-branch"
        }
        workspace_manager.create_tester_workspace.return_value = {
            "path": "/tmp/test_workspace", 
            "branch": "test-branch"
        }

        # Mock test bench to succeed completely
        testbench_instance = MagicMock()
        MockTestBench.return_value = testbench_instance
        testbench_instance.setup_testbench.return_value = "/tmp/testbench"
        testbench_instance.merge_commits.return_value = True
        testbench_instance.run_tests.return_value = {"success": True, "output": "All tests passed"}
        testbench_instance.cleanup_testbench.return_value = None

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
    @patch("app.agent_orchestrator.WorkspaceManager")
    @patch("app.agent_orchestrator.TestBench")
    def test_workflow_reviewer_failure(
        self,
        MockTestBench,
        MockWorkspaceManager,
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

        # Mock workspace manager
        workspace_manager = MockWorkspaceManager.return_value
        workspace_manager.create_developer_workspace.return_value = {
            "path": "/tmp/dev_workspace",
            "branch": "dev-branch"
        }
        workspace_manager.create_tester_workspace.return_value = {
            "path": "/tmp/test_workspace", 
            "branch": "test-branch"
        }

        # Mock test bench to succeed completely
        testbench_instance = MagicMock()
        MockTestBench.return_value = testbench_instance
        testbench_instance.setup_testbench.return_value = "/tmp/testbench"
        testbench_instance.merge_commits.return_value = True
        testbench_instance.run_tests.return_value = {"success": True, "output": "All tests passed"}
        testbench_instance.cleanup_testbench.return_value = None

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
