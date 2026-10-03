from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.dev_workflow import DevelopmentWorkflow
from app.python_package_executor import PythonPackageExecutor
from app.requirement_model import (
    RequirementActivation,
    SetupPlan,
    SetupStep,
)
from app.setup_executor import ExecutionResult
from app.workflow_plan_store import (
    WorkflowPlanStore,
    WorkflowPlanStoreError,
)


def _make_plan(
    *,
    plan_id="plan-1",
    project_id="workflow-demo",
    status="pending_approval",
):
    step = SetupStep(
        id="step-1",
        requirement_id="req-1",
        action="install",
        install_method="python_package",
        package="build",
        version=None,
        command=None,
        verification_after="import build",
        is_approved=(status == "approved"),
        setup_effect="python_package_install",
    )
    rollback_step = SetupStep(
        id="rollback-1",
        requirement_id="req-1",
        action="manual_review",
        install_method=None,
        package=None,
        version=None,
        command=None,
        verification_after=None,
        is_approved=False,
    )

    return SetupPlan(
        id=plan_id,
        project_id=project_id,
        steps=(step,),
        requires_user_approval=True,
        rollback_steps=(rollback_step,),
        warnings=("warning-1",),
        status=status,
    )


def test_save_and_load_roundtrip(tmp_path):
    store = WorkflowPlanStore(tmp_path / "plans")
    original = _make_plan()

    saved_path = store.save(original)

    assert saved_path == (
        tmp_path / "plans" / "workflow-demo" / "plan-1.json"
    )
    assert saved_path.is_file()

    loaded = store.load("workflow-demo", "plan-1")

    assert loaded == original


def test_approved_plan_roundtrip(tmp_path):
    store = WorkflowPlanStore(tmp_path / "plans")
    original = _make_plan(status="approved")

    store.save(original)

    loaded = store.load("workflow-demo", "plan-1")

    assert loaded.status == "approved"
    assert loaded.steps[0].is_approved is True


def test_save_rejects_wrong_type(tmp_path):
    store = WorkflowPlanStore(tmp_path / "plans")

    with pytest.raises(TypeError):
        store.save("not-a-plan")


def test_load_missing_plan_fails(tmp_path):
    store = WorkflowPlanStore(tmp_path / "plans")

    with pytest.raises(
        WorkflowPlanStoreError,
        match="does not exist",
    ):
        store.load("workflow-demo", "missing-plan")


def test_load_invalid_json_fails(tmp_path):
    root = Path(tmp_path) / "plans" / "workflow-demo"
    root.mkdir(parents=True)

    (root / "broken.json").write_text(
        "{not-json",
        encoding="utf-8",
    )

    store = WorkflowPlanStore(tmp_path / "plans")

    with pytest.raises(
        WorkflowPlanStoreError,
        match="Could not load setup plan",
    ):
        store.load("workflow-demo", "broken")


def test_multiple_projects_are_isolated(tmp_path):
    store = WorkflowPlanStore(tmp_path / "plans")

    first = _make_plan(
        plan_id="plan-1",
        project_id="workflow-demo",
    )
    second = _make_plan(
        plan_id="plan-1",
        project_id="another-project",
    )

    store.save(first)
    store.save(second)

    assert store.load("workflow-demo", "plan-1") == first
    assert store.load("another-project", "plan-1") == second


def test_empty_project_id_is_rejected(tmp_path):
    store = WorkflowPlanStore(tmp_path / "plans")

    plan = _make_plan(project_id="")

    with pytest.raises(
        WorkflowPlanStoreError,
        match="project_id must be a non-empty string",
    ):
        store.save(plan)


