"""CLAUDE-E2E-003I-B: Human Approval binds execution-relevant SetupStep
content BEFORE the first SetupExecutionState record exists.

Mechanically confirmed by direct reproduction (before any fix) that
Human Approval for setup generation G1 / step S1 / content A did NOT
bind anything about content A itself -- only generation_id, project
scope and Council/Chairman references. A step whose execution-relevant
content was mutated to B while keeping the SAME generation_id, SAME
step_id and "approved" status was silently re-authorized using G1's
original approval, provided no SetupExecutionState record for A had
ever been created yet -- REQ-S3-GENERATION-CONTENT-IMMUTABILITY
(app.setup_execution_state) never had an existing record to compare
against in that window, so its own protection never engaged.

This closes that gap via REQ-S3-APPROVED-PLAN-CONTENT-IMMUTABILITY
(app.approved_plan_content). TC numbering follows CLAUDE-E2E-003I-B
Part 3/6/7/8 exactly.
"""
from __future__ import annotations

import os
from dataclasses import replace

import pytest

from app.approved_plan_content import ApprovedPlanContentError, ApprovedPlanContentStore
from app.council_models import CouncilResult, CouncilVariant, ToolchainItem
from app.dev_workflow import DevelopmentWorkflow
from app.execution import CapabilityRegistry
from app.project_setup_application import authorize_setup_plan_targets
from app.python_package_executor import PythonPackageExecutor
from app.requirement_model import Requirement, RequirementType
from app.requirement_preflight import RequirementPreflight
from app.setup_approval import SetupApproval
from app.setup_execution_state import SetupExecutionStateStore
from app.toolchain_materializer import ToolchainMaterializer

from tests.local_package_fixture import (
    PACKAGE_NAME, build_launch_counting_target, build_local_wheel_index, read_launch_count,
)


def _requirement(req_id, name=PACKAGE_NAME):
    return Requirement(
        id=req_id, name=name, type=RequirementType.PYTHON_PACKAGE,
        purpose="test dependency", required=True, confidence=0.9,
    )


def _materialize_and_approve(project_id, project_root, requirement, council_id, name=PACKAGE_NAME):
    preflight = RequirementPreflight.check((requirement,), project_id, project_root=str(project_root))
    item = ToolchainItem(
        requirement_ref=requirement.id, name=name,
        type=RequirementType.PYTHON_PACKAGE, install_method=f"pip install {name}",
    )
    variant = CouncilVariant(id="variant-1", name="variant-1", toolchain=(item,))
    council = CouncilResult(
        id=council_id, project_id=project_id, variants=(variant,),
        recommendation="variant-1", council_complete=True,
    )
    plan = ToolchainMaterializer().materialize(council, project_id, preflight=preflight)
    approved = SetupApproval.approve(plan)
    return approved, council


class TestTC1ApprovalDoesNotAuthorizeChangedContentBeforeFirstExecution:
    """TC-S3-APPROVAL-CONTENT-01 (negative): G1/A approved, NO execution
    yet, NO SetupExecutionState record yet -- mutate to B under the SAME
    generation -- must fail closed with zero Capability authorization,
    zero begin(), zero subprocess, mutation counter unchanged."""

    def test_no_execution_yet_changed_content_is_blocked(self, tmp_path, monkeypatch):
        wheels = build_local_wheel_index(tmp_path)
        target, counter = build_launch_counting_target(tmp_path, "toolchain-a", wheels)
        monkeypatch.setenv("PATH", f"{os.path.dirname(target)}:{os.environ.get('PATH', '')}")
        project_root = tmp_path / "project"
        project_root.mkdir()
        requirement = _requirement("req-approval-tc1")
        approved_a, council = _materialize_and_approve(project_root.name, project_root, requirement, "council-tc1")

        content_store = ApprovedPlanContentStore(tmp_path / "approved-content.json")
        content_store.record_approved(approved_a)  # the real Human Approval event

        exec_store = SetupExecutionStateStore(tmp_path / "exec-state.json")
        workflow = DevelopmentWorkflow(
            discovery=None, validator=None, preflight=None,
            executor=PythonPackageExecutor(), execution_state_store=exec_store,
        )
        count_before = read_launch_count(counter)

        # Mutate execution-relevant content while retaining the same
        # generation, step_id and "approved" status -- G1/A -> G1/B.
        mutated_step = replace(approved_a.steps[0], package="different-package", install_method="pip install different-package")
        approved_b = replace(approved_a, steps=(mutated_step,))
        assert approved_b.generation_id == approved_a.generation_id
        assert approved_b.steps[0].id == approved_a.steps[0].id
        assert approved_b.status == "approved"

        registry = CapabilityRegistry()
        with pytest.raises(ApprovedPlanContentError):
            authorize_setup_plan_targets(
                approved_b, project_root,
                engineering_council_ref=council.id, chairman_approval_ref=council.recommendation,
                capability_registry=registry, approved_content_store=content_store,
            )
        assert registry.get("python", project_root) is None, "no Capability authorization for B"

        # No SetupExecutionState record exists for A OR B: begin() was
        # never reached for either.
        from app.setup_execution_state import SetupStepIdentity
        identity_b = SetupStepIdentity.for_step(str(project_root), approved_b.generation_id, approved_b.steps[0])
        assert exec_store.get(identity_b) is None

        # The productive gate (authorize_setup_plan_targets, above)
        # already stopped everything before any subprocess could run.
        assert read_launch_count(counter) == count_before, "mutation counter must remain unchanged"


