import json
import os
import tempfile
from pathlib import Path
from datetime import datetime

from app.logger import get_logger
from app.state_lock import get_state_lock


logger = get_logger("workflow_manager")


_UNSET = object()


class WorkflowManager:

    def __init__(self, storage="workflow_state.json"):
        self.storage = Path(storage)
        self._lock = get_state_lock(self.storage)

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

    def _merge_with_defaults(self, default, state):
        if not isinstance(state, dict):
            return default

        merged = dict(default)

        for key, value in state.items():
            if (
                key in merged
                and isinstance(merged[key], dict)
                and isinstance(value, dict)
            ):
                merged[key] = self._merge_with_defaults(
                    merged[key],
                    value
                )
            else:
                merged[key] = value

        return merged

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

        try:
            raw = self.storage.read_text(encoding="utf-8")
            state = json.loads(raw)

        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as error:
            logger.error(
                f"Failed to load workflow state from {self.storage}: "
                f"{error}. Falling back to default state."
            )
            return self._default_state(status="not_started")

        if not isinstance(state, dict):
            logger.error(
                f"Workflow state in {self.storage} is not a JSON "
                "object. Falling back to default state."
            )
            return self._default_state(status="not_started")

        return self._merge_with_defaults(
            self._default_state(),
            state
        )

    def save(self, state):
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

    def update_agent(self, agent, status, commit=_UNSET, result=_UNSET):
        with self._lock:
            state = self.load()

            state[agent]["status"] = status

            if commit is not _UNSET:
                state[agent]["commit"] = commit

            if result is not _UNSET:
                state[agent]["result"] = result

            self.save(state)

            return state
