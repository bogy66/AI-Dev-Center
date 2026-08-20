from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from app.agent_executor import AgentExecutor
from app.agent_manager import AgentManager
from app.agent_orchestrator import AgentOrchestrator
from app.approval_manager import ApprovalManager
from app.git_manager import GitManager
from app.workflow_manager import WorkflowManager
from app.workflow_publisher import WorkflowPublisher


app = FastAPI(
    title="AI Dev Center"
)


# Technical workflow failure statuses that should return HTTP 500
TECHNICAL_FAILURE_STATUSES = {
    "development_failed",
    "tester_failed",
    "review_failed",
    "rework_failed",
}


class WorkflowFailureException(HTTPException):
    """Custom exception that returns workflow state as response body."""
    def __init__(self, workflow_state):
        super().__init__(status_code=500, detail=workflow_state)
        self.workflow_state = workflow_state


@app.exception_handler(WorkflowFailureException)
async def workflow_failure_exception_handler(request, exc: WorkflowFailureException):
    return JSONResponse(
        status_code=500,
        content=exc.workflow_state
    )


# Gemeinsamer Workflow-State
workflow_manager = WorkflowManager()


# Orchestrator
orchestrator = AgentOrchestrator(
    AgentManager(),
    AgentExecutor(),
    workflow_manager
)


# Approval
approval_manager = ApprovalManager(
    storage=workflow_manager.storage
)


# Publisher
workflow_publisher = WorkflowPublisher(
    workflow_manager,
    GitManager()
)


class Task(BaseModel):
    project: str
    task: str


class ApprovalRequest(BaseModel):
    approved_by: str = "Udo"
    comment: str | None = None


class PublishRequest(BaseModel):
    project: str


@app.get("/approval")
def get_approval_status():
    return approval_manager.get_status()


@app.post("/approval/approve")
def approve_approval(request: ApprovalRequest):
    approval_manager.approve(
        approved_by=request.approved_by,
        comment=request.comment
    )

    return approval_manager.get_status()


@app.post("/approval/reject")
def reject_approval(request: ApprovalRequest):
    approval_manager.reject(
        approved_by=request.approved_by,
        comment=request.comment
    )

    return approval_manager.get_status()


@app.get("/workflow")
def get_workflow_status():
    # Neue Instanz pro Request, damit Tests WorkflowManager patchen können.
    return WorkflowManager().load()


@app.post("/workflow/run")
def run_workflow(task: Task):
    result = orchestrator.run_workflow(
        task.project,
        task.task
    )
    
    status = result.get("status", "")
    if status in TECHNICAL_FAILURE_STATUSES:
        raise WorkflowFailureException(result)
    
    return result


@app.post("/workflow/rework")
def rework_workflow(request: PublishRequest):
    result = orchestrator.rework_workflow(
        request.project
    )
    
    status = result.get("status", "")
    if status in TECHNICAL_FAILURE_STATUSES:
        raise WorkflowFailureException(result)
    
    return result


@app.post("/workflow/publish")
def publish_workflow(request: PublishRequest):
    return workflow_publisher.publish(
        request.project
    )


@app.get("/gui", response_class=HTMLResponse)
def gui():
    return Path(
        "app/gui/index.html"
    ).read_text(
        encoding="utf-8"
    )


@app.post("/run")
def run(task: Task):
    return orchestrator.run(
        task.project,
        task.task
    )


def home():
    return {
        "name": "AI Dev Center",
        "status": "running"
    }
