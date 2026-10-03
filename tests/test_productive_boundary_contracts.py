"""Productive boundary-contract tests (OC-ADC-BOUNDARY-COVERAGE-AUDIT-FIX-002).

Deterministic offline tests for real Producer->Artifact->Consumer boundaries.
All tests are hermetic (isolated stores in tmp_path, no CWD side-effects).

Coverage levels reported honestly, never overclaimed:
  TC-B-S3.2-S3.3 auth-gate: FULLY_PRODUCTIVE (real authorize_setup_plan_targets)
  TC-B-S3.2-S3.3 lifecycle: PARTIAL (mock downstream service; real
    plan_store round-trip and council ref forwarding proven)
  TC-B-S3-S4 handoff: PARTIAL (odiates execute_approved() in isolation;
    the real orchestration is covered by test_s3_subsubsystem_architecture)
  TC-B-S5-S6 gate: PARTIAL (string-fed gate; see below)
  TC-B-S5-S6 productive: FULLY_PRODUCTIVE (TestS5_S6_ProductiveComposition:
    canonical service -> real S5 result -> real Final Approval; only the
    external LLM provider is substituted)
  TC-B-BYPASS: isolated fail-closed guards (not full end-to-end bypasses)
  TC-B-S1-S2: SEPARATED_UNITS (both artifacts manually constructed;
    no real S1->S2 transformer exercised)
"""

from __future__ import annotations

import json
import sys

from dataclasses import replace
from datetime import datetime
from pathlib import Path
import sys
import time
from unittest.mock import MagicMock

import pytest

from app.council_models import CouncilResult, CouncilVariant, CouncilInput, ToolchainItem
from app.dev_workflow import DevelopmentWorkflow, WorkflowExecutionError
from app.execution import (
    CapabilityRegistry,
    ExecutionRequest,
    validate_request,
)
from app.final_approval import FinalApprovalError
from app.project_setup_application import (
    approve_setup_plan,
    authorize_setup_plan_targets,
    execute_approved_plan_from_store,
    persist_setup_plan,
)
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
from app.setup_approval import SetupApproval
from app.setup_execution_state import (
    SetupExecutionStateError,
    SetupExecutionStateStore,
    SetupStepIdentity,
)
from app.setup_executor import ExecutionResult
from app.toolchain_materializer import ToolchainMaterializer
from app.workflow_manager import WorkflowManager
from app.workflow_plan_store import WorkflowPlanStore


# ---------------------------------------------------------------------------
# Shared deterministic fixtures (adapted from test_central_workflow_system.py)
# ---------------------------------------------------------------------------

def _requirement(req_id, req_type=RequirementType.PYTHON_PACKAGE, **kwargs):
    base = {
        "id": req_id,
        "name": req_id.replace("-", " ").title(),
        "type": req_type,
        "purpose": "purpose of " + req_id,
        "required": True,
        "confidence": 1.0,
        "install_method": "pip",
    }
    if req_type == RequirementType.PYTHON_PACKAGE:
        base["technical_identity"] = req_id
    base.update(kwargs)
    accepted = {f.name for f in Requirement.__dataclass_fields__.values()}
    return Requirement(**{k: v for k, v in base.items() if k in accepted})


def _activation(req_id, active=True, blocks=True):
    return RequirementActivation(
        requirement_id=req_id, active=active,
        blocks_current_operation=blocks, reason="test",
    )


def _toolchain_item(req_ref, name=None, type_=RequirementType.PYTHON_PACKAGE,
                    install_method="pip", state="needs_install", version=None):
    if name is None:
        name = req_ref if type_ == RequirementType.PYTHON_PACKAGE else req_ref.replace("-", " ").title()
    return ToolchainItem(
        requirement_ref=req_ref, name=name, type=type_,
        install_method=install_method, version=version, state=state,
    )


def _variant(variant_id="variant-selected", toolchain=()):
    return CouncilVariant(
        id=variant_id, name=variant_id.replace("-", " ").title(),
        toolchain=tuple(toolchain),
    )


def _council_result(variant, project_id="test-project"):
    return CouncilResult(
        id="council-" + project_id, project_id=project_id,
        variants=(variant,), recommendation=variant.id,
        council_complete=True,
    )


def _materialize(variant, preflight=None, project_id="test-project"):
    return ToolchainMaterializer().materialize(
        _council_result(variant, project_id=project_id),
        project_id, preflight=preflight,
    )


def _exec_success(step_id):
    return ExecutionResult(
        step_id=step_id, success=True, message="installed",
        verification_passed=True,
    )


def _exec_failure(step_id):
    return ExecutionResult(
        step_id=step_id, success=False, message="install failed",
        verification_passed=False,
    )


def _workflow_with_executor(executor_result):
    executor = MagicMock()
    executor.execute.return_value = executor_result
    return DevelopmentWorkflow(
        discovery=MagicMock(), validator=MagicMock(), preflight=MagicMock(),
        executor=executor,
    )


# ---------------------------------------------------------------------------
# TC-B-S3.2-S3.3 POSITIVE: persist -> approve -> execute chain
# ---------------------------------------------------------------------------

