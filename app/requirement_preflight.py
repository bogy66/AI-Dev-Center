"""Minimal generic requirement preflight implementation."""

import importlib.metadata
import importlib.util
import shutil
import uuid

from app.requirement_model import (
    PreflightRequirementResult,
    PreflightResult,
    Requirement,
    RequirementType,
    normalize_requirement_activations,
)


class RequirementPreflight:
    """Minimal generic requirement preflight.

    This version checks locally verifiable requirement types
    (EXECUTABLE, PYTHON_PACKAGE, and SYSTEM_PACKAGE). EXECUTABLE and
    SYSTEM_PACKAGE requirements prefer a structured verification_executable
    over the human-readable name for deterministic PATH resolution. Other
    types remain represented as not locally verifiable; explicit per-workflow
    activation decides whether their absence blocks the current operation.
    """

    UNSUPPORTED_WARNING = "requirement type verification not implemented"
    NOT_LOCALLY_VERIFIABLE_WARNING = "requirement type not locally verifiable"
    VERSION_CONSTRAINT_WARNING = "version constraint not evaluated"

    @staticmethod
    def _resolvable_executable(requirement) -> str | None:
        """Return the executable identity to resolve via shutil.which."""
        if requirement.verification_executable:
            return requirement.verification_executable
        return requirement.name

    @staticmethod
    def check(requirements, project_id: str, activations=None) -> PreflightResult:
        """Run generic preflight logic over the given requirements."""

        requirements_tuple = tuple(requirements)
        explicit_activation = activations is not None
        normalized_activations = normalize_requirement_activations(
            requirements_tuple, activations,
        )
        activation_by_id = {
            activation.requirement_id: activation
            for activation in normalized_activations
        }

        results = []
        missing_requirements = []
        inactive_requirements = []

        for requirement in requirements_tuple:
            activation = activation_by_id[requirement.id]
            detected_version = None
            present = False
            satisfied = False
            warning = None

            if requirement.type == RequirementType.EXECUTABLE:
                executable = RequirementPreflight._resolvable_executable(requirement)
                install_path = shutil.which(executable)
                present = bool(install_path)
                satisfied = present
            elif requirement.type == RequirementType.PYTHON_PACKAGE:
                try:
                    spec = importlib.util.find_spec(requirement.name)
                except Exception:
                    spec = None

                present = spec is not None
                satisfied = present

                if present:
                    try:
                        detected_version = importlib.metadata.version(
                            requirement.name
                        )
                    except Exception:
                        detected_version = None
            elif requirement.type == RequirementType.SYSTEM_PACKAGE:
                executable = RequirementPreflight._resolvable_executable(requirement)
                install_path = shutil.which(executable)
                if install_path:
                    present = True
                    satisfied = True
                else:
                    warning = RequirementPreflight.NOT_LOCALLY_VERIFIABLE_WARNING
            elif requirement.type == RequirementType.VERSION_CONSTRAINT:
                warning = RequirementPreflight.VERSION_CONSTRAINT_WARNING
            else:
                warning = RequirementPreflight.NOT_LOCALLY_VERIFIABLE_WARNING

            results.append(
                PreflightRequirementResult(
                    requirement_id=requirement.id,
                    present=present,
                    detected_version=detected_version,
                    satisfied=satisfied,
                    warning=warning,
                    active=activation.active,
                    blocks_current_operation=activation.blocks_current_operation,
                )
            )

            if not activation.active:
                inactive_requirements.append(requirement)
            elif not satisfied and (
                explicit_activation
                or (
                    requirement.required
                    and requirement.type in (
                        RequirementType.EXECUTABLE,
                        RequirementType.PYTHON_PACKAGE,
                    )
                )
            ):
                missing_requirements.append(requirement)

        blocking_ids = {
            activation.requirement_id
            for activation in normalized_activations
            if activation.blocks_current_operation
        }
        overall_ready = not any(
            requirement.id in blocking_ids for requirement in missing_requirements
        )

        # Collect all non‑empty warnings from the per‑requirement results.
        warnings = tuple(
            result.warning
            for result in results
            if result.warning
        )

        return PreflightResult(
            id=str(uuid.uuid4()),
            project_id=project_id,
            overall_ready=overall_ready,
            results=tuple(results),
            missing_requirements=tuple(missing_requirements),
            already_installed=tuple(),
            warnings=warnings,
            activations=normalized_activations,
            inactive_requirements=tuple(inactive_requirements),
            project_requirements=requirements_tuple,
        )
