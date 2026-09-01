from __future__ import annotations

import subprocess
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.agent_setup_workflow import AgentSetupWorkflow, AgentSetupWorkflowResult
from app.agent_executor import AgentExecutor
from app.ai_config import load_ai_config
from app.ai_requirement_discovery import AIRequirementDiscovery
from app.dev_workflow import DevelopmentWorkflow, WorkflowExecutionError
from app.development_stage import DeveloperAgent, DevelopmentStage
from app.development_testing_stage import DevelopmentTestingStage
from app.developer_file_applier import DeveloperFileApplier
from app.engineering_council import EngineeringCouncil
from app.diagnostic_trace import DiagnosticTraceRecorder, TraceEvent, TraceLevel
from app.llm_provider_factory import create_llm_provider
from app.local_secret_store import LocalSecretStore
from app.project_inspector import ProjectInspector
from app.project_test_runner import ProjectTestRunner
from app.project_setup_application import ProjectSetupApplicationService
from app.canonical_execution import (
    ConcurrentExecutionError, ExecutionReentryError, RecoveryRequiredError,
)
from app.mcp_server import MCPServer
from app.python_package_executor import PythonPackageExecutor
from app.requirement_preflight import RequirementPreflight
from app.requirement_validator import RequirementValidator
from app.setup_approval import SetupApproval
from app.setup_planner import SetupPlanner
from app.toolchain_materializer import ToolchainMaterializer
from app.test_change_generator import TestChangeGenerator
from app.testing_stage import DiagnosisReviewer, TestingStage
from app.workflow_plan_store import WorkflowPlanStore
from app.project_scanner import ProjectScanner

# Import the shared file reading helper.  This keeps the web component
# aligned with the existing CLI/domain behaviour instead of duplicating
# the same logic in a new place.
from app.workflow_cli import read_project_files


app = FastAPI(title="AI Dev Center Web GUI")
app.mount("/static", StaticFiles(directory="web"), name="static")


# ---------------------------------------------------------------------------
#  Tracing wrapper for MCPServer
# ---------------------------------------------------------------------------
class TracingMCPServerWrapper:
    """Intercepts MCPServer tool calls and records diagnostic trace events.

    The wrapper intentionally ignores ``list_tools`` and internal/dunder
    methods.  All other callable public methods on the real MCP server are
    treated as observable MCP tool calls and are recorded as tool_started,
    tool_completed, or tool_failed.
    """

    def __init__(self, real_mcp: MCPServer, recorder: DiagnosticTraceRecorder):
        self._real = real_mcp
        self._recorder = recorder

    def __getattr__(self, name: str):
        if name.startswith("_"):
            # Delegate internal/dunder attribute access to the real object.
            return getattr(self._real, name)

        attr = getattr(self._real, name)

        # list_tools is not a tool call itself; it only describes tools.
        if name == "list_tools" or not callable(attr):
            return attr

        def traced_call(*args, **kwargs):
            start = datetime.now()
            self._recorder.record(
                level=TraceLevel.INFO,
                component="MCP",
                event="tool_started",
                action=name,
                status="started",
                arguments=kwargs if kwargs else {},
            )
            try:
                result = attr(*args, **kwargs)
                elapsed_ms = (datetime.now() - start).total_seconds() * 1000
                self._recorder.record(
                    level=TraceLevel.INFO,
                    component="MCP",
                    event="tool_completed",
                    action=name,
                    status="success",
                    duration_ms=elapsed_ms,
                    result_summary=str(result)[:200],
                )
                return result
            except Exception as exc:
                elapsed_ms = (datetime.now() - start).total_seconds() * 1000
                self._recorder.record(
                    level=TraceLevel.ERROR,
                    component="MCP",
                    event="tool_failed",
                    action=name,
                    status="failed",
                    duration_ms=elapsed_ms,
                    result_summary=str(exc)[:200],
                )
                raise

        return traced_call


# ---------------------------------------------------------------------------
#  Session management
# ---------------------------------------------------------------------------
class Session:
    def __init__(
        self,
        project_id: str,
        project_path: str,
        task_description: str,
        run_id: str,
        trace_level: TraceLevel,
        recorder: DiagnosticTraceRecorder,
    ):
        self.project_id = project_id
        self.project_path = project_path
        self.task_description = task_description
        self.run_id = run_id
        self.trace_level = trace_level
        self.recorder = recorder
        self.mcp_wrapper: Optional[TracingMCPServerWrapper] = None
        self.workflow: Optional[AgentSetupWorkflow] = None
        self.development_workflow: Optional[DevelopmentWorkflow] = None
        self.project_setup_service: Optional[ProjectSetupApplicationService] = None
        self.plan_store: Optional[WorkflowPlanStore] = None
        self.approval = None
        self.plan_id: Optional[str] = None
        self.approval_status: Optional[str] = None
        self.approval_required: bool = False
        self.workflow_status: str = "unknown"
        self.error_message: Optional[str] = None
        self.blocked: bool = False
        self.final_approval_result = None

    @property
    def trace_events(self) -> List[TraceEvent]:
        return self.recorder.events


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

    project_scanner = ProjectScanner()
    plan_store = WorkflowPlanStore(".workflow-plans")
    approval = SetupApproval

    return MCPServer(
        project_scanner=project_scanner,
        discovery=discovery,
        preflight=RequirementPreflight,
        planner=SetupPlanner(),
        plan_store=plan_store,
        approval=approval,
        development_workflow=development_workflow,
    )


