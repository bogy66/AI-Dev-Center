"""Generic, ecosystem-neutral persisted binding between a Human Approval
event and the exact execution-relevant SetupStep content it authorized
(CLAUDE-E2E-003I-B).

REQ-S3-APPROVED-PLAN-CONTENT-IMMUTABILITY:
"Human Approval authorizes the execution-relevant content of the exact
materialized setup generation. Execution-relevant SetupStep content must
not change after approval within the same generation. Any material
mismatch must fail closed and require a new materialization, generation
and Human Approval."

This is separate from, but complementary to, REQ-S3-GENERATION-CONTENT-
IMMUTABILITY (app.setup_execution_state): that requirement protects the
interval from first execution/state onward (retry, restart, recovery),
and by construction can only compare against a SetupExecutionState
record that already exists. This module protects the earlier interval
-- materialization -> approval -> first execution -- where no such
record exists yet. An independent security review of CLAUDE-E2E-003I/
003I-A found, and this module closes, a real, mechanically reproduced
gap in that earlier interval: Human Approval for setup generation G1
with Step S1 content A did not bind anything about A itself -- only the
generation_id, project scope and Council/Chairman references. A
step whose execution-relevant content was mutated to B (command,
package, version, install_method, target_executable, ...) while
keeping the SAME generation_id, SAME step_id and "approved" status was
silently re-authorized and re-executed using G1's original approval,
even though no SetupExecutionState record for A had ever been created
(so REQ-S3-GENERATION-CONTENT-IMMUTABILITY's own protection, keyed off
an existing record, never had anything to compare against).

record_approved() is called exactly once, by the single adapter-shared
approve_setup_plan() function every real Human Approval transition goes
through (app.project_setup_application) -- this is the one place a
genuine Human Approval event happens for both Web and MCP. verify() is
called from the other single shared gate, authorize_setup_plan_targets(),
before any dynamic capability registration is attempted for an approved
plan. Together this makes the binding centrally derived and never
client-suppliable: nothing about the recorded content ever depends on
anything a caller of authorize_setup_plan_targets()/execute_approved()
supplies.

Keyed purely by (generation_id, step_id): SetupPlan.generation_id is
already a process-wide-unique value (uuid4 hex, see
app.requirement_model._new_generation_id) for every genuine new
materialization, so no project scoping is needed for this fingerprint
to be unambiguous -- unlike app.setup_execution_state, this store never
has to reconcile a pre-existing (pre-CLAUDE-E2E-003I) persisted shape,
since it is introduced only now; no legacy compatibility lookup is
needed or provided.

Uses the same atomic-write pattern (temp file + fsync + os.replace)
already established by WorkflowManager and SetupExecutionStateStore.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from app.setup_execution_state import setup_step_content_snapshot
from app.state_lock import get_state_lock


class ApprovedPlanContentError(Exception):
    """Raised whenever execution-relevant SetupStep content diverges
    from what Human Approval actually authorized for this exact setup
    generation, or when no such recorded Human Approval content exists
    at all for an approved plan. Always fails closed: never caught
    internally to silently proceed with authorization or execution."""


class ApprovedPlanContentStore:
    """Persisted, generation-scoped record of the execution-relevant
    content Human Approval actually authorized, restart-safe by
    design."""

    def __init__(self, storage="approved_plan_content.json"):
        self.storage = Path(storage)
        self._lock = get_state_lock(self.storage)

    def _load_raw(self) -> dict:
        if not self.storage.exists():
            return {}
        try:
            raw = self.storage.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApprovedPlanContentError(
                f"Approved plan content file {self.storage} is corrupt "
                f"or unreadable; refusing to treat this as unapproved: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise ApprovedPlanContentError(
                f"Approved plan content file {self.storage} does not "
                "contain a JSON object; refusing to treat this as unapproved."
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

    def record_approved(self, plan) -> None:
        """Persist the immutable, approval-time execution-relevant
        content fingerprint for every step of this exact setup
        generation. Called once, by approve_setup_plan(), at the exact
        moment a real Human Approval transition happens.

        Idempotent when called again with identical content for the
        same (generation_id, step_id) -- e.g. a duplicate/retried
        approval event for the same generation. Fails closed
        (ApprovedPlanContentError) if an existing recorded fingerprint
        for this exact (generation_id, step_id) differs: an approved
        generation's own content must never be mutated even before
        verify() is ever consulted."""
        with self._lock:
            data = self._load_raw()
            bucket = data.setdefault(plan.generation_id, {})
            for step in plan.steps:
                content = list(setup_step_content_snapshot(step))
                existing = bucket.get(step.id)
                if existing is not None and existing != content:
                    raise ApprovedPlanContentError(
                        f"Setup step '{step.id}' (generation "
                        f"'{plan.generation_id}') already has a recorded "
                        "Human-Approved content fingerprint that differs "
                        "from the content now being recorded "
                        "(REQ-S3-APPROVED-PLAN-CONTENT-IMMUTABILITY). A "
                        "genuinely new/changed operation requires a new "
                        "materialization and generation, never a second "
                        "approval-content record for the same one."
                    )
                bucket[step.id] = content
            self._save_raw(data)

    def verify(self, plan) -> None:
        """Raise ApprovedPlanContentError unless every one of this
        plan's currently approved steps has execution-relevant content
        identical to what was recorded at real Human Approval time for
        this exact generation (record_approved()).

        Fails closed both when a step's content has changed AND when no
        approval-content record exists at all for this generation --
        the latter is never silently treated as "nothing to check": an
        approved plan whose exact content was never actually the
        subject of a recorded Human Approval event must not be
        authorized either."""
        data = self._load_raw()
        bucket = data.get(plan.generation_id)
        if bucket is None:
            raise ApprovedPlanContentError(
                f"No Human-Approved content is recorded for setup "
                f"generation '{plan.generation_id}'; refusing to "
                "authorize or execute an approved plan whose exact "
                "content was never the subject of a recorded Human "
                "Approval event (REQ-S3-APPROVED-PLAN-CONTENT-IMMUTABILITY)."
            )
        for step in plan.steps:
            if not step.is_approved:
                continue
            recorded = bucket.get(step.id)
            current = list(setup_step_content_snapshot(step))
            if recorded is None or recorded != current:
                raise ApprovedPlanContentError(
                    f"Setup step '{step.id}' (generation "
                    f"'{plan.generation_id}') execution-relevant content "
                    "does not match what Human Approval actually "
                    "authorized for this exact setup generation "
                    "(REQ-S3-APPROVED-PLAN-CONTENT-IMMUTABILITY). A "
                    "material content change after approval, within the "
                    "same generation, is never automatically "
                    "re-authorized; a new materialization, generation "
                    "and Human Approval are required."
                )
