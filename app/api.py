"""Compatibility HTTP adapter routed exclusively to the canonical workflow."""
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from app.canonical_composition import build_canonical_components
from app.workflow_manager import WorkflowManager


app = FastAPI(title="AI Dev Center")


def get_canonical_components():
    return build_canonical_components()


class Task(BaseModel):
    project: str
    task: str


class ApprovalRequest(BaseModel):
    approved_by: str = "Udo"
    comment: str | None = None


class PublishRequest(BaseModel):
    project: str


def _deprecated(action):
    return JSONResponse(status_code=409, content={
        "status": "deprecated_unsafe_contract",
        "error": f"{action} requires the canonical run/plan-specific approval endpoint",
    })


@app.get("/approval")
def get_approval_status():
    return _deprecated("approval status")


@app.post("/approval/approve")
def approve_approval(request: ApprovalRequest):
    return _deprecated("setup approval")


@app.post("/approval/reject")
def reject_approval(request: ApprovalRequest):
    return _deprecated("setup rejection")


@app.get("/workflow")
def get_workflow_status():
    return WorkflowManager().load()


@app.post("/workflow/run")
def run_workflow(task: Task):
    project_path = Path(task.project).expanduser().resolve(strict=False)
    components = get_canonical_components()
    run_id = str(uuid4())
    result = components.service.plan_project_setup(
        project_path.name, project_path, run_id=run_id,
    )
    components.plan_store.save(result.setup_plan)
    return {
        "status": result.setup_plan.status, "project_id": project_path.name,
        "plan_id": result.setup_plan.id, "run_id": run_id,
    }


@app.post("/workflow/rework")
def rework_workflow(request: PublishRequest):
    return _deprecated("free-standing rework")


@app.post("/workflow/publish")
def publish_workflow(request: PublishRequest):
    return _deprecated("publish")


@app.get("/gui", response_class=HTMLResponse)
def gui():
    return Path("app/gui/index.html").read_text(encoding="utf-8")


@app.post("/run")
def run(task: Task):
    return run_workflow(task)


def home():
    return {"name": "AI Dev Center", "status": "running"}
