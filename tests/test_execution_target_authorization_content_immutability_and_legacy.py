"""CLAUDE-E2E-003I-A: same-generation content immutability and legacy
003H execution-state upgrade safety.

Closes two real defects an independent review of CLAUDE-E2E-003I found
and this task confirmed by mechanical reproduction before fixing:

1. Same generation + changed execution-relevant content was silently
   treated as NOT_STARTED, allowing a fresh, unauthorized mutation to
   begin under an approval that was never granted for that content
   (REQ-S3-GENERATION-CONTENT-IMMUTABILITY, see app/setup_execution_state.py).

2. A real CLAUDE-E2E-003H-format execution-state record (keyed by the
   raw plan.id, before the "legacy-" generation-identity prefix
   existed) became invisible to CLAUDE-E2E-003I's generation-based
   lookup after upgrading, causing a genuinely already-SUCCEEDED step
   to be silently re-interpreted as never attempted.

TC numbering below follows CLAUDE-E2E-003I-A Part 19 exactly.
"""
from __future__ import annotations

import json
import os

import pytest

from app.canonical_execution import project_key as resolve_project_key
from app.council_models import CouncilResult, CouncilVariant, ToolchainItem
from app.dev_workflow import DevelopmentWorkflow
from app.python_package_executor import PythonPackageExecutor
from app.requirement_model import Requirement, RequirementType
from app.requirement_preflight import RequirementPreflight
from app.setup_approval import SetupApproval
from app.setup_execution_state import (
    FAILED, IN_PROGRESS, SUCCEEDED, SetupExecutionStateError, SetupExecutionStateStore,
    SetupStepIdentity,
)
from app.toolchain_materializer import ToolchainMaterializer
from app.workflow_plan_store import WorkflowPlanStore

from tests.local_package_fixture import (
    PACKAGE_NAME, build_launch_counting_target, build_local_wheel_index, read_launch_count,
)


def _requirement(req_id):
    return Requirement(
        technical_identity=PACKAGE_NAME,
        id=req_id, name=PACKAGE_NAME, type=RequirementType.PYTHON_PACKAGE,
        purpose="test dependency", required=True, confidence=0.9,
    )


def _materialize_and_approve(project_id, project_root, requirement, council_id):
    preflight = RequirementPreflight.check((requirement,), project_id, project_root=str(project_root))
    item = ToolchainItem(
        requirement_ref=requirement.id, name=PACKAGE_NAME,
        type=RequirementType.PYTHON_PACKAGE, install_method=f"pip install {PACKAGE_NAME}",
    )
    variant = CouncilVariant(id="variant-1", name="variant-1", toolchain=(item,))
    council = CouncilResult(
        id=council_id, project_id=project_id, variants=(variant,),
        recommendation="variant-1", council_complete=True,
    )
    plan = ToolchainMaterializer().materialize(council, project_id, preflight=preflight)
    approved = SetupApproval.approve(plan)
    return approved, council


def _write_legacy_execution_state(state_path, project_key, legacy_plan_id, step_id, status, content, result=None):
    """Build a REAL CLAUDE-E2E-003H-format execution-state file: keyed
    by the raw plan.id (the "legacy-" prefix concept did not exist
    before CLAUDE-E2E-003I). Mechanically derived from the actual
    pre-003I-A SetupExecutionStateStore.begin()/finish() record shape.
    """
    record = {
        "project_key": project_key, "plan_id": legacy_plan_id, "step_id": step_id,
        "status": status, "content": list(content), "owner_id": "legacy-owner",
        "started_at": "2025-01-01T00:00:00+00:00",
    }
    if status in (SUCCEEDED, FAILED):
        record["finished_at"] = "2025-01-01T00:00:05+00:00"
        record["result"] = result or {"success": status == SUCCEEDED, "message": "legacy", "verification_passed": status == SUCCEEDED}
    payload = {project_key: {legacy_plan_id: {step_id: record}}}
    state_path.write_text(json.dumps(payload))


