import threading
from unittest.mock import MagicMock, patch

from app.agent_orchestrator import AgentOrchestrator
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


def _patch_success_dependencies():
    """
    Returns the patch context managers needed to make a full
    run_workflow()/rework_workflow() pass reach approval_waiting,
    with GitManager/TesterAgent/ReviewerAgent/DeveloperFileApplier all
    mocked to succeed.
    """
    return patch(
        "app.agent_orchestrator.GitManager"
    ), patch(
        "app.agent_orchestrator.TesterAgent"
    ), patch(
        "app.agent_orchestrator.ReviewerAgent"
    ), patch(
        "app.agent_orchestrator.DeveloperFileApplier"
    )


def _configure_success_mocks(git_class, tester_class, reviewer_class, applier_class):
    git_class.return_value.commit_and_get_hash.return_value = {
        "code": 0,
        "commit": "abc123",
        "message": "DEV: Development completed"
    }

    tester_class.return_value.test.return_value = {
        "tester": {
            "status": "completed",
            "commit": "abc123",
            "result": "PASS"
        }
    }

    reviewer_class.return_value.review.return_value = {
        "status": "approved"
    }

    applier_class.return_value.apply.return_value = {
        "applied": ["app/example.py"],
        "skipped": []
    }


def test_two_parallel_run_workflow_calls_only_one_actually_starts(tmp_path):

    project = str(tmp_path)

    started = threading.Event()
    release = threading.Event()

    def executor_run(agent_role, task, project_context, role_name, max_tokens):
        if role_name == "project_manager":
            started.set()
            release.wait(timeout=5)
            return "mock_response"
        if role_name == "developer":
            return DEVELOPER_RESPONSE
        return "mock_response"

    mock_agent_manager = MagicMock()
    mock_agent_executor = MagicMock()
    mock_agent_executor.run.side_effect = executor_run

    orchestrator = AgentOrchestrator(
        mock_agent_manager,
        mock_agent_executor,
        workflow_manager=WorkflowManager(tmp_path / "workflow_state.json")
    )

    results = {}

    with patch(
        "app.agent_orchestrator.GitManager"
    ) as git_class, patch(
        "app.agent_orchestrator.TesterAgent"
    ) as tester_class, patch(
        "app.agent_orchestrator.ReviewerAgent"
    ) as reviewer_class, patch(
        "app.agent_orchestrator.DeveloperFileApplier"
    ) as applier_class:

        _configure_success_mocks(
            git_class,
            tester_class,
            reviewer_class,
            applier_class
        )

        def run_a():
            results["a"] = orchestrator.run_workflow(
                project,
                "task_a"
            )

        thread_a = threading.Thread(target=run_a)
        thread_a.start()

        assert started.wait(timeout=5), (
            "Expected the first run_workflow() call to reach the "
            "project_manager step within the timeout."
        )

        result_b = orchestrator.run_workflow(
            project,
            "task_b"
        )

        release.set()
        thread_a.join(timeout=5)

    assert not thread_a.is_alive(), "First run_workflow() did not finish in time."

    assert result_b["status"] == "workflow_already_running", (
        "Expected a second concurrent run_workflow() call for the same "
        "project to be immediately rejected with an explicit "
        "'workflow_already_running' status, but got "
        f"{result_b['status']!r}."
    )

    assert results["a"]["status"] == "approval_waiting", (
        "Expected the first run_workflow() call to complete normally "
        "once released, but got "
        f"{results['a']['status']!r}."
    )


def test_two_different_projects_can_run_in_parallel(tmp_path):

    project_a = str(tmp_path / "project_a")
    project_b = str(tmp_path / "project_b")

    started_a = threading.Event()
    release_a = threading.Event()

    def executor_run(agent_role, task, project_context, role_name, max_tokens):
        if role_name == "project_manager" and task == "task_a":
            started_a.set()
            release_a.wait(timeout=5)
            return "mock_response"
        if role_name == "developer":
            return DEVELOPER_RESPONSE
        return "mock_response"

    mock_agent_manager = MagicMock()
    mock_agent_executor = MagicMock()
    mock_agent_executor.run.side_effect = executor_run

    orchestrator_a = AgentOrchestrator(
        mock_agent_manager,
        mock_agent_executor,
        workflow_manager=WorkflowManager(tmp_path / "workflow_state_a.json")
    )

    orchestrator_b = AgentOrchestrator(
        mock_agent_manager,
        mock_agent_executor,
        workflow_manager=WorkflowManager(tmp_path / "workflow_state_b.json")
    )

    results = {}

    with patch(
        "app.agent_orchestrator.GitManager"
    ) as git_class, patch(
        "app.agent_orchestrator.TesterAgent"
    ) as tester_class, patch(
        "app.agent_orchestrator.ReviewerAgent"
    ) as reviewer_class, patch(
        "app.agent_orchestrator.DeveloperFileApplier"
    ) as applier_class:

        _configure_success_mocks(
            git_class,
            tester_class,
            reviewer_class,
            applier_class
        )

        def run_a():
            results["a"] = orchestrator_a.run_workflow(
                project_a,
                "task_a"
            )

        thread_a = threading.Thread(target=run_a)
        thread_a.start()

        assert started_a.wait(timeout=5), (
            "Expected the first run_workflow() call to reach the "
            "project_manager step within the timeout."
        )

        results["b"] = orchestrator_b.run_workflow(
            project_b,
            "task_b"
        )

        release_a.set()
        thread_a.join(timeout=5)

    assert not thread_a.is_alive(), "First run_workflow() did not finish in time."

    assert results["b"]["status"] != "workflow_already_running", (
        "Expected a run_workflow() call for a different project to "
        "proceed normally while another project's workflow is still "
        "running, but it was rejected as 'workflow_already_running'. "
        f"Got status {results['b']['status']!r}."
    )

    assert results["a"]["status"] != "workflow_already_running"