class TestS32_S33_ProductiveLifecycle:
    """Persist/approve/execute through shared central helpers.

    Coverage: PARTIAL — the authorization GATE is tested for real
    (see test_authorize_setup_plan_targets_creates_registration_on...
    within this class), but the full productive
    lifecycle through execute_approved_plan_from_store proves only the
    plan_store round-trip and council-ref forwarding contract. The
    downstream service.execute_approved_setup_and_development call is
    mocked (adapter-specific Web/MCP gate), which is sufficient for
    the handoff proof but not complete lifecycle evidence."""

    def test_persist_then_approve_then_execute_via_central_helpers(self, tmp_path):
        """The central lifecycle handoff: persist -> approve -> execute.
        Coverage: PARTIAL — proves plan_store round-trip + council
        ref forwarding. The downstream service gate is mocked."""
        plan_store = WorkflowPlanStore(tmp_path / "plans")

        r_pkg = _requirement("req-s32-33-pkg", RequirementType.PYTHON_PACKAGE)
        activation = _activation(r_pkg.id)
        preflight = PreflightResult(
            id="pre-s32-33", project_id="proj-s32-33",
            overall_ready=False,
            results=(
                PreflightRequirementResult(
                    requirement_id=r_pkg.id, present=False, satisfied=False,
                    active=True, blocks_current_operation=True,
                ),
            ),
            missing_requirements=(r_pkg,),
            already_installed=(), warnings=(), activations=(activation,),
            inactive_requirements=(),
            project_requirements=(r_pkg,),
        )
        variant = _variant(toolchain=[
            _toolchain_item(r_pkg.id, type_=RequirementType.PYTHON_PACKAGE),
        ])
        plan = _materialize(variant, preflight, project_id="proj-s32-33")
        assert plan.status == "pending_approval"

        # Step 1: persist (simulating Web/MCP adapter)
        council = CouncilResult(
            id="council-s32-33", project_id="proj-s32-33",
            variants=(variant,), recommendation=variant.id,
            council_complete=True,
        )
        persist_setup_plan(plan_store, plan, council)

        reloaded = plan_store.load("proj-s32-33", plan.id)
        assert reloaded.status == "pending_approval"
        refs = plan_store.load_council_reference("proj-s32-33", plan.id)
        assert refs == ("council-s32-33", variant.id)

        # Step 2: approve through shared central helper
        service = MagicMock()
        service._approved_content_store = MagicMock()
        approved = approve_setup_plan(
            service, plan_store, "proj-s32-33", plan.id, run_id="run-s32-33",
        )
        assert approved.status == "approved"

        # approve_setup_plan records central trace approval event
        service.record_setup_approval_event.assert_called_once()
        call_args = service.record_setup_approval_event.call_args[0]
        assert call_args[0] == "proj-s32-33"
        assert call_args[1] == plan.id
        assert call_args[2] == approved.generation_id
        assert call_args[3] == "run-s32-33"

        # Step 3: execute via central helper
        service.execute_approved_setup_and_development = MagicMock()
        mock_wf = MagicMock()
        mock_wf.execute_approved_and_run_development.return_value = MagicMock(
            status="accepted", final_approval_result=MagicMock(status="pending"),
        )
        service._development_workflow = mock_wf

        execute_approved_plan_from_store(
            service, plan_store, "proj-s32-33", plan.id,
            str(tmp_path / "project"), "Do the task", "run-s32-33",
        )

        # Must have forwarded the council refs
        service.execute_approved_setup_and_development.assert_called_once()
        call = service.execute_approved_setup_and_development.call_args
        assert call.kwargs.get("engineering_council_ref") == "council-s32-33"
        assert call.kwargs.get("chairman_approval_ref") == variant.id

    def test_authorize_setup_plan_targets_creates_registration_on_default_registry(
        self, tmp_path,
    ):
        """When Council/Chairman refs are supplied for an approved plan,
        authorize_setup_plan_targets() creates a CapabilityRegistration
        with complete ApprovalProvenance on an isolated registry."""
        from app.approved_plan_content import ApprovedPlanContentStore

        r_pkg = _requirement("req-s32-auth-pkg", RequirementType.PYTHON_PACKAGE)
        step = SetupStep(
            id="step-s32-auth", requirement_id=r_pkg.id,
            action="install", install_method="pip", package=r_pkg.id,
            setup_effect=SetupEffect.PYTHON_PACKAGE_INSTALL,
            is_approved=True,
            target_executable="/usr/bin/python3",
        )
        plan = SetupPlan(
            id="plan-s32-auth", project_id="proj-s32-auth",
            steps=(step,), status="approved",
            requires_user_approval=True,
            rollback_steps=(), warnings=(),
            created_at=datetime(2025, 1, 1),
        )
        project_root = str(tmp_path / "project")
        Path(project_root).mkdir()

