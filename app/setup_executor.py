from dataclasses import dataclass
from app.requirement_model import SetupStep


class StepNotApprovedError(Exception):
    """Raised when attempting to execute a step that has not been approved."""
    pass


@dataclass(frozen=True)
class ExecutionResult:
    step_id: str
    success: bool
    message: str
    verification_passed: bool = False


class SetupExecutor:
    """Generic executor for approved setup steps.

    Currently returns a placeholder result without performing any real
    installation or verification.
    """

    def execute_step(self, step: SetupStep) -> ExecutionResult:
        """Execute a single approved setup step.

        Args:
            step: The setup step to execute.

        Returns:
            ExecutionResult with success=False and a placeholder message.

        Raises:
            StepNotApprovedError: If the step has not been approved.
        """
        if not step.is_approved:
            raise StepNotApprovedError(
                f"Step {step.id} has not been approved and cannot be executed."
            )
        # Placeholder – no real execution is performed.
        return ExecutionResult(
            step_id=step.id,
            success=False,
            message="execution backend not implemented",
            verification_passed=False,
        )
