from app.requirement_model import Requirement, RequirementType, SetupStep, SetupPlan, Status


class SetupPlanner:
    """Stack‑neutral planner that produces a SetupPlan from Requirement objects.

    The planner contains no hard‑coded package names, framework names,
    install commands, or stack‑specific rules.  It uses exactly the data
    provided by each Requirement to decide whether a setup step should be
    created and how it should look.
    """

    _METADATA_INSTALL_KEYS = (
        "install_method",
        "command",
        "setup_command",
    )

    def _effective_install_method(self, requirement: Requirement):
        """Return the install method that should be used for this requirement.

        The primary source is Requirement.install_method.  If that is missing,
        the planner may consult Requirement.metadata for additional install
        information that came with the Requirement itself.  No command is ever
        invented by the planner.
        """
        if requirement.install_method:
            return requirement.install_method

        for key in self._METADATA_INSTALL_KEYS:
            value = requirement.metadata.get(key)
            if value:
                return str(value)

        return None

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
            A SetupPlan containing one step per required and not-yet-installed
            Requirement.  Optional and already satisfied requirements are
            intentionally skipped.
        """
        steps: list[SetupStep] = []
        warnings: list[str] = []

        for req in requirements:
            # Already installed/verified requirements do not need a setup step.
            if req.status in (Status.INSTALLED, Status.VERIFIED):
                continue

            # Only required requirements are installed automatically.
            # Optional requirements are not turned into automatic setup steps.
            if not req.required:
                continue

            method = self._effective_install_method(req)

            if method:
                action = method
            else:
                action = f"No install method defined for '{req.name}'."
                warnings.append(
                    f"Requirement '{req.name}' is required but has no install method."
                )

            step = SetupStep(
                id=f"step-{req.id}",
                requirement_id=req.id,
                action=action,
                install_method=method,
                package=req.name,
                version=req.required_version,
                command=method,
                verification_after=req.verification_method,
                is_approved=False,
            )
            steps.append(step)

        return SetupPlan(
            id=f"plan-{project_id}",
            project_id=project_id,
            steps=tuple(steps),
            requires_user_approval=True,
            rollback_steps=(),
            warnings=tuple(warnings),
            status="pending_approval",
        )
