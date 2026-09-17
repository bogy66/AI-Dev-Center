"""Minimal generic requirement preflight implementation."""

import shutil
import uuid

from app.python_distribution import (
    check_distribution_installed,
    is_valid_distribution_identifier,
    resolve_target_python_executable,
)
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
    def check(
        requirements, project_id: str, activations=None,
        target_executable: str | None = None, project_root: str | None = None,
    ) -> PreflightResult:
        """Run generic preflight logic over the given requirements.

        target_executable, when supplied, is the exact, already-resolved
        executable identity every PYTHON_PACKAGE requirement in this
        call is checked against (currently the only requirement type
        with an execution-target concept) — used as given, with no
        fallback substitution. When omitted, resolve_target_python_executable()
        is called exactly ONCE here, up front, and that single resolved
        value is reused for every PYTHON_PACKAGE requirement in this
        call (never re-resolved per requirement) and stamped onto each
        such requirement's own PreflightRequirementResult.target_executable
        — deliberately per-requirement, not a single value for the whole
        result, since a project can contain multiple ecosystems and a
        future non-Python requirement type would resolve and own its own
        target independently. Later stages of the same workflow/setup
        operation (materialization, installation, verification) carry
        and reuse this exact per-requirement identity instead of each
        independently re-resolving PATH at a later, possibly different,
        moment.

        project_root, when supplied, lets PYTHON_PACKAGE requirements be
        checked through the central controlled execution boundary
        (execute_controlled) — there is no direct, unconfined subprocess
        fallback of any kind. Without it (or when a requirement's technical_identity
        is not a valid, single structured distribution identifier), PYTHON_PACKAGE presence is reported as not locally
        verifiable, the same treatment already given to every other
        requirement type this function cannot safely check.
        """

        requirements_tuple = tuple(requirements)
        resolved_target_executable = target_executable or resolve_target_python_executable()
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
        already_installed = []

        for requirement in requirements_tuple:
            activation = activation_by_id[requirement.id]
            detected_version = None
            present = False
            satisfied = False
            warning = None
            target_executable_used = None

            if requirement.type == RequirementType.EXECUTABLE:
                executable = RequirementPreflight._resolvable_executable(requirement)
                install_path = shutil.which(executable)
                present = bool(install_path)
                satisfied = present
            elif requirement.type == RequirementType.PYTHON_PACKAGE:
                # Distribution-installed semantics, not import-module
                # semantics: a distribution's importable module name can
                # differ from its distribution name (PyYAML -> yaml,
                # scikit-learn -> sklearn, beautifulsoup4 -> bs4), so
                # find_spec(requirement.name) is not a valid presence
                # test. This is the same central, target-Python-aware
                # distribution check PythonPackageExecutor's own
                # post-install verification uses, always routed through
                # the central controlled execution boundary.
                #
                # Only explicit Requirement-side distribution identity is evidence.
                if project_root is None or not is_valid_distribution_identifier(
                    requirement.technical_identity,
                ):
                    warning = RequirementPreflight.NOT_LOCALLY_VERIFIABLE_WARNING
                else:
                    check_result = check_distribution_installed(
                        requirement.technical_identity, resolved_target_executable,
                        project_root=project_root,
                    )
                    present = check_result.installed
                    satisfied = present
                    detected_version = check_result.version
                    target_executable_used = resolved_target_executable
                    if not check_result.target_python_available:
                        warning = RequirementPreflight.NOT_LOCALLY_VERIFIABLE_WARNING
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
                    target_executable=target_executable_used,
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
            elif satisfied:
                # CLAUDE-ADC-ZIELBILD-DIFF-FIX-001 (A5): a requirement
                # Preflight found satisfied is only evidence for the
                # exact target this check ran against (PreflightRequirementResult.
                # target_executable, above) -- never proof that a
                # candidate targeting a DIFFERENT environment (e.g. a
                # "venv" candidate, when this check ran against the
                # host interpreter) is also satisfied. Recording it here
                # lets S2.3 (app.engineering_decision) decide, per
                # candidate, whether that evidence is actually target-
                # bound before treating the requirement as non-binding.
                already_installed.append(requirement)

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
            already_installed=tuple(already_installed),
            warnings=warnings,
            activations=normalized_activations,
            inactive_requirements=tuple(inactive_requirements),
            project_requirements=requirements_tuple,
        )
