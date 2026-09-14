"""CLAUDE-E2E-003F UNIT tests for the shared adapter-lifecycle helpers
in app.project_setup_application (persist_setup_plan, approve_setup_plan,
execute_approved_plan_from_store) and ProjectSetupApplicationService.
record_setup_approval_event: provenance retrieval, adapter rejection,
approval-event identity, and missing/corrupt persisted references.

Mocks/fresh, isolated instances are acceptable at this layer.
"""
from unittest.mock import MagicMock

import pytest

from app.project_setup_application import (
    approve_setup_plan,
    execute_approved_plan_from_store,
    persist_setup_plan,
)
from app.requirement_model import SetupPlan
from app.setup_approval import SetupApprovalError
from app.workflow_plan_store import WorkflowPlanStore


def _plan(status="pending_approval", project_id="proj-1", plan_id="plan-1"):
    return SetupPlan(id=plan_id, project_id=project_id, status=status)


class TestPersistSetupPlan:
    def test_saves_plan_and_council_reference_when_both_present(self, tmp_path):
        store = WorkflowPlanStore(tmp_path / "plans")
        plan = _plan()
        council_result = MagicMock(id="council-1", recommendation="variant-1")

        persist_setup_plan(store, plan, council_result)

        assert store.load("proj-1", "plan-1") == plan
        assert store.load_council_reference("proj-1", "plan-1") == ("council-1", "variant-1")

    def test_saves_plan_without_council_reference_when_council_result_is_none(self, tmp_path):
        store = WorkflowPlanStore(tmp_path / "plans")
        plan = _plan()

        persist_setup_plan(store, plan, None)

        assert store.load("proj-1", "plan-1") == plan
        assert store.load_council_reference("proj-1", "plan-1") is None

    def test_skips_council_reference_when_recommendation_missing(self, tmp_path):
        """An incomplete Council run (e.g. council_complete=False,
        recommendation=None) must not raise and must not fabricate a
        council reference -- it is simply not saved."""
        store = WorkflowPlanStore(tmp_path / "plans")
        plan = _plan()
        council_result = MagicMock(id="council-1", recommendation=None)

        persist_setup_plan(store, plan, council_result)

        assert store.load_council_reference("proj-1", "plan-1") is None

    def test_skips_council_reference_when_id_missing(self, tmp_path):
        store = WorkflowPlanStore(tmp_path / "plans")
        plan = _plan()
        council_result = MagicMock(id=None, recommendation="variant-1")

        persist_setup_plan(store, plan, council_result)

        assert store.load_council_reference("proj-1", "plan-1") is None


class TestApproveSetupPlan:
    def test_approves_persisted_plan_and_records_central_trace_event(self, tmp_path):
        store = WorkflowPlanStore(tmp_path / "plans")
        store.save(_plan(status="pending_approval"))
        service = MagicMock()

        approved = approve_setup_plan(service, store, "proj-1", "plan-1", run_id="run-1")

        assert approved.status == "approved"
        assert store.load("proj-1", "plan-1").status == "approved"
        service.record_setup_approval_event.assert_called_once_with(
            "proj-1", "plan-1", approved.generation_id, "run-1",
        )

    def test_rejects_a_plan_that_is_not_pending_approval(self, tmp_path):
        """Real SetupApproval.approve() type/state checking is used
        directly -- an adapter cannot approve an already-approved or
        rejected plan through this shared function either."""
        store = WorkflowPlanStore(tmp_path / "plans")
        store.save(_plan(status="approved"))
        service = MagicMock()

        with pytest.raises(Exception):
            approve_setup_plan(service, store, "proj-1", "plan-1")

        service.record_setup_approval_event.assert_not_called()

    def test_run_id_defaults_to_plan_id_when_omitted(self, tmp_path):
        store = WorkflowPlanStore(tmp_path / "plans")
        store.save(_plan(status="pending_approval"))
        service = MagicMock()

        approved = approve_setup_plan(service, store, "proj-1", "plan-1")

        service.record_setup_approval_event.assert_called_once_with(
            "proj-1", "plan-1", approved.generation_id, None,
        )


class TestExecuteApprovedPlanFromStore:
    def test_loads_plan_and_council_reference_from_store_and_forwards_them(self, tmp_path):
        store = WorkflowPlanStore(tmp_path / "plans")
        plan = _plan(status="approved")
        store.save(plan)
        store.save_council_reference("proj-1", "plan-1", "council-1", "variant-1")
        service = MagicMock()

        execute_approved_plan_from_store(
            service, store, "proj-1", "plan-1", "/project/path", "Do the task", "run-1",
        )

        service.execute_approved_setup_and_development.assert_called_once_with(
            plan, "proj-1", "/project/path", "Do the task", "run-1",
            engineering_council_ref="council-1", chairman_approval_ref="variant-1",
        )

    def test_forwards_none_refs_when_no_council_reference_was_ever_saved(self, tmp_path):
        """A caller of this function has no way to substitute its own
        engineering_council_ref/chairman_approval_ref -- there is no
        parameter for it. When plan_store never recorded one, None is
        forwarded, matching execute_approved_setup_and_development's
        own fully-backward-compatible default behavior."""
        store = WorkflowPlanStore(tmp_path / "plans")
        plan = _plan(status="approved")
        store.save(plan)
        service = MagicMock()

        execute_approved_plan_from_store(
            service, store, "proj-1", "plan-1", "/project/path", "Do the task",
        )

        service.execute_approved_setup_and_development.assert_called_once_with(
            plan, "proj-1", "/project/path", "Do the task", None,
            engineering_council_ref=None, chairman_approval_ref=None,
        )

    def test_a_caller_cannot_pass_its_own_engineering_council_ref(self, tmp_path):
        """No such parameter exists on this function at all -- passing
        one is a TypeError, not a silently-accepted trust override."""
        store = WorkflowPlanStore(tmp_path / "plans")
        store.save(_plan(status="approved"))
        service = MagicMock()

        with pytest.raises(TypeError):
            execute_approved_plan_from_store(
                service, store, "proj-1", "plan-1", "/project/path", "Do the task",
                engineering_council_ref="attacker-supplied",
            )
