from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.dev_workflow import SetupDevelopmentTestingResult
from app.final_approval import FinalApprovalError
from app.project_setup_application import ProjectSetupApplicationService
from app.workflow_manager import WorkflowManager


def _service(tmp_path, status="accepted"):
    workflow = Mock()
    workflow.execute_approved_and_run_development.return_value = SetupDevelopmentTestingResult(
        (), SimpleNamespace(status=status, final_result=SimpleNamespace()),
    )
    manager = WorkflowManager(tmp_path / "workflow_state.json")
    return ProjectSetupApplicationService(workflow, Mock(), manager), workflow, manager


def test_accepted_run_creates_persisted_pending_final_approval(tmp_path):
    service, _, manager = _service(tmp_path)

    result = service.execute_approved_setup_and_development(
        Mock(id="plan-1"), "project", tmp_path, "task", "run-a"
    )

    assert result.status == "accepted"
    assert result.final_approval_result.status == "pending"
    assert result.final_approval_result.ready_for_git is False
    state = manager.load()
    assert state["final_approvals"]["run-a"]["status"] == "pending"
    assert state["user_approval"]["status"] == "waiting"


@pytest.mark.parametrize("status", ["rework_required", "review_failed"])
def test_nonaccepted_run_has_no_final_approval(status, tmp_path):
    service, _, manager = _service(tmp_path, status)

    result = service.execute_approved_setup_and_development(
        Mock(id="plan-1"), "project", tmp_path, "task", "run-a"
    )

    assert result.final_approval_result.status == "not_applicable"
    assert result.final_approval_result.applicable is False
    assert manager.load()["final_approvals"] == {}


def test_final_approval_is_explicit_idempotent_and_ready_for_git(tmp_path):
    service, workflow, _ = _service(tmp_path)
    service.execute_approved_setup_and_development(Mock(id="plan-1"), "project", tmp_path, "task", "run-a")

    approved = service.decide_final_approval("run-a", "approved", "Udo")
    approved_again = service.decide_final_approval("run-a", "approved", "Udo")

    assert approved.status == approved_again.status == "approved"
    assert approved.ready_for_git is True
    workflow.execute_approved_and_run_development.assert_called_once()


def test_rejection_is_terminal_and_isolated_to_its_run(tmp_path):
    service, _, _ = _service(tmp_path)
    for run_id in ("run-a", "run-b"):
        service.execute_approved_setup_and_development(Mock(id=run_id), "project", tmp_path, "task", run_id)

    rejected = service.decide_final_approval("run-a", "rejected", "Udo")

    assert rejected.status == "rejected"
    with pytest.raises(FinalApprovalError, match="Cannot change"):
        service.decide_final_approval("run-a", "approved", "Udo")
    assert service.decide_final_approval("run-b", "approved", "Udo").status == "approved"


def test_final_approval_requires_a_persisted_accepted_run(tmp_path):
    service, _, _ = _service(tmp_path)

    with pytest.raises(FinalApprovalError, match="No accepted development run"):
        service.decide_final_approval("missing", "approved", "Udo")