# Real productive chain: record_approved() is called by
        # approve_setup_plan() before any authorization gate runs.
        # authorize_setup_plan_targets() then verifies that the content
        # it is about to authorize is the exact same content that was
        # the subject of a genuine Human Approval event.
        # USING ISOLATED STORE (no CWD side-effect).
        content_store = ApprovedPlanContentStore(tmp_path / "ac.json")
        content_store.record_approved(plan)

        cap_registry = CapabilityRegistry()

        authorize_setup_plan_targets(
            plan, project_root,
            engineering_council_ref="council-s32-auth",
            chairman_approval_ref="variant-s32-auth",
            approved_content_store=content_store,
            capability_registry=cap_registry,
        )

        reg = cap_registry.get("python", project_root)
        assert reg is not None, (
            "authorize_setup_plan_targets must create a "
            "CapabilityRegistration when Council/Chairman refs are supplied"
        )
        assert reg.allowed_operations == ("install", "verification")
        assert reg.status == "active"

        prov = reg.approval_provenance
        assert prov is not None
        assert prov.is_complete() is True, "incomplete provenance: " + str(prov)
        assert prov.engineering_council_ref == "council-s32-auth"
        assert prov.chairman_approval_ref == "variant-s32-auth"
        assert "setup-approval:plan-s32-auth" in prov.human_approval_ref


# ---------------------------------------------------------------------------
# TC-B-S3.2-S3.3 NEGATIVE: direct approve + execute rejected
# ---------------------------------------------------------------------------

class TestS32_S33_DirectApproveAndExecuteIsRejected:
    """A caller that approves a plan directly and then attempts confined
    mutating execution without going through authorize_setup_plan_targets
    encounters the capability authorization gate."""

    def test_direct_approve_plus_confined_execute_rejected_no_store(self, tmp_path):
        """Confined execution with no execution_state_store rejected."""
        r_pkg = _requirement("req-dir-pkg", RequirementType.PYTHON_PACKAGE)
        activation = _activation(r_pkg.id)
        preflight = PreflightResult(
            id="pre-dir", project_id="proj-dir",
            overall_ready=False,
            results=(
                PreflightRequirementResult(
                    requirement_id=r_pkg.id, present=False, satisfied=False,
                    active=True, blocks_current_operation=True,
                ),
            ),
            missing_requirements=(r_pkg,),
            already_installed=(), warnings=(), activations=(activation,),
            inactive_requirements=(),
            project_requirements=(r_pkg,),
        )
        variant = _variant(toolchain=[
            _toolchain_item(r_pkg.id, type_=RequirementType.PYTHON_PACKAGE),
        ])
        plan = _materialize(variant, preflight, project_id="proj-dir")
        approved = SetupApproval.approve(plan)
        assert approved.status == "approved"

        workflow = _workflow_with_executor(_exec_success("step-" + r_pkg.id))
        project_root = str(tmp_path / "project")
        Path(project_root).mkdir()

        # Confined execution rejected -- no execution_state_store
        with pytest.raises(WorkflowExecutionError, match="execution_state_store"):
            workflow.execute_approved(approved, project_root)

    def test_bootstrap_only_python_install_rejected_at_boundary(self, tmp_path):
        """Mutating install with only a bootstrap capability
        (no ApprovalProvenance) is rejected.  B1 invariant."""
        from app.execution import _bootstrap

        project_root = tmp_path / "project"
        project_root.mkdir()

        bootstrap_registry = CapabilityRegistry()
        bootstrap_registry._register_bootstrap(_bootstrap(
            "python", ("python3", "python"), ("verification", "test", "install"),
        ))

        request = ExecutionRequest(
            ("python3", "-m", "pip", "install", "whatever"),
            str(project_root), 10, "python", "install",
        )
        violation = validate_request(request, project_root, bootstrap_registry)
        assert violation is not None
        assert "approval-provenance" in violation.diagnostics


# ---------------------------------------------------------------------------
# TC-B-S5-S6: Final Approval gate
# ---------------------------------------------------------------------------

class TestS5_S6_FinalApprovalGate:
    """Only "accepted" status may reach Final Approval pending."""

    def test_accepted_creates_final_approval_pending(self, tmp_path):
        manager = WorkflowManager(tmp_path / "state.json")
        approval = manager.create_final_approval("run-s5-s6", "accepted")
        assert approval.status == "pending"
        assert approval.applicable is True
        assert approval.ready_for_git is False

    def test_non_accepted_status_block_final_approval(self, tmp_path):
        manager = WorkflowManager(tmp_path / "state.json")
        for status in ("apply_failed", "rework_required",
                         "review_failed", "tool_unavailable"):
            with pytest.raises(FinalApprovalError, match="accepted"):
                manager.create_final_approval("run-nonacc-" + status, status)

    def test_final_approval_chain_persists_state(self, tmp_path):
        manager = WorkflowManager(tmp_path / "state.json")
        manager.create_final_approval("run-chain", "accepted")
        approved = manager.decide_final_approval(
            "run-chain", "approved", approved_by="tester",
        )
        assert approved.status == "approved"
        assert approved.ready_for_git is True

        state = manager.load()
        record = state.get("final_approvals", {}).get("run-chain")
        assert record is not None
        assert record["status"] == "approved"
        assert record["approved_by"] == "tester"
        assert record["development_status"] == "accepted"


