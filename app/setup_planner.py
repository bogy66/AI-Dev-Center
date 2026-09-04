from app.execution import is_controlled_setup_effect
from app.requirement_model import (
    RequirementType,
    PreflightResult,
    SetupPlan,
    SetupStep,
    classify_setup_effect,
)


class SetupPlanner:
    def plan(
        self,
        requirements,
        preflight_result: PreflightResult,
        project_id: str,
    ) -> SetupPlan:
        steps: list[SetupStep] = []
        warnings: list[str] = []
        activation_by_id = {
            activation.requirement_id: activation
            for activation in preflight_result.activations
        }
        deferred_ids = [
            requirement.id for requirement in preflight_result.inactive_requirements
        ]
        unsupported_effects: set[str] = set()

        for req in preflight_result.missing_requirements:
            effect = classify_setup_effect(req.type, req.name, req.install_method)
            controlled = is_controlled_setup_effect(effect)
            action = "install" if controlled else "manual_review"

            if controlled:
                package = req.name
            elif req.type == RequirementType.PYTHON_PACKAGE:
                package = req.name
            else:
                package = None

            activation = activation_by_id.get(req.id)
            if (
                activation is not None
                and not activation.blocks_current_operation
                and not controlled
            ):
                deferred_ids.append(req.id)
                continue

            if not controlled and effect != "manual" and effect is not None:
                unsupported_effects.add(effect)

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
                setup_effect=effect if effect != "manual" else None,
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
            requirement_activations=preflight_result.activations,
            deferred_requirement_ids=tuple(dict.fromkeys(deferred_ids)),
            deferred_requirements=tuple(
                requirement for requirement in preflight_result.project_requirements
                if requirement.id in set(deferred_ids)
            ),
            unsupported_backend_effects=tuple(sorted(unsupported_effects)),
        )