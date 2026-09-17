"""CLAUDE-E2E-003I Part 3-8/14/18: setup-generation semantics.

Proves the core scenario the task requires: a SetupStep that already
SUCCEEDED under one setup generation (Generation A) is not permanently
blocked from ever executing again in the same project -- a genuinely
new setup generation (Generation B, e.g. after a later Environment
Soll/Ist evaluation detects the tool is missing again) can be approved
and executed once more, without Generation A's SUCCEEDED state or
approval ever being reused, and without a client ever supplying the
generation identity itself.
"""
from __future__ import annotations

import os

import pytest

from app.approved_plan_content import ApprovedPlanContentStore
from app.council_models import CouncilResult, CouncilVariant, ToolchainItem
from app.dev_workflow import DevelopmentWorkflow
from app.execution import (
    ApprovalProvenance, CapabilityRegistration, CapabilityRegistry, DEFAULT_CAPABILITY_REGISTRY,
)
from app.project_setup_application import authorize_setup_plan_targets
from app.python_package_executor import PythonPackageExecutor
from app.requirement_model import Requirement, RequirementType
from app.requirement_preflight import RequirementPreflight
from app.setup_approval import SetupApproval
from app.setup_execution_state import SetupExecutionStateStore, SetupStepIdentity
from app.toolchain_materializer import ToolchainMaterializer
from app.workflow_plan_store import WorkflowPlanStore, WorkflowPlanStoreError

from tests.local_package_fixture import (
    PACKAGE_NAME, build_launch_counting_target, build_local_wheel_index, read_launch_count,
)


def _requirement(req_id="req-gen"):
    return Requirement(
        technical_identity=PACKAGE_NAME,
        id=req_id, name=PACKAGE_NAME, type=RequirementType.PYTHON_PACKAGE,
        purpose="test dependency", required=True, confidence=0.9,
    )


def _council_result(requirement_id, project_id, council_id):
    item = ToolchainItem(
        requirement_ref=requirement_id, name=PACKAGE_NAME,
        type=RequirementType.PYTHON_PACKAGE, install_method=f"pip install {PACKAGE_NAME}",
    )
    variant = CouncilVariant(id="variant-1", name="variant-1", toolchain=(item,))
    return CouncilResult(
        id=council_id, project_id=project_id,
        variants=(variant,), recommendation="variant-1", council_complete=True,
    )


def _materialize_and_approve(project_id, project_root, requirement, council_id):
    preflight = RequirementPreflight.check((requirement,), project_id, project_root=str(project_root))
    council = _council_result(requirement.id, project_id, council_id)
    plan = ToolchainMaterializer().materialize(council, project_id, preflight=preflight)
    approved = SetupApproval.approve(plan)
    return approved, council


