from unittest.mock import MagicMock, patch

from app.agent_orchestrator import AgentOrchestrator
from app.workflow_manager import WorkflowManager


DEVELOPER_RESPONSE = """
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


def _developer_only_executor(response=DEVELOPER_RESPONSE):
    def executor_run(agent_role, task, project_context, role_name, max_tokens):
        if role_name == "developer":
            return response
        return "mock_response"
    return executor_run


# ---------------------------------------------------------------------------
# TC-F1-01
# Given: fresh workflow state, developer change applied successfully,
#        git commit fails with a generic (non "nothing to commit") error.
# When:  orchestrator.run_workflow() is called.
# Then:  result["status"] must be an explicit, distinct failure marker,
#        not silently left as the untouched prior state.
# ---------------------------------------------------------------------------
def test_tc_f1_01_git_commit_failure_not_signaled_in_run_workflow():

    mock_agent_manager = MagicMock()
    mock_agent_executor = MagicMock()
    mock_agent_executor.run.side_effect = _developer_only_executor()

    orchestrator = AgentOrchestrator(
        mock_agent_manager,
        mock_agent_executor
    )

    git_manager = MagicMock()
    git_manager.commit_and_get_hash.return_value = {
        "code": 1,
        "stdout": "error: could not lock config file",
        "message": ""
    }

    file_applier = MagicMock()
    file_applier.apply.return_value = {
        "applied": ["app/example.py"]
    }

    initial_state = {
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
            "status": "waiting",
            "approved_by": None,
            "approved_at": None,
            "comment": None
        }
    }

    with patch(
        "app.agent_orchestrator.GitManager",
        return_value=git_manager
    ), patch(
        "app.agent_orchestrator.TesterAgent"
    ), patch(
        "app.agent_orchestrator.ReviewerAgent"
    ) as reviewer_class, patch(
        "app.agent_orchestrator.WorkflowManager"
    ) as workflow_class, patch(
        "app.agent_orchestrator.DeveloperFileApplier",
        return_value=file_applier
    ):

        workflow_manager = workflow_class.return_value
        workflow_manager.storage = "mock_workflow_state.json"
        workflow_manager.load.return_value = initial_state

        result = orchestrator.run_workflow(
            "mock_project",
            "mock_task"
        )

        reviewer_class.return_value.review.assert_not_called()

    assert result["status"] == "development_failed", (
        "Expected an explicit failure status ('development_failed') when "
        "git commit fails with a generic error, but got "
        f"{result['status']!r}. The current implementation silently "
        "returns the unchanged prior state on any commit failure that "
        "does not match the 'nothing to commit' pattern."
    )

    assert result["developer"]["status"] == "pending"
    assert result["developer"]["commit"] is None


# ---------------------------------------------------------------------------
# TC-F2-01
# Given: a rejected workflow state (rework scenario), developer change
#        applied successfully, git commit fails with a generic error.
# When:  orchestrator.rework_workflow() is called.
# Then:  result["status"] must be an explicit, distinct failure marker.
# ---------------------------------------------------------------------------
def test_tc_f2_01_git_commit_failure_not_signaled_in_rework_workflow():

    mock_agent_manager = MagicMock()
    mock_agent_executor = MagicMock()
    mock_agent_executor.run.return_value = DEVELOPER_RESPONSE

    orchestrator = AgentOrchestrator(
        mock_agent_manager,
        mock_agent_executor
    )

    workflow_state = {
        "task": "Erstelle app/example.py",
        "branch": "dev_branch",
        "status": "changes_required",
        "developer": {
            "status": "completed",
            "commit": "old123"
        },
        "tester": {
            "status": "failed",
            "commit": None,
            "result": "Inhalt stimmt nicht"
        },
        "reviewer": {
            "status": "changes_required",
            "result": "Review fehlgeschlagen"
        },
        "user_approval": {
            "status": "rejected",
            "approved_by": "Udo",
            "approved_at": "2026-08-19T20:40:01",
            "comment": "Needs changes"
        }
    }

    with patch(
        "app.agent_orchestrator.WorkflowManager"
    ) as workflow_class, patch(
        "app.agent_orchestrator.GitManager"
    ) as git_class, patch(
        "app.agent_orchestrator.TesterAgent"
    ) as tester_class, patch(
        "app.agent_orchestrator.ReviewerAgent"
    ) as reviewer_class, patch(
        "app.agent_orchestrator.DeveloperFileApplier"
    ) as applier_class:

        workflow = workflow_class.return_value
        workflow.load.return_value = workflow_state
        workflow.storage = "mock_workflow_state.json"

        git_class.return_value.commit_and_get_hash.return_value = {
            "code": 1,
            "stdout": "fatal: unable to write new_index"
        }

        applier_class.return_value.apply.return_value = {
            "applied": ["app/example.py"]
        }

        result = orchestrator.rework_workflow(
            "mock_project"
        )

        tester_class.return_value.test.assert_not_called()
        reviewer_class.return_value.review.assert_not_called()

    assert result["status"] == "rework_failed", (
        "Expected an explicit failure status ('rework_failed') when git "
        "commit fails during rework, but got "
        f"{result['status']!r}. The current implementation has no "
        "special-case handling at all for commit failures in "
        "rework_workflow() and silently returns the unchanged prior state."
    )

    assert result["user_approval"]["status"] == "rejected"


# ---------------------------------------------------------------------------
# TC-F3-01
# Given: run_workflow, developer commit succeeds, tester reports FAIL.
# When:  orchestrator.run_workflow() is called.
# Then:  result["status"] must be an explicit "tester_failed" marker,
#        distinct from "started".
# ---------------------------------------------------------------------------
def test_tc_f3_01_run_workflow_status_not_updated_on_tester_failure():

    mock_agent_manager = MagicMock()
    mock_agent_executor = MagicMock()
    mock_agent_executor.run.side_effect = _developer_only_executor()

    orchestrator = AgentOrchestrator(
        mock_agent_manager,
        mock_agent_executor
    )

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

    with patch(
        "app.agent_orchestrator.WorkflowManager"
    ) as workflow_class, patch(
        "app.agent_orchestrator.GitManager"
    ) as git_class, patch(
        "app.agent_orchestrator.TesterAgent"
    ) as tester_class, patch(
        "app.agent_orchestrator.ReviewerAgent"
    ) as reviewer_class, patch(
        "app.agent_orchestrator.DeveloperFileApplier"
    ) as applier_class:

        workflow = workflow_class.return_value
        workflow.storage = "mock_workflow_state.json"
        workflow.create.return_value = state
        workflow.load.return_value = state

        applier_class.return_value.apply.return_value = {
            "applied": ["app/example.py"]
        }

        git_class.return_value.commit_and_get_hash.return_value = {
            "code": 0,
            "commit": "dev123"
        }

        tester_class.return_value.test.return_value = {
            "tester": {
                "status": "completed",
                "result": "FAIL"
            }
        }

        result = orchestrator.run_workflow(
            "mock_project",
            "mock_task"
        )

        reviewer_class.return_value.review.assert_not_called()

    assert result["status"] == "tester_failed", (
        "Expected an explicit failure status ('tester_failed') after a "
        "failing tester stage, but got "
        f"{result['status']!r}. The current implementation never writes "
        "to state['status'] on tester failure, leaving it at its prior "
        "value ('started')."
    )


# ---------------------------------------------------------------------------
# TC-F3-02
# Given: run_workflow, tester passes, reviewer requests changes.
# When:  orchestrator.run_workflow() is called.
# Then:  result["status"] must be an explicit "review_failed" marker.
# ---------------------------------------------------------------------------
def test_tc_f3_02_run_workflow_status_not_updated_on_reviewer_rejection():

    mock_agent_manager = MagicMock()
    mock_agent_executor = MagicMock()
    mock_agent_executor.run.side_effect = _developer_only_executor()

    orchestrator = AgentOrchestrator(
        mock_agent_manager,
        mock_agent_executor
    )

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

    with patch(
        "app.agent_orchestrator.WorkflowManager"
    ) as workflow_class, patch(
        "app.agent_orchestrator.GitManager"
    ) as git_class, patch(
        "app.agent_orchestrator.TesterAgent"
    ) as tester_class, patch(
        "app.agent_orchestrator.ReviewerAgent"
    ) as reviewer_class, patch(
        "app.agent_orchestrator.DeveloperFileApplier"
    ) as applier_class:

        workflow = workflow_class.return_value
        workflow.storage = "mock_workflow_state.json"
        workflow.create.return_value = state
        workflow.load.return_value = state

        applier_class.return_value.apply.return_value = {
            "applied": ["app/example.py"]
        }

        git_class.return_value.commit_and_get_hash.return_value = {
            "code": 0,
            "commit": "dev123"
        }

        tester_class.return_value.test.return_value = {
            "tester": {
                "status": "completed",
                "result": "PASS"
            }
        }

        reviewer_class.return_value.review.return_value = {
            "reviewer": {
                "status": "changes_required",
                "result": "Review failed"
            }
        }

        result = orchestrator.run_workflow(
            "mock_project",
            "mock_task"
        )

    assert result["status"] == "review_failed", (
        "Expected an explicit failure status ('review_failed') after a "
        "reviewer rejection, but got "
        f"{result['status']!r}. The current implementation never writes "
        "to state['status'] on reviewer rejection, leaving it at its "
        "prior value ('started')."
    )


# ---------------------------------------------------------------------------
# TC-F3-03
# Given: rework_workflow, developer commit succeeds, tester reports FAIL.
# When:  orchestrator.rework_workflow() is called.
# Then:  result["status"] must be an explicit "tester_failed" marker,
#        distinct from the prior "changes_required" status.
# ---------------------------------------------------------------------------
def test_tc_f3_03_rework_workflow_status_not_updated_on_tester_failure():

    mock_agent_manager = MagicMock()
    mock_agent_executor = MagicMock()
    mock_agent_executor.run.return_value = DEVELOPER_RESPONSE

    orchestrator = AgentOrchestrator(
        mock_agent_manager,
        mock_agent_executor
    )

    workflow_state = {
        "task": "Erstelle app/example.py",
        "branch": "dev_branch",
        "status": "changes_required",
        "developer": {
            "status": "completed",
            "commit": "old123"
        },
        "tester": {
            "status": "failed",
            "commit": None,
            "result": "Inhalt stimmt nicht"
        },
        "reviewer": {
            "status": "changes_required",
            "result": "Review fehlgeschlagen"
        },
        "user_approval": {
            "status": "rejected",
            "approved_by": "Udo",
            "approved_at": "2026-08-19T20:40:01",
            "comment": "Needs changes"
        }
    }

    with patch(
        "app.agent_orchestrator.WorkflowManager"
    ) as workflow_class, patch(
        "app.agent_orchestrator.GitManager"
    ) as git_class, patch(
        "app.agent_orchestrator.TesterAgent"
    ) as tester_class, patch(
        "app.agent_orchestrator.ReviewerAgent"
    ) as reviewer_class, patch(
        "app.agent_orchestrator.DeveloperFileApplier"
    ) as applier_class:

        workflow = workflow_class.return_value
        workflow.load.return_value = workflow_state
        workflow.storage = "mock_workflow_state.json"

        git_class.return_value.commit_and_get_hash.return_value = {
            "code": 0,
            "commit": "new123",
            "message": "DEV: Rework completed"
        }

        applier_class.return_value.apply.return_value = {
            "applied": ["app/example.py"]
        }

        tester_class.return_value.test.return_value = {
            "status": "completed",
            "result": "FAIL"
        }

        result = orchestrator.rework_workflow(
            "mock_project"
        )

        reviewer_class.return_value.review.assert_not_called()

    assert result["status"] == "tester_failed", (
        "Expected an explicit failure status ('tester_failed') after a "
        "failing tester stage during rework, but got "
        f"{result['status']!r}. The current implementation never writes "
        "to state['status'] on tester failure in rework_workflow(), "
        "leaving it at its prior value ('changes_required')."
    )


# ---------------------------------------------------------------------------
# TC-F3-04
# Given: rework_workflow, tester passes, reviewer requests changes again.
# When:  orchestrator.rework_workflow() is called.
# Then:  result["status"] must be an explicit "review_failed" marker,
#        distinct from the prior "changes_required" status.
# ---------------------------------------------------------------------------
def test_tc_f3_04_rework_workflow_status_not_updated_on_reviewer_rejection():

    mock_agent_manager = MagicMock()
    mock_agent_executor = MagicMock()
    mock_agent_executor.run.return_value = DEVELOPER_RESPONSE

    orchestrator = AgentOrchestrator(
        mock_agent_manager,
        mock_agent_executor
    )

    workflow_state = {
        "task": "Erstelle app/example.py",
        "branch": "dev_branch",
        "status": "changes_required",
        "developer": {
            "status": "completed",
            "commit": "old123"
        },
        "tester": {
            "status": "failed",
            "commit": None,
            "result": "Inhalt stimmt nicht"
        },
        "reviewer": {
            "status": "changes_required",
            "result": "Review fehlgeschlagen"
        },
        "user_approval": {
            "status": "rejected",
            "approved_by": "Udo",
            "approved_at": "2026-08-19T20:40:01",
            "comment": "Needs changes"
        }
    }

    with patch(
        "app.agent_orchestrator.WorkflowManager"
    ) as workflow_class, patch(
        "app.agent_orchestrator.GitManager"
    ) as git_class, patch(
        "app.agent_orchestrator.TesterAgent"
    ) as tester_class, patch(
        "app.agent_orchestrator.ReviewerAgent"
    ) as reviewer_class, patch(
        "app.agent_orchestrator.DeveloperFileApplier"
    ) as applier_class:

        workflow = workflow_class.return_value
        workflow.load.return_value = workflow_state
        workflow.storage = "mock_workflow_state.json"

        git_class.return_value.commit_and_get_hash.return_value = {
            "code": 0,
            "commit": "new123",
            "message": "DEV: Rework completed"
        }

        applier_class.return_value.apply.return_value = {
            "applied": ["app/example.py"]
        }

        tester_class.return_value.test.return_value = {
            "status": "completed",
            "result": "PASS"
        }

        reviewer_class.return_value.review.return_value = {
            "status": "changes_required",
            "result": "Review failed again"
        }

        result = orchestrator.rework_workflow(
            "mock_project"
        )

    assert result["status"] == "review_failed", (
        "Expected an explicit failure status ('review_failed') after a "
        "reviewer rejection during rework, but got "
        f"{result['status']!r}. The current implementation never writes "
        "to state['status'] on reviewer rejection in rework_workflow(), "
        "leaving it at its prior value ('changes_required')."
    )


# ---------------------------------------------------------------------------
# TC-F4-01
# Given: a persisted workflow state already in "approval_waiting" with a
#        completed developer commit "abc123".
# When:  orchestrator.run_workflow() is called again with a new task,
#        before any approve/reject decision has been made.
# Then:  the pending approval state must be preserved (developer.commit
#        must still be "abc123"), not silently discarded.
# ---------------------------------------------------------------------------
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
            "result": "Review passed"
        },
        "user_approval": {
            "status": "waiting",
            "approved_by": None,
            "approved_at": None,
            "comment": None
        },
        "created": "2026-01-01 00:00:00"
    }

    real_workflow.save(pending_state)

    mock_agent_manager = MagicMock()
    mock_agent_executor = MagicMock()
    mock_agent_executor.run.side_effect = _developer_only_executor()

    orchestrator = AgentOrchestrator(
        mock_agent_manager,
        mock_agent_executor
    )

    git_manager = MagicMock()
    git_manager.commit_and_get_hash.return_value = {
        "code": 0,
        "commit": "new999",
        "message": "DEV: Development completed"
    }

    tester_agent = MagicMock()
    tester_agent.test.return_value = {
        "tester": {
            "status": "completed",
            "commit": "new999",
            "result": "PASS"
        }
    }

    reviewer_agent = MagicMock()
    reviewer_agent.review.return_value = {
        "status": "approved"
    }

    with patch(
        "app.agent_orchestrator.WorkflowManager",
        return_value=real_workflow
    ), patch(
        "app.agent_orchestrator.GitManager",
        return_value=git_manager
    ), patch(
        "app.agent_orchestrator.TesterAgent",
        return_value=tester_agent
    ), patch(
        "app.agent_orchestrator.ReviewerAgent",
        return_value=reviewer_agent
    ), patch(
        "app.agent_orchestrator.DeveloperFileApplier"
    ) as file_applier_class:

        file_applier_class.return_value.apply.return_value = {
            "applied": ["app/example.py"]
        }

        orchestrator.run_workflow(
            "mock_project",
            "New conflicting task"
        )

    persisted = real_workflow.load()

    assert persisted["developer"]["commit"] == "abc123", (
        "Expected the pending-approval state's developer commit "
        "('abc123') to be preserved, but got "
        f"{persisted['developer']['commit']!r}. The current "
        "implementation of run_workflow() unconditionally calls "
        "workflow_manager.create(), overwriting any existing "
        "in-progress or pending-approval workflow without any guard."
    )

    assert persisted["task"] == "Original task", (
        "Expected the original task belonging to the pending-approval "
        "workflow to be preserved, but it was overwritten by the new "
        "task, confirming the unconditional state overwrite."
    )

def test_tc_git_01_commit_and_get_hash_propagates_last_commit_failure():
    from app.git_manager import GitManager

    git = GitManager()

    git.commit = lambda project, message: {
        "code": 0,
        "stdout": "commit successful",
        "stderr": ""
    }

    git.last_commit = lambda project: {
        "code": 1,
        "stdout": "",
        "stderr": "fatal: not a git repository"
    }

    result = git.commit_and_get_hash(
        "/tmp/project",
        "test commit"
    )

    assert result["code"] != 0
    assert "fatal: not a git repository" in result["stderr"]
