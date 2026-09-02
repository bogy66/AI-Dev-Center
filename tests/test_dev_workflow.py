"""Tests for the deterministic development workflow."""

from unittest.mock import MagicMock

import pytest

from app.ai_requirement_discovery import AIRequirementDiscovery
from app.council_models import CouncilInput, CouncilResult
from app.dev_workflow import (
    DevelopmentWorkflow,
    WorkflowBlockedError,
    WorkflowExecutionError,
    WorkflowResult,
)
from app.engineering_council import EngineeringCouncil
from app.diagnostic_trace import DiagnosticTrace, DiagnosticTraceStore
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
from app.setup_executor import ExecutionResult
from app.setup_planner import SetupPlanner
from app.toolchain_materializer import ToolchainMaterializer


def _make_requirement(req_id: str = "req-1") -> Requirement:
    return Requirement(
        id=req_id,
        name="example-package",
        type=RequirementType.PYTHON_PACKAGE,
        purpose="testing",
        required=True,
        confidence=0.9,
        evidence=(
            RequirementEvidence(
                id="ev-1",
                source_type="manual",
                description="needed for tests",
            ),
        ),
        status=Status.DISCOVERED,
    )


def _make_discovery_result(project_id: str = "proj-1") -> DiscoveryResult:
    req = _make_requirement()
    return DiscoveryResult(
        id="disc-1",
        source="test",
        project_id=project_id,
        requirements=(req,),
        warnings=(),
    )


def _make_validation_result(requirements) -> ValidationResult:
    return ValidationResult(
        id="val-1",
        valid=True,
        requirements=requirements,
        errors=(),
        warnings=(),
        normalized_requirements=requirements,
        required_requirements=requirements,
        optional_requirements=(),
        rejected_requirements=(),
    )


def _make_preflight_result(project_id: str = "proj-1") -> PreflightResult:
    return PreflightResult(
        id="pre-1",
        project_id=project_id,
        overall_ready=True,
        results=(),
        missing_requirements=(),
        already_installed=(),
        warnings=(),
    )


def _make_setup_step(
    step_id: str = "step-1",
    approved: bool = False,
    *,
    action: str = "install",
    package: str | None = "example-package",
    install_method: str | None = "python_package",
) -> SetupStep:
    return SetupStep(
        id=step_id,
        requirement_id="req-1",
        action=action,
        install_method=install_method,
        package=package,
        version=None,
        command=None,
        verification_after="import example_package",
        is_approved=approved,
    )


def _make_setup_plan(
    project_id: str = "proj-1",
    *,
    status: str = "pending_approval",
    steps=(),
) -> SetupPlan:
    return SetupPlan(
        id="plan-1",
        project_id=project_id,
        steps=tuple(steps),
        requires_user_approval=True,
        rollback_steps=(),
        warnings=(),
        status=status,
    )


def _make_components(project_id: str = "proj-1"):
    discovery = MagicMock(spec=AIRequirementDiscovery)
    validator = MagicMock(spec=RequirementValidator)
    preflight = MagicMock(spec=RequirementPreflight)
    planner = MagicMock(spec=SetupPlanner)
    council = MagicMock(spec=EngineeringCouncil)
    materializer = MagicMock(spec=ToolchainMaterializer)

    discovery_result = _make_discovery_result(project_id)
    validation_result = _make_validation_result(
        discovery_result.requirements,
    )
    preflight_result = _make_preflight_result(project_id)
    council_result = CouncilResult(
        id="council-1",
        project_id=project_id,
    )
    plan_result = _make_setup_plan(project_id)

    discovery.discover.return_value = discovery_result
    validator.validate.return_value = validation_result
    preflight.check.return_value = preflight_result
    planner.plan.return_value = plan_result
    council.evaluate.return_value = council_result
    materializer.materialize.return_value = plan_result

    return (
        discovery,
        validator,
        preflight,
        planner,
        council,
        materializer,
        discovery_result,
        validation_result,
        preflight_result,
        council_result,
        plan_result,
    )


