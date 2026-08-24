"""Tests for the deterministic development workflow."""

import pytest
from unittest.mock import MagicMock

from app.ai_requirement_discovery import AIRequirementDiscovery
from app.dev_workflow import DevelopmentWorkflow, WorkflowResult
from app.requirement_model import (
    DiscoveryResult,
    PreflightResult,
    Requirement,
    RequirementEvidence,
    RequirementType,
    SetupPlan,
    Status,
    ValidationResult,
)
from app.requirement_preflight import RequirementPreflight
from app.requirement_validator import RequirementValidator
from app.setup_planner import SetupPlanner


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


def _make_setup_plan(project_id: str = "proj-1") -> SetupPlan:
    return SetupPlan(
        id="plan-1",
        project_id=project_id,
        steps=(),
        requires_user_approval=True,
        rollback_steps=(),
        warnings=(),
        status="pending_approval",
    )


class TestDevelopmentWorkflow:
    def test_full_workflow_returns_all_stages(self):
        discovery = MagicMock(spec=AIRequirementDiscovery)
        validator = MagicMock(spec=RequirementValidator)
        preflight = MagicMock(spec=RequirementPreflight)
        planner = MagicMock(spec=SetupPlanner)

        project_info = {"name": "test-project"}
        project_id = "proj-1"

        disc_result = _make_discovery_result(project_id)
        val_result = _make_validation_result(disc_result.requirements)
        pre_result = _make_preflight_result(project_id)
        plan_result = _make_setup_plan(project_id)

        discovery.discover.return_value = disc_result
        validator.validate.return_value = val_result
        preflight.check.return_value = pre_result
        planner.plan.return_value = plan_result

        workflow = DevelopmentWorkflow(discovery, validator, preflight, planner)
        result = workflow.run(project_info, project_id)

        assert isinstance(result, WorkflowResult)
        assert result.discovery_result is disc_result
        assert result.validation_result is val_result
        assert result.preflight_result is pre_result
        assert result.setup_plan is plan_result

    def test_discovery_called_with_correct_args(self):
        discovery = MagicMock(spec=AIRequirementDiscovery)
        validator = MagicMock(spec=RequirementValidator)
        preflight = MagicMock(spec=RequirementPreflight)
        planner = MagicMock(spec=SetupPlanner)

        project_info = {"name": "test"}
        project_id = "proj-1"

        disc_result = _make_discovery_result(project_id)
        val_result = _make_validation_result(disc_result.requirements)
        pre_result = _make_preflight_result(project_id)
        plan_result = _make_setup_plan(project_id)

        discovery.discover.return_value = disc_result
        validator.validate.return_value = val_result
        preflight.check.return_value = pre_result
        planner.plan.return_value = plan_result

        workflow = DevelopmentWorkflow(discovery, validator, preflight, planner)
        workflow.run(project_info, project_id)

        discovery.discover.assert_called_once_with(project_info, project_id)

    def test_validator_receives_discovery_requirements(self):
        discovery = MagicMock(spec=AIRequirementDiscovery)
        validator = MagicMock(spec=RequirementValidator)
        preflight = MagicMock(spec=RequirementPreflight)
        planner = MagicMock(spec=SetupPlanner)

        project_info = {"name": "test"}
        project_id = "proj-1"

        disc_result = _make_discovery_result(project_id)
        val_result = _make_validation_result(disc_result.requirements)
        pre_result = _make_preflight_result(project_id)
        plan_result = _make_setup_plan(project_id)

        discovery.discover.return_value = disc_result
        validator.validate.return_value = val_result
        preflight.check.return_value = pre_result
        planner.plan.return_value = plan_result

        workflow = DevelopmentWorkflow(discovery, validator, preflight, planner)
        workflow.run(project_info, project_id)

        validator.validate.assert_called_once_with(disc_result.requirements)

    def test_preflight_receives_normalized_requirements(self):
        discovery = MagicMock(spec=AIRequirementDiscovery)
        validator = MagicMock(spec=RequirementValidator)
        preflight = MagicMock(spec=RequirementPreflight)
        planner = MagicMock(spec=SetupPlanner)

        project_info = {"name": "test"}
        project_id = "proj-1"

        disc_result = _make_discovery_result(project_id)
        val_result = _make_validation_result(disc_result.requirements)
        pre_result = _make_preflight_result(project_id)
        plan_result = _make_setup_plan(project_id)

        discovery.discover.return_value = disc_result
        validator.validate.return_value = val_result
        preflight.check.return_value = pre_result
        planner.plan.return_value = plan_result

        workflow = DevelopmentWorkflow(discovery, validator, preflight, planner)
        workflow.run(project_info, project_id)

        preflight.check.assert_called_once_with(
            val_result.normalized_requirements, project_id
        )

    def test_planner_receives_required_requirements_and_preflight(self):
        discovery = MagicMock(spec=AIRequirementDiscovery)
        validator = MagicMock(spec=RequirementValidator)
        preflight = MagicMock(spec=RequirementPreflight)
        planner = MagicMock(spec=SetupPlanner)

        project_info = {"name": "test"}
        project_id = "proj-1"

        disc_result = _make_discovery_result(project_id)
        val_result = _make_validation_result(disc_result.requirements)
        pre_result = _make_preflight_result(project_id)
        plan_result = _make_setup_plan(project_id)

        discovery.discover.return_value = disc_result
        validator.validate.return_value = val_result
        preflight.check.return_value = pre_result
        planner.plan.return_value = plan_result

        workflow = DevelopmentWorkflow(discovery, validator, preflight, planner)
        workflow.run(project_info, project_id)

        planner.plan.assert_called_once_with(
            val_result.required_requirements, pre_result, project_id
        )

    def test_setup_plan_remains_pending_approval(self):
        discovery = MagicMock(spec=AIRequirementDiscovery)
        validator = MagicMock(spec=RequirementValidator)
        preflight = MagicMock(spec=RequirementPreflight)
        planner = MagicMock(spec=SetupPlanner)

        project_info = {"name": "test"}
        project_id = "proj-1"

        disc_result = _make_discovery_result(project_id)
        val_result = _make_validation_result(disc_result.requirements)
        pre_result = _make_preflight_result(project_id)
        plan_result = _make_setup_plan(project_id)

        discovery.discover.return_value = disc_result
        validator.validate.return_value = val_result
        preflight.check.return_value = pre_result
        planner.plan.return_value = plan_result

        workflow = DevelopmentWorkflow(discovery, validator, preflight, planner)
        result = workflow.run(project_info, project_id)

        assert result.setup_plan.status == "pending_approval"

    def test_no_approval_or_execution_calls(self):
        discovery = MagicMock(spec=AIRequirementDiscovery)
        validator = MagicMock(spec=RequirementValidator)
        preflight = MagicMock(spec=RequirementPreflight)
        planner = MagicMock(spec=SetupPlanner)

        project_info = {"name": "test"}
        project_id = "proj-1"

        disc_result = _make_discovery_result(project_id)
        val_result = _make_validation_result(disc_result.requirements)
        pre_result = _make_preflight_result(project_id)
        plan_result = _make_setup_plan(project_id)

        discovery.discover.return_value = disc_result
        validator.validate.return_value = val_result
        preflight.check.return_value = pre_result
        planner.plan.return_value = plan_result

        workflow = DevelopmentWorkflow(discovery, validator, preflight, planner)
        workflow.run(project_info, project_id)

        # Ensure no approve/reject/execute methods were called on any component
        for mock_obj in (discovery, validator, preflight, planner):
            for forbidden in ("approve", "reject", "execute"):
                assert not hasattr(mock_obj, forbidden) or not getattr(
                    mock_obj, forbidden
                ).called, f"{mock_obj}.{forbidden} was called"

    def test_discovery_error_propagates(self):
        discovery = MagicMock(spec=AIRequirementDiscovery)
        validator = MagicMock(spec=RequirementValidator)
        preflight = MagicMock(spec=RequirementPreflight)
        planner = MagicMock(spec=SetupPlanner)

        discovery.discover.side_effect = RuntimeError("discovery failed")

        workflow = DevelopmentWorkflow(discovery, validator, preflight, planner)

        with pytest.raises(RuntimeError, match="discovery failed"):
            workflow.run({"name": "test"}, "proj-1")

    def test_intermediate_objects_are_not_mutated(self):
        discovery = MagicMock(spec=AIRequirementDiscovery)
        validator = MagicMock(spec=RequirementValidator)
        preflight = MagicMock(spec=RequirementPreflight)
        planner = MagicMock(spec=SetupPlanner)

        project_info = {"name": "test"}
        project_id = "proj-1"

        disc_result = _make_discovery_result(project_id)
        val_result = _make_validation_result(disc_result.requirements)
        pre_result = _make_preflight_result(project_id)
        plan_result = _make_setup_plan(project_id)

        discovery.discover.return_value = disc_result
        validator.validate.return_value = val_result
        preflight.check.return_value = pre_result
        planner.plan.return_value = plan_result

        workflow = DevelopmentWorkflow(discovery, validator, preflight, planner)
        result = workflow.run(project_info, project_id)

        # All objects are frozen dataclasses, but we can still verify identity
        assert result.discovery_result is disc_result
        assert result.validation_result is val_result
        assert result.preflight_result is pre_result
        assert result.setup_plan is plan_result
