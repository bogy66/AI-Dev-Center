import json
from pathlib import Path
from datetime import datetime


class ApprovalManager:
    def __init__(self, storage="workflow_state.json"):
        self.storage = Path(storage)

    def create_approval(self):
        state = self.load_state()
        state["user_approval"] = {
            "status": "waiting",
            "approved_by": None,
            "approved_at": None,
            "comment": None
        }
        self.save_state(state)

    def approve(self, approved_by="Udo", comment=None):
        state = self.load_state()
        state["user_approval"] = {
            "status": "approved",
            "approved_by": approved_by,
            "approved_at": datetime.now().isoformat(),
            "comment": comment
        }
        self.save_state(state)

    def reject(self, approved_by="Udo", comment=None):
        state = self.load_state()
        state["user_approval"] = {
            "status": "rejected",
            "approved_by": approved_by,
            "approved_at": datetime.now().isoformat(),
            "comment": comment
        }
        self.save_state(state)

    def get_status(self):
        state = self.load_state()
        return state.get("user_approval", {})

    def load_state(self):
        if not self.storage.exists():
            return {}
        return json.loads(self.storage.read_text(encoding="utf-8"))

    def save_state(self, state):
        self.storage.write_text(
            json.dumps(state, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
