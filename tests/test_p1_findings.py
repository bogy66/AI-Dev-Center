from unittest.mock import MagicMock, patch

from app.agent_orchestrator import AgentOrchestrator
from app.workflow_manager import WorkflowManager


def test_tc_f4_01_run_workflow_overwrites_pending_approval_state(tmp_path):

    storage = tmp_path / "workflow_state.json"

    real_workflow = WorkflowManager(storage)

    pending_state = {
        "task": "Original task",
        "branch": "dev_branch",
        "status": "approval_waiting",
        "developer": {
            "status": "completed",
            "commit": "abc123"
        },
        "tester": {
            "status": "completed",
            "commit": "abc123",
            "result": "PASS"
        },
        "reviewer": {
            "status": "approved",
            "result": "Review erfolgreich"
        },
        "user_approval": {
            "status": "waiting",
            "approved_by": None,
            "approved_at": None,
            "comment": None
        }
    }

    real_workflow.save(pending_state)

    mock_agent_manager = MagicMock()
    mock_agent_executor = MagicMock()

    orchestrator = AgentOrchestrator(
        mock_agent_manager,
        mock_agent_executor
    )

    with patch(
        "app.agent_orchestrator.WorkflowManager",
        return_value=real_workflow
    ), patch(
        "app.agent_orchestrator.GitManager"
    ) as git_class, patch(
        "app.agent_orchestrator.TesterAgent"
    ) as tester_class, patch(
        "app.agent_orchestrator.ReviewerAgent"
    ) as reviewer_class, patch(
        "app.agent_orchestrator.DeveloperFileApplier"
    ) as applier_class:

        result = orchestrator.run_workflow(
            "mock_project",
            "New task"
        )

    mock_agent_executor.run.assert_not_called()
    git_class.return_value.commit_and_get_hash.assert_not_called()
    tester_class.return_value.test.assert_not_called()
    reviewer_class.return_value.review.assert_not_called()
    applier_class.return_value.apply.assert_not_called()

    assert result["status"] == "approval_waiting"
    assert result["task"] == "Original task"
    assert result["developer"]["commit"] == "abc123"

    persisted = real_workflow.load()

    assert persisted["status"] == "approval_waiting"
    assert persisted["task"] == "Original task"
    assert persisted["developer"]["commit"] == "abc123"
