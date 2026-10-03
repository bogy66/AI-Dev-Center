from pathlib import Path
from types import SimpleNamespace
import threading

import pytest

from app.canonical_execution import (
    PROCESS_OWNER_ID, ConcurrentExecutionError, ExecutionReentryError,
    RecoveryRequiredError, acquire_project_execution,
)
from app.dev_workflow import SetupDevelopmentTestingResult
from app.project_setup_application import ProjectSetupApplicationService
from app.workflow_manager import WorkflowManager


def _result(status="review_failed"):
    controlled = SimpleNamespace(status=status, final_result=SimpleNamespace(status=status))
    return SetupDevelopmentTestingResult((), controlled)


def _service(tmp_path, workflow):
    return ProjectSetupApplicationService(
        workflow, workflow_manager=WorkflowManager(tmp_path / "state.json"),
    )


def test_same_project_allows_only_one_mutating_execution(tmp_path):
    started = threading.Event()
    release = threading.Event()
    workflow = SimpleNamespace()
    calls = []

    def execute(plan, request):
        calls.append(request.run_id)
        started.set()
        assert release.wait(5)
        return _result()

    workflow.execute_approved_and_run_development = execute
    service = _service(tmp_path, workflow)
    results = {}

    worker = threading.Thread(target=lambda: results.setdefault(
        "first", service.execute_approved_setup_and_development(
            SimpleNamespace(id="plan-a"), "project", tmp_path / "project", "task", "run-a"
        )
    ))
    worker.start()
    assert started.wait(5)
    with pytest.raises(ConcurrentExecutionError):
        service.execute_approved_setup_and_development(
            SimpleNamespace(id="plan-b"), "project", tmp_path / "project", "task", "run-b"
        )
    release.set()
    worker.join(5)
    assert not worker.is_alive()
    assert calls == ["run-a"]


def test_different_projects_can_mutate_independently(tmp_path):
    lease_a = acquire_project_execution(tmp_path / "a", "run-a", "development")
    try:
        lease_b = acquire_project_execution(tmp_path / "b", "run-b", "development")
        lease_b.release()
    finally:
        lease_a.release()


def test_lifecycle_persists_reload_and_reads_do_not_mutate(tmp_path):
    path = tmp_path / "state.json"
    manager = WorkflowManager(path)
    manager.begin_execution("run-a", "development", tmp_path / "project", PROCESS_OWNER_ID)
    before = path.read_bytes()
    assert WorkflowManager(path).get_execution_state("run-a")["status"] == "started"
    assert path.read_bytes() == before
    manager.finish_execution("run-a", "development", PROCESS_OWNER_ID, "completed")
    assert WorkflowManager(path).get_execution_state("run-a")["status"] == "completed"
    assert manager.get_execution_state("unknown")["status"] == "not_started"


def test_controlled_exception_is_failed_and_reentry_is_rejected(tmp_path):
    workflow = SimpleNamespace()
    workflow.execute_approved_and_run_development = lambda plan, request: (_ for _ in ()).throw(RuntimeError("boom"))
    service = _service(tmp_path, workflow)
    with pytest.raises(RuntimeError, match="boom"):
        service.execute_approved_setup_and_development(
            SimpleNamespace(id="plan"), "project", tmp_path / "project", "task", "run"
        )
    assert service._workflow_manager.get_execution_state("run")["status"] == "failed"
    lease = acquire_project_execution(tmp_path / "project", "other", "development")
    lease.release()
    with pytest.raises(ExecutionReentryError):
        service.execute_approved_setup_and_development(
            SimpleNamespace(id="plan"), "project", tmp_path / "project", "task", "run"
        )


def test_completed_setup_and_development_cannot_start_twice(tmp_path):
    calls = []
    workflow = SimpleNamespace()
    workflow.execute_approved_and_run_development = lambda plan, request: (
        calls.append(request.run_id) or _result()
    )
    service = _service(tmp_path, workflow)
    service.execute_approved_setup_and_development(
        SimpleNamespace(id="plan"), "project", tmp_path / "project", "task", "run"
    )
    with pytest.raises(ExecutionReentryError):
        service.execute_approved_setup_and_development(
            SimpleNamespace(id="plan"), "project", tmp_path / "project", "task", "run"
        )
    assert calls == ["run"]


def test_interrupted_execution_requires_recovery_and_does_not_rerun(tmp_path):
    calls = []
    workflow = SimpleNamespace()

    def interrupted(plan, request):
        calls.append(request.run_id)
        raise SystemExit("simulated crash")

    workflow.execute_approved_and_run_development = interrupted
    service = _service(tmp_path, workflow)
    with pytest.raises(SystemExit):
        service.execute_approved_setup_and_development(
            SimpleNamespace(id="plan"), "project", tmp_path / "project", "task", "run"
        )
    assert service._workflow_manager.get_execution_state("run")["status"] == "started"

    replacement = _service(tmp_path, workflow)
    with pytest.raises(RecoveryRequiredError):
        replacement.execute_approved_setup_and_development(
            SimpleNamespace(id="plan"), "project", tmp_path / "project", "task", "run"
        )
    assert calls == ["run"]
    assert replacement._workflow_manager.get_execution_state("run")["status"] == "recovery_required"


def test_lifecycle_updates_preserve_terminal_approval_state(tmp_path):
    manager = WorkflowManager(tmp_path / "state.json")
    state = manager.load()
    state["final_approvals"]["run"] = {"status": "approved", "development_status": "accepted"}
    manager.save(state)
    manager.begin_execution("other", "development", tmp_path / "project", PROCESS_OWNER_ID)
    manager.finish_execution("other", "development", PROCESS_OWNER_ID, "failed")
    assert manager.load()["final_approvals"]["run"]["status"] == "approved"
