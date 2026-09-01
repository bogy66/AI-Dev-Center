"""Application-core entry point for canonical project setup planning."""

from __future__ import annotations

from pathlib import Path

from app.common_request import CommonRequest, RequestIntent
from app.development_stage import DevelopmentRequest
from app.dev_workflow import (
    DevelopmentWorkflow,
    SetupDevelopmentTestingResult,
    WorkflowResult,
)
from app.project_inspector import ProjectInspector


class ProjectSetupApplicationService:
    """Inspect a project, normalize adapter input, and delegate planning."""

    def __init__(
        self,
        development_workflow: DevelopmentWorkflow,
        project_inspector: ProjectInspector | None = None,
    ) -> None:
        self._development_workflow = development_workflow
        self._project_inspector = project_inspector or ProjectInspector()

    def build_request(
        self, project_id: str, project_path: str | Path
    ) -> CommonRequest:
        """Inspect the project and create the sole supported input intent."""
        project_info = self._project_inspector.inspect(project_id, project_path)
        return CommonRequest(
            project_id=project_id,
            project_info=project_info,
            intent=RequestIntent.PLAN_PROJECT_SETUP,
        )

    def plan_project_setup(
        self, project_id: str, project_path: str | Path
    ) -> WorkflowResult:
        """Plan setup through the canonical workflow; never approve or execute."""
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id must be a non-empty string")

        request = self.build_request(project_id, project_path)
        if request.intent is not RequestIntent.PLAN_PROJECT_SETUP:
            raise ValueError(f"Unsupported request intent: {request.intent}")

        return self._development_workflow.run(
            request.project_info,
            request.project_id,
        )

    def execute_approved_setup_and_development(
        self,
        plan,
        project_id: str,
        project_path: str | Path,
        task: str,
    ) -> SetupDevelopmentTestingResult:
        """Execute approved setup, then delegate development/testing once."""
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id must be a non-empty string")
        if not isinstance(task, str) or not task.strip():
            raise ValueError("task must be a non-empty string")

        request = DevelopmentRequest(
            project_id=project_id,
            project_path=project_path,
            task=task,
        )
        return self._development_workflow.execute_approved_and_run_development(
            plan,
            request,
        )