def test_requirement_activations_and_setup_effect_survive_save_and_load(tmp_path):
    """CLAUDE-E2E-001: the real productive execution path (web_api's
    execute_canonical_workflow) loads a plan via WorkflowPlanStore before
    executing it. Before this fix, requirement_activations and
    SetupStep.setup_effect were silently dropped on every such round
    trip, which is the direct, confirmed explanation for the reported
    ``requirement_activations=()`` symptom on the failed real E2E plan.
    This proves both fields -- and the nonblocking exemption they carry
    for a genuine manual_review step -- survive a real save/load cycle
    and are still correctly honored by DevelopmentWorkflow.execute_approved().
    """
    store = WorkflowPlanStore(tmp_path / "plans")

    nonblocking = RequirementActivation(
        "req-config", True, False, "development-created artifact",
    )
    blocking = RequirementActivation("req-install", True, True, "current request")
    plan = SetupPlan(
        id="plan-1", project_id="workflow-demo",
        steps=(
            SetupStep(id="step-config", requirement_id="req-config",
                      action="manual_review", is_approved=True),
            SetupStep(id="step-install", requirement_id="req-install",
                      action="install", install_method="pip", package="pkg",
                      setup_effect="python_package_install", is_approved=True),
        ),
        requires_user_approval=True,
        status="approved",
        requirement_activations=(nonblocking, blocking),
    )

    store.save(plan)
    loaded = store.load("workflow-demo", "plan-1")

    assert loaded == plan
    assert loaded.requirement_activations == (nonblocking, blocking)
    assert loaded.steps[1].setup_effect == "python_package_install"

    executor = MagicMock(spec=PythonPackageExecutor)
    executor.execute.return_value = ExecutionResult(
        step_id="step-install", success=True, message="ok",
        verification_passed=True,
    )
    workflow = DevelopmentWorkflow(
        discovery=MagicMock(), validator=MagicMock(),
        preflight=MagicMock(), planner=MagicMock(), executor=executor,
    )

    results = workflow.execute_approved(loaded)

    assert len(results) == 1
    assert results[0].step_id == "step-install"


def test_step_target_executable_survives_save_and_load(tmp_path):
    """CLAUDE-E2E-003B/003C Gap A: the resolved, generic execution-target
    identity is stamped onto SetupStep at materialization time and must
    survive the exact same save/load round trip that motivated the
    CLAUDE-E2E-001 fix -- planning and execution can be separated by a
    real persisted plan, and the target must not be lost or re-resolved
    across that boundary."""
    store = WorkflowPlanStore(tmp_path / "plans")
    step = SetupStep(
        id="step-1", requirement_id="req-1", action="install",
        install_method="python_package", package="ESPHome",
        is_approved=True, setup_effect="python_package_install",
        target_executable="/isolated/toolchain/bin/python",
    )
    plan = SetupPlan(
        id="plan-1", project_id="workflow-demo", steps=(step,),
        requires_user_approval=True, status="approved",
    )

    store.save(plan)
    loaded = store.load("workflow-demo", "plan-1")

    assert loaded == plan
    assert loaded.steps[0].target_executable == "/isolated/toolchain/bin/python"


def test_step_target_executable_compat_reads_legacy_target_python_key(tmp_path):
    """CLAUDE-E2E-003C PART 7: a plan persisted by the short-lived,
    uncommitted CLAUDE-E2E-003B format (field name "target_python"
    instead of the current "target_executable") must still load
    correctly -- there is exactly one authoritative field going
    forward, but reading the old key is a safe, documented
    compatibility fallback."""
    plans_dir = tmp_path / "plans" / "workflow-demo"
    plans_dir.mkdir(parents=True)
    legacy_plan_json = {
        "id": "plan-legacy", "project_id": "workflow-demo",
        "steps": [{
            "id": "step-1", "requirement_id": "req-1", "action": "install",
            "install_method": "python_package", "package": "ESPHome",
            "version": None, "command": None, "verification_after": None,
            "is_approved": True, "setup_effect": "python_package_install",
            "target_python": "/isolated/toolchain/bin/python",
        }],
        "requires_user_approval": True, "rollback_steps": (), "warnings": (),
        "status": "approved", "created_at": None,
        "requirement_activations": (), "deferred_requirement_ids": (),
        "unsupported_backend_effects": (), "provided_requirement_ids": (),
    }
    import json
    (plans_dir / "plan-legacy.json").write_text(json.dumps(legacy_plan_json))

    store = WorkflowPlanStore(tmp_path / "plans")
    loaded = store.load("workflow-demo", "plan-legacy")

    assert loaded.steps[0].target_executable == "/isolated/toolchain/bin/python"
