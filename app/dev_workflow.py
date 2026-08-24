"""Deterministic development workflow connecting discovery, validation, preflight, and planning."""

from dataclasses import dataclass

from app.ai_requirement_discovery import AIRequirementDiscovery
from app.requirement_model import DiscoveryResult, PreflightResult, SetupPlan, ValidationResult
from app.requirement_preflight import RequirementPreflight
from app.requirement_validator import RequirementValidator
from app.setup_planner import SetupPlanner


@dataclass(frozen=True)
class WorkflowResult:
    """Immutable container holding the results of each workflow stage."""

    discovery_result: DiscoveryResult
    validation_result: ValidationResult
    preflight_result: PreflightResult
    setup_plan: SetupPlan


class DevelopmentWorkflow:
    """Orchestrates the deterministic development workflow.

    The workflow runs four stages in order:

    1. Requirement discovery (AIRequirementDiscovery)
    2. Requirement validation (RequirementValidator)
    3. Environment preflight (RequirementPreflight)
    4. Setup planning (SetupPlanner)

    The workflow does **not** approve, reject, execute, or install anything.
    The resulting ``SetupPlan`` is left in ``pending_approval`` status.
    """

    def __init__(
        self,
        discovery: AIRequirementDiscovery,
        validator: RequirementValidator,
        preflight: RequirementPreflight,
        planner: SetupPlanner,
    ) -> None:
        self._discovery = discovery
        self._validator = validator
        self._preflight = preflight
        self._planner = planner

    def run(self, project_info: object, project_id: str) -> WorkflowResult:
        """Execute the full workflow and return an immutable result.

        Args:
            project_info: Arbitrary project information consumed by the discovery stage.
            project_id: Unique identifier for the project.

        Returns:
            WorkflowResult containing the outputs of all four stages.

        Raises:
            Any exception raised by the discovery, validation, preflight, or planning
            stages is propagated unchanged.
        """
        # 1. Discovery
        discovery_result = self._discovery.discover(project_info, project_id)

        # 2. Validation
        validation_result = self._validator.validate(discovery_result.requirements)

        # 3. Preflight
        preflight_result = self._preflight.check(
            validation_result.normalized_requirements, project_id
        )

        # 4. Planning
        setup_plan = self._planner.plan(
            validation_result.required_requirements, preflight_result, project_id
        )

        return WorkflowResult(
            discovery_result=discovery_result,
            validation_result=validation_result,
            preflight_result=preflight_result,
            setup_plan=setup_plan,
        )
