from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.agent_setup_workflow import AgentSetupWorkflow, AgentSetupWorkflowResult
from app.ai_config import load_ai_config
from app.ai_requirement_discovery import AIRequirementDiscovery
from app.dev_workflow import DevelopmentWorkflow
from app.llm_provider_factory import create_llm_provider
from app.local_secret_store import LocalSecretStore
from app.mcp_server import MCPServer
from app.python_package_executor import PythonPackageExecutor
from app.requirement_preflight import RequirementPreflight
from app.requirement_validator import RequirementValidator
from app.setup_approval import SetupApproval
from app.setup_planner import SetupPlanner
from app.workflow_plan_store import WorkflowPlanStore
from app.gui import sanitize_args

# Import the shared file reading helper.  This keeps the web component
# aligned with the existing CLI/domain behaviour instead of duplicating
# the same logic in a new place.
from app.workflow_cli import read_project_files


app = FastAPI(title="AI Dev Center Web GUI")
app.mount("/web", StaticFiles(directory="web"), name="web")


# ---------------------------------------------------------------------------
#  Trace event model
# ---------------------------------------------------------------------------
from dataclasses import dataclass


@dataclass
class TraceEvent:
    timestamp: datetime
    component: str
    action: str
    status: str          # "start", "success", "failure"
    duration: Optional[float] = None
    args: Optional[Dict[str, Any]] = None
    result_summary: Optional[str] = None


# ---------------------------------------------------------------------------
#  Tracing wrapper for MCPServer
# ---------------------------------------------------------------------------
class TracingMCPServerWrapper:
    """Intercepts tool calls and records them as TraceEvent entries."""

    def __init__(self, real_mcp: MCPServer, event_list: List[TraceEvent]):
        self._real = real_mcp
        self._events = event_list
        try:
            self._tool_names = {t.name for t in real_mcp.list_tools()}
        except Exception:
            # Some mocks or lightweight doubles may not implement list_tools.
            # In production this will always succeed.
            self._tool_names = set()

    def __getattr__(self, name: str):
        attr = getattr(self._real, name)
        if name not in self._tool_names or not callable(attr):
            # Passthrough for non‑tool attributes (including `list_tools` itself)
            return attr

        def traced_call(*args, **kwargs):
            start = datetime.now()
            sanitized = sanitize_args(kwargs) if kwargs else {}
            self._events.append(
                TraceEvent(
                    timestamp=start,
                    component="MCP",
                    action=name,
                    status="start",
                    args=sanitized,
                )
            )
            try:
                result = attr(*args, **kwargs)
                elapsed = (datetime.now() - start).total_seconds()
                self._events.append(
                    TraceEvent(
                        timestamp=datetime.now(),
                        component="MCP",
                        action=name,
                        status="success",
                        duration=elapsed,
                        result_summary=str(result)[:200],
                    )
                )
                return result
            except Exception as exc:
                elapsed = (datetime.now() - start).total_seconds()
                self._events.append(
                    TraceEvent(
                        timestamp=datetime.now(),
                        component="MCP",
                        action=name,
                        status="failure",
                        duration=elapsed,
                        result_summary=str(exc)[:200],
                    )
                )
                raise
        return traced_call


# ---------------------------------------------------------------------------
#  Session management
# ---------------------------------------------------------------------------
class Session:
    def __init__(self, project_id: str, project_path: str):
        self.project_id = project_id
        self.project_path = project_path
        self.trace_events: List[TraceEvent] = []
        self.mcp_wrapper: Optional[TracingMCPServerWrapper] = None
        self.workflow: Optional[AgentSetupWorkflow] = None
        self.plan_id: Optional[str] = None
        self.approval_status: Optional[str] = None
        self.approval_required: bool = False
        self.workflow_status: str = "unknown"
        self.error_message: Optional[str] = None
        self.blocked: bool = False


sessions: Dict[str, Session] = {}


# ---------------------------------------------------------------------------
#  Component construction
# ---------------------------------------------------------------------------
def build_mcp_server(config, llm_provider) -> MCPServer:
    """Create a fully wired MCPServer, matching the application's normal
    dependency graph instead of relying on a zero-argument constructor."""
    discovery = AIRequirementDiscovery(
        llm_provider=llm_provider,
        ai_model=config.model,
    )

    development_workflow = DevelopmentWorkflow(
        discovery=discovery,
        validator=RequirementValidator,
        preflight=RequirementPreflight,
        planner=SetupPlanner(),
        executor=PythonPackageExecutor(),
    )

    plan_store = WorkflowPlanStore(".workflow-plans")
    approval = SetupApproval

    return MCPServer(
        project_scanner=read_project_files,
        discovery=discovery,
        preflight=RequirementPreflight,
        planner=SetupPlanner(),
        plan_store=plan_store,
        approval=approval,
        development_workflow=development_workflow,
    )