# ---------------------------------------------------------------------------
# TC-B-S5-S6 PRODUCTIVE: real S5 result -> real service handoff -> real S6
# ---------------------------------------------------------------------------

class _S4S5LlmProvider:
    """The one external LLM provider boundary (canonical_composition's
    create_llm_provider). Every S4/S5 role reaches it only through the
    real ProviderAgentExecutor prompts; nothing internal is replaced."""

    def __init__(self, implementation):
        self.implementation = implementation
        self.roles = []
        self._proposed = set()

    def _change(self, file, content):
        action = "update" if file in self._proposed else "create"
        self._proposed.add(file)
        return {"file": file, "action": action, "content": content}

    def complete(self, prompt, **_options):
        if "You are the Diagnosis Reviewer of AI-Dev-Center" in prompt:
            self.roles.append("reviewer")
            return json.dumps({"decision": "accepted", "summary": "verification evidence reviewed"})
        if "You are the Tester of AI-Dev-Center" in prompt:
            self.roles.append("tester")
            return json.dumps({"changes": [self._change(
                "tests/test_feature.py",
                "from feature import answer\n\n\ndef test_answer():\n    assert answer() == 42\n",
            )], "tests": ["pytest"]})
        if "Internal role: developer" in prompt:
            self.roles.append("developer")
            return json.dumps({"changes": [self._change(
                "feature.py", f"def answer():\n    return {self.implementation}\n",
            )], "tests": []})
        raise AssertionError("unexpected LLM prompt at the S4/S5 boundary")


class TestS5_S6_ProductiveComposition:
    """GATE2_S5_S6: real S5 output consumed productively by S6.

    Entry point is the production owner of the S5->S6 transition,
    ProjectSetupApplicationService.execute_approved_setup_and_development()
    from the canonical composition root. The S5 producer (DevelopmentWorkflow
    -> ControlledReworkStage -> DevelopmentTestingStage with the real
    ProjectInspector, default verification registry and ProjectTestRunner)
    produces the SetupDevelopmentTestingResult; the service itself hands
    its status to the real S6 consumer (WorkflowManager.
    complete_development_execution -> Final Approval). Only the external
    LLM provider factories are substituted. The zero-step SetupPlan is an
    upstream S3 input approved through the real SetupApproval, not the
    S5->S6 artifact under test.
    """

    def _compose(self, tmp_path, monkeypatch, implementation, provider=None):
        from pathlib import Path as _Path
        import shutil
        from app.canonical_composition import build_canonical_components

        owned_root = tmp_path / "owned"
        project = owned_root / "project"
        project.mkdir(parents=True)
        (project / "pyproject.toml").write_text(
            "[project]\nname = \"s5-s6-productive\"\nversion = \"0.1.0\"\n\n"
            "[tool.pytest.ini_options]\npythonpath = [\".\"]\n",
            encoding="utf-8",
        )
        (project / "tests").mkdir()
        config_dir = owned_root / "config"
        config_dir.mkdir()
        config_path = config_dir / "ai-dev-center.yml"
        shutil.copy2(_Path(__file__).parents[1] / "config" / "ai-dev-center.yml", config_path)
        monkeypatch.chdir(owned_root)
        provider = provider or _S4S5LlmProvider(implementation)
        monkeypatch.setattr("app.canonical_composition.create_llm_provider", lambda *_a, **_k: provider)
        monkeypatch.setattr(
            "app.engineering_council.create_council_provider",
            lambda *_a, **_k: pytest.fail("S2 Council must not be reached from S5->S6"),
        )
        components = build_canonical_components(str(config_path))
        plan = components.approval.approve(
            SetupPlan(
                id="plan-s5-s6", project_id="s5-s6-project",
                environment_target_executable=sys.executable,
            ),
        )
        return components, project, provider, plan

    def test_accepted_real_s5_result_opens_real_s6_final_approval(self, tmp_path, monkeypatch):
        components, project, provider, plan = self._compose(tmp_path, monkeypatch, 42)
        service = components.service

        result = service.execute_approved_setup_and_development(
            plan, "s5-s6-project", project, "Add answer()", "run-s5-s6",
        )

        # Real S5 producer created the artifact from real verification.
        s5 = result.development_testing_result
        assert provider.roles == ["developer", "tester", "reviewer"]
        assert result.controlled_rework_result.rework_executed is False
        assert s5.test_result.passed is True
        assert s5.testing_stage_result.status == "accepted"
        assert result.status == "accepted"
        assert (project / "feature.py").is_file()
        # The service carried that exact S5 status into the real S6 owner.
        approval = result.final_approval_result
        assert approval.status == "pending"
        assert approval.applicable is True
        assert approval.ready_for_git is False
        state = WorkflowManager().load()
        assert state["final_approvals"]["run-s5-s6"]["development_status"] == result.status
        # S6 continues only through the explicit human transition.
        decided = service.decide_final_approval("run-s5-s6", "approved", approved_by="human")
        assert decided.status == "approved"
        assert decided.ready_for_git is True
        phases = [(e.phase, e.status) for e in service.get_diagnostic_trace("run-s5-s6")]
        assert ("final_approval", "pending") in phases
        assert ("final_approval", "approved") in phases

    def test_real_deterministic_s5_failure_never_reaches_s6(self, tmp_path, monkeypatch):
        components, project, provider, plan = self._compose(tmp_path, monkeypatch, 41)
        service = components.service

        result = service.execute_approved_setup_and_development(
            plan, "s5-s6-project", project, "Add answer()", "run-s5-s6-fail",
        )

        # Real failing verification forces S5.6 rework despite an accepting
        # reviewer; the single bounded rework fails the same way.
        assert result.controlled_rework_result.rework_executed is True
        assert provider.roles == ["developer", "tester", "reviewer"] * 2
        assert result.controlled_rework_result.initial_result.test_result.passed is False
        assert result.development_testing_result.test_result.passed is False
        assert result.status == "rework_required"
        assert result.final_approval_result.status == "not_applicable"
        assert result.final_approval_result.applicable is False
        assert "run-s5-s6-fail" not in WorkflowManager().load()["final_approvals"]
        with pytest.raises(FinalApprovalError):
            service.decide_final_approval("run-s5-s6-fail", "approved", approved_by="human")


