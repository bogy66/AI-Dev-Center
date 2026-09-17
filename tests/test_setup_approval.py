from datetime import datetime
import pytest

from app.requirement_model import SetupPlan, SetupStep
from app.setup_approval import SetupApproval, SetupApprovalError


def make_step(idx: int = 1) -> SetupStep:
    return SetupStep(
        id=f"step-{idx}",
        requirement_id=f"req-{idx}",
        action="install",
        install_method="pip",
        package=f"pkg-{idx}",
        version="1.0.0",
        command=f"pip install pkg-{idx}",
        verification_after="pytest",
        is_approved=False,
    )


def make_plan(steps=None, status="pending_approval") -> SetupPlan:
    steps = steps if steps is not None else []
    return SetupPlan(
        id="plan-1",
        project_id="proj-1",
        steps=tuple(steps),
        requires_user_approval=True,
        rollback_steps=(),
        warnings=(),
        status=status,
        created_at=datetime(2025, 1, 1),
    )


def test_pending_plan_approve_sets_approved_and_steps_approved():
    plan = make_plan(steps=[make_step(1), make_step(2)])
    approved = SetupApproval.approve(plan)

    assert approved.status == "approved"
    assert all(step.is_approved for step in approved.steps)
    assert plan.status == "pending_approval"
    assert not any(step.is_approved for step in plan.steps)


def test_pending_plan_reject_sets_rejected_and_steps_not_approved():
    plan = make_plan(steps=[make_step(1), make_step(2)])
    rejected = SetupApproval.reject(plan)

    assert rejected.status == "rejected"
    assert all(not step.is_approved for step in rejected.steps)
    assert plan.status == "pending_approval"


def test_approve_approved_raises():
    plan = make_plan(status="approved")
    with pytest.raises(SetupApprovalError):
        SetupApproval.approve(plan)


def test_approve_rejected_raises():
    plan = make_plan(status="rejected")
    with pytest.raises(SetupApprovalError):
        SetupApproval.approve(plan)


def test_reject_approved_raises():
    plan = make_plan(status="approved")
    with pytest.raises(SetupApprovalError):
        SetupApproval.reject(plan)


def test_reject_rejected_raises():
    plan = make_plan(status="rejected")
    with pytest.raises(SetupApprovalError):
        SetupApproval.reject(plan)


def test_original_plan_not_mutated():
    steps = [make_step(1), make_step(2)]
    plan = make_plan(steps=steps)
    original_status = plan.status
    original_steps = plan.steps

    approved = SetupApproval.approve(plan)

    assert plan is not approved
    assert plan.status == original_status
    assert plan.steps == original_steps
    assert all(step.is_approved is False for step in plan.steps)


def test_step_parameters_unchanged_after_approve():
    step = make_step(1)
    plan = make_plan(steps=[step])
    approved = SetupApproval.approve(plan)
    new_step = approved.steps[0]

    assert new_step.id == step.id
    assert new_step.requirement_id == step.requirement_id
    assert new_step.action == step.action
    assert new_step.install_method == step.install_method
    assert new_step.package == step.package
    assert new_step.version == step.version
    assert new_step.command == step.command
    assert new_step.verification_after == step.verification_after
    assert new_step.is_approved is True
    assert step.is_approved is False


def test_multiple_steps_all_approved():
    steps = [make_step(i) for i in range(1, 5)]
    plan = make_plan(steps=steps)
    approved = SetupApproval.approve(plan)

    assert len(approved.steps) == 4
    assert all(step.is_approved for step in approved.steps)
    assert all(not step.is_approved for step in plan.steps)


def test_empty_plan_approve():
    plan = make_plan(steps=[])
    approved = SetupApproval.approve(plan)

    assert approved.status == "approved"
    assert approved.steps == ()


def test_new_plan_status_correct():
    plan = make_plan(steps=[make_step(1)])
    result = SetupApproval.approve(plan)

    assert result is not plan
    assert result.status == "approved"


def make_manual_review_step(idx: int = 1) -> SetupStep:
    return SetupStep(
        id=f"step-manual-{idx}",
        requirement_id=f"req-manual-{idx}",
        action="manual_review",
        is_approved=False,
    )


def test_approve_does_not_mark_manual_review_step_as_approved():
    """CLAUDE-ADC-ZIELBILD-DIFF-FIX-001 (E1): Human Approval of the plan
    must never falsely convert a manual/non-executable item into an
    approved executable mutation."""
    manual_step = make_manual_review_step(1)
    install_step = make_step(2)
    plan = make_plan(steps=[manual_step, install_step])

    approved = SetupApproval.approve(plan)

    approved_by_id = {step.id: step for step in approved.steps}
    assert approved_by_id[manual_step.id].is_approved is False
    assert approved_by_id[install_step.id].is_approved is True
    assert approved.status == "approved"
