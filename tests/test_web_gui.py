import json
import uuid
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from app.web_api import app, sessions, get_workflow_components


@pytest.fixture(autouse=True)
def clear_sessions():
    sessions.clear()
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def _mock_components(llm=None, mcp=None):
    if llm is None:
        llm = MagicMock()
    if mcp is None:
        mcp = MagicMock()
        mcp.list_tools.return_value = []
    return llm, mcp


def _set_override(llm=None, mcp=None):
    llm, mcp = _mock_components(llm, mcp)
    app.dependency_overrides[get_workflow_components] = lambda: (llm, mcp)
    return llm, mcp


def test_get_root_returns_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")


@patch("app.web_api.AgentSetupWorkflow")
def test_start_session_creation(mock_workflow_cls, client):
    mock_llm, mock_mcp = _set_override()
    fake_result = MagicMock()
    fake_result.plan_id = "plan-123"
    fake_result.approval_required = True
    fake_result.approval_status = "pending"
    fake_result.error_message = None
    mock_workflow_cls.return_value.start_setup_workflow.return_value = fake_result

    resp = client.post(
        "/api/workflow/start",
        json={"project_name": "testproj", "project_directory": "/tmp/testproj"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    assert data["plan_id"] == "plan-123"
    assert data["session_id"] in sessions


def test_start_missing_fields(client):
    # Validation should happen before dependencies are resolved.
    resp = client.post("/api/workflow/start", json={})
    assert resp.status_code == 422


@patch("app.web_api.AgentSetupWorkflow")
def test_state_response_contains_required_fields(mock_workflow_cls, client):
    _set_override()
    fake_result = MagicMock()
    fake_result.plan_id = "plan-abc"
    fake_result.approval_required = False
    fake_result.approval_status = "completed"
    fake_result.error_message = None
    mock_workflow_cls.return_value.start_setup_workflow.return_value = fake_result

    start_resp = client.post(
        "/api/workflow/start",
        json={"project_name": "x", "project_directory": "/tmp/x"},
    )
    sid = start_resp.json()["session_id"]

    state_resp = client.get(f"/api/state/{sid}")
    assert state_resp.status_code == 200
    st = state_resp.json()
    for key in ("session_id", "project_id", "project_path", "plan_id",
                "approval_required", "approval_status", "workflow_status",
                "blocked", "trace", "timeline", "transparency"):
        assert key in st


def test_state_unknown_session(client):
    resp = client.get("/api/state/nonexistent")
    assert resp.status_code == 404


@patch("app.web_api.AgentSetupWorkflow")
def test_trace_events_include_mcp_calls(mock_workflow_cls, client):
    _set_override()
    fake_result = MagicMock()
    fake_result.plan_id = "plan-events"
    fake_result.approval_required = True
    fake_result.approval_status = "pending"
    fake_result.error_message = None
    mock_workflow_cls.return_value.start_setup_workflow.return_value = fake_result

    start_resp = client.post(
        "/api/workflow/start",
        json={"project_name": "ev", "project_directory": "/a/b"},
    )
    sid = start_resp.json()["session_id"]

    session = sessions[sid]
    from datetime import datetime
    from app.web_api import TraceEvent
    session.trace_events.append(
        TraceEvent(
            timestamp=datetime.now(),
            component="MCP",
            action="inspect_project",
            status="success",
            duration=0.5,
            args={"project_path": "/a/b"},
        )
    )

    state_resp = client.get(f"/api/state/{sid}")
    st = state_resp.json()
    assert len(st["trace"]) >= 1
    assert "args" in st["trace"][0]


@patch("app.web_api.AgentSetupWorkflow")
def test_approve_reject_workflow(mock_workflow_cls, client):
    _set_override()
    mock_workflow_inst = mock_workflow_cls.return_value
    fake_start_result = MagicMock()
    fake_start_result.plan_id = "plan-approve"
    fake_start_result.approval_required = True
    fake_start_result.approval_status = "pending"
    fake_start_result.error_message = None
    mock_workflow_inst.start_setup_workflow.return_value = fake_start_result

    # start
    start_resp = client.post(
        "/api/workflow/start",
        json={"project_name": "p", "project_directory": "/p"},
    )
    sid = start_resp.json()["session_id"]

    # reject
    reject_resp = client.post(f"/api/workflow/{sid}/reject")
    assert reject_resp.status_code == 200

    st = client.get(f"/api/state/{sid}").json()
    assert st["blocked"] is True
    assert st["workflow_status"] == "blocked"

    # start another session
    start2 = client.post(
        "/api/workflow/start",
        json={"project_name": "p", "project_directory": "/p"},
    )
    sid2 = start2.json()["session_id"]
    fake_approve_result = MagicMock()
    fake_approve_result.workflow_status = "completed"
    mock_workflow_inst.approve_and_execute.return_value = fake_approve_result
    approve_resp = client.post(f"/api/workflow/{sid2}/approve")
    assert approve_resp.status_code == 200
    st2 = client.get(f"/api/state/{sid2}").json()
    assert st2["workflow_status"] == "completed"


def test_no_auto_workflow_on_page_load(client):
    # GET / should not trigger a workflow start
    resp = client.get("/")
    assert "No project loaded" in resp.text


@patch("app.web_api.AgentSetupWorkflow")
def test_project_name_path_separation(mock_workflow_cls, client):
    _set_override()
    fake_result = MagicMock()
    fake_result.plan_id = "plan-sep"
    fake_result.approval_required = False
    fake_result.approval_status = "completed"
    fake_result.error_message = None
    mock_workflow_cls.return_value.start_setup_workflow.return_value = fake_result

    resp = client.post(
        "/api/workflow/start",
        json={"project_name": "test-name", "project_directory": "/test/dir"},
    )
    sid = resp.json()["session_id"]
    st = client.get(f"/api/state/{sid}").json()
    assert st["project_id"] == "test-name"
    assert st["project_path"] == "/test/dir"


def test_no_auto_dialog_in_html(client):
    resp = client.get("/")
    html = resp.text
    assert "modal" not in html.lower()
    assert "dialog" not in html.lower()
    assert 'id="project-name-input"' in html
    assert 'id="project-dir-input"' in html
    assert 'Workflow starten' in html


@patch("app.web_api.AgentSetupWorkflow")
@patch("app.web_api.create_llm_provider")
@patch("app.web_api.load_ai_config")
@patch("app.web_api.LocalSecretStore")
@patch("app.web_api.build_mcp_server")
def test_start_does_not_construct_real_mcp_or_provider(
    mock_build_mcp,
    mock_secret_cls,
    mock_load_config,
    mock_create_provider,
    mock_workflow_cls,
    client,
):
    """When get_workflow_components is overridden, the real provider factory
    must never be invoked, so no real OpenRouterLLMProvider is created.

    This test patches the actual boundary used by web_api.py rather than
    OpenRouterLLMProvider directly.
    """
    # Override the dependency so the endpoint receives fully mocked components.
    mock_llm, mock_mcp = _set_override()

    # But the dependency-override also short-circuits get_workflow_components,
    # so we need to ensure the real provider factory is never called.
    # (If the override were somehow bypassed, the mocks below would trigger
    #  assertion failures.)
    # We don't expect the real provider to be constructed, but we still
    # guard against any accidental call.

    # Configure the real provider path so that any accidental call still
    # leads to a controlled outcome (an AssertionError) rather than a real
    # API-key lookup.
    mock_load_config.side_effect = AssertionError(
        "load_ai_config should not be called when dependency is overridden"
    )
    mock_secret_cls.side_effect = AssertionError(
        "LocalSecretStore should not be called when dependency is overridden"
    )
    mock_create_provider.side_effect = AssertionError(
        "create_llm_provider should not be called when dependency is overridden"
    )
    mock_build_mcp.side_effect = AssertionError(
        "build_mcp_server should not be called when dependency is overridden"
    )

    fake_result = MagicMock()
    fake_result.plan_id = "plan-no-real"
    fake_result.approval_required = False
    fake_result.approval_status = "completed"
    fake_result.error_message = None
    mock_workflow_cls.return_value.start_setup_workflow.return_value = fake_result

    resp = client.post(
        "/api/workflow/start",
        json={"project_name": "safe", "project_directory": "/safe"},
    )
    assert resp.status_code == 200

    # Sanity-check that these mocks were never touched.
    mock_load_config.assert_not_called()
    mock_secret_cls.assert_not_called()
    mock_create_provider.assert_not_called()
    mock_build_mcp.assert_not_called()


@patch("app.web_api.create_llm_provider")
@patch("app.web_api.load_ai_config")
@patch("app.web_api.LocalSecretStore")
@patch("app.web_api.build_mcp_server")
def test_get_workflow_components_uses_provider_factory(
    mock_build_mcp, mock_secret_cls, mock_load_config, mock_create_provider
):
    mock_config = MagicMock()
    mock_load_config.return_value = mock_config
    mock_secret = MagicMock()
    mock_secret_cls.return_value = mock_secret
    mock_llm = MagicMock()
    mock_create_provider.return_value = mock_llm
    mock_mcp = MagicMock()
    mock_build_mcp.return_value = mock_mcp

    llm, mcp = get_workflow_components()

    mock_load_config.assert_called_once_with("config/ai-dev-center.yml")
    mock_secret_cls.assert_called_once_with()
    mock_create_provider.assert_called_once_with(mock_config, mock_secret)
    mock_build_mcp.assert_called_once_with(mock_config, mock_llm)
    assert llm is mock_llm
    assert mcp is mock_mcp
