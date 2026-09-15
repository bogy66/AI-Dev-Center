"""Canonical coordination of existing development and testing stages."""
from dataclasses import dataclass

from app.project_test_runner import TestExecutionRequest, TestResult


def _test_result_from_verification(executable_steps) -> TestResult:
    """Fold real per-step verification evidence into one TestResult.

    A `VerificationResult` carries the actual stdout/stderr/return_code
    for each step (whatever kind of verifier produced it -- pytest, a
    compiler, a config validator, ...), but `TestResult` only has one
    stdout/stderr/return_code/command slot. Only `failure_summary` (a
    bare "area/step: status" line, with no diagnostic text at all) was
    being carried into it, so a failing rework Developer never actually
    saw *why* a step failed -- only that it did. This aggregates the
    real evidence from every failing step, in plan order, so nothing
    verifier-specific has to be hard-coded here.
    """
    passed_all = all(s.passed for s in executable_steps)
    if passed_all:
        return TestResult(
            passed=True, return_code=0, stdout="", stderr="",
            command=("verification",), timed_out=False,
        )

    failing = [s for s in executable_steps if not s.passed]
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    commands: list[str] = []
    timed_out = False
    return_code = None
    for step in failing:
        header = f"[{step.area}/{step.step_id} ({step.runner_type}/{step.verification_kind}): {step.status}]"
        stdout_parts.append(header)
        if step.stdout:
            stdout_parts.append(step.stdout)
        if step.stderr:
            stderr_parts.append(f"{header}\n{step.stderr}")
        if step.command:
            commands.append(" ".join(str(part) for part in step.command))
        timed_out = timed_out or step.timed_out
        if return_code is None and step.return_code is not None:
            return_code = step.return_code

    return TestResult(
        passed=False,
        return_code=return_code if return_code is not None else 1,
        stdout="\n".join(stdout_parts),
        stderr="\n".join(stderr_parts),
        command=tuple(commands) if commands else ("verification",),
        timed_out=timed_out,
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
    def __init__(self, development_stage, test_change_generator, file_applier_factory, project_test_runner, testing_stage, verification_registry=None, project_inspector=None):
        self._development_stage = development_stage
        self._test_change_generator = test_change_generator
        self._file_applier_factory = file_applier_factory
        self._project_test_runner = project_test_runner
        self._testing_stage = testing_stage
        self._verification_registry = verification_registry
        self._project_inspector = project_inspector

    def run(self, request):
        development_result = self._development_stage.run(request)
        test_changes = self._test_change_generator.generate(request)
        applier = self._file_applier_factory(request.project_path)
        phase = "rework_test" if getattr(request, "rework_request", None) else "test"
        apply_result = request.provenance_recorder.apply(applier, test_changes, phase) if getattr(request, "provenance_recorder", None) else applier.apply(test_changes)

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