class WebSetupComponents:
    """Canonical planning dependencies for the web adapter."""

    def __init__(self, service, plan_store, approval, development_workflow):
        self.service = service
        self.plan_store = plan_store
        self.approval = approval
        self.development_workflow = development_workflow


def get_web_setup_components() -> WebSetupComponents:
    """Build the canonical setup path without creating legacy agents."""
    config = load_ai_config("config/ai-dev-center.yml")
    council_config = config.council
    if council_config is None or not council_config.enabled:
        raise WorkflowExecutionError(
            "Engineering Council configuration must be enabled."
        )

    secret_resolver = LocalSecretStore()
    llm_provider = create_llm_provider(config, secret_resolver)
    discovery = AIRequirementDiscovery(llm_provider=llm_provider, ai_model=config.model)
    council = EngineeringCouncil(
        council_config=council_config,
        secret_resolver=secret_resolver,
    )
    agent_executor = AgentExecutor(model=config.model)
    development_testing_stage = DevelopmentTestingStage(
        DevelopmentStage(DeveloperAgent(agent_executor)),
        TestChangeGenerator(agent_executor),
        DeveloperFileApplier,
        ProjectTestRunner(),
        TestingStage(DiagnosisReviewer(agent_executor)),
    )
    workflow = DevelopmentWorkflow(
        discovery=discovery,
        validator=RequirementValidator,
        preflight=RequirementPreflight,
        executor=PythonPackageExecutor(),
        council=council,
        materializer=ToolchainMaterializer(),
        development_testing_stage=development_testing_stage,
    )
    return WebSetupComponents(
        ProjectSetupApplicationService(workflow, ProjectInspector()),
        WorkflowPlanStore(".workflow-plans"),
        SetupApproval,
        workflow,
    )


# Legacy dependency retained for the old agent-backed compatibility path.
def get_workflow_components():
    config = load_ai_config("config/ai-dev-center.yml")
    secret_resolver = LocalSecretStore()
    llm_provider = create_llm_provider(config, secret_resolver)
    return llm_provider, build_mcp_server(config, llm_provider)


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------
def _serialize_event(trace_event: TraceEvent) -> Dict[str, Any]:
    return {
        "timestamp": trace_event.timestamp.isoformat(),
        "run_id": trace_event.run_id,
        "level": trace_event.level.value,
        "component": trace_event.component,
        "event": trace_event.event,
        "action": trace_event.action,
        "status": trace_event.status,
        "duration_ms": trace_event.duration_ms,
        "arguments": trace_event.arguments,
        "result_summary": trace_event.result_summary,
        "metadata": trace_event.metadata,
    }


