"""IF_REQ_037 developer regressions: structured installer identity
resolution, explicit tool -> provisioning-requirement correlation, and the
productive S5 -> S3.5 recovery seam.

External boundaries substituted, and nothing else:
  - the LLM/provider behind DeveloperAgent/TestChangeGenerator/
    DiagnosisReviewer (a deterministic fake executor);
  - the host PATH lookup ESPHomeCheckRunner performs (``shutil.which``),
    so the real runner reports TOOL_UNAVAILABLE deterministically;
  - the installation terminal (the existing INERT recording terminal: it
    records the argv and never runs pip);
  - post-install detection at the existing ``verifier`` /
    ``availability_checker`` injection seams.
Every internal artifact (VerificationPlan, VerificationResult,
EngineeringDecision, WorkflowResult, recovery record, SetupPlan) is
produced by its real producer. ESPHome appears only as a specimen.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

import app.interactive_terminal as interactive_terminal_module
import app.verification as verification_module
from app.approved_plan_content import ApprovedPlanContentStore
from app.council_models import CouncilResult, CouncilVariant, ToolchainItem
from app.dev_workflow import DevelopmentWorkflow, WorkflowExecutionError
from app.developer_file_applier import DeveloperFileApplier
from app.development_stage import DeveloperAgent, DevelopmentStage
from app.development_testing_stage import DevelopmentTestingStage
from app.diagnostic_trace import DiagnosticTrace, DiagnosticTraceStore
from app.engineering_decision import EngineeringDecision
from app.engineering_solution_class import EngineeringSolutionClass
from app.execution import resolve_structured_installer_identity
from app.missing_toolchain_setup import (
    MissingToolchainSetupError,
    StructuredInstallerRegistration,
    StructuredInstallerRegistry,
    correlate_provisioning_requirement,
)
from app.project_inspector import ProjectInspector
from app.project_setup_application import ProjectSetupApplicationService
from app.python_package_executor import PythonPackageExecutor
from app.requirement_model import (
    PreflightRequirementResult,
    PreflightResult,
    RequirementType,
    SetupEffect,
    SetupStep,
)
from app.setup_approval import SetupApproval
from app.setup_execution_state import SetupExecutionStateStore
from app.test_change_generator import TestChangeGenerator
from app.testing_stage import DiagnosisReviewer, TestingStage
from app.toolchain_materializer import ToolchainMaterializer
from app.verification import PASS, TOOL_UNAVAILABLE, build_default_registry
from app.workflow_manager import WorkflowManager

from tests.terminal_final_child_probe import inert_recording_provider, read_recorded_argv

PACKAGE = "esphome"          # package (distribution) identity of the specimen
EXECUTABLE = "esphome"       # executable identity the S5 runner looks up
PKG_REF = "req-tool-package"
CLI_REF = "req-tool-cli"


def _package_item(install_method="pip", requirement_ref=PKG_REF, technical_identity=PACKAGE):
    return ToolchainItem(
        requirement_ref=requirement_ref, name="Specimen Python package",
        type=RequirementType.PYTHON_PACKAGE, technical_identity=technical_identity,
        install_method=install_method, state="needs_install",
    )


def _cli_item(provided_by=PKG_REF, technical_identity=EXECUTABLE, requirement_ref=CLI_REF):
    return ToolchainItem(
        requirement_ref=requirement_ref, name="Specimen CLI",
        type=RequirementType.EXECUTABLE, technical_identity=technical_identity,
        state="needs_install", provided_by=provided_by,
    )


def _decision(*items):
    variant = CouncilVariant(id="v1", name="specimen", environment="host", toolchain=tuple(items))
    solution_class = EngineeringSolutionClass(
        environment_model="host",
        toolchain_types=frozenset(item.type for item in items),
        execution_classes=frozenset(), requires_environment_mutation=True,
    )
    return EngineeringDecision(variant=variant, solution_class=solution_class, selection_authority="human")


def _preflight(active: bool, *refs):
    return PreflightResult(
        id="pre", project_id="proj", overall_ready=True,
        results=tuple(PreflightRequirementResult(
            requirement_id=ref, present=False, satisfied=False,
            active=active, blocks_current_operation=active,
        ) for ref in refs),
    )


def _canonical_installers(executor, availability_checker=None):
    """The same registrations app.canonical_composition makes."""
    installers = StructuredInstallerRegistry()
    kwargs = {} if availability_checker is None else {
        "availability_checker": availability_checker,
        # the same simulated availability, asked for the selected target
        "target_availability_checker": lambda name, _target: availability_checker(name),
    }
    installers.register(StructuredInstallerRegistration("pip", executor, **kwargs))
    installers.register(StructuredInstallerRegistration("python_package", executor, **kwargs))
    return installers


# ============================================================================
# 1. Installer identity resolution through the real materializer
# ============================================================================

SUPPORTED_FORMS = (
    ("pip", "pip"),
    ("python_package", "python_package"),
    (f"pip install {PACKAGE}", "pip"),
    (f"python -m pip install {PACKAGE}", "pip"),
    # PEP 503 name equivalence is part of the existing contract.
    ("pip install ESPHome", "pip"),
)

UNSUPPORTED_FORMS = (
    "pip install other-package",
    f"pip install {PACKAGE} --user",
    f"pip install {PACKAGE} other",
    f"pip install {PACKAGE}; rm -rf /",
    f"sudo pip install {PACKAGE}",
    f"pip3 install {PACKAGE}",
    f"python3 -m pip install {PACKAGE}",
    f"  pip install {PACKAGE}",
    "PIP",
    PACKAGE,
    "",
)


@pytest.mark.parametrize("install_method,expected_identity", SUPPORTED_FORMS)
def test_supported_forms_resolve_through_materializer_to_one_registered_installer(
    tmp_path, install_method, expected_identity,
):
    executor = PythonPackageExecutor(verifier=lambda step: True)
    installers = _canonical_installers(executor)
    plan = ToolchainMaterializer().materialize_decision(
        _decision(_package_item(install_method)), "proj",
        preflight=_preflight(True, PKG_REF), project_root=str(tmp_path),
    )

    (step,) = plan.steps
    assert step.action == "install"
    assert step.setup_effect == SetupEffect.PYTHON_PACKAGE_INSTALL
    assert step.install_method == install_method  # representation preserved
    assert step.package == PACKAGE                # package identity preserved
    identity = resolve_structured_installer_identity(step.setup_effect, step.install_method, step.package)
    assert identity == expected_identity
    registration = installers.resolve(step)
    assert registration is not None
    assert registration.executor is executor


@pytest.mark.parametrize("install_method", UNSUPPORTED_FORMS)
def test_unsupported_forms_never_become_install_steps_or_resolve(tmp_path, install_method):
    installers = _canonical_installers(PythonPackageExecutor(verifier=lambda step: True))
    plan = ToolchainMaterializer().materialize_decision(
        _decision(_package_item(install_method)), "proj",
        preflight=_preflight(True, PKG_REF), project_root=str(tmp_path),
    )
    assert all(step.action != "install" for step in plan.steps)

    forged = SetupStep(
        id="forged", requirement_id=PKG_REF, action="install", install_method=install_method,
        package=PACKAGE, setup_effect=SetupEffect.PYTHON_PACKAGE_INSTALL,
    )
    assert resolve_structured_installer_identity(forged.setup_effect, forged.install_method, forged.package) is None
    assert installers.resolve(forged) is None


def test_package_identity_is_never_used_as_installer_identity():
    """An installer registered under a package name is never selected for
    a controlled step installing that package."""
    installers = StructuredInstallerRegistry()
    installers.register(StructuredInstallerRegistration(PACKAGE, Mock()))
    step = SetupStep(
        id="s", requirement_id=PKG_REF, action="install", install_method=f"pip install {PACKAGE}",
        package=PACKAGE, setup_effect=SetupEffect.PYTHON_PACKAGE_INSTALL,
    )
    assert installers.resolve(step) is None


def test_uncontrolled_effect_resolves_to_no_installer():
    installers = _canonical_installers(Mock())
    step = SetupStep(
        id="s", requirement_id="r", action="install", install_method="pip",
        package="tool", setup_effect=SetupEffect.PROJECT_TOOL_INSTALL,
    )
    assert installers.resolve(step) is None


# ============================================================================
# 2. Explicit tool -> provisioning-requirement correlation
# ============================================================================

def test_executable_correlates_to_provider_through_declared_provided_by():
    decision = _decision(_package_item(), _cli_item())
    assert correlate_provisioning_requirement(decision.variant, EXECUTABLE) == PKG_REF


def test_package_identity_alone_never_correlates_to_an_executable():
    decision = _decision(_package_item())
    with pytest.raises(MissingToolchainSetupError):
        correlate_provisioning_requirement(decision.variant, EXECUTABLE)


@pytest.mark.parametrize("items", [
    (_package_item(), _cli_item(), _cli_item(requirement_ref="req-tool-cli-2")),
    (_package_item(), _cli_item(provided_by="req-unknown")),
    (_cli_item(provided_by=CLI_REF),),
])
def test_ambiguous_or_broken_correlation_fails_closed(items):
    with pytest.raises(MissingToolchainSetupError):
        correlate_provisioning_requirement(_decision(*items).variant, EXECUTABLE)


# ============================================================================
# 3. Materializability / fail-early characterization (existing authority)
# ============================================================================

def test_active_binding_missing_controllable_requirement_yields_install_step(tmp_path):
    plan = ToolchainMaterializer().materialize_decision(
        _decision(_package_item()), "proj",
        preflight=_preflight(True, PKG_REF), project_root=str(tmp_path),
    )
    assert [(s.requirement_id, s.action) for s in plan.steps] == [(PKG_REF, "install")]
    assert PKG_REF not in plan.deferred_requirement_ids


def test_active_binding_unresolvable_requirement_is_explicit_and_blocks_development(tmp_path):
    """ACTIVE + BINDING + missing + not controllably installable ->
    explicit manual_review step (never silently dropped), and development
    never starts (IF_REQ_014, IF_REQ_017)."""
    item = _package_item(install_method="curl -sSL https://example.invalid/install.sh | sh")
    plan = ToolchainMaterializer().materialize_decision(
        _decision(item), "proj", preflight=_preflight(True, PKG_REF), project_root=str(tmp_path),
    )
    assert [(s.requirement_id, s.action) for s in plan.steps] == [(PKG_REF, "manual_review")]

    stage = Mock()
    workflow = DevelopmentWorkflow(
        Mock(), Mock(), Mock(), executor=PythonPackageExecutor(verifier=lambda step: True),
        materializer=ToolchainMaterializer(), development_testing_stage=stage,
    )
    with pytest.raises(WorkflowExecutionError):
        workflow.execute_approved_and_run_development(
            SetupApproval.approve(plan), Mock(run_id="run", project_path=None),
        )
    stage.run.assert_not_called()


def test_inactive_requirement_remains_legitimately_deferred(tmp_path):
    """Control case: activation and installation state are distinct -- an
    inactive requirement with state=needs_install stays DEFERRED."""
    decision = _decision(_package_item(), _cli_item())
    assert all(item.state == "needs_install" for item in decision.variant.toolchain)
    plan = ToolchainMaterializer().materialize_decision(
        decision, "proj", preflight=_preflight(False, PKG_REF, CLI_REF), project_root=str(tmp_path),
    )
    assert plan.steps == ()
    assert set(plan.deferred_requirement_ids) == {PKG_REF, CLI_REF}


# ============================================================================
# 4. Productive S5 -> S3.5 path
# ============================================================================

class _FakeLLMExecutor:
    """Deterministic stand-in for the external LLM provider only."""

    def run(self, role, content, context, role_again):
        if role == "developer":
            return json.dumps({"changes": [{"file": "device.yaml", "action": "create",
                                            "content": "esphome:\n  name: specimen\n"}], "tests": []})
        if role == "tester":
            return json.dumps({"disposition": "no_changes_required", "changes": [], "tests": [],
                               "reason": "firmware verification covers the change"})
        raise AssertionError(f"unexpected LLM role after TOOL_UNAVAILABLE: {role}")


@pytest.fixture
def productive_chain(tmp_path, monkeypatch):
    record_path = tmp_path / "recorded-argv.txt"
    provider = inert_recording_provider(tmp_path, monkeypatch, record_path)
    monkeypatch.setattr(interactive_terminal_module, "DesktopTerminalProvider", lambda: provider)

    project = tmp_path / "project"
    project.mkdir()
    (project / "esphome.yaml").write_text("esphome:\n  name: specimen\n", encoding="utf-8")

    tool_state = {"installed": False}
    real_which = verification_module.shutil.which

    def host_path_lookup(name, *args, **kwargs):
        if name == EXECUTABLE:
            return str(tmp_path / "bin" / EXECUTABLE) if tool_state["installed"] else None
        return real_which(name, *args, **kwargs)

    monkeypatch.setattr(verification_module.shutil, "which", host_path_lookup)

    llm = _FakeLLMExecutor()
    development_testing = DevelopmentTestingStage(
        DevelopmentStage(DeveloperAgent(llm)), TestChangeGenerator(llm), DeveloperFileApplier,
        Mock(), TestingStage(DiagnosisReviewer(llm)),
        verification_registry=build_default_registry(), project_inspector=ProjectInspector(),
    )
    installer_calls = []

    class _RecordingExecutor(PythonPackageExecutor):
        def execute(self, step, project_root=None):
            installer_calls.append(step.id)
            result = super().execute(step, project_root)
            tool_state["installed"] = result.success
            return result

    package_executor = _RecordingExecutor(verifier=lambda step: True)
    workflow = DevelopmentWorkflow(
        Mock(), Mock(), Mock(), executor=package_executor,
        materializer=ToolchainMaterializer(), development_testing_stage=development_testing,
        execution_state_store=SetupExecutionStateStore(tmp_path / "setup-state"),
    )
    manager = WorkflowManager(str(tmp_path / "workflow_state.json"))
    service = ProjectSetupApplicationService(
        workflow, workflow_manager=manager,
        diagnostic_trace=DiagnosticTrace(DiagnosticTraceStore(str(tmp_path / "events.jsonl"))),
        structured_installers=_canonical_installers(
            package_executor,
            availability_checker=lambda name: str(tmp_path / "bin" / name) if tool_state["installed"] else None,
        ),
        verification_registry=build_default_registry(),
        approved_content_store=ApprovedPlanContentStore(tmp_path / "approved_plan_content.json"),
    )
    return service, workflow, project, record_path, installer_calls, tool_state


def _plan_with_human_selection(workflow, project, items):
    council_result = CouncilResult(
        id="council-1", project_id="proj",
        variants=(CouncilVariant(id="v1", name="specimen", environment="host", toolchain=items),),
        recommendation="v1", council_complete=True,
    )
    refs = tuple(item.requirement_ref for item in items)
    return workflow.resolve_engineering_selection(
        council_result, _preflight(False, *refs), None, "proj",
        human_selected_variant_id="v1", run_id="run-1", project_root=str(project),
    )


def _execute_until_tool_unavailable(service, workflow, project, items):
    planning = _plan_with_human_selection(workflow, project, items)
    assert planning.setup_plan.steps == ()  # inactive: legitimately DEFERRED
    assert planning.engineering_decision.selection_authority == "human"
    return planning, service.execute_approved_setup_and_development(
        SetupApproval.approve(planning.setup_plan), "proj", project, "add specimen config",
        "run-1", planning_result=planning,
    )


def _esphome_steps(verification_result):
    return [s for s in verification_result.steps if s.runner_type == "esphome_check"]


def test_productive_s5_tool_unavailable_routes_to_approval_bound_bounded_recovery(productive_chain):
    service, workflow, project, record_path, installer_calls, tool_state = productive_chain
    items = (_package_item(f"python -m pip install {PACKAGE}"), _cli_item())

    planning, result = _execute_until_tool_unavailable(service, workflow, project, items)

    # real S5 producer -> real TOOL_UNAVAILABLE artifact
    testing = result.development_testing_result
    assert testing.status == "tool_unavailable"
    unavailable = [s for s in _esphome_steps(testing.verification_result) if s.status == TOOL_UNAVAILABLE.value]
    assert unavailable and {s.unavailable_tool for s in unavailable} == {EXECUTABLE}

    # production-owned routing -> real recovery artifact, paused for approval
    recovery = result.missing_toolchain_recovery
    assert recovery.status == "pending_approval", recovery.blockers
    assert installer_calls == [] and not record_path.exists()
    record = service._workflow_manager.get_missing_toolchain_setup(recovery.plan_id)
    assert record["toolchain"] == EXECUTABLE
    assert record["provisioning_requirement_ref"] == PKG_REF
    assert record["chairman_approval_ref"] == planning.engineering_decision.variant.id
    assert record["verification_plan"]["run_id"] == testing.verification_plan.run_id
    assert [s["step_id"] for s in record["verification_plan"]["steps"]] == [
        s.step_id for s in testing.verification_plan.steps
    ]
    (step,) = record["setup_plan"]["steps"]
    assert (step["requirement_id"], step["package"], step["install_method"]) == (
        PKG_REF, PACKAGE, f"python -m pip install {PACKAGE}",
    )

    # no execution without the explicit human decision
    assert service.execute_missing_toolchain_setup(recovery.plan_id).status == "pending_approval"
    assert installer_calls == []

    # explicit human decision through the real application boundary
    assert service.decide_missing_toolchain_setup(recovery.plan_id, "approved", "human").status == "approved"

    executed = service.execute_missing_toolchain_setup(recovery.plan_id)
    assert executed.status == "completed", executed.blockers
    assert installer_calls == [f"step-{PKG_REF}"]
    assert read_recorded_argv(record_path)[1:] == ["-m", "pip", "install", PACKAGE]

    # bounded: a repeated execute never reinstalls
    assert service.execute_missing_toolchain_setup(recovery.plan_id).status == "completed"
    assert installer_calls == [f"step-{PKG_REF}"]

    # bounded continuation: the persisted S5 plan is re-executed exactly
    # once. The PATH-lookup double only claims the CLI exists -- nothing
    # real runs -- so the retry does not pass and recovery must fail
    # closed instead of reporting completion (the productive pass case is
    # tests/test_installer_recovery_productive_path.py).
    retried = service.retry_missing_toolchain_verification(recovery.plan_id)
    assert retried.status == "verification_failed"
    assert retried.verification_result.run_id == testing.verification_plan.run_id
    assert retried.verification_result.aggregate_status != PASS.value
    again_retried = service.retry_missing_toolchain_verification(recovery.plan_id)
    assert again_retried.status == "verification_failed"
    assert again_retried.verification_result is None

    # re-routing the same outcome never opens a second recovery
    again = service.route_tool_unavailable_to_recovery(planning, result, "proj", project)
    assert again.plan_id == recovery.plan_id
    assert installer_calls == [f"step-{PKG_REF}"]


def test_productive_recovery_without_explicit_identity_relation_fails_closed(productive_chain):
    """Valid trigger, but the selected variant declares no executable
    identity for the unavailable tool: no recovery artifact, no install."""
    service, workflow, project, record_path, installer_calls, _ = productive_chain

    _, result = _execute_until_tool_unavailable(service, workflow, project, (_package_item(),))

    assert result.development_testing_result.status == "tool_unavailable"
    recovery = result.missing_toolchain_recovery
    assert recovery.status == "rejected"
    assert recovery.plan_id == ""
    assert any("executable identity" in blocker for blocker in recovery.blockers)
    assert installer_calls == [] and not record_path.exists()


def test_productive_recovery_with_unresolvable_installer_fails_closed_without_install(productive_chain, monkeypatch):
    """Valid trigger and correlation, but no registered installer resolves
    the approved step: structured failure, the installer never runs."""
    service, workflow, project, record_path, installer_calls, _ = productive_chain
    service._structured_installers = StructuredInstallerRegistry()
    items = (_package_item(f"pip install {PACKAGE}"), _cli_item())

    _, result = _execute_until_tool_unavailable(service, workflow, project, items)
    recovery = result.missing_toolchain_recovery
    assert recovery.status == "pending_approval"
    service.decide_missing_toolchain_setup(recovery.plan_id, "approved", "human")

    executed = service.execute_missing_toolchain_setup(recovery.plan_id)
    assert executed.status == "failed"
    assert executed.blockers == ("No structured installer is registered",)
    assert installer_calls == [] and not record_path.exists()
    assert service.retry_missing_toolchain_verification(recovery.plan_id).status == "retry_blocked"


def test_without_planning_result_no_recovery_is_routed(productive_chain):
    """Existing callers that do not pass the planning result keep the
    exact prior behavior."""
    service, workflow, project, _, installer_calls, _ = productive_chain
    planning = _plan_with_human_selection(workflow, project, (_package_item(), _cli_item()))
    result = service.execute_approved_setup_and_development(
        SetupApproval.approve(planning.setup_plan), "proj", project, "add specimen config", "run-1",
    )
    assert result.development_testing_result.status == "tool_unavailable"
    assert result.missing_toolchain_recovery is None
    assert installer_calls == []


# ============================================================================
# 5. Distinct identities (Gate-1 primitive; the productive roundtrip is
#    tests/test_installer_recovery_productive_path.py)
# ============================================================================

DISTINCT_DIST_REF = "req-cli-distribution"
DISTINCT_CLI_REF = "req-firmware-cli"
DISTINCT_DISTRIBUTION = "specimen-firmware-cli"
DISTINCT_EXECUTABLE = "specimen-validate"
DISTINCT_REPRESENTATION = f"python -m pip install {DISTINCT_DISTRIBUTION}"


def test_distinct_identities_correlate_only_through_explicit_relations(tmp_path):
    """Requirement ids, distribution, executable, installation
    representation, installer identity and recovery capability are all
    different values; they are joined only by the declared relations."""
    from app.execution import capability_for_setup_effect

    decision = _decision(
        _package_item(DISTINCT_REPRESENTATION, requirement_ref=DISTINCT_DIST_REF,
                      technical_identity=DISTINCT_DISTRIBUTION),
        _cli_item(provided_by=DISTINCT_DIST_REF, technical_identity=DISTINCT_EXECUTABLE,
                  requirement_ref=DISTINCT_CLI_REF),
    )
    ref = correlate_provisioning_requirement(decision.variant, DISTINCT_EXECUTABLE)
    assert ref == DISTINCT_DIST_REF
    for not_an_executable in (DISTINCT_DISTRIBUTION, DISTINCT_DIST_REF, DISTINCT_CLI_REF, "pip"):
        with pytest.raises(MissingToolchainSetupError):
            correlate_provisioning_requirement(decision.variant, not_an_executable)

    plan = ToolchainMaterializer().materialize_decision(
        decision, "proj", preflight=_preflight(True, DISTINCT_DIST_REF), project_root=str(tmp_path),
    )
    (step,) = [s for s in plan.steps if s.requirement_id == ref and s.action == "install"]
    assert step.package == DISTINCT_DISTRIBUTION
    assert step.install_method == DISTINCT_REPRESENTATION
    installer_identity = resolve_structured_installer_identity(
        step.setup_effect, step.install_method, step.package,
    )
    capability = capability_for_setup_effect(step.setup_effect)
    identities = (DISTINCT_DIST_REF, DISTINCT_CLI_REF, DISTINCT_DISTRIBUTION,
                  DISTINCT_EXECUTABLE, DISTINCT_REPRESENTATION, installer_identity, capability)
    assert installer_identity == "pip" and capability == "python"
    assert len(set(identities)) == len(identities)

    executor = PythonPackageExecutor(verifier=lambda step: True)
    installers = _canonical_installers(executor)
    assert installers.resolve(step).executor is executor
    for not_an_installer in (DISTINCT_DISTRIBUTION, DISTINCT_EXECUTABLE, DISTINCT_REPRESENTATION):
        assert installers.get(not_an_installer) is None
