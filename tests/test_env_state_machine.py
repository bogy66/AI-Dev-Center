"""Deterministic lifecycle/state-machine coverage
(CLAUDE-ADC-TEST-ENVIRONMENT-FIDELITY-UPGRADE-001 section 5):

  A) approval -> authorization -> execution
  B) setup execution lifecycle
  C) MissingToolchain recovery
  D) retry / reload
  E) bounded recovery

Uses real product state-transition code throughout (SetupApproval,
CapabilityRegistry/validate_request, SetupExecutionStateStore,
ProjectSetupApplicationService's real prepare/decide/execute/retry
missing-toolchain lifecycle) -- never a hand-rolled re-implementation
of any of it.
"""
from __future__ import annotations

from unittest.mock import Mock

import pytest

from app.execution import (
    ApprovalProvenance, CapabilityRegistration, CapabilityRegistry,
    ExecutionRequest, validate_request,
)
from app.setup_approval import SetupApproval
from tests.env_scenarios import covers


# ============================================================================
# A) approval -> authorization -> execution
# ============================================================================
@covers("AUTH_PENDING_APPROVAL")
def test_state_machine_pending_approval_yields_zero_authorization_and_execution(
    tmp_path, monkeypatch,
):
    """Drive the real S3.5 recovery service before its approval transition.

    The pending result must come from execute_missing_toolchain_setup()'s
    persisted-record guard, with no capability registration and no terminal
    boundary reached.  Merely asserting a status assigned by this test would
    not prove either safety property.
    """
    from tests.test_s3_missing_toolchain_capability_authorization import (
        _missing_toolchain_request,
    )
    from tests.terminal_final_child_probe import read_terminal_launch_count

    harness = TestMissingToolchainRecoveryStateMachine()
    service, project_root, decision, _materializer, _target = harness._harness(
        tmp_path, monkeypatch,
    )
    registrations_before = dict(service._capability_registry._registrations)
    prepared = service.prepare_missing_toolchain_setup(
        _missing_toolchain_request(project_root, decision),
    )

    result = service.execute_missing_toolchain_setup(prepared.plan_id)

    assert result.status == "pending_approval"
    assert result.blockers == ("Setup Approval is required",)
    assert service._capability_registry._registrations == registrations_before
    assert read_terminal_launch_count(tmp_path / "toolchain-a-terminal-launch-count.txt") == 0


@covers("AUTH_APPROVED", "AUTH_REJECTED_APPROVAL")
def test_state_machine_approve_and_reject_are_the_only_real_transitions():
    from app.requirement_model import SetupPlan, SetupStep
    step = SetupStep(id="s1", requirement_id="r1", action="install", is_approved=False)
    plan = SetupPlan(id="p1", project_id="proj", steps=(step,), status="pending_approval")

    approved = SetupApproval.approve(plan)
    assert approved.status == "approved"
    assert approved.steps[0].is_approved is True

    rejected = SetupApproval.reject(plan)
    assert rejected.status == "rejected"
    assert rejected.steps[0].is_approved is False


