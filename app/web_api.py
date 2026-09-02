from __future__ import annotations

import subprocess
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.dev_workflow import (
    DevelopmentWorkflow, WorkflowBlockedError, WorkflowExecutionError,
)
from app.diagnostic_trace import DiagnosticTraceRecorder, TraceEvent, TraceLevel
from app.project_setup_application import ProjectSetupApplicationService
from app.canonical_execution import (
    ConcurrentExecutionError, ExecutionReentryError, RecoveryRequiredError,
)
from app.workflow_plan_store import WorkflowPlanStore
from app.canonical_composition import build_canonical_components
from app.ai_config import load_ai_config, update_web_config

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

    def __init__(self, real_mcp: object, recorder: DiagnosticTraceRecorder):
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
        self.workflow: Optional[object] = None
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
_planning_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="web-planning")
planning_tasks: Dict[str, Future] = {}


# ---------------------------------------------------------------------------
#  Component construction
# ---------------------------------------------------------------------------
class WebSetupComponents:
    """Canonical planning dependencies for the web adapter."""

    def __init__(self, service, plan_store, approval, development_workflow):
        self.service = service
        self.plan_store = plan_store
        self.approval = approval
        self.development_workflow = development_workflow


def get_web_setup_components() -> WebSetupComponents:
    """Build the canonical setup path without creating legacy agents."""
    components = build_canonical_components()
    return WebSetupComponents(
        components.service, components.plan_store, components.approval,
        components.development_workflow,
    )


# Legacy dependency retained for the old agent-backed compatibility path.
def get_workflow_components():
    """Deprecated compatibility hook; returns the canonical composition."""
    return build_canonical_components()


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


class ValidateProjectRequest(BaseModel):
    project_path: str


class WebConfigUpdate(BaseModel):
    model: str | None = None
    endpoint: str | None = None
    timeout_seconds: float | None = None
    secret_reference: str | None = None
    discovery_enabled: bool | None = None
    require_json: bool | None = None
    max_requirements: int | None = None

    class Config:
        extra = "forbid"


def get_web_config_path() -> Path:
    return Path("config/ai-dev-center.yml")


def _web_config_response(config):
    council = None
    if config.council is not None:
        council = {
            "enabled": config.council.enabled,
            "max_variants_per_agent": config.council.max_variants_per_agent,
            "roles": {
                name: asdict(getattr(config.council, name))
                for name in (
                    "environment_architect", "toolchain_integrator",
                    "risk_assessor", "chairman",
                )
            },
            "read_only": True,
        }
    return {
        "version": config.version,
        "ai": {
            "provider": config.provider, "model": config.model,
            "endpoint": config.endpoint,
            "authentication": {
                "type": config.authentication.type,
                "secret_reference": config.authentication.secret,
            },
            "timeout_seconds": config.timeout_seconds,
            "discovery": asdict(config.discovery),
            "council": council,
        },
        "writable_fields": [
            "model", "endpoint", "timeout_seconds", "secret_reference",
            "discovery_enabled", "require_json", "max_requirements",
        ],
    }


class LocalDirectorySelector:
    """Select a server-local directory using one fixed desktop command."""

    def select(self) -> str | None:
        result = subprocess.run(
            ["zenity", "--file-selection", "--directory", "--title=Select project directory"],
            check=False, capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None


def get_directory_selector():
    return LocalDirectorySelector()


def _resolved_existing_directory(raw_path: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("Project directory is required.")
    try:
        path = Path(raw_path).expanduser().resolve(strict=True)
    except (FileNotFoundError, OSError, RuntimeError) as error:
        raise FileNotFoundError("Project directory does not exist.") from error
    if not path.is_dir():
        raise NotADirectoryError("Project path is not a directory.")
    return path


class FinalApprovalRequest(BaseModel):
    decision: str
    approved_by: str | None = None
    comment: str | None = None


@app.get("/")
async def root():
    return FileResponse("web/index.html")


@app.get("/api/config")
async def get_web_config(config_path: Path = Depends(get_web_config_path)):
    try:
        return _web_config_response(load_ai_config(config_path))
    except ValueError:
        return JSONResponse(
            content={"error": "Productive configuration is unavailable."},
            status_code=500,
        )


@app.patch("/api/config")
async def patch_web_config(
    request: WebConfigUpdate,
    config_path: Path = Depends(get_web_config_path),
):
    updates = {
        key: value for key, value in request.dict(exclude_unset=True).items()
        if value is not None
    }
    try:
        config = update_web_config(config_path, updates)
    except ValueError as error:
        return JSONResponse(content={"error": str(error)}, status_code=400)
    except OSError:
        return JSONResponse(
            content={"error": "Productive configuration could not be saved."},
            status_code=500,
        )
    return _web_config_response(config)


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
        },
    )

    try:
        project_path = str(_resolved_existing_directory(project_path))
        session.project_path = project_path
    except (ValueError, FileNotFoundError, NotADirectoryError) as exc:
        safe_error = str(exc) if isinstance(
            exc, (FileNotFoundError, NotADirectoryError)
        ) else "Project or planning request was rejected."
        status_code = 400
        session.error_message = safe_error
        session.blocked = True
        session.workflow_status = "failed"
        recorder.record(
            level=TraceLevel.ERROR, component="Workflow",
            event="workflow_start_failed", action="validate_project",
            status="failed", result_summary=safe_error,
        )
        sessions[session_id] = session
        return JSONResponse(content={
            "session_id": session_id, "blocked": True,
            "status": "failed", "error": safe_error,
        }, status_code=status_code)

    existing = sessions.get(session_id)
    if existing is not None and existing.workflow_status in {"planning", "running"}:
        return JSONResponse(content={
            "session_id": session_id, "status": existing.workflow_status,
            "error": "This project already has an active Web workflow session.",
        }, status_code=409)

    session.development_workflow = components.development_workflow
    session.project_setup_service = components.service
    session.plan_store = components.plan_store
    session.approval = components.approval
    session.workflow_status = "planning"
    sessions[session_id] = session
    task = _planning_executor.submit(_run_initial_planning, session, components)
    planning_tasks[session_id] = task
    task.add_done_callback(lambda _task, sid=session_id: planning_tasks.pop(sid, None))
    return JSONResponse(content={
        "session_id": session_id, "status": "planning",
    }, status_code=202)


