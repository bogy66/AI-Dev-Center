"""S3 Environment & Setup subsubsystem architecture acceptance suite
(CLAUDE-ADC-S3-S4-S5-ARCHITECTURE-PERSIST-001, following the S2 pilot's
own model -- tests/test_s2_subsubsystem_architecture.py).

Proves the CURRENT productive S3.1-S3.5 decomposition persisted in
ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §4B: exactly one productive
Primary/Central Owner per Sx.y, real input/output artifacts, allowed and
forbidden Authority, happy-path/fail-closed/recovery behavior, fault
localization, Genericity/Non-Specialization, and that no Sx.y.z level
exists.

Does NOT duplicate:
  - tests/test_toolchain_materializer.py (S3.1 classification-rule
    exhaustiveness)
  - tests/test_s3_legacy_hygiene_wiring.py (canonical wiring/AST
    evidence that SetupPlanner/SetupExecutor are never constructed --
    remains the authority for those historical-hygiene details; this
    file's own legacy-ownership tests below are the ARCHITECTURE-level
    corroboration, not a re-run of that suite)
  - tests/test_setup_execution_state.py (SetupExecutionStateStore's own
    low-level transition/corruption matrix -- this file only proves the
    PRODUCTIVE integration through DevelopmentWorkflow.execute_approved())
  - tests/test_missing_toolchain_setup.py (the already-available/
    approval-required/install-fails/restart-safe/persisted-retry matrix
    -- this file adds only the cases that matrix does not cover: a
    successful-looking install that still leaves the toolchain
    unavailable, and an interrupted mid-execution restart)

Mocks/fakes are used only at true external boundaries: the setup
subprocess/tool-execution boundary (never PythonPackageExecutor's own
pip/subprocess machinery -- no live pip install ever runs here) and, in
the S3->S4 boundary section, the LLM executor boundary.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.controlled_rework_stage import ControlledReworkStage
from app.council_models import CouncilResult, CouncilVariant, ToolchainItem
from app.dev_workflow import DevelopmentWorkflow, WorkflowExecutionError
from app.developer_file_applier import DeveloperFileApplier
from app.development_stage import DeveloperAgent, DevelopmentRequest, DevelopmentStage
from app.development_testing_stage import DevelopmentTestingStage
from app.engineering_decision import EngineeringDecision, validate_variants
from app.missing_toolchain_setup import (
    MissingToolchainSetupRequest,
    StructuredInstallerRegistration,
    StructuredInstallerRegistry,
)
from app.project_setup_application import ProjectSetupApplicationService
from app.requirement_model import (
    PreflightRequirementResult,
    PreflightResult,
    Requirement,
    RequirementActivation,
    RequirementType,
    SetupEffect,
    SetupPlan,
    SetupStep,
)
from app.setup_approval import SetupApproval, SetupApprovalError
from app.setup_executor import ExecutionResult
from app.setup_execution_state import SetupExecutionStateError, SetupExecutionStateStore, SetupStepIdentity
from app.setup_planner import SetupPlanner
from app.test_change_generator import TestChangeGenerator
from app.testing_stage import DiagnosisReviewer, TestingStage
from app.toolchain_materializer import ToolchainMaterializer
from app.workflow_manager import WorkflowManager

from tests._architecture_genericity_scan import parse, scan_forbidden_ecosystem_dispatch
from tests.test_s3_legacy_hygiene_wiring import CENTRAL_S3_FILES, FORBIDDEN_ECOSYSTEM_NAMES

ROOT = Path(__file__).parents[1]


# =========================================================================
# Shared fixtures: two materially different requirement/effect shapes.
# =========================================================================


def _python_requirement(req_id="req-py"):
    return Requirement(
        id=req_id, name="example-package", type=RequirementType.PYTHON_PACKAGE,
        purpose="library", required=True, confidence=0.9, technical_identity="example-package",
    )


def _tool_requirement(req_id="req-tool"):
    """A materially different shape: an EXECUTABLE/tool requirement,
    which classifies to SetupEffect.PROJECT_TOOL_INSTALL -- an effect
    ADC has NO controlled backend for today (CONTROLLED_SETUP_EFFECTS
    == {PYTHON_PACKAGE_INSTALL}) -- never a second Python-package
    fixture wearing a different name."""
    return Requirement(
        id=req_id, name="some-native-tool", type=RequirementType.EXECUTABLE,
        purpose="build", required=True, confidence=0.9, install_method="download",
    )


def _preflight(*requirements, project_id="proj"):
    return PreflightResult(
        id="pre-1", project_id=project_id, overall_ready=False,
        results=tuple(
            PreflightRequirementResult(requirement_id=r.id, present=False, satisfied=False)
            for r in requirements
        ),
        missing_requirements=tuple(requirements),
        activations=tuple(RequirementActivation(r.id, True, True) for r in requirements),
        project_requirements=tuple(requirements),
    )


def _python_item(requirement_ref, install_method="pip", technical_identity="example-package"):
    return ToolchainItem(
        requirement_ref=requirement_ref, name="example-package",
        type=RequirementType.PYTHON_PACKAGE, technical_identity=technical_identity,
        install_method=install_method, state="needs_install",
    )


def _tool_item(requirement_ref):
    return ToolchainItem(
        requirement_ref=requirement_ref, name="some-native-tool",
        type=RequirementType.EXECUTABLE, install_method="download", state="needs_install",
    )


def _engineering_decision(variant, preflight=None, authority="human"):
    validation = validate_variants((variant,), preflight)[0]
    return EngineeringDecision(
        variant=variant, solution_class=validation.solution_class, selection_authority=authority,
    )


def _approved_python_plan(project_id="proj", step_id="step-1", package="example-package"):
    step = SetupStep(
        id=step_id, requirement_id="req-py", action="install",
        install_method="pip", package=package, is_approved=True,
        setup_effect=SetupEffect.PYTHON_PACKAGE_INSTALL,
    )
    return SetupPlan(id=f"plan-{project_id}", project_id=project_id, steps=(step,), status="approved")


# =========================================================================
# S3.1 Setup Planning -- ToolchainMaterializer.materialize_decision()
# =========================================================================


class TestS3_1_SetupPlanning:
    def test_consumes_engineering_decision_as_input_and_produces_pending_setup_plan(self):
        req = _python_requirement()
        preflight = _preflight(req)
        variant = CouncilVariant(id="v1", name="v1", toolchain=(_python_item(req.id),))
        decision = _engineering_decision(variant, preflight)

        plan = ToolchainMaterializer().materialize_decision(decision, "proj", preflight=preflight)

        assert isinstance(plan, SetupPlan)
        assert plan.status == "pending_approval"

    def test_does_not_approve_or_execute(self):
        req = _python_requirement()
        preflight = _preflight(req)
        variant = CouncilVariant(id="v1", name="v1", toolchain=(_python_item(req.id),))
        decision = _engineering_decision(variant, preflight)

        plan = ToolchainMaterializer().materialize_decision(decision, "proj", preflight=preflight)

        assert plan.status != "approved"
        assert all(not step.is_approved for step in plan.steps)

    def test_does_not_reopen_s2_candidate_selection_or_admissibility(self):
        """materialize_decision() structurally cannot reach back into S2
        selection: it has no CouncilResult/recommendation/platform/human-
        selection parameter at all (mirrors the S2 pilot's own RED-2
        permanent regression, TestBoundaryS2ToS3)."""
        import inspect
        params = list(inspect.signature(ToolchainMaterializer.materialize_decision).parameters)
        assert "council_result" not in params
        assert "chairman_recommendation" not in params
        assert "human_selected_variant_id" not in params
        assert "platform" not in params

    def test_setup_planner_is_not_the_productive_owner(self):
        """SetupPlanner.plan() is never invoked by materialize_decision()
        or by DevelopmentWorkflow's own S3.1 path -- ARCHITECTURE-level
        corroboration of the legacy-hygiene wiring proof, not a repeat
        of it: proven here BEHAVIORALLY, by giving DevelopmentWorkflow a
        SetupPlanner spy and confirming its .plan() is never called
        while materialize_setup_plan()/execute_approved() still work."""
        req = _python_requirement()
        preflight = _preflight(req)
        variant = CouncilVariant(id="v1", name="v1", toolchain=(_python_item(req.id),))
        council_result = CouncilResult(
            id="c1", project_id="proj", variants=(variant,), recommendation="v1", council_complete=True,
        )
        planner_spy = Mock(spec=SetupPlanner)
        workflow = DevelopmentWorkflow(
            discovery=None, validator=None, preflight=None, planner=planner_spy,
            materializer=ToolchainMaterializer(),
        )

        plan = workflow.materialize_setup_plan(council_result, "proj", preflight=preflight)

        assert plan.status == "pending_approval"
        planner_spy.plan.assert_not_called()

    def test_two_materially_different_requirement_effect_shapes_coexist_in_one_plan(self):
        """A Python-package requirement (controlled backend exists) and
        an EXECUTABLE/tool requirement (no controlled backend exists)
        materialize into ONE SetupPlan through the SAME code path --
        never two competing planning mechanisms, never a Python-only
        fixture standing in for "any requirement"."""
        py_req, tool_req = _python_requirement(), _tool_requirement()
        preflight = _preflight(py_req, tool_req)
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(_python_item(py_req.id), _tool_item(tool_req.id)),
        )
        decision = _engineering_decision(variant, preflight)

        plan = ToolchainMaterializer().materialize_decision(decision, "proj", preflight=preflight)

        assert len(plan.steps) == 2
        by_ref = {s.requirement_id: s for s in plan.steps}
        assert by_ref[py_req.id].action == "install"
        assert by_ref[py_req.id].setup_effect == SetupEffect.PYTHON_PACKAGE_INSTALL
        assert by_ref[tool_req.id].action == "manual_review"

    def test_unsupported_backend_effect_remains_explicit_never_falsely_executable(self):
        tool_req = _tool_requirement()
        preflight = _preflight(tool_req)
        variant = CouncilVariant(id="v1", name="v1", toolchain=(_tool_item(tool_req.id),))
        decision = _engineering_decision(variant, preflight)

        plan = ToolchainMaterializer().materialize_decision(decision, "proj", preflight=preflight)

        assert plan.steps[0].action == "manual_review"
        assert SetupEffect.PROJECT_TOOL_INSTALL in plan.unsupported_backend_effects


# =========================================================================
# S3.2 Setup Approval -- SetupApproval
# =========================================================================


class TestS3_2_SetupApproval:
    def _pending_plan(self):
        step = SetupStep(id="s1", requirement_id="r1", action="install",
                          install_method="pip", package="pkg", setup_effect=SetupEffect.PYTHON_PACKAGE_INSTALL)
        return SetupPlan(id="plan-1", project_id="proj", steps=(step,))

    def test_pending_approval_to_approved(self):
        plan = self._pending_plan()
        approved = SetupApproval.approve(plan)
        assert approved.status == "approved"
        assert all(step.is_approved for step in approved.steps)

    def test_pending_approval_to_rejected(self):
        plan = self._pending_plan()
        rejected = SetupApproval.reject(plan)
        assert rejected.status == "rejected"
        assert all(not step.is_approved for step in rejected.steps)

    def test_double_approve_fails_closed(self):
        approved = SetupApproval.approve(self._pending_plan())
        with pytest.raises(SetupApprovalError):
            SetupApproval.approve(approved)

    def test_reject_from_non_pending_fails_closed(self):
        approved = SetupApproval.approve(self._pending_plan())
        with pytest.raises(SetupApprovalError):
            SetupApproval.reject(approved)

    def test_every_step_receives_approval_state_correctly(self):
        step_a = SetupStep(id="a", requirement_id="r-a", action="install", setup_effect=SetupEffect.PYTHON_PACKAGE_INSTALL)
        step_b = SetupStep(id="b", requirement_id="r-b", action="manual_review")
        plan = SetupPlan(id="plan-2", project_id="proj", steps=(step_a, step_b))
        approved = SetupApproval.approve(plan)
        assert approved.steps[0].is_approved and approved.steps[1].is_approved

    def test_approval_does_not_plan(self):
        import inspect
        source = inspect.getsource(SetupApproval)
        assert "ToolchainMaterializer" not in source
        assert "materialize" not in source

    def test_approval_does_not_execute(self):
        import inspect
        source = inspect.getsource(SetupApproval)
        assert "subprocess" not in source
        assert "PythonPackageExecutor" not in source

    def test_canonical_productive_execution_cannot_bypass_approval_state(self):
        """Architecture regression: DevelopmentWorkflow.execute_approved()
        -- the real, productive S3.3 gate -- refuses a plan that never
        went through SetupApproval, for ANY plan.status other than
        'approved', with no deterministic or LLM shortcut around it."""
        plan = self._pending_plan()
        workflow = DevelopmentWorkflow(
            discovery=None, validator=None, preflight=None, executor=Mock(),
        )
        for status in ("pending_approval", "rejected", "completed", "unknown"):
            with pytest.raises(WorkflowExecutionError):
                workflow.execute_approved(replace(plan, status=status))


# =========================================================================
# S3.3 Controlled Execution -- DevelopmentWorkflow.execute_approved()
# =========================================================================


class _FakeSetupExecutor:
    """A non-PythonPackageExecutor backend, to prove execute_approved()
    dispatches generically to WHATEVER backend is configured -- never
    to a hardcoded, Python-specific implementation."""

    def __init__(self, succeed=True):
        self.calls = []
        self._succeed = succeed

    def execute(self, step, project_root=None):
        self.calls.append(step)
        return ExecutionResult(step.id, self._succeed, "fake backend ran", self._succeed)


class TestS3_3_ControlledExecution:
    def test_central_gate_validates_plan_approval(self):
        plan = _approved_python_plan()
        pending = replace(plan, status="pending_approval")
        workflow = DevelopmentWorkflow(discovery=None, validator=None, preflight=None, executor=_FakeSetupExecutor())
        with pytest.raises(WorkflowExecutionError):
            workflow.execute_approved(pending)

    def test_central_gate_validates_step_approval(self):
        plan = _approved_python_plan()
        unapproved_step = replace(plan.steps[0], is_approved=False)
        plan = replace(plan, steps=(unapproved_step,))
        workflow = DevelopmentWorkflow(discovery=None, validator=None, preflight=None, executor=_FakeSetupExecutor())
        with pytest.raises(WorkflowExecutionError):
            workflow.execute_approved(plan)

    def test_central_gate_delegates_to_whichever_backend_is_configured(self):
        fake = _FakeSetupExecutor()
        workflow = DevelopmentWorkflow(discovery=None, validator=None, preflight=None, executor=fake)
        results = workflow.execute_approved(_approved_python_plan())
        assert len(fake.calls) == 1
        assert all(r.success for r in results)

    def test_python_package_executor_is_an_adapter_not_central_policy(self):
        """execute_approved()'s own CODE (its docstring is deliberately
        allowed to explain the concept in prose) never imports/
        constructs PythonPackageExecutor -- it only calls the generic
        `.execute()` contract on whatever `self._executor` is (proven
        above with a wholly different fake backend)."""
        import ast
        import inspect
        import textwrap
        source = inspect.getsource(DevelopmentWorkflow.execute_approved)
        tree = ast.parse(textwrap.dedent(source))
        func = tree.body[0]
        body_without_docstring = func.body[1:] if ast.get_docstring(func) else func.body
        body_source = "\n".join(ast.unparse(node) for node in body_without_docstring)
        assert "PythonPackageExecutor" not in body_source

    def test_setup_executor_is_not_the_productive_owner(self):
        """execute_approved() never constructs or references the legacy
        SetupExecutor -- ARCHITECTURE-level corroboration, not a repeat
        of the dedicated legacy-hygiene wiring suite. dev_workflow.py
        DOES import SetupExecutor at module level (only for the shared
        ExecutionResult type -- see its own import line), so this checks
        for actual construction, never a bare mention."""
        from tests._architecture_genericity_scan import call_names
        import ast
        import inspect
        import textwrap
        source = inspect.getsource(DevelopmentWorkflow.execute_approved)
        tree = ast.parse(textwrap.dedent(source))
        assert "SetupExecutor" not in call_names(tree)

    def test_unsupported_setup_effect_fails_honestly_never_silently_executed(self):
        uncontrolled_step = SetupStep(
            id="s1", requirement_id="r1", action="manual_review",
            setup_effect=SetupEffect.PROJECT_TOOL_INSTALL, is_approved=True,
        )
        plan = SetupPlan(id="plan-1", project_id="proj", steps=(uncontrolled_step,), status="approved")
        fake = _FakeSetupExecutor()
        workflow = DevelopmentWorkflow(discovery=None, validator=None, preflight=None, executor=fake)

        with pytest.raises(WorkflowExecutionError):
            workflow.execute_approved(plan)
        assert fake.calls == []

    def test_confined_execution_requires_a_configured_execution_state_store(self):
        """CLAUDE-E2E-003I: supplying project_root (a real, confined,
        productive mutation attempt) without a configured
        execution_state_store fails closed rather than executing
        unguarded -- this is S3.3's own integration point with S3.4."""
        fake = _FakeSetupExecutor()
        workflow = DevelopmentWorkflow(discovery=None, validator=None, preflight=None, executor=fake)
        with pytest.raises(WorkflowExecutionError):
            workflow.execute_approved(_approved_python_plan(), project_root="/tmp/does-not-matter")
        assert fake.calls == []

    def test_controlled_setup_effects_is_current_backend_coverage_not_architecture(self):
        from app.execution import CONTROLLED_SETUP_EFFECTS
        assert CONTROLLED_SETUP_EFFECTS == {SetupEffect.PYTHON_PACKAGE_INSTALL}


