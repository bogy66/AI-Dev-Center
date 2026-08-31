from app.council_models import CouncilResult, CouncilVariant, ToolchainItem
from app.requirement_model import RequirementType, SetupPlan, SetupStep


class ToolchainMaterializationError(Exception):
    """Raised when Council output cannot be safely materialized."""


class ToolchainMaterializer:
    """Convert the recommended Council variant into a safe SetupPlan."""

    def materialize(
        self,
        council_result: CouncilResult,
        project_id: str,
    ) -> SetupPlan:
        if not council_result.council_complete:
            raise ToolchainMaterializationError(
                "Council result is incomplete and cannot be materialized."
            )

        recommendation = council_result.recommendation
        if not recommendation:
            raise ToolchainMaterializationError(
                "Council result does not contain a recommendation."
            )

        variant = self._find_recommended_variant(
            council_result,
            recommendation,
        )

        steps = tuple(
            step
            for item in variant.toolchain
            if item.state != "already_installed"
            for step in (self._materialize_item(item),)
        )

        return SetupPlan(
            id=f"plan-{project_id}",
            project_id=project_id,
            steps=steps,
            requires_user_approval=True,
            rollback_steps=(),
            warnings=(),
            status="pending_approval",
        )

    def _find_recommended_variant(
        self,
        council_result: CouncilResult,
        recommendation: str,
    ) -> CouncilVariant:
        for variant in council_result.variants:
            if variant.id == recommendation:
                return variant

        raise ToolchainMaterializationError(
            f"Recommended Council variant not found: {recommendation}"
        )

    def _materialize_item(self, item: ToolchainItem) -> SetupStep:
        is_python_package = item.type == RequirementType.PYTHON_PACKAGE
        has_package = bool(item.name and item.name.strip())
        has_install_method = bool(
            item.install_method and item.install_method.strip()
        )

        if is_python_package and has_package and has_install_method:
            action = "install"
            package = item.name
        else:
            action = "manual_review"
            package = item.name if is_python_package else None

        return SetupStep(
            id=f"step-{item.requirement_ref}",
            requirement_id=item.requirement_ref,
            action=action,
            install_method=item.install_method,
            package=package,
            version=item.version,
            command=None,
            verification_after=None,
            is_approved=False,
        )