# ---------------------------------------------------------------------------
# TC-B-S3-S4: Setup obligations gate
# ---------------------------------------------------------------------------

class TestS3_S4_SetupObligationsGate:
    """Setup failures block S4; completed obligations permit S4."""

    def test_setup_failure_blocks_s4_development(self):
        r_pkg = _requirement("req-s3-s4-fail", RequirementType.PYTHON_PACKAGE)
        activation = _activation(r_pkg.id)
        preflight = PreflightResult(
            id="pre-s3-s4-fail", project_id="proj-s3-s4-fail",
            overall_ready=False,
            results=(
                PreflightRequirementResult(
                    requirement_id=r_pkg.id, present=False, satisfied=False,
                    active=True, blocks_current_operation=True,
                ),
            ),
            missing_requirements=(r_pkg,),
            already_installed=(), warnings=(), activations=(activation,),
            inactive_requirements=(),
            project_requirements=(r_pkg,),
        )
        variant = _variant(toolchain=[
            _toolchain_item(r_pkg.id, type_=RequirementType.PYTHON_PACKAGE),
        ])
        plan = _materialize(variant, preflight, project_id="proj-s3-s4-fail")
        approved = SetupApproval.approve(plan)

        development_request = MagicMock(
            project_id="proj-s3-s4-fail",
            project_path="/tmp/path", task="Do it",
            run_id="run-s3-s4-fail",
        )
        fail_executor = MagicMock()
        fail_executor.execute.return_value = _exec_failure("step-s3-s4-fail")
        workflow = DevelopmentWorkflow(
            discovery=MagicMock(), validator=MagicMock(), preflight=MagicMock(),
            executor=fail_executor,
        )

        # execute_approved returns the failure result; the caller
        # (execute_approved_and_run_development) checks all results
        # and raises WorkflowExecutionError before S4 ever starts.
        results = workflow.execute_approved(approved)
        assert len(results) == 1
        assert results[0].success is False
        assert "install failed" in results[0].message

    def test_plan_not_approved_blocks(self):
        r_pkg = _requirement("req-unapp", RequirementType.PYTHON_PACKAGE)
        activation = _activation(r_pkg.id)
        preflight = PreflightResult(
            id="pre-unapp", project_id="proj-unapp",
            overall_ready=False,
            results=(
                PreflightRequirementResult(
                    requirement_id=r_pkg.id, present=False, satisfied=False,
                    active=True, blocks_current_operation=True,
                ),
            ),
            missing_requirements=(r_pkg,),
            already_installed=(), warnings=(), activations=(activation,),
            inactive_requirements=(),
            project_requirements=(r_pkg,),
        )
        variant = _variant(toolchain=[
            _toolchain_item(r_pkg.id, type_=RequirementType.PYTHON_PACKAGE),
        ])
        plan = _materialize(variant, preflight, project_id="proj-unapp")
        assert plan.status == "pending_approval"

        workflow = _workflow_with_executor(_exec_success("never"))
        with pytest.raises(WorkflowExecutionError, match="not approved"):
            workflow.execute_approved(plan)


# ---------------------------------------------------------------------------
# TC-B-BYPASS: Negative boundary-bypass suite for critical shortcuts
# ---------------------------------------------------------------------------

