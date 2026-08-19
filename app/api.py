from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.responses import HTMLResponse
from pathlib import Path

from app.agent_orchestrator import AgentOrchestrator
from app.agent_manager import AgentManager
from app.agent_executor import AgentExecutor
from app.approval_manager import ApprovalManager



app = FastAPI(
    title="AI Dev Center"
)


orchestrator = AgentOrchestrator(
    AgentManager(),
    AgentExecutor()
)


class Task(BaseModel):
    project: str
    task: str


approval_manager = ApprovalManager()

# Ensure the approval state is initialized
if not approval_manager.get_status():
    approval_manager.create_approval()


@app.get("/approval")
def get_approval_status():
    return approval_manager.get_status()


@app.post("/approval/approve")
def approve_approval(approved_by: str = "Udo", comment: str = None):
    approval_manager.approve(approved_by=approved_by, comment=comment)
    return approval_manager.get_status()


@app.post("/approval/reject")
def reject_approval(approved_by: str = "Udo", comment: str = None):
    approval_manager.reject(approved_by=approved_by, comment=comment)
    return approval_manager.get_status()

def home():
    return {
        "name": "AI Dev Center",
        "status": "running"
    }



@app.get("/gui", response_class=HTMLResponse)
def gui():

    return (
        Path("app/gui/index.html")
        .read_text(
            encoding="utf-8"
        )
    )



@app.post("/run")
def run(task: Task):

    result = orchestrator.run(
        task.project,
        task.task
    )

    return result