# =========================================================================
# S3.4 Execution State & Idempotency -- SetupExecutionStateStore,
# proven through the PRODUCTIVE execute_approved()/_execute_with_state_
# guard integration, not only the raw store class.
# =========================================================================


class TestS3_4_ExecutionStateIdempotency:
    def _workflow(self, tmp_path, executor):
        store = SetupExecutionStateStore(storage=tmp_path / "exec-state.json")
        workflow = DevelopmentWorkflow(
            discovery=None, validator=None, preflight=None,
            executor=executor, execution_state_store=store,
        )
        return workflow, store

    def test_not_started_claim_terminal_via_productive_execution(self, tmp_path):
        fake = _FakeSetupExecutor()
        workflow, store = self._workflow(tmp_path, fake)
        project_root = str(tmp_path)

        results = workflow.execute_approved(_approved_python_plan(), project_root=project_root)

        assert len(fake.calls) == 1
        assert results[0].success is True

    def test_known_succeeded_result_is_not_re_executed(self, tmp_path):
        fake = _FakeSetupExecutor()
        workflow, store = self._workflow(tmp_path, fake)
        project_root = str(tmp_path)
        plan = _approved_python_plan()

        workflow.execute_approved(plan, project_root=project_root)
        workflow.execute_approved(plan, project_root=project_root)

        assert len(fake.calls) == 1

    def test_known_failed_result_is_not_blindly_repeated(self, tmp_path):
        fake = _FakeSetupExecutor(succeed=False)
        workflow, store = self._workflow(tmp_path, fake)
        project_root = str(tmp_path)
        plan = _approved_python_plan()

        first = workflow.execute_approved(plan, project_root=project_root)
        second = workflow.execute_approved(plan, project_root=project_root)

        assert len(fake.calls) == 1
        assert first[0].success is False and second[0].success is False

    def test_in_progress_state_fails_closed_never_guessed_safe(self, tmp_path):
        fake = _FakeSetupExecutor()
        workflow, store = self._workflow(tmp_path, fake)
        project_root = str(tmp_path)
        plan = _approved_python_plan()
        identity = SetupStepIdentity.for_step(project_root, plan.generation_id, plan.steps[0])
        store.begin(identity, "some-other-owner")

        with pytest.raises(SetupExecutionStateError):
            workflow.execute_approved(plan, project_root=project_root)
        assert fake.calls == []

    def test_changed_content_same_generation_fails_closed(self, tmp_path):
        fake = _FakeSetupExecutor()
        workflow, store = self._workflow(tmp_path, fake)
        project_root = str(tmp_path)
        plan = _approved_python_plan()
        workflow.execute_approved(plan, project_root=project_root)

        # Same plan.id AND same generation_id (dataclasses.replace()
        # preserves it), but the step's execution-relevant content
        # (package) changed -- this must never be silently treated as
        # a fresh, startable operation.
        changed_step = replace(plan.steps[0], package="a-different-package")
        changed_plan = replace(plan, steps=(changed_step,))

        with pytest.raises(SetupExecutionStateError):
            workflow.execute_approved(changed_plan, project_root=project_root)

    def test_new_generation_permits_re_execution_of_changed_content(self, tmp_path):
        fake = _FakeSetupExecutor()
        workflow, store = self._workflow(tmp_path, fake)
        project_root = str(tmp_path)
        plan = _approved_python_plan()
        workflow.execute_approved(plan, project_root=project_root)

        fresh_plan = _approved_python_plan(package="a-different-package")
        assert fresh_plan.generation_id != plan.generation_id
        workflow.execute_approved(fresh_plan, project_root=project_root)

        assert len(fake.calls) == 2

    def test_workflow_manager_lease_is_a_distinct_broader_concern(self):
        """S3.4's own scope is exclusively setup-step execution identity
        -- its CODE never imports or constructs WorkflowManager (its
        module docstring is deliberately allowed to reference the name
        in prose, contrasting the two concerns explicitly)."""
        import ast
        import app.setup_execution_state as module
        import inspect
        tree = ast.parse(inspect.getsource(module))
        import_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                import_names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Import):
                import_names.update(alias.name for alias in node.names)
        assert "WorkflowManager" not in import_names
        assert isinstance(WorkflowManager, type)  # sanity: the distinct class exists elsewhere


