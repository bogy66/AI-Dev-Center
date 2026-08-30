from __future__ import annotations
from types import SimpleNamespace

import pytest

from app.llm_agent import AgentLLM
from app.agent_setup_workflow import AgentSetupWorkflow, AgentSetupWorkflowResult


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        if not self.responses:
            return '{"tool_calls": []}'
        return self.responses.pop(0)


class FakeMCPServer:
    """Fake MCP server with hard-coded tool outputs for testing."""
    def __init__(self, handlers=None):
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
        self.calls = []
        self.list_tools_called = False

    def list_tools(self):
        self.list_tools_called = True
        return [SimpleNamespace(name=name) for name in self.tool_names]

    def __getattr__(self, name):
        if name in self.handlers:
            def callable_tool(**kwargs):
                self.calls.append((name, kwargs))
                return self.handlers[name](**kwargs)
            return callable_tool
        raise AttributeError(name)


def _llm_plan_sequence():
    """Return scripted LLM responses that call the required tools and stop after get_setup_plan."""
    return [
        '{"tool_calls":[{"name":"inspect_project","arguments":{}}]}',
        '{"tool_calls":[{"name":"discover_requirements","arguments":{}}]}',
        '{"tool_calls":[{"name":"get_preflight","arguments":{}}]}',
        '{"tool_calls":[{"name":"create_setup_plan","arguments":{}}]}',
        '{"tool_calls":[{"name":"get_setup_plan","arguments":{}}]}',
        # The agent would likely issue more calls in a real LLM, but our
        # stop_condition should halt after the pending_approval tool result.
        '{"tool_calls":[{"name":"execute_setup_plan","arguments":{}}]}',
    ]


def test_start_reaches_pending_approval_and_stops_llm():
    llm = FakeLLM(_llm_plan_sequence())
    server = FakeMCPServer()
    workflow = AgentSetupWorkflow(llm, server)

    result = workflow.start_setup_workflow("proj1", "/tmp/proj")

    assert result.approval_required is True
    assert result.workflow_status == "pending_approval"
    assert result.plan_id == "plan-1"
    assert result.error_message is None
    # The agent must stop before attempting execute_setup_plan.
    assert "execute_setup_plan" not in [c[0] for c in server.calls]
    # The LLM should not be called again after pending approval.
    assert len(llm.calls) <= 5
    assert server.list_tools_called is True


def test_approve_and_execute_success():
    llm = FakeLLM([])  # not used for continuation
    server = FakeMCPServer()
    workflow = AgentSetupWorkflow(llm, server)

    result = workflow.approve_and_execute("proj1", "plan-1")

    assert result.workflow_status == "completed"
    assert result.plan_id == "plan-1"
    assert result.approval_required is False
    assert result.approval_status == "approved"
    assert result.execution_results
    assert server.calls[-1][0] == "execute_setup_plan"


def test_approval_rejected():
    def reject(**kwargs):
        return {"status": "rejected"}

    def not_found_plan(**kwargs):
        return {"status": "pending_approval", "plan_id": "plan-1"}  # still exists for lookup

    server = FakeMCPServer(handlers={
        "get_setup_plan": not_found_plan,
        "approve_setup_plan": reject,
        "execute_setup_plan": lambda **kwargs: {"status": "would_execute"},
    })
    workflow = AgentSetupWorkflow(FakeLLM([]), server)

    result = workflow.approve_and_execute("proj1", "plan-1")

    assert result.workflow_status == "failed"
    assert result.approval_status == "rejected"
    assert "Approval was rejected" in result.error_message
    # Execution must not happen after failed approval
    assert all(c[0] != "execute_setup_plan" for c in server.calls)


def test_plan_not_found_on_continuation():
    def missing_plan(**kwargs):
        return {"status": "not_found"}

    server = FakeMCPServer(handlers={
        "get_setup_plan": missing_plan,
        "approve_setup_plan": lambda **kwargs: {"status": "approved"},
        "execute_setup_plan": lambda **kwargs: {"status": "completed", "results": ["done"]},
    })
    workflow = AgentSetupWorkflow(FakeLLM([]), server)

    result = workflow.approve_and_execute("proj1", "missing-plan")

    assert result.workflow_status == "failed"
    assert result.error_message == "Plan not found"
    # Neither approval nor execution may be called.
    assert all(c[0] != "approve_setup_plan" for c in server.calls)
    assert all(c[0] != "execute_setup_plan" for c in server.calls)


def test_execution_failure():
    def fail_exec(**kwargs):
        return {"error": "execution exploded"}

    def existing_plan(**kwargs):
        return {"status": "pending_approval", "plan_id": "plan-1"}

    server = FakeMCPServer(handlers={
        "get_setup_plan": existing_plan,
        "approve_setup_plan": lambda **kwargs: {"status": "approved"},
        "execute_setup_plan": fail_exec,
    })
    workflow = AgentSetupWorkflow(FakeLLM([]), server)

    result = workflow.approve_and_execute("proj1", "plan-1")

    assert result.workflow_status == "failed"
    assert "execution exploded" in result.error_message