class TestTC1SameGenerationContentChangeFailsClosed:
    """TC1: same generation + SUCCEEDED content A -> content B -> FAIL
    CLOSED, zero launch, old SUCCEEDED result NOT returned for B."""

    def test_same_generation_changed_content_fails_closed_with_zero_launches(self, tmp_path, monkeypatch):
        wheels = build_local_wheel_index(tmp_path)
        target, counter = build_launch_counting_target(tmp_path, "toolchain-a", wheels)
        monkeypatch.setenv("PATH", f"{os.path.dirname(target)}:{os.environ.get('PATH', '')}")
        project_root = tmp_path / "project"
        project_root.mkdir()
        requirement = _requirement("req-tc1")
        approved, _council = _materialize_and_approve(project_root.name, project_root, requirement, "council-tc1")
        store = SetupExecutionStateStore(tmp_path / "exec-state.json")
        workflow = DevelopmentWorkflow(
            discovery=None, validator=None, preflight=None,
            executor=PythonPackageExecutor(), execution_state_store=store,
        )
        result_a = workflow.execute_approved(approved, str(project_root))
        assert result_a[0].success is True
        count_after_a = read_launch_count(counter)
        assert count_after_a > 0

        # Hand-modify the step's execution-relevant content while
        # KEEPING the exact same generation_id -- the scenario this
        # task's contract forbids from executing freely.
        from dataclasses import replace
        changed_step = replace(approved.steps[0], package="different-package", install_method="pip install different-package")
        changed_plan = replace(approved, steps=(changed_step,))
        assert changed_plan.generation_id == approved.generation_id

        with pytest.raises(SetupExecutionStateError):
            workflow.execute_approved(changed_plan, str(project_root))

        assert read_launch_count(counter) == count_after_a, "zero additional launches for changed content"

        # The OLD SUCCEEDED result for content A must not be silently
        # returned as if it were a valid result for content B either --
        # the raised exception (not a fabricated success) is itself
        # proof of this; additionally confirm no result Class for B exists.
        identity_b = SetupStepIdentity.for_step(str(project_root), approved.generation_id, changed_step)
        with pytest.raises(SetupExecutionStateError):
            store.get(identity_b)


class TestTC2OldApprovalCannotAuthorizeChangedContent:
    """TC2: same generation, content changes before execution -- the
    OLD approval (built from the ORIGINAL content's plan) must not
    authorize the changed content's capability/target either.

    CLAUDE-E2E-003I-B: authorize_setup_plan_targets() itself now raises
    ApprovedPlanContentError for the changed target_executable, because
    it no longer matches what was recorded as approved for this exact
    generation (REQ-S3-APPROVED-PLAN-CONTENT-IMMUTABILITY) -- a strictly
    earlier fail-closed point than the execution-state guard this test
    previously relied on exclusively (which only ever protects the
    interval AFTER a SetupExecutionState record already exists)."""

    def test_authorize_setup_plan_targets_is_never_reached_for_changed_content(self, tmp_path, monkeypatch):
        from app.approved_plan_content import ApprovedPlanContentError, ApprovedPlanContentStore
        from app.execution import CapabilityRegistry
        from app.project_setup_application import authorize_setup_plan_targets

        wheels = build_local_wheel_index(tmp_path)
        target, counter = build_launch_counting_target(tmp_path, "toolchain-a", wheels)
        monkeypatch.setenv("PATH", f"{os.path.dirname(target)}:{os.environ.get('PATH', '')}")
        project_root = tmp_path / "project"
        project_root.mkdir()
        requirement = _requirement("req-tc2")
        approved, council = _materialize_and_approve(project_root.name, project_root, requirement, "council-tc2")
        content_store = ApprovedPlanContentStore(tmp_path / "approved-content.json")
        content_store.record_approved(approved)
        store = SetupExecutionStateStore(tmp_path / "exec-state.json")
        workflow = DevelopmentWorkflow(
            discovery=None, validator=None, preflight=None,
            executor=PythonPackageExecutor(), execution_state_store=store,
        )
        workflow.execute_approved(approved, str(project_root))
        count_after_a = read_launch_count(counter)

        from dataclasses import replace
        changed_step = replace(approved.steps[0], target_executable="/attacker/controlled/python")
        changed_plan = replace(approved, steps=(changed_step,))

        registry = CapabilityRegistry()
        # Even attempting to (re-)authorize using the SAME, real
        # council/chairman references from generation A must never
        # reach a real execution for the changed target: the
        # approval-content binding rejects it before any Capability
        # registration is even attempted.
        with pytest.raises(ApprovedPlanContentError):
            authorize_setup_plan_targets(
                changed_plan, project_root,
                engineering_council_ref=council.id, chairman_approval_ref=council.recommendation,
                capability_registry=registry, approved_content_store=content_store,
            )
        assert registry.get("python", project_root) is None, "no Capability authorization for the changed target"

        # The pre-existing execution-state guard independently also
        # rejects it (defense in depth, REQ-S3-GENERATION-CONTENT-
        # IMMUTABILITY) since generation A already SUCCEEDED.
        with pytest.raises(SetupExecutionStateError):
            workflow.execute_approved(changed_plan, str(project_root))

        assert read_launch_count(counter) == count_after_a