class TestTC2NewGenerationWithNewApprovalPermutation:
    """Part 6/11 permutation #7: a genuinely new materialization (G2/B)
    with its OWN new Human Approval authorizes and executes exactly
    once -- proving the fix does not block legitimate new generations."""

    def test_new_generation_new_approval_executes_once(self, tmp_path, monkeypatch):
        wheels = build_local_wheel_index(tmp_path)
        target, counter = build_launch_counting_target(tmp_path, "toolchain-a", wheels)
        monkeypatch.setenv("PATH", f"{os.path.dirname(target)}:{os.environ.get('PATH', '')}")
        project_root = tmp_path / "project"
        project_root.mkdir()
        requirement = _requirement("req-approval-tc2")
        approved_g2, council = _materialize_and_approve(project_root.name, project_root, requirement, "council-tc2")

        content_store = ApprovedPlanContentStore(tmp_path / "approved-content.json")
        content_store.record_approved(approved_g2)

        exec_store = SetupExecutionStateStore(tmp_path / "exec-state.json")
        workflow = DevelopmentWorkflow(
            discovery=None, validator=None, preflight=None,
            executor=PythonPackageExecutor(), execution_state_store=exec_store,
        )
        count_before = read_launch_count(counter)
        registry = CapabilityRegistry()

        authorize_setup_plan_targets(
            approved_g2, project_root,
            engineering_council_ref=council.id, chairman_approval_ref=council.recommendation,
            capability_registry=registry, approved_content_store=content_store,
        )
        assert registry.get("python", project_root) is not None

        result = workflow.execute_approved(approved_g2, str(project_root))
        assert result[0].success is True
        assert read_launch_count(counter) > count_before


