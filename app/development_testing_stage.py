"""Canonical coordination of existing development and testing stages."""
from dataclasses import dataclass

from app.change_application import ChangeApplicationService
from app.project_test_runner import StepFailureEvidence, TestExecutionRequest, TestResult
from app.test_change_generator import TestChangeDisposition


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
    test_changes: dict | None
    apply_result: dict | None
    test_result: object | None
    testing_stage_result: object | None
    verification_result: object | None = None
    # None on the normal path (S5 was reached and testing_stage_result
    # carries the real decision). Set to "development_apply" or
    # "test_apply" when the S4 -> S5 gate below rejected this cycle
    # before verification could start -- in that case there is no
    # testing_stage_result to report status from, because S5 never ran.
    # Set to "tool_unavailable" (CLAUDE-ADC-ZIELBILD-DIFF-FIX-001, A3)
    # when S5 Quality & Verification DID run and found a recoverable
    # TOOL_UNAVAILABLE outcome -- an environment/setup issue, never
    # source-code rework; see _tool_unavailable_result() below.
    failure_stage: str | None = None
    # A3: the VerificationPlan S5 actually executed, populated
    # alongside `verification_result` only for the "tool_unavailable"
    # terminal state -- together they carry everything the existing
    # app.missing_toolchain_setup.MissingToolchainSetupRequest contract
    # needs from S5 to reach S3.5 recovery, without S5 itself guessing
    # the additional S2/S3 context (EngineeringDecision/CouncilResult)
    # only a caller further up the stack actually has.
    verification_plan: object | None = None

    @property
    def status(self) -> str:
        """Expose the testing decision without introducing a second policy.

        A set `failure_stage` means S5 Quality & Verification's normal
        pass/fail/rework decision was never reached for this cycle.
        "tool_unavailable" is its own distinct terminal status (never
        folded into "apply_failed", which specifically means an S4
        mutation was rejected before S5 could even start); every other
        `failure_stage` value keeps reporting "apply_failed", read from
        `testing_stage_result` only when neither is set.
        """
        if self.failure_stage == "tool_unavailable":
            return "tool_unavailable"
        if self.failure_stage is not None:
            return "apply_failed"
        return self.testing_stage_result.status


def _pre_verification_apply_failure(development_result, test_changes, apply_result, failure_stage) -> "DevelopmentTestingResult":
    """The one place a rejected S4 mutation becomes the terminal result.

    S5-owned fields (test_result, testing_stage_result, verification_result)
    are left None -- accurately "not reached" -- rather than fabricated,
    since S5 Quality & Verification may start only after every required
    S4 mutation for this cycle applied successfully (see
    DevelopmentTestingStage.run below).
    """
    return DevelopmentTestingResult(
        development_result=development_result,
        test_changes=test_changes,
        apply_result=apply_result,
        test_result=None,
        testing_stage_result=None,
        verification_result=None,
        failure_stage=failure_stage,
    )


def _tool_unavailable_result(
    development_result, test_changes, apply_result, verification_plan, verification_result,
) -> "DevelopmentTestingResult":
    """A3: S5 found a recoverable TOOL_UNAVAILABLE verification outcome
    -- a missing executable/toolchain, i.e. an environment/setup issue,
    never source-code rework. test_result/testing_stage_result stay
    None (there is no real deterministic pass/fail verdict to report;
    folding TOOL_UNAVAILABLE into a failing TestResult is exactly the
    defect this closes), so ControlledReworkStage's own, unmodified
    `status != "rework_required"` check never starts Developer rework
    for this cycle. verification_plan/verification_result ARE carried
    (unlike the S4-apply-failure terminal state above) so a caller with
    the additional S2/S3 context S5 itself does not have
    (EngineeringDecision/CouncilResult) can construct the existing
    app.missing_toolchain_setup.MissingToolchainSetupRequest and reach
    the existing S3.5 Missing-Toolchain Setup contract unchanged."""
    return DevelopmentTestingResult(
        development_result=development_result,
        test_changes=test_changes,
        apply_result=apply_result,
        test_result=None,
        testing_stage_result=None,
        verification_result=verification_result,
        failure_stage="tool_unavailable",
        verification_plan=verification_plan,
    )


