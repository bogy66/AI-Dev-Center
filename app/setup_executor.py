"""ExecutionResult and StepNotApprovedError below are shared,
productively-consumed contracts (e.g. by
app.python_package_executor.PythonPackageExecutor). UnsupportedSetupEffectError
is defined here for the same reason (this module's own SetupExecutor.execute_step()
raises it) but, unlike the other two, is not currently imported or
raised by any other productive module -- it is not (yet) an equally
shared cross-module contract; see ADC_Zielbild §4J.3. SetupExecutor
itself is a different matter -- see its own docstring.
"""
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
    """LEGACY / PLACEHOLDER -- NOT the productive S3.3 Controlled
    Execution owner.

    Always returns success=False, "execution backend not implemented":
    it performs no real installation or verification and never has.
    canonical_composition.py never constructs this class -- grep
    confirms SetupExecutor( is never instantiated anywhere in app/*.py
    outside this module and its own dedicated test file.

    The productive S3.3 boundary is:
      - app.dev_workflow.DevelopmentWorkflow.execute_approved() --
        the central gate that validates plan/step approval, enforces
        the replay/idempotency guard, and dispatches to whichever
        executor is actually configured;
      - app.python_package_executor.PythonPackageExecutor -- the
        current concrete backend adapter it dispatches to (Python
        package installation only; not a generic definition of S3.3,
        and not to be treated as central policy for other ecosystems).

    Kept, not deleted, because ExecutionResult/StepNotApprovedError/
    UnsupportedSetupEffectError defined in this module remain shared,
    productively-consumed contracts (CLAUDE-ADC-S3-LEGACY-HYGIENE-
    OWNERSHIP-FIX-001) -- do not reintroduce SetupExecutor itself into
    the canonical execution path.
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