def test_llm_failure():
    class ExplodingLLM:
        def complete(self, prompt):
            raise RuntimeError("LLM is down")

    server = FakeMCPServer()
    workflow = AgentSetupWorkflow(ExplodingLLM(), server)

    with pytest.raises(RuntimeError):
        workflow.start_setup_workflow("proj1", "/tmp/proj")


def test_max_turn_failure():
    responses = [
        '{"tool_calls":[{"name":"get_setup_plan","arguments":{}}]}'
    ]
    llm = FakeLLM(responses)
    server = FakeMCPServer()
    workflow = AgentSetupWorkflow(llm, server, max_turns=1)

    result = workflow.start_setup_workflow("proj1", "/tmp/proj")

    assert result.workflow_status == "failed"
    assert result.error_message is not None
    assert "Maximum agent turns reached" in result.error_message


def test_no_direct_domain_imports():
    import app.agent_setup_workflow as asw
    source = asw.__file__
    with open(source, "r", encoding="utf-8") as f:
        code = f.read()
    forbidden = [
        "DevelopmentWorkflow",
        "SetupApproval",
        "WorkflowPlanStore",
        "PythonPackageExecutor",
        "AIRequirementDiscovery",
        "RequirementPreflight",
        "SetupPlanner",
    ]
    for name in forbidden:
        assert name not in code


def test_cli_start_and_approve(tmp_path):
    # Minimal smoke test for CLI functions without subprocess.
    from cli.agent_workflow_cli import start_command, approve_command

    class Args:
        project_id = "proj1"
        project_path = str(tmp_path)

    assert callable(start_command)
    assert callable(approve_command)


def test_plan_shape_with_id_and_no_wrapper():
    """Continuation should accept a real serialized SetupPlan with 'id'."""
    server = FakeMCPServer(handlers={
        "get_setup_plan": lambda **kwargs: {
            "id": "plan-real",
            "project_id": "proj1",
            "status": "pending_approval",
            "steps": [],
        },
        "approve_setup_plan": lambda **kwargs: {"status": "approved"},
        "execute_setup_plan": lambda **kwargs: {"status": "completed", "results": []},
    })
    workflow = AgentSetupWorkflow(FakeLLM([]), server)

    result = workflow.approve_and_execute("proj1", "plan-real")

    assert result.workflow_status == "completed"
    assert result.plan_id == "plan-real"
    assert result.approval_status == "approved"


def test_start_handles_real_setup_plan_shape_with_id():
    """Start should produce pending result when get_setup_plan returns a real SetupPlan representation."""
    responses = [
        '{"tool_calls":[{"name":"inspect_project","arguments":{}}]}',
        '{"tool_calls":[{"name":"discover_requirements","arguments":{}}]}',
        '{"tool_calls":[{"name":"get_preflight","arguments":{}}]}',
        '{"tool_calls":[{"name":"create_setup_plan","arguments":{}}]}',
        '{"tool_calls":[{"name":"get_setup_plan","arguments":{}}]}',
    ]
    llm = FakeLLM(responses)
    server = FakeMCPServer(handlers={
        "inspect_project": lambda **kwargs: {"status": "ok"},
        "discover_requirements": lambda **kwargs: {"status": "ok", "requirements": []},
        "get_preflight": lambda **kwargs: {"status": "ok", "preflight": {}},
        "create_setup_plan": lambda **kwargs: {"status": "ok", "plan_id": "plan-real"},
        "get_setup_plan": lambda **kwargs: {
            "id": "plan-real",
            "project_id": "proj1",
            "status": "pending_approval",
            "steps": [],
        },
        "approve_setup_plan": lambda **kwargs: {"status": "approved"},
        "execute_setup_plan": lambda **kwargs: {"status": "completed", "results": []},
    })
    workflow = AgentSetupWorkflow(llm, server)

    result = workflow.start_setup_workflow("proj1", "/tmp/proj")

    assert result.workflow_status == "pending_approval"
    assert result.plan_id == "plan-real"
    assert result.setup_plan is not None
    assert result.setup_plan["id"] == "plan-real"


# ---------------------------------------------------------------------------
# New tests: explicit get_setup_plan bridging when LLM stops too early
# ---------------------------------------------------------------------------

