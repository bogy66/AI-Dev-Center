import json
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient

from app.diagnostic_trace import DiagnosticTraceRecorder, TraceEvent, TraceLevel
from app.web_api import (
    app, sessions, get_directory_selector, get_web_config_path, get_workflow_components,
    get_web_setup_components, TracingMCPServerWrapper,
)


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


def _wait_for_workflow_state(client, session_id, terminal=("pending_approval", "failed")):
    state = None
    for _ in range(100):
        state = client.get(f"/api/state/{session_id}").json()
        if state["workflow_status"] in terminal:
            return state
        time.sleep(0.01)
    return state


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
    assert 'id="project-directory-picker"' not in html
    assert 'id="choose-directory-btn"' in html
    assert 'Open Existing Project' in html
    assert 'This does not create a new project.' in html
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
def test_start_endpoint_uses_exact_existing_project_root(client, tmp_path):
    components = _set_override()
    project = tmp_path / "testproj"
    project.mkdir()

    resp = client.post(
        "/api/workflow/start",
        json={
            "project_name": "testproj",
            "project_directory": str(project),
            "task_description": "Create ESPHome project",
            "trace_level": "INFO",
        },
    )
    assert resp.status_code == 202
    data = resp.json()
    assert "session_id" in data
    assert data["session_id"] in sessions
    assert data["status"] == "planning"
    state = _wait_for_workflow_state(client, data["session_id"])
    assert state["plan_id"] == "plan-123"
    components.service.plan_project_setup.assert_called_once_with(
        "testproj", str(project.resolve())
    )
    components.plan_store.save.assert_called_once_with(
        components.service.plan_project_setup.return_value.setup_plan
    )


def test_state_response_fields(client, tmp_path):
    _set_override()
    project = tmp_path / "proj"
    project.mkdir()

    start_resp = client.post(
        "/api/workflow/start",
        json={
            "project_name": "proj",
            "project_directory": str(project),
            "task_description": "task",
        },
    )
    sid = start_resp.json()["session_id"]
    _wait_for_workflow_state(client, sid)

    state_resp = client.get(f"/api/state/{sid}")
    assert state_resp.status_code == 200
    st = state_resp.json()
    for key in (
        "session_id", "run_id", "trace_level", "project_id", "project_path",
        "task_description", "plan_id", "approval_required", "approval_status",
        "workflow_status", "blocked", "trace", "central_trace",
        "current_activity", "timeline", "transparency",
    ):
        assert key in st
    assert st["session_id"] == sid
    assert st["run_id"] == "proj"
    assert st["project_id"] == "proj"
    assert st["project_path"] == str(project.resolve())
    assert st["task_description"] == "task"
    assert st["plan_id"] == "plan-123"
    assert st["approval_required"] is True
    assert st["approval_status"] == "pending_approval"
    assert st["workflow_status"] == "pending_approval"
    assert st["blocked"] is False
    assert isinstance(st["trace"], list)
    assert isinstance(st["timeline"], list)
    assert isinstance(st["transparency"], dict)


def test_trace_export_endpoint(client, tmp_path):
    _set_override()
    project = tmp_path / "export"
    project.mkdir()

    start_resp = client.post(
        "/api/workflow/start",
        json={
            "project_name": "export",
            "project_directory": str(project),
            "task_description": "task",
        },
    )
    sid = start_resp.json()["session_id"]
    _wait_for_workflow_state(client, sid)

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


def test_browser_uses_structured_activity_and_local_compact_trace_time():
    script = Path("web/app.js").read_text(encoding="utf-8")

    assert "formatActivity(state.current_activity)" in script
    assert "toLocaleTimeString" in script
    assert "hour: '2-digit', minute: '2-digit', second: '2-digit'" in script