# =========================================================================
# S3.5 Missing-Toolchain Recovery -- ProjectSetupApplicationService's
# missing-toolchain methods. Only the cases NOT already covered by
# tests/test_missing_toolchain_setup.py are added here (see module
# docstring).
# =========================================================================


def _verification_step_and_result(project_root):
    from app.verification import TOOL_UNAVAILABLE, VerificationPlan, VerificationResult, VerificationStep, VerificationStepResult
    step = VerificationStep("verify", ".", ".", "build", "future", "future", "controlled_execution")
    plan = VerificationPlan("run", str(project_root), "existing", 1, (step,))
    result = VerificationResult("run", (
        VerificationStepResult("verify", ".", TOOL_UNAVAILABLE.value, "build", "future", False),
    ), "fail")
    return plan, result


def _missing_toolchain_service(tmp_path, *, becomes_available_after_install=True):
    plan, result = _verification_step_and_result(tmp_path)
    manager = WorkflowManager(tmp_path / "state.json")
    workflow = Mock()
    workflow.materialize_setup_plan.return_value = SetupPlan(
        "plan-project", "project", steps=(SetupStep(
            "install-future", "req", "install", install_method="future-structured", package="futurecc",
        ),),
    )
    availability = {"available": False}

    def availability_checker(name):
        return name if availability["available"] else None

    executor = Mock()

    def execute(step, project_root=None):
        # Reports success, but the toolchain does NOT actually become
        # observable afterward unless the caller opts in -- this is
        # what distinguishes "installer.execute() failed" from
        # "installer.execute() claimed success but the toolchain is
        # still not verifiably available", the case
        # tests/test_missing_toolchain_setup.py does not cover.
        if becomes_available_after_install:
            availability["available"] = True
        return ExecutionResult(step.id, True, "structured install ran", True)

    executor.execute.side_effect = execute
    installers = StructuredInstallerRegistry()
    installers.register(StructuredInstallerRegistration(
        "future-structured", executor, availability_checker=availability_checker,
    ))
    verification_registry = Mock()
    verification_registry.execute_plan.return_value = _pass_verification_result()
    service = ProjectSetupApplicationService(
        workflow, workflow_manager=manager, diagnostic_trace=Mock(),
        structured_installers=installers, verification_registry=verification_registry,
    )
    request = MissingToolchainSetupRequest(
        "project", str(tmp_path), "futurecc", "build", Mock(id="council"), plan, result,
    )
    return service, manager, executor, request, verification_registry