class TestDevelopmentWorkflow:
    def test_full_workflow_returns_all_stages(self):
        (
            discovery,
            validator,
            preflight,
            planner,
            council,
            materializer,
            discovery_result,
            validation_result,
            preflight_result,
            council_result,
            plan_result,
        ) = _make_components()

        workflow = DevelopmentWorkflow(
            discovery,
            validator,
            preflight,
            planner,
            council=council,
            materializer=materializer,
        )

        result = workflow.run({"name": "test-project"}, "proj-1")

        assert isinstance(result, WorkflowResult)
        assert result.discovery_result is discovery_result
        assert result.validation_result is validation_result
        assert result.preflight_result is preflight_result
        assert result.council_result is council_result
        assert result.setup_plan is plan_result

    def test_discovery_called_with_correct_args(self):
        discovery, validator, preflight, planner, council, materializer, *_ = _make_components()

        workflow = DevelopmentWorkflow(
            discovery,
            validator,
            preflight,
            planner,
            council=council,
            materializer=materializer,
        )

        project_info = {"name": "test"}
        project_id = "proj-1"

        workflow.run(project_info, project_id)

        discovery.discover.assert_called_once_with(
            project_info,
            project_id,
        )

    def test_validator_receives_discovery_requirements(self):
        (
            discovery,
            validator,
            preflight,
            planner,
            council,
            materializer,
            discovery_result,
            *_,
        ) = _make_components()

        workflow = DevelopmentWorkflow(
            discovery,
            validator,
            preflight,
            planner,
            council=council,
            materializer=materializer,
        )

        workflow.run({"name": "test"}, "proj-1")

        validator.validate.assert_called_once_with(
            discovery_result.requirements,
        )

    def test_preflight_receives_normalized_requirements(self):
        (
            discovery,
            validator,
            preflight,
            planner,
            council,
            materializer,
            _,
            validation_result,
            *_,
        ) = _make_components()

        workflow = DevelopmentWorkflow(
            discovery,
            validator,
            preflight,
            planner,
            council=council,
            materializer=materializer,
        )

        workflow.run({"name": "test"}, "proj-1")

        preflight.check.assert_called_once_with(
            validation_result.normalized_requirements,
            "proj-1",
        )

    def test_council_receives_canonical_input(self):
        (
            discovery,
            validator,
            preflight,
            planner,
            council,
            materializer,
            _,
            validation_result,
            preflight_result,
            _,
            _,
        ) = _make_components()

        workflow = DevelopmentWorkflow(
            discovery,
            validator,
            preflight,
            planner,
            council=council,
            materializer=materializer,
        )

        workflow.run(
            {
                "files": [
                    {"path": "pyproject.toml", "content": ""},
                    {"path": "app/main.py", "content": ""},
                ],
            },
            "proj-1",
        )

        council.evaluate.assert_called_once()
        council_input = council.evaluate.call_args.args[0]
        assert isinstance(council_input, CouncilInput)
        assert council_input.requirements == validation_result.normalized_requirements
        assert council_input.preflight is preflight_result
        assert council_input.project_id == "proj-1"
        assert council_input.project_files == ("pyproject.toml", "app/main.py")
        assert council_input.validation_warnings == validation_result.warnings

    def test_invalid_project_file_information_is_ignored(self):
        discovery, validator, preflight, planner, council, materializer, *_ = _make_components()

        workflow = DevelopmentWorkflow(
            discovery,
            validator,
            preflight,
            planner,
            council=council,
            materializer=materializer,
        )

        workflow.run({"files": "not-a-file-list"}, "proj-1")

        assert council.evaluate.call_args.args[0].project_files == ()

    def test_materializer_receives_exact_council_result_and_project_id(self):
        (
            discovery,
            validator,
            preflight,
            planner,
            council,
            materializer,
            _,
            _,
            _,
            council_result,
            plan_result,
        ) = _make_components()

        workflow = DevelopmentWorkflow(
            discovery,
            validator,
            preflight,
            planner,
            council=council,
            materializer=materializer,
        )

        result = workflow.run({"name": "test"}, "proj-1")

        materializer.materialize.assert_called_once_with(council_result, "proj-1")
        assert result.council_result is council_result
        assert result.setup_plan is plan_result

    def test_planner_is_never_called(self):
        discovery, validator, preflight, planner, council, materializer, *_ = _make_components()

        workflow = DevelopmentWorkflow(
            discovery,
            validator,
            preflight,
            planner,
            council=council,
            materializer=materializer,
        )

        workflow.run({"name": "test"}, "proj-1")

        planner.plan.assert_not_called()

    def test_discovery_error_propagates(self):
        discovery = MagicMock(spec=AIRequirementDiscovery)
        validator = MagicMock(spec=RequirementValidator)
        preflight = MagicMock(spec=RequirementPreflight)
        planner = MagicMock(spec=SetupPlanner)

        discovery.discover.side_effect = RuntimeError(
            "discovery failed",
        )

        workflow = DevelopmentWorkflow(
            discovery,
            validator,
            preflight,
            planner,
        )

        with pytest.raises(RuntimeError, match="discovery failed"):
            workflow.run({"name": "test"}, "proj-1")

    def test_discovery_fallback_blocks_planning(self):
        (
            discovery,
            validator,
            preflight,
            planner,
            council,
            materializer,
            discovery_result,
            *_,
        ) = _make_components()

        fallback_result = DiscoveryResult(
            id=discovery_result.id,
            source=discovery_result.source,
            project_id=discovery_result.project_id,
            requirements=(),
            conversation_trace_id=None,
            ai_model="test-model",
            fallback_used=True,
            warnings=("LLM provider failed",),
        )

        discovery.discover.return_value = fallback_result

        workflow = DevelopmentWorkflow(
            discovery,
            validator,
            preflight,
            planner,
        )

        with pytest.raises(
            WorkflowBlockedError,
            match="planning was blocked",
        ):
            workflow.run(
                {"name": "test"},
                "proj-1",
            )

        validator.validate.assert_not_called()
        preflight.check.assert_not_called()
        planner.plan.assert_not_called()
        council.evaluate.assert_not_called()
        materializer.materialize.assert_not_called()

    def test_missing_council_blocks_planning(self):
        discovery, validator, preflight, planner, _, materializer, *_ = _make_components()

        workflow = DevelopmentWorkflow(
            discovery,
            validator,
            preflight,
            planner,
            materializer=materializer,
        )

        with pytest.raises(WorkflowExecutionError, match="Engineering Council"):
            workflow.run({"name": "test"}, "proj-1")

        materializer.materialize.assert_not_called()

    def test_missing_materializer_blocks_planning(self):
        discovery, validator, preflight, planner, council, _, *_ = _make_components()

        workflow = DevelopmentWorkflow(
            discovery,
            validator,
            preflight,
            planner,
            council=council,
        )

        with pytest.raises(WorkflowExecutionError, match="ToolchainMaterializer"):
            workflow.run({"name": "test"}, "proj-1")

        council.evaluate.assert_not_called()

    def test_incomplete_council_result_blocks_before_materialization(self, tmp_path):
        discovery, validator, preflight, planner, council, materializer, *_ = _make_components()
        council.evaluate.return_value = CouncilResult(
            id="council-incomplete", project_id="proj-1",
            council_complete=False, agent_errors=("A2 unavailable",),
        )
        trace = DiagnosticTrace(DiagnosticTraceStore(tmp_path / "trace.jsonl"))
        workflow = DevelopmentWorkflow(
            discovery, validator, preflight, planner,
            council=council, materializer=materializer,
            diagnostic_trace=trace,
        )

        with pytest.raises(WorkflowBlockedError, match="planning was blocked"):
            workflow.run({"name": "test"}, "proj-1")

        materializer.materialize.assert_not_called()
        events = trace.get_trace("proj-1")
        assert any(
            event.phase == "engineering_council" and event.status == "incomplete"
            for event in events
        )
        assert any(
            event.phase == "workflow_end" and event.status == "blocked"
            for event in events
        )
        assert not any(event.phase == "toolchain_materialization" for event in events)


    def test_intermediate_objects_are_not_mutated(self):
        (
            discovery,
            validator,
            preflight,
            planner,
            council,
            materializer,
            discovery_result,
            validation_result,
            preflight_result,
            council_result,
            plan_result,
        ) = _make_components()

        workflow = DevelopmentWorkflow(
            discovery,
            validator,
            preflight,
            planner,
            council=council,
            materializer=materializer,
        )

        result = workflow.run({"name": "test"}, "proj-1")

        assert result.discovery_result is discovery_result
        assert result.validation_result is validation_result
        assert result.preflight_result is preflight_result
        assert result.council_result is council_result
        assert result.setup_plan is plan_result