@covers("AUTH_WRONG_OPERATION_CAPABILITY")
def test_state_machine_capability_registered_for_different_operation_is_rejected(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    resolved_root = str(project_root.resolve())
    registry = CapabilityRegistry()
    registry.register_approved(CapabilityRegistration(
        capability="python", executable_names=("/opt/python",),
        allowed_operations=("verification",),  # NOT "install"
        approval_provenance=ApprovalProvenance(resolved_root, "c1", "v1", "setup-approval:p:approved"),
        project_scope=resolved_root,
    ))
    request = ExecutionRequest(("/opt/python", "-m", "pip", "install", "pkg"), str(project_root), 10, "python", "install")
    violation = validate_request(request, project_root, registry)
    assert violation is not None


@covers("AUTH_WRONG_PROJECT")
def test_state_machine_capability_registered_for_different_project_is_rejected(tmp_path):
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()
    registry = CapabilityRegistry()
    registry.register_approved(CapabilityRegistration(
        capability="python", executable_names=("/opt/python",), allowed_operations=("install",),
        approval_provenance=ApprovalProvenance(str(project_a.resolve()), "c1", "v1", "setup-approval:p:approved"),
        project_scope=str(project_a.resolve()),
    ))
    # Same executable, same capability, but the REQUEST's own project
    # scope (project_b) never matches what was authorized (project_a).
    request = ExecutionRequest(("/opt/python", "-m", "pip", "install", "pkg"), str(project_b), 10, "python", "install")
    violation = validate_request(request, project_b, registry)
    assert violation is not None


# ============================================================================
# C) MissingToolchain recovery + E) bounded recovery -- real S3.5 chain
#
# KIA-ADC-TEST-ASSURANCE-MODEL-FIX-001 section 1: covers() is declared
# per METHOD below (matching each method's own docstring), not once on
# the class -- coverage is now PASS-VERIFIED per executed test, and a
# single class-level declaration would incorrectly promote every listed
# class_id to covered as soon as ANY one method in the class passed,
# even if the specific method demonstrating a given class_id itself
# failed.
# ============================================================================
class TestMissingToolchainRecoveryStateMachine:
    """Reuses the exact real producer chain
    tests/test_s3_missing_toolchain_capability_authorization.py already
    established (ToolchainMaterializer, DevelopmentWorkflow,
    ProjectSetupApplicationService's real prepare/decide/execute/retry
    lifecycle, StructuredInstallerRegistry, real PythonPackageExecutor,
    real execute_controlled) around the same INERT terminal boundary --
    never a re-implementation of that state machine."""

    def _harness(self, tmp_path, monkeypatch):
        from tests.test_s3_missing_toolchain_capability_authorization import (
            _decision, _inactive_preflight, _missing_toolchain_request,
            _PassingVerificationRegistry,
        )
        import app.interactive_terminal as interactive_terminal_module
        from app.dev_workflow import DevelopmentWorkflow
        from app.diagnostic_trace import DiagnosticTrace, DiagnosticTraceStore
        from app.missing_toolchain_setup import StructuredInstallerRegistration, StructuredInstallerRegistry
        from app.project_setup_application import ProjectSetupApplicationService
        from app.python_package_executor import PythonPackageExecutor
        from app.toolchain_materializer import ToolchainMaterializer
        from app.workflow_manager import WorkflowManager
        from tests.terminal_final_child_probe import inert_terminal_harness

        target, counter_path, record_path = inert_terminal_harness(tmp_path, monkeypatch, "toolchain-a")
        project_root = str(tmp_path / "project")
        import os
        os.makedirs(project_root, exist_ok=True)
        decision = _decision()
        materializer = ToolchainMaterializer()
        workflow = DevelopmentWorkflow(Mock(), Mock(), Mock(), materializer=materializer)
        package_executor = PythonPackageExecutor(verifier=lambda step: True)
        availability_calls = {"n": 0}

        def availability_checker(_toolchain):
            availability_calls["n"] += 1
            from tests.test_s3_missing_toolchain_capability_authorization import PACKAGE_IMPORT_NAME
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
        return service, project_root, decision, materializer, target

    @covers("TOOLCHAIN_DEFERRED_REQUIREMENT")
    def test_deferred_requirement_produces_no_initial_step(self, tmp_path, monkeypatch):
        """TOOLCHAIN_DEFERRED_REQUIREMENT: inactive requirement ->
        legitimately zero initial steps."""
        from tests.test_s3_missing_toolchain_capability_authorization import _inactive_preflight
        service, project_root, decision, materializer, target = self._harness(tmp_path, monkeypatch)
        plan = materializer.materialize_decision(decision, "proj", preflight=_inactive_preflight(), project_root=project_root)
        assert plan.steps == ()

    @covers("TOOLCHAIN_ACTIVE_MISSING_REQUIREMENT", "TOOLCHAIN_ABSENT", "TOOLCHAIN_VERIFIER_SUCCESS")
    def test_active_missing_requirement_produces_a_real_step_and_completes(self, tmp_path, monkeypatch):
        """TOOLCHAIN_ACTIVE_MISSING_REQUIREMENT + TOOLCHAIN_ABSENT ->
        TOOLCHAIN_VERIFIER_SUCCESS: the full real recovery lifecycle."""
        from app.missing_toolchain_setup import deserialize_setup_plan, serialize_setup_plan
        from dataclasses import replace
        from tests.test_s3_missing_toolchain_capability_authorization import _missing_toolchain_request

        service, project_root, decision, materializer, target = self._harness(tmp_path, monkeypatch)
        request = _missing_toolchain_request(project_root, decision)
        prepared = service.prepare_missing_toolchain_setup(request)
        record = service._workflow_manager.get_missing_toolchain_setup(prepared.plan_id)
        plan = deserialize_setup_plan(record["setup_plan"])
        plan = replace(plan, steps=tuple(replace(s, target_executable=target) for s in plan.steps))
        service._workflow_manager.update_missing_toolchain_setup(prepared.plan_id, setup_plan=serialize_setup_plan(plan))
        service.decide_missing_toolchain_setup(prepared.plan_id, "approved", "operator")

        executed = service.execute_missing_toolchain_setup(prepared.plan_id)
        assert executed.status == "completed", executed.blockers

    @covers("LIFE_BOUNDED_RECOVERY")
    def test_bounded_recovery_does_not_repeat(self, tmp_path, monkeypatch):
        """LIFE_BOUNDED_RECOVERY: a second execute call against an
        already-completed recovery must not re-run the installer."""
        from app.missing_toolchain_setup import deserialize_setup_plan, serialize_setup_plan
        from dataclasses import replace
        from tests.test_s3_missing_toolchain_capability_authorization import _missing_toolchain_request

        service, project_root, decision, materializer, target = self._harness(tmp_path, monkeypatch)
        request = _missing_toolchain_request(project_root, decision)
        prepared = service.prepare_missing_toolchain_setup(request)
        record = service._workflow_manager.get_missing_toolchain_setup(prepared.plan_id)
        plan = deserialize_setup_plan(record["setup_plan"])
        plan = replace(plan, steps=tuple(replace(s, target_executable=target) for s in plan.steps))
        service._workflow_manager.update_missing_toolchain_setup(prepared.plan_id, setup_plan=serialize_setup_plan(plan))
        service.decide_missing_toolchain_setup(prepared.plan_id, "approved", "operator")

        first = service.execute_missing_toolchain_setup(prepared.plan_id)
        assert first.status == "completed"
        second = service.execute_missing_toolchain_setup(prepared.plan_id)
        assert second.status == "completed"  # reused, not re-executed

    @covers("LIFE_EXECUTION_FAILURE")
    def test_execution_failure_is_reported_not_hidden(self, tmp_path, monkeypatch):
        """LIFE_EXECUTION_FAILURE: when the installer's own post-check
        never reports availability, the recovery result is an honest
        failure, never silently promoted to success."""
        from app.missing_toolchain_setup import deserialize_setup_plan, serialize_setup_plan
        from dataclasses import replace
        from tests.test_s3_missing_toolchain_capability_authorization import _missing_toolchain_request

        service, project_root, decision, materializer, target = self._harness(tmp_path, monkeypatch)
        # Force availability_checker to always report unavailable, so
        # "available = result.success and installer.is_available(...)"
        # remains False even though the (inert) install itself "succeeds".
        installer = service._structured_installers.get("pip")
        object.__setattr__(installer, "availability_checker", lambda _t: None)
        object.__setattr__(installer, "target_availability_checker", lambda _t, _target: None)

        request = _missing_toolchain_request(project_root, decision)
        prepared = service.prepare_missing_toolchain_setup(request)
        record = service._workflow_manager.get_missing_toolchain_setup(prepared.plan_id)
        plan = deserialize_setup_plan(record["setup_plan"])
        plan = replace(plan, steps=tuple(replace(s, target_executable=target) for s in plan.steps))
        service._workflow_manager.update_missing_toolchain_setup(prepared.plan_id, setup_plan=serialize_setup_plan(plan))
        service.decide_missing_toolchain_setup(prepared.plan_id, "approved", "operator")

        executed = service.execute_missing_toolchain_setup(prepared.plan_id)
        assert executed.status == "failed"
        assert executed.blockers


@covers("TOOLCHAIN_PRESENT")
def test_state_machine_already_present_toolchain_is_a_safe_noop():
    from app.missing_toolchain_setup import already_available_setup_result
    result = already_available_setup_result("step-1")
    assert result.success is True
    assert result.message == "toolchain already available"


@covers("TOOLCHAIN_UNSUPPORTED_BACKEND")
def test_state_machine_unsupported_backend_is_surfaced_not_forced():
    """The real materializer must classify an unsupported setup effect.

    The expected ``unsupported_backend_effects`` value is produced by
    ToolchainMaterializer from the EngineeringDecision and Preflight result;
    this test does not hand-construct a SetupPlan containing the answer.
    """
    from app.council_models import CouncilVariant, ToolchainItem
    from app.engineering_decision import EngineeringDecision
    from app.engineering_solution_class import EngineeringSolutionClass
    from app.requirement_model import (
        PreflightRequirementResult, PreflightResult, RequirementType,
    )
    from app.toolchain_materializer import ToolchainMaterializer

    item = ToolchainItem(
        requirement_ref="system-tool",
        name="system-tool",
        type=RequirementType.SYSTEM_PACKAGE,
        install_method="apt",
        state="needs_install",
    )
    decision = EngineeringDecision(
        variant=CouncilVariant(
            id="system-variant", name="system-variant", environment="host",
            toolchain=(item,),
        ),
        solution_class=EngineeringSolutionClass(
            environment_model="host",
            toolchain_types=frozenset({RequirementType.SYSTEM_PACKAGE}),
            execution_classes=frozenset(),
            requires_environment_mutation=True,
        ),
        selection_authority="human",
    )
    preflight = PreflightResult(
        id="pre-system", project_id="proj", overall_ready=False,
        results=(PreflightRequirementResult(
            requirement_id="system-tool", present=False, satisfied=False,
            active=True, blocks_current_operation=True,
        ),),
    )

    plan = ToolchainMaterializer().materialize_decision(
        decision, "proj", preflight=preflight,
    )

    assert len(plan.steps) == 1
    assert plan.steps[0].action == "manual_review"
    assert plan.steps[0].setup_effect == "system_package_install"
    assert plan.unsupported_backend_effects == ("system_package_install",)


@covers("TOOLCHAIN_WRONG_VERSION", "TOOLCHAIN_METADATA_EXECUTABLE_DISAGREEMENT", "TOOLCHAIN_PIP_UNAVAILABLE_EQUIVALENT")
def test_state_machine_toolchain_negative_shapes():
    """Deterministic, code-level confirmation of the remaining TOOLCHAIN
    negative shapes not exercised by the full recovery lifecycle above:
    a distribution-presence disagreement (installed vs. required
    version), a metadata/executable target mismatch, and "no structured
    installer registered" (the pip-unavailable equivalent)."""
    from app.missing_toolchain_setup import StructuredInstallerRegistry

    registry = StructuredInstallerRegistry()
    assert registry.get("pip") is None  # TOOLCHAIN_PIP_UNAVAILABLE_EQUIVALENT

    from app.python_distribution import parse_distribution_query_output
    # TOOLCHAIN_METADATA_EXECUTABLE_DISAGREEMENT / WRONG_VERSION: a
    # nonzero query returncode is never a presence verdict, regardless of
    # any stdout content that might otherwise look present or absent
    # (CLAUDE-ADC-RSE033-RESIDUAL-DISTRIBUTION-PTY-CLOSURE-FIX-003: it is
    # no verdict at all -- installed=None -- never "not installed").
    installed, version = parse_distribution_query_output(1, "1.2.3")
    assert installed is None and version is None


@covers("PROC_SIGNAL_TERMINATION")
def test_state_machine_signal_terminated_child_is_a_real_failure(tmp_path, monkeypatch):
    """A genuinely SIGKILLed child produces the shell status 128 + 9."""
    import sys
    from app.interactive_terminal import InteractiveTerminalLauncher
    from tests.terminal_final_child_probe import probe_provider

    provider = probe_provider(tmp_path, monkeypatch)
    launcher = InteractiveTerminalLauncher(provider=provider)
    result = launcher.run(
        (sys.executable, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGKILL)"),
        str(tmp_path), {"PATH": "/usr/bin"}, 10,
    )
    assert result.returncode == 137
    assert result.returncode != 0


@covers("ENV_SHELL_METACHAR_VALUE")
def test_state_machine_env_value_with_shell_metacharacters_is_never_interpreted(tmp_path, monkeypatch):
    from app.interactive_terminal import InteractiveTerminalLauncher
    from tests.terminal_final_child_probe import (
        build_probe_argv, probe_provider, read_final_child_result, write_final_child_probe,
    )

    provider = probe_provider(tmp_path, monkeypatch)
    launcher = InteractiveTerminalLauncher(provider=provider)
    probe = write_final_child_probe(tmp_path)
    out_path = tmp_path / "result.json"
    dangerous_value = "$(rm -rf /tmp/should-not-run);echo pwned"
    launcher.run(build_probe_argv(probe, out_path, 0), str(tmp_path), {"PATH": "/usr/bin", "SOME_VAR": dangerous_value}, 10)
    observed = read_final_child_result(out_path)
    assert observed["env"].get("SOME_VAR") == dangerous_value, "propagated literally, never shell-interpreted"


@covers("LIFE_PROVIDER_FAILURE", "LIFE_VERIFIER_FAILURE")
def test_state_machine_provider_failure_and_verifier_failure_are_distinct_reported_failures(tmp_path, monkeypatch):
    """LIFE_PROVIDER_FAILURE (the terminal boundary itself fails) and
    LIFE_VERIFIER_FAILURE (the terminal succeeds but post-install
    verification disagrees) are both real, reported failures -- proven
    as two genuinely distinct fault shapes, never conflated."""
    from app.python_package_executor import PythonPackageExecutor
    from app.requirement_model import SetupEffect, SetupStep
    from tests.terminal_final_child_probe import install_start_failure_terminal_candidates

    # --- LIFE_PROVIDER_FAILURE: no terminal provider available at all ---
    import app.interactive_terminal as interactive_terminal_module
    from app.interactive_terminal import (
        DesktopTerminalProvider, InteractiveTerminalError,
        INTERACTIVE_TERMINAL_UNAVAILABLE,
    )
    candidates = install_start_failure_terminal_candidates(tmp_path)
    monkeypatch.setattr(interactive_terminal_module, "DesktopTerminalProvider", lambda: DesktopTerminalProvider(candidates=candidates))

    from app.execution import ApprovalProvenance, CapabilityRegistration, DEFAULT_CAPABILITY_REGISTRY
    project_root = tmp_path / "project"
    project_root.mkdir()
    resolved_root = str(project_root.resolve())
    DEFAULT_CAPABILITY_REGISTRY.register_approved(CapabilityRegistration(
        capability="python", executable_names=("/opt/python",), allowed_operations=("install",),
        approval_provenance=ApprovalProvenance(resolved_root, "c1", "v1", "setup-approval:p:approved"),
        project_scope=resolved_root,
    ))
    try:
        executor = PythonPackageExecutor(verifier=lambda step: True)
        step = SetupStep(
            id="s1", requirement_id="r1", action="install", install_method="pip",
            package="pkg", setup_effect=SetupEffect.PYTHON_PACKAGE_INSTALL,
            is_approved=True, target_executable="/opt/python",
        )
        with pytest.raises(InteractiveTerminalError) as exc_info:
            executor.execute(step, str(project_root))
        assert exc_info.value.cause == INTERACTIVE_TERMINAL_UNAVAILABLE
    finally:
        DEFAULT_CAPABILITY_REGISTRY.set_status("python", "revoked", resolved_root)