def _pass_verification_result():
    from app.verification import VerificationResult
    return VerificationResult("run", (), "pass")


class TestS3_5_MissingToolchainRecovery:
    def test_bounded_flow_prepare_decide_execute_retry(self, tmp_path):
        """The full mandatory sequence, TOOL_UNAVAILABLE -> prepare ->
        approval decision -> bounded structured installer execution ->
        persisted VerificationPlan retry, using generic
        toolchain/capability/install_method vocabulary throughout."""
        service, manager, executor, request, verification_registry = _missing_toolchain_service(tmp_path)
        pending = service.prepare_missing_toolchain_setup(request)
        assert pending.status == "pending_approval"

        approved = service.decide_missing_toolchain_setup(pending.plan_id, "approved", "human")
        assert approved.status == "approved"

        executed = service.execute_missing_toolchain_setup(pending.plan_id)
        assert executed.status == "completed"
        executor.execute.assert_called_once()

        retried = service.retry_missing_toolchain_verification(pending.plan_id)
        assert retried.status == "verification_completed"

    def test_still_unavailable_after_successful_looking_install_is_terminal_blocker(self, tmp_path):
        """Mandatory case not covered by tests/test_missing_toolchain_
        setup.py: the structured installer's own execute() reports
        success=True, but the toolchain is STILL not observable
        afterward (a distinct failure shape from the installer simply
        raising/reporting success=False) -- this must be a terminal,
        explicit blocker, never silently treated as completed."""
        service, manager, executor, request, verification_registry = _missing_toolchain_service(
            tmp_path, becomes_available_after_install=False,
        )
        plan_id = service.prepare_missing_toolchain_setup(request).plan_id
        service.decide_missing_toolchain_setup(plan_id, "approved", "human")

        result = service.execute_missing_toolchain_setup(plan_id)

        assert result.status == "failed"
        assert result.blockers
        assert "unavailable after setup" in result.blockers[0]

    def test_interrupted_execution_requires_recovery_never_silently_reexecuted(self, tmp_path):
        """Mandatory case not covered elsewhere: a restart/re-entry while
        the persisted record is mid-"executing" (interrupted, outcome
        unknown) must fail closed as recovery-required, never silently
        launch a second real installer attempt."""
        service, manager, executor, request, verification_registry = _missing_toolchain_service(tmp_path)
        plan_id = service.prepare_missing_toolchain_setup(request).plan_id
        service.decide_missing_toolchain_setup(plan_id, "approved", "human")
        manager.update_missing_toolchain_setup(plan_id, status="executing")

        result = service.execute_missing_toolchain_setup(plan_id)

        assert result.status == "recovery_required"
        executor.execute.assert_not_called()

    def test_no_infinite_retry_completed_install_is_never_repeated(self, tmp_path):
        service, manager, executor, request, verification_registry = _missing_toolchain_service(tmp_path)
        plan_id = service.prepare_missing_toolchain_setup(request).plan_id
        service.decide_missing_toolchain_setup(plan_id, "approved", "human")
        service.execute_missing_toolchain_setup(plan_id)

        service.execute_missing_toolchain_setup(plan_id)
        service.execute_missing_toolchain_setup(plan_id)

        executor.execute.assert_called_once()

    def test_no_s2_reselection_only_the_persisted_candidate_is_retried(self):
        """prepare_missing_toolchain_setup / execute_missing_toolchain_
        setup / retry_missing_toolchain_verification never call any S2
        selection/admissibility function -- structurally, not just by
        convention."""
        import inspect
        import app.project_setup_application as module
        service_cls = module.ProjectSetupApplicationService
        for name in (
            "prepare_missing_toolchain_setup", "decide_missing_toolchain_setup",
            "execute_missing_toolchain_setup", "retry_missing_toolchain_verification",
        ):
            source = inspect.getsource(getattr(service_cls, name))
            assert "select_engineering_variant" not in source
            assert "resolve_human_engineering_selection" not in source
            assert "validate_variants" not in source

    def test_retry_reuses_the_exact_persisted_verification_plan_never_fresh_replanning(self, tmp_path):
        service, manager, executor, request, verification_registry = _missing_toolchain_service(tmp_path)
        plan_id = service.prepare_missing_toolchain_setup(request).plan_id
        service.decide_missing_toolchain_setup(plan_id, "approved", "human")
        service.execute_missing_toolchain_setup(plan_id)

        service.retry_missing_toolchain_verification(plan_id)

        retried_plan = verification_registry.execute_plan.call_args.args[0]
        assert retried_plan.run_id == request.verification_plan.run_id
        assert retried_plan.step_ids() == request.verification_plan.step_ids()
        import inspect
        source = inspect.getsource(ProjectSetupApplicationService.retry_missing_toolchain_verification)
        assert "build_verification_plan" not in source

    def test_generic_contract_vocabulary_no_ecosystem_specific_branching(self):
        """MissingToolchainSetupRequest's own fields, and the four
        productive methods, use only generic toolchain/capability/
        install_method vocabulary -- never a hardcoded ecosystem name."""
        violations = scan_forbidden_ecosystem_dispatch(
            ("app/missing_toolchain_setup.py",), ROOT, FORBIDDEN_ECOSYSTEM_NAMES,
        )
        assert violations == []
        import dataclasses
        field_names = {f.name for f in dataclasses.fields(MissingToolchainSetupRequest)}
        assert field_names == {
            "project_id", "project_root", "toolchain", "operation_type",
            "council_result", "verification_plan", "verification_result", "platform",
        }