class TestPart7RestartContract:
    """Part 7: approval-content binding must survive a restart (a fresh
    ApprovedPlanContentStore instance re-reading the same persisted
    file, simulating a process restart)."""

    def test_unchanged_content_remains_executable_after_restart(self, tmp_path, monkeypatch):
        wheels = build_local_wheel_index(tmp_path)
        target, counter = build_launch_counting_target(tmp_path, "toolchain-a", wheels)
        monkeypatch.setenv("PATH", f"{os.path.dirname(target)}:{os.environ.get('PATH', '')}")
        project_root = tmp_path / "project"
        project_root.mkdir()
        requirement = _requirement("req-approval-restart-ok")
        approved, council = _materialize_and_approve(project_root.name, project_root, requirement, "council-restart-ok")
        storage_path = tmp_path / "approved-content.json"

        content_store_a = ApprovedPlanContentStore(storage_path)
        content_store_a.record_approved(approved)

        # --- simulated restart: a fresh store instance, same file ---
        content_store_b = ApprovedPlanContentStore(storage_path)
        registry = CapabilityRegistry()
        authorize_setup_plan_targets(
            approved, project_root,
            engineering_council_ref=council.id, chairman_approval_ref=council.recommendation,
            capability_registry=registry, approved_content_store=content_store_b,
        )
        assert registry.get("python", project_root) is not None

        exec_store = SetupExecutionStateStore(tmp_path / "exec-state.json")
        workflow = DevelopmentWorkflow(
            discovery=None, validator=None, preflight=None,
            executor=PythonPackageExecutor(), execution_state_store=exec_store,
        )
        result = workflow.execute_approved(approved, str(project_root))
        assert result[0].success is True

    def test_changed_content_remains_blocked_after_restart(self, tmp_path, monkeypatch):
        wheels = build_local_wheel_index(tmp_path)
        target, counter = build_launch_counting_target(tmp_path, "toolchain-a", wheels)
        monkeypatch.setenv("PATH", f"{os.path.dirname(target)}:{os.environ.get('PATH', '')}")
        project_root = tmp_path / "project"
        project_root.mkdir()
        requirement = _requirement("req-approval-restart-blocked")
        approved, council = _materialize_and_approve(project_root.name, project_root, requirement, "council-restart-blocked")
        storage_path = tmp_path / "approved-content.json"

        content_store_a = ApprovedPlanContentStore(storage_path)
        content_store_a.record_approved(approved)
        count_before = read_launch_count(counter)

        # --- simulated restart ---
        content_store_b = ApprovedPlanContentStore(storage_path)
        mutated_step = replace(approved.steps[0], command="pip install something-else")
        mutated = replace(approved, steps=(mutated_step,))
        registry = CapabilityRegistry()

        with pytest.raises(ApprovedPlanContentError):
            authorize_setup_plan_targets(
                mutated, project_root,
                engineering_council_ref=council.id, chairman_approval_ref=council.recommendation,
                capability_registry=registry, approved_content_store=content_store_b,
            )
        assert registry.get("python", project_root) is None
        assert read_launch_count(counter) == count_before


class TestPart8MultiStepApprovalContent:
    """Part 8: a plan with multiple steps -- one unchanged, one mutated
    after approval -- must fail closed for the whole affected
    authorization attempt before any registration happens for either
    step, not just the mutated one. A central plan/content contract
    test, deliberately not a large productive multi-package fixture
    (Part 8 explicitly permits this)."""

    def test_one_changed_step_blocks_the_whole_authorization_attempt(self, tmp_path):
        project_id = "proj-multi-step"
        project_root = tmp_path / "project"
        project_root.mkdir()
        requirement_a = _requirement("req-multi-a", name="pkg-a")
        requirement_b = _requirement("req-multi-b", name="pkg-b")
        preflight = RequirementPreflight.check(
            (requirement_a, requirement_b), project_id, project_root=str(project_root),
        )
        item_a = ToolchainItem(
            requirement_ref=requirement_a.id, name="pkg-a",
            type=RequirementType.PYTHON_PACKAGE, install_method="pip install pkg-a",
        )
        item_b = ToolchainItem(
            requirement_ref=requirement_b.id, name="pkg-b",
            type=RequirementType.PYTHON_PACKAGE, install_method="pip install pkg-b",
        )
        variant = CouncilVariant(id="variant-1", name="variant-1", toolchain=(item_a, item_b))
        council = CouncilResult(
            id="council-multi", project_id=project_id, variants=(variant,),
            recommendation="variant-1", council_complete=True,
        )
        plan = ToolchainMaterializer().materialize(council, project_id, preflight=preflight)
        assert len(plan.steps) == 2
        approved = SetupApproval.approve(plan)

        content_store = ApprovedPlanContentStore(tmp_path / "approved-content.json")
        content_store.record_approved(approved)

        step_a, step_b = approved.steps
        mutated_step_b = replace(step_b, package="pkg-b-mutated", install_method="pip install pkg-b-mutated")
        mutated_plan = replace(approved, steps=(step_a, mutated_step_b))

        registry = CapabilityRegistry()
        with pytest.raises(ApprovedPlanContentError):
            authorize_setup_plan_targets(
                mutated_plan, project_root,
                engineering_council_ref=council.id, chairman_approval_ref=council.recommendation,
                capability_registry=registry, approved_content_store=content_store,
            )
        # Zero registrations for EITHER step -- including the untouched
        # step_a, which never got a chance to be authorized either,
        # because the whole approved-content set is verified up front.
        assert registry.get("python", project_root) is None
