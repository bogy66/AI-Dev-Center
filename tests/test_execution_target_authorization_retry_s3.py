"""CLAUDE-E2E-003H official S3 (Environment & Setup) subsystem tests:
persisted setup-execution retry/restart safety.

Uses a real, observable, subprocess.run()-independent launch counter
(tests/local_package_fixture.py::build_launch_counting_target) rather
than mocking subprocess.run or relying on backend (pip) idempotency as
evidence, per Part 9.

TestReproducesThe003GDefect formalizes the exact defect this task
closes: without an execution_state_store, DevelopmentWorkflow.execute_approved()
launches the real mutating process again on every call, even for an
already-succeeded step -- proven with a real, counted launch, not
inferred from code. Every other test class in this file proves the
fix, wired the same way production composition wires it.
"""
from __future__ import annotations

import os

import pytest

from app.council_models import CouncilResult, CouncilVariant, ToolchainItem
from app.dev_workflow import DevelopmentWorkflow, WorkflowExecutionError
from app.execution import register_setup_step_targets
from app.python_package_executor import PythonPackageExecutor
from app.requirement_model import Requirement, RequirementType, SetupEffect, SetupStep
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


def _requirement(req_id="req-s3"):
    return Requirement(
        technical_identity=PACKAGE_NAME,
        id=req_id, name=PACKAGE_NAME, type=RequirementType.PYTHON_PACKAGE,
        purpose="test dependency", required=True, confidence=0.9,
    )


def _council_result(requirement_id, project_id):
    item = ToolchainItem(
        requirement_ref=requirement_id, name=PACKAGE_NAME,
        type=RequirementType.PYTHON_PACKAGE, install_method=f"pip install {PACKAGE_NAME}",
    )
    variant = CouncilVariant(id="variant-1", name="variant-1", toolchain=(item,))
    return CouncilResult(
        id="council-1", project_id=project_id,
        variants=(variant,), recommendation="variant-1", council_complete=True,
    )


def _build_approved_plan(tmp_path, project_root, target_a, project_id, requirement):
    preflight = RequirementPreflight.check((requirement,), project_id, project_root=str(project_root))
    plan = ToolchainMaterializer().materialize(
        _council_result(requirement.id, project_id), project_id, preflight=preflight,
    )
    assert plan.steps[0].target_executable == target_a
    approved = SetupApproval.approve(plan)
    # CLAUDE-ADC-ZIELBILD-DIFF-FIX-001 (B1): a mutating "install" now
    # requires a project-scoped, approval-provenance-backed capability
    # registration -- exactly what the real productive
    # execute_approved_setup_and_development() -> authorize_setup_
    # plan_targets() -> register_setup_step_targets() chain performs,
    # reused here so this file's own retry/restart-safety proofs stay
    # focused on what they actually test.
    register_setup_step_targets(
        approved, project_root,
        engineering_council_ref="council-1", chairman_approval_ref="variant-1",
        human_approval_ref=f"setup-approval:{plan.id}:{approved.generation_id}:approved",
    )
    return approved


@pytest.fixture()
def target_a(tmp_path, monkeypatch):
    wheels = build_local_wheel_index(tmp_path)
    target, counter = build_launch_counting_target(tmp_path, "toolchain-a", wheels)
    prior_path = os.environ.get("PATH", "")
    monkeypatch.setenv("PATH", f"{os.path.dirname(target)}:{prior_path}")
    return target, counter