def _run_initial_planning(session: Session, components: WebSetupComponents):
    terminal_kind = "failed"
    try:
        result = components.service.plan_project_setup(
            session.project_id, session.project_path,
        )
        plan = result.setup_plan
        components.plan_store.save(plan)
    except WorkflowBlockedError as error:
        safe_error = error.safe_reason
        terminal_kind = "blocked"
    except (ValueError, FileNotFoundError, NotADirectoryError):
        safe_error = "Project or planning request was rejected."
    except WorkflowExecutionError:
        safe_error = "The central workflow rejected the planning request."
    except Exception:
        safe_error = "The central workflow could not start."
    else:
        session.plan_id = plan.id
        session.approval_required = True
        session.approval_status = plan.status
        session.workflow_status = plan.status
        session.recorder.record(
            level=TraceLevel.INFO, component="Workflow", event="plan_created",
            action="create_plan", status="success",
            result_summary=f"Plan {plan.id}",
        )
        session.recorder.record(
            level=TraceLevel.INFO, component="Workflow", event="approval_required",
            action="request_approval", status="pending",
            result_summary=f"Project {session.project_id}, Plan {plan.id}",
        )
        return

    if safe_error:
        session.error_message = safe_error
        session.blocked = terminal_kind == "blocked"
        session.workflow_status = terminal_kind
        session.recorder.record(
            level=TraceLevel.WARNING if terminal_kind == "blocked" else TraceLevel.ERROR,
            component="Workflow",
            event=(
                "workflow_planning_blocked"
                if terminal_kind == "blocked" else "workflow_planning_failed"
            ),
            action="plan_project_setup", status=terminal_kind,
            result_summary=safe_error,
        )


@app.get("/api/state/{session_id}")
async def get_state(session_id: str):
    session = sessions.get(session_id)
    if not session:
        return JSONResponse(content={"error": "unknown session"}, status_code=404)

    trace = _serialize_trace(session.trace_events)
    central_trace = []
    current_activity = None
    if session.project_setup_service is not None:
        try:
            central_events = session.project_setup_service.get_diagnostic_trace(
                session.run_id
            )
            central_trace = [
                {
                    "timestamp": event.timestamp,
                    "run_id": session.run_id,
                    "level": "ERROR" if event.status in {"failed", "blocked"} else "INFO",
                    "component": "Workflow",
                    "event": event.event_type,
                    "action": event.phase,
                    "status": event.status,
                    "result_summary": event.summary,
                    "metadata": {"source": event.source, **event.details},
                }
                for event in central_events
            ]
            if central_events:
                latest = central_events[-1]
                current_activity = {
                    "stage": latest.phase,
                    "actor": latest.details.get("actor", ""),
                    "runtime_state": latest.details.get(
                        "runtime_state", latest.status
                    ),
                    "summary": latest.summary,
                }
        except Exception:
            central_trace = []
            current_activity = None
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
        "central_trace": central_trace,
        "current_activity": current_activity,
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
    try:
        path = _resolved_existing_directory(req.project_path)
    except (ValueError, FileNotFoundError, NotADirectoryError) as error:
        return JSONResponse(
            content={"error": str(error)},
            status_code=400,
        )

    try:
        # Use xdg-open to open the directory in the Linux file manager.
        # Never use shell=True.
        subprocess.run(["xdg-open", "--", str(path)], check=False)
    except Exception:
        return JSONResponse(
            content={"error": "Failed to open the project directory."},
            status_code=500,
        )

    return {"status": "opened", "project_path": str(path)}


@app.post("/api/project/validate")
async def validate_project_directory(req: ValidateProjectRequest):
    try:
        path = _resolved_existing_directory(req.project_path)
    except (ValueError, FileNotFoundError, NotADirectoryError) as error:
        return JSONResponse(
            content={"valid": False, "error": str(error)}, status_code=400,
        )
    return {"valid": True, "project_path": str(path), "intent": "existing"}


@app.post("/api/project/select-directory")
async def select_project_directory(
    selector: LocalDirectorySelector = Depends(get_directory_selector),
):
    try:
        selected = selector.select()
        if selected is None:
            return JSONResponse(content={"status": "cancelled"}, status_code=409)
        path = _resolved_existing_directory(selected)
    except (ValueError, FileNotFoundError, NotADirectoryError) as error:
        return JSONResponse(content={"error": str(error)}, status_code=400)
    except (OSError, subprocess.SubprocessError):
        return JSONResponse(
            content={"error": "Server-side directory selection is unavailable."},
            status_code=503,
        )
    return {"status": "selected", "project_path": str(path)}
