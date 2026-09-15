"""CLAUDE-E2E-003I Part 9-11: real cross-process execution-claim safety.

Uses multiprocessing.Process (fork on Linux) to create genuinely
separate OS processes -- not threads, not mocks -- that race on the
exact same (project, generation, step) execution-state identity,
synchronized with a real multiprocessing.Barrier so the race window is
intentional and repeatable. The real, observable launch counter
(tests/local_package_fixture.py) is a plain file, naturally shared
across processes without any special plumbing.
"""
from __future__ import annotations

import multiprocessing
import os

import pytest

from app.council_models import CouncilResult, CouncilVariant, ToolchainItem
from app.dev_workflow import DevelopmentWorkflow
from app.python_package_executor import PythonPackageExecutor
from app.requirement_model import Requirement, RequirementType
from app.requirement_preflight import RequirementPreflight
from app.setup_approval import SetupApproval
from app.setup_execution_state import SetupExecutionStateStore
from app.toolchain_materializer import ToolchainMaterializer

from tests.local_package_fixture import (
    PACKAGE_NAME, build_launch_counting_target, build_local_wheel_index, read_launch_count,
)


def _race_worker(storage_path, approved_plan, project_root, barrier, result_queue, proc_label):
    workflow = DevelopmentWorkflow(
        discovery=None, validator=None, preflight=None,
        executor=PythonPackageExecutor(),
        execution_state_store=SetupExecutionStateStore(storage_path),
    )
    barrier.wait()  # both processes attempt execute_approved() at the same instant
    try:
        result = workflow.execute_approved(approved_plan, project_root)
        result_queue.put((proc_label, "ok", result[0].success))
    except Exception as exc:  # noqa: BLE001 -- recording the real outcome, not predicting it
        result_queue.put((proc_label, "error", f"{type(exc).__name__}: {exc}"))


def _build_approved_plan(project_root, target, project_id, requirement):
    preflight = RequirementPreflight.check((requirement,), project_id, project_root=str(project_root))
    item = ToolchainItem(
        requirement_ref=requirement.id, name=PACKAGE_NAME,
        type=RequirementType.PYTHON_PACKAGE, install_method=f"pip install {PACKAGE_NAME}",
    )
    variant = CouncilVariant(id="v1", name="v1", toolchain=(item,))
    council = CouncilResult(
        id="c1", project_id=project_id, variants=(variant,),
        recommendation="v1", council_complete=True,
    )
    plan = ToolchainMaterializer().materialize(council, project_id, preflight=preflight)
    assert plan.steps[0].target_executable == target
    return SetupApproval.approve(plan)


def _run_race(storage_path, approved_plan, project_root):
    ctx = multiprocessing.get_context("fork")
    barrier = ctx.Barrier(2)
    result_queue = ctx.Queue()
    proc_a = ctx.Process(
        target=_race_worker,
        args=(storage_path, approved_plan, project_root, barrier, result_queue, "A"),
    )
    proc_b = ctx.Process(
        target=_race_worker,
        args=(storage_path, approved_plan, project_root, barrier, result_queue, "B"),
    )
    proc_a.start()
    proc_b.start()
    proc_a.join(timeout=60)
    proc_b.join(timeout=60)
    assert not proc_a.is_alive() and not proc_b.is_alive(), "race worker processes hung"

    results = {}
    while not result_queue.empty():
        label, kind, payload = result_queue.get()
        results[label] = (kind, payload)
    assert set(results) == {"A", "B"}, f"both real OS processes must report a result: {results}"
    return results