class TestReproducesThe003GDefectHistorically:
    """Historical, permanent record of the CLAUDE-E2E-003G defect (Part
    24): before CLAUDE-E2E-003H, retrying an already-successful setup
    execution launched the real mutating process again, because no
    execution-state guard existed at all.

    CLAUDE-E2E-003I closes the *residual* half of that defect: 003H
    only guarded execution when a caller happened to supply an
    execution_state_store, but a productive-shaped call (project_root
    supplied) with none configured still silently executed unguarded --
    the exact configuration this test previously used to reproduce the
    003G defect "live". That configuration is now itself impossible:
    DevelopmentWorkflow.execute_approved() fails closed instead
    (test_confined_execution_without_state_store_fails_closed below),
    which is the correct, final fix Part 2 of 003I requires. The literal
    003G defect can therefore no longer be demonstrated by constructing
    a real DevelopmentWorkflow at all -- only by directly, repeatedly
    invoking the underlying executor without any workflow/guard in
    between, which is what this test now does, purely as a historical
    illustration of what "no guard at all" used to mean in practice.
    """

    def test_calling_the_bare_executor_twice_relaunches(self, tmp_path, target_a):
        target, counter = target_a
        project_root = tmp_path / "project"
        project_root.mkdir()
        requirement = _requirement("req-repro-historical")
        approved = _build_approved_plan(tmp_path, project_root, target, "proj-repro-hist", requirement)

        executor = PythonPackageExecutor()

        first = executor.execute(approved.steps[0], str(project_root))
        assert first.success is True
        count_after_first = read_launch_count(counter)
        assert count_after_first > 0

        second = executor.execute(approved.steps[0], str(project_root))
        assert second.success is True
        count_after_retry = read_launch_count(counter)

        assert count_after_retry > count_after_first, (
            "historical illustration only: PythonPackageExecutor.execute() "
            "itself never had (and still does not have) any replay memory "
            "-- that responsibility belongs entirely to "
            "DevelopmentWorkflow._execute_with_state_guard(), which every "
            "productive call path now mandatorily passes through instead "
            "of ever reaching the bare executor directly like this test does"
        )


class TestConfinedExecutionRequiresStateAuthority:
    """CLAUDE-E2E-003I Part 2: a productive-shaped execute_approved()
    call (project_root supplied) with no execution_state_store
    configured must fail closed, never silently execute unguarded."""

    def test_confined_execution_without_state_store_fails_closed(self, tmp_path, target_a):
        target, counter = target_a
        project_root = tmp_path / "project"
        project_root.mkdir()
        requirement = _requirement("req-mandatory")
        approved = _build_approved_plan(tmp_path, project_root, target, "proj-mandatory", requirement)
        count_before = read_launch_count(counter)

        unguarded_workflow = DevelopmentWorkflow(
            discovery=None, validator=None, preflight=None,
            executor=PythonPackageExecutor(),
            # No execution_state_store -- must now fail closed, not execute.
        )

        with pytest.raises(WorkflowExecutionError):
            unguarded_workflow.execute_approved(approved, str(project_root))

        assert read_launch_count(counter) == count_before, "no mutation may occur without state authority"

    def test_unconfined_call_without_project_root_remains_a_legitimate_low_level_helper(self):
        """Omitting project_root entirely (never done by Web, MCP, or
        the application service, which always supply a real one) is
        the one remaining legitimate low-level/unit-test shape that
        does not require an execution_state_store -- documented
        explicitly, not reachable from any productive path."""
        from unittest.mock import MagicMock

        from app.requirement_model import SetupPlan, SetupStep

        plan = SetupPlan(
            id="plan-unconfined", project_id="proj-unconfined",
            status="approved",
            steps=(SetupStep(
                id="step-1", requirement_id="req-1", action="install",
                install_method="pip install x", package="x", is_approved=True,
            ),),
        )
        fake_executor = MagicMock()
        fake_executor.execute.return_value = MagicMock(success=True)
        workflow = DevelopmentWorkflow(
            discovery=None, validator=None, preflight=None, executor=fake_executor,
        )

        workflow.execute_approved(plan)  # no project_root -- no exception

        fake_executor.execute.assert_called_once()


