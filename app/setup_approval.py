from dataclasses import replace
from app.requirement_model import SetupPlan


class SetupApprovalError(Exception):
    """Raised when an invalid SetupPlan approval transition is attempted."""


class SetupApproval:
    @staticmethod
    def approve(plan: SetupPlan) -> SetupPlan:
        if not isinstance(plan, SetupPlan):
            raise TypeError("plan must be an instance of SetupPlan")
        if plan.status != "pending_approval":
            raise SetupApprovalError(
                f"Cannot approve plan with status {plan.status!r}; expected 'pending_approval'."
            )
        new_steps = tuple(
            # CLAUDE-ADC-ZIELBILD-DIFF-FIX-001 (E1): a "manual_review"
            # step is not a concrete executable setup action -- Human
            # Approval of the plan must never itself claim to have
            # approved such a step for execution. Every other action
            # (currently only "install") keeps the exact prior behavior.
            replace(step, is_approved=step.action != "manual_review")
            for step in plan.steps
        )
        return replace(plan, status="approved", steps=new_steps)

    @staticmethod
    def reject(plan: SetupPlan) -> SetupPlan:
        if not isinstance(plan, SetupPlan):
            raise TypeError("plan must be an instance of SetupPlan")
        if plan.status != "pending_approval":
            raise SetupApprovalError(
                f"Cannot reject plan with status {plan.status!r}; expected 'pending_approval'."
            )
        new_steps = tuple(
            replace(step, is_approved=False) for step in plan.steps
        )
        return replace(plan, status="rejected", steps=new_steps)
