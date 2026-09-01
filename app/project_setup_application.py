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
from app.workflow_manager import WorkflowManager
from app.final_approval import FinalApprovalResult
from app.change_provenance import RunChangeProvenance


class ProjectSetupApplicationService:
    """Inspect a project, normalize adapter input, and delegate planning."""

    def __init__(
        self,
        development_workflow: DevelopmentWorkflow,
        project_inspector: ProjectInspector | None = None,
        workflow_manager: WorkflowManager | None = None,
    ) -> None:
        self._development_workflow = development_workflow
        self._project_inspector = project_inspector or ProjectInspector()
        self._workflow_manager = workflow_manager or WorkflowManager()

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
        run_id: str | None = None,
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
            run_id=run_id or plan.id,
            provenance_recorder=RunChangeProvenance(self._workflow_manager, run_id or plan.id, project_path),
        )
        result = self._development_workflow.execute_approved_and_run_development(
            plan,
            request,
        )
        approval = self._final_approval_for(
            run_id or plan.id,
            result.status,
        )
        from dataclasses import replace
        return replace(result, final_approval_result=approval)

    def decide_final_approval(
        self,
        run_id: str,
        decision: str,
        approved_by: str | None = None,
        comment: str | None = None,
    ) -> FinalApprovalResult:
        return self._workflow_manager.decide_final_approval(
            run_id, decision, approved_by, comment,
        )

    def _final_approval_for(self, run_id: str, development_status: str) -> FinalApprovalResult:
        if development_status != "accepted":
            return FinalApprovalResult(run_id, "not_applicable", False, False)
        return self._workflow_manager.create_final_approval(run_id, development_status)
