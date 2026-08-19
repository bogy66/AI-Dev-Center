from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
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


orchestrator = AgentOrchestrator(
    AgentManager(),
    AgentExecutor()
)


approval_manager = ApprovalManager()

workflow_publisher = WorkflowPublisher(
    WorkflowManager(),
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


# Ensure the approval state is initialized
if not approval_manager.get_status():
    approval_manager.create_approval()


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