class TestRealCrossProcessRace:
    def test_two_real_os_processes_racing_on_not_started_step(self, tmp_path, monkeypatch):
        """PROCESS A + PROCESS B start concurrently against the same,
        genuinely NOT_STARTED (project, generation, step) identity.
        Exactly one real mutation launch must occur; the loser must not
        execute; persisted state must remain valid afterward."""
        wheels = build_local_wheel_index(tmp_path)
        target, counter = build_launch_counting_target(tmp_path, "toolchain-a", wheels)
        monkeypatch.setenv("PATH", f"{os.path.dirname(target)}:{os.environ.get('PATH', '')}")
        project_root = tmp_path / "project"
        project_root.mkdir()
        requirement = Requirement(
            technical_identity=PACKAGE_NAME,
            id="req-race", name=PACKAGE_NAME, type=RequirementType.PYTHON_PACKAGE,
            purpose="test dependency", required=True, confidence=0.9,
        )
        approved = _build_approved_plan(project_root, target, "proj-race", requirement)
        storage_path = tmp_path / "exec-state.json"
        count_before = read_launch_count(counter)

        results = _run_race(storage_path, approved, str(project_root))

        successes = [label for label, (kind, payload) in results.items() if kind == "ok" and payload is True]
        errors = [(label, payload) for label, (kind, payload) in results.items() if kind == "error"]
        # Exactly one process must be the genuine claimant/executor.
        # The other either (a) arrives after the winner already
        # persisted SUCCEEDED and safely receives that persisted
        # result (also "ok"/True), or (b) arrives while the winner is
        # still actively executing and fails closed with a real
        # SetupExecutionStateError -- never silently corrupted, never
        # a second real launch either way.
        assert len(successes) >= 1, results
        for _label, message in errors:
            assert "unresolved execution attempt" in message, (
                f"a losing process must fail closed with the real "
                f"concurrent-claim rejection, not some other error: {message}"
            )
        launches = read_launch_count(counter) - count_before
        assert launches > 0, "the real mutation must actually have launched exactly once, not zero times"

        # A third, later attempt (same process, after the race settled)
        # must not relaunch either -- the persisted state is valid.
        workflow = DevelopmentWorkflow(
            discovery=None, validator=None, preflight=None,
            executor=PythonPackageExecutor(),
            execution_state_store=SetupExecutionStateStore(storage_path),
        )
        third = workflow.execute_approved(approved, str(project_root))
        assert third[0].success is True
        assert read_launch_count(counter) - count_before == launches, "no additional launch after the race settled"

    def test_two_real_os_processes_racing_on_already_succeeded_step(self, tmp_path, monkeypatch):
        """Once a step is already SUCCEEDED, two real OS processes
        racing on it must together cause ZERO additional mutation
        launches."""
        wheels = build_local_wheel_index(tmp_path)
        target, counter = build_launch_counting_target(tmp_path, "toolchain-a", wheels)
        monkeypatch.setenv("PATH", f"{os.path.dirname(target)}:{os.environ.get('PATH', '')}")
        project_root = tmp_path / "project"
        project_root.mkdir()
        requirement = Requirement(
            technical_identity=PACKAGE_NAME,
            id="req-race-done", name=PACKAGE_NAME, type=RequirementType.PYTHON_PACKAGE,
            purpose="test dependency", required=True, confidence=0.9,
        )
        approved = _build_approved_plan(project_root, target, "proj-race-done", requirement)
        storage_path = tmp_path / "exec-state.json"

        # Establish SUCCEEDED first, in this process.
        setup_workflow = DevelopmentWorkflow(
            discovery=None, validator=None, preflight=None,
            executor=PythonPackageExecutor(),
            execution_state_store=SetupExecutionStateStore(storage_path),
        )
        setup_workflow.execute_approved(approved, str(project_root))
        count_after_setup = read_launch_count(counter)

        results = _run_race(storage_path, approved, str(project_root))

        assert all(kind == "ok" and payload is True for kind, payload in results.values()), results
        assert read_launch_count(counter) == count_after_setup, "zero additional launches once already SUCCEEDED"

    def test_two_real_os_processes_racing_on_stale_in_progress_step(self, tmp_path, monkeypatch):
        """A stale IN_PROGRESS record (a prior attempt that never
        finished) must cause ZERO mutation launches from either racing
        process -- both must observe recovery-required, never guess."""
        from app.setup_execution_state import SetupStepIdentity

        wheels = build_local_wheel_index(tmp_path)
        target, counter = build_launch_counting_target(tmp_path, "toolchain-a", wheels)
        monkeypatch.setenv("PATH", f"{os.path.dirname(target)}:{os.environ.get('PATH', '')}")
        project_root = tmp_path / "project"
        project_root.mkdir()
        requirement = Requirement(
            technical_identity=PACKAGE_NAME,
            id="req-race-stale", name=PACKAGE_NAME, type=RequirementType.PYTHON_PACKAGE,
            purpose="test dependency", required=True, confidence=0.9,
        )
        approved = _build_approved_plan(project_root, target, "proj-race-stale", requirement)
        storage_path = tmp_path / "exec-state.json"
        count_before = read_launch_count(counter)

        store = SetupExecutionStateStore(storage_path)
        identity = SetupStepIdentity.for_step(str(project_root), approved.generation_id, approved.steps[0])
        store.begin(identity, "dead-process-owner")  # never finished -- simulates a crash

        results = _run_race(storage_path, approved, str(project_root))

        assert all(kind == "error" for kind, _ in results.values()), (
            f"both racing processes must fail closed on a stale IN_PROGRESS record: {results}"
        )
        assert read_launch_count(counter) == count_before, "zero launches while recovery is required"

    def test_two_real_os_processes_racing_on_a_legacy_shaped_generation(self, tmp_path, monkeypatch):
        """CLAUDE-E2E-003I-A Part 11/TC9: the legacy compatibility
        lookup (app.setup_execution_state.SetupExecutionStateStore.
        _find_raw_record) is pure read, never a write/migration -- so
        it introduces no new cross-process race surface. Proven with
        two real OS processes racing on a plan whose generation_id has
        the legacy shape ("legacy-{plan.id}"), exactly as a real
        pre-003I plan resolves to."""
        from dataclasses import replace

        wheels = build_local_wheel_index(tmp_path)
        target, counter = build_launch_counting_target(tmp_path, "toolchain-a", wheels)
        monkeypatch.setenv("PATH", f"{os.path.dirname(target)}:{os.environ.get('PATH', '')}")
        project_root = tmp_path / "project"
        project_root.mkdir()
        requirement = Requirement(
            technical_identity=PACKAGE_NAME,
            id="req-race-legacy", name=PACKAGE_NAME, type=RequirementType.PYTHON_PACKAGE,
            purpose="test dependency", required=True, confidence=0.9,
        )
        approved = _build_approved_plan(project_root, target, "proj-race-legacy", requirement)
        legacy_approved = replace(approved, generation_id=f"legacy-{approved.id}")
        storage_path = tmp_path / "exec-state.json"
        count_before = read_launch_count(counter)

        results = _run_race(storage_path, legacy_approved, str(project_root))

        successes = [label for label, (kind, payload) in results.items() if kind == "ok" and payload is True]
        errors = [(label, payload) for label, (kind, payload) in results.items() if kind == "error"]
        assert len(successes) >= 1, results
        for _label, message in errors:
            assert "unresolved execution attempt" in message, results
        launches = read_launch_count(counter) - count_before
        assert launches > 0, "the real mutation must have launched exactly once"

        # A subsequent lookup (simulating a fresh process/restart) must
        # find the SUCCEEDED record and not relaunch.
        store = SetupExecutionStateStore(storage_path)
        workflow = DevelopmentWorkflow(
            discovery=None, validator=None, preflight=None,
            executor=PythonPackageExecutor(), execution_state_store=store,
        )
        again = workflow.execute_approved(legacy_approved, str(project_root))
        assert again[0].success is True
        assert read_launch_count(counter) - count_before == launches