class TestGuardedFirstExecutionAndRetry:
    def _guarded_workflow(self, tmp_path):
        store = SetupExecutionStateStore(tmp_path / "exec-state.json")
        return DevelopmentWorkflow(
            discovery=None, validator=None, preflight=None,
            executor=PythonPackageExecutor(), execution_state_store=store,
        ), store

    def test_first_real_execution_persists_succeeded(self, tmp_path, target_a):
        target, counter = target_a
        project_root = tmp_path / "project"
        project_root.mkdir()
        requirement = _requirement("req-first")
        approved = _build_approved_plan(tmp_path, project_root, target, "proj-first", requirement)
        workflow, store = self._guarded_workflow(tmp_path)

        result = workflow.execute_approved(approved, str(project_root))

        assert result[0].success is True
        assert read_launch_count(counter) > 0
        identity = SetupStepIdentity.for_step(str(project_root), approved.generation_id, approved.steps[0])
        record = store.get(identity)
        assert record["status"] == SUCCEEDED

    def test_second_execute_request_does_not_relaunch(self, tmp_path, target_a):
        target, counter = target_a
        project_root = tmp_path / "project"
        project_root.mkdir()
        requirement = _requirement("req-retry")
        approved = _build_approved_plan(tmp_path, project_root, target, "proj-retry", requirement)
        workflow, store = self._guarded_workflow(tmp_path)

        workflow.execute_approved(approved, str(project_root))
        count_after_first = read_launch_count(counter)

        second = workflow.execute_approved(approved, str(project_root))

        assert second[0].success is True
        assert read_launch_count(counter) == count_after_first, "no second real launch"

    def test_process_restart_after_succeeded_does_not_relaunch(self, tmp_path, target_a):
        """A fresh store instance (simulating an ADC process restart)
        must still honor the persisted SUCCEEDED record."""
        target, counter = target_a
        project_root = tmp_path / "project"
        project_root.mkdir()
        requirement = _requirement("req-restart")
        approved = _build_approved_plan(tmp_path, project_root, target, "proj-restart", requirement)
        storage_path = tmp_path / "exec-state.json"

        store_a = SetupExecutionStateStore(storage_path)
        workflow_a = DevelopmentWorkflow(
            discovery=None, validator=None, preflight=None,
            executor=PythonPackageExecutor(), execution_state_store=store_a,
        )
        workflow_a.execute_approved(approved, str(project_root))
        count_after_first = read_launch_count(counter)
        del store_a, workflow_a  # instance A "ends"

        store_b = SetupExecutionStateStore(storage_path)
        workflow_b = DevelopmentWorkflow(
            discovery=None, validator=None, preflight=None,
            executor=PythonPackageExecutor(), execution_state_store=store_b,
        )
        result = workflow_b.execute_approved(approved, str(project_root))

        assert result[0].success is True
        assert read_launch_count(counter) == count_after_first


class TestStaleInProgressAfterRestart:
    def test_stale_in_progress_fails_closed_and_launches_nothing(self, tmp_path, target_a):
        target, counter = target_a
        project_root = tmp_path / "project"
        project_root.mkdir()
        requirement = _requirement("req-stale")
        approved = _build_approved_plan(tmp_path, project_root, target, "proj-stale", requirement)
        storage_path = tmp_path / "exec-state.json"
        # _build_approved_plan's own Preflight call already queried the
        # target once (a real, but read-only, distribution presence
        # check) -- capture that as the baseline, not zero.
        count_before_begin = read_launch_count(counter)

        # Simulate: a prior process persisted IN_PROGRESS and then died
        # before ever launching (or finishing) the real mutation.
        store_a = SetupExecutionStateStore(storage_path)
        identity = SetupStepIdentity.for_step(str(project_root), approved.generation_id, approved.steps[0])
        store_a.begin(identity, "dead-process-owner")
        assert read_launch_count(counter) == count_before_begin

        store_b = SetupExecutionStateStore(storage_path)
        workflow_b = DevelopmentWorkflow(
            discovery=None, validator=None, preflight=None,
            executor=PythonPackageExecutor(), execution_state_store=store_b,
        )

        with pytest.raises(SetupExecutionStateError):
            workflow_b.execute_approved(approved, str(project_root))

        assert read_launch_count(counter) == count_before_begin, "no automatic replay of an uncertain attempt"
        # CLAUDE-E2E-003I: claim_or_report() deliberately does NOT mutate
        # an observed IN_PROGRESS record to recovery_required merely
        # because a second caller also observed it here -- doing so
        # would corrupt a legitimately still-active claim in a genuine
        # concurrent-process race (see TestRealCrossProcessRace). The
        # record correctly stays exactly as the original (here,
        # simulated-dead) owner left it: in_progress, unresolved.
        assert store_b.get(identity)["status"] == "in_progress"


