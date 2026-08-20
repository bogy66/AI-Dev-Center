import json
from pathlib import Path
from datetime import datetime


_UNSET = object()


class WorkflowManager:

    def __init__(self, storage="workflow_state.json"):
        self.storage = Path(storage)

    def _default_state(self, status="not_started", task=None, branch=None):
        return {
            "task": task,
            "branch": branch,
            "status": status,
            "developer": {
                "status": "pending",
                "commit": None
            },
            "tester": {
                "status": "pending",
                "commit": None,
                "result": None
            },
            "reviewer": {
                "status": "pending",
                "result": None
            },
            "user_approval": {
                "status": "waiting",
                "approved_by": None,
                "approved_at": None,
                "comment": None
            }
        }

    def create(self, task, branch):
        state = self._default_state(
            status="started",
            task=task,
            branch=branch
        )

        state["created"] = str(datetime.now())

        self.save(state)

        return state

    def load(self):
        if not self.storage.exists():
            return self._default_state(status="not_started")

        return json.loads(
            self.storage.read_text(encoding="utf-8")
        )

    def save(self, state):
        self.storage.write_text(
            json.dumps(state, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    def update_agent(self, agent, status, commit=_UNSET, result=_UNSET):
        state = self.load()

        state[agent]["status"] = status

        if commit is not _UNSET:
            state[agent]["commit"] = commit

        if result is not _UNSET:
            state[agent]["result"] = result

        self.save(state)

        return state
