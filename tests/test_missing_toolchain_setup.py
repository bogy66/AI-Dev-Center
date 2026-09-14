from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.execution import CapabilityRegistry
from app.missing_toolchain_setup import (
    MissingToolchainSetupRequest,
    StructuredInstallerRegistration,
    StructuredInstallerRegistry,
)
from app.project_setup_application import ProjectSetupApplicationService
from app.requirement_model import SetupPlan, SetupStep
from app.setup_executor import ExecutionResult
from app.verification import (
    TOOL_UNAVAILABLE, VerificationPlan, VerificationResult,
    VerificationStep, VerificationStepResult,
)
from app.workflow_manager import WorkflowManager


def _request(project):
    step = VerificationStep("verify", ".", ".", "build", "future", "future", "controlled_execution")
    plan = VerificationPlan("run", str(project), "existing", 1, (step,))
    result = VerificationResult("run", (
        VerificationStepResult("verify", ".", TOOL_UNAVAILABLE.value, "build", "future", False),
    ), "fail")
    return MissingToolchainSetupRequest(
        "project", str(project), "futurecc", "build", Mock(id="council"), plan, result,
    )


def _service(tmp_path, *, available=False, install_success=True):
    manager = WorkflowManager(tmp_path / "state.json")
    materializer = Mock()
    materializer.materialize.return_value = SetupPlan(
        "plan-project", "project", steps=(SetupStep(
            "install-future", "req", "install", install_method="future-structured",
            package="futurecc",
        ),),
    )
    state = {"available": available}
    executor = Mock()
    def execute(step, project_root=None):
        if install_success:
            state["available"] = True
        return ExecutionResult(step.id, install_success, "structured", install_success)
    executor.execute.side_effect = execute
    installers = StructuredInstallerRegistry()
    installers.register(StructuredInstallerRegistration(
        "future-structured", executor,
        availability_checker=lambda name: name if state["available"] else None,
    ))
    verification = Mock()
    verification.execute_plan.return_value = VerificationResult("run", (), "pass")
    capabilities = CapabilityRegistry()
    workflow = Mock()
    workflow.materialize_setup_plan.return_value = materializer.materialize.return_value
    service = ProjectSetupApplicationService(
        workflow, workflow_manager=manager, diagnostic_trace=Mock(),
        capability_registry=capabilities,
        structured_installers=installers, verification_registry=verification,
    )
    return service, manager, executor, verification, capabilities


def _prepare_and_decide(service, project, decision="approved"):
    pending = service.prepare_missing_toolchain_setup(_request(project))
    service.decide_missing_toolchain_setup(pending.plan_id, decision, "Human")
    return pending.plan_id


def test_tool_unavailable_does_not_install_automatically(tmp_path):
    service, _, executor, _, _ = _service(tmp_path)
    service.prepare_missing_toolchain_setup(_request(tmp_path))
    executor.execute.assert_not_called()


def test_setup_plan_is_obtained_from_workflow_boundary(tmp_path):
    service, _, _, _, _ = _service(tmp_path)
    request = _request(tmp_path)
    service.prepare_missing_toolchain_setup(request)
    # CLAUDE-ADC-S23-STRICT-IDENTITY-ENVIRONMENT-BINDING-FIX-004 (#5):
    # the already-validated project_root must be forwarded so a "venv"
    # candidate's own environment can actually bind to a real target
    # instead of silently inheriting Preflight's generic, pre-candidate
    # target.
    service._development_workflow.materialize_setup_plan.assert_called_once_with(
        request.council_result, request.project_id, platform=request.platform,
        project_root=str(tmp_path.resolve()),
    )


def test_materialize_setup_plan_threads_platform_into_real_constraint_enforcement():
    """CLAUDE-PRE-E2E-009C, Part 10: the narrower Missing-Toolchain retry
    boundary (DevelopmentWorkflow.materialize_setup_plan(), used by
    prepare_missing_toolchain_setup() above) previously had no platform
    parameter at all, so a variant's environment_constraint could never
    be enforced on this path even though it already was on the
    productive dev_workflow.py::run() call site. This is the smallest
    additive plumbing fix (an optional, default-None platform parameter
    threaded straight through to the same real ToolchainMaterializer
    every other path already uses) -- proven here with the REAL
    materializer, not a mock, so it is genuine end-to-end Constraint
    enforcement, not merely an argument being forwarded."""
    from app.council_models import CouncilResult, CouncilVariant, ToolchainItem
    from app.dev_workflow import DevelopmentWorkflow
    from app.engineering_decision import NoEligibleEngineeringCandidateError
    from app.requirement_model import RequirementType
    from app.toolchain_materializer import ToolchainMaterializer

    windows_only = CouncilVariant(
        id="v1", name="v1",
        toolchain=(ToolchainItem(
            requirement_ref="req-1", name="future-tool",
            type=RequirementType.PYTHON_PACKAGE, technical_identity="future-tool",
            install_method="pip", environment_constraint="windows",
        ),),
    )
    council_result = CouncilResult(
        id="council-1", project_id="proj", variants=(windows_only,),
        recommendation="v1", council_complete=True,
    )
    workflow = DevelopmentWorkflow(
        discovery=None, validator=None, preflight=None,
        materializer=ToolchainMaterializer(),
    )

    # Without a platform (the historical default), the constraint is not
    # enforced -- unchanged prior behaviour, still a valid manual_review
    # candidate since nothing contradicts it.
    unconstrained_plan = workflow.materialize_setup_plan(council_result, "proj")
    assert unconstrained_plan.steps

    # With platform now threaded through, the same variant becomes
    # inadmissible on this retry path too, exactly as it already was on
    # the productive dev_workflow.py::run() call site.
    with pytest.raises(NoEligibleEngineeringCandidateError):
        workflow.materialize_setup_plan(council_result, "proj", platform="linux")


