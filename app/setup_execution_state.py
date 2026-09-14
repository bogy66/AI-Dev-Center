"""Generic, ecosystem-neutral persisted execution state for individual
controlled setup-mutation attempts (CLAUDE-E2E-003H).

This closes the retry/restart safety gap CLAUDE-E2E-003G exposed:
DevelopmentWorkflow.execute_approved() previously had no memory at all
of whether a given SetupStep had already been executed, so calling it
again for the same approved plan (same-process retry, or after a fresh
process/store reconstruction) would launch the underlying mutating
operation again -- harmless for an idempotent pip install, but not a
safe generic ADC execution model for arbitrary controlled mutations.

Deliberately NOT stored in WorkflowManager's own workflow_state.json:
WorkflowManager.load() intentionally treats a corrupt/unparseable state
file as "not_started" for its own, already broadly-relied-upon
purposes (run-level development/git/publish lifecycle) -- exactly the
opposite of the fail-closed guarantee this narrower, safety-relevant
state requires ("a corrupt execution-state record must not be
interpreted as NOT_STARTED"). This is not a second, competing source
of truth for anything WorkflowManager already owns; it is a genuinely
new responsibility with stricter safety needs, using the same safe
atomic-write pattern (temp file + fsync + os.replace) WorkflowManager
already established.

No claim of generic "exactly once" execution across arbitrary process
crashes is made or implied anywhere in this module: if ADC crashes
after launching the real mutating process but before persisting a
terminal result, the persisted record stays IN_PROGRESS, and a later
attempt to resume is refused (recovery-required) rather than guessed
at in either direction.

CLAUDE-E2E-003I: claim_or_report() additionally serializes the whole
check-and-claim decision across genuinely separate OS processes using a
real advisory file lock (fcntl.flock), not just the in-process
threading.RLock get_state_lock() provides. The lock is a pure
concurrency mechanism, scoped to exactly one (project, generation,
step) identity; it never decides replay/recovery safety by itself and
disappearing (e.g. because the process that held it died) never implies
the mutation did not happen -- the persisted execution-state record
remains the sole authority for that question, exactly as before.

CLAUDE-E2E-003I-A -- REQ-S3-GENERATION-CONTENT-IMMUTABILITY:
"Execution-relevant content of an approved SetupStep must not change
within the same setup generation. Any such mismatch invalidates replay
identity and must fail closed until a new setup generation is
materialized and approved." An independent review of CLAUDE-E2E-003I
found, and this module now closes, two real defects that violated this
requirement in different ways:
  1. get()/begin() previously treated a content mismatch under the SAME
     (project, generation, step) key as equivalent to "never attempted"
     -- silently permitting a fresh begin() (and therefore a fresh real
     mutation launch) for materially different content under an
     approval that was never actually granted for that content. Fixed:
     both now fail closed (SetupExecutionStateError) on any content
     mismatch found under a matching (project, generation, step) key,
     never silently reinterpreting it as a new, freely-startable
     operation. A genuinely new/changed operation must be materialized
     under a NEW generation instead -- which by construction never
     shares this exact key with the old one.
  2. A real CLAUDE-E2E-003H-format execution-state record (keyed by the
     raw plan.id, before the "legacy-" generation-identity prefix
     existed) became invisible to CLAUDE-E2E-003I's generation-based
     lookup for a legacy plan, because the resolved legacy generation
     identity ("legacy-{plan.id}") never matches that older, unprefixed
     key. Fixed via _find_raw_record()'s read-only compatibility
     lookup: no physical migration, no write, hence no new
     cross-process race surface and trivially idempotent.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.logger import get_logger
from app.state_lock import get_state_lock

logger = get_logger("setup_execution_state")

NOT_STARTED = "not_started"
IN_PROGRESS = "in_progress"
SUCCEEDED = "succeeded"
FAILED = "failed"
RECOVERY_REQUIRED = "recovery_required"

VALID_STATUSES = frozenset({NOT_STARTED, IN_PROGRESS, SUCCEEDED, FAILED, RECOVERY_REQUIRED})


class SetupExecutionStateError(Exception):
    """Raised whenever persisted setup-execution state cannot be safely
    interpreted or a transition is illegal. Always fails closed: never
    caught internally to silently fall back to NOT_STARTED or to a
    fresh execution attempt."""


def setup_step_content_snapshot(step) -> tuple:
    """A deterministic, generic content fingerprint of a SetupStep's
    own execution-relevant fields. Every field named here already
    exists on the central, ecosystem-neutral SetupStep model itself --
    nothing pip/Python/toolchain-specific is introduced. Used so a
    step whose content changed under the same (project, plan, step_id)
    can never silently inherit a prior SUCCEEDED/FAILED record."""
    return (
        step.action, step.setup_effect, step.install_method,
        step.package, step.version, step.command, step.target_executable,
    )


@dataclass(frozen=True)
class SetupStepIdentity:
    """The stable, generic identity a persisted execution-state record
    is bound to: project + setup generation + step, qualified by a
    content fingerprint (CLAUDE-E2E-003I).

    generation_id (SetupPlan.generation_id) -- not the stable,
    per-project plan.id -- is deliberately what scopes this identity:
    plan.id alone is insufficient, since replanning the same project
    reuses the same plan.id indefinitely, while generation_id changes
    on every genuinely new materialization. This is what lets a later,
    legitimate new setup generation (e.g. after an externally-detected
    environment regression) execute again even though an earlier
    generation for the very same logical step already SUCCEEDED --
    without ever letting a stale/old generation's approval authorize
    anything for a new one.

    step.id is already SetupPlan/ToolchainMaterializer's own stable,
    persistent identity for a step (derived deterministically from its
    requirement) -- this does not introduce a second, competing step
    identity, only scopes it to a project+generation and binds it to
    the step's own current content.
    """
    project_key: str
    generation_id: str
    step_id: str
    content: tuple

    @classmethod
    def for_step(cls, project_root, generation_id: str, step) -> "SetupStepIdentity":
        from app.canonical_execution import project_key as resolve_project_key
        return cls(
            project_key=resolve_project_key(project_root),
            generation_id=generation_id, step_id=step.id,
            content=setup_step_content_snapshot(step),
        )


class SetupExecutionStateStore:
    """Generic, project/plan/step-scoped persisted state for controlled
    mutating setup-step execution attempts, restart-safe by design."""

    def __init__(self, storage="setup_execution_state.json"):
        self.storage = Path(storage)
        self._lock = get_state_lock(self.storage)

    def _load_raw(self) -> dict:
        if not self.storage.exists():
            return {}
        try:
            raw = self.storage.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SetupExecutionStateError(
                f"Setup execution state file {self.storage} is corrupt "
                f"or unreadable; refusing to treat this as not_started: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise SetupExecutionStateError(
                f"Setup execution state file {self.storage} does not "
                "contain a JSON object; refusing to treat this as not_started."
            )
        return data

    def _save_raw(self, data: dict) -> None:
        payload = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True)
        directory = str(self.storage.parent) or "."
        Path(directory).mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=directory, prefix=f".{self.storage.name}.", suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.storage)
        except Exception:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
            raise

    _LEGACY_GENERATION_PREFIX = "legacy-"

    def _find_raw_record(self, data: dict, identity: SetupStepIdentity):
        """Locate the raw persisted record dict for this identity, if
        any, INCLUDING the CLAUDE-E2E-003I-A read-only legacy
        compatibility lookup: a plan persisted before generation_id
        existed (003E-003H) resolves (via WorkflowPlanStore) to a
        generation of the deterministic shape "legacy-{plan.id}" --
        but any execution-state record a genuinely pre-003I ADC process
        already wrote for that same plan was keyed by the RAW plan.id
        itself (that 003H format predates the "legacy-" prefix concept
        entirely). Without this compatibility check, such a real,
        already-SUCCEEDED record would silently become invisible (and
        therefore be re-interpreted as NOT_STARTED) purely because of
        the generation-identity naming change -- never because the
        underlying execution outcome actually changed.

        This lookup is pure read: it never writes, merges or migrates
        anything, so it is trivially idempotent and introduces no new
        cross-process race surface (CLAUDE-E2E-003I-A Part 8/11) -- any
        new begin()/finish() for a legacy plan is still written under
        its "legacy-{plan.id}" key going forward, and this same
        compatibility check will keep finding it there afterwards.
        """
        record = (
            data.get(identity.project_key, {})
            .get(identity.generation_id, {})
            .get(identity.step_id)
        )
        if record is not None:
            return record
        if identity.generation_id.startswith(self._LEGACY_GENERATION_PREFIX):
            raw_plan_id = identity.generation_id[len(self._LEGACY_GENERATION_PREFIX):]
            record = data.get(identity.project_key, {}).get(raw_plan_id, {}).get(identity.step_id)
        return record

    def get(self, identity: SetupStepIdentity) -> dict | None:
        """Return the persisted record for this exact (project,
        generation, step), or None when nothing matching is recorded
        at all -- genuinely never attempted (including via the legacy
        003H-format compatibility lookup, see _find_raw_record()).

        CLAUDE-E2E-003I-A: a record found under a MATCHING (project,
        generation, step) key but with DIFFERENT execution-relevant
        content is a same-generation content-immutability violation
        (REQ-S3-GENERATION-CONTENT-IMMUTABILITY, see module docstring)
        and fails closed with SetupExecutionStateError -- it is no
        longer silently treated as "not started" the way CLAUDE-E2E-003I
        originally (incorrectly) allowed. A genuinely different logical
        operation must be materialized under a NEW generation, which by
        construction never shares this (project, generation, step) key
        in the first place.

        Raises SetupExecutionStateError for a corrupt store or an
        unrecognized status -- never returns None for that case, which
        would be indistinguishable from not-started."""
        data = self._load_raw()
        record = self._find_raw_record(data, identity)
        if record is None:
            return None
        if not isinstance(record, dict) or record.get("status") not in VALID_STATUSES:
            raise SetupExecutionStateError(
                f"Corrupt or unrecognized setup execution state for "
                f"{(identity.project_key, identity.generation_id, identity.step_id)}: {record!r}"
            )
        if record.get("content") != list(identity.content):
            raise SetupExecutionStateError(
                f"Setup step '{identity.step_id}' (generation "
                f"'{identity.generation_id}') has a persisted record "
                "with different execution-relevant content than the "
                "one now being checked (REQ-S3-GENERATION-CONTENT-"
                "IMMUTABILITY). A changed step under the SAME generation "
                "is never automatically re-authorized or re-executed; "
                "a new materialization/generation and a new Human "
                "Approval are required."
            )
        return dict(record)

    def _lock_file_path(self, identity: SetupStepIdentity) -> Path:
        digest = hashlib.sha256(
            f"{identity.project_key}\x00{identity.generation_id}\x00{identity.step_id}".encode("utf-8")
        ).hexdigest()
        return self.storage.parent / f".{self.storage.name}.locks" / f"{digest}.lock"

    def claim_or_report(self, identity: SetupStepIdentity, owner_id: str):
        """Atomically decide, across genuinely separate OS processes,
        whether this exact (project, generation, step, content) identity
        may be claimed for execution right now (CLAUDE-E2E-003I Part 9).

        Holds a real OS-level advisory file lock (fcntl.flock, LOCK_EX)
        scoped to this exact identity for the full duration of the
        check-and-decide sequence -- not just the in-process
        threading.RLock get_state_lock() already provides internally
        for begin()/finish(). This is what makes "two real OS processes
        both observe NOT_STARTED and both claim it" impossible: only
        one process can hold this file lock at a time, so only one can
        ever transition a genuinely NOT_STARTED identity to IN_PROGRESS.

        Returns a ("claimed", record) tuple when this call itself just
        persisted a fresh IN_PROGRESS record (the caller must now
        actually execute and call finish()), or
        (existing["status"], existing) when a terminal (SUCCEEDED/
        FAILED) record already existed and this call claimed nothing.
        Raises SetupExecutionStateError (via begin()) when a matching
        IN_PROGRESS/RECOVERY_REQUIRED record already exists -- the
        lock's disappearance if that earlier holder's process died does
        NOT make this call assume the mutation is safe to repeat; the
        persisted state alone decides that.
        """
        lock_path = self._lock_file_path(identity)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "a+") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                existing = self.get(identity)
                if existing is not None and existing["status"] in (SUCCEEDED, FAILED):
                    return existing["status"], existing
                if existing is not None and existing["status"] in (IN_PROGRESS, RECOVERY_REQUIRED):
                    # Fail closed WITHOUT calling begin(): an active
                    # concurrent claim (a real, still-executing racing
                    # process, not necessarily a crashed one) must never
                    # be mutated/corrupted just because a second process
                    # also observed it here -- doing so would break the
                    # legitimate holder's own later finish() call. Only
                    # a genuinely fresh begin() (no existing record, or
                    # a different-content one) is safe to perform under
                    # this lock.
                    raise SetupExecutionStateError(
                        f"Setup step '{identity.step_id}' (generation "
                        f"'{identity.generation_id}') already has an "
                        f"unresolved execution attempt ({existing['status']}); "
                        "not automatically claimed or re-executed."
                    )
                record = self.begin(identity, owner_id)
                return "claimed", record
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def begin(self, identity: SetupStepIdentity, owner_id: str) -> dict:
        """Persist IN_PROGRESS before external mutation starts.

        Legal ONLY when no record exists at all for this (project,
        generation, step) -- including via the legacy 003H-format
        compatibility lookup (_find_raw_record()). CLAUDE-E2E-003I-A:
        an existing record for this exact (project, generation, step)
        key is NEVER silently overwritten merely because its content
        differs -- that was CLAUDE-E2E-003I's original, incorrect
        behavior. Changed execution-relevant content under the SAME
        generation fails closed (REQ-S3-GENERATION-CONTENT-IMMUTABILITY),
        exactly like a matching-content SUCCEEDED/FAILED record does.
        An existing IN_PROGRESS record -- regardless of content -- means
        a prior attempt's outcome is unknown, and this fails closed with
        SetupExecutionStateError (recovery-required) rather than
        starting a new one. Callers must call get() first to decide
        whether beginning a fresh attempt is appropriate at all (e.g.
        do not call begin() when get() already returned a matching
        SUCCEEDED/FAILED record).
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            data = self._load_raw()
            existing = self._find_raw_record(data, identity)
            if isinstance(existing, dict):
                status = existing.get("status")
                if status not in VALID_STATUSES:
                    raise SetupExecutionStateError(
                        f"Refusing to begin execution over a corrupt record "
                        f"for {(identity.project_key, identity.generation_id, identity.step_id)}: {existing!r}"
                    )
                if status in (IN_PROGRESS, RECOVERY_REQUIRED):
                    existing.update({"status": RECOVERY_REQUIRED, "interrupted_at": now})
                    self._save_raw(data)
                    raise SetupExecutionStateError(
                        f"Setup step {identity.step_id} (generation {identity.generation_id}) "
                        "was previously started and its outcome is unknown; "
                        "recovery is required, it will not be automatically re-executed."
                    )
                if status in (SUCCEEDED, FAILED) and existing.get("content") == list(identity.content):
                    raise SetupExecutionStateError(
                        f"Setup step {identity.step_id} (generation {identity.generation_id}) "
                        f"already reached a terminal state ({status}) for this "
                        "exact content; call get() first and do not begin() a "
                        "known-terminal attempt again."
                    )
                if status in (SUCCEEDED, FAILED) and existing.get("content") != list(identity.content):
                    raise SetupExecutionStateError(
                        f"Setup step {identity.step_id} (generation {identity.generation_id}) "
                        "has a persisted record with different execution-"
                        "relevant content (REQ-S3-GENERATION-CONTENT-"
                        "IMMUTABILITY). Changed content under the same "
                        "generation is never automatically begun; a new "
                        "materialization/generation and a new Human "
                        "Approval are required."
                    )
            plan_bucket = data.setdefault(identity.project_key, {}).setdefault(identity.generation_id, {})
            record = {
                "project_key": identity.project_key, "generation_id": identity.generation_id,
                "step_id": identity.step_id, "status": IN_PROGRESS,
                "content": list(identity.content), "owner_id": owner_id,
                "started_at": now,
            }
            plan_bucket[identity.step_id] = record
            self._save_raw(data)
            return dict(record)

    def finish(
        self, identity: SetupStepIdentity, owner_id: str, status: str, result: dict,
    ) -> dict:
        """Persist a terminal SUCCEEDED/FAILED result for the matching
        IN_PROGRESS record this exact owner began."""
        if status not in {SUCCEEDED, FAILED}:
            raise ValueError("terminal status must be succeeded or failed")
        with self._lock:
            data = self._load_raw()
            record = (
                data.get(identity.project_key, {})
                .get(identity.generation_id, {})
                .get(identity.step_id)
            )
            if not isinstance(record, dict) or record.get("status") != IN_PROGRESS:
                raise SetupExecutionStateError(
                    f"Cannot finish setup step {identity.step_id}: no matching "
                    "in-progress record."
                )
            if record.get("owner_id") != owner_id:
                raise SetupExecutionStateError(
                    f"Setup step {identity.step_id} owner mismatch on finish."
                )
            record.update({
                "status": status,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "result": result,
            })
            self._save_raw(data)
            return dict(record)