def _test_result_for_unexecuted_verification(steps) -> TestResult:
    """A2: reached only when generalized verification is configured but
    yields no genuinely executable evidence -- either Project
    Intelligence could not be built (`steps` is empty) or every planned
    VerificationStep is unsupported/not_applicable/deferred. Must never
    silently become "run pytest" (a guessed, single-stack fallback);
    instead this fails closed, honestly, using the SAME generalized
    verification evidence shape `_test_result_from_verification()`
    already produces for a real failure -- never a second, competing
    TestResult-construction policy."""
    if not steps:
        return TestResult(
            passed=False, return_code=1, stdout="",
            stderr=(
                "No verification steps could be planned for this project "
                "(Project Intelligence unavailable or no verifiable areas "
                "found)."
            ),
            command=("verification",), timed_out=False,
        )
    step_failures = tuple(_step_failure_evidence(s) for s in steps)
    return TestResult(
        passed=False, return_code=1,
        stdout=(
            f"No executable verification steps available; {len(steps)} "
            "step(s) unsupported/not applicable/deferred; see "
            "step_failures for per-step detail."
        ),
        stderr="", command=("verification",), timed_out=False,
        step_failures=step_failures,
    )


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
        if development_result.status != "success":
            # S4.3's own authoritative classification already says this
            # cycle's development mutation did not fully apply -- no
            # test generation, no application, no S5 inspection/plan/
            # execution/diagnosis may follow a change ADC cannot confirm
            # actually landed.
            return _pre_verification_apply_failure(development_result, None, None, "development_apply")

        test_changes = self._test_change_generator.generate(request)
        if test_changes.get("disposition") == TestChangeDisposition.NO_CHANGES_REQUIRED:
            # S4.2's own explicit, evidenced no-op (disposition + a
            # non-empty reason, already enforced by TestChangeGenerator):
            # there is no test mutation to attempt, so S4.3 is never
            # invoked and never asked to classify a nonexistent apply --
            # ChangeApplicationService.status_for() remains exclusively
            # about real apply attempts. `apply_result` stays None,
            # truthfully representing "no application attempt occurred",
            # and the cycle proceeds to S5 exactly as a successful apply
            # would have.
            apply_result = None
        else:
            is_rework = bool(getattr(request, "rework_request", None))
            apply_result = self._change_application.apply(
                request.project_path, test_changes, "test", is_rework,
                provenance_recorder=getattr(request, "provenance_recorder", None),
            )
            if ChangeApplicationService.status_for(apply_result) != "success":
                # Same invariant, for the test-file mutation: a skipped or
                # partially applied required test change means verification
                # would run against stale or incomplete project state.
                return _pre_verification_apply_failure(development_result, test_changes, apply_result, "test_apply")

        verification_result = None
        test_result = None

        if self._verification_registry is not None and self._project_inspector is not None:
            from app.verification import TOOL_UNAVAILABLE, build_verification_plan
            run_id = getattr(request, "run_id", "") or "unknown"
            try:
                intelligence = self._project_inspector.build_intelligence(request.project_path)
            except Exception:
                intelligence = None
            plan = build_verification_plan(intelligence, run_id)
            verification_result = self._verification_registry.execute_plan(plan)

            executable = [s for s in verification_result.steps
                          if s.status not in ("unsupported", "not_applicable", "deferred")]
            # A3: a recoverable TOOL_UNAVAILABLE outcome is an
            # environment/setup issue, not source-code rework -- stop
            # this cycle before it can ever be folded into a failing
            # TestResult and reach Developer rework.
            if any(s.status == TOOL_UNAVAILABLE.value for s in executable):
                return _tool_unavailable_result(
                    development_result, test_changes, apply_result, plan, verification_result,
                )
            if executable:
                test_result = _test_result_from_verification(executable)
            else:
                # A2: no valid executable VerificationStep exists
                # (Project Intelligence unavailable, or every step is
                # unsupported/not_applicable/deferred) -- must never
                # silently become "run pytest" (a guessed,
                # stack-specific fallback that could run pytest in a
                # non-Python repository). Fail closed, honestly, using
                # the real generalized verification evidence instead.
                test_result = _test_result_for_unexecuted_verification(verification_result.steps)
        else:
            # Legacy/unit-test compatibility only: the productive
            # canonical composition (see app.canonical_composition)
            # always supplies both verification_registry and
            # project_inspector, so this branch is not reachable from
            # productive S4/S5 orchestration -- it exists solely for
            # callers/tests that construct this stage without
            # generalized verification configured at all.
            test_result = self._project_test_runner.run(TestExecutionRequest(request.project_path))

        stage_result = self._testing_stage.run(development_result, test_result)
        return DevelopmentTestingResult(development_result, test_changes, apply_result, test_result, stage_result, verification_result=verification_result)