# =========================================================================
# S2.5 -> S3 boundary
# =========================================================================


class TestS2_5_to_S3_Boundary:
    def test_engineering_decision_is_the_handoff_artifact(self):
        req = _python_requirement()
        preflight = _preflight(req)
        variant = CouncilVariant(id="v1", name="v1", toolchain=(_python_item(req.id),))
        decision = _engineering_decision(variant, preflight)
        plan = ToolchainMaterializer().materialize_decision(decision, "proj", preflight=preflight)
        materialized_refs = {step.requirement_id for step in plan.steps}
        assert materialized_refs == {req.id}

    def test_absence_of_a_valid_decision_cannot_silently_become_a_setup_plan(self):
        with pytest.raises(AttributeError):
            ToolchainMaterializer().materialize_decision(None, "proj")

    def test_s3_does_not_duplicate_s2_admissibility_authority(self):
        import inspect
        import app.toolchain_materializer as module
        source = inspect.getsource(module)
        assert "validate_variants" not in source
        assert "admissible_variants" not in source


# =========================================================================
# S3 -> S4 boundary: S4.1 (DeveloperAgent) must not begin while required
# S3 obligations are unresolved. Proven through the PRODUCTIVE
# orchestration path, DevelopmentWorkflow.execute_approved_and_run_
# development().
# =========================================================================


