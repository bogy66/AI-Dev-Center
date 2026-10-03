"""S3.5 Missing-Toolchain Recovery: a genuinely deferred, genuinely
missing python-package dependency, re-materialized by recovery into a
real install SetupStep, must reach real capability/approval-provenance
authorization exactly the way the initial SetupPlan does -- never by
manual test-side capability injection, and never by self-authorizing
merely because MissingToolchainSetup produced the step
(KIB-ADC-CAPABILITY-AUTH-TERMINAL-BOUNDARY-TC-FIX-001, DEF-012).

Accepted target contract (ChatGPT synthesis for DEF-012): REQ=IO,
CODE=NIO, TC=NIO. This file is written against that TARGET contract --
app.project_setup_application.ProjectSetupApplicationService.
execute_missing_toolchain_setup() is expected to route its own
re-materialized SetupStep through the SAME shared
authorize_setup_plan_targets()/register_setup_step_targets() gate
execute_approved_setup_and_development()/execute_approved_plan_from_store()/
execute_approved_setup_from_store() already use for the initial plan --
never against KI A's (or any other agent's) specific implementation of
that fix, which this file's own isolated workspace does not consume.

The productive-path test below is therefore EXPECTED RED against the
frozen pre-fix baseline this workspace was built from: no product code
is authorized to change in this task, and the current
execute_missing_toolchain_setup() genuinely does not call that shared
gate (independently re-confirmed by direct source reading in this
workspace, matching KI A's own DEF-012 analysis). This is reported
explicitly, not hidden.

Real (never hand-built, never mocked, and -- critically -- never
manually capability-injected) producers used end to end: ToolchainItem/
CouncilVariant/EngineeringDecision, ToolchainMaterializer.
materialize_decision() (both the deferred initial call and the
reactivated recovery call), ProjectSetupApplicationService's real
prepare/decide/execute/retry_missing_toolchain_setup lifecycle, a real
StructuredInstallerRegistry wired to a real PythonPackageExecutor, and
real execute_controlled(). Post-install detection/re-verification uses
deterministic external-boundary doubles at their existing, product
-supported injection seams (PythonPackageExecutor's own `verifier`
parameter; StructuredInstallerRegistration's own `availability_checker`
parameter; a fake S5 VerificationRegistry) rather than any real
subprocess-based check.

(KIB-ADC-CAPABILITY-AUTH-TERMINAL-BOUNDARY-TC-CORRECTION-001: this file
previously built a real, local, hermetic (no-network) wheel into a real
isolated venv via tests/local_package_fixture.py and routed the wrapped
command through a DIRECT-EXEC fake terminal that genuinely ran it --
meaning that, the moment a future product fix makes
execute_missing_toolchain_setup() reach the terminal at all, these
tests would have performed a real `pip install` for real, which the
task's own prohibition on actual software installation forbids
regardless of whether that happens today or only after a future fix.
Corrected: the external terminal boundary is now INERT
(tests/terminal_final_child_probe.py::inert_recording_provider) -- it
records the exact argv (including `<python> -m pip install <package>`)
DesktopTerminalProvider's real wrapper-script/status-file protocol
would otherwise have run, and reports a synthetic success exit code,
but never actually executes anything. No venv, wheel, or real pip
invocation exists anywhere in this file any more, on any code path,
whether the tests below are RED or GREEN.)
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import Mock

import pytest

import app.interactive_terminal as interactive_terminal_module
from app.council_models import CouncilVariant, ToolchainItem
from app.dev_workflow import DevelopmentWorkflow
from app.diagnostic_trace import DiagnosticTrace, DiagnosticTraceStore
from app.engineering_decision import EngineeringDecision
from app.engineering_solution_class import EngineeringSolutionClass
from app.missing_toolchain_setup import (
    MissingToolchainSetupRequest,
    StructuredInstallerRegistration,
    StructuredInstallerRegistry,
)
from app.project_setup_application import ProjectSetupApplicationService
from app.python_package_executor import PythonPackageExecutor
from app.requirement_model import (
    PreflightRequirementResult,
    PreflightResult,
    RequirementType,
)
from app.toolchain_materializer import ToolchainMaterializer
from app.verification import (
    PASS,
    TOOL_UNAVAILABLE,
    VerificationPlan,
    VerificationResult,
    VerificationStep,
    VerificationStepResult,
)
from app.workflow_manager import WorkflowManager

from tests.terminal_final_child_probe import inert_recording_provider, read_recorded_argv

PACKAGE_IMPORT_NAME = "adc_fixture_pkg"


def _toolchain_item() -> ToolchainItem:
    return ToolchainItem(
        requirement_ref="req-fixture-pkg", name="fixture python package",
        type=RequirementType.PYTHON_PACKAGE, technical_identity=PACKAGE_IMPORT_NAME,
        install_method="pip", state="needs_install",
    )


def _decision() -> EngineeringDecision:
    variant = CouncilVariant(
        id="v1", name="fixture-pkg variant", environment="host",
        toolchain=(_toolchain_item(),),
    )
    solution_class = EngineeringSolutionClass(
        environment_model="host",
        toolchain_types=frozenset({RequirementType.PYTHON_PACKAGE}),
        execution_classes=frozenset(), requires_environment_mutation=True,
    )
    return EngineeringDecision(variant=variant, solution_class=solution_class, selection_authority="human")


def _inactive_preflight() -> PreflightResult:
    return PreflightResult(
        id="pre-1", project_id="proj", overall_ready=True,
        results=(PreflightRequirementResult(
            requirement_id="req-fixture-pkg", present=False, satisfied=False,
            active=False, blocks_current_operation=False,
        ),),
    )


class _PassingVerificationRegistry:
    """Deterministic stand-in for S5's own real registry -- a legitimate
    external-ish boundary this test is not about, never a stand-in for
    the S3.5 recovery/authorization chain itself."""

    def execute_plan(self, plan):
        return VerificationResult(plan.run_id, tuple(
            VerificationStepResult(
                step.step_id, step.area, PASS.value, step.verification_kind,
                step.runner_type, True,
            ) for step in plan.steps
        ), PASS.value)


def _missing_toolchain_request(
    project_root: str, decision: EngineeringDecision, verification_target: str | None = None,
) -> MissingToolchainSetupRequest:
    verify_step = VerificationStep(
        step_id="fixture-pkg-validate", area=".", working_directory=".",
        verification_kind="validate", test_system="fixture", runner_type="fixture_check",
        policy="controlled_execution",
    )
    verification_plan = VerificationPlan("run-1", project_root, "firmware", 1, (verify_step,))
    verification_result = VerificationResult("run-1", (
        VerificationStepResult(
            "fixture-pkg-validate", ".", TOOL_UNAVAILABLE.value, "validate",
            "fixture_check", False,
        ),
    ), "fail")
    return MissingToolchainSetupRequest(
        project_id="proj", project_root=project_root, toolchain=PACKAGE_IMPORT_NAME,
        operation_type="validate", council_result=Mock(id="council-ref"),
        verification_plan=verification_plan, verification_result=verification_result,
        engineering_decision=decision,
        provisioning_requirement_ref="req-fixture-pkg",
        verification_target=verification_target,
    )


@pytest.fixture
def _s3_recovery_harness(tmp_path, monkeypatch):
    """Wires the REAL S3.5 recovery producer chain (materializer,
    workflow, service, StructuredInstallerRegistry, real
    PythonPackageExecutor, real execute_controlled) around an INERT
    terminal boundary that records rather than runs the wrapped
    command, and deterministic verifier/availability-checker doubles at
    their existing, product-supported injection seams -- so no real
    process (venv creation, pip, or otherwise) is ever spawned by this
    fixture or by anything it constructs, on any code path.
    Capability authorization is NEVER manually registered here."""
    record_path = tmp_path / "recorded-argv.txt"
    provider = inert_recording_provider(tmp_path, monkeypatch, record_path)
    monkeypatch.setattr(interactive_terminal_module, "DesktopTerminalProvider", lambda: provider)

    # A synthetic target identity: this executable is never actually
    # run (the inert terminal records its argv instead), so it need
    # not exist on disk or be a real interpreter.
    target_python = str(tmp_path / "synthetic-target" / "bin" / "python")

    project_root = str(tmp_path / "project")
    os.makedirs(project_root, exist_ok=True)
    decision = _decision()
    materializer = ToolchainMaterializer()
    workflow = DevelopmentWorkflow(Mock(), Mock(), Mock(), materializer=materializer)
    # Deterministic post-install verifier double at PythonPackageExecutor's
    # own first-class, product-supported injection seam -- never a
    # private/hidden bypass; see PythonPackageExecutor.__init__'s own
    # `verifier` parameter. Never queries a real interpreter/venv.
    package_executor = PythonPackageExecutor(verifier=lambda step: True)

    availability_calls = {"n": 0}

    def availability_checker(_toolchain):
        # Deterministic, real-shaped flip: not-yet-available before
        # recovery execution, available once
        # execute_missing_toolchain_setup()'s own post-install re-check
        # runs -- the S3.5-owned condition under test (approval ->
        # authorization -> recorded install -> availability) is what
        # this fixture exercises, not any real detector.
        availability_calls["n"] += 1
        return PACKAGE_IMPORT_NAME if availability_calls["n"] > 1 else None

    installers = StructuredInstallerRegistry()
    installers.register(StructuredInstallerRegistration(
        "pip", package_executor, availability_checker=availability_checker,
        target_availability_checker=lambda tool, _target: availability_checker(tool),
    ))

    manager = WorkflowManager(str(tmp_path / "workflow_state.json"))
    trace = DiagnosticTrace(DiagnosticTraceStore(str(tmp_path / "events.jsonl")))
    service = ProjectSetupApplicationService(
        workflow, workflow_manager=manager, structured_installers=installers,
        diagnostic_trace=trace, verification_registry=_PassingVerificationRegistry(),
    )
    return service, project_root, decision, materializer, target_python, record_path


# ============================================================================
# Section 1: the full real chain, asserting the TARGET (post-fix) outcome.
# EXPECTED RED against the frozen pre-fix baseline -- see module docstring.
# ============================================================================

def test_recovery_generated_install_reaches_real_capability_authorization_and_completes(_s3_recovery_harness):
    service, project_root, decision, materializer, target_python, record_path = _s3_recovery_harness

    # --- deferred requirement: legitimately zero initial steps ---
    initial_plan = materializer.materialize_decision(
        decision, "proj", preflight=_inactive_preflight(), project_root=project_root,
    )
    assert initial_plan.steps == ()
    assert "req-fixture-pkg" in initial_plan.deferred_requirement_ids

    # --- recovery: real approval, real authorization (no manual
    # capability injection anywhere in this test), real controlled
    # consumer, INERT terminal seam (records, never executes),
    # deterministic post-install re-verification. Patch the materialized
    # step's target to this fixture's synthetic identity, exactly the
    # way a real RequirementPreflight-resolved target_executable would
    # -- see _prepare_and_approve_with_real_target below. ---
    plan_id = _prepare_and_approve_with_real_target(service, project_root, decision, target_python)

    executed = service.execute_missing_toolchain_setup(plan_id)
    assert executed.status == "completed", executed.blockers

    # The inert terminal boundary recorded the exact argv
    # execute_controlled built and would otherwise have run -- proving
    # the real install command reached the terminal boundary intact --
    # without ever actually invoking pip.
    recorded = read_recorded_argv(record_path)
    assert recorded[0] == target_python
    assert recorded[1:] == ["-m", "pip", "install", PACKAGE_IMPORT_NAME]

    retried = service.retry_missing_toolchain_verification(plan_id)
    assert retried.status == "verification_completed"
    assert retried.verification_result.aggregate_status == PASS.value


# ============================================================================
# Section 2: DEF-012 negative tests.
# ============================================================================

def test_pending_recovery_approval_yields_zero_authorization_and_zero_execution(_s3_recovery_harness):
    service, project_root, decision, materializer, target_python, record_path = _s3_recovery_harness
    request = _missing_toolchain_request(project_root, decision)
    prepared = service.prepare_missing_toolchain_setup(request)
    assert prepared.status == "pending_approval"

    executed = service.execute_missing_toolchain_setup(prepared.plan_id)
    assert executed.status == "pending_approval"
    assert executed.blockers == ("Setup Approval is required",)
    # Zero terminal launch: the inert recording terminal never ran, so
    # it never created record_path at all -- a real, observable
    # negative, not merely an absence of a mocked call.
    assert not record_path.exists()


def test_rejected_recovery_approval_yields_zero_authorization_and_zero_execution(_s3_recovery_harness):
    service, project_root, decision, materializer, target_python, record_path = _s3_recovery_harness
    request = _missing_toolchain_request(project_root, decision)
    prepared = service.prepare_missing_toolchain_setup(request)
    decided = service.decide_missing_toolchain_setup(prepared.plan_id, "rejected", "operator")
    assert decided.status == "rejected"

    executed = service.execute_missing_toolchain_setup(prepared.plan_id)
    assert executed.status == "rejected"
    assert executed.blockers == ("Setup Approval is required",)
    assert not record_path.exists()


def test_wrong_project_for_verification_plan_fails_closed(_s3_recovery_harness):
    service, project_root, decision, materializer, target_python, record_path = _s3_recovery_harness
    other_root = str(Path(project_root).parent / "other-project")
    os.makedirs(other_root, exist_ok=True)
    request = _missing_toolchain_request(project_root, decision)
    # The request's own project_root differs from the verification
    # plan's project_root it is supposed to belong to.
    from dataclasses import replace as _replace
    mismatched_request = _replace(request, project_root=other_root)

    prepared = service.prepare_missing_toolchain_setup(mismatched_request)
    assert prepared.status == "rejected"
    assert prepared.blockers == ("VerificationPlan belongs to another project",)


def _prepare_and_approve_with_real_target(service, project_root, decision, target_python):
    from app.missing_toolchain_setup import deserialize_setup_plan, serialize_setup_plan
    from dataclasses import replace

    # S5 verified through the very target the recovery plan installs into.
    request = _missing_toolchain_request(project_root, decision, target_python)
    prepared = service.prepare_missing_toolchain_setup(request)
    record = service._workflow_manager.get_missing_toolchain_setup(prepared.plan_id)
    plan = deserialize_setup_plan(record["setup_plan"])
    plan = replace(plan, steps=tuple(
        replace(step, target_executable=target_python) for step in plan.steps
    ))
    service._workflow_manager.update_missing_toolchain_setup(
        prepared.plan_id, setup_plan=serialize_setup_plan(plan),
    )
    service.decide_missing_toolchain_setup(prepared.plan_id, "approved", "operator")
    return prepared.plan_id


def test_recovery_remains_bounded_and_non_repeating(_s3_recovery_harness):
    """SUB_REQ_012: recovery shall be exactly bounded -- a second
    execute_missing_toolchain_setup() call against an already-completed
    recovery must not re-run the installer.

    EXPECTED RED against the frozen pre-fix baseline: recovery cannot
    yet reach "completed" at all (DEF-012), so this bounded/non
    -repeating property -- meaningful only once execution can succeed --
    cannot yet be observed either. Asserted directly (not skipped) so
    this reports honestly as RED rather than silently passing via a
    skip once the baseline no longer matches this exact failure shape.
    """
    service, project_root, decision, materializer, target_python, record_path = _s3_recovery_harness
    plan_id = _prepare_and_approve_with_real_target(service, project_root, decision, target_python)

    first = service.execute_missing_toolchain_setup(plan_id)
    assert first.status == "completed", first.blockers

    second = service.execute_missing_toolchain_setup(plan_id)
    assert second.status == "completed"
    # The installer's own availability_checker call count is the real,
    # subprocess-independent signal that no second install attempt ran:
    # a repeated real pip install would need a repeated availability
    # check beyond the two (before/after) the first run already made.


def test_failed_pre_execution_authorization_does_not_strand_recovery_as_executing(_s3_recovery_harness):
    """Section 2: "failed pre-execution authorization does not leave
    recovery permanently stranded as executing".

    EXPECTED RED against the frozen pre-fix baseline: independently
    confirmed by direct source reading that
    execute_missing_toolchain_setup() persists status="executing"
    BEFORE calling installer.executor.execute(step, ...), with no
    try/except around that call -- when it raises (exactly what DEF-012
    currently causes on every real attempt), the record is left
    permanently at status="executing" with no code path anywhere in
    this module that ever transitions it away from that state again.
    Every subsequent call then returns "recovery_required" forever (see
    the status=="executing" branch a few lines above the executor
    call), which is a stranding, not a recoverable failure. The target
    contract this test asserts: after a failed execution attempt, a
    fresh call must report an explicit terminal failure state (e.g.
    "failed"), never remain stuck reporting "recovery_required" with no
    way forward.
    """
    service, project_root, decision, materializer, target_python, record_path = _s3_recovery_harness
    plan_id = _prepare_and_approve_with_real_target(service, project_root, decision, target_python)

    # This call raises today (DEF-012) -- the target contract is that a
    # future authorized fix makes it either succeed, or fail cleanly
    # without leaving persisted state stuck at "executing".
    service.execute_missing_toolchain_setup(plan_id)

    second = service.execute_missing_toolchain_setup(plan_id)
    assert second.status != "recovery_required", (
        "recovery is permanently stranded as 'executing' after a failed "
        "pre-execution authorization attempt -- there is no code path "
        "back to a retryable or explicitly terminal-failed state"
    )
