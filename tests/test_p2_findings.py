from unittest.mock import MagicMock, patch

from app.agent_orchestrator import AgentOrchestrator
from app.workflow_manager import WorkflowManager


# ---------------------------------------------------------------------------
# TC-F8-01
# Given: a persisted, "rejected" workflow state that is missing the
#        "developer" key (e.g. an older/partial state schema on disk).
# When:  orchestrator.rework_workflow() is called and the developer commit
#        succeeds.
# Then:  the in-memory normalization performed at the top of
#        rework_workflow() (via _ensure_workflow_state()) must survive
#        into the state that update_agent() operates on, so the resulting
#        state still contains the new developer commit instead of crashing.
# ---------------------------------------------------------------------------
def test_tc_f8_01_rework_workflow_loses_normalization_before_update_agent(
    tmp_path
):

    storage = tmp_path / "workflow_state.json"
    real_workflow = WorkflowManager(storage)

    # Deliberately missing the "developer" key, simulating a persisted
    # state that _ensure_workflow_state() would normally patch up only
    # in-memory.
    incomplete_state = {
        "task": "Some task",
        "branch": "dev_branch",
        "status": "changes_required",
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

    real_workflow.save(incomplete_state)

    mock_agent_manager = MagicMock()
    mock_agent_executor = MagicMock()

    mock_agent_executor.run.return_value = """
## Dateien

### Datei:
app/example.py

### Aktion:
update

### Inhalt:
print("fixed")

## Tests

python -m pytest -q
"""

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
    ), patch(
        "app.agent_orchestrator.ReviewerAgent"
    ), patch(
        "app.agent_orchestrator.DeveloperFileApplier"
    ) as applier_class:

        git_class.return_value.commit_and_get_hash.return_value = {
            "code": 0,
            "commit": "new123",
            "message": "DEV: Rework completed"
        }

        applier_class.return_value.apply.return_value = {
            "applied": ["app/example.py"]
        }

        # This currently raises KeyError: 'developer' because
        # workflow_manager.update_agent() re-loads the raw persisted
        # state (missing "developer") instead of reusing the in-memory
        # state normalized via _ensure_workflow_state() earlier in
        # rework_workflow().
        result = orchestrator.rework_workflow("mock_project")

    assert "developer" in result, (
        "Expected the persisted-but-incomplete state to be normalized "
        "before update_agent() operates on it, but the normalization "
        "performed at the top of rework_workflow() was discarded once "
        "update_agent() re-loaded the raw, incomplete state from disk."
    )

    assert result["developer"]["commit"] == "new123"


# ---------------------------------------------------------------------------
# TC-F10-01
# Given: a workflow state with stale, non-empty commit/result values.
# When:  update_agent() is called with explicit empty-string overrides.
# Then:  the explicitly passed empty strings must be stored, not silently
#        discarded by a truthiness check.
# ---------------------------------------------------------------------------
def test_tc_f10_01_update_agent_drops_falsy_commit_and_result(tmp_path):

    storage = tmp_path / "workflow_state.json"
    manager = WorkflowManager(storage)

    manager.create("Some task", "dev_branch")

    state = manager.load()
    state["developer"]["commit"] = "stale_commit"
    state["tester"]["result"] = "stale_result"
    manager.save(state)

    updated = manager.update_agent(
        "developer",
        "completed",
        commit=""
    )

    assert updated["developer"]["commit"] == "", (
        "Expected update_agent() to overwrite developer.commit with the "
        "explicitly passed empty string, but the falsy-value check "
        "`if commit:` silently discarded it, leaving the stale prior "
        f"value in place: {updated['developer']['commit']!r}"
    )

    updated = manager.update_agent(
        "tester",
        "completed",
        result=""
    )

    assert updated["tester"]["result"] == "", (
        "Expected update_agent() to overwrite tester.result with the "
        "explicitly passed empty string, but the falsy-value check "
        "`if result:` silently discarded it, leaving the stale prior "
        f"value in place: {updated['tester']['result']!r}"
    )


# ---------------------------------------------------------------------------
# TC-F11-01
# Given: a WorkflowManager whose storage file does not exist yet (no
#        create() has ever been called).
# When:  update_agent() is called directly on that fresh state.
# Then:  it must produce a sensible updated state instead of crashing,
#        despite load()'s minimal {"status": "not_started"} shape being
#        structurally different from what create() would have produced.
# ---------------------------------------------------------------------------
def test_tc_f11_01_update_agent_on_fresh_state_should_not_crash(tmp_path):

    storage = tmp_path / "workflow_state.json"
    manager = WorkflowManager(storage)

    assert not storage.exists()

    # update_agent() assumes the loaded state already has a nested dict
    # for the given agent (as create() would provide), but load()'s
    # "not_started" default does not include it. This currently raises
    # an unhandled KeyError instead of producing a sensible result.
    updated = manager.update_agent(
        "developer",
        "completed",
        commit="abc123"
    )

    assert updated["developer"]["status"] == "completed"
    assert updated["developer"]["commit"] == "abc123"