class TestKnownFailedIsNotAutomaticallyReplayed:
    def test_failed_step_is_returned_without_relaunch(self, tmp_path, target_a):
        target, counter = target_a
        project_root = tmp_path / "project"
        project_root.mkdir()
        storage_path = tmp_path / "exec-state.json"
        store = SetupExecutionStateStore(storage_path)

        # A step that will fail: package name the local index cannot
        # resolve (no-index/find-links only serves PACKAGE_NAME).
        requirement = _requirement("req-failed")
        preflight = RequirementPreflight.check((requirement,), "proj-failed", project_root=str(project_root))
        item = ToolchainItem(
            requirement_ref=requirement.id, name="nonexistent-package-xyz",
            type=RequirementType.PYTHON_PACKAGE,
            install_method="pip install nonexistent-package-xyz",
        )
        variant = CouncilVariant(id="v1", name="v1", toolchain=(item,))
        council = CouncilResult(id="c1", project_id="proj-failed", variants=(variant,), recommendation="v1", council_complete=True)
        plan = ToolchainMaterializer().materialize(council, "proj-failed", preflight=preflight)
        approved = SetupApproval.approve(plan)
        register_setup_step_targets(
            approved, project_root,
            engineering_council_ref="c1", chairman_approval_ref="v1",
            human_approval_ref=f"setup-approval:{plan.id}:{approved.generation_id}:approved",
        )

        workflow = DevelopmentWorkflow(
            discovery=None, validator=None, preflight=None,
            executor=PythonPackageExecutor(), execution_state_store=store,
        )
        first = workflow.execute_approved(approved, str(project_root))
        assert first[0].success is False
        count_after_first_failure = read_launch_count(counter)
        assert count_after_first_failure > 0

        second = workflow.execute_approved(approved, str(project_root))

        assert second[0].success is False
        assert read_launch_count(counter) == count_after_first_failure, "FAILED must not be automatically replayed"


class TestVerificationFailureDoesNotBlindlyRepeatMutation:
    def test_success_with_failed_verification_is_not_relaunched(self, tmp_path, target_a):
        """Install succeeds but verification fails (success=False,
        verification_passed=False per ExecutionResult's own contract) --
        this is a known, terminal FAILED outcome from this store's
        perspective (ExecutionResult.success is what gates
        SUCCEEDED/FAILED), and must not be silently repeated either."""
        target, counter = target_a
        project_root = tmp_path / "project"
        project_root.mkdir()
        storage_path = tmp_path / "exec-state.json"
        store = SetupExecutionStateStore(storage_path)

        class VerifierAlwaysFails:
            def execute(self, step, project_root=None):
                from app.setup_executor import ExecutionResult
                return ExecutionResult(
                    step_id=step.id, success=False,
                    message="install succeeded but verification failed",
                    verification_passed=False,
                )

        requirement = _requirement("req-verifyfail")
        approved = _build_approved_plan(tmp_path, project_root, target, "proj-verifyfail", requirement)
        workflow = DevelopmentWorkflow(
            discovery=None, validator=None, preflight=None,
            executor=VerifierAlwaysFails(), execution_state_store=store,
        )

        first = workflow.execute_approved(approved, str(project_root))
        assert first[0].success is False

        second = workflow.execute_approved(approved, str(project_root))
        assert second[0].success is False
        assert second[0].message == first[0].message


