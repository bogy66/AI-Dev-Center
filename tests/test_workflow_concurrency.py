import threading
import time
from unittest.mock import MagicMock, patch
from pathlib import Path

from app.agent_orchestrator import AgentOrchestrator
from app.approval_manager import ApprovalManager
from app.workflow_manager import WorkflowManager


DEVELOPER_RESPONSE = """
## Dateien

### Datei:
app/example.py

### Aktion:
create

### Inhalt:
print("changed")

## Tests

python -m pytest -q
"""


def test_reject_during_reviewer_call_is_not_lost_on_review_failure(git_repo):
    """
    Reproduces the concrete F4 lost-update case:

    - run_workflow() reaches the reviewer stage.
    - While reviewer_agent.review() is still running (long call),
      a concurrent request rejects the (not yet approval_waiting)
      workflow via ApprovalManager.reject().
    - The reviewer then reports "changes_required".
    - The resulting review_failed save must NOT overwrite the
      concurrently persisted "rejected" approval back to "waiting",
      since this save does not establish a new approval phase.
    """
    storage = Path(git_repo) / "workflow_state.json"

    real_workflow = WorkflowManager(storage)
    approval = ApprovalManager(storage=storage)

    mock_agent_manager = MagicMock()
    mock_agent_executor = MagicMock()

    # Mock executor responses for developer and tester
    def executor_run(agent_role, task, project_context, role_name, max_tokens):
        if role_name == "developer":
            return DEVELOPER_RESPONSE
        elif role_name == "tester":
            return """
## Dateien

### Datei:
tests/test_example.py

### Aktion:
create

### Inhalt:
def test_example():
    assert True

## Tests

python -m pytest -q
"""
        return "mock_response"

    mock_agent_executor.run.side_effect = executor_run

    orchestrator = AgentOrchestrator(
        mock_agent_manager,
        mock_agent_executor,
        workflow_manager=real_workflow
    )

    git_manager = MagicMock()
    git_manager.commit_and_get_hash.return_value = {
        "code": 0,
        "commit": "abc123",
        "message": "DEV: Development completed"
    }

    reviewer_started = threading.Event()
    reject_done = threading.Event()

    reviewer_agent = MagicMock()

    def blocking_review(project, state):
        reviewer_started.set()
        reject_done.wait(timeout=5)
        return {
            "reviewer": {
                "status": "changes_required",
                "result": "Review fehlgeschlagen"
            }
        }

    reviewer_agent.review.side_effect = blocking_review

    file_applier = MagicMock()
    file_applier.apply.return_value = {
        "applied": ["app/example.py"]
    }

    with patch(
        "app.agent_orchestrator.GitManager",
        return_value=git_manager
    ), patch(
        "app.agent_orchestrator.ReviewerAgent",
        return_value=reviewer_agent
    ), patch(
        "app.agent_orchestrator.DeveloperFileApplier",
        return_value=file_applier
    ), patch(
        "app.agent_orchestrator.WorkspaceManager"
    ) as workspace_class, patch(
        "app.agent_orchestrator.TestBench"
    ) as testbench_class:

        # Mock workspace manager
        workspace_manager = workspace_class.return_value
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
        testbench_class.return_value = testbench_instance
        testbench_instance.setup_testbench.return_value = "/tmp/testbench"
        testbench_instance.merge_commits.return_value = True
        testbench_instance.run_tests.return_value = {"success": True, "output": "All tests passed"}
        testbench_instance.cleanup_testbench.return_value = None

        result_container = {}

        def run():
            result_container["result"] = orchestrator.run_workflow(
                git_repo,
                "mock_task"
            )

        worker = threading.Thread(target=run)
        worker.start()

        assert reviewer_started.wait(timeout=5), (
            "Expected reviewer_agent.review() to have started within "
            "the timeout."
        )

        approval.reject(
            approved_by="Udo",
            comment="Needs changes"
        )

        reject_done.set()

        worker.join(timeout=5)

    assert not worker.is_alive(), "Workflow thread did not finish in time."

    persisted = WorkflowManager(storage).load()

    assert persisted["user_approval"]["status"] == "rejected", (
        "Expected the concurrently rejected approval to be preserved, "
        "but a later orchestrator save overwrote it back to a "
        "non-rejected state. This reproduces the lost-update race "
        "between AgentOrchestrator and ApprovalManager on the shared "
        "workflow_state.json file."
    )

    assert persisted["user_approval"]["comment"] == "Needs changes"

    assert result_container["result"]["status"] == "review_failed"


