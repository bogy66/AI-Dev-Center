from dataclasses import dataclass
from app.execution import is_controlled_setup_effect
from app.requirement_model import SetupStep


class StepNotApprovedError(Exception):
    """Raised when attempting to execute a step that has not been approved."""
    pass


class UnsupportedSetupEffectError(Exception):
    """Raised when a setup effect has no controlled execution backend."""

    def __init__(self, step_id: str, effect: str):
        super().__init__(
            f"Setup step '{step_id}' requires effect '{effect}' "
            f"but ADC has no controlled backend for this setup effect."
        )
        self.step_id = step_id
        self.effect = effect


@dataclass(frozen=True)
class ExecutionResult:
    step_id: str
    success: bool
    message: str
    verification_passed: bool = False


class SetupExecutor:
    """Generic executor for approved setup steps.

    Currently returns a placeholder result without performing any real
    installation or verification.  Only setup effects with an explicitly
    controlled execution backend are permitted.
    """

    def execute_step(self, step: SetupStep) -> ExecutionResult:
        """Execute a single approved setup step.

        Args:
            step: The setup step to execute.

        Returns:
            ExecutionResult with success=False and a placeholder message.

        Raises:
            StepNotApprovedError: If the step has not been approved.
            UnsupportedSetupEffectError: If the setup effect has no
                controlled execution backend.
        """
        if not step.is_approved:
            raise StepNotApprovedError(
                f"Step {step.id} has not been approved and cannot be executed."
            )
        effect = step.setup_effect
        if effect and not is_controlled_setup_effect(effect):
            raise UnsupportedSetupEffectError(step.id, effect)
        return ExecutionResult(
            step_id=step.id,
            success=False,
            message="execution backend not implemented",
            verification_passed=False,
        )