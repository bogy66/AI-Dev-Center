"""Web boundary tests for the canonical setup application service."""

from types import SimpleNamespace
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
    store = MagicMock()
    approval = MagicMock()
    approval.approve.return_value = SimpleNamespace(id="plan-1", status="approved")
    workflow = MagicMock()
    workflow.execute_approved.return_value = ("done",)
    return SimpleNamespace(service=service, plan_store=store, approval=approval, development_workflow=workflow)


def _start(client):
    return client.post("/api/workflow/start", json={"project_name": "test-proj", "project_directory": "/tmp/test-proj", "task_description": "Testing"})


def test_web_planning_uses_canonical_service_without_agent_or_execution():
    components = _components()
    app.dependency_overrides[get_web_setup_components] = lambda: components
    client = TestClient(app)

    response = _start(client)

    assert response.status_code == 200
    assert response.json()["status"] == "pending_approval"
    components.service.plan_project_setup.assert_called_once_with("test-proj", "/tmp/test-proj")
    components.plan_store.save.assert_called_once()
    components.approval.approve.assert_not_called()
    components.development_workflow.execute_approved.assert_not_called()


def test_canonical_approval_and_execution_are_separate_http_steps():
    components = _components()
    app.dependency_overrides[get_web_setup_components] = lambda: components
    client = TestClient(app)
    session_id = _start(client).json()["session_id"]
    pending_plan = SimpleNamespace(id="plan-1", status="pending_approval")
    approved_plan = SimpleNamespace(id="plan-1", status="approved")
    components.plan_store.load.side_effect = [pending_plan, approved_plan]

    approval = client.post(f"/api/workflow/{session_id}/approval")

    assert approval.json() == {"plan_id": "plan-1", "status": "approved"}
    components.development_workflow.execute_approved.assert_not_called()

    execution = client.post(f"/api/workflow/{session_id}/execute")

    assert execution.status_code == 200
    components.development_workflow.execute_approved.assert_called_once_with(approved_plan)


@pytest.mark.parametrize("council", [None, SimpleNamespace(enabled=False)])
def test_composition_blocks_invalid_council_before_secrets(monkeypatch, council):
    config = SimpleNamespace(council=council)
    secret_store = MagicMock()
    provider = MagicMock()
    council_factory = MagicMock()
    monkeypatch.setattr(web_api, "load_ai_config", lambda _: config)
    monkeypatch.setattr(web_api, "LocalSecretStore", secret_store)
    monkeypatch.setattr(web_api, "create_llm_provider", provider)
    monkeypatch.setattr(web_api, "EngineeringCouncil", council_factory)

    with pytest.raises(web_api.WorkflowExecutionError):
        web_api.get_web_setup_components()

    secret_store.assert_not_called()
    provider.assert_not_called()
    council_factory.assert_not_called()