def get_workflow_components():
    """Load centralized AI configuration and build both LLM provider and
    properly wired MCPServer.  This mirrors the existing CLI application
    construction path."""
    config = load_ai_config("config/ai-dev-center.yml")
    secret_resolver = LocalSecretStore()
    llm_provider = create_llm_provider(config, secret_resolver)
    mcp_server = build_mcp_server(config, llm_provider)
    return llm_provider, mcp_server


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------
def _serialize_trace(events: List[TraceEvent]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for ev in events:
        rows.append(
            {
                "timestamp": ev.timestamp.isoformat(),
                "component": ev.component,
                "action": ev.action,
                "status": ev.status,
                "duration": ev.duration,
                "args": ev.args,
                "result_summary": ev.result_summary,
            }
        )
    return rows


def _compute_timeline(events: List[TraceEvent], session: Session) -> List[Dict[str, str]]:
    STAGE_ORDER = [
        "Inspect",
        "Discovery",
        "Preflight",
        "Setup Plan",
        "Approval",
        "Execution",
        "Verification",
        "Completed",
        "Failed",
    ]

    completed_tools = {ev.action for ev in events if ev.status == "success"}
    stage_map = {
        "inspect_project": "Inspect",
        "discover_requirements": "Discovery",
        "run_preflight": "Preflight",
        "create_plan": "Setup Plan",
    }

    stages: List[Dict[str, str]] = []
    for name in STAGE_ORDER:
        if name == "Approval":
            if session.approval_required and not session.workflow_status == "completed":
                status = "pending"
            elif session.approval_status == "approved" or session.workflow_status == "completed":
                status = "completed"
            else:
                status = "pending"
            stages.append({"stage": name, "status": status})
            continue
        if name == "Execution":
            if session.approval_status == "approved" and session.workflow_status != "completed":
                status = "in_progress"
            elif session.workflow_status == "completed":
                status = "completed"
            else:
                status = "pending"
            stages.append({"stage": name, "status": status})
            continue
        if name == "Verification":
            if session.workflow_status == "completed":
                status = "completed"
            else:
                status = "pending"
            stages.append({"stage": name, "status": status})
            continue
        if name in ("Completed", "Failed"):
            if session.error_message:
                stages.append({"stage": "Failed", "status": "active"})
            elif session.workflow_status == "completed":
                stages.append({"stage": "Completed", "status": "active"})
            else:
                stages.append({"stage": name, "status": "inactive"})
            continue

        # Map tool->stage
        tool_names_for_stage = [t for t, s in stage_map.items() if s == name]
        if any(t in completed_tools for t in tool_names_for_stage):
            status = "completed"
        else:
            status = "pending"
        stages.append({"stage": name, "status": status})

    if session.blocked:
        # insert "Blocked" stage overriding
        for s in stages:
            if s["stage"] == "Inspect":
                s["status"] = "completed"
        stages.append({"stage": "Blocked", "status": "active"})

    return stages


def _current_state_info(session: Session) -> Dict[str, Any]:
    last_event = session.trace_events[-1] if session.trace_events else None
    last_completed = None
    next_expected = None
    if session.blocked:
        next_expected = "Workflow blocked"
    elif session.workflow_status == "completed":
        next_expected = "Workflow completed"
    elif session.approval_required and not session.approval_status == "approved":
        next_expected = "User approval"
    else:
        next_expected = "Execution"
    if last_event and last_event.status in ("success", "failure"):
        last_completed = f"{last_event.action} ({last_event.status})"
    elapsed_str = ""
    if events_with_dur := [e for e in session.trace_events if e.duration is not None]:
        total = sum(e.duration for e in events_with_dur)
        elapsed_str = f"{total:.1f}s"
    return {
        "current_action": last_event.action if last_event else "idle",
        "current_component": last_event.component if last_event else "none",
        "current_mcp_tool": (
            last_event.action if last_event and last_event.component == "MCP" else "none"
        ),
        "elapsed": elapsed_str,
        "last_completed": last_completed or "none",
        "next_expected": next_expected,
    }


# ---------------------------------------------------------------------------
#  API endpoints
# ---------------------------------------------------------------------------
class StartRequest(BaseModel):
    project_name: str
    project_directory: str


@app.get("/")
async def root():
    return FileResponse("web/index.html")


@app.post("/api/workflow/start")
async def start_workflow(
    req: StartRequest,
    components: tuple = Depends(get_workflow_components),
):
    llm_provider, mcp_server = components
    project_id = req.project_name
    project_path = req.project_directory
    session_id = str(uuid.uuid4())
    session = Session(project_id, project_path)

    wrapper = TracingMCPServerWrapper(mcp_server, session.trace_events)
    session.mcp_wrapper = wrapper
    workflow = AgentSetupWorkflow(llm_provider, wrapper)
    session.workflow = workflow

    try:
        result: AgentSetupWorkflowResult = workflow.start_setup_workflow(
            project_id, project_path
        )
    except Exception as exc:
        session.error_message = str(exc)
        session.blocked = True
        sessions[session_id] = session
        return JSONResponse(
            content={"session_id": session_id, "blocked": True, "error": str(exc)},
            status_code=200,
        )

    session.plan_id = result.plan_id
    session.approval_required = bool(result.approval_required)
    session.approval_status = getattr(result, "approval_status", "pending")
    session.error_message = result.error_message
    if result.error_message:
        session.blocked = True
    if not result.approval_required and not result.error_message:
        session.workflow_status = "completed"
    else:
        # Add synthetic approval‑pending event
        session.trace_events.append(
            TraceEvent(
                timestamp=datetime.now(),
                component="Agent",
                action="plan_ready",
                status="start",
                result_summary="Plan created, awaiting approval",
            )
        )
    sessions[session_id] = session
    return {"session_id": session_id, "plan_id": result.plan_id}


@app.get("/api/state/{session_id}")
async def get_state(session_id: str):
    session = sessions.get(session_id)
    if not session:
        return JSONResponse(content={"error": "unknown session"}, status_code=404)
    trace = _serialize_trace(session.trace_events)
    timeline = _compute_timeline(session.trace_events, session)
    info = _current_state_info(session)
    return {
        "session_id": session_id,
        "project_id": session.project_id,
        "project_path": session.project_path,
        "plan_id": session.plan_id,
        "approval_required": session.approval_required,
        "approval_status": session.approval_status,
        "workflow_status": session.workflow_status,
        "blocked": session.blocked,
        "error_message": session.error_message,
        "trace": trace,
        "timeline": timeline,
        "transparency": info,
    }


@app.post("/api/workflow/{session_id}/approve")
async def approve_workflow(session_id: str):
    session = sessions.get(session_id)
    if not session:
        return JSONResponse(content={"error": "unknown session"}, status_code=404)
    if not session.workflow or not session.plan_id:
        return JSONResponse(content={"error": "no plan to approve"}, status_code=400)
    if session.workflow_status == "completed":
        return JSONResponse(content={"message": "already completed"}, status_code=200)
    try:
        result = session.workflow.approve_and_execute(session.project_id, session.plan_id)
    except Exception as exc:
        session.error_message = str(exc)
        session.blocked = True
        session.workflow_status = "failed"
        return JSONResponse(content={"error": str(exc)}, status_code=500)

    session.approval_status = "approved"
    if getattr(result, "workflow_status", None) == "completed":
        session.workflow_status = "completed"
    else:
        session.workflow_status = "executing"
    # add post‑approval execution trace
    session.trace_events.append(
        TraceEvent(
            timestamp=datetime.now(),
            component="Agent",
            action="execution_complete",
            status="success",
            result_summary="Execution finished",
        )
    )
    return {"workflow_status": session.workflow_status}


@app.post("/api/workflow/{session_id}/reject")
async def reject_workflow(session_id: str):
    session = sessions.get(session_id)
    if not session:
        return JSONResponse(content={"error": "unknown session"}, status_code=404)
    session.approval_status = "rejected"
    session.blocked = True
    session.workflow_status = "blocked"
    session.trace_events.append(
        TraceEvent(
            timestamp=datetime.now(),
            component="Agent",
            action="rejected",
            status="failure",
            result_summary="Workflow rejected by user",
        )
    )
    return {"status": "rejected"}
