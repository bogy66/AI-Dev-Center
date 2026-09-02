import json
import os
import tempfile
from hashlib import sha256
from pathlib import Path
from datetime import datetime, timezone

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
            "capability_approvals": {},
            "missing_toolchain_setups": {},
            "execution_lifecycles": {},
            "communication_requests": {},
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

    def create_capability_approval(
        self, request_id, project_id, project_intelligence_ref,
        council_result_id, chairman_variant_id, capability,
        executable_names, allowed_operations, project_scope,
    ):
        """Persist a separate pending Human Approval for one capability request."""
        with self._lock:
            state = self.load()
            approvals = state.setdefault("capability_approvals", {})
            record = approvals.get(request_id)
            if record is None:
                record = {
                    "id": request_id,
                    "status": "pending",
                    "project_id": project_id,
                    "project_intelligence_ref": project_intelligence_ref,
                    "council_result_id": council_result_id,
                    "chairman_variant_id": chairman_variant_id,
                    "capability": capability,
                    "executable_names": list(executable_names),
                    "allowed_operations": list(allowed_operations),
                    "project_scope": project_scope,
                    "approved_by": None,
                    "approved_at": None,
                    "comment": None,
                }
                approvals[request_id] = record
                self.save(state)
            return dict(record)

    def decide_capability_approval(self, request_id, decision, approved_by=None, comment=None):
        """Apply an explicit terminal Human Approval to a capability request."""
        if decision not in {"approved", "rejected"}:
            raise ValueError("Capability approval decision must be approved or rejected")
        with self._lock:
            state = self.load()
            record = state.get("capability_approvals", {}).get(request_id)
            if record is None:
                raise ValueError("Capability approval request is missing")
            current = record.get("status")
            if current == decision:
                return dict(record)
            if current != "pending":
                raise ValueError(f"Cannot change capability approval from {current!r} to {decision!r}")
            record.update({
                "status": decision,
                "approved_by": approved_by,
                "approved_at": datetime.now(timezone.utc).isoformat(),
                "comment": comment,
            })
            self.save(state)
            return dict(record)

    def get_capability_approval(self, request_id):
        record = self.load().get("capability_approvals", {}).get(request_id)
        return dict(record) if isinstance(record, dict) else None

    def create_missing_toolchain_setup(self, plan_id, record):
        with self._lock:
            state = self.load()
            setups = state.setdefault("missing_toolchain_setups", {})
            current = setups.get(plan_id)
            if current is None:
                setups[plan_id] = dict(record)
                self.save(state)
                current = setups[plan_id]
            return dict(current)

    def decide_missing_toolchain_setup(
        self, plan_id, decision, approved_plan, approved_by=None, comment=None,
    ):
        if decision not in {"approved", "rejected"}:
            raise ValueError("Setup decision must be approved or rejected")
        with self._lock:
            state = self.load()
            record = state.get("missing_toolchain_setups", {}).get(plan_id)
            if record is None or record.get("status") != "pending_approval":
                raise ValueError("No pending missing-toolchain setup exists")
            record["status"] = decision
            record["setup_plan"] = approved_plan
            record["approved_by"] = approved_by
            record["approved_at"] = datetime.now(timezone.utc).isoformat()
            record["comment"] = comment
            self.save(state)
            return dict(record)

    def get_missing_toolchain_setup(self, plan_id):
        record = self.load().get("missing_toolchain_setups", {}).get(plan_id)
        return dict(record) if isinstance(record, dict) else None

    def update_missing_toolchain_setup(self, plan_id, **updates):
        with self._lock:
            state = self.load()
            record = state.get("missing_toolchain_setups", {}).get(plan_id)
            if record is None:
                raise ValueError("Missing-toolchain setup does not exist")
            record.update(updates)
            self.save(state)
            return dict(record)

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

    @staticmethod
    def _execution_record(state, run_id, stage):
        return state.setdefault("execution_lifecycles", {}).setdefault(run_id, {}).get(stage)

    def get_execution_state(self, run_id, stage="development"):
        """Read one lifecycle without mutating persistent state."""
        state = self.load()
        record = state.get("execution_lifecycles", {}).get(run_id, {}).get(stage)
        return dict(record) if isinstance(record, dict) else {
            "run_id": run_id, "stage": stage, "status": "not_started"
        }

    def begin_execution(self, run_id, stage, project_root, owner_id, metadata=None):
        from app.canonical_execution import ExecutionReentryError, RecoveryRequiredError
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            state = self.load()
            stages = state.setdefault("execution_lifecycles", {}).setdefault(run_id, {})
            record = stages.get(stage)
            if isinstance(record, dict):
                if record.get("status") == "started":
                    record.update({"status": "recovery_required", "interrupted_at": now})
                    self.save(state)
                    raise RecoveryRequiredError(
                        f"{stage} execution was previously started and requires recovery"
                    )
                raise ExecutionReentryError(
                    f"{stage} execution is already {record.get('status', 'recorded')}"
                )
            record = {
                "run_id": run_id, "stage": stage, "status": "started",
                "project_root": str(Path(project_root).resolve(strict=False)),
                "owner_id": owner_id, "started_at": now,
            }
            if isinstance(metadata, dict):
                record["metadata"] = dict(metadata)
            stages[stage] = record
            self.save(state)
            return dict(record)

    def finish_execution(self, run_id, stage, owner_id, status, error_type=None):
        if status not in {"completed", "failed"}:
            raise ValueError("execution terminal status must be completed or failed")
        with self._lock:
            state = self.load()
            record = self._execution_record(state, run_id, stage)
            if not isinstance(record, dict) or record.get("status") != "started":
                raise ValueError("execution is not started")
            if record.get("owner_id") != owner_id:
                raise ValueError("execution owner does not match")
            record["status"] = status
            record["finished_at"] = datetime.now(timezone.utc).isoformat()
            if error_type:
                record["error_type"] = str(error_type)[:100]
            self.save(state)
            return dict(record)

    def complete_development_execution(self, run_id, owner_id, development_status):
        """Atomically complete mutation and open Final Approval when eligible."""
        from app.final_approval import result_from_record
        with self._lock:
            state = self.load()
            record = self._execution_record(state, run_id, "development")
            if not isinstance(record, dict) or record.get("status") != "started":
                raise ValueError("development execution is not started")
            if record.get("owner_id") != owner_id:
                raise ValueError("execution owner does not match")
            approval_record = None
            if development_status == "accepted":
                approvals = state.setdefault("final_approvals", {})
                approval_record = approvals.get(run_id)
                if approval_record is None:
                    approval_record = {
                        "status": "pending", "development_status": "accepted",
                        "approved_by": None, "approved_at": None, "comment": None,
                    }
                    approvals[run_id] = approval_record
            record.update({
                "status": "completed",
                "finished_at": datetime.now(timezone.utc).isoformat(),
            })
            self.save(state)
            return result_from_record(run_id, approval_record) if approval_record else None

    def require_recovery(self, run_id, stage):
        with self._lock:
            state = self.load()
            record = self._execution_record(state, run_id, stage)
            if not isinstance(record, dict):
                return None
            if record.get("status") == "started":
                record["status"] = "recovery_required"
                record["interrupted_at"] = datetime.now(timezone.utc).isoformat()
                self.save(state)
            return dict(record)

    def complete_recovered_execution(self, run_id, stage, owner_id):
        with self._lock:
            state = self.load()
            record = self._execution_record(state, run_id, stage)
            if not isinstance(record, dict) or record.get("status") not in {"started", "recovery_required"}:
                raise ValueError("execution is not recoverable")
            record.update({
                "status": "completed", "owner_id": owner_id,
                "recovered": True,
                "finished_at": datetime.now(timezone.utc).isoformat(),
            })
            self.save(state)
            return dict(record)

    def resume_publish_execution(self, run_id, owner_id):
        """Reclaim only the idempotently verifiable Controlled Publish stage."""
        with self._lock:
            state = self.load()
            record = self._execution_record(state, run_id, "publish")
            if not isinstance(record, dict) or record.get("status") not in {"started", "recovery_required"}:
                raise ValueError("publish execution is not recoverable")
            record.update({
                "status": "started", "owner_id": owner_id,
                "recovery_attempted_at": datetime.now(timezone.utc).isoformat(),
            })
            self.save(state)
            return dict(record)

    def begin_communication_request(
        self, transport, message_id, sender_id, conversation_id, *, limit=1000,
    ):
        """Atomically claim one transport message without storing its content."""
        key = self._communication_request_key(
            transport, message_id, sender_id, conversation_id,
        )
        with self._lock:
            state = self.load()
            requests = state.setdefault("communication_requests", {})
            existing = requests.get(key)
            if existing is not None:
                if (
                    existing.get("sender_id") != sender_id
                    or existing.get("conversation_id") != conversation_id
                ):
                    raise ValueError("Transport message identity does not match")
                return False, dict(existing)
            while len(requests) >= limit:
                completed = [
                    item for item in requests.items()
                    if item[1].get("status") == "completed"
                ]
                if not completed:
                    raise ValueError("Communication request capacity is exhausted")
                oldest_key = min(
                    completed,
                    key=lambda item: item[1].get("received_at", ""),
                )[0]
                del requests[oldest_key]
            record = {
                "transport": transport,
                "message_id": message_id,
                "sender_id": sender_id,
                "conversation_id": conversation_id,
                "status": "processing",
                "received_at": datetime.now(timezone.utc).isoformat(),
            }
            requests[key] = record
            self.save(state)
            return True, dict(record)

    def complete_communication_request(
        self, transport, message_id, sender_id, conversation_id, response,
    ):
        """Persist a safe adapter response for deterministic redelivery."""
        key = self._communication_request_key(
            transport, message_id, sender_id, conversation_id,
        )
        with self._lock:
            state = self.load()
            record = state.setdefault("communication_requests", {}).get(key)
            if record is None or record.get("status") != "processing":
                raise ValueError("Communication request is not processing")
            record.update({
                "status": "completed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "response": dict(response),
            })
            self.save(state)
            return dict(record)

    @staticmethod
    def _communication_request_key(transport, message_id, sender_id, conversation_id):
        identity = "\0".join((transport, sender_id, conversation_id, message_id))
        return f"{transport}:{sha256(identity.encode('utf-8')).hexdigest()}"