class TestBoundaryBypassNegative:
    """Prove that dangerous shortcuts are rejected by current architecture."""

    def test_s32_bypass_unapproved_plan_rejected(self):
        r_pkg = _requirement("req-bpass-s32", RequirementType.PYTHON_PACKAGE)
        activation = _activation(r_pkg.id)
        preflight = PreflightResult(
            id="pre-bpass-s32", project_id="proj-bpass-s32",
            overall_ready=False,
            results=(
                PreflightRequirementResult(
                    requirement_id=r_pkg.id, present=False, satisfied=False,
                    active=True, blocks_current_operation=True,
                ),
            ),
            missing_requirements=(r_pkg,),
            already_installed=(), warnings=(), activations=(activation,),
            inactive_requirements=(),
            project_requirements=(r_pkg,),
        )
        variant = _variant(toolchain=[
            _toolchain_item(r_pkg.id, type_=RequirementType.PYTHON_PACKAGE),
        ])
        plan = _materialize(variant, preflight, project_id="proj-bpass-s32")
        workflow = _workflow_with_executor(_exec_success("never"))
        with pytest.raises(WorkflowExecutionError, match="not approved"):
            workflow.execute_approved(plan)

    def test_s5_failed_no_s6(self, tmp_path):
        manager = WorkflowManager(tmp_path / "state.json")
        with pytest.raises(FinalApprovalError):
            manager.create_final_approval("run-fail", "apply_failed")

    def test_s5_rework_no_s6(self, tmp_path):
        manager = WorkflowManager(tmp_path / "state.json")
        with pytest.raises(FinalApprovalError):
            manager.create_final_approval("run-rwk", "rework_required")

    def test_approved_plan_content_immutability(self, tmp_path):
        """A plan whose execution-relevant content changed under the
        same generation must be blocked by the execution-state guard."""
        step = SetupStep(
            id="step-mut", requirement_id="req-mut",
            action="install", install_method="pip", package="pkg",
            setup_effect=SetupEffect.PYTHON_PACKAGE_INSTALL,
            is_approved=True,
        )
        identity = SetupStepIdentity.for_step("/proj", "gen-1", step)
        store = SetupExecutionStateStore(tmp_path / "state.json")

        store.claim_or_report(identity, "owner-1")
        store.finish(identity, "owner-1", "succeeded", {
            "success": True, "message": "done",
            "verification_passed": True,
        })

        modified = replace(step, package="different-pkg")
        mod_identity = SetupStepIdentity.for_step("/proj", "gen-1", modified)

        with pytest.raises(SetupExecutionStateError, match="different"):
            store.claim_or_report(mod_identity, "owner-2")


# ---------------------------------------------------------------------------
# TC-B-S1-S2: Requirement-to-Council continuity
# ---------------------------------------------------------------------------

class TestS1_S2_RequirementToCuncilContinuity:
    """Requirement artifacts survive through Preflight into Cuncillnput."""

    def test_requirement_ids_preserved_across_boundary(self):
        r_a = _requirement("req-s1-s2-a")
        r_b = _requirement("req-s1-s2-b")
        activation_a = _activation(r_a.id)
        activation_b = _activation(r_b.id)

        requirements = (r_a, r_b)
        activations = (activation_a, activation_b)

        preflight = PreflightResult(
            id="pre-s1-s2", project_id="proj-s1-s2",
            overall_ready=False,
            results=(
                PreflightRequirementResult(
                    requirement_id=r_a.id, present=False, satisfied=False,
                    active=True, blocks_current_operation=True,
                ),
                PreflightRequirementResult(
                    requirement_id=r_b.id, present=True, satisfied=True,
                    active=True, blocks_current_operation=True,
                ),
            ),
            missing_requirements=(r_a,),
            already_installed=(r_b,),
            warnings=(), activations=activations,
            inactive_requirements=(),
            project_requirements=requirements,
        )

        council_input = CouncilInput(
            requirements=requirements,
            preflight=preflight,
            project_id="proj-s1-s2",
            project_files=(),
            detected_stack="",
            project_intelligence=None,
            validation_warnings=(),
            requirement_activations=activations,
        )

        # Key invariants: no requirement id is lost or renamed
        input_ids = {r.id for r in council_input.requirements}
        assert r_a.id in input_ids
        assert r_b.id in input_ids
        assert len(input_ids) == 2

        missing_ids = {r.id for r in preflight.missing_requirements}
        assert r_a.id in missing_ids
        assert r_b.id not in missing_ids

        installed_ids = {r.id for r in preflight.already_installed}
        assert r_b.id in installed_ids


# =========================================================================
# DEF-RSE033-ESPHOME-COMPILE-TIMEOUT: productive S5 verification timeout
# =========================================================================

# The external work reports progress that is not valid UTF-8 straight to
# the controlled process's output pipes (FIX-002): malformed output must
# not change the timeout outcome or its routing.
_SLOW_VERIFICATION_TEST = '''\
import os, subprocess, sys, time

from feature import answer


def test_answer_after_long_external_work(capsys):
    child = subprocess.Popen([sys.executable, "-c",
        "import signal, time\\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\\ntime.sleep(120)"])
    with open({pid_file!r}, "w") as fh:
        fh.write(str(child.pid))
    with capsys.disabled():
        os.write(1, b"\\nexternal progress \\xff\\xfe\\n")
        os.write(2, b"external warning \\xc3\\x28\\n")
    time.sleep(120)
    assert answer() == 42
'''


def _process_alive(pid):
    # ENOENT/ESRCH while reading /proc: the process has exited; zombie (Z)
    # and dead (X) states have run to completion.
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except (OSError, IndexError):
        return False
    return state not in ("Z", "X")