def _serialize_trace(events: List[TraceEvent]) -> List[Dict[str, Any]]:
    return [_serialize_event(event) for event in events]


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

    completed_tool_actions = {
        ev.action
        for ev in events
        if ev.event == "tool_completed" and ev.status == "success"
    }
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

        tool_names_for_stage = [t for t, s in stage_map.items() if s == name]
        if any(t in completed_tool_actions for t in tool_names_for_stage):
            status = "completed"
        else:
            status = "pending"
        stages.append({"stage": name, "status": status})

    if session.blocked:
        for stage in stages:
            if stage["stage"] == "Inspect":
                stage["status"] = "completed"
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
    durations = [e.duration_ms for e in session.trace_events if e.duration_ms is not None]
    if durations:
        elapsed_str = f"{sum(durations) / 1000:.1f}s"

    return {
        "current_action": last_event.action if last_event else "idle",
        "current_component": last_event.component if last_event else "none",
        "current_mcp_tool": (
            last_event.action
            if last_event
            and last_event.component == "MCP"
            and last_event.event.startswith("tool_")
            else "none"
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
    task_description: str
    trace_level: TraceLevel = TraceLevel.INFO


class OpenProjectRequest(BaseModel):
    project_path: str


class FinalApprovalRequest(BaseModel):
    decision: str
    approved_by: str | None = None
    comment: str | None = None


@app.get("/")
async def root():
    return FileResponse("web/index.html")


@app.post("/api/workflow/start")
async def start_workflow(
    req: StartRequest,
    components: WebSetupComponents = Depends(get_web_setup_components),
):
    project_id = req.project_name
    project_path = req.project_directory
    task_description = req.task_description
    trace_level = req.trace_level

    # The established two-argument application-service contract uses the
    # project identifier as the canonical planning run identifier.
    session_id = run_id = project_id
    recorder = DiagnosticTraceRecorder(run_id=run_id, trace_level=trace_level)
    session = Session(
        project_id,
        project_path,
        task_description,
        run_id,
        trace_level,
        recorder,
    )

    recorder.record(
        level=TraceLevel.INFO,
        component="Workflow",
        event="workflow_started",
        action="start",
        status="started",
        arguments={
            "project_id": project_id,
            "project_path": project_path,
            "task_description": task_description,
        },
    )

    try:
        result = components.service.plan_project_setup(project_id, project_path)
        plan = result.setup_plan
        components.plan_store.save(plan)
    except (ValueError, FileNotFoundError, NotADirectoryError) as exc:
        return JSONResponse(content={"error": str(exc)}, status_code=400)
    except WorkflowExecutionError as exc:
        return JSONResponse(content={"error": str(exc)}, status_code=409)
    except Exception as exc:
        session.error_message = str(exc)
        session.blocked = True
        recorder.record(
            level=TraceLevel.ERROR,
            component="Workflow",
            event="exception",
            action="plan_project_setup",
            status="failed",
            result_summary=str(exc),
        )
        sessions[session_id] = session
        return JSONResponse(
            content={"session_id": session_id, "blocked": True, "error": str(exc)},
            status_code=500,
        )

    session.development_workflow = components.development_workflow
    session.project_setup_service = components.service
    session.plan_store = components.plan_store
    session.approval = components.approval
    session.plan_id = plan.id
    session.approval_required = True
    session.approval_status = plan.status
    session.workflow_status = plan.status

    recorder.record(
        level=TraceLevel.INFO,
        component="Workflow",
        event="plan_created",
        action="create_plan",
        status="success",
        result_summary=f"Plan {plan.id}",
    )

    recorder.record(
        level=TraceLevel.INFO,
        component="Workflow",
        event="approval_required",
        action="request_approval",
        status="pending",
        result_summary=f"Project {project_id}, Plan {plan.id}",
    )

    sessions[session_id] = session
    return {"session_id": session_id, "plan_id": plan.id, "status": plan.status}


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
        "run_id": session.run_id,
        "trace_level": session.trace_level.value,
        "project_id": session.project_id,
        "project_path": session.project_path,
        "task_description": session.task_description,
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

    recorder = session.recorder
    recorder.record(
        level=TraceLevel.INFO,
        component="Agent",
        event="approval_granted",
        action="approve",
        status="success",
    )
    recorder.record(
        level=TraceLevel.INFO,
        component="Workflow",
        event="execution_started",
        action="execute_approved_plan",
        status="started",
    )

    try:
        result = session.workflow.approve_and_execute(session.project_id, session.plan_id)
    except Exception as exc:
        session.error_message = str(exc)
        session.blocked = True
        session.workflow_status = "failed"
        recorder.record(
            level=TraceLevel.ERROR,
            component="Workflow",
            event="execution_failed",
            action="approve_and_execute",
            status="failed",
            result_summary=str(exc),
        )
        return JSONResponse(content={"error": str(exc)}, status_code=500)

    session.approval_status = "approved"
    if getattr(result, "workflow_status", None) == "completed":
        session.workflow_status = "completed"
    else:
        session.workflow_status = "executing"

    recorder.record(
        level=TraceLevel.INFO,
        component="Workflow",
        event="execution_completed",
        action="execute_approved_plan",
        status="success",
    )
    recorder.record(
        level=TraceLevel.INFO,
        component="Workflow",
        event="verification_completed",
        action="verify_execution",
        status="success",
    )

    return {"workflow_status": session.workflow_status}


@app.post("/api/workflow/{session_id}/approval")
async def approve_canonical_workflow(session_id: str):
    """Approve a canonical plan without starting execution."""
    session = sessions.get(session_id)
    if not session:
        return JSONResponse(content={"error": "unknown session"}, status_code=404)
    if not session.plan_store or not session.approval or not session.plan_id:
        return JSONResponse(content={"error": "no canonical plan to approve"}, status_code=400)
    try:
        plan = session.plan_store.load(session.project_id, session.plan_id)
        approved_plan = session.approval.approve(plan)
        session.plan_store.save(approved_plan)
    except Exception as exc:
        return JSONResponse(content={"error": str(exc)}, status_code=409)

    session.approval_status = approved_plan.status
    session.approval_required = False
    session.workflow_status = approved_plan.status
    return {"plan_id": approved_plan.id, "status": approved_plan.status}


@app.post("/api/workflow/{session_id}/execute")
async def execute_canonical_workflow(session_id: str):
    """Execute only a separately approved canonical plan."""
    session = sessions.get(session_id)
    if not session:
        return JSONResponse(content={"error": "unknown session"}, status_code=404)
    if not session.plan_store or not session.project_setup_service or not session.plan_id:
        return JSONResponse(content={"error": "no canonical plan to execute"}, status_code=400)
    try:
        plan = session.plan_store.load(session.project_id, session.plan_id)
        result = session.project_setup_service.execute_approved_setup_and_development(
            plan,
            session.project_id,
            session.project_path,
            session.task_description,
            session.run_id,
        )
    except ConcurrentExecutionError as exc:
        return JSONResponse(content={"status": "concurrent_execution_rejected", "error": str(exc)}, status_code=409)
    except RecoveryRequiredError as exc:
        return JSONResponse(content={"status": "recovery_required", "error": str(exc)}, status_code=409)
    except ExecutionReentryError as exc:
        return JSONResponse(content={"status": "reentry_rejected", "error": str(exc)}, status_code=409)
    except Exception as exc:
        return JSONResponse(content={"error": str(exc)}, status_code=409)

    session.final_approval_result = result.final_approval_result
    session.workflow_status = result.final_approval_result.status
    return {
        "plan_id": plan.id,
        "status": result.final_approval_result.status,
        "development_status": result.status,
        "results": result.setup_execution_results,
    }


@app.post("/api/workflow/{session_id}/final-approval")
async def decide_final_approval(session_id: str, request: FinalApprovalRequest):
    """Record an explicit final human decision without re-running development."""
    session = sessions.get(session_id)
    if not session or not session.project_setup_service:
        return JSONResponse(content={"error": "unknown session"}, status_code=404)
    try:
        result = session.project_setup_service.decide_final_approval(
            session.run_id, request.decision, request.approved_by, request.comment,
        )
    except Exception as exc:
        return JSONResponse(content={"error": str(exc)}, status_code=409)
    session.final_approval_result = result
    session.workflow_status = "ready_for_git" if result.ready_for_git else result.status
    return {"status": result.status, "ready_for_git": result.ready_for_git}


@app.post("/api/workflow/{session_id}/reject")
async def reject_workflow(session_id: str):
    session = sessions.get(session_id)
    if not session:
        return JSONResponse(content={"error": "unknown session"}, status_code=404)

    session.approval_status = "rejected"
    session.blocked = True
    session.workflow_status = "blocked"

    session.recorder.record(
        level=TraceLevel.INFO,
        component="Agent",
        event="approval_rejected",
        action="reject",
        status="rejected",
    )
    session.recorder.record(
        level=TraceLevel.INFO,
        component="Workflow",
        event="workflow_state_changed",
        action="blocked",
        status="blocked",
    )

    return {"status": "rejected"}


@app.get("/api/workflow/{session_id}/export")
async def export_trace(session_id: str):
    session = sessions.get(session_id)
    if not session:
        return JSONResponse(content={"error": "unknown session"}, status_code=404)

    return JSONResponse(content=session.recorder.export())


@app.get("/api/workflow/{session_id}/diagnostic-trace")
async def get_central_diagnostic_trace(session_id: str):
    """Read the persistent central trace through the application contract."""
    session = sessions.get(session_id)
    if not session or not session.project_setup_service:
        return JSONResponse(content={"error": "unknown session"}, status_code=404)
    events = session.project_setup_service.get_diagnostic_trace(session.run_id)
    return {
        "run_id": session.run_id,
        "events": [
            {
                "event_id": event.event_id,
                "sequence": event.sequence,
                "timestamp": event.timestamp,
                "phase": event.phase,
                "event_type": event.event_type,
                "status": event.status,
                "summary": event.summary,
                "source": event.source,
                "details": event.details,
                "related_result_id": event.related_result_id,
            }
            for event in events
        ],
    }


@app.post("/api/project/open")
async def open_project_directory(req: OpenProjectRequest):
    """Open the provided project directory using the Linux file manager."""
    raw_path = req.project_path
    if not isinstance(raw_path, str) or not raw_path.strip():
        return JSONResponse(
            content={"error": "project_path must be a non-empty string"},
            status_code=400,
        )

    path = Path(raw_path).expanduser()
    if not path.exists():
        return JSONResponse(
            content={"error": "project path does not exist"},
            status_code=400,
        )
    if not path.is_dir():
        return JSONResponse(
            content={"error": "project path is not a directory"},
            status_code=400,
        )

    try:
        # Use xdg-open to open the directory in the Linux file manager.
        # Never use shell=True.
        subprocess.run(["xdg-open", str(path)], check=False)
    except Exception as exc:
        return JSONResponse(
            content={"error": f"failed to open project directory: {exc}"},
            status_code=500,
        )

    return {"status": "opened", "project_path": str(path)}
