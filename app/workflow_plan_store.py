"""Persistence for generated setup plans."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from app.requirement_model import SetupPlan


class WorkflowPlanStoreError(Exception):
    """Raised when a workflow plan cannot be stored or loaded."""


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

    def save(self, plan: SetupPlan) -> Path:
        if not isinstance(plan, SetupPlan):
            raise TypeError("plan must be an instance of SetupPlan")

        project_root = self._project_root(plan.project_id)
        project_root.mkdir(parents=True, exist_ok=True)

        path = self._plan_path(plan.project_id, plan.id)

        try:
            path.write_text(
                json.dumps(
                    asdict(plan),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                    default=str,
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
    def _deserialize(data: dict) -> SetupPlan:
        from app.requirement_model import SetupStep

        steps = tuple(
            SetupStep(
                id=step["id"],
                requirement_id=step["requirement_id"],
                action=step["action"],
                install_method=step.get("install_method"),
                package=step.get("package"),
                version=step.get("version"),
                command=step.get("command"),
                verification_after=step.get("verification_after"),
                is_approved=step["is_approved"],
            )
            for step in data["steps"]
        )

        created_at_raw = data.get("created_at")
        created_at = (
            datetime.fromisoformat(created_at_raw)
            if created_at_raw
            else None
        )

        return SetupPlan(
            id=data["id"],
            project_id=data["project_id"],
            steps=steps,
            requires_user_approval=data["requires_user_approval"],
            rollback_steps=tuple(data.get("rollback_steps", ())),
            warnings=tuple(data.get("warnings", ())),
            status=data["status"],
            created_at=created_at,
            provided_requirement_ids=tuple(data.get("provided_requirement_ids", ())),
        )