class _TimeoutLlmProvider(_S4S5LlmProvider):
    """Same single external LLM boundary; the Tester proposes a test whose
    real external work outlives the policy budget, and the Diagnosis
    Reviewer returns the scripted decisions."""

    def __init__(self, pid_file, *review_decisions):
        super().__init__(42)
        self._pid_file = str(pid_file)
        self._decisions = list(review_decisions)

    def complete(self, prompt, **options):
        import json
        if "You are the Diagnosis Reviewer of AI-Dev-Center" in prompt:
            self.roles.append("reviewer")
            return json.dumps({"decision": self._decisions.pop(0), "summary": "timeout diagnosis"})
        if "You are the Tester of AI-Dev-Center" in prompt:
            self.roles.append("tester")
            return json.dumps({"changes": [self._change(
                "tests/test_feature.py", _SLOW_VERIFICATION_TEST.format(pid_file=self._pid_file),
            )], "tests": ["pytest"]})
        return super().complete(prompt, **options)


@pytest.mark.skipif(sys.platform != "linux", reason="observes descendants through /proc")
class TestS5_VerificationTimeoutProductiveComposition:
    """GATE2_S5_1_TO_S5_7 / GATE2_S5_S4_BOUNDED_REWORK /
    GATE2_FAULT_PERMUTATIONS: a real verification timeout through the
    canonical composition root.

    Real: ProjectSetupApplicationService -> DevelopmentWorkflow ->
    ControlledReworkStage -> DevelopmentTestingStage -> ProjectInspector ->
    build_verification_plan (reads the central budget policy) ->
    default registry -> PytestRunner -> ExecutionRequest ->
    execute_controlled -> real pytest subprocess tree -> real timeout ->
    TestingStage/DiagnosisReviewer -> Final Approval. Substituted: only the
    external LLM provider, and the central policy's "test" budget value is
    set to a test-sized 4 seconds (the policy itself, not a component) --
    enough for the real pytest subprocess to start and reach the test's
    external work before the budget expires."""

    _BUDGET = 4

    def _run(self, tmp_path, monkeypatch, *decisions):
        from app.verification import VERIFICATION_EXECUTION_BUDGET_SECONDS

        monkeypatch.setitem(VERIFICATION_EXECUTION_BUDGET_SECONDS, "test", self._BUDGET)
        pid_file = tmp_path / "descendant.pid"
        provider = _TimeoutLlmProvider(pid_file, *decisions)
        components, project, _provider, plan = TestS5_S6_ProductiveComposition()._compose(
            tmp_path, monkeypatch, 42, provider=provider,
        )
        assert _provider is provider
        result = components.service.execute_approved_setup_and_development(
            plan, "s5-s6-project", project, "Add answer()", "run-s5-timeout",
        )
        return components, result, provider, pid_file

    def _assert_real_timeout(self, cycle_result, pid_file):
        from app.execution import TIMEOUT_RETURN_CODE
        from app.verification import TIMEOUT, VERIFICATION_EXECUTION_BUDGET_SECONDS

        verification = cycle_result.verification_result
        (step,) = [s for s in verification.steps if s.runner_type == "pytest"]
        assert step.status == TIMEOUT.value and step.timed_out and not step.passed
        assert step.return_code == TIMEOUT_RETURN_CODE
        assert isinstance(step.stdout, str) and isinstance(step.stderr, str)
        assert pid_file.exists(), "the verification timed out before reaching the external work"
        assert "external progress \ufffd\ufffd" in step.stdout
        assert "external warning \ufffd(" in step.stderr
        assert cycle_result.failure_stage != "tool_unavailable"
        assert cycle_result.test_result.timed_out is True
        assert cycle_result.test_result.passed is False
        assert VERIFICATION_EXECUTION_BUDGET_SECONDS["test"] == self._BUDGET
        descendant = int(pid_file.read_text())
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and _process_alive(descendant):
            time.sleep(0.05)
        assert not _process_alive(descendant), "timed-out verification left a descendant alive"

    def test_real_timeout_without_source_diagnosis_is_fail_closed_without_rework(self, tmp_path, monkeypatch):
        components, result, provider, pid_file = self._run(tmp_path, monkeypatch, "accepted")

        assert provider.roles == ["developer", "tester", "reviewer"]
        assert result.controlled_rework_result.rework_executed is False
        self._assert_real_timeout(result.development_testing_result, pid_file)
        assert result.status == "verification_timeout"
        # fail-closed: no S6 acceptance, no S3 recovery
        assert result.final_approval_result.applicable is False
        assert result.missing_toolchain_recovery is None
        phases = [(e.phase, e.status) for e in components.service.get_diagnostic_trace("run-s5-timeout")]
        assert ("testing", "timeout") in phases
        assert ("diagnosis_review", "timeout") in phases
        assert ("controlled_rework", "started") not in phases

    def test_diagnosed_source_correctable_timeout_uses_exactly_one_bounded_rework(self, tmp_path, monkeypatch):
        components, result, provider, pid_file = self._run(
            tmp_path, monkeypatch, "rework_required", "rework_required",
        )

        assert provider.roles == ["developer", "tester", "reviewer"] * 2
        assert result.controlled_rework_result.rework_executed is True
        assert "source-correctable" in result.controlled_rework_result.rework_request.reason
        self._assert_real_timeout(result.controlled_rework_result.initial_result, pid_file)
        self._assert_real_timeout(result.development_testing_result, pid_file)
        assert result.status == "rework_required"
        assert result.final_approval_result.applicable is False
        assert result.missing_toolchain_recovery is None


