from app.requirement_model import Requirement, RequirementType, PreflightResult, SetupPlan, SetupStep


class SetupPlanner:
    def plan(
        self,
        requirements,
        preflight_result: PreflightResult,
        project_id: str,
    ) -> SetupPlan:
        steps: list[SetupStep] = []
        warnings: list[str] = []

        for req in preflight_result.missing_requirements:
            is_python_package = req.type == RequirementType.PYTHON_PACKAGE
            has_package = bool(req.name and req.name.strip())
            has_install_method = bool(
                req.install_method and req.install_method.strip()
            )

            if is_python_package and has_package and has_install_method:
                action = "install"
                package = req.name
            else:
                action = "manual_review"
                package = (
                    req.name
                    if is_python_package
                    else None
                )

            step = SetupStep(
                id=f"step-{req.id}",
                requirement_id=req.id,
                action=action,
                install_method=req.install_method,
                package=package,
                version=req.required_version,
                command=None,
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