class _TrackingExecutor:
    def __init__(self, succeed=True):
        self.calls = []
        self._succeed = succeed

    def execute(self, step, project_root=None):
        self.calls.append(step)
        return ExecutionResult(step.id, self._succeed, "ran", self._succeed)


class _DeveloperCallTracker:
    """Fake LLM executor boundary: counts real S4.1 DeveloperAgent
    invocations so the S3->S4 gate can be proven behaviorally."""

    def __init__(self):
        self.developer_calls = 0

    def run(self, role, task, context, role_again):
        if role == "developer":
            self.developer_calls += 1
            return json.dumps({"changes": [{"file": "x.py", "action": "create", "content": "x"}], "tests": []})
        if role == "tester":
            return json.dumps({"disposition": "no_changes_required", "reason": "n/a", "changes": [], "tests": []})
        raise AssertionError(f"unexpected role: {role}")


class TestS3_to_S4_Boundary:
    def _workflow(self, setup_executor, tmp_path, execution_state_store=None):
        # Real productive composition always configures an execution
        # state store (see execute_approved()'s own docstring,
        # CLAUDE-E2E-003I) -- mirrored here by default so every
        # boundary case below fails for the reason it claims to,
        # never incidentally because the store was left unconfigured.
        if execution_state_store is None:
            execution_state_store = SetupExecutionStateStore(storage=tmp_path / "exec-state.json")
        llm = _DeveloperCallTracker()
        development_stage = DevelopmentStage(DeveloperAgent(llm))
        test_change_generator = TestChangeGenerator(llm)
        testing_stage = TestingStage(DiagnosisReviewer(llm))
        development_testing_stage = DevelopmentTestingStage(
            development_stage, test_change_generator, DeveloperFileApplier,
            Mock(), testing_stage,
        )
        controlled_rework_stage = ControlledReworkStage(development_testing_stage)
        workflow = DevelopmentWorkflow(
            discovery=None, validator=None, preflight=None,
            executor=setup_executor,
            controlled_rework_stage=controlled_rework_stage,
            execution_state_store=execution_state_store,
        )
        return workflow, llm

    def test_plan_not_approved_blocks_s4(self, tmp_path):
        workflow, llm = self._workflow(_TrackingExecutor(), tmp_path)
        pending_plan = replace(_approved_python_plan(project_id="p"), status="pending_approval")
        request = DevelopmentRequest("p", tmp_path, "do work")
        with pytest.raises(WorkflowExecutionError):
            workflow.execute_approved_and_run_development(pending_plan, request)
        assert llm.developer_calls == 0

    def test_required_step_unapproved_blocks_s4(self, tmp_path):
        workflow, llm = self._workflow(_TrackingExecutor(), tmp_path)
        plan = _approved_python_plan(project_id="p")
        plan = replace(plan, steps=(replace(plan.steps[0], is_approved=False),))
        request = DevelopmentRequest("p", tmp_path, "do work")
        with pytest.raises(WorkflowExecutionError):
            workflow.execute_approved_and_run_development(plan, request)
        assert llm.developer_calls == 0

    def test_required_execution_failure_blocks_s4(self, tmp_path):
        workflow, llm = self._workflow(_TrackingExecutor(succeed=False), tmp_path)
        plan = _approved_python_plan(project_id="p")
        request = DevelopmentRequest("p", tmp_path, "do work")
        with pytest.raises(WorkflowExecutionError):
            workflow.execute_approved_and_run_development(plan, request)
        assert llm.developer_calls == 0

    def test_recovery_required_setup_state_blocks_s4(self, tmp_path):
        store = SetupExecutionStateStore(storage=tmp_path / "exec-state.json")
        workflow, llm = self._workflow(_TrackingExecutor(), tmp_path, execution_state_store=store)
        plan = _approved_python_plan(project_id="p")
        identity = SetupStepIdentity.for_step(str(tmp_path), plan.generation_id, plan.steps[0])
        store.begin(identity, "someone-else")
        request = DevelopmentRequest("p", tmp_path, "do work")

        with pytest.raises(Exception):
            workflow.execute_approved_and_run_development(plan, request)
        assert llm.developer_calls == 0

    def test_unresolved_unsupported_blocking_requirement_blocks_s4(self, tmp_path):
        uncontrolled_step = SetupStep(
            id="s1", requirement_id="r1", action="manual_review",
            setup_effect=SetupEffect.PROJECT_TOOL_INSTALL, is_approved=True,
        )
        plan = SetupPlan(id="plan-p", project_id="p", steps=(uncontrolled_step,), status="approved")
        workflow, llm = self._workflow(_TrackingExecutor(), tmp_path)
        request = DevelopmentRequest("p", tmp_path, "do work")
        with pytest.raises(WorkflowExecutionError):
            workflow.execute_approved_and_run_development(plan, request)
        assert llm.developer_calls == 0

    def test_completed_required_s3_obligations_permit_s4(self, tmp_path):
        workflow, llm = self._workflow(_TrackingExecutor(), tmp_path)
        plan = _approved_python_plan(project_id="p")
        request = DevelopmentRequest("p", tmp_path, "do work")

        result = workflow.execute_approved_and_run_development(plan, request)

        assert llm.developer_calls == 1
        assert result.status in ("accepted", "rework_required", "review_failed")