def test_save_preserving_approval_keeps_current_approval_when_no_new_phase(
    git_repo
):
    storage = Path(git_repo) / "workflow_state.json"
    workflow = WorkflowManager(storage)

    workflow.save({
        "status": "started",
        "developer": {
            "status": "pending",
            "commit": None
        },
        "tester": {
            "status": "pending",
            "commit": None,
            "result": None
        },
        "reviewer": {
            "status": "pending",
            "result": None
        },
        "user_approval": {
            "status": "rejected",
            "approved_by": "Udo",
            "approved_at": "2026-01-01T00:00:00",
            "comment": "Needs changes"
        }
    })

    orchestrator = AgentOrchestrator(MagicMock(), MagicMock())

    stale_local_state = {
        "status": "tester_failed",
        "developer": {
            "status": "completed",
            "commit": "abc123"
        },
        "tester": {
            "status": "failed",
            "commit": "abc123",
            "result": "FAIL"
        },
        "reviewer": {
            "status": "pending",
            "result": None
        },
        "user_approval": {
            "status": "waiting",
            "approved_by": None,
            "approved_at": None,
            "comment": None
        }
    }

    merged = orchestrator._save_preserving_approval(
        workflow,
        stale_local_state
    )

    assert merged["user_approval"]["status"] == "rejected", (
        "Expected the currently persisted approval decision to be "
        "preserved, not the stale in-memory default carried by the "
        "orchestrator's local state."
    )
    assert merged["user_approval"]["comment"] == "Needs changes"
    assert merged["status"] == "tester_failed"
    assert merged["developer"]["commit"] == "abc123"

    persisted = WorkflowManager(storage).load()
    assert persisted["user_approval"]["status"] == "rejected"
    assert persisted["status"] == "tester_failed"


def test_save_preserving_approval_applies_explicit_new_phase(git_repo):
    storage = Path(git_repo) / "workflow_state.json"
    workflow = WorkflowManager(storage)

    workflow.save({
        "status": "started",
        "developer": {
            "status": "pending",
            "commit": None
        },
        "tester": {
            "status": "pending",
            "commit": None,
            "result": None
        },
        "reviewer": {
            "status": "pending",
            "result": None
        },
        "user_approval": {
            "status": "rejected",
            "approved_by": "Udo",
            "approved_at": "2026-01-01T00:00:00",
            "comment": "Old comment"
        }
    })

    orchestrator = AgentOrchestrator(MagicMock(), MagicMock())

    local_state = {
        "status": "approval_waiting",
        "developer": {
            "status": "completed",
            "commit": "new456"
        },
        "tester": {
            "status": "completed",
            "commit": "new456",
            "result": "PASS"
        },
        "reviewer": {
            "status": "approved",
            "result": "Review erfolgreich"
        }
    }

    new_approval = {
        "status": "waiting",
        "approved_by": None,
        "approved_at": None,
        "comment": "Old comment"
    }

    merged = orchestrator._save_preserving_approval(
        workflow,
        local_state,
        new_approval=new_approval
    )

    assert merged["user_approval"] == new_approval, (
        "Expected an explicitly provided new approval phase to "
        "overwrite the previously persisted approval decision."
    )
    assert merged["status"] == "approval_waiting"


def test_update_agent_does_not_lose_concurrent_updates(git_repo):
    """
    Forces an interleaving between two update_agent() calls on
    different WorkflowManager instances pointing at the same file,
    proving that the shared lock prevents a lost update.
    """
    storage = Path(git_repo) / "workflow_state.json"

    workflow_a = WorkflowManager(storage)
    workflow_a.create("mock_task", "dev_branch")

    workflow_b = WorkflowManager(storage)

    original_load = WorkflowManager.load

    def delayed_load(self):
        state = original_load(self)
        time.sleep(0.05)
        return state

    barrier = threading.Barrier(2)

    def update_tester():
        barrier.wait()
        workflow_a.update_agent(
            "tester",
            "completed",
            result="PASS"
        )

    def update_reviewer():
        barrier.wait()
        workflow_b.update_agent(
            "reviewer",
            "approved",
            result="Review erfolgreich"
        )

    with patch.object(WorkflowManager, "load", delayed_load):
        thread_a = threading.Thread(target=update_tester)
        thread_b = threading.Thread(target=update_reviewer)

        thread_a.start()
        thread_b.start()

        thread_a.join(timeout=5)
        thread_b.join(timeout=5)

    assert not thread_a.is_alive()
    assert not thread_b.is_alive()

    final_state = WorkflowManager(storage).load()

    assert final_state["tester"]["status"] == "completed", (
        "Expected the tester update to survive the concurrent "
        "reviewer update, but it was lost due to an unsynchronized "
        "read-modify-write race."
    )
    assert final_state["tester"]["result"] == "PASS"
    assert final_state["reviewer"]["status"] == "approved", (
        "Expected the reviewer update to survive the concurrent "
        "tester update, but it was lost due to an unsynchronized "
        "read-modify-write race."
    )
    assert final_state["reviewer"]["result"] == "Review erfolgreich"
