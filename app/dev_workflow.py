"""Deterministic development workflow with explicit approved execution."""

from __future__ import annotations

from dataclasses import dataclass

from app.ai_requirement_discovery import AIRequirementDiscovery
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


class WorkflowExecutionError(Exception):
    """Raised when an approved setup plan cannot be executed safely."""


@dataclass(frozen=True)
class WorkflowResult:
    """Immutable result of discovery, validation, preflight and planning."""

    discovery_result: DiscoveryResult
    validation_result: ValidationResult
    preflight_result: PreflightResult
    setup_plan: SetupPlan


class DevelopmentWorkflow:
    """Run deterministic planning and, separately, approved execution."""

    def __init__(
        self,
        discovery: AIRequirementDiscovery,
        validator: RequirementValidator,
        preflight: RequirementPreflight,
        planner: SetupPlanner,
        executor: SetupExecutor | None = None,
    ) -> None:
        self._discovery = discovery
        self._validator = validator
        self._preflight = preflight
        self._planner = planner
        self._executor = executor

    def run(self, project_info: object, project_id: str) -> WorkflowResult:
        """Run discovery through planning only.

        This method never approves, rejects or executes setup steps.
        """

        discovery_result = self._discovery.discover(
            project_info,
            project_id,
        )

        validation_result = self._validator.validate(
            discovery_result.requirements,
        )

        preflight_result = self._preflight.check(
            validation_result.normalized_requirements,
            project_id,
        )

        setup_plan = self._planner.plan(
            validation_result.required_requirements,
            preflight_result,
            project_id,
        )

        return WorkflowResult(
            discovery_result=discovery_result,
            validation_result=validation_result,
            preflight_result=preflight_result,
            setup_plan=setup_plan,
        )

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
