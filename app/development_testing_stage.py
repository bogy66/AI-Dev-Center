"""Canonical coordination of existing development and testing stages."""
from dataclasses import dataclass

from app.change_application import ChangeApplicationService
from app.project_test_runner import StepFailureEvidence, TestExecutionRequest, TestResult


def _step_failure_evidence(step) -> StepFailureEvidence:
    """Carry one failing VerificationStepResult's full evidence forward.

    Reads only the fields VerificationStepResult already declares --
    including `diagnostics`/`error_category`, which is the *only*
    explanation some controlled outcomes (BLOCKED, EXECUTION_ERROR,
    INVALID_PLAN, ...) ever populate, since their stdout/stderr are
    empty by construction. Never verifier-specific: every field here
    comes from the generic VerificationStepResult contract.
    """
    return StepFailureEvidence(
        area=step.area,
        step_id=step.step_id,
        runner_type=step.runner_type,
        verification_kind=step.verification_kind,
        status=step.status,
        command=step.command,
        return_code=step.return_code,
        timed_out=step.timed_out,
        error_category=step.error_category,
        diagnostics=step.diagnostics,
        stdout=step.stdout,
        stderr=step.stderr,
    )


def _test_result_from_verification(executable_steps) -> TestResult:
    """Fold real per-step verification evidence into one TestResult.

    A `VerificationResult` carries the actual stdout/stderr/return_code/
    diagnostics for each step (whatever kind of verifier produced it --
    pytest, a compiler, a config validator, ...), but `TestResult` only
    has one scalar stdout/stderr/return_code/command slot. Rather than
    flattening every failing step into that one slot -- which either
    drops diagnostics-only failures (BLOCKED/EXECUTION_ERROR steps whose
    stdout/stderr are empty by construction) or falsely presents one
    step's command/return_code as if it described every failure -- each
    failing step's full evidence is preserved individually in
    `step_failures`. The scalar fields stay a safe, neutral aggregate:
    a real, faithful mirror of the one step's evidence when exactly one
    step failed, or a neutral "N steps failed" marker (never one
    arbitrarily chosen step's value) when several did.
    """
    passed_all = all(s.passed for s in executable_steps)
    if passed_all:
        return TestResult(
            passed=True, return_code=0, stdout="", stderr="",
            command=("verification",), timed_out=False,
        )

    failing = [s for s in executable_steps if not s.passed]
    step_failures = tuple(_step_failure_evidence(s) for s in failing)
    timed_out = any(s.timed_out for s in failing)

    if len(failing) == 1:
        only = failing[0]
        return TestResult(
            passed=False,
            return_code=only.return_code if only.return_code is not None else 1,
            stdout=only.stdout,
            stderr=only.stderr,
            command=only.command if only.command else ("verification",),
            timed_out=timed_out,
            step_failures=step_failures,
        )

    return TestResult(
        passed=False,
        return_code=1,
        stdout=f"{len(failing)} verification steps failed; see step_failures for per-step detail.",
        stderr="",
        command=("verification",),
        timed_out=timed_out,
        step_failures=step_failures,
    )


@dataclass(frozen=True)
class DevelopmentTestingResult:
    development_result: object
    test_changes: dict
    apply_result: dict
    test_result: object
    testing_stage_result: object
    verification_result: object | None = None

    @property
    def status(self) -> str:
        """Expose the testing decision without introducing a second policy."""
        return self.testing_stage_result.status


class DevelopmentTestingStage:
    def __init__(self, development_stage, test_change_generator, file_applier_factory, project_test_runner, testing_stage, verification_registry=None, project_inspector=None,
                 change_application: ChangeApplicationService | None = None):
        self._development_stage = development_stage
        self._test_change_generator = test_change_generator
        self._change_application = change_application or ChangeApplicationService(file_applier_factory)
        self._project_test_runner = project_test_runner
        self._testing_stage = testing_stage
        self._verification_registry = verification_registry
        self._project_inspector = project_inspector

    def run(self, request):
        development_result = self._development_stage.run(request)
        test_changes = self._test_change_generator.generate(request)
        is_rework = bool(getattr(request, "rework_request", None))
        apply_result = self._change_application.apply(
            request.project_path, test_changes, "test", is_rework,
            provenance_recorder=getattr(request, "provenance_recorder", None),
        )

        verification_result = None
        test_result = None

        if self._verification_registry is not None and self._project_inspector is not None:
            from app.verification import build_verification_plan
            run_id = getattr(request, "run_id", "") or "unknown"
            try:
                intelligence = self._project_inspector.build_intelligence(request.project_path)
            except Exception:
                intelligence = None
            plan = build_verification_plan(intelligence, run_id)
            verification_result = self._verification_registry.execute_plan(plan)

            executable = [s for s in verification_result.steps
                          if s.status not in ("unsupported", "not_applicable", "deferred")]
            if executable:
                test_result = _test_result_from_verification(executable)
            else:
                test_result = self._project_test_runner.run(TestExecutionRequest(request.project_path))
        else:
            test_result = self._project_test_runner.run(TestExecutionRequest(request.project_path))

        stage_result = self._testing_stage.run(development_result, test_result)
        return DevelopmentTestingResult(development_result, test_changes, apply_result, test_result, stage_result, verification_result=verification_result)
