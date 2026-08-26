import json
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from app.diagnostic_trace import DiagnosticTraceRecorder, TraceEvent, TraceLevel
from app.web_api import app, sessions, get_workflow_components, TracingMCPServerWrapper


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


def _make_workflow_result(**kwargs):
    result = MagicMock()
    result.plan_id = kwargs.get("plan_id", "plan-123")
    result.approval_required = kwargs.get("approval_required", False)
    result.approval_status = kwargs.get("approval_status", "completed")
    result.error_message = kwargs.get("error_message", None)
    return result


def test_get_root_returns_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")


@patch("app.web_api.AgentSetupWorkflow")
def test_start_session_creation(mock_workflow_cls, client):
    mock_llm, mock_mcp = _set_override()
    mock_workflow_cls.return_value.start_setup_workflow.return_value = _make_workflow_result(
        approval_required=True
    )

    resp = client.post(
        "/api/workflow/start",
        json={
            "project_name": "testproj",
            "project_directory": "/tmp/testproj",
            "task_description": "test task",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    assert data["plan_id"] == "plan-123"
    assert data["session_id"] in sessions


def test_start_missing_fields(client):
    resp = client.post("/api/workflow/start", json={})
    assert resp.status_code == 422


@patch("app.web_api.AgentSetupWorkflow")
def test_state_response_contains_required_fields(mock_workflow_cls, client):
    _set_override()
    mock_workflow_cls.return_value.start_setup_workflow.return_value = _make_workflow_result()

    start_resp = client.post(
        "/api/workflow/start",
        json={
            "project_name": "x",
            "project_directory": "/tmp/x",
            "task_description": "test task",
        },
    )
    sid = start_resp.json()["session_id"]

    state_resp = client.get(f"/api/state/{sid}")
    assert state_resp.status_code == 200
    st = state_resp.json()
    for key in (
        "session_id",
        "run_id",
        "trace_level",
        "project_id",
        "project_path",
        "task_description",
        "plan_id",
        "approval_required",
        "approval_status",
        "workflow_status",
        "blocked",
        "trace",
        "timeline",
        "transparency",
    ):
        assert key in st


def test_state_unknown_session(client):
    resp = client.get("/api/state/nonexistent")
    assert resp.status_code == 404


@patch("app.web_api.AgentSetupWorkflow")
def test_trace_events_include_mcp_calls(mock_workflow_cls, client):
    _set_override()
    mock_workflow_cls.return_value.start_setup_workflow.return_value = _make_workflow_result(
        approval_required=True
    )

    start_resp = client.post(
        "/api/workflow/start",
        json={
            "project_name": "ev",
            "project_directory": "/a/b",
            "task_description": "test task",
        },
    )
    sid = start_resp.json()["session_id"]

    session = sessions[sid]
    session.trace_events.append(
        TraceEvent(
            timestamp=datetime.now(),
            run_id=session.run_id,
            level=TraceLevel.INFO,
            component="MCP",
            event="tool_completed",
            action="inspect_project",
            status="success",
            duration_ms=500.0,
            arguments={"project_path": "/a/b"},
        )
    )

    state_resp = client.get(f"/api/state/{sid}")
    st = state_resp.json()
    assert len(st["trace"]) >= 1
    assert "arguments" in st["trace"][0]


@patch("app.web_api.AgentSetupWorkflow")
def test_approve_reject_workflow(mock_workflow_cls, client):
    _set_override()
    mock_workflow_inst = mock_workflow_cls.return_value
    mock_workflow_inst.start_setup_workflow.return_value = _make_workflow_result(
        approval_required=True
    )

    start_resp = client.post(
        "/api/workflow/start",
        json={
            "project_name": "p",
            "project_directory": "/p",
            "task_description": "test task",
        },
    )
    sid = start_resp.json()["session_id"]

    reject_resp = client.post(f"/api/workflow/{sid}/reject")
    assert reject_resp.status_code == 200

    st = client.get(f"/api/state/{sid}").json()
    assert st["blocked"] is True
    assert st["workflow_status"] == "blocked"

    start2 = client.post(
        "/api/workflow/start",
        json={
            "project_name": "p",
            "project_directory": "/p",
            "task_description": "test task",
        },
    )
    sid2 = start2.json()["session_id"]

    approve_result = MagicMock()
    approve_result.workflow_status = "completed"
    mock_workflow_inst.approve_and_execute.return_value = approve_result

    approve_resp = client.post(f"/api/workflow/{sid2}/approve")
    assert approve_resp.status_code == 200

    st2 = client.get(f"/api/state/{sid2}").json()
    assert st2["workflow_status"] == "completed"


def test_no_auto_workflow_on_page_load(client):
    # GET / should not trigger a workflow start
    resp = client.get("/")
    assert "Kein Projekt geladen" in resp.text


@patch("app.web_api.AgentSetupWorkflow")
def test_project_name_path_separation(mock_workflow_cls, client):
    _set_override()
    mock_workflow_cls.return_value.start_setup_workflow.return_value = _make_workflow_result()

    resp = client.post(
        "/api/workflow/start",
        json={
            "project_name": "test-name",
            "project_directory": "/test/dir",
            "task_description": "test task",
        },
    )
    sid = resp.json()["session_id"]
    st = client.get(f"/api/state/{sid}").json()
    assert st["project_id"] == "test-name"
    assert st["project_path"] == "/test/dir"
    assert st["task_description"] == "test task"


def test_no_auto_dialog_in_html(client):
    resp = client.get("/")
    html = resp.text
    assert "modal" not in html.lower()
    assert "dialog" not in html.lower()
    assert 'id="project-name-input"' in html
    assert 'id="project-dir-input"' in html
    assert 'id="task-description-input"' in html
    assert 'Aufgabe' in html
    assert 'Trace Level' in html
    assert 'id="trace-level-select"' in html
    assert 'Exportieren' in html
    assert 'Workflow starten' in html


@patch("app.web_api.AgentSetupWorkflow")
def test_task_description_is_submitted_and_persisted(mock_workflow_cls, client):
    _set_override()
    mock_workflow_cls.return_value.start_setup_workflow.return_value = _make_workflow_result()

    task = "Implement user authentication for the new portal."
    resp = client.post(
        "/api/workflow/start",
        json={
            "project_name": "taskproj",
            "project_directory": "/tmp/taskproj",
            "task_description": task,
        },
    )
    assert resp.status_code == 200
    sid = resp.json()["session_id"]
    st = client.get(f"/api/state/{sid}").json()
    assert st["task_description"] == task


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
    _set_override()

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

    mock_workflow_cls.return_value.start_setup_workflow.return_value = _make_workflow_result()

    resp = client.post(
        "/api/workflow/start",
        json={
            "project_name": "safe",
            "project_directory": "/safe",
            "task_description": "test task",
        },
    )
    assert resp.status_code == 200

    mock_load_config.assert_not_called()
    mock_secret_cls.assert_not_called()
    mock_create_provider.assert_not_called()
    mock_build_mcp.assert_not_called()


# ---------------------------------------------------------------------------
#  Diagnostic trace tests
# ---------------------------------------------------------------------------

@patch("app.web_api.AgentSetupWorkflow")
def test_default_trace_level_is_info(mock_workflow_cls, client):
    _set_override()
    mock_workflow_cls.return_value.start_setup_workflow.return_value = _make_workflow_result()

    resp = client.post(
        "/api/workflow/start",
        json={
            "project_name": "default-level",
            "project_directory": "/tmp/default-level",
            "task_description": "test task",
        },
    )
    sid = resp.json()["session_id"]
    st = client.get(f"/api/state/{sid}").json()

    assert st["trace_level"] == "INFO"
    assert st["run_id"]
    assert any(e["event"] == "workflow_started" for e in st["trace"])


@pytest.mark.parametrize(
    "selected, level_to_record, should_capture",
    [
        ("DEBUG", "DEBUG", True),
        ("INFO", "DEBUG", False),
        ("INFO", "INFO", True),
        ("WARNING", "INFO", False),
        ("WARNING", "WARNING", True),
        ("ERROR", "WARNING", False),
        ("ERROR", "ERROR", True),
    ],
)
@patch("app.web_api.AgentSetupWorkflow")
def test_trace_level_capture_semantics(
    mock_workflow_cls, client, selected, level_to_record, should_capture
):
    _set_override()
    mock_workflow_cls.return_value.start_setup_workflow.return_value = _make_workflow_result()

    resp = client.post(
        "/api/workflow/start",
        json={
            "project_name": "capture-semantics",
            "project_directory": "/tmp/capture-semantics",
            "task_description": "test task",
            "trace_level": selected,
        },
    )
    sid = resp.json()["session_id"]
    session = sessions[sid]

    event_level = TraceLevel[level_to_record]
    session.recorder.record(
        level=event_level,
        component="Test",
        event="level_test_event",
        action="test",
        status="ok",
    )

    st = client.get(f"/api/state/{sid}").json()
    captured = any(e["event"] == "level_test_event" for e in st["trace"])
    assert captured == should_capture


def test_run_id_is_generated_and_consistent():
    rec = DiagnosticTraceRecorder(run_id="run-123", trace_level=TraceLevel.INFO)
    rec.record(
        level=TraceLevel.INFO,
        component="Test",
        event="ev1",
        action="test",
        status="ok",
    )
    rec.record(
        level=TraceLevel.WARNING,
        component="Test",
        event="ev2",
        action="test",
        status="ok",
    )
    assert all(e.run_id == "run-123" for e in rec.events)


def test_secret_redaction_in_recorder():
    rec = DiagnosticTraceRecorder(run_id="redact-run", trace_level=TraceLevel.INFO)
    rec.record(
        level=TraceLevel.INFO,
        component="Test",
        event="redact",
        action="test",
        status="ok",
        arguments={
            "api_key": "super-secret",
            "nested": {"secret": "hidden", "normal": "visible"},
            "password": "p@ssw0rd",
        },
        result_summary="token=some-token password=abc",
    )

    ev = rec.events[0]
    assert ev.arguments["api_key"] == "[REDACTED]"
    assert ev.arguments["nested"]["secret"] == "[REDACTED]"
    assert ev.arguments["nested"]["normal"] == "visible"
    assert ev.arguments["password"] == "[REDACTED]"
    assert "token=[REDACTED]" in ev.result_summary


def test_mcp_wrapper_records_tool_events_and_failures():
    class FakeMCP:
        def list_tools(self):
            return [SimpleNamespace(name="do_thing")]

        def do_thing(self, x):
            return "done"

    rec = DiagnosticTraceRecorder(run_id="tool-run", trace_level=TraceLevel.INFO)
    wrapper = TracingMCPServerWrapper(FakeMCP(), rec)

    wrapper.do_thing(x=1)

    assert any(e.event == "tool_started" and e.action == "do_thing" for e in rec.events)
    assert any(e.event == "tool_completed" and e.status == "success" for e in rec.events)

    class FailingMCP:
        def list_tools(self):
            return [SimpleNamespace(name="fail_thing")]

        def fail_thing(self):
            raise RuntimeError("boom")

    rec2 = DiagnosticTraceRecorder(run_id="tool-fail-run", trace_level=TraceLevel.ERROR)
    wrapper2 = TracingMCPServerWrapper(FailingMCP(), rec2)

    with pytest.raises(RuntimeError):
        wrapper2.fail_thing()

    failed_events = [e for e in rec2.events if e.event == "tool_failed"]
    assert any(e.status == "failed" for e in failed_events)
    assert any(e.level == TraceLevel.ERROR for e in failed_events)


def test_wrapper_captures_mcp_call_when_list_tools_returns_empty():
    """Fallback capture must work even when list_tools is empty/missing.

    This mirrors the real scenario where the MCPServer may not expose its
    tool names in advance for some reason.
    """

    class SilentMCP:
        def list_tools(self):
            return []

        def inspect_project(self, project_path):
            return {"status": "ok"}

    rec = DiagnosticTraceRecorder(run_id="fallback-run", trace_level=TraceLevel.INFO)
    wrapper = TracingMCPServerWrapper(SilentMCP(), rec)

    wrapper.inspect_project(project_path="/tmp/project")

    assert any(e.event == "tool_started" and e.action == "inspect_project" for e in rec.events)
    assert any(e.event == "tool_completed" and e.action == "inspect_project" for e in rec.events)


@patch("app.web_api.AgentSetupWorkflow")
def test_export_contains_run_id_and_trace_level(mock_workflow_cls, client):
    _set_override()
    mock_workflow_cls.return_value.start_setup_workflow.return_value = _make_workflow_result()

    resp = client.post(
        "/api/workflow/start",
        json={
            "project_name": "export-project",
            "project_directory": "/tmp/export-project",
            "task_description": "test task",
            "trace_level": "DEBUG",
        },
    )
    sid = resp.json()["session_id"]
    st = client.get(f"/api/state/{sid}").json()

    export_resp = client.get(f"/api/workflow/{sid}/export")
    assert export_resp.status_code == 200
    export_data = export_resp.json()

    assert export_data["run_id"] == st["run_id"]
    assert export_data["trace_level"] == st["trace_level"]
    assert "events" in export_data
    assert isinstance(export_data["events"], list)


@patch("app.web_api.AgentSetupWorkflow")
def test_no_llm_reasoning_events_are_captured(mock_workflow_cls, client):
    _set_override()
    mock_workflow_cls.return_value.start_setup_workflow.return_value = _make_workflow_result()

    resp = client.post(
        "/api/workflow/start",
        json={
            "project_name": "no-llm-reasoning",
            "project_directory": "/tmp/no-llm-reasoning",
            "task_description": "test task",
        },
    )
    sid = resp.json()["session_id"]
    st = client.get(f"/api/state/{sid}").json()

    components = {e["component"] for e in st["trace"]}
    assert "LLM" not in components
    assert not any(e["event"] in {"chain_of_thought", "reasoning"} for e in st["trace"])


@patch("app.web_api.AgentSetupWorkflow")
@patch("app.web_api.create_llm_provider")
@patch("app.web_api.load_ai_config")
@patch("app.web_api.LocalSecretStore")
@patch("app.web_api.build_mcp_server")
def test_get_workflow_components_uses_provider_factory(
    mock_build_mcp,
    mock_secret_cls,
    mock_load_config,
    mock_create_provider,
    _mock_agent_setup_workflow,
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