class TestIsolation:
    def test_wrong_project_cannot_reuse_state(self, tmp_path, target_a):
        target, counter = target_a
        project_root_a = tmp_path / "project-a"
        project_root_a.mkdir()
        project_root_b = tmp_path / "project-b"
        project_root_b.mkdir()
        store = SetupExecutionStateStore(tmp_path / "exec-state.json")
        requirement = _requirement("req-isolation")

        approved_a = _build_approved_plan(tmp_path, project_root_a, target, "proj-a", requirement)
        workflow = DevelopmentWorkflow(
            discovery=None, validator=None, preflight=None,
            executor=PythonPackageExecutor(), execution_state_store=store,
        )
        workflow.execute_approved(approved_a, str(project_root_a))
        count_after_a = read_launch_count(counter)

        # B1: the artificial reuse below targets a DIFFERENT project
        # scope (project_root_b) than _build_approved_plan() registered
        # (project_root_a) -- register that scope too, so this test
        # still proves project-scoped state isolation specifically,
        # not incidentally the (already separately proven) capability
        # authorization boundary.
        register_setup_step_targets(
            approved_a, project_root_b,
            engineering_council_ref="council-1", chairman_approval_ref="variant-1",
            human_approval_ref=f"setup-approval:{approved_a.id}:{approved_a.generation_id}:approved-b",
        )

        # Same plan.id/step.id (deterministic from project_id="proj-a"
        # is different per project, but force an artificial collision
        # by reusing the SAME plan object against a DIFFERENT project
        # root -- the identity is scoped by project_root, not plan.project_id.
        result_b = workflow.execute_approved(approved_a, str(project_root_b))

        assert read_launch_count(counter) > count_after_a, (
            "a different project_root must not silently reuse project-a's SUCCEEDED state"
        )

    def test_wrong_generation_cannot_reuse_state(self, tmp_path, target_a):
        """CLAUDE-E2E-003I: plan.id is stable per project (deterministic,
        f"plan-{project_id}"), so two genuinely separate materializations
        for the SAME project produce the SAME plan.id but DIFFERENT
        generation_id values -- generation_id, not plan.id, is what
        execution-state identity is scoped by."""
        target, counter = target_a
        project_root = tmp_path / "project"
        project_root.mkdir()
        store = SetupExecutionStateStore(tmp_path / "exec-state.json")
        requirement = _requirement("req-planiso")

        preflight = RequirementPreflight.check((requirement,), "proj-planiso", project_root=str(project_root))
        item = ToolchainItem(requirement_ref=requirement.id, name=PACKAGE_NAME, type=RequirementType.PYTHON_PACKAGE, install_method=f"pip install {PACKAGE_NAME}")
        variant = CouncilVariant(id="v1", name="v1", toolchain=(item,))
        council = CouncilResult(id="c1", project_id="proj-planiso", variants=(variant,), recommendation="v1", council_complete=True)
        plan_1 = ToolchainMaterializer().materialize(council, "proj-planiso", preflight=preflight)
        plan_2 = ToolchainMaterializer().materialize(council, "proj-planiso", preflight=preflight)
        assert plan_1.id == plan_2.id, "test setup invalid: plan.id should be stable per project"
        assert plan_1.generation_id != plan_2.generation_id, (
            "test setup invalid: two separate materializations must get different generations"
        )
        approved_1 = SetupApproval.approve(plan_1)
        approved_2 = SetupApproval.approve(plan_2)
        for approved in (approved_1, approved_2):
            register_setup_step_targets(
                approved, project_root,
                engineering_council_ref="c1", chairman_approval_ref="v1",
                human_approval_ref=f"setup-approval:{approved.id}:{approved.generation_id}:approved",
            )

        workflow = DevelopmentWorkflow(
            discovery=None, validator=None, preflight=None,
            executor=PythonPackageExecutor(), execution_state_store=store,
        )
        workflow.execute_approved(approved_1, str(project_root))
        count_after_generation_1 = read_launch_count(counter)

        workflow.execute_approved(approved_2, str(project_root))

        assert read_launch_count(counter) > count_after_generation_1, (
            "a different generation_id must not silently reuse another "
            "generation's SUCCEEDED state, even for the identical plan.id"
        )

    def test_different_step_cannot_reuse_another_steps_state(self, tmp_path, target_a):
        target, counter = target_a
        project_root = tmp_path / "project"
        project_root.mkdir()
        store = SetupExecutionStateStore(tmp_path / "exec-state.json")
        requirement_1 = _requirement("req-step-1")

        preflight = RequirementPreflight.check((requirement_1,), "proj-stepiso", project_root=str(project_root))
        item_1 = ToolchainItem(requirement_ref=requirement_1.id, name=PACKAGE_NAME, type=RequirementType.PYTHON_PACKAGE, install_method=f"pip install {PACKAGE_NAME}")
        variant = CouncilVariant(id="v1", name="v1", toolchain=(item_1,))
        council = CouncilResult(id="c1", project_id="proj-stepiso", variants=(variant,), recommendation="v1", council_complete=True)
        plan = ToolchainMaterializer().materialize(council, "proj-stepiso", preflight=preflight)
        approved = SetupApproval.approve(plan)
        register_setup_step_targets(
            approved, project_root,
            engineering_council_ref="c1", chairman_approval_ref="v1",
            human_approval_ref=f"setup-approval:{plan.id}:{approved.generation_id}:approved",
        )
        workflow = DevelopmentWorkflow(
            discovery=None, validator=None, preflight=None,
            executor=PythonPackageExecutor(), execution_state_store=store,
        )
        workflow.execute_approved(approved, str(project_root))
        identity_1 = SetupStepIdentity.for_step(str(project_root), approved.generation_id, approved.steps[0])
        identity_2 = SetupStepIdentity.for_step(
            str(project_root), approved.generation_id,
            SetupStep(**{**approved.steps[0].__dict__, "id": "step-req-step-2"}),
        )
        assert store.get(identity_1) is not None
        assert store.get(identity_2) is None