class TestTC3NewGenerationWithoutNewApprovalIsBlocked:
    """TC3: new generation + content B + NO new approval -> blocked."""

    def test_unapproved_new_generation_is_blocked(self, tmp_path, monkeypatch):
        from app.execution import CapabilityRegistry
        from app.project_setup_application import authorize_setup_plan_targets

        wheels = build_local_wheel_index(tmp_path)
        target, counter = build_launch_counting_target(tmp_path, "toolchain-a", wheels)
        monkeypatch.setenv("PATH", f"{os.path.dirname(target)}:{os.environ.get('PATH', '')}")
        project_root = tmp_path / "project"
        project_root.mkdir()
        requirement = _requirement("req-tc3")
        project_id = project_root.name

        preflight = RequirementPreflight.check((requirement,), project_id, project_root=str(project_root))
        item = ToolchainItem(
            requirement_ref=requirement.id, name=PACKAGE_NAME,
            type=RequirementType.PYTHON_PACKAGE, install_method=f"pip install {PACKAGE_NAME}",
        )
        variant = CouncilVariant(id="variant-1", name="variant-1", toolchain=(item,))
        council = CouncilResult(id="council-tc3", project_id=project_id, variants=(variant,), recommendation="variant-1", council_complete=True)
        plan_b = ToolchainMaterializer().materialize(council, project_id, preflight=preflight)
        assert plan_b.status == "pending_approval"

        store = SetupExecutionStateStore(tmp_path / "exec-state.json")
        workflow = DevelopmentWorkflow(
            discovery=None, validator=None, preflight=None,
            executor=PythonPackageExecutor(), execution_state_store=store,
        )
        count_before = read_launch_count(counter)

        registry = CapabilityRegistry()
        authorize_setup_plan_targets(
            plan_b, project_root,
            engineering_council_ref=council.id, chairman_approval_ref=council.recommendation,
            capability_registry=registry,
        )
        assert registry.get("python", project_root) is None, "an unapproved plan must never be authorized"

        from app.dev_workflow import WorkflowExecutionError
        with pytest.raises(WorkflowExecutionError):
            workflow.execute_approved(plan_b, str(project_root))

        assert read_launch_count(counter) == count_before


class TestTC4NewGenerationWithNewApprovalExecutesOnce:
    """TC4: new generation + content B + new approval -> exactly one
    legitimate execution. (Also covered end-to-end by
    tests/test_execution_target_authorization_generation.py::TestEnvironmentRepairScenario;
    kept here as an explicit, minimal, directly-labeled TC.)"""

    def test_new_generation_with_new_approval_executes_once(self, tmp_path, monkeypatch):
        wheels = build_local_wheel_index(tmp_path)
        target, counter = build_launch_counting_target(tmp_path, "toolchain-a", wheels)
        monkeypatch.setenv("PATH", f"{os.path.dirname(target)}:{os.environ.get('PATH', '')}")
        project_root = tmp_path / "project"
        project_root.mkdir()
        requirement = _requirement("req-tc4")
        approved, _council = _materialize_and_approve(project_root.name, project_root, requirement, "council-tc4")
        store = SetupExecutionStateStore(tmp_path / "exec-state.json")
        workflow = DevelopmentWorkflow(
            discovery=None, validator=None, preflight=None,
            executor=PythonPackageExecutor(), execution_state_store=store,
        )
        count_before = read_launch_count(counter)

        result = workflow.execute_approved(approved, str(project_root))

        assert result[0].success is True
        assert read_launch_count(counter) > count_before


