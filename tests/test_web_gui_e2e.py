"""Web boundary tests for the canonical setup application service."""

from types import SimpleNamespace
import time
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.web_api import app, get_web_setup_components, sessions
import app.web_api as web_api


@pytest.fixture(autouse=True)
def clean_web_state():
    sessions.clear()
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def _components():
    plan = SimpleNamespace(id="plan-1", status="pending_approval")
    service = MagicMock()
    service.plan_project_setup.return_value = SimpleNamespace(setup_plan=plan)
    service.execute_approved_setup_and_development.return_value = SimpleNamespace(
        status="accepted",
        setup_execution_results=("done",),
        final_approval_result=SimpleNamespace(status="pending", ready_for_git=False),
    )
    service.decide_final_approval.return_value = SimpleNamespace(status="approved", ready_for_git=True)
    store = MagicMock()
    approval = MagicMock()
    approval.approve.return_value = SimpleNamespace(id="plan-1", status="approved")
    workflow = MagicMock()
    return SimpleNamespace(service=service, plan_store=store, approval=approval, development_workflow=workflow)


def _start(client, project_path):
    return client.post("/api/workflow/start", json={"project_name": "test-proj", "project_directory": str(project_path), "task_description": "Testing"})


def _wait_for_plan(client, session_id):
    for _ in range(100):
        state = client.get(f"/api/state/{session_id}").json()
        if state["plan_id"]:
            return state
        time.sleep(0.01)
    return state


def test_web_planning_uses_canonical_service_without_agent_or_execution(tmp_path):
    components = _components()
    app.dependency_overrides[get_web_setup_components] = lambda: components
    client = TestClient(app)

    project = tmp_path / "test-proj"
    project.mkdir()
    response = _start(client, project)

    assert response.status_code == 202
    assert response.json()["status"] == "planning"
    _wait_for_plan(client, response.json()["session_id"])
    components.service.plan_project_setup.assert_called_once_with(
        "test-proj", str(project.resolve()),
        entry_interface="web", entry_data={
            "task_description": "Testing",
            "project_id": "test-proj",
        },
    )
    components.plan_store.save.assert_called_once()
    components.approval.approve.assert_not_called()
    components.service.execute_approved_setup_and_development.assert_not_called()


def test_canonical_approval_and_execution_are_separate_http_steps(tmp_path):
    components = _components()
    app.dependency_overrides[get_web_setup_components] = lambda: components
    client = TestClient(app)
    project = tmp_path / "test-proj"
    project.mkdir()
    session_id = _start(client, project).json()["session_id"]
    _wait_for_plan(client, session_id)
    pending_plan = SimpleNamespace(id="plan-1", status="pending_approval")
    approved_plan = SimpleNamespace(id="plan-1", status="approved")
    components.plan_store.load.side_effect = [pending_plan, approved_plan]

    approval = client.post(f"/api/workflow/{session_id}/approval")

    assert approval.json() == {"plan_id": "plan-1", "status": "approved"}
    components.service.execute_approved_setup_and_development.assert_not_called()

    execution = client.post(f"/api/workflow/{session_id}/execute")

    assert execution.status_code == 200
    assert execution.json()["status"] == "pending"
    assert execution.json()["development_status"] == "accepted"
    components.service.execute_approved_setup_and_development.assert_called_once_with(
        approved_plan,
        "test-proj",
        str(project.resolve()),
        "Testing",
        session_id,
    )
    final_approval = client.post(
        f"/api/workflow/{session_id}/final-approval",
        json={"decision": "approved", "approved_by": "Udo"},
    )
    assert final_approval.json() == {"status": "approved", "ready_for_git": True}
    components.service.decide_final_approval.assert_called_once_with(
        session_id, "approved", "Udo", None,
    )


def test_web_composition_delegates_to_shared_canonical_root(monkeypatch):
    components = SimpleNamespace(
        service=object(),
        plan_store=object(),
        approval=object(),
        development_workflow=object(),
    )
    builder = MagicMock(return_value=components)
    monkeypatch.setattr(web_api, "build_canonical_components", builder)

    result = web_api.get_web_setup_components()

    builder.assert_called_once_with()
    assert isinstance(result, web_api.WebSetupComponents)
    assert result.service is components.service
    assert result.plan_store is components.plan_store
    assert result.approval is components.approval
    assert result.development_workflow is components.development_workflow
