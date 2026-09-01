import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient

from app.diagnostic_trace import DiagnosticTraceRecorder, TraceEvent, TraceLevel
from app.web_api import app, sessions, get_workflow_components, get_web_setup_components, TracingMCPServerWrapper


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
    plan = MagicMock(id="plan-123", status="pending_approval")
    result = MagicMock(setup_plan=plan)
    components = MagicMock()
    components.service.plan_project_setup.return_value = result
    components.plan_store = MagicMock()
    components.approval = MagicMock()
    components.development_workflow = MagicMock()
    app.dependency_overrides[get_web_setup_components] = lambda: components
    return components


# ---------------------------------------------------------------------------
# HTML structure tests
# ---------------------------------------------------------------------------
def test_page_loads_without_modal(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "new-project-modal" in resp.text
    assert "modal hidden" in resp.text  # hidden class present initially


def test_two_column_layout_structure(client):
    resp = client.get("/")
    html = resp.text
    assert 'id="recents-panel"' in html
    assert 'id="main-panel"' in html
    # no permanent 3-column layout
    assert 'id="approval-column"' not in html


def test_new_project_button_exists(client):
    resp = client.get("/")
    assert 'id="new-project-btn"' in resp.text


def test_modal_contains_project_fields(client):
    resp = client.get("/")
    html = resp.text
    assert 'id="project-name-input"' in html
    assert 'id="project-dir-input"' in html
    assert 'id="new-project-trace-level"' in html
    assert 'id="project-directory-picker"' in html
    assert 'id="choose-directory-btn"' in html
    # no task textarea in modal
    assert 'id="task-description-input"' not in html


def test_chat_input_is_textarea(client):
    resp = client.get("/")
    html = resp.text
    assert '<textarea id="chat-input"' in html


def test_send_button_exists(client):
    resp = client.get("/")
    assert 'id="send-btn"' in resp.text


def test_trace_section_and_controls_exist(client):
    resp = client.get("/")
    html = resp.text
    assert 'id="trace-panel"' in html
    assert 'id="trace-list-container"' in html
    assert 'id="trace-filter"' in html
    assert 'id="trace-level-select"' in html
    assert 'id="clear-trace-btn"' in html
    assert 'id="copy-all-btn"' in html
    assert 'id="export-trace-btn"' in html


def test_trace_drag_handle_exists(client):
    resp = client.get("/")
    assert 'id="trace-drag-handle"' in resp.text


def test_live_status_area_exists(client):
    resp = client.get("/")
    assert 'id="live-status"' in resp.text


def test_no_automatic_workflow_on_page_load(client):
    # GET / should not trigger backend workflow start
    resp = client.get("/")
    assert resp.status_code == 200
    # no session should be created
    assert len(sessions) == 0


def test_empty_chat_state_present(client):
    resp = client.get("/")
    html = resp.text
    assert 'id="empty-chat-state"' in html
    assert 'Start a conversation...' in html


def test_session_info_elements_exist_and_visible_initially(client):
    resp = client.get("/")
    html = resp.text
    assert 'id="session-info"' in html
    assert 'id="session-id-display"' in html
    assert 'id="copy-session-btn"' in html
    # Session: — is part of the visible page (not hidden)
    assert 'Session:' in html
    assert '>—<' in html.replace(' ', '')
    # Copy button must be disabled initially
    assert 'disabled' in html.split('id="copy-session-btn"')[1].split('>')[0]


def test_trace_is_below_chat_and_composer_is_above_trace(client):
    resp = client.get("/")
    html = resp.text
    assert 'id="chat-panel"' in html
    assert 'id="input-panel"' in html
    assert 'id="trace-panel"' in html
    # The composer (input-panel) is inside chat-panel and comes before trace-panel
    idx_input = html.index('id="input-panel"')
    idx_trace = html.index('id="trace-panel"')
    assert idx_input < idx_trace
    idx_chat = html.index('id="chat-panel"')
    assert idx_chat < idx_trace


def test_full_layout_does_not_introduce_third_column(client):
    resp = client.get("/")
    html = resp.text
    # there should be exactly two top-level columns: recents-panel and main-panel
    assert 'id="recents-panel"' in html
    assert 'id="main-panel"' in html
    assert 'id="approval-column"' not in html
    assert 'id="plan-sidebar"' not in html


# ---------------------------------------------------------------------------
# API compatibility tests (still valid)
# ---------------------------------------------------------------------------
def test_start_endpoint_with_new_project(client):
    components = _set_override()

    resp = client.post(
        "/api/workflow/start",
        json={
            "project_name": "testproj",
            "project_directory": "/tmp/testproj",
            "task_description": "Create ESPHome project",
            "trace_level": "INFO",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    assert data["session_id"] in sessions
    assert data["plan_id"] == "plan-123"
    assert data["status"] == "pending_approval"
    components.service.plan_project_setup.assert_called_once_with(
        "testproj", "/tmp/testproj"
    )
    components.plan_store.save.assert_called_once_with(
        components.service.plan_project_setup.return_value.setup_plan
    )


def test_state_response_fields(client):
    _set_override()

    start_resp = client.post(
        "/api/workflow/start",
        json={
            "project_name": "proj",
            "project_directory": "/tmp/proj",
            "task_description": "task",
        },
    )
    sid = start_resp.json()["session_id"]

    state_resp = client.get(f"/api/state/{sid}")
    assert state_resp.status_code == 200
    st = state_resp.json()
    for key in (
        "session_id", "run_id", "trace_level", "project_id", "project_path",
        "task_description", "plan_id", "approval_required", "approval_status",
        "workflow_status", "blocked", "trace", "timeline", "transparency",
    ):
        assert key in st
    assert st["session_id"] == sid
    assert st["run_id"] == "proj"
    assert st["project_id"] == "proj"
    assert st["project_path"] == "/tmp/proj"
    assert st["task_description"] == "task"
    assert st["plan_id"] == "plan-123"
    assert st["approval_required"] is True
    assert st["approval_status"] == "pending_approval"
    assert st["workflow_status"] == "pending_approval"
    assert st["blocked"] is False
    assert isinstance(st["trace"], list)
    assert isinstance(st["timeline"], list)
    assert isinstance(st["transparency"], dict)


def test_trace_export_endpoint(client):
    _set_override()

    start_resp = client.post(
        "/api/workflow/start",
        json={
            "project_name": "export",
            "project_directory": "/tmp/export",
            "task_description": "task",
        },
    )
    sid = start_resp.json()["session_id"]

    export_resp = client.get(f"/api/workflow/{sid}/export")
    assert export_resp.status_code == 200
    data = export_resp.json()
    assert "events" in data
    assert "run_id" in data
    assert data["run_id"] == sid
    assert isinstance(data["events"], list)
    assert [event["event"] for event in data["events"]] == [
        "workflow_started", "plan_created", "approval_required",
    ]


def test_get_workflow_components_uses_provider_factory():
    # This verifies that the dependency injection path remains the same.
    # The actual factory is mocked in other tests; here we just ensure the
    # function is imported and callable.
    assert callable(get_workflow_components)


def test_browser_uses_separate_canonical_approval_and_execution_routes():
    script = Path("web/app.js").read_text(encoding="utf-8")

    assert "handleApproval('approval')" in script
    assert "action === 'approval' ? 'approval' : 'reject'" in script
    assert "${currentSessionId}/execute" in script
    assert "Approval granted. Executing" not in script


def test_readme_documents_port_8010():
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "--port 8010" in readme
    assert "127.0.0.1:8010" in readme


# ---------------------------------------------------------------------------
# Additional assertion: no old task form elements in new page
# ---------------------------------------------------------------------------
def test_no_old_task_description_textarea(client):
    resp = client.get("/")
    assert 'id="task-description-input"' not in resp.text
    assert 'id="project-start"' not in resp.text
    assert 'id="timeline-section"' not in resp.text
    assert 'id="mcp-activity"' not in resp.text


# ---------------------------------------------------------------------------
# New Project GitHub checkbox tests
# ---------------------------------------------------------------------------
def test_new_project_dialog_contains_github_checkbox(client):
    resp = client.get("/")
    html = resp.text
    assert 'id="create-github-repo-checkbox"' in html


def test_github_checkbox_defaults_to_unchecked(client):
    resp = client.get("/")
    html = resp.text
    # The checkbox should not have the checked attribute in the initial HTML.
    # We look for the checkbox element and ensure it does not contain 'checked'.
    checkbox_start = html.index('id="create-github-repo-checkbox"')
    # Grab a reasonable slice around the element.
    snippet = html[checkbox_start:checkbox_start + 200]
    assert 'checked' not in snippet