def test_explicit_get_call_when_llm_stops_after_create():
    """LLM stops after create_setup_plan; AgentSetupWorkflow must call
    get_setup_plan itself and reach pending_approval."""
    # LLM only calls up to create_setup_plan, then returns no more calls.
    responses = [
        '{"tool_calls":[{"name":"inspect_project","arguments":{}}]}',
        '{"tool_calls":[{"name":"discover_requirements","arguments":{}}]}',
        '{"tool_calls":[{"name":"get_preflight","arguments":{}}]}',
        '{"tool_calls":[{"name":"create_setup_plan","arguments":{}}]}',
        # LLM stops here; workflow must bridge the gap.
    ]
    llm = FakeLLM(responses)
    server = FakeMCPServer()  # default handlers include get_setup_plan returning pending_approval
    workflow = AgentSetupWorkflow(llm, server)

    result = workflow.start_setup_workflow("proj1", "/tmp/proj")

    assert result.workflow_status == "pending_approval"
    assert result.approval_required is True
    assert result.approval_status == "pending_approval"
    assert result.plan_id == "plan-1"  # from default handler
    assert result.error_message is None

    # The synthetic get_setup_plan must have been called on the MCP server.
    get_calls = [c for c in server.calls if c[0] == "get_setup_plan"]
    assert len(get_calls) >= 1

    # No approve or execute calls must have been made.
    called_tools = {c[0] for c in server.calls}
    assert "approve_setup_plan" not in called_tools
    assert "execute_setup_plan" not in called_tools


def test_explicit_get_call_error_handling():
    """When LLM stops early and explicit get_setup_plan returns an error,
    the workflow must report a genuine failure."""
    responses = [
        '{"tool_calls":[{"name":"inspect_project","arguments":{}}]}',
        '{"tool_calls":[{"name":"discover_requirements","arguments":{}}]}',
        '{"tool_calls":[{"name":"get_preflight","arguments":{}}]}',
        '{"tool_calls":[{"name":"create_setup_plan","arguments":{}}]}',
        # LLM stops here; workflow must bridge the gap.
    ]
    llm = FakeLLM(responses)
    # get_setup_plan will raise an error (simulated by handler returning {"error":...})
    error_server = FakeMCPServer(handlers={
        "inspect_project": lambda **kwargs: {"status": "ok"},
        "discover_requirements": lambda **kwargs: {"status": "ok", "requirements": []},
        "get_preflight": lambda **kwargs: {"status": "ok", "preflight": {}},
        "create_setup_plan": lambda **kwargs: {"status": "ok", "plan_id": "plan-1"},
        "get_setup_plan": lambda **kwargs: {"error": "simulated get_setup_plan failure"},
        "approve_setup_plan": lambda **kwargs: {"status": "approved"},
        "execute_setup_plan": lambda **kwargs: {"status": "completed", "results": []},
    })
    workflow = AgentSetupWorkflow(llm, error_server)

    result = workflow.start_setup_workflow("proj1", "/tmp/proj")

    assert result.workflow_status == "failed"
    assert "simulated get_setup_plan failure" in (result.error_message or "")
    assert result.approval_required is False

    # get_setup_plan must have been called (the explicit bridge).
    get_calls = [c for c in error_server.calls if c[0] == "get_setup_plan"]
    assert len(get_calls) >= 1

    # No approve or execute calls must have been made.
    called_tools = {c[0] for c in error_server.calls}
    assert "approve_setup_plan" not in called_tools
    assert "execute_setup_plan" not in called_tools


def test_no_approve_or_execute_during_start_workflow():
    """Start workflow must never call approve_setup_plan or execute_setup_plan,
    even when the LLM skips stopping early."""
    responses = [
        '{"tool_calls":[{"name":"inspect_project","arguments":{}}]}',
        # LLM stops after inspect; workflow must bridge get_setup_plan but must NOT
        # inadvertently call approve/execute.
        '{"tool_calls":[]}',
    ]
    llm = FakeLLM(responses)
    server = FakeMCPServer()
    workflow = AgentSetupWorkflow(llm, server)

    result = workflow.start_setup_workflow("proj1", "/tmp/proj")

    # The result may be pending_approval or a failure; the key invariant is that
    # approve/execute *never* appear in server calls.
    called_tools = {c[0] for c in server.calls}
    assert "approve_setup_plan" not in called_tools
    assert "execute_setup_plan" not in called_tools

    # If we reached pending_approval, we still must not have called approve/execute.
    if result.workflow_status == "pending_approval":
        assert result.approval_required is True
        assert "approve_setup_plan" not in called_tools
        assert "execute_setup_plan" not in called_tools


def test_pending_approval_detail_fields():
    """When pending_approval is reached, the result must correctly expose
    approval_required and approval_status."""
    # Use sequence where LLM calls everything including get_setup_plan.
    llm = FakeLLM(_llm_plan_sequence())
    server = FakeMCPServer()
    workflow = AgentSetupWorkflow(llm, server)

    result = workflow.start_setup_workflow("proj-X", "/opt/proj")

    assert result.workflow_status == "pending_approval"
    assert result.approval_required is True
    assert result.approval_status == "pending_approval"
    assert result.plan_id is not None