def test_run_workflow_blocks_concurrent_rework_workflow_for_same_project(
    tmp_path
):

    project = str(tmp_path)

    started = threading.Event()
    release = threading.Event()

    def executor_run(agent_role, task, project_context, role_name, max_tokens):
        if role_name == "project_manager":
            started.set()
            release.wait(timeout=5)
            return "mock_response"
        if role_name == "developer":
            return DEVELOPER_RESPONSE
        return "mock_response"

    mock_agent_manager = MagicMock()
    mock_agent_executor = MagicMock()
    mock_agent_executor.run.side_effect = executor_run

    orchestrator = AgentOrchestrator(
        mock_agent_manager,
        mock_agent_executor,
        workflow_manager=WorkflowManager(tmp_path / "workflow_state.json")
    )

    results = {}

    with patch(
        "app.agent_orchestrator.GitManager"
    ) as git_class, patch(
        "app.agent_orchestrator.TesterAgent"
    ) as tester_class, patch(
        "app.agent_orchestrator.ReviewerAgent"
    ) as reviewer_class, patch(
        "app.agent_orchestrator.DeveloperFileApplier"
    ) as applier_class:

        _configure_success_mocks(
            git_class,
            tester_class,
            reviewer_class,
            applier_class
        )

        def run_a():
            results["run"] = orchestrator.run_workflow(
                project,
                "task_a"
            )

        thread_a = threading.Thread(target=run_a)
        thread_a.start()

        assert started.wait(timeout=5), (
            "Expected run_workflow() to reach the project_manager step "
            "within the timeout."
        )

        results["rework"] = orchestrator.rework_workflow(project)

        release.set()
        thread_a.join(timeout=5)

    assert not thread_a.is_alive(), "run_workflow() did not finish in time."

    assert results["rework"]["status"] == "workflow_already_running", (
        "Expected rework_workflow() to be rejected as "
        "'workflow_already_running' while run_workflow() is still in "
        "progress for the same project, but got "
        f"{results['rework']['status']!r}."
    )

    assert results["run"]["status"] != "workflow_already_running"


def test_guard_is_released_after_completion_allowing_subsequent_call(
    tmp_path
):

    project = str(tmp_path)

    mock_agent_manager = MagicMock()
    mock_agent_executor = MagicMock()
    mock_agent_executor.run.return_value = DEVELOPER_RESPONSE

    orchestrator = AgentOrchestrator(
        mock_agent_manager,
        mock_agent_executor,
        workflow_manager=WorkflowManager(tmp_path / "workflow_state.json")
    )

    with patch(
        "app.agent_orchestrator.GitManager"
    ) as git_class, patch(
        "app.agent_orchestrator.TesterAgent"
    ) as tester_class, patch(
        "app.agent_orchestrator.ReviewerAgent"
    ) as reviewer_class, patch(
        "app.agent_orchestrator.DeveloperFileApplier"
    ) as applier_class:

        _configure_success_mocks(
            git_class,
            tester_class,
            reviewer_class,
            applier_class
        )

        first_result = orchestrator.run_workflow(
            project,
            "task_one"
        )

        assert first_result["status"] == "approval_waiting"

        second_result = orchestrator.run_workflow(
            project,
            "task_two"
        )

    assert second_result["status"] != "workflow_already_running", (
        "Expected the guard to be released after the first "
        "run_workflow() call completed, allowing a subsequent "
        "sequential call for the same project to proceed normally, "
        f"but got {second_result['status']!r}."
    )
