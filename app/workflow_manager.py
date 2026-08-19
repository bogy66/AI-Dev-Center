import json
from pathlib import Path
from datetime import datetime


class WorkflowManager:


    def __init__(
        self,
        storage="workflow_state.json"
    ):

        self.storage = Path(storage)


    def create(
        self,
        task,
        branch
    ):

        state = {

            "task": task,

            "branch": branch,

            "status": "started",

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

            "user_approval": False,

            "created": str(datetime.now())

        }


        self.save(state)

        return state



    def load(self):

        if not self.storage.exists():
            return None


        return json.loads(
            self.storage.read_text(
                encoding="utf-8"
            )
        )



    def save(
        self,
        state
    ):

        self.storage.write_text(
            json.dumps(
                state,
                indent=2,
                ensure_ascii=False
            ),
            encoding="utf-8"
        )



    def update_agent(
        self,
        agent,
        status,
        commit=None,
        result=None
    ):

        state = self.load()


        state[agent]["status"] = status


        if commit:
            state[agent]["commit"] = commit


        if result:
            state[agent]["result"] = result


        self.save(state)

        return state