class TestApprovedExecution:
    def _make_workflow(self, executor):
        discovery = MagicMock(spec=AIRequirementDiscovery)
        validator = MagicMock(spec=RequirementValidator)
        preflight = MagicMock(spec=RequirementPreflight)
        planner = MagicMock(spec=SetupPlanner)

        return DevelopmentWorkflow(
            discovery=discovery,
            validator=validator,
            preflight=preflight,
            planner=planner,
            executor=executor,
        )

    def test_approved_plan_executes_all_approved_install_steps(self):
        executor = MagicMock(spec=PythonPackageExecutor)

        step1 = _make_setup_step("step-1", approved=True)
        step2 = _make_setup_step("step-2", approved=True)

        result1 = ExecutionResult(
            step_id="step-1",
            success=True,
            message="ok",
            verification_passed=True,
        )
        result2 = ExecutionResult(
            step_id="step-2",
            success=True,
            message="ok",
            verification_passed=True,
        )

        executor.execute.side_effect = [result1, result2]

        workflow = self._make_workflow(executor)

        plan = _make_setup_plan(
            status="approved",
            steps=(step1, step2),
        )

        results = workflow.execute_approved(plan)

        assert results == (result1, result2)
        executor.execute.assert_any_call(step1)
        executor.execute.assert_any_call(step2)

    def test_pending_plan_is_rejected(self):
        executor = MagicMock(spec=PythonPackageExecutor)
        workflow = self._make_workflow(executor)

        plan = _make_setup_plan(
            status="pending_approval",
            steps=(_make_setup_step(approved=False),),
        )

        with pytest.raises(WorkflowExecutionError):
            workflow.execute_approved(plan)

        executor.execute.assert_not_called()

    def test_rejected_plan_is_rejected(self):
        executor = MagicMock(spec=PythonPackageExecutor)
        workflow = self._make_workflow(executor)

        plan = _make_setup_plan(
            status="rejected",
            steps=(),
        )

        with pytest.raises(WorkflowExecutionError):
            workflow.execute_approved(plan)

        executor.execute.assert_not_called()

    def test_plan_with_unapproved_step_is_rejected(self):
        executor = MagicMock(spec=PythonPackageExecutor)
        workflow = self._make_workflow(executor)

        plan = _make_setup_plan(
            status="approved",
            steps=(_make_setup_step(approved=False),),
        )

        with pytest.raises(WorkflowExecutionError):
            workflow.execute_approved(plan)

        executor.execute.assert_not_called()

    def test_manual_review_action_is_rejected(self):
        executor = MagicMock(spec=PythonPackageExecutor)
        workflow = self._make_workflow(executor)

        step = _make_setup_step(
            approved=True,
            action="manual_review",
        )
        plan = _make_setup_plan(
            status="approved",
            steps=(step,),
        )

        with pytest.raises(
            WorkflowExecutionError,
            match="requires manual review",
        ):
            workflow.execute_approved(plan)

        executor.execute.assert_not_called()

    def test_missing_package_is_rejected(self):
        executor = MagicMock(spec=PythonPackageExecutor)
        workflow = self._make_workflow(executor)

        step = _make_setup_step(
            approved=True,
            package=None,
        )
        plan = _make_setup_plan(
            status="approved",
            steps=(step,),
        )

        with pytest.raises(
            WorkflowExecutionError,
            match="no package is specified",
        ):
            workflow.execute_approved(plan)

        executor.execute.assert_not_called()

    def test_missing_install_method_is_rejected(self):
        executor = MagicMock(spec=PythonPackageExecutor)
        workflow = self._make_workflow(executor)

        step = _make_setup_step(
            approved=True,
            install_method=None,
        )
        plan = _make_setup_plan(
            status="approved",
            steps=(step,),
        )

        with pytest.raises(
            WorkflowExecutionError,
            match="no install method is specified",
        ):
            workflow.execute_approved(plan)

        executor.execute.assert_not_called()

    def test_execution_results_are_returned_as_tuple(self):
        executor = MagicMock(spec=PythonPackageExecutor)

        execution_result = ExecutionResult(
            step_id="step-1",
            success=True,
            message="ok",
            verification_passed=True,
        )
        executor.execute.return_value = execution_result

        workflow = self._make_workflow(executor)

        step = _make_setup_step(
            "step-1",
            approved=True,
        )
        plan = _make_setup_plan(
            status="approved",
            steps=(step,),
        )

        results = workflow.execute_approved(plan)

        assert isinstance(results, tuple)
        assert results == (execution_result,)

    def test_no_executor_configured_is_rejected(self):
        workflow = self._make_workflow(None)

        step = _make_setup_step(
            "step-1",
            approved=True,
        )
        plan = _make_setup_plan(
            status="approved",
            steps=(step,),
        )

        with pytest.raises(
            WorkflowExecutionError,
            match="No setup executor has been configured",
        ):
            workflow.execute_approved(plan)

    def test_execute_approved_does_not_mutate_plan(self):
        executor = MagicMock(spec=PythonPackageExecutor)
        executor.execute.return_value = ExecutionResult(
            step_id="step-1",
            success=True,
            message="ok",
            verification_passed=True,
        )

        workflow = self._make_workflow(executor)

        step = _make_setup_step(
            "step-1",
            approved=True,
        )
        plan = _make_setup_plan(
            status="approved",
            steps=(step,),
        )

        results = workflow.execute_approved(plan)

        assert plan.status == "approved"
        assert plan.steps == (step,)
        assert results[0].step_id == "step-1"

    def test_run_never_executes_even_with_executor_configured(self):
        executor = MagicMock(spec=PythonPackageExecutor)
        (
            discovery,
            validator,
            preflight,
            planner,
            council,
            materializer,
            _,
            _,
            _,
            _,
            plan_result,
        ) = _make_components()

        workflow = DevelopmentWorkflow(
            discovery,
            validator,
            preflight,
            planner,
            executor=executor,
            council=council,
            materializer=materializer,
        )

        result = workflow.run({"name": "test"}, "proj-1")

        assert result.setup_plan is plan_result
        executor.execute.assert_not_called()
