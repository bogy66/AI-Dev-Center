"""Tests for the deterministic development workflow."""

from dataclasses import replace
import shutil
import sys
from unittest.mock import MagicMock

import pytest

from app.ai_requirement_discovery import AIRequirementDiscovery
from app.council_models import CouncilInput, CouncilResult, CouncilVariant, ToolchainItem
from app.dev_workflow import (
    DevelopmentWorkflow,
    WorkflowBlockedError,
    WorkflowExecutionError,
    WorkflowResult,
)
from app.engineering_council import EngineeringCouncil
from app.engineering_decision import select_engineering_variant
from app.diagnostic_trace import DiagnosticTrace, DiagnosticTraceStore
from app.python_package_executor import CommandResult, PythonPackageExecutor
from app.requirement_model import (
    DiscoveryResult,
    PreflightResult,
    PreflightRequirementResult,
    Requirement,
    RequirementActivation,
    RequirementEvidence,
    RequirementType,
    SetupEffect,
    SetupPlan,
    SetupStep,
    Status,
    ValidationResult,
    normalize_requirement_activations,
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
        activations=(RequirementActivation(req.id, True, True, "current request"),),
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
        activations=tuple(
            RequirementActivation(req.id, True, True, "current request")
            for req in requirements
        ),
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
    setup_effect: str | None = SetupEffect.PYTHON_PACKAGE_INSTALL,
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
        setup_effect=setup_effect,
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
    # CLAUDE-ARCH-S2-012A: dev_workflow.py's real production path now
    # calls select_engineering_variant() (S2) directly rather than only
    # through the (here fully mocked) materializer, so this fixture's
    # council_result must be a genuinely admissible CouncilResult -- a
    # real variant with a recommendation pointing to it -- for that real,
    # unmocked S2 call to succeed. preflight_result above has no missing
    # requirements, so there is no binding Requirement/Constraint for
    # this single, empty-toolchain variant to violate.
    council_result = CouncilResult(
        id="council-1",
        project_id=project_id,
        variants=(CouncilVariant(id="v1", name="v1"),),
        recommendation="v1",
        council_complete=True,
    )
    plan_result = _make_setup_plan(project_id)

    discovery.discover.return_value = discovery_result
    validator.validate.return_value = validation_result
    preflight.check.return_value = preflight_result
    planner.plan.return_value = plan_result
    council.evaluate.return_value = council_result
    materializer.materialize.return_value = plan_result
    materializer.materialize_decision.return_value = plan_result

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
        # CLAUDE-ARCH-S2-013C: run() now stops at the productive S2.4
        # Human Engineering Authority boundary -- no SetupPlan exists yet.
        assert result.setup_plan is None
        assert result.engineering_selection is not None
        resumed = workflow.resolve_engineering_selection(
            result.council_result, result.preflight_result, "linux", "proj-1",
            human_selected_variant_id=result.engineering_selection.chairman_recommendation,
        )
        assert resumed.setup_plan is plan_result

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

    def test_discovery_receives_real_user_request_without_merging_project_facts(self):
        discovery, validator, preflight, planner, council, materializer, *_ = _make_components()
        workflow = DevelopmentWorkflow(
            discovery, validator, preflight, planner,
            council=council, materializer=materializer,
        )
        project_info = {"project_kind": "existing", "languages": ["Python"]}

        workflow.run(
            project_info, "proj-1", user_request="Add a status endpoint",
            source_interface="web",
        )

        discovery.discover.assert_called_once_with(
            project_info, "proj-1", user_request="Add a status endpoint",
        )
        assert "user_request" not in project_info

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
            discovery_result.activations,
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
            validation_result.activations,
            project_root=None,
        )

    def test_preflight_receives_project_root_from_project_context(self):
        """CLAUDE-E2E-003B Gap B: the productive project_root (carried by
        ProjectContext, already built by ProjectSetupApplicationService's
        plan_project_setup before DevelopmentWorkflow.run() is called) is
        threaded into RequirementPreflight.check() so PYTHON_PACKAGE
        checks can route through the central controlled execution
        boundary instead of falling back to an unconfined subprocess."""
        (
            discovery, validator, preflight, planner, council, materializer,
            *_,
        ) = _make_components()

        workflow = DevelopmentWorkflow(
            discovery, validator, preflight, planner,
            council=council, materializer=materializer,
        )
        fake_project_context = MagicMock(project_root="/tmp/adc-project-root")

        workflow.run({"name": "test"}, "proj-1", project_context=fake_project_context)

        _, kwargs = preflight.check.call_args
        assert kwargs["project_root"] == "/tmp/adc-project-root"

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
        assert council_input.requirement_activations == validation_result.activations

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

    def test_materializer_receives_exact_engineering_decision_and_project_id(self):
        """CLAUDE-ARCH-S2-012A: the real production path now resolves the
        S2 EngineeringDecision (select_engineering_variant()) BEFORE
        calling the S3-facing materializer, and calls
        materialize_decision() -- not materialize() -- with exactly that
        decision. This is the TC-B-S2.5-S3 proof that S3 receives the
        already-published S2.5 artifact rather than a raw CouncilResult
        it would have to resolve itself."""
        (
            discovery,
            validator,
            preflight,
            planner,
            council,
            materializer,
            _,
            _,
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
        resumed = workflow.resolve_engineering_selection(
            result.council_result, preflight_result, "linux", "proj-1",
            human_selected_variant_id=council_result.recommendation,
        )

        expected_decision = select_engineering_variant(
            council_result, preflight_result, "linux",
            chairman_recommendation=council_result.recommendation,
            human_selected_variant_id=council_result.recommendation,
        )
        materializer.materialize.assert_not_called()
        materializer.materialize_decision.assert_called_once_with(
            expected_decision, "proj-1", preflight=preflight_result, project_root=None,
        )
        assert result.council_result is council_result
        assert resumed.setup_plan is plan_result

    def test_zero_admissible_candidates_failure_exposes_per_candidate_evidence_in_trace(self, tmp_path):
        """CLAUDE-E2E-NIO-010A, Part 7: Real-System-E2E #5 exposed that a
        NoEligibleEngineeringCandidateError reached the diagnostic trace
        only as a generic "Toolchain materialization failed:
        NoEligibleEngineeringCandidateError" summary -- no way to
        mechanically see WHY. The trace must now carry the same rich,
        safe, per-candidate evidence the exception itself exposes.

        CLAUDE-ARCH-S2-012A: the real production path now resolves
        select_engineering_variant() (S2) for real before ever reaching
        the (mocked) materializer, so this exercises the genuine S2.3
        rejection rather than injecting the exception via a mock."""
        from app.council_models import CouncilVariant, ToolchainItem
        from app.engineering_decision import NoEligibleEngineeringCandidateError
        from app.requirement_model import (
            PreflightRequirementResult, PreflightResult, Requirement, RequirementActivation,
        )

        (
            discovery, validator, preflight, planner, council, materializer,
            _, _, _, _, _,
        ) = _make_components()
        req_platformio = Requirement(
            id="req-platformio", name="platformio", type="executable",
            purpose="build backend", required=True, confidence=0.9,
        )
        preflight_result = PreflightResult(
            id="pre-1", project_id="proj-1", overall_ready=False,
            results=(PreflightRequirementResult(
                requirement_id="req-platformio", present=False, satisfied=False,
            ),),
            missing_requirements=(req_platformio,),
            activations=(RequirementActivation("req-platformio", True, True),),
        )
        rejected_variant = CouncilVariant(id="merged-venv", name="ESPHome mit Python Virtual Environment")
        council_result = CouncilResult(
            id="council-1", project_id="proj-1",
            variants=(rejected_variant,), recommendation="merged-venv",
            council_complete=True,
        )
        preflight.check.return_value = preflight_result
        council.evaluate.return_value = council_result
        trace = DiagnosticTrace(DiagnosticTraceStore(tmp_path / "trace.jsonl"))
        workflow = DevelopmentWorkflow(
            discovery, validator, preflight, planner,
            council=council, materializer=materializer,
            diagnostic_trace=trace,
        )

        with pytest.raises(NoEligibleEngineeringCandidateError):
            workflow.run({"name": "test"}, "proj-1")

        events = trace.get_trace("proj-1")
        failure_events = [
            event for event in events
            if event.phase == "toolchain_materialization" and event.status == "failed"
            and "failure_summary" in event.details
        ]
        assert len(failure_events) == 1
        failure_summary = failure_events[0].details.get("failure_summary", "")
        assert "merged-venv" in failure_summary
        assert "req-platformio" in failure_summary
        assert "inadmissible" in failure_summary

    def test_materializer_binding_diagnostic_reaches_the_trace_for_a_rejected_candidate(self, tmp_path):
        """CLAUDE-ADC-S23-MATERIALIZER-DIAGNOSTICS-001: run()'s real
        validate_candidates() call for a python_package binding item whose
        display name is not a valid distribution identifier and whose
        technical_identity is missing (the exact CLAUDE-ARCH-S2-012D /
        Real-System-E2E #8 shape) must reach the central diagnostic trace
        with the new, structured per-item materializer diagnostic --
        distinguishing identity_missing_or_invalid mechanically, without
        needing to inspect any raw effective_prompt text."""
        from app.engineering_decision import NoEligibleEngineeringCandidateError

        (
            discovery, validator, preflight, planner, council, materializer,
            _, _, _, _, _,
        ) = _make_components()
        req_esphome = Requirement(
            id="req-esphome", name="esphome", type=RequirementType.PYTHON_PACKAGE,
            purpose="firmware build", required=True, confidence=0.9,
        )
        preflight_result = PreflightResult(
            id="pre-1", project_id="proj-1", overall_ready=False,
            results=(PreflightRequirementResult(
                requirement_id="req-esphome", present=False, satisfied=False,
            ),),
            missing_requirements=(req_esphome,),
            activations=(RequirementActivation("req-esphome", True, True),),
        )
        rejected_variant = CouncilVariant(
            id="merged-host-venv", name="ESPHome CLI mit Python Virtual Environment",
            toolchain=(ToolchainItem(
                requirement_ref="req-esphome", name="ESPHome CLI",
                type=RequirementType.PYTHON_PACKAGE, technical_identity=None,
                install_method="pip install esphome",
            ),),
        )
        council_result = CouncilResult(
            id="council-1", project_id="proj-1",
            variants=(rejected_variant,), recommendation="merged-host-venv",
            council_complete=True,
        )
        preflight.check.return_value = preflight_result
        council.evaluate.return_value = council_result
        trace = DiagnosticTrace(DiagnosticTraceStore(tmp_path / "trace.jsonl"))
        workflow = DevelopmentWorkflow(
            discovery, validator, preflight, planner,
            council=council, materializer=materializer,
            diagnostic_trace=trace,
        )

        with pytest.raises(NoEligibleEngineeringCandidateError):
            workflow.run({"name": "test"}, "proj-1")

        events = trace.get_trace("proj-1")
        diagnostic_events = [
            event for event in events
            if event.phase == "toolchain_materialization"
            and event.details.get("interface_data", {}).get("info", {}).get("y", {}).get("data", {})
            .get("materializer_rejection_category") == "identity_missing_or_invalid"
        ]
        assert len(diagnostic_events) == 1
        payload = diagnostic_events[0].details["interface_data"]["verbose"]
        assert payload["x"]["data"]["variant_id"] == "merged-host-venv"
        assert payload["x"]["data"]["requirement_ref"] == "req-esphome"
        assert payload["x"]["data"]["technical_identity_present"] is False
        assert payload["y"]["data"]["safe_identifier"] is None
        assert payload["y"]["data"]["materializer_action"] == "manual_review"
        assert payload["y"]["data"]["materializer_rejection_category"] == "identity_missing_or_invalid"
        # This diagnostic is additive and observational only: the existing
        # per-candidate failure evidence event from the prior test still
        # reaches the trace unchanged, and run() still raises exactly the
        # same exception it always did.
        assert any(
            event.phase == "toolchain_materialization" and event.status == "failed"
            and "failure_summary" in event.details
            for event in events
        )

    def test_bytes_install_method_diagnostic_never_replaces_the_real_failure_evidence(self, tmp_path):
        """CLAUDE-ADC-S23-MATERIALIZER-DIAGNOSTICS-FIX-001 (CDX-ADC-S23-
        MATERIALIZER-DIAGNOSTICS-REVIEW-001): before this fix, a binding
        item with missing identity AND install_method=b"pip" made the new
        diagnostic instrumentation itself raise TypeError from run()'s
        try/except around validate_candidates()/resolve_human_engineering_
        selection() -- replacing the real NoEligibleEngineeringCandidateError
        and losing its failure_summary evidence entirely (the `except
        Exception` handler's `getattr(error, "validations", None) or
        getattr(error, "rejected", None)` finds nothing on a bare TypeError,
        so `details` becomes {} instead of carrying failure_summary). This
        proves the fix: the ORIGINAL exception type and its failure_summary
        evidence still reach the trace exactly as in the string-install-
        method test above, and the new diagnostic event itself is present
        and did not crash, now correctly labeling install_method's shape as
        "non_string_type"."""
        from app.engineering_decision import NoEligibleEngineeringCandidateError

        (
            discovery, validator, preflight, planner, council, materializer,
            _, _, _, _, _,
        ) = _make_components()
        req_esphome = Requirement(
            id="req-esphome", name="esphome", type=RequirementType.PYTHON_PACKAGE,
            purpose="firmware build", required=True, confidence=0.9,
        )
        preflight_result = PreflightResult(
            id="pre-1", project_id="proj-1", overall_ready=False,
            results=(PreflightRequirementResult(
                requirement_id="req-esphome", present=False, satisfied=False,
            ),),
            missing_requirements=(req_esphome,),
            activations=(RequirementActivation("req-esphome", True, True),),
        )
        rejected_variant = CouncilVariant(
            id="merged-host-venv", name="ESPHome CLI mit Python Virtual Environment",
            toolchain=(ToolchainItem(
                requirement_ref="req-esphome", name="ESPHome CLI",
                type=RequirementType.PYTHON_PACKAGE, technical_identity=None,
                install_method=b"pip",
            ),),
        )
        council_result = CouncilResult(
            id="council-1", project_id="proj-1",
            variants=(rejected_variant,), recommendation="merged-host-venv",
            council_complete=True,
        )
        preflight.check.return_value = preflight_result
        council.evaluate.return_value = council_result
        trace = DiagnosticTrace(DiagnosticTraceStore(tmp_path / "trace.jsonl"))
        workflow = DevelopmentWorkflow(
            discovery, validator, preflight, planner,
            council=council, materializer=materializer,
            diagnostic_trace=trace,
        )

        # The ORIGINAL exception type, never a TypeError from the
        # diagnostic instrumentation.
        with pytest.raises(NoEligibleEngineeringCandidateError):
            workflow.run({"name": "test"}, "proj-1")

        events = trace.get_trace("proj-1")
        failure_events = [
            event for event in events
            if event.phase == "toolchain_materialization" and event.status == "failed"
            and "failure_summary" in event.details
        ]
        assert len(failure_events) == 1
        failure_summary = failure_events[0].details.get("failure_summary", "")
        assert "merged-host-venv" in failure_summary
        assert "req-esphome" in failure_summary
        assert "inadmissible" in failure_summary

        diagnostic_events = [
            event for event in events
            if event.phase == "toolchain_materialization"
            and event.details.get("interface_data", {}).get("info", {}).get("y", {}).get("data", {})
            .get("materializer_rejection_category") == "identity_missing_or_invalid"
        ]
        assert len(diagnostic_events) == 1
        payload = diagnostic_events[0].details["interface_data"]["verbose"]
        assert payload["x"]["data"]["install_method_python_type"] == "bytes"
        assert payload["y"]["data"]["install_method_classification"] == "non_string_type"
        assert payload["y"]["data"]["materializer_action"] == "manual_review"
        assert payload["y"]["data"]["materializer_rejection_category"] == "identity_missing_or_invalid"

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

    def test_complete_degraded_council_continues_to_materialization(self, tmp_path):
        (
            discovery, validator, preflight, planner, council, materializer,
            _, _, preflight_result, _, plan_result,
        ) = _make_components()
        degraded_result = CouncilResult(
            id="council-degraded",
            project_id="proj-1",
            variants=(CouncilVariant(id="v1", name="v1"),),
            recommendation="v1",
            council_complete=True,
            council_degraded=True,
            agent_errors=("A1 unavailable",),
        )
        council.evaluate.return_value = degraded_result
        trace = DiagnosticTrace(DiagnosticTraceStore(tmp_path / "trace.jsonl"))
        workflow = DevelopmentWorkflow(
            discovery, validator, preflight, planner,
            council=council, materializer=materializer,
            diagnostic_trace=trace,
        )

        result = workflow.run({"name": "test"}, "proj-1")
        resumed = workflow.resolve_engineering_selection(
            result.council_result, preflight_result, "linux", "proj-1",
            human_selected_variant_id="v1",
        )

        expected_decision = select_engineering_variant(
            degraded_result, preflight_result, "linux", chairman_recommendation="v1",
            human_selected_variant_id="v1",
        )
        materializer.materialize_decision.assert_called_once_with(
            expected_decision, "proj-1", preflight=preflight_result, project_root=None,
        )
        assert result.council_result is degraded_result
        assert resumed.setup_plan is plan_result
        council_events = [
            event for event in trace.get_trace("proj-1")
            if event.phase == "engineering_council"
        ]
        assert any(event.status == "completed" for event in council_events)
        assert not any(event.status == "degraded" for event in council_events)
        assert any(
            event.details.get("council_degraded") is True
            for event in council_events
        )
        assert any(
            event.details.get("interface_data", {})
            .get("info", {})
            .get("y", {})
            .get("data", {})
            .get("council_degraded") is True
            for event in council_events
        )

    def test_preflight_trace_exposes_safe_activation_state(self, tmp_path):
        (
            discovery, validator, preflight, planner, council, materializer,
            discovery_result, validation_result, _, _, _,
        ) = _make_components()
        activation = RequirementActivation(
            discovery_result.requirements[0].id, False, False,
        )
        discovery.discover.return_value = DiscoveryResult(
            id=discovery_result.id, source=discovery_result.source,
            project_id=discovery_result.project_id,
            requirements=discovery_result.requirements,
            activations=(activation,),
        )
        validator.validate.return_value = ValidationResult(
            id=validation_result.id, valid=True,
            requirements=validation_result.requirements,
            normalized_requirements=validation_result.normalized_requirements,
            required_requirements=validation_result.required_requirements,
            activations=(activation,),
        )
        preflight.check.return_value = PreflightResult(
            id="pre-activation", project_id="proj-1", overall_ready=True,
            results=(PreflightRequirementResult(
                requirement_id=activation.requirement_id,
                present=False, satisfied=False, active=False,
                blocks_current_operation=False,
            ),),
            activations=(activation,),
            inactive_requirements=discovery_result.requirements,
        )
        trace = DiagnosticTrace(DiagnosticTraceStore(tmp_path / "trace.jsonl"))
        workflow = DevelopmentWorkflow(
            discovery, validator, preflight, planner,
            council=council, materializer=materializer,
            diagnostic_trace=trace,
        )

        workflow.run({"name": "test"}, "proj-1")

        states = [
            row.get("state")
            for event in trace.get_trace("proj-1")
            for row in (
                event.details.get("interface_data", {})
                .get("verbose", {}).get("y", {}).get("data", {})
                .get("preflight_results", [])
            )
        ]
        assert "inactive" in states


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
        resumed = workflow.resolve_engineering_selection(
            result.council_result, result.preflight_result, "linux", "proj-1",
            human_selected_variant_id=council_result.recommendation,
        )
        assert resumed.setup_plan is plan_result


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

    def test_approved_plan_with_deferred_requirement_does_not_block_execution(self):
        executor = MagicMock(spec=PythonPackageExecutor)
        workflow = self._make_workflow(executor)
        activation = RequirementActivation(
            "future-physical-capability", False, False,
        )
        plan = SetupPlan(
            id="plan-deferred", project_id="proj-1", steps=(),
            status="approved", requirement_activations=(activation,),
            deferred_requirement_ids=(activation.requirement_id,),
        )

        results = workflow.execute_approved(plan)

        assert results == ()
        executor.execute.assert_not_called()

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
            setup_effect=None,
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
        resumed = workflow.resolve_engineering_selection(
            result.council_result, result.preflight_result, "linux", "proj-1",
            human_selected_variant_id=result.engineering_selection.chairman_recommendation,
        )

        assert resumed.setup_plan is plan_result
        executor.execute.assert_not_called()


class TestDiscoveryFallbackTraceSemantics:
    """Tests verifying that trace events correctly represent discovery state."""

    def test_successful_discovery_emits_completed_trace_status(self, tmp_path):
        (
            discovery, validator, preflight, planner, council, materializer,
            discovery_result, *_,
        ) = _make_components()
        trace = DiagnosticTrace(DiagnosticTraceStore(tmp_path / "trace.jsonl"))
        workflow = DevelopmentWorkflow(
            discovery, validator, preflight, planner,
            council=council, materializer=materializer,
            diagnostic_trace=trace,
        )

        workflow.run({"name": "test"}, "proj-1")

        events = trace.get_trace("proj-1")
        discovery_completed = [
            e for e in events
            if e.phase == "requirement_discovery" and e.event_type == "completed"
        ]
        assert len(discovery_completed) >= 1
        assert all(
            e.status == "completed" for e in discovery_completed
        )

    def test_fallback_discovery_emits_blocked_not_completed_trace_status(
        self, tmp_path,
    ):
        (
            discovery, validator, preflight, planner, council, materializer,
            discovery_result, *_,
        ) = _make_components()
        fallback_result = DiscoveryResult(
            id=discovery_result.id,
            source=discovery_result.source,
            project_id=discovery_result.project_id,
            requirements=(),
            conversation_trace_id=None,
            ai_model="test-model",
            fallback_used=True,
            warnings=("Failed to parse LLM response: invalid structure",),
        )
        discovery.discover.return_value = fallback_result

        trace = DiagnosticTrace(DiagnosticTraceStore(tmp_path / "trace.jsonl"))
        workflow = DevelopmentWorkflow(
            discovery, validator, preflight, planner,
            diagnostic_trace=trace,
        )

        with pytest.raises(WorkflowBlockedError, match="planning was blocked"):
            workflow.run({"name": "test"}, "proj-1")

        events = trace.get_trace("proj-1")
        discovery_completed_events = [
            e for e in events
            if e.phase == "requirement_discovery" and e.status == "completed"
        ]
        assert discovery_completed_events == []

        discovery_blocked_events = [
            e for e in events
            if e.phase == "requirement_discovery" and e.status == "blocked"
        ]
        assert len(discovery_blocked_events) >= 1

    def test_successful_discovery_interface_status_is_completed(
        self, tmp_path,
    ):
        (
            discovery, validator, preflight, planner, council, materializer,
            *_,
        ) = _make_components()
        trace = DiagnosticTrace(DiagnosticTraceStore(tmp_path / "trace.jsonl"))
        workflow = DevelopmentWorkflow(
            discovery, validator, preflight, planner,
            council=council, materializer=materializer,
            diagnostic_trace=trace,
        )

        workflow.run({"name": "test"}, "proj-1")

        events = trace.get_trace("proj-1")
        interface_events = [
            e for e in events
            if e.phase == "requirement_discovery"
            and e.details.get("interface_stage") == "requirement_discovery"
        ]
        assert interface_events
        for e in interface_events:
            y_data = (
                e.details.get("interface_data", {})
                .get("info", {}).get("y", {}).get("data", {})
            )
            assert y_data.get("warning_count", -1) == 0

    def test_fallback_discovery_interface_status_is_failed(self, tmp_path):
        (
            discovery, validator, preflight, planner, council, materializer,
            discovery_result, *_,
        ) = _make_components()
        fallback_result = DiscoveryResult(
            id=discovery_result.id,
            source=discovery_result.source,
            project_id=discovery_result.project_id,
            requirements=(),
            conversation_trace_id=None,
            ai_model="test-model",
            fallback_used=True,
            warnings=("Failed to parse LLM response: invalid structure",),
        )
        discovery.discover.return_value = fallback_result
        trace = DiagnosticTrace(DiagnosticTraceStore(tmp_path / "trace.jsonl"))
        workflow = DevelopmentWorkflow(
            discovery, validator, preflight, planner,
            diagnostic_trace=trace,
        )

        with pytest.raises(WorkflowBlockedError, match="planning was blocked"):
            workflow.run({"name": "test"}, "proj-1")

        events = trace.get_trace("proj-1")
        interface_events = [
            e for e in events
            if e.phase == "requirement_discovery"
            and e.details.get("interface_stage") == "requirement_discovery"
        ]
        assert interface_events
        for e in interface_events:
            assert e.status == "failed"

    def test_discovery_effective_prompt_appears_in_interface_very_verbose(
        self, tmp_path,
    ):
        (
            discovery, validator, preflight, planner, council, materializer,
            *_,
        ) = _make_components()
        discovery.effective_prompt = (
            "You are the Requirement Discovery Analyst of AI-Dev-Center."
        )
        discovery.effective_repair_prompt = None
        trace = DiagnosticTrace(DiagnosticTraceStore(tmp_path / "trace.jsonl"))
        workflow = DevelopmentWorkflow(
            discovery, validator, preflight, planner,
            council=council, materializer=materializer,
            diagnostic_trace=trace,
        )

        workflow.run({"name": "test"}, "proj-1")

        events = trace.get_trace("proj-1")
        interface_events = [
            e for e in events
            if e.phase == "requirement_discovery"
            and e.details.get("interface_stage") == "requirement_discovery"
        ]
        assert interface_events
        interface_data = interface_events[0].details.get("interface_data", {})
        very_verbose = interface_data.get("very_verbose", {})
        x_data = very_verbose.get("x", {}).get("data", {})
        assert "effective_prompt" in x_data
        assert "Requirement Discovery Analyst of AI-Dev-Center" in x_data["effective_prompt"]


class TestSetupExecutionActivation:
    """Tests for activation-aware setup step execution."""

    def test_nonblocking_manual_step_is_skipped_not_rejected(self):
        executor = MagicMock(spec=PythonPackageExecutor)
        result = ExecutionResult(step_id="step-req-1", success=True,
                                 message="ok", verification_passed=True)
        executor.execute.return_value = result

        discovery = MagicMock(spec=AIRequirementDiscovery)
        workflow = DevelopmentWorkflow(
            discovery=discovery, validator=MagicMock(),
            preflight=MagicMock(), planner=MagicMock(), executor=executor,
        )
        activation = RequirementActivation("req-future", False, False,
                                           "forward-looking")
        plan = SetupPlan(
            id="plan-future", project_id="proj-1",
            steps=(
                SetupStep(id="step-req-future", requirement_id="req-future",
                          action="manual_review", package=None,
                          install_method=None),
                SetupStep(id="step-req-1", requirement_id="req-1",
                          action="install", install_method="pip",
                          package="example-package", is_approved=True),
            ),
            status="approved",
            requirement_activations=(activation,),
        )

        results = workflow.execute_approved(plan)
        assert len(results) == 1
        assert results[0].step_id == "step-req-1"

    def test_active_blocking_manual_step_still_blocks(self):
        executor = MagicMock(spec=PythonPackageExecutor)
        workflow = DevelopmentWorkflow(
            discovery=MagicMock(), validator=MagicMock(),
            preflight=MagicMock(), planner=MagicMock(), executor=executor,
        )
        blocking_activation = RequirementActivation(
            "req-blocking", True, True, "genuinely needed",
        )
        plan = SetupPlan(
            id="plan-block", project_id="proj-1",
            steps=(SetupStep(
                id="step-req-blocking", requirement_id="req-blocking",
                action="manual_review", package=None, install_method=None,
                is_approved=True,
            ),),
            status="approved",
            requirement_activations=(blocking_activation,),
        )

        with pytest.raises(WorkflowExecutionError, match="manual review"):
            workflow.execute_approved(plan)

    def test_inactive_noblocking_step_skipped_in_plan(self):
        executor = MagicMock(spec=PythonPackageExecutor)
        executor.execute.return_value = ExecutionResult(
            step_id="step-req-install", success=True, message="ok",
            verification_passed=True,
        )
        workflow = DevelopmentWorkflow(
            discovery=MagicMock(), validator=MagicMock(),
            preflight=MagicMock(), planner=MagicMock(), executor=executor,
        )
        inactive = RequirementActivation("req-inactive", False, False,
                                         "not needed")
        plan = SetupPlan(
            id="plan-inactive", project_id="proj-1",
            steps=(
                SetupStep(id="step-req-inactive", requirement_id="req-inactive",
                          action="manual_review", is_approved=True),
                SetupStep(id="step-req-install", requirement_id="req-install",
                          action="install", install_method="pip",
                          package="pkg", is_approved=True),
            ),
            status="approved",
            requirement_activations=(inactive,),
        )

        results = workflow.execute_approved(plan)
        assert len(results) == 1
        assert results[0].step_id == "step-req-install"

    def test_active_nonblocking_manual_skipped(self):
        executor = MagicMock(spec=PythonPackageExecutor)
        executor.execute.return_value = ExecutionResult(
            step_id="install-step", success=True, message="ok",
            verification_passed=True,
        )
        workflow = DevelopmentWorkflow(
            discovery=MagicMock(), validator=MagicMock(),
            preflight=MagicMock(), planner=MagicMock(), executor=executor,
        )
        active_nonblock = RequirementActivation(
            "req-active-nonblock", True, False, "active but not blocking",
        )
        plan = SetupPlan(
            id="plan-anb", project_id="proj-1",
            steps=(
                SetupStep(id="step-req-anb", requirement_id="req-active-nonblock",
                          action="manual_review", is_approved=True),
                SetupStep(id="install-step", requirement_id="req-install",
                          action="install", install_method="pip",
                          package="pkg", is_approved=True),
            ),
            status="approved",
            requirement_activations=(active_nonblock,),
        )

        results = workflow.execute_approved(plan)
        assert len(results) == 1

    def test_no_activation_data_still_validates_as_before(self):
        executor = MagicMock(spec=PythonPackageExecutor)
        executor.execute.return_value = ExecutionResult(
            step_id="step-req-1", success=True, message="ok",
            verification_passed=True,
        )
        workflow = DevelopmentWorkflow(
            discovery=MagicMock(), validator=MagicMock(),
            preflight=MagicMock(), planner=MagicMock(), executor=executor,
        )
        plan = _make_setup_plan(
            status="approved",
            steps=(_make_setup_step("step-req-1", approved=True),),
        )

        results = workflow.execute_approved(plan)
        assert len(results) == 1


class TestDevelopmentArtifactRequirementActivation:
    """CLAUDE-E2E-001: a missing development-created artifact (e.g. a
    project configuration file Development is expected to produce) must
    not block execution of the rest of an approved plan, while a genuine
    external prerequisite (executable/package/toolchain/hardware/
    connection) must still block -- using the real, unmodified
    normalize_requirement_activations default (no explicit activation
    supplied by the caller), reproducing the full CLAUDE-E2E-001 chain
    from Requirement through to DevelopmentWorkflow.execute_approved().
    """

    def test_missing_config_file_requirement_defaults_to_nonblocking_and_is_skipped(self):
        executor = MagicMock(spec=PythonPackageExecutor)
        executor.execute.return_value = ExecutionResult(
            step_id="step-install", success=True, message="ok",
            verification_passed=True,
        )
        workflow = DevelopmentWorkflow(
            discovery=MagicMock(), validator=MagicMock(),
            preflight=MagicMock(), planner=MagicMock(), executor=executor,
        )
        artifact_requirement = Requirement(
            id="req-config", name="project configuration file",
            type=RequirementType.CONFIG_FILE, purpose="project configuration",
            required=True, confidence=0.9,
        )
        other_requirement = _make_requirement("req-install")
        activations = normalize_requirement_activations(
            (artifact_requirement, other_requirement),
        )
        plan = SetupPlan(
            id="plan-artifact", project_id="proj-1",
            steps=(
                SetupStep(id="step-config", requirement_id="req-config",
                          action="manual_review", is_approved=True),
                SetupStep(id="step-install", requirement_id="req-install",
                          action="install", install_method="pip",
                          package="pkg", is_approved=True),
            ),
            status="approved",
            requirement_activations=activations,
        )

        results = workflow.execute_approved(plan)

        assert len(results) == 1
        assert results[0].step_id == "step-install"

    def test_missing_config_file_requirement_activation_is_still_represented(self):
        """The requirement remains present in the plan's activations,
        merely non-blocking -- proving the fix uses the central
        RequirementActivation mechanism rather than dropping the
        requirement or inventing a parallel exception path."""
        artifact_requirement = Requirement(
            id="req-config", name="project configuration file",
            type=RequirementType.CONFIG_FILE, purpose="project configuration",
            required=True, confidence=0.9,
        )
        activations = normalize_requirement_activations((artifact_requirement,))

        assert len(activations) == 1
        activation = activations[0]
        assert activation.requirement_id == "req-config"
        assert activation.active is True
        assert activation.blocks_current_operation is False

    def test_missing_hardware_prerequisite_still_blocks_by_default(self):
        """A genuine external prerequisite (here: required hardware) must
        retain the original required-implies-blocking default; the fix
        must not blindly make all requirement types non-blocking."""
        executor = MagicMock(spec=PythonPackageExecutor)
        workflow = DevelopmentWorkflow(
            discovery=MagicMock(), validator=MagicMock(),
            preflight=MagicMock(), planner=MagicMock(), executor=executor,
        )
        hardware_requirement = Requirement(
            id="req-device", name="ESP32 development board",
            type=RequirementType.HARDWARE_COMPONENT, purpose="target hardware",
            required=True, confidence=0.9,
        )
        activations = normalize_requirement_activations((hardware_requirement,))
        plan = SetupPlan(
            id="plan-hardware", project_id="proj-1",
            steps=(SetupStep(
                id="step-device", requirement_id="req-device",
                action="manual_review", is_approved=True,
            ),),
            status="approved",
            requirement_activations=activations,
        )

        with pytest.raises(WorkflowExecutionError, match="manual review"):
            workflow.execute_approved(plan)

    def test_explicit_activation_overrides_development_artifact_default(self):
        """An explicitly supplied activation for a config_file requirement
        (e.g. a future Council/discovery enhancement that determines it
        genuinely must pre-exist) still takes precedence over the type-based
        default -- the default never overrides an explicit decision."""
        artifact_requirement = Requirement(
            id="req-config", name="project configuration file",
            type=RequirementType.CONFIG_FILE, purpose="project configuration",
            required=True, confidence=0.9,
        )
        explicit = RequirementActivation(
            "req-config", True, True, "explicitly required by this workflow",
        )
        activations = normalize_requirement_activations(
            (artifact_requirement,), (explicit,),
        )

        assert activations == (explicit,)

    def test_missing_python_package_prerequisite_retains_controlled_setup(self):
        """Missing executable/package/toolchain prerequisites retain their
        current controlled setup behavior (installable, blocking by
        default) unaffected by the development-artifact classification."""
        executor = MagicMock(spec=PythonPackageExecutor)
        executor.execute.return_value = ExecutionResult(
            step_id="step-install", success=True, message="ok",
            verification_passed=True,
        )
        workflow = DevelopmentWorkflow(
            discovery=MagicMock(), validator=MagicMock(),
            preflight=MagicMock(), planner=MagicMock(), executor=executor,
        )
        package_requirement = _make_requirement("req-install")
        activations = normalize_requirement_activations((package_requirement,))
        assert activations[0].blocks_current_operation is True

        plan = SetupPlan(
            id="plan-package", project_id="proj-1",
            steps=(SetupStep(
                id="step-install", requirement_id="req-install",
                action="install", install_method="pip", package="pkg",
                setup_effect=SetupEffect.PYTHON_PACKAGE_INSTALL, is_approved=True,
            ),),
            status="approved",
            requirement_activations=activations,
        )

        results = workflow.execute_approved(plan)
        assert len(results) == 1
        assert results[0].step_id == "step-install"


class TestDeterministicMissingPythonPackageProductiveFlow:
    """CLAUDE-E2E-003 PART 7 / PART 9-D: a deterministic, non-LLM-driven
    reproduction of the missing-Python-package productive flow -- from
    a genuinely missing distribution through Preflight, the Engineering
    Council's ToolchainItem/SetupPlan materialization, and into
    DevelopmentWorkflow.execute_approved() -- proving the real-E2E
    shape (display-cased package name, differently-cased install_method)
    now reaches the controlled execution boundary instead of raising
    UnsupportedInstallMethodError, without depending on what the LLM
    happens to choose in any given paid E2E run.
    """

    def test_missing_python_package_is_detected_then_reaches_execution(self, tmp_path):
        # A deliberately fictional distribution name -- guaranteed absent
        # from any real Python environment, so this test's "missing"
        # premise is genuinely deterministic and never coupled to
        # whatever happens to be installed in the venv running it.
        package_name = "Some-Fictional-ADC-Test-Package"
        requirement = Requirement(
            id="req-fictional", name=package_name,
            type=RequirementType.PYTHON_PACKAGE, purpose="firmware toolchain",
            required=True, confidence=0.9,
        )

        preflight = RequirementPreflight.check(
            (requirement,), "proj-fictional",
            target_executable=sys.executable, project_root=str(tmp_path),
        )
        assert preflight.results[0].present is False
        assert preflight.results[0].target_executable == sys.executable

        item = ToolchainItem(
            requirement_ref="req-fictional", name=package_name,
            type=RequirementType.PYTHON_PACKAGE,
            install_method="pip install some-fictional-adc-test-package",
        )
        variant = CouncilVariant(id="variant-1", name="variant-1", toolchain=(item,))
        council_result = CouncilResult(
            id="council-1", project_id="proj-fictional",
            variants=(variant,), recommendation="variant-1",
            council_complete=True,
        )

        plan = ToolchainMaterializer().materialize(
            council_result, "proj-fictional", preflight=preflight,
        )
        assert len(plan.steps) == 1
        step = plan.steps[0]
        assert step.action == "install"
        assert step.package == package_name
        assert step.install_method == "pip install some-fictional-adc-test-package"
        assert step.target_executable == sys.executable

        approved_plan = replace(
            plan,
            status="approved",
            steps=(replace(step, is_approved=True),),
        )

        runner = MagicMock()
        runner.run.return_value = CommandResult(returncode=0, stdout="", stderr="")
        executor = PythonPackageExecutor(runner=runner, verifier=lambda step: True)
        workflow = DevelopmentWorkflow(
            discovery=MagicMock(), validator=MagicMock(),
            preflight=MagicMock(), planner=MagicMock(), executor=executor,
        )

        results = workflow.execute_approved(approved_plan)

        assert len(results) == 1
        assert results[0].success is True
        assert runner.run.call_count == 1
        assert runner.run.call_args[0][0] == [
            sys.executable, "-m", "pip", "install", package_name,
        ]


class TestTargetPythonSurvivesPathMutation:
    """CLAUDE-E2E-003B/003C Gap A: the target Python identity is
    resolved exactly once, by RequirementPreflight, at the start of a
    workflow/setup operation, and then carried as plain, immutable,
    ecosystem-neutral data (through
    PreflightRequirementResult.target_executable ->
    SetupStep.target_executable) into materialization, installation,
    and verification. Neither installation nor verification may
    re-resolve it from PATH later.

    Proven here by deliberately changing what "python" resolves to on
    PATH AFTER the target was selected, and confirming the
    already-resolved value from Preflight is still exactly what the
    productive install call uses -- even though a fresh, default
    PythonPackageExecutor built after the mutation would, on its own,
    resolve the new (wrong) PATH-based target.
    """

    def test_path_mutation_after_target_selection_does_not_change_the_target(
        self, monkeypatch, tmp_path,
    ):
        import subprocess
        import app.execution as execution_module

        monkeypatch.setattr(shutil, "which", lambda name: "/target/A/python")

        requirement = Requirement(
            id="req-fictional", name="Some-Fictional-ADC-Test-Package",
            type=RequirementType.PYTHON_PACKAGE, purpose="firmware toolchain",
            required=True, confidence=0.9,
        )
        preflight = RequirementPreflight.check(
            (requirement,), "proj-fictional", project_root=str(tmp_path),
        )
        assert preflight.results[0].target_executable == "/target/A/python"

        item = ToolchainItem(
            requirement_ref="req-fictional", name="Some-Fictional-ADC-Test-Package",
            type=RequirementType.PYTHON_PACKAGE,
            install_method="pip install some-fictional-adc-test-package",
        )
        variant = CouncilVariant(id="variant-1", name="variant-1", toolchain=(item,))
        council_result = CouncilResult(
            id="council-1", project_id="proj-fictional",
            variants=(variant,), recommendation="variant-1", council_complete=True,
        )
        plan = ToolchainMaterializer().materialize(
            council_result, "proj-fictional", preflight=preflight,
        )
        step = plan.steps[0]
        assert step.target_executable == "/target/A/python"

        # Target selection is done. PATH now points somewhere else
        # entirely -- this must never be revisited by install or verify.
        monkeypatch.setattr(shutil, "which", lambda name: "/target/B/python")

        approved_plan = replace(
            plan, status="approved", steps=(replace(step, is_approved=True),),
        )

        calls = []

        def fake_execute_controlled(request, project_root):
            calls.append(tuple(request.args))
            return subprocess.CompletedProcess(list(request.args), 0, "1.0\n", "")

        monkeypatch.setattr(execution_module, "execute_controlled", fake_execute_controlled)

        # Built AFTER the mutation, using the exact productive (default
        # runner) composition -- proving its OWN instance-level default
        # really did follow PATH to the new, wrong target.
        executor = PythonPackageExecutor()
        assert executor.python_executable == "/target/B/python"

        from app.setup_execution_state import SetupExecutionStateStore

        workflow = DevelopmentWorkflow(
            discovery=MagicMock(), validator=MagicMock(), preflight=MagicMock(),
            planner=MagicMock(), executor=executor,
            execution_state_store=SetupExecutionStateStore(tmp_path / "exec-state.json"),
        )

        results = workflow.execute_approved(approved_plan, str(tmp_path))

        assert len(results) == 1
        assert results[0].success is True
        install_calls = [c for c in calls if "install" in c]
        assert len(install_calls) == 1
        assert install_calls[0][0] == "/target/A/python"
        assert all("/target/B/python" not in call for call in calls)