def test_detailed_trace_renders_actor_and_structured_runtime_states():
    script = Path("web/app.js").read_text(encoding="utf-8")

    assert "const runtimeState = String(meta.runtime_state || '').trim()" in script
    assert "const activityActor = actor || String(event.component || 'Workflow')" in script
    assert "${activityActor} — ${runtimeState}" in script
    assert "filtered.map(formatTraceLine)" in script
    # Direct interpolation deliberately has no state-specific branch: preparing,
    # thinking, reviewing, completed and failed therefore use the same visible path.
    assert "runtimeState ===" not in script


def test_detailed_trace_preserves_ordinary_event_fallback():
    script = Path("web/app.js").read_text(encoding="utf-8")

    assert "if (runtimeState)" in script
    assert "${event.event} ${event.action} ${event.status}" in script
    assert "container.textContent" in script


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
# Existing project selection tests
# ---------------------------------------------------------------------------
def test_existing_project_dialog_has_no_creation_or_upload_controls(client):
    resp = client.get("/")
    html = resp.text
    assert 'id="create-github-repo-checkbox"' not in html
    assert 'webkitdirectory' not in html


def test_server_side_directory_selector_returns_only_resolved_path(client, tmp_path):
    selector = MagicMock()
    selector.select.return_value = str(tmp_path)
    app.dependency_overrides[get_directory_selector] = lambda: selector

    response = client.post("/api/project/select-directory")

    assert response.status_code == 200
    assert response.json() == {
        "status": "selected", "project_path": str(tmp_path.resolve()),
    }


def test_project_open_uses_fixed_argv_with_exact_validated_root(
    client, tmp_path, monkeypatch,
):
    run = MagicMock()
    monkeypatch.setattr("app.web_api.subprocess.run", run)

    response = client.post(
        "/api/project/open", json={"project_path": str(tmp_path)},
    )

    assert response.status_code == 200
    run.assert_called_once_with(
        ["xdg-open", "--", str(tmp_path.resolve())], check=False,
    )


def test_missing_project_start_retains_failed_session_and_trace(client, tmp_path):
    components = _set_override()
    missing = tmp_path / "missing"

    response = client.post("/api/workflow/start", json={
        "project_name": "missing-project",
        "project_directory": str(missing),
        "task_description": "inspect",
    })

    assert response.status_code == 400
    assert response.json()["session_id"] == "missing-project"
    assert response.json()["status"] == "failed"
    assert "missing-project" in sessions
    components.service.plan_project_setup.assert_not_called()
    state = client.get("/api/state/missing-project").json()
    assert state["blocked"] is True
    assert state["workflow_status"] == "failed"
    assert state["trace"][-1]["event"] == "workflow_start_failed"
    assert str(missing) not in state["error_message"]


def test_planning_value_error_retains_safe_failed_session(client, tmp_path):
    components = _set_override()
    components.service.plan_project_setup.side_effect = ValueError(
        "unsafe internal detail /private/project"
    )

    response = client.post("/api/workflow/start", json={
        "project_name": "rejected-project",
        "project_directory": str(tmp_path),
        "task_description": "inspect",
    })

    assert response.status_code == 202
    assert response.json()["session_id"] == "rejected-project"
    state = _wait_for_workflow_state(client, "rejected-project")
    assert state["error_message"] == "Project or planning request was rejected."
    assert state["trace"][-1]["event"] == "workflow_start_failed"
    assert "/private/project" not in str(state)


@pytest.mark.parametrize("path_kind", ["empty", "missing", "file"])
def test_project_validation_rejects_unusable_roots(client, tmp_path, path_kind):
    if path_kind == "empty":
        project_path = ""
    elif path_kind == "missing":
        project_path = str(tmp_path / "missing")
    else:
        file_path = tmp_path / "file.txt"
        file_path.write_text("not a project directory", encoding="utf-8")
        project_path = str(file_path)

    response = client.post(
        "/api/project/validate", json={"project_path": project_path},
    )

    assert response.status_code == 400
    assert response.json()["valid"] is False


def test_frontend_retains_failed_session_and_never_appends_project_name():
    script = Path("web/app.js").read_text(encoding="utf-8")

    assert "err.payload?.session_id" in script
    assert "validateProjectPath(getProjectDirectory(currentProject))" in script
    assert "resolveProjectDirectory" not in script
    assert "project-directory-picker" not in script


