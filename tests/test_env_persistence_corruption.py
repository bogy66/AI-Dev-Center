"""Fail-closed parsing contracts for persisted plan authorization state."""
from __future__ import annotations

import pytest


def test_workflow_plan_store_corruption_is_not_treated_as_missing_plan(tmp_path):
    from app.requirement_model import SetupPlan
    from app.workflow_plan_store import WorkflowPlanStore, WorkflowPlanStoreError

    store = WorkflowPlanStore(tmp_path / "plans")
    plan = SetupPlan(id="plan-corrupt", project_id="project")
    path = store.save(plan)
    path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(WorkflowPlanStoreError, match="Could not load setup plan"):
        store.load("project", "plan-corrupt")


def test_approved_plan_content_corruption_is_not_treated_as_unapproved(tmp_path):
    from app.approved_plan_content import ApprovedPlanContentError, ApprovedPlanContentStore

    path = tmp_path / "approved-content.json"
    path.write_text("{not valid json", encoding="utf-8")
    store = ApprovedPlanContentStore(path)

    with pytest.raises(ApprovedPlanContentError, match="corrupt or unreadable"):
        store._load_raw()  # noqa: SLF001 - the store's defined parsing boundary
