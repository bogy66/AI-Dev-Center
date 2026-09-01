from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from app.api import PublishRequest, Task, get_workflow_status, publish_workflow
from app.api import rework_workflow, run, run_workflow


def test_run_workflow_uses_canonical_application_service(tmp_path):
    plan = SimpleNamespace(status="pending_approval", id="plan-1")
    result = SimpleNamespace(setup_plan=plan)
    components = SimpleNamespace(
        service=Mock(plan_project_setup=Mock(return_value=result)),
        plan_store=Mock(),
    )
    with patch("app.api.get_canonical_components", return_value=components):
        response = run_workflow(Task(project=str(tmp_path), task="build it"))
    assert response == {
        "status": "pending_approval", "project_id": tmp_path.name,
        "plan_id": "plan-1", "run_id": response["run_id"],
    }
    call = components.service.plan_project_setup.call_args
    assert call.args == (tmp_path.name, tmp_path.resolve())
    assert call.kwargs == {"run_id": response["run_id"]}
    components.plan_store.save.assert_called_once_with(plan)


def test_run_alias_uses_same_canonical_adapter(tmp_path):
    plan = SimpleNamespace(status="pending_approval", id="plan-2")
    components = SimpleNamespace(
        service=Mock(plan_project_setup=Mock(
            return_value=SimpleNamespace(setup_plan=plan)
        )),
        plan_store=Mock(),
    )
    with patch("app.api.get_canonical_components", return_value=components):
        response = run(Task(project=str(tmp_path), task="build it"))
    assert response["plan_id"] == "plan-2"


@patch("app.api.WorkflowManager")
def test_get_workflow_status(mock_workflow_manager):
    mock_workflow_manager.return_value.load.return_value = {
        "status": "approval_waiting", "task": "mock_task"
    }
    response = get_workflow_status()
    assert response["status"] == "approval_waiting"
    assert response["task"] == "mock_task"


@pytest.mark.parametrize("action", [rework_workflow, publish_workflow])
def test_unsafe_legacy_workflow_actions_are_deterministically_deprecated(action):
    response = action(PublishRequest(project="project"))
    assert response.status_code == 409
    assert b'deprecated_unsafe_contract' in response.body
