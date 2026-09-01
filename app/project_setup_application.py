"""Application-core entry point for canonical project setup planning."""

from __future__ import annotations

from pathlib import Path

from app.common_request import CommonRequest, RequestIntent
from app.dev_workflow import DevelopmentWorkflow, WorkflowResult
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
