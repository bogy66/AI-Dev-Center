from dataclasses import dataclass, field
from datetime import datetime
from app.requirement_model import Requirement, SetupStep, SetupPlan


class SetupPlanner:
    """Stack‑neutral planner that produces a SetupPlan from a list of
    Requirement objects.

    The planner does **not** contain any knowledge of specific packages,
    frameworks, or installation commands.  It reads *only* the data
    provided by each Requirement (name, type, required, required_version,
    install_method, verification_method, metadata) and translates it into
    SetupStep objects without inventing commands.
    """

    def plan(
        self,
        requirements: list[Requirement],
        project_id: str = "",
    ) -> SetupPlan:
        """Return a SetupPlan built solely from the given Requirement list.

        Parameters:
            requirements: The requirements that should be turned into a plan.
            project_id: Identifier used for the generated SetupPlan.id.

        Returns:
            A SetupPlan containing one step per input Requirement.
        """
        steps: list[SetupStep] = []
        warnings: list[str] = []

        for req in requirements:
            # Determine the action text.
            action_text = ""
            if req.install_method:
                # Transparently use whatever install_method the
                # requirement specifies.  The planner does not validate
                # it and does not add anything on its own.
                action_text = req.install_method
            else:
                # No install method → no automatic action.
                action_text = (
                    f"No install method defined for '{req.name}'."
                )

            # Determine verification after install.
            verification_after = None
            if req.verification_method:
                verification_after = req.verification_method

            # Build the step using the data from the Requirement.
            step = SetupStep(
                id=f"step-{req.id}",
                requirement_id=req.id,
                action=action_text,
                install_method=req.install_method,
                package=req.name if req.type in ("python_package", "system_package") else None,
                version=req.required_version,
                command=req.install_method,  # command equals install_method when available
                verification_after=verification_after,
                is_approved=False,
            )
            steps.append(step)

            # If something that is required has no install method, add a
            # warning so that callers are informed.
            if req.required and not req.install_method:
                warnings.append(
                    f"Requirement '{req.name}' is required but has no install method."
                )

        plan = SetupPlan(
            id=f"plan-{project_id}",
            project_id=project_id,
            steps=tuple(steps),
            requires_user_approval=True,
            rollback_steps=(),  # no rollback information available at this stage
            warnings=tuple(warnings),
            status="pending_approval",
        )
        return plan
