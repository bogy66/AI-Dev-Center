from unittest.mock import MagicMock, patch

from app.agent_orchestrator import AgentOrchestrator


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


def _developer_only_executor(response=DEVELOPER_RESPONSE):
    def executor_run(agent_role, task, project_context, role_name, max_tokens):
        if role_name == "developer":
            return response
        return "mock_response"
    return executor_run


def _initial_state():
    return {
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


def _rejected_workflow_state():
    return {
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


# ---------------------------------------------------------------------------
# TC-F5-01
# Given: run_workflow, developer proposes only a create action for a
#        file that already exists (skipped, nothing applied).
# When:  orchestrator.run_workflow() is called.
# Then:  result["status"] must be a distinct, explicit status,
#        different from "development_no_changes" (which means the LLM
#        proposed no changes at all).
# ---------------------------------------------------------------------------
def test_run_workflow_create_on_existing_file_only_is_development_incomplete():

    mock_agent_manager = MagicMock()
    mock_agent_executor = MagicMock()
    mock_agent_executor.run.side_effect = _developer_only_executor()

    orchestrator = AgentOrchestrator(
        mock_agent_manager,
        mock_agent_executor
    )

    git_manager = MagicMock()
    tester_agent = MagicMock()
    reviewer_agent = MagicMock()

    file_applier = MagicMock()
    file_applier.apply.return_value = {
        "applied": [],
        "skipped": [
            {
                "file": "app/example.py",
                "reason": "already_exists"
            }
        ]
    }

    initial_state = _initial_state()

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
        workflow_manager.load.return_value = initial_state

        result = orchestrator.run_workflow(
            "mock_project",
            "mock_task"
        )

        git_manager.commit_and_get_hash.assert_not_called()
        tester_agent.test.assert_not_called()
        reviewer_agent.review.assert_not_called()

    assert result["status"] == "development_incomplete", (
        "Expected a skipped create-on-existing-file to be reported as "
        "'development_incomplete', distinct from 'development_no_changes' "
        "(which means the LLM proposed no changes at all), but got "
        f"{result['status']!r}."
    )

    assert result["status"] != "development_no_changes"

    assert result["developer"]["skipped"] == [
        {
            "file": "app/example.py",
            "reason": "already_exists"
        }
    ]


# ---------------------------------------------------------------------------
# TC-F5-02
# Given: run_workflow, developer proposes a mix of one successfully
#        applied change and one skipped create-on-existing-file.
# When:  orchestrator.run_workflow() is called.
# Then:  the workflow must NOT silently continue to commit/test/review/
#        approval as if everything succeeded.
# ---------------------------------------------------------------------------
def test_run_workflow_mixed_applied_and_skipped_does_not_reach_approval():

    mock_agent_manager = MagicMock()
    mock_agent_executor = MagicMock()
    mock_agent_executor.run.side_effect = _developer_only_executor()

    orchestrator = AgentOrchestrator(
        mock_agent_manager,
        mock_agent_executor
    )

    git_manager = MagicMock()
    tester_agent = MagicMock()
    reviewer_agent = MagicMock()

    file_applier = MagicMock()
    file_applier.apply.return_value = {
        "applied": ["app/foo.py"],
        "skipped": [
            {
                "file": "app/bar.py",
                "reason": "already_exists"
            }
        ]
    }

    initial_state = _initial_state()

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
        workflow_manager.load.return_value = initial_state

        result = orchestrator.run_workflow(
            "mock_project",
            "mock_task"
        )

        git_manager.commit_and_get_hash.assert_not_called()
        tester_agent.test.assert_not_called()
        reviewer_agent.review.assert_not_called()

    assert result["status"] == "development_incomplete", (
        "Expected a mix of applied and skipped changes to be reported "
        "as an incomplete development step, not silently proceeding to "
        "commit/test/review/approval as if everything succeeded, but "
        f"got {result['status']!r}."
    )

    assert result["status"] != "approval_waiting"

    assert result["developer"]["skipped"] == [
        {
            "file": "app/bar.py",
            "reason": "already_exists"
        }
    ]


# ---------------------------------------------------------------------------
# TC-F5-03
# Given: rework_workflow (rejected state), developer proposes a mix of
#        one successfully applied change and one skipped
#        create-on-existing-file.
# When:  orchestrator.rework_workflow() is called.
# Then:  the workflow must NOT silently continue to commit/test/review/
#        approval, and the existing "rejected" approval must be kept
#        untouched.
# ---------------------------------------------------------------------------
def test_rework_workflow_mixed_applied_and_skipped_does_not_reach_approval():

    mock_agent_manager = MagicMock()
    mock_agent_executor = MagicMock()
    mock_agent_executor.run.return_value = DEVELOPER_RESPONSE

    orchestrator = AgentOrchestrator(
        mock_agent_manager,
        mock_agent_executor
    )

    workflow_state = _rejected_workflow_state()

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

        applier_class.return_value.apply.return_value = {
            "applied": ["app/example.py"],
            "skipped": [
                {
                    "file": "app/new_thing.py",
                    "reason": "already_exists"
                }
            ]
        }

        result = orchestrator.rework_workflow(
            "mock_project"
        )

        git_class.return_value.commit_and_get_hash.assert_not_called()
        tester_class.return_value.test.assert_not_called()
        reviewer_class.return_value.review.assert_not_called()

    assert result["status"] == "development_incomplete", (
        "Expected rework_workflow() to report a mix of applied and "
        "skipped changes as an incomplete development step, but got "
        f"{result['status']!r}."
    )

    assert result["status"] != "approval_waiting"

    assert result["developer"]["skipped"] == [
        {
            "file": "app/new_thing.py",
            "reason": "already_exists"
        }
    ]

    assert result["user_approval"]["status"] == "rejected"


# ---------------------------------------------------------------------------
# TC-F5-04
# Given: rework_workflow (rejected state), an existing file already
#        present in the target project.
# When:  orchestrator.rework_workflow() is called.
# Then:  the developer LLM call must receive a non-empty project
#        context that lists the already-existing file, so the LLM can
#        choose "update" instead of "create" for it.
# ---------------------------------------------------------------------------
def test_rework_workflow_provides_existing_file_context_to_developer(
    tmp_path
):

    app_dir = tmp_path / "app"
    app_dir.mkdir(parents=True)

    (app_dir / "existing.py").write_text(
        'print("already here")',
        encoding="utf-8"
    )

    mock_agent_manager = MagicMock()
    mock_agent_executor = MagicMock()
    mock_agent_executor.run.return_value = DEVELOPER_RESPONSE

    orchestrator = AgentOrchestrator(
        mock_agent_manager,
        mock_agent_executor
    )

    workflow_state = _rejected_workflow_state()

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
            "applied": ["app/example.py"],
            "skipped": []
        }

        tester_class.return_value.test.return_value = {
            "status": "completed",
            "result": "PASS"
        }

        reviewer_class.return_value.review.return_value = {
            "status": "approved",
            "result": "Review erfolgreich"
        }

        orchestrator.rework_workflow(
            str(tmp_path)
        )

    calls = mock_agent_executor.run.call_args_list

    developer_calls = [
        call for call in calls
        if call.args[3] == "developer"
    ]

    assert len(developer_calls) == 1

    project_context = developer_calls[0].args[2]

    assert project_context != "", (
        "Expected rework_workflow() to provide the developer with "
        "context about already-existing project files, but the "
        "project_context argument was empty."
    )

    assert "existing.py" in project_context, (
        "Expected the existing project file to be listed in the "
        "developer's context so the LLM can distinguish between "
        "'create' and 'update' actions, but it was not found in: "
        f"{project_context!r}"
    )