# =========================================================================
# DEF-RSE033-ESPHOME-COMPILE-TIMEOUT / EXECUTION_ERROR_CLASSIFICATION:
# productive S5 verification execution error
# =========================================================================

class _ExecutionErrorLlmProvider(_TimeoutLlmProvider):
    """The Tester proposes a test whose real external work keeps running
    (with a SIGTERM-resistant descendant); the Diagnosis Reviewer returns
    the scripted decisions."""


@pytest.mark.skipif(sys.platform != "linux", reason="observes descendants through /proc")
class TestS5_VerificationExecutionErrorProductiveComposition:
    """GATE2_S5_1_TO_S5_7 / GATE2_S5_S4_BOUNDED_REWORK /
    GATE2_S5_S3_BOUNDED_RECOVERY / GATE2_FAULT_PERMUTATIONS: a controlled
    verification process that really started and then failed at ADC's own
    execution boundary, through the canonical composition root.

    Real: ProjectSetupApplicationService -> DevelopmentWorkflow ->
    ControlledReworkStage -> DevelopmentTestingStage -> ProjectInspector ->
    build_verification_plan (central budget policy) -> default registry ->
    PytestRunner -> ExecutionRequest -> execute_controlled -> real running
    pytest subprocess tree -> real OSError from subprocess.Popen.communicate
    (the stdlib fault is the only injection) -> process-tree containment ->
    EXECUTION_ERROR -> TestingStage/DiagnosisReviewer -> Final Approval.
    Substituted: only the external LLM provider."""

    def _run(self, tmp_path, monkeypatch, *decisions):
        import errno
        import subprocess

        pid_file = tmp_path / "descendant.pid"
        provider = _ExecutionErrorLlmProvider(pid_file, *decisions)
        components, project, _provider, plan = TestS5_S6_ProductiveComposition()._compose(
            tmp_path, monkeypatch, 42, provider=provider,
        )
        real_communicate = subprocess.Popen.communicate
        started = []

        def communicate(process, *args, **kwargs):
            argv = process.args if isinstance(process.args, (list, tuple)) else []
            if "pytest" in argv and "-m" in argv and not started:
                started.append(process.pid)
                deadline = time.monotonic() + 30
                while not pid_file.exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                raise OSError(errno.EPIPE, "Broken pipe while talking to the verification process")
            return real_communicate(process, *args, **kwargs)

        monkeypatch.setattr(subprocess.Popen, "communicate", communicate)
        result = components.service.execute_approved_setup_and_development(
            plan, "s5-s6-project", project, "Add answer()", "run-s5-execution-error",
        )
        return components, result, provider, pid_file, started

    def test_real_execution_error_is_fail_closed_terminal_without_rework_or_recovery(self, tmp_path, monkeypatch):
        from app.execution import ControlledExecutionError
        from app.verification import EXECUTION_ERROR, TOOL_UNAVAILABLE

        # the diagnosis even asks for rework: it has no authority to get it
        components, result, provider, pid_file, started = self._run(tmp_path, monkeypatch, "rework_required")

        cycle = result.development_testing_result
        (step,) = [s for s in cycle.verification_result.steps if s.runner_type == "pytest"]
        assert started, "the verification process never started"
        assert step.status == EXECUTION_ERROR.value and step.status != TOOL_UNAVAILABLE.value
        assert step.error_category == ControlledExecutionError.__name__
        assert step.unavailable_tool is None and step.timed_out is False and not step.passed
        assert cycle.failure_stage != "tool_unavailable"
        assert cycle.test_result.passed is False
        assert cycle.testing_stage_result.status == "verification_execution_error"
        # S5 -> S4: the single bounded rework is not consumed
        assert provider.roles == ["developer", "tester", "reviewer"]
        assert result.controlled_rework_result.rework_executed is False
        # fail-closed terminal outcome: no S6 acceptance, no S5 -> S3 recovery
        assert result.status == "verification_execution_error"
        assert result.final_approval_result.applicable is False
        assert result.missing_toolchain_recovery is None
        phases = [(e.phase, e.status) for e in components.service.get_diagnostic_trace("run-s5-execution-error")]
        assert ("diagnosis_review", "execution_error") in phases
        assert ("controlled_rework", "started") not in phases
        # the whole started tree was contained before the error surfaced
        descendant = int(pid_file.read_text())
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and (_process_alive(descendant) or _process_alive(started[0])):
            time.sleep(0.05)
        assert not _process_alive(started[0]) and not _process_alive(descendant)
