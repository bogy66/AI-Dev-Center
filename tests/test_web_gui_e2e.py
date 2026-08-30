"""Real-web E2E tests that exercise HTTP → AgentSetupWorkflow → AgentLLM → MCP boundary,
without a live external LLM."""

import pytest
from fastapi.testclient import TestClient
from types import SimpleNamespace

from app.web_api import app, get_workflow_components
from app.diagnostic_trace import TraceLevel  # not used but available


# ---------------------------------------------------------------------------
# Fake provider used to drive the AgentLLM with deterministic tool calls
# ---------------------------------------------------------------------------
class FakeLLMProvider:
    """Return scripted tool‑call JSON strings in order."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[str] = []

    def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        if self.responses:
            return self.responses.pop(0)
        return '{"tool_calls": []}'


# ---------------------------------------------------------------------------
# Fake MCP server that returns realistic deterministic results for each tool
# ---------------------------------------------------------------------------
class FakeMCPServer:
    """Implements the MCPSetupTools protocol."""

    def __init__(self, handlers: dict[str, callable] | None = None):
        if handlers is None:
            handlers = {
                "inspect_project": lambda **kwargs: {"status": "ok"},
                "discover_requirements": lambda **kwargs: {"status": "ok", "requirements": []},
                "get_preflight": lambda **kwargs: {"status": "ok", "preflight": {}},
                "create_setup_plan": lambda **kwargs: {"status": "ok", "plan_id": "plan-1"},
                "get_setup_plan": lambda **kwargs: {
                    "status": "pending_approval",
                    "plan_id": "plan-1",
                    "setup_plan": {"steps": []},
                },
                "approve_setup_plan": lambda **kwargs: {"status": "approved"},
                "execute_setup_plan": lambda **kwargs: {"status": "completed", "results": ["done"]},
            }
        self.handlers = handlers
        self.tool_names = list(handlers.keys())
        self.calls: list[tuple[str, dict]] = []
        self.list_tools_called = False

    def list_tools(self):
        self.list_tools_called = True
        return [SimpleNamespace(name=name) for name in self.tool_names]

    def __getattr__(self, name: str):
        if name in self.handlers:
            def callable_tool(**kwargs):
                self.calls.append((name, kwargs))
                return self.handlers[name](**kwargs)
            return callable_tool
        raise AttributeError(name)


# ---------------------------------------------------------------------------
# Helpers for common LLM response sequences
# ---------------------------------------------------------------------------
def _success_llm_sequence() -> list[str]:
    """Sequence that calls all required tools and stops after get_setup_plan."""
    return [
        '{"tool_calls":[{"name":"inspect_project","arguments":{}}]}',
        '{"tool_calls":[{"name":"discover_requirements","arguments":{}}]}',
        '{"tool_calls":[{"name":"get_preflight","arguments":{}}]}',
        '{"tool_calls":[{"name":"create_setup_plan","arguments":{}}]}',
        '{"tool_calls":[{"name":"get_setup_plan","arguments":{}}]}',
        # The agent would likely issue more calls, but stop_condition pauses
        # before the next LLM call.
        '{"tool_calls":[{"name":"execute_setup_plan","arguments":{}}]}',
    ]


def _stops_after_create_llm_sequence() -> list[str]:
    """LLM stops producing tool calls after create_setup_plan."""
    return [
        '{"tool_calls":[{"name":"inspect_project","arguments":{}}]}',
        '{"tool_calls":[{"name":"discover_requirements","arguments":{}}]}',
        '{"tool_calls":[{"name":"get_preflight","arguments":{}}]}',
        '{"tool_calls":[{"name":"create_setup_plan","arguments":{}}]}',
        # explicit stop – empty tool_calls
        '{"tool_calls":[]}',
    ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _clean_override():
    """Ensure the dependency overrides are reset after every test."""
    yield
    app.dependecy_ovverrides.clear()

# Note: sessions clearing not strictly needed but harmless; we don't share between tests.

# ---------------------------------------------------------------------------
# Actual E2E tests
# ---------------------------------------------------------------------------
def test_web_workflow_reaches_pending_approval():
    fake_llm = FakeLLMProvider(_success_llm_sequence())
    fake_mcp = FakeMCPServer()

    app.dependecy_ovverrides[get_workflow_components] = lambda: (fake_llm, fake_mcp)
    client = TestClient(app)

    resp = client.post(
        "/api/workflow/start",
        json={
            "project_name": "test-proj",
            "project_directory": "/tmp/test-proj",
            "task_description": "Testing",
            "trace_level": "INFO",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    session_id = data["session_id"]
    plan_id = data.get("plan_id")

    assert session_id
    assert plan_id is not None

    # Fetch workflow state
    state_resp = client.get(f"/api/state/{session_id}")
    assert state_resp.status_code == 200
    state = state_resp.json()

    assert state["approval_required"] is True
    assert state["workflow_status"] == "pending_approval"
    assert state["approval_status"] == "pending_approval"
    assert state["blocked"] is False
    assert state["plan_id"] == plan_id

    # Trace assertions
    trace = state["trace"]
    plan_created = [e for e in trace if e["event"] == "plan_created"]
    approval_events = [e for e in trace if e["event"] == "approval_required"]
    assert len(plan_created) == 1, "Expected exactly one plan_created trace event"
    assert len(approval_events) == 1, "Expected exactly one approvalequired trace event"

    # No approve/execute call must have been made on the MCP boundary
    called_tools = {c[0] for c in fake_mcp.calls}
    assert "approve_setup_plan" not in called_tools
    assert "execute_setup_plan" not in called_tools

    # LLM completion call count ≤ max turns (5 by default) for a clean run
    assert len(fake_llm.calls) <= 5


def test_web_workflow_blocks_when_pending_approval_is_not_reached():
    """When the LLM stops after create_setup_plan and the explicit get_setup_plan
    does NOT return a pending‑approval status, the web workflow must report
    a blocked/failed state with the expected error message."""
    fake_llm = FakeLLMProvider(_stops_after_create_llm_sequence())

    # Handlers where get_setup_plan returns a non‑pending status.
    def non_pending_get(**kwargs):
        # Simulate a successful but non‑approval response.
        return {"status": "ok", "plan_id": "plan-1"}

    fail_handers = {
        "inspect_project": lambda **kwargs: {"status": "ok"},
        "discover_requirements": lambda **kwargs: {"status": "ok", "requirements": []},
        "get_preflight": lambda **kwargs: {"status": "ok"},
        "create_setup_plan": lambda **kwargs: {"status": "ok", "plan_id": "plan-1"},
        "get_setup_plan": non_pending_get,
        "approve_setup_plan": lambda **kwargs: {"status": "approved"},
        "execute_setup_plan": lambda **kwargs: {"status": "completed"},
    }
    fake_mcp = FakeMCPServer(handlers=fail_handers)

    app.dependecy_ovverrides[get_workflow_components] = lambda: (fake_llm, fake_mcp)
    client = TestClient(app)

    resp = client.post(
        "/api/workflow/start",
        json={
            "project_name": "failing-proj",
            "project_directory": "/tmp/fail",
            "task_description": "Expect failure",
            "trace_level": "INFO",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    session_id = data["session_id"]

    state_resp = client.get(f"/api/state/{session_id}")
    assert state_resp.status_code == 200
    state = state_resp.json()

    assert state["blocked"] is True
    # workflow_status may be "unknown" when error occurs; we just require it to be non‑success.
    assert state["workflow_status"] not in ("completed", "pending_approval")

    error_msg = state.get("error_message")
    assert error_msg is not None
    assert "Agent stopped before reaching pending_approval" in error_msg

    # Approve/execute must not have been called on the MCP boundary.
    called_tools = {c[0] for c in fake_mcp.calls}
    assert "approve_setup_plan" not in called_tools
    assert "execute_setup_plan" not in called_tools