class TestCentralServiceGuardIndependentOfRunId:
    """Web's HTTP boundary reuses the same run_id/session_id for a
    given project, so its own pre-existing, run-level
    WorkflowManager.begin_execution() reentry guard already blocks a
    same-session retry -- masking whether the NEW, per-step guard this
    task adds is what Web's central service itself relies on. This
    test proves the new guard directly, at the level Web's HTTP
    endpoint actually delegates to
    (ProjectSetupApplicationService.execute_approved_setup_and_development),
    using two DIFFERENT run_ids for the SAME already-succeeded plan --
    exactly what a genuinely different Web session/run for the same
    project would look like, independent of the older run-level guard.
    """

    def test_different_run_id_for_the_same_plan_does_not_relaunch(self, tmp_path, target_a):
        from app.project_setup_application import ProjectSetupApplicationService
        from app.workflow_manager import WorkflowManager

        target, counter = target_a
        project_root = tmp_path / "project"
        project_root.mkdir()
        requirement = _requirement("req-runid")
        approved = _build_approved_plan(tmp_path, project_root, target, "proj-runid", requirement)

        store = SetupExecutionStateStore(tmp_path / "exec-state.json")

        class NoOpReworkStage:
            def run(self, request):
                from types import SimpleNamespace
                from app.controlled_rework_stage import ControlledReworkResult
                from app.development_testing_stage import DevelopmentTestingResult
                testing_result = DevelopmentTestingResult(
                    development_result=None, test_changes={}, apply_result={},
                    test_result=None, testing_stage_result=SimpleNamespace(status="accepted"),
                    verification_result=None,
                )
                return ControlledReworkResult(initial_result=testing_result, rework_executed=False)

        workflow = DevelopmentWorkflow(
            discovery=None, validator=None, preflight=None,
            executor=PythonPackageExecutor(), execution_state_store=store,
            controlled_rework_stage=NoOpReworkStage(),
        )
        service = ProjectSetupApplicationService(
            development_workflow=workflow,
            workflow_manager=WorkflowManager(storage=str(tmp_path / "wf.json")),
        )

        first = service.execute_approved_setup_and_development(
            approved, "proj-runid", str(project_root), "task one", "run-1",
        )
        assert first.setup_execution_results[0].success is True
        count_after_first = read_launch_count(counter)
        assert count_after_first > 0

        second = service.execute_approved_setup_and_development(
            approved, "proj-runid", str(project_root), "task two", "run-2",
        )

        assert second.setup_execution_results[0].success is True
        assert read_launch_count(counter) == count_after_first, (
            "a genuinely different run_id for the same already-succeeded "
            "plan/step must still be protected by the new per-step guard, "
            "independent of WorkflowManager's older, run-scoped reentry check"
        )


class TestRetryGuardComposesWithPathPinning:
    """Part 12: execution-state deduplication must come AFTER/around
    the correct central authorization logic, never instead of it. This
    proves the composition survives PATH drift: a retry against an
    already-SUCCEEDED step returns the persisted result without ever
    re-invoking the executor (and therefore without ever needing to
    re-resolve or re-validate a target against a now-drifted PATH) --
    Target B is never considered, let alone substituted, on retry.
    """

    def test_retry_after_success_survives_path_drift_without_reexecuting(self, tmp_path, target_a):
        import shutil
        import sys

        target, counter = target_a
        project_root = tmp_path / "project"
        project_root.mkdir()
        requirement = _requirement("req-pathretry")
        approved = _build_approved_plan(tmp_path, project_root, target, "proj-pathretry", requirement)
        store = SetupExecutionStateStore(tmp_path / "exec-state.json")
        workflow = DevelopmentWorkflow(
            discovery=None, validator=None, preflight=None,
            executor=PythonPackageExecutor(), execution_state_store=store,
        )

        first = workflow.execute_approved(approved, str(project_root))
        assert first[0].success is True
        count_after_first = read_launch_count(counter)

        # PATH drift: Target A's directory removed; a fresh lookup
        # would now resolve a different interpreter entirely.
        prior_path = os.environ["PATH"]
        try:
            del os.environ["PATH"]
            os.environ["PATH"] = "/usr/bin:/bin"
            drifted_target = shutil.which("python") or sys.executable
            assert drifted_target != target

            second = workflow.execute_approved(approved, str(project_root))
        finally:
            os.environ["PATH"] = prior_path

        assert second[0].success is True
        assert read_launch_count(counter) == count_after_first, (
            "retry after success must not re-invoke the executor at all, "
            "so PATH drift is irrelevant to it -- Target B is never "
            "considered on retry, let alone substituted"
        )