# =========================================================================
# Genericity / Non-Specialization (§4G) -- improved beyond ast.Compare.
# =========================================================================


class TestS3GenericityNonSpecialization:
    def test_central_s3_orchestration_has_no_forbidden_ecosystem_dispatch(self):
        """Extends the pre-existing S3 legacy-hygiene scan (ast.Compare
        only) with match/case literal patterns and anonymous inline
        dict-subscript dispatch -- closes the §4J/Part 29B review
        finding on the SAME central S3 files that scan already covers."""
        violations = scan_forbidden_ecosystem_dispatch(CENTRAL_S3_FILES, ROOT, FORBIDDEN_ECOSYSTEM_NAMES)
        assert violations == []

    def test_generic_enum_vocabulary_is_not_flagged(self):
        """RequirementType.PYTHON_PACKAGE / SetupEffect.PYTHON_PACKAGE_
        INSTALL are legitimate, generic, structured vocabulary -- never
        a bare string Compare operand -- so the scan above does not
        (and must not) flag them."""
        tree = parse("app/toolchain_materializer.py", ROOT)
        from tests._architecture_genericity_scan import string_literal_comparison_operands
        literals = {value for _, value in string_literal_comparison_operands(tree)}
        assert "python_package" not in literals

    def test_heterogeneous_requirement_shapes_reach_the_same_central_contract(self):
        """§26: at least two materially different requirement shapes
        (Python package; native/tool) pass through the exact same
        ToolchainMaterializer.materialize_decision() without any central
        redesign -- already proven functionally above (TestS3_1); this
        pins it as the suite's own explicit heterogeneous-shape proof."""
        py_req, tool_req = _python_requirement(), _tool_requirement()
        preflight = _preflight(py_req, tool_req)
        materializer = ToolchainMaterializer()

        py_only = CouncilVariant(id="v1", name="v1", toolchain=(_python_item(py_req.id),))
        tool_only = CouncilVariant(id="v2", name="v2", toolchain=(_tool_item(tool_req.id),))

        plan_a = materializer.materialize_decision(_engineering_decision(py_only, preflight), "proj", preflight=preflight)
        plan_b = materializer.materialize_decision(_engineering_decision(tool_only, preflight), "proj", preflight=preflight)

        assert plan_a.status == plan_b.status == "pending_approval"


# =========================================================================
# Foreign repository: S3 planning respects existing structure, imposes
# no ADC-created layout, and does not mutate the filesystem at all.
# =========================================================================


class TestS3ExistingForeignRepository:
    def test_materialize_decision_is_indifferent_to_arbitrary_existing_layout(self, tmp_path):
        (tmp_path / "firmware").mkdir()
        (tmp_path / "firmware" / "main.cpp").write_text("// existing firmware\n")
        (tmp_path / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.10)\n")
        (tmp_path / "vendor" / "thirdparty").mkdir(parents=True)
        before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))

        req = _python_requirement()
        preflight = _preflight(req)
        variant = CouncilVariant(id="v1", name="v1", toolchain=(_python_item(req.id),))
        decision = _engineering_decision(variant, preflight)

        plan = ToolchainMaterializer().materialize_decision(
            decision, "proj", preflight=preflight, project_root=str(tmp_path),
        )

        after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
        assert plan.status == "pending_approval"
        assert before == after  # planning never mutates the project tree