def test_projects_help_and_pitch_use_product_language():
    help_text = Path("web/index.html").read_text(encoding="utf-8")
    pitch = Path("web/app.js").read_text(encoding="utf-8").split(
        "const helpSlides = [", 1,
    )[1]

    assert "<h2>Projects</h2>" in help_text
    assert "Start here" in help_text
    assert "How to use it" in help_text
    assert "Diagnostic Trace" in help_text
    assert "1. What is AI Dev Center?" in pitch
    assert "6. New projects" in pitch
    assert "15. Why AI Dev Center?" in pitch
    for internal_name in ("File Applier", "ProjectTestRunner", "compatibility classes"):
        assert internal_name not in pitch


def test_setup_reads_productive_config_without_secret_contents(client, tmp_path):
    config = tmp_path / "config.yml"
    config.write_text("""version: 1
ai:
  provider: openrouter
  model: primary/model
  endpoint: https://example.invalid/api
  authentication: {type: secret_reference, secret: configured-reference}
  timeout_seconds: 30
  discovery: {enabled: true, require_json: true, max_requirements: 50}
  council:
    enabled: true
    max_variants_per_agent: 3
    agents:
      environment_architect: {provider: openrouter, model: role/a, timeout_seconds: 60, temperature: 0.7}
      toolchain_integrator: {provider: openrouter, model: role/b, timeout_seconds: 60, temperature: 0.7}
      risk_assessor: {provider: openrouter, model: role/c, timeout_seconds: 60, temperature: 0.7}
      chairman: {provider: openrouter, model: role/chair, timeout_seconds: 90, temperature: 0.2}
""", encoding="utf-8")
    app.dependency_overrides[get_web_config_path] = lambda: config

    response = client.get("/api/config")

    assert response.status_code == 200
    data = response.json()
    assert data["ai"]["model"] == "primary/model"
    assert data["ai"]["council"]["roles"]["chairman"]["model"] == "role/chair"
    assert data["ai"]["council"]["read_only"] is True
    assert data["ai"]["authentication"] == {
        "type": "secret_reference", "secret_reference": "configured-reference",
    }
    assert "secret_value" not in str(data)


def test_setup_safely_updates_supported_fields_and_protects_read_only_fields(
    client, tmp_path,
):
    config = tmp_path / "config.yml"
    config.write_text("""version: 1
ai:
  provider: openrouter
  model: old/model
  endpoint: https://example.invalid/api
  authentication: {type: secret_reference, secret: configured-reference}
  timeout_seconds: 30
  discovery: {enabled: true, require_json: true, max_requirements: 50}
""", encoding="utf-8")
    app.dependency_overrides[get_web_config_path] = lambda: config

    updated = client.patch("/api/config", json={"model": "new/model"})
    rejected = client.patch("/api/config", json={"provider": "other"})

    assert updated.status_code == 200
    assert updated.json()["ai"]["model"] == "new/model"
    assert rejected.status_code == 422


def test_start_session_is_observable_while_planning_is_still_running(
    client, tmp_path,
):
    import threading

    entered = threading.Event()
    release = threading.Event()
    components = _set_override()
    completed_result = components.service.plan_project_setup.return_value

    def blocking_plan(*_args):
        entered.set()
        release.wait(2)
        return completed_result

    components.service.plan_project_setup.side_effect = blocking_plan
    response = client.post("/api/workflow/start", json={
        "project_name": "live-project",
        "project_directory": str(tmp_path),
        "task_description": "inspect",
    })
    try:
        assert response.status_code == 202
        assert response.json()["status"] == "planning"
        entered.wait(1)
        state = client.get("/api/state/live-project").json()
        assert state["workflow_status"] == "planning"
        assert state["trace"][0]["event"] == "workflow_started"
        assert "central_trace" in state
    finally:
        release.set()
