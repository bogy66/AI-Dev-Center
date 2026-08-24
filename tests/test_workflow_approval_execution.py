from unittest.mock import MagicMock

from app.ai_requirement_discovery import AIRequirementDiscovery
from app.dev_workflow import DevelopmentWorkflow
from app.python_package_executor import PythonPackageExecutor
from app.requirement_model import (
    DiscoveryResult,
    PreflightResult,
    Requirement,
    RequirementEvidence,
    RequirementType,
    SetupPlan,
    SetupStep,
    Status,
    ValidationResult,
)
from app.requirement_preflight import RequirementPreflight
from app.requirement_validator import RequirementValidator
from app.setup_approval import SetupApproval
from app.setup_executor import ExecutionResult
from app.setup_planner import SetupPlanner


def _make_requirement():
    return Requirement(
        id="req-1",
        name="example-package",
        type=RequirementType.PYTHON_PACKAGE,
        purpose="integration test",
        required=True,
        confidence=0.9,
        evidence=(
            RequirementEvidence(
                id="ev-1",
                source_type="manual",
                description="integration test requirement",
            ),
        ),
        status=Status.DISCOVERED,
    )


def _make_workflow(executor):
    discovery = MagicMock(spec=AIRequirementDiscovery)
    validator = MagicMock(spec=RequirementValidator)
    preflight = MagicMock(spec=RequirementPreflight)
    planner = MagicMock(spec=SetupPlanner)

    requirement = _make_requirement()

    discovery_result = DiscoveryResult(
        id="disc-1",
        source="test",
        project_id="workflow-integration",
        requirements=(requirement,),
        warnings=(),
    )

    validation_result = ValidationResult(
        id="val-1",
        valid=True,
        requirements=(requirement,),
        errors=(),
        warnings=(),
        normalized_requirements=(requirement,),
        required_requirements=(requirement,),
        optional_requirements=(),
        rejected_requirements=(),
    )

    preflight_result = PreflightResult(
        id="pre-1",
        project_id="workflow-integration",
        overall_ready=False,
        results=(),
        missing_requirements=(requirement,),
        already_installed=(),
        warnings=(),
    )

    step = SetupStep(
        id="step-1",
        requirement_id="req-1",
        action="install",
        install_method="python_package",
        package="example-package",
        version=None,
        command=None,
        verification_after="import example_package",
        is_approved=False,
    )

    setup_plan = SetupPlan(
        id="plan-1",
        project_id="workflow-integration",
        steps=(step,),
        requires_user_approval=True,
        rollback_steps=(),
        warnings=(),
        status="pending_approval",
    )

    discovery.discover.return_value = discovery_result
    validator.validate.return_value = validation_result
    preflight.check.return_value = preflight_result
    planner.plan.return_value = setup_plan

    workflow = DevelopmentWorkflow(
        discovery=discovery,
        validator=validator,
        preflight=preflight,
        planner=planner,
        executor=executor,
    )

    return workflow, setup_plan


def test_run_to_approval_to_execution():
    executor = MagicMock(spec=PythonPackageExecutor)

    execution_result = ExecutionResult(
        step_id="step-1",
        success=True,
        message="executed",
        verification_passed=True,
    )
    executor.execute.return_value = execution_result

    workflow, original_plan = _make_workflow(executor)

    workflow_result = workflow.run(
        {"name": "workflow-integration"},
        "workflow-integration",
    )

    assert workflow_result.setup_plan is original_plan
    assert original_plan.status == "pending_approval"
    assert original_plan.steps[0].is_approved is False
    executor.execute.assert_not_called()

    approved_plan = SetupApproval.approve(original_plan)

    assert approved_plan is not original_plan
    assert original_plan.status == "pending_approval"
    assert approved_plan.status == "approved"
    assert approved_plan.steps[0].is_approved is True

    results = workflow.execute_approved(approved_plan)

    assert results == (execution_result,)
    executor.execute.assert_called_once_with(
        approved_plan.steps[0]
    )


def test_rejected_plan_never_executes():
    executor = MagicMock(spec=PythonPackageExecutor)

    workflow, original_plan = _make_workflow(executor)

    workflow.run(
        {"name": "workflow-integration"},
        "workflow-integration",
    )

    rejected_plan = SetupApproval.reject(original_plan)

    try:
        workflow.execute_approved(rejected_plan)
    except Exception:
        pass
    else:
        raise AssertionError("Rejected plan must not execute")

    executor.execute.assert_not_called()


def test_approval_creates_approved_copy():
    executor = MagicMock(spec=PythonPackageExecutor)

    workflow, original_plan = _make_workflow(executor)

    workflow.run(
        {"name": "workflow-integration"},
        "workflow-integration",
    )

    approved_plan = SetupApproval.approve(original_plan)

    assert approved_plan is not original_plan
    assert original_plan.status == "pending_approval"
    assert original_plan.steps[0].is_approved is False
    assert approved_plan.status == "approved"
    assert approved_plan.steps[0].is_approved is True