class TestEnvironmentRepairScenario:
    """Part 14/18 #2: Generation A succeeds; the tool is later
    considered missing again (a new Environment Soll/Ist evaluation);
    Generation B is materialized, newly approved, and may execute
    exactly once -- Generation A's SUCCEEDED state does not block it,
    and Generation A's approval/provenance is never reused."""

    def test_generation_b_executes_after_generation_a_succeeded(self, tmp_path, monkeypatch):
        wheels = build_local_wheel_index(tmp_path)
        target, counter = build_launch_counting_target(tmp_path, "toolchain-a", wheels)
        monkeypatch.setenv("PATH", f"{os.path.dirname(target)}:{os.environ.get('PATH', '')}")
        project_root = tmp_path / "project"
        project_root.mkdir()
        project_id = "proj-repair"
        requirement = _requirement("req-repair")
        # CLAUDE-ADC-ZIELBILD-DIFF-FIX-001 (B1): workflow.execute_approved()
        # below routes through PythonPackageExecutor's default runner,
        # which always consults DEFAULT_CAPABILITY_REGISTRY (never an
        # injected registry) -- authorization must be registered there.
        registry = DEFAULT_CAPABILITY_REGISTRY
        store = SetupExecutionStateStore(tmp_path / "exec-state.json")
        content_store = ApprovedPlanContentStore(tmp_path / "approved-content.json")
        workflow = DevelopmentWorkflow(
            discovery=None, validator=None, preflight=None,
            executor=PythonPackageExecutor(), execution_state_store=store,
        )
        plan_store = WorkflowPlanStore(tmp_path / "plans")

        # --- Generation A: real Preflight/Materializer/Approval, authorized, executed ---
        approved_a, council_a = _materialize_and_approve(project_id, project_root, requirement, "council-a")
        # CLAUDE-E2E-003I-B: record_approved() is what approve_setup_plan()
        # itself calls at the real Human Approval moment -- simulated
        # explicitly here since this test builds approval directly via
        # SetupApproval.approve() rather than through that shared function.
        content_store.record_approved(approved_a)
        authorize_setup_plan_targets(
            approved_a, project_root,
            engineering_council_ref=council_a.id, chairman_approval_ref=council_a.recommendation,
            capability_registry=registry, approved_content_store=content_store,
        )
        result_a = workflow.execute_approved(approved_a, str(project_root))
        assert result_a[0].success is True
        count_after_a = read_launch_count(counter)
        assert count_after_a > 0

        # --- Retry of the SAME Generation A must not relaunch ---
        workflow.execute_approved(approved_a, str(project_root))
        assert read_launch_count(counter) == count_after_a

        # --- Environment regression: the tool is genuinely removed
        # externally (a deleted venv, a corrupted SDK, ...) -- a real
        # uninstall against the SAME real target, not a fabrication ---
        import subprocess
        uninstall = subprocess.run(
            [target, "-m", "pip", "uninstall", "-y", PACKAGE_NAME],
            capture_output=True, text=True, timeout=30,
        )
        assert uninstall.returncode == 0, uninstall.stderr

        # --- A new Environment Soll/Ist evaluation now genuinely finds
        # the tool missing again -> real Preflight/Materializer produce
        # a real new install step -> Generation B ---
        approved_b, council_b = _materialize_and_approve(project_id, project_root, requirement, "council-b")
        assert len(approved_b.steps) == 1, "Preflight must genuinely find the tool missing again"
        assert approved_b.id == approved_a.id, "plan.id is stable per project"
        assert approved_b.generation_id != approved_a.generation_id, (
            "a genuinely new materialization must get a new generation"
        )

        # --- Generation A's SUCCEEDED state must not block Generation B ---
        identity_b = SetupStepIdentity.for_step(str(project_root), approved_b.generation_id, approved_b.steps[0])
        assert store.get(identity_b) is None, "Generation B must start with no inherited state"

        # --- Generation B requires and receives its OWN, fresh authorization ---
        content_store.record_approved(approved_b)
        authorize_setup_plan_targets(
            approved_b, project_root,
            engineering_council_ref=council_b.id, chairman_approval_ref=council_b.recommendation,
            capability_registry=registry, approved_content_store=content_store,
        )
        current_registration = registry.get("python", project_root)
        assert current_registration.approval_provenance.engineering_council_ref == "council-b"
        assert current_registration.approval_provenance.human_approval_ref != (
            f"setup-approval:{approved_a.id}:{approved_a.generation_id}:approved"
        )

        # --- Generation B executes exactly once (a genuine new mutation) ---
        result_b = workflow.execute_approved(approved_b, str(project_root))

        assert result_b[0].success is True
        assert read_launch_count(counter) > count_after_a, (
            "Generation B must actually execute -- a new, legitimate "
            "attempt, not silently blocked by Generation A's SUCCEEDED state"
        )


class TestOldGenerationApprovalCannotAuthorizeNewGeneration:
    """Part 6/19: even if a caller (hypothetically, due to a bug)
    supplied Generation A's OLD human_approval_ref for Generation B's
    authorization, CapabilityRegistry's own supersede path still
    requires a COMPLETE, matching-project provenance -- but the
    structural protection this task relies on is that
    WorkflowPlanStore.load_council_reference() and
    record_setup_approval_event() are ALWAYS re-sourced fresh per
    generation by the real adapter-shared functions, so a stale
    reference is never naturally reachable. This test proves the
    structural sourcing directly: persisting Generation B's own council
    reference overwrites -- never merges with -- Generation A's."""

    def test_persisted_council_reference_reflects_only_the_current_generation(self, tmp_path):
        from app.project_setup_application import persist_setup_plan

        plan_store = WorkflowPlanStore(tmp_path / "plans")
        project_id = "proj-refresh"
        requirement = _requirement("req-refresh")
        project_root = tmp_path / "project"
        project_root.mkdir()

        preflight = RequirementPreflight.check((requirement,), project_id, project_root=None)
        council_a = _council_result(requirement.id, project_id, "council-a")
        plan_a = ToolchainMaterializer().materialize(council_a, project_id, preflight=preflight)
        persist_setup_plan(plan_store, plan_a, council_a)
        assert plan_store.load_council_reference(project_id, plan_a.id) == ("council-a", "variant-1")

        council_b = _council_result(requirement.id, project_id, "council-b")
        plan_b = ToolchainMaterializer().materialize(council_b, project_id, preflight=preflight)
        assert plan_b.generation_id != plan_a.generation_id
        persist_setup_plan(plan_store, plan_b, council_b)

        # The SAME (project_id, plan.id)-keyed marker now reflects ONLY
        # Generation B -- Generation A's reference is gone, never
        # reachable as a "stale but still loadable" value.
        assert plan_store.load_council_reference(project_id, plan_b.id) == ("council-b", "variant-1")


