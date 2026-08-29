from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.llm_agent import AgentLLM, AgentState, LLMProvider


class MCPSetupTools(Protocol):
    def list_tools(self) -> list[Any]:
        """Return available tools."""
        ...

    # Additional tool methods are resolved dynamically via getattr() in the
    # integration layer.  The actual MCPServer implementation provides them.


@dataclass
class AgentSetupWorkflowResult:
    project_id: str
    project_path: str
    agent_status: str
    workflow_status: str
    plan_id: str | None = None
    setup_plan: dict[str, Any] | None = None
    approval_required: bool = False
    approval_status: str | None = None
    execution_results: list[Any] = field(default_factory=list)
    error_message: str | None = None
    conversation_trace_id: str | None = None


_PENDING_APPROVAL = "pending_approval"
_APPROVED = "approved"

_REQUIRED_TOOL_SEQUENCE = [
    "inspect_project",
    "discover_requirements",
    "get_preflight",
    "create_setup_plan",
    "get_setup_plan",
]


class AgentSetupWorkflow:
    """Integrates the minimal LLM agent with the existing AgentWorkflow/MCPServer boundary.

    The LLM agent is only allowed to interact with MCP tools.  This class
    therefore never imports domain services directly; it talks exclusively
    through the supplied MCP server.
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        mcp_server: MCPSetupTools,
        max_turns: int = 5,
    ):
        self.llm_provider = llm_provider
        self.mcp_server = mcp_server
        self.max_turns = max_turns
        self.agent = AgentLLM(llm_provider, mcp_server, max_turns)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def start_setup_workflow(
        self,
        project_id: str,
        project_path: str,
    ) -> AgentSetupWorkflowResult:
        """Run the agent until it reaches pending_approval or fails."""
        prompt = (
            "You are an AI developer assistant driving a setup workflow.\n"
            "Call MCP tools in the following order:\n"
            f"inspect_project(project_id={project_id!r}, project_path={project_path!r})\n"
            f"discover_requirements(project_id={project_id!r})\n"
            f"get_preflight(project_id={project_id!r})\n"
            f"create_setup_plan(project_id={project_id!r})\n"
            f"get_setup_plan(project_id={project_id!r})\n"
            "After get_setup_plan, stop.  Do not call approve_setup_plan or "
            "execute_setup_plan.  Approval requires explicit human action."
        )

        stop_condition = _stop_if_pending_approval
        state = self.agent.run(prompt, stop_condition=stop_condition)

        trace_id = _trace_id(state)
        used_turns = _count_assistant_messages(state)
        max_turns_hit = state.max_turns_reached or used_turns >= self.max_turns

        # ------------------------------------------------------------------
        # Ensure get_setup_plan is called when the LLM stops after
        # create_setup_plan but before get_setup_plan.
        # ------------------------------------------------------------------
        if not _has_required_sequence(state):
            # Check if the sequence up to create_setup_plan is complete.
            if _has_sequence_up_to_create(state):
                # The LLM stopped before calling get_setup_plan.
                # Explicitly invoke get_setup_plan through the MCP boundary.
                plan_result = self._call_tool(
                    "get_setup_plan", project_id=project_id
                )
                # Record the tool call in the state so that subsequent
                # helpers can inspect it.
                state.tool_calls.append({
                    "name": "get_setup_plan",
                    "arguments": {"project_id": project_id},
                    "result": plan_result,
                })
                # Re‑evaluate the stop condition on the explicit result.
                stop_reason = stop_condition(plan_result)
                if stop_reason == _PENDING_APPROVAL:
                    state.stop_reason = _PENDING_APPROVAL
                    return self._pending_result(
                        project_id, project_path, state, trace_id
                    )
                # If the explicit call did not yield pending approval,
                # treat it as a failure.
                error_msg = (
                    plan_result.get("error")
                    if isinstance(plan_result, dict)
                    else "get_setup_plan did not return pending approval"
                )
                return AgentSetupWorkflowResult(
                    project_id=project_id,
                    project_path=project_path,
                    agent_status="failed",
                    workflow_status="failed",
                    error_message=error_msg,
                    conversation_trace_id=trace_id,
                )

        if max_turns_hit:
            # Max turns is a hard upper bound.  Only accept pending approval
            # when the whole required sequence has been completed.
            if state.stop_reason == _PENDING_APPROVAL and _has_required_sequence(state):
                return self._pending_result(
                    project_id, project_path, state, trace_id
                )
            return AgentSetupWorkflowResult(
                project_id=project_id,
                project_path=project_path,
                agent_status="failed",
                workflow_status="failed",
                error_message="Maximum agent turns reached",
                conversation_trace_id=trace_id,
            )

        if state.stop_reason == _PENDING_APPROVAL:
            if _has_required_sequence(state):
                return self._pending_result(
                    project_id, project_path, state, trace_id
                )
            return AgentSetupWorkflowResult(
                project_id=project_id,
                project_path=project_path,
                agent_status="failed",
                workflow_status="failed",
                error_message="Workflow reached pending approval before completing required sequence",
                conversation_trace_id=trace_id,
            )

        if state.last_error:
            return AgentSetupWorkflowResult(
                project_id=project_id,
                project_path=project_path,
                agent_status="tool_error",
                workflow_status="failed",
                error_message=state.last_error,
                conversation_trace_id=trace_id,
            )

        # The agent completed without a clear pending approval.
        return AgentSetupWorkflowResult(
            project_id=project_id,
            project_path=project_path,
            agent_status="completed_without_approval",
            workflow_status="failed",
            error_message="Agent stopped before reaching pending_approval",
            conversation_trace_id=trace_id,
        )

    def approve_and_execute(
        self,
        project_id: str,
        plan_id: str,
    ) -> AgentSetupWorkflowResult:
        """Explicit human approval followed by execution through MCP only."""
        if not plan_id:
            raise ValueError("plan_id is required")

        # Resolve/load the plan through the MCP interface before approval.
        plan_result = self._call_tool(
            "get_setup_plan", project_id=project_id, plan_id=plan_id
        )
        if not _plan_exists(plan_result, plan_id):
            return AgentSetupWorkflowResult(
                project_id=project_id,
                project_path="",
                agent_status="plan_not_found",
                workflow_status="failed",
                plan_id=plan_id,
                approval_required=False,
                approval_status=None,
                error_message="Plan not found",
            )

        approval_result = self._call_tool(
            "approve_setup_plan", project_id=project_id, plan_id=plan_id
        )
        if not _is_approved(approval_result):
            return AgentSetupWorkflowResult(
                project_id=project_id,
                project_path="",
                agent_status="approval_failed",
                workflow_status="failed",
                plan_id=plan_id,
                approval_required=False,
                approval_status=_result_status(approval_result),
                error_message="Approval was rejected or could not be verified",
            )

        execution_result = self._call_tool(
            "execute_setup_plan", project_id=project_id, plan_id=plan_id
        )
        if isinstance(execution_result, dict) and execution_result.get("error"):
            return AgentSetupWorkflowResult(
                project_id=project_id,
                project_path="",
                agent_status="execution_failed",
                workflow_status="failed",
                plan_id=plan_id,
                execution_results=[execution_result],
                error_message=str(execution_result.get("error")),
            )

        return AgentSetupWorkflowResult(
            project_id=project_id,
            project_path="",
            agent_status="completed",
            workflow_status="completed",
            plan_id=plan_id,
            approval_required=False,
            approval_status=_APPROVED,
            execution_results=[execution_result],
            conversation_trace_id=None,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _pending_result(
        self,
        project_id: str,
        project_path: str,
        state: AgentState,
        trace_id: str,
    ) -> AgentSetupWorkflowResult:
        last_tool = _last_tool(state)
        plan_info = _extract_plan_info(last_tool)
        return AgentSetupWorkflowResult(
            project_id=project_id,
            project_path=project_path,
            agent_status=state.stop_reason,
            workflow_status=_PENDING_APPROVAL,
            plan_id=plan_info.get("plan_id"),
            setup_plan=plan_info.get("setup_plan"),
            approval_required=True,
            approval_status=_PENDING_APPROVAL,
            conversation_trace_id=trace_id,
        )

    def _call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        try:
            method = getattr(self.mcp_server, tool_name)
        except AttributeError:
            return {"error": f"Unknown tool: {tool_name}"}
        try:
            return method(**kwargs)
        except Exception as exc:
            return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Stop condition / result helpers
# ---------------------------------------------------------------------------
def _stop_if_pending_approval(result: dict[str, Any]) -> str | None:
    if not isinstance(result, dict):
        return None
    status = result.get("status")
    if status == _PENDING_APPROVAL:
        return _PENDING_APPROVAL
    if result.get("approval_required") is True:
        return _PENDING_APPROVAL
    return None


def _last_tool(state: AgentState) -> dict[str, Any] | None:
    if state.tool_calls:
        return state.tool_calls[-1]
    return None


def _extract_plan_info(tool_call: dict[str, Any] | None) -> dict[str, Any]:
    if not tool_call:
        return {}
    result = tool_call.get("result")
    if not isinstance(result, dict):
        return {}

    plan_id = result.get("plan_id")
    if plan_id is None:
        plan_id = result.get("id")

    setup_plan = result.get("setup_plan") if "setup_plan" in result else result

    return {
        "plan_id": plan_id,
        "setup_plan": setup_plan,
    }


def _is_approved(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("status") == _APPROVED:
        return True
    if result.get("approved") is True:
        return True
    return False


def _result_status(result: Any) -> str | None:
    if isinstance(result, dict):
        return result.get("status")
    return None


def _trace_id(state: AgentState) -> str:
    return str(id(state))


def _count_assistant_messages(state: AgentState) -> int:
    """Count LLM turns represented by assistant messages."""
    return sum(1 for msg in state.messages if msg.get("role") == "assistant")


def _has_required_sequence(state: AgentState) -> bool:
    """Return True when the agent has executed the required tool sequence."""
    tool_names = [call.get("name") for call in state.tool_calls]
    idx = 0
    for required in _REQUIRED_TOOL_SEQUENCE:
        if required not in tool_names:
            return False
        try:
            idx = tool_names.index(required, idx) + 1
        except ValueError:
            return False
    return True


def _has_sequence_up_to_create(state: AgentState) -> bool:
    """Return True when the agent has executed the required sequence up to
    and including create_setup_plan, but not necessarily get_setup_plan."""
    tool_names = [call.get("name") for call in state.tool_calls]
    idx = 0
    for required in _REQUIRED_TOOL_SEQUENCE:
        if required == "get_setup_plan":
            # We only care about the prefix up to create_setup_plan.
            break
        if required not in tool_names:
            return False
        try:
            idx = tool_names.index(required, idx) + 1
        except ValueError:
            return False
    return True


def _plan_exists(result: Any, expected_plan_id: str) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("error"):
        return False

    status = result.get("status")
    if status in {"not_found", "missing", "failed"}:
        return False

    result_plan_id = result.get("plan_id")
    if result_plan_id is None:
        result_plan_id = result.get("id")

    if result_plan_id is None:
        return False

    return str(result_plan_id) == str(expected_plan_id)
