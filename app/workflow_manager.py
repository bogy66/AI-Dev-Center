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
            },
            "final_approvals": {},
            "change_provenance": {},
            "git_commit_results": {},
            "publish_approvals": {},
            "publish_results": {},
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

    def create_final_approval(self, run_id, development_status):
        """Persist a pending final approval only for an accepted run."""
        from app.final_approval import FinalApprovalError, result_from_record

        if development_status != "accepted":
            raise FinalApprovalError("Final approval requires an accepted development run")
        with self._lock:
            state = self.load()
            approvals = state.setdefault("final_approvals", {})
            record = approvals.get(run_id)
            if record is None:
                record = {
                    "status": "pending",
                    "development_status": "accepted",
                    "approved_by": None,
                    "approved_at": None,
                    "comment": None,
                }
                approvals[run_id] = record
                self.save(state)
            return result_from_record(run_id, record)

    def decide_final_approval(self, run_id, decision, approved_by=None, comment=None):
        """Apply one explicit, fail-safe final human approval transition."""
        from app.final_approval import FinalApprovalError, result_from_record

        if decision not in {"approved", "rejected"}:
            raise FinalApprovalError("Final approval decision must be approved or rejected")
        with self._lock:
            state = self.load()
            record = state.get("final_approvals", {}).get(run_id)
            if record is None or record.get("development_status") != "accepted":
                raise FinalApprovalError("No accepted development run is awaiting final approval")
            current = record.get("status")
            if current == decision:
                return result_from_record(run_id, record)
            if current != "pending":
                raise FinalApprovalError(
                    f"Cannot change final approval from {current!r} to {decision!r}"
                )
            record.update({
                "status": decision,
                "approved_by": approved_by,
                "approved_at": str(datetime.now()),
                "comment": comment,
            })
            self.save(state)
            return result_from_record(run_id, record)

    def capture_provenance_baseline(self, run_id, project_root, path, phase, baseline):
        with self._lock:
            state = self.load()
            entries = state.setdefault("change_provenance", {}).setdefault(run_id, {})
            entries.setdefault(path, {"project_root": project_root, "baseline": {**baseline, "phase": phase}, "events": []})
            self.save(state)

    def record_provenance_event(self, run_id, path, event):
        with self._lock:
            state = self.load()
            entry = state.setdefault("change_provenance", {}).setdefault(run_id, {}).get(path)
            if entry is None:
                raise ValueError("Provenance baseline is missing")
            entry["events"].append(event)
            self.save(state)

    def git_stage_transaction(self):
        """Expose the canonical state lock for one application-level Git transaction."""
        return self._lock

    def persist_git_commit_result(self, state, run_id, result):
        state.setdefault("git_commit_results", {})[run_id] = result
        self.save(state)

    def create_publish_approval(self, run_id):
        """Create pending approval only from this run's committed Git result."""
        from app.publish_approval import PublishApprovalError, result_from_record

        with self._lock:
            state = self.load()
            commit = state.get("git_commit_results", {}).get(run_id)
            if not commit or commit.get("status") != "committed" or not commit.get("commit_hash"):
                raise PublishApprovalError("Publish approval requires a committed run")
            approvals = state.setdefault("publish_approvals", {})
            record = approvals.get(run_id)
            if record is None:
                record = {
                    "status": "pending",
                    "ready_for_publish": True,
                    "approved_by": None,
                    "approved_at": None,
                    "comment": None,
                }
                approvals[run_id] = record
                self.save(state)
            return result_from_record(run_id, record)

    def decide_publish_approval(self, run_id, decision, approved_by=None, comment=None):
        """Apply one explicit, terminal publish approval decision."""
        from app.publish_approval import PublishApprovalError, result_from_record

        if decision not in {"approved", "rejected"}:
            raise PublishApprovalError("Publish approval decision must be approved or rejected")
        with self._lock:
            state = self.load()
            record = state.get("publish_approvals", {}).get(run_id)
            commit = state.get("git_commit_results", {}).get(run_id)
            if record is None or not commit or commit.get("status") != "committed":
                raise PublishApprovalError("No committed run is awaiting publish approval")
            current = record.get("status")
            if current == decision:
                return result_from_record(run_id, record)
            if current != "pending":
                raise PublishApprovalError(
                    f"Cannot change publish approval from {current!r} to {decision!r}"
                )
            record.update({
                "status": decision,
                "approved_by": approved_by,
                "approved_at": str(datetime.now()),
                "comment": comment,
            })
            self.save(state)
            return result_from_record(run_id, record)

    def persist_publish_result(self, state, run_id, result):
        state.setdefault("publish_results", {})[run_id] = result
        self.save(state)
