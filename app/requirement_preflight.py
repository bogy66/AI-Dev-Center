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
)


class RequirementPreflight:
    """Minimal generic requirement preflight.

    This version checks locally verifiable requirement types
    (EXECUTABLE and PYTHON_PACKAGE). Types that cannot be verified locally
    are reported as not present/not satisfied but do not affect overall
    readiness or missing requirements.
    """

    UNSUPPORTED_WARNING = "requirement type verification not implemented"
    NOT_LOCALLY_VERIFIABLE_WARNING = "requirement type not locally verifiable"
    VERSION_CONSTRAINT_WARNING = "version constraint not evaluated"

    @staticmethod
    def check(requirements, project_id: str) -> PreflightResult:
        """Run generic preflight logic over the given requirements."""

        requirements_tuple = tuple(requirements)

        results = []
        missing_requirements = []

        for requirement in requirements_tuple:
            detected_version = None
            present = False
            satisfied = False
            warning = None

            if requirement.type == RequirementType.EXECUTABLE:
                install_path = shutil.which(requirement.name)
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
                )
            )

            # Only locally checkable, required, and not satisfied requirements
            # contribute to missing_requirements.
            if (
                requirement.type in (
                    RequirementType.EXECUTABLE,
                    RequirementType.PYTHON_PACKAGE,
                )
                and requirement.required
                and not satisfied
            ):
                missing_requirements.append(requirement)

        overall_ready = not missing_requirements

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
        )
