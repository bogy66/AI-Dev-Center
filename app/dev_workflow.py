"""Development workflow with Council planning and explicit approved execution."""

from __future__ import annotations

from dataclasses import dataclass

from app.ai_requirement_discovery import AIRequirementDiscovery
from app.council_models import CouncilInput, CouncilResult
from app.engineering_council import EngineeringCouncil
from app.requirement_model import (
    DiscoveryResult,
    PreflightResult,
    SetupPlan,
    ValidationResult,
)
from app.requirement_preflight import RequirementPreflight
from app.requirement_validator import RequirementValidator
from app.setup_executor import ExecutionResult, SetupExecutor
from app.setup_planner import SetupPlanner
from app.toolchain_materializer import ToolchainMaterializer


class WorkflowExecutionError(Exception):
    """Raised when the workflow cannot continue safely."""


@dataclass(frozen=True)
class WorkflowResult:
    """Immutable result of discovery through Council-based planning."""

    discovery_result: DiscoveryResult
    validation_result: ValidationResult
    preflight_result: PreflightResult
    council_result: CouncilResult
    setup_plan: SetupPlan


class DevelopmentWorkflow:
    """Run canonical planning and, separately, approved execution."""

    def __init__(
        self,
        discovery: AIRequirementDiscovery,
        validator: RequirementValidator,
        preflight: RequirementPreflight,
        planner: SetupPlanner | None = None,
        executor: SetupExecutor | None = None,
        council: EngineeringCouncil | None = None,
        materializer: ToolchainMaterializer | None = None,
    ) -> None:
        self._discovery = discovery
        self._validator = validator
        self._preflight = preflight

        # Transitional constructor compatibility only.
        # The canonical planning flow no longer uses SetupPlanner.
        self._planner = planner

        self._executor = executor
        self._council = council
        self._materializer = materializer

    def run(self, project_info: object, project_id: str) -> WorkflowResult:
        """Run discovery through Council-based planning only.

        This method never approves, rejects or executes setup steps.
        """

        discovery_result = self._discovery.discover(
            project_info,
            project_id,
        )

        if discovery_result.fallback_used:
            raise WorkflowExecutionError(
                "Requirement discovery fallback was used; "
                "workflow planning is blocked."
            )

        validation_result = self._validator.validate(
            discovery_result.requirements,
        )

        preflight_result = self._preflight.check(
            validation_result.normalized_requirements,
            project_id,
        )

        if self._council is None:
            raise WorkflowExecutionError(
                "No Engineering Council has been configured."
            )

        if self._materializer is None:
            raise WorkflowExecutionError(
                "No ToolchainMaterializer has been configured."
            )

        council_input = CouncilInput(
            requirements=validation_result.normalized_requirements,
            preflight=preflight_result,
            project_id=project_id,
            project_files=self._extract_project_files(project_info),
            validation_warnings=validation_result.warnings,
        )

        council_result = self._council.evaluate(council_input)

        setup_plan = self._materializer.materialize(
            council_result,
            project_id,
        )

        return WorkflowResult(
            discovery_result=discovery_result,
            validation_result=validation_result,
            preflight_result=preflight_result,
            council_result=council_result,
            setup_plan=setup_plan,
        )

    @staticmethod
    def _extract_project_files(project_info: object) -> tuple[str, ...]:
        """Return only explicitly supplied project file paths."""

        if not isinstance(project_info, dict):
            return ()

        files = project_info.get("files")
        if not isinstance(files, (list, tuple)):
            return ()

        paths: list[str] = []

        for item in files:
            if not isinstance(item, dict):
                continue

            path = item.get("path")
            if isinstance(path, str) and path:
                paths.append(path)

        return tuple(paths)

    def _validate_executable_step(self, step) -> None:
        """Reject steps that are not safe for automatic execution."""

        if step.action != "install":
            raise WorkflowExecutionError(
                f"Setup step '{step.id}' requires manual review: "
                f"action={step.action!r}."
            )

        if not step.package or not step.package.strip():
            raise WorkflowExecutionError(
                f"Setup step '{step.id}' requires manual review: "
                "no package is specified."
            )

        if not step.install_method:
            raise WorkflowExecutionError(
                f"Setup step '{step.id}' requires manual review: "
                "no install method is specified."
            )

    def execute_approved(
        self,
        plan: SetupPlan,
    ) -> tuple[ExecutionResult, ...]:
        """Execute an already approved setup plan safely."""

        if plan.status != "approved":
            raise WorkflowExecutionError(
                f"Setup plan '{plan.id}' is not approved; "
                f"current status is '{plan.status}'."
            )

        if self._executor is None:
            raise WorkflowExecutionError(
                "No setup executor has been configured."
            )

        for step in plan.steps:
            if not step.is_approved:
                raise WorkflowExecutionError(
                    f"Setup step '{step.id}' is not approved."
                )

            self._validate_executable_step(step)

        return tuple(
            self._executor.execute(step)
            for step in plan.steps
        )
