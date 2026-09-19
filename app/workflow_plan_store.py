"""Persistence for generated setup plans."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from datetime import datetime
from enum import Enum
from pathlib import Path
from types import MappingProxyType

from app.requirement_model import SetupPlan


class WorkflowPlanStoreError(Exception):
    """Raised when a workflow plan cannot be stored or loaded."""


def _serialize_plan(obj):
    """Recursively convert a SetupPlan (or any nested dataclass) into a
    JSON-safe dict.

    Unlike ``dataclasses.asdict()`` this handles ``MappingProxyType``,
    arbitrary ``Mapping`` subclasses, ``datetime``, tuples, enums, and
    nested dataclasses without relying on ``copy.deepcopy()`` which
    cannot traverse immutable stdlib types like ``MappingProxyType``.
    Unsupported object types raise ``TypeError`` rather than silently
    producing a lossy ``repr()``/``str()`` fallback.
    """
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        result = {}
        for f in dataclasses.fields(obj):
            value = getattr(obj, f.name)
            result[f.name] = _serialize_plan(value)
        return result
    if isinstance(obj, (MappingProxyType, Mapping)):
        return {str(k): _serialize_plan(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize_plan(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    raise TypeError(
        f"unsupported type for plan serialization: "
        f"{type(obj).__qualname__} (value={obj!r})"
    )


class WorkflowPlanStore:
    """File-based persistence for SetupPlan objects."""

    def __init__(self, root: Path | str = ".workflow-plans") -> None:
        self.root = Path(root)

    def _project_root(self, project_id: str) -> Path:
        if not project_id or not project_id.strip():
            raise WorkflowPlanStoreError(
                "project_id must be a non-empty string."
            )

        return self.root / project_id

    def _plan_path(self, project_id: str, plan_id: str) -> Path:
        if not plan_id or not plan_id.strip():
            raise WorkflowPlanStoreError(
                "plan_id must be a non-empty string."
            )

        return self._project_root(project_id) / f"{plan_id}.json"

    def _project_root_marker_path(self, project_id: str) -> Path:
        return self._project_root(project_id) / "_project_root.json"

    def save_project_root(self, project_id: str, project_root: str) -> None:
        """Associate one validated filesystem root with a project_id.

        This is not a second project registry: it lives in the same
        project_id-scoped directory this store already owns, alongside
        that project's SetupPlan files, and exists solely so a later
        execute_setup_plan(project_id, plan_id) call can resolve the
        exact project_root that was already validated at plan-creation
        time, without inventing a new persistence mechanism.
        """
        if not project_root or not str(project_root).strip():
            raise WorkflowPlanStoreError("project_root must be a non-empty string.")

        directory = self._project_root(project_id)
        directory.mkdir(parents=True, exist_ok=True)
        marker = self._project_root_marker_path(project_id)
        try:
            marker.write_text(
                json.dumps({"project_root": str(project_root)}),
                encoding="utf-8",
            )
        except OSError as exc:
            raise WorkflowPlanStoreError(
                f"Could not persist project root for '{project_id}'."
            ) from exc

    def load_project_root(self, project_id: str) -> str | None:
        """Return the validated project_root associated with project_id, if any."""
        marker = self._project_root_marker_path(project_id)
        if not marker.is_file():
            return None
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        value = data.get("project_root") if isinstance(data, dict) else None
        return value if isinstance(value, str) and value.strip() else None

    def _council_reference_marker_path(self, project_id: str, plan_id: str) -> Path:
        return self._project_root(project_id) / f"{plan_id}._council_reference.json"

    def save_council_reference(
        self, project_id: str, plan_id: str,
        engineering_council_ref: str, chairman_approval_ref: str,
    ) -> None:
        """Associate one plan's Engineering Council/Chairman references
        with (project_id, plan_id).

        Not a second registry, and not a shortcut around approval: it
        lives in the same project_id-scoped directory this store already
        owns, alongside that plan's own SetupPlan file, solely so a
        caller that only has (project_id, plan_id) after the persisted
        approval gap — having lost the in-memory CouncilResult the plan
        was originally materialized from — can still recover the small,
        stable identifiers needed to build a real, non-fabricated
        ApprovalProvenance for capability authorization, without
        reloading (or inventing a way to reload) the full CouncilResult.
        """
        if not engineering_council_ref or not str(engineering_council_ref).strip():
            raise WorkflowPlanStoreError("engineering_council_ref must be a non-empty string.")
        if not chairman_approval_ref or not str(chairman_approval_ref).strip():
            raise WorkflowPlanStoreError("chairman_approval_ref must be a non-empty string.")

        directory = self._project_root(project_id)
        directory.mkdir(parents=True, exist_ok=True)
        marker = self._council_reference_marker_path(project_id, plan_id)
        try:
            marker.write_text(
                json.dumps({
                    "engineering_council_ref": str(engineering_council_ref),
                    "chairman_approval_ref": str(chairman_approval_ref),
                }),
                encoding="utf-8",
            )
        except OSError as exc:
            raise WorkflowPlanStoreError(
                f"Could not persist council reference for '{plan_id}'."
            ) from exc

    def load_council_reference(
        self, project_id: str, plan_id: str,
    ) -> tuple[str, str] | None:
        """Return (engineering_council_ref, chairman_approval_ref) for
        (project_id, plan_id), or None if never saved."""
        marker = self._council_reference_marker_path(project_id, plan_id)
        if not marker.is_file():
            return None
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        council_ref = data.get("engineering_council_ref")
        chairman_ref = data.get("chairman_approval_ref")
        if (
            isinstance(council_ref, str) and council_ref.strip()
            and isinstance(chairman_ref, str) and chairman_ref.strip()
        ):
            return council_ref, chairman_ref
        return None

    def save(self, plan: SetupPlan) -> Path:
        if not isinstance(plan, SetupPlan):
            raise TypeError("plan must be an instance of SetupPlan")

        project_root = self._project_root(plan.project_id)
        project_root.mkdir(parents=True, exist_ok=True)

        path = self._plan_path(plan.project_id, plan.id)

        try:
            path.write_text(
                json.dumps(
                    _serialize_plan(plan),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            raise WorkflowPlanStoreError(
                f"Could not save setup plan '{plan.id}'."
            ) from exc

        return path

    def load(self, project_id: str, plan_id: str) -> SetupPlan:
        path = self._plan_path(project_id, plan_id)

        if not path.is_file():
            raise WorkflowPlanStoreError(
                f"Setup plan '{plan_id}' does not exist "
                f"for project '{project_id}'."
            )

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkflowPlanStoreError(
                f"Could not load setup plan '{plan_id}'."
            ) from exc

        try:
            return self._deserialize(data)
        except Exception as exc:
            raise WorkflowPlanStoreError(
                f"Invalid setup plan '{plan_id}'."
            ) from exc

    @staticmethod
    def _deserialize_step(step: dict):
        from app.requirement_model import SetupStep

        return SetupStep(
            id=step["id"],
            requirement_id=step["requirement_id"],
            action=step["action"],
            install_method=step.get("install_method"),
            package=step.get("package"),
            version=step.get("version"),
            command=step.get("command"),
            verification_after=step.get("verification_after"),
            is_approved=step["is_approved"],
            setup_effect=step.get("setup_effect"),
            # target_executable is the current (CLAUDE-E2E-003C) generic
            # field name. A plan persisted by the short-lived, uncommitted
            # CLAUDE-E2E-003B format used "target_python" instead -- read
            # it as a compatibility fallback so an already-saved 003B-era
            # plan still round-trips correctly, without ever writing that
            # old key back out (save() always uses the current schema).
            target_executable=step.get("target_executable", step.get("target_python")),
        )

    @staticmethod
    def _deserialize_requirement(req_data: dict):
        from app.requirement_model import Requirement, RequirementEvidence

        evidence_raw = req_data.get("evidence", ())
        evidence = tuple(
        RequirementEvidence(
        id=e.get("id", ""),
        source_type=e.get("source_type", ""),
        description=e.get("description", ""),
        source_file=e.get("source_file"),
        snippet=e.get("snippet"),
        confidence_contribution=e.get("confidence_contribution"),
        url=e.get("url"),
        )
        for e in evidence_raw
        )
        return Requirement(
        id=req_data["id"],
        name=req_data["name"],
        type=req_data["type"],
        purpose=req_data["purpose"],
        required=req_data["required"],
        confidence=req_data["confidence"],
        evidence=evidence,
        source_file=req_data.get("source_file"),
        detected_version=req_data.get("detected_version"),
        required_version=req_data.get("required_version"),
        install_method=req_data.get("install_method"),
        verification_method=req_data.get("verification_method"),
        verification_executable=req_data.get("verification_executable"),
        status=req_data.get("status", "discovered"),
        metadata=dict(req_data.get("metadata", {})),
        technical_identity=req_data.get("technical_identity"),
        )

    @staticmethod
    def _deserialize_activation(activation: dict):
        from app.requirement_model import RequirementActivation

        return RequirementActivation(
            requirement_id=activation["requirement_id"],
            active=activation["active"],
            blocks_current_operation=activation["blocks_current_operation"],
            reason=activation.get("reason", ""),
        )

    @staticmethod
    def _deserialize(data: dict) -> SetupPlan:
        steps = tuple(
            WorkflowPlanStore._deserialize_step(step)
            for step in data["steps"]
        )
        rollback_steps = tuple(
            WorkflowPlanStore._deserialize_step(step)
            for step in data.get("rollback_steps", ())
        )
        requirement_activations = tuple(
            WorkflowPlanStore._deserialize_activation(activation)
            for activation in data.get("requirement_activations", ())
        )

        created_at_raw = data.get("created_at")
        created_at = (
            datetime.fromisoformat(created_at_raw)
            if created_at_raw
            else None
        )

        generation_id = WorkflowPlanStore._resolve_generation_id(data)

        return SetupPlan(
            id=data["id"],
            project_id=data["project_id"],
            steps=steps,
            requires_user_approval=data["requires_user_approval"],
            rollback_steps=rollback_steps,
            warnings=tuple(data.get("warnings", ())),
            status=data["status"],
            created_at=created_at,
            requirement_activations=requirement_activations,
            deferred_requirement_ids=tuple(data.get("deferred_requirement_ids", ())),
            unsupported_backend_effects=tuple(data.get("unsupported_backend_effects", ())),
            provided_requirement_ids=tuple(data.get("provided_requirement_ids", ())),
            generation_id=generation_id,
            deferred_requirements=tuple(
                WorkflowPlanStore._deserialize_requirement(r)
                for r in data.get("deferred_requirements", ())
            ),
        )

    @staticmethod
    def _resolve_generation_id(data: dict) -> str:
        """CLAUDE-E2E-003I legacy/corrupt generation_id handling.

        A plan persisted before generation_id existed (003E-003H) has no
        such key at all -- that is the ONLY case treated as legacy: a
        deterministic, restart-stable identity bound to this exact
        plan.id (f"legacy-{plan.id}"), distinct in shape from any real,
        randomly-generated generation_id, so it can never collide with a
        genuinely new materialization's generation and never lets an old
        SUCCEEDED execution-state record silently apply to a future new
        one. A PRESENT but malformed value (not a non-empty string) is
        corrupt, not legacy, and fails closed rather than being guessed at.
        """
        if "generation_id" not in data:
            return f"legacy-{data['id']}"
        value = data.get("generation_id")
        if not isinstance(value, str) or not value.strip():
            raise WorkflowPlanStoreError(
                f"Setup plan '{data.get('id')}' has a corrupt generation_id; "
                "refusing to guess a safe value."
            )
        return value
