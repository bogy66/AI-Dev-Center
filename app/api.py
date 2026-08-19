from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.responses import HTMLResponse
from pathlib import Path

from app.agent_orchestrator import AgentOrchestrator
from app.agent_manager import AgentManager
from app.agent_executor import AgentExecutor


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



@app.get("/")
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