def test_setup_cannot_execute_before_approval(tmp_path):
    service, _, executor, _, _ = _service(tmp_path)
    plan_id = service.prepare_missing_toolchain_setup(_request(tmp_path)).plan_id
    assert service.execute_missing_toolchain_setup(plan_id).blockers
    executor.execute.assert_not_called()


def test_rejected_setup_does_not_execute(tmp_path):
    service, _, executor, _, _ = _service(tmp_path)
    plan_id = _prepare_and_decide(service, tmp_path, "rejected")
    service.execute_missing_toolchain_setup(plan_id)
    executor.execute.assert_not_called()


def test_approved_structured_setup_executes_once(tmp_path):
    service, _, executor, _, _ = _service(tmp_path)
    plan_id = _prepare_and_decide(service, tmp_path)
    assert service.execute_missing_toolchain_setup(plan_id).status == "completed"
    service.execute_missing_toolchain_setup(plan_id)
    executor.execute.assert_called_once()


def test_already_available_toolchain_is_not_reinstalled(tmp_path):
    service, _, executor, _, _ = _service(tmp_path, available=True)
    plan_id = _prepare_and_decide(service, tmp_path)
    result = service.execute_missing_toolchain_setup(plan_id)
    assert result.status == "already_available"
    assert isinstance(result.setup_result, ExecutionResult)
    assert result.setup_result.success is True
    executor.execute.assert_not_called()


def test_arbitrary_installer_method_is_rejected(tmp_path):
    service, manager, executor, _, _ = _service(tmp_path)
    plan_id = _prepare_and_decide(service, tmp_path)
    record = manager.get_missing_toolchain_setup(plan_id)
    record["setup_plan"]["steps"][0]["install_method"] = "sh -c"
    manager.update_missing_toolchain_setup(plan_id, setup_plan=record["setup_plan"])
    assert service.execute_missing_toolchain_setup(plan_id).status == "failed"
    executor.execute.assert_not_called()


def test_installation_does_not_register_capability(tmp_path):
    service, _, _, _, capabilities = _service(tmp_path)
    plan_id = _prepare_and_decide(service, tmp_path)
    service.execute_missing_toolchain_setup(plan_id)
    assert capabilities.get("futurecc", tmp_path) is None


def test_retry_uses_persisted_existing_verification_plan(tmp_path):
    service, _, _, verification, _ = _service(tmp_path)
    plan_id = _prepare_and_decide(service, tmp_path)
    service.execute_missing_toolchain_setup(plan_id)
    service.retry_missing_toolchain_verification(plan_id)
    verification.execute_plan.assert_called_once()
    assert isinstance(verification.execute_plan.call_args.args[0], VerificationPlan)


def test_restart_does_not_repeat_completed_installation(tmp_path):
    service, manager, executor, verification, capabilities = _service(tmp_path)
    plan_id = _prepare_and_decide(service, tmp_path)
    service.execute_missing_toolchain_setup(plan_id)
    restarted = ProjectSetupApplicationService(
        Mock(), workflow_manager=manager, diagnostic_trace=Mock(),
        capability_registry=capabilities, structured_installers=service._structured_installers,
        verification_registry=verification,
    )
    restarted.execute_missing_toolchain_setup(plan_id)
    executor.execute.assert_called_once()


def test_failed_installation_does_not_retry_verification(tmp_path):
    service, _, _, verification, _ = _service(tmp_path, install_success=False)
    plan_id = _prepare_and_decide(service, tmp_path)
    assert service.execute_missing_toolchain_setup(plan_id).status == "failed"
    assert service.retry_missing_toolchain_verification(plan_id).status == "retry_blocked"
    verification.execute_plan.assert_not_called()
