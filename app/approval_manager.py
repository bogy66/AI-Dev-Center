import json
import os
import tempfile
from pathlib import Path
from datetime import datetime

from app.logger import get_logger
from app.state_lock import get_state_lock


logger = get_logger("approval_manager")


class ApprovalManager:
    def __init__(self, storage="workflow_state.json"):
        self.storage = Path(storage)
        self._lock = get_state_lock(self.storage)

    def create_approval(self):
        with self._lock:
            state = self.load_state()
            state["user_approval"] = {
                "status": "waiting",
                "approved_by": None,
                "approved_at": None,
                "comment": None
            }
            self.save_state(state)

    def approve(self, approved_by="Udo", comment=None):
        with self._lock:
            state = self.load_state()
            state["user_approval"] = {
                "status": "approved",
                "approved_by": approved_by,
                "approved_at": datetime.now().isoformat(),
                "comment": comment
            }
            self.save_state(state)

    def reject(self, approved_by="Udo", comment=None):
        with self._lock:
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
        return state.get(
            "user_approval",
            {
                "status": "not_started",
                "approved_by": None,
                "approved_at": None,
                "comment": None
            }
        )

    def load_state(self):
        if not self.storage.exists():
            return {}

        try:
            raw = self.storage.read_text(encoding="utf-8")
            state = json.loads(raw)

        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as error:
            logger.error(
                f"Failed to load approval state from {self.storage}: "
                f"{error}. Falling back to empty state."
            )
            return {}

        if not isinstance(state, dict):
            logger.error(
                f"Approval state in {self.storage} is not a JSON "
                "object. Falling back to empty state."
            )
            return {}

        return state

    def save_state(self, state):
        data = json.dumps(state, indent=2, ensure_ascii=False)

        directory = str(self.storage.parent)

        fd, tmp_name = tempfile.mkstemp(
            dir=directory,
            prefix=f".{self.storage.name}.",
            suffix=".tmp"
        )

        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())

            os.replace(tmp_name, self.storage)

        except Exception:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
            raise