class TestLegacy003HUpgradeSafety:
    """TC5-TC8: real CLAUDE-E2E-003H-format execution-state records
    must remain safe after upgrading to CLAUDE-E2E-003I-A."""

    def _legacy_plan_and_identity(self, tmp_path, project_root, status, result=None):
        plan_store = WorkflowPlanStore(tmp_path / "plans")
        project_id = project_root.name
        legacy_plan_id = f"plan-{project_id}"
        directory = tmp_path / "plans" / project_id
        directory.mkdir(parents=True, exist_ok=True)
        content = ["install", "python_package_install", "pip install x", "x", None, None, "/bin/target-python"]
        step_payload = {
            "id": "step-legacy", "requirement_id": "req-legacy", "action": "install",
            "install_method": "pip install x", "package": "x", "version": None,
            "command": None, "verification_after": None, "is_approved": True,
            "setup_effect": "python_package_install", "target_executable": "/bin/target-python",
        }
        plan_payload = {
            "id": legacy_plan_id, "project_id": project_id, "steps": [step_payload],
            "requires_user_approval": True, "status": "approved",
            # no "generation_id" key -- the exact real pre-003I persisted shape
        }
        (directory / f"{legacy_plan_id}.json").write_text(json.dumps(plan_payload))

        pk = resolve_project_key(str(project_root))
        state_path = tmp_path / "exec-state.json"
        _write_legacy_execution_state(state_path, pk, legacy_plan_id, "step-legacy", status, content, result)

        loaded = plan_store.load(project_id, legacy_plan_id)
        assert loaded.generation_id == f"legacy-{legacy_plan_id}"
        identity = SetupStepIdentity.for_step(str(project_root), loaded.generation_id, loaded.steps[0])
        return loaded, identity, state_path

    def test_tc5_legacy_succeeded_upgrade_zero_replay(self, tmp_path):
        project_root = tmp_path / "project"
        project_root.mkdir()
        loaded, identity, state_path = self._legacy_plan_and_identity(
            tmp_path, project_root, SUCCEEDED,
            result={"success": True, "message": "legacy install ok", "verification_passed": True},
        )
        store = SetupExecutionStateStore(state_path)

        record = store.get(identity)

        assert record is not None
        assert record["status"] == SUCCEEDED

    def test_tc6_legacy_succeeded_survives_a_further_restart(self, tmp_path):
        project_root = tmp_path / "project"
        project_root.mkdir()
        loaded, identity, state_path = self._legacy_plan_and_identity(
            tmp_path, project_root, SUCCEEDED,
            result={"success": True, "message": "legacy install ok", "verification_passed": True},
        )
        store_a = SetupExecutionStateStore(state_path)
        assert store_a.get(identity)["status"] == SUCCEEDED

        store_b = SetupExecutionStateStore(state_path)  # fresh instance -- simulated restart
        record = store_b.get(identity)
        assert record is not None
        assert record["status"] == SUCCEEDED

    def test_tc7_legacy_in_progress_fails_closed(self, tmp_path):
        project_root = tmp_path / "project"
        project_root.mkdir()
        loaded, identity, state_path = self._legacy_plan_and_identity(
            tmp_path, project_root, IN_PROGRESS,
        )
        store = SetupExecutionStateStore(state_path)

        with pytest.raises(SetupExecutionStateError):
            store.begin(identity, "new-owner")

    def test_tc8_legacy_failed_is_not_automatically_replayed(self, tmp_path):
        project_root = tmp_path / "project"
        project_root.mkdir()
        loaded, identity, state_path = self._legacy_plan_and_identity(
            tmp_path, project_root, FAILED,
            result={"success": False, "message": "legacy install failed", "verification_passed": False},
        )
        store = SetupExecutionStateStore(state_path)

        record = store.get(identity)
        assert record["status"] == FAILED
        with pytest.raises(SetupExecutionStateError):
            store.begin(identity, "new-owner")

    def test_tc9_legacy_lookup_is_pure_read_no_migration_write(self, tmp_path):
        """TC9: the legacy compatibility lookup never writes/migrates
        anything, so it cannot introduce a new cross-process race
        surface -- proven by observing the state file's mtime/content
        is unchanged after repeated reads."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        loaded, identity, state_path = self._legacy_plan_and_identity(
            tmp_path, project_root, SUCCEEDED,
            result={"success": True, "message": "legacy install ok", "verification_passed": True},
        )
        before = state_path.read_text()

        store = SetupExecutionStateStore(state_path)
        store.get(identity)
        store.get(identity)
        store.get(identity)

        after = state_path.read_text()
        assert before == after, "the read-only legacy lookup must never write or migrate the store"
