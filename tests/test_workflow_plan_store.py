from pathlib import Path

import pytest

from app.requirement_model import SetupPlan, SetupStep
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
    )

    return SetupPlan(
        id=plan_id,
        project_id=project_id,
        steps=(step,),
        requires_user_approval=True,
        rollback_steps=("rollback-1",),
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