class TestLegacyPlanGenerationCompatibility:
    """Part 8: a SetupPlan persisted before generation_id existed
    (003E-003H) has no such key in its JSON at all. Loading it must be
    restart-safe and deterministic (the same legacy plan always
    resolves to the same generation identity), must never be
    client-controlled, must never merge with an unrelated plan, and
    must never let a pre-003I SUCCEEDED record apply to a genuinely new
    future generation. A present-but-malformed value is corrupt, not
    legacy, and fails closed."""

    def test_legacy_plan_without_generation_id_gets_a_deterministic_restart_stable_identity(self, tmp_path):
        import json

        store = WorkflowPlanStore(tmp_path / "plans")
        directory = tmp_path / "plans" / "proj-legacy"
        directory.mkdir(parents=True)
        legacy_payload = {
            "id": "plan-proj-legacy", "project_id": "proj-legacy",
            "steps": [], "requires_user_approval": True,
            "status": "approved",
            # no "generation_id" key at all -- the exact pre-003I shape
        }
        (directory / "plan-proj-legacy.json").write_text(json.dumps(legacy_payload))

        loaded_first = store.load("proj-legacy", "plan-proj-legacy")
        loaded_second = store.load("proj-legacy", "plan-proj-legacy")

        assert loaded_first.generation_id == "legacy-plan-proj-legacy"
        assert loaded_first.generation_id == loaded_second.generation_id, "deterministic across reload/restart"

    def test_legacy_generation_identity_does_not_collide_with_a_real_new_generation(self, tmp_path):
        from app.requirement_model import SetupPlan

        legacy_style_id = f"legacy-plan-x"
        real_plan = SetupPlan(id="plan-x", project_id="proj-x")

        assert real_plan.generation_id != legacy_style_id, (
            "a real, randomly-generated generation_id must never take "
            "the deterministic legacy-derived shape"
        )

    def test_corrupt_generation_id_fails_closed_not_treated_as_legacy(self, tmp_path):
        import json

        store = WorkflowPlanStore(tmp_path / "plans")
        directory = tmp_path / "plans" / "proj-corrupt"
        directory.mkdir(parents=True)
        payload = {
            "id": "plan-proj-corrupt", "project_id": "proj-corrupt",
            "steps": [], "requires_user_approval": True,
            "status": "approved", "generation_id": "",
        }
        (directory / "plan-proj-corrupt.json").write_text(json.dumps(payload))

        with pytest.raises(WorkflowPlanStoreError):
            store.load("proj-corrupt", "plan-proj-corrupt")


class TestGenerationCannotBeClientSupplied:
    def test_generation_id_defaults_centrally_and_is_not_a_constructor_requirement(self):
        """A caller building a SetupPlan without specifying
        generation_id always gets one generated centrally -- there is
        no way for an external input (e.g. a Web/MCP request body) to
        supply this value through normal construction."""
        from app.requirement_model import SetupPlan

        plan_1 = SetupPlan(id="plan-x", project_id="proj-x")
        plan_2 = SetupPlan(id="plan-x", project_id="proj-x")

        assert plan_1.generation_id
        assert plan_2.generation_id
        assert plan_1.generation_id != plan_2.generation_id


class TestCapabilityRegistrySupersede:
    """Part 6: CapabilityRegistry.supersede_approved() only replaces an
    existing registration for the exact same executable identity, and
    still enforces the full provenance-completeness/project-scope
    validation register_approved() itself enforces -- it does not
    weaken CapabilityRegistry."""

    def _registration(self, project_scope, human_ref):
        return CapabilityRegistration(
            capability="python", executable_names=("/opt/tool/python",),
            allowed_operations=("install", "verification"),
            approval_provenance=ApprovalProvenance(
                project_intelligence_ref=str(project_scope),
                engineering_council_ref="council-x", chairman_approval_ref="variant-x",
                human_approval_ref=human_ref,
            ),
            project_scope=str(project_scope),
        )

    def test_supersede_replaces_same_target_registration(self, tmp_path):
        registry = CapabilityRegistry()
        first = self._registration(tmp_path, "setup-approval:plan:gen-a:approved")
        registry.register_approved(first)

        second = self._registration(tmp_path, "setup-approval:plan:gen-b:approved")
        registry.supersede_approved(second)

        current = registry.get("python", tmp_path)
        assert current.approval_provenance.human_approval_ref == "setup-approval:plan:gen-b:approved"

    def test_supersede_still_rejects_incomplete_provenance(self, tmp_path):
        registry = CapabilityRegistry()
        first = self._registration(tmp_path, "setup-approval:plan:gen-a:approved")
        registry.register_approved(first)

        from dataclasses import replace
        broken = replace(
            self._registration(tmp_path, "setup-approval:plan:gen-b:approved"),
            approval_provenance=ApprovalProvenance(
                project_intelligence_ref=str(tmp_path),
                engineering_council_ref="", chairman_approval_ref="variant-x",
                human_approval_ref="setup-approval:plan:gen-b:approved",
            ),
        )
        with pytest.raises(ValueError):
            registry.supersede_approved(broken)
