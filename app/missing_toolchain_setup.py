"""Central, approval-gated bridge from TOOL_UNAVAILABLE to verification retry."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import shutil

from app.council_models import CouncilResult
from app.engineering_decision import EngineeringDecision
from app.requirement_model import RequirementType, SetupPlan, SetupStep
from app.setup_executor import ExecutionResult
from app.verification import TOOL_UNAVAILABLE, VerificationPlan, VerificationResult, VerificationStep


class MissingToolchainSetupError(Exception):
    pass


@dataclass(frozen=True)
class MissingToolchainSetupRequest:
    project_id: str
    project_root: str
    toolchain: str
    operation_type: str
    council_result: CouncilResult
    verification_plan: VerificationPlan
    verification_result: VerificationResult
    platform: str | None = None
    # CLAUDE-ADC-ZIELBILD-DIFF-FIX-001 (A4): the already-resolved S2
    # EngineeringDecision the original S2->S3 handoff selected (Chairman
    # recommendation, explicit human override, or sole admissible
    # candidate) -- optional and additive so every existing caller that
    # constructs this request with only `council_result` keeps working
    # unchanged. When supplied, prepare_missing_toolchain_setup() below
    # materializes THIS exact already-selected variant
    # (ToolchainMaterializer.materialize_decision()) instead of
    # re-running S2 selection from `council_result` alone -- S3.5
    # recovery must never repeat or reinterpret S2 selection, and a
    # human's explicit choice of a non-recommended-but-admissible
    # variant must never be silently replaced by the Chairman's own
    # recommendation during recovery.
    engineering_decision: EngineeringDecision | None = None
    # IF_REQ_037: the requirement_ref of the selected-variant ToolchainItem
    # that provisions `toolchain` (an executable/tool identity), as
    # established by correlate_provisioning_requirement(). Optional and
    # additive; when omitted, prepare_missing_toolchain_setup() derives it
    # through that same correlation and fails closed if it cannot.
    provisioning_requirement_ref: str | None = None
    # The established target executable S5 verified through (IF_REQ_038).
    # The one-shot re-verification retry re-enters exactly this target; a
    # recovery without it can never be retried on the host.
    verification_target: str | None = None


@dataclass(frozen=True)
class MissingToolchainSetupResult:
    plan_id: str
    status: str
    setup_result: ExecutionResult | None = None
    verification_result: VerificationResult | None = None
    blockers: tuple[str, ...] = ()


def already_available_setup_result(step_id: str) -> ExecutionResult:
    """Return the existing setup execution contract for a safe no-op."""
    return ExecutionResult(
        step_id=step_id,
        success=True,
        message="toolchain already available",
        verification_passed=True,
    )


@dataclass(frozen=True)
class StructuredInstallerRegistration:
    install_method: str
    executor: object
    availability_checker: object = shutil.which
    # Optional installer-specific, target-aware checker `(toolchain, target)
    # -> path | None`. Without one, a target-bound check uses the generic
    # target-environment lookup.
    target_availability_checker: object | None = None

    def is_available(self, toolchain: str, target_executable: str | None = None) -> bool:
        """Is `toolchain` available? With a selected execution target, ONLY
        that target's own environment counts: detection, approval and
        execution refer to the same target, and a host PATH hit for the same
        name is never accepted as a substitute (unknown/unusable target or
        a tool absent there -> not available). Without a target (a setup
        effect that has no execution-target concept) the host checker
        applies unchanged."""
        if target_executable:
            if self.target_availability_checker is not None:
                return self.target_availability_checker(toolchain, target_executable) is not None
            from app.execution import resolve_tool_in_target
            return resolve_tool_in_target(target_executable, toolchain) is not None
        return self.availability_checker(toolchain) is not None


class StructuredInstallerRegistry:
    """Trusted installer implementations; registrations contain no command argv."""
    def __init__(self):
        self._installers: dict[str, StructuredInstallerRegistration] = {}

    def register(self, registration: StructuredInstallerRegistration) -> None:
        if not registration.install_method or registration.install_method in self._installers:
            raise ValueError("Installer method is empty or already registered")
        self._installers[registration.install_method] = registration

    def get(self, install_method: str) -> StructuredInstallerRegistration | None:
        return self._installers.get(install_method)

    def resolve(self, step: SetupStep) -> StructuredInstallerRegistration | None:
        """IF_REQ_037: resolve a SetupStep to its registered installer.

        A controlled setup_effect resolves only through the central
        resolve_structured_installer_identity() contract, so every
        accepted install_method representation reaches the same installer
        and a rejected one reaches none. A step without a setup_effect
        (legacy shape) matches only an installer registered under exactly
        its install_method; nothing is normalized for it."""
        from app.execution import resolve_structured_installer_identity
        if step.setup_effect is not None:
            identity = resolve_structured_installer_identity(
                step.setup_effect, step.install_method, step.package,
            )
            return self._installers.get(identity) if identity else None
        return self._installers.get(step.install_method or "")


# Requirement types whose technical_identity is an executable/tool
# identity (see ToolchainItem's docstring) -- never a package identity.
_EXECUTABLE_IDENTITY_TYPES = frozenset({
    RequirementType.EXECUTABLE, RequirementType.TOOLCHAIN,
    RequirementType.SDK, RequirementType.FLASHER,
})


def correlate_provisioning_requirement(variant, tool_identity: str) -> str:
    """IF_REQ_037: correlate an unavailable executable/tool identity with
    the requirement_ref of the selected-variant ToolchainItem that
    provisions it.

    Only explicit relations count: an executable-kind item whose
    technical_identity equals `tool_identity` exactly, then its declared
    `provided_by` relation (validated against the current requirements
    by the Council producer) to the providing item. A package item is
    never matched on its package identity, so package == executable is
    never assumed. Missing or ambiguous correlation raises
    MissingToolchainSetupError."""
    if not isinstance(tool_identity, str) or not tool_identity.strip():
        raise MissingToolchainSetupError("Unavailable tool identity is missing")
    toolchain = tuple(getattr(variant, "toolchain", ()) or ())
    matches = [
        item for item in toolchain
        if item.type in _EXECUTABLE_IDENTITY_TYPES and item.technical_identity == tool_identity
    ]
    if not matches:
        raise MissingToolchainSetupError(
            f"No selected ToolchainItem declares executable identity '{tool_identity}'"
        )
    if len(matches) > 1:
        raise MissingToolchainSetupError(
            f"Executable identity '{tool_identity}' is declared by several ToolchainItems"
        )
    item = matches[0]
    seen = {item.requirement_ref}
    while item.provided_by:
        providers = [p for p in toolchain if p.requirement_ref == item.provided_by]
        if len(providers) != 1 or providers[0].requirement_ref in seen:
            raise MissingToolchainSetupError(
                f"provided_by relation of '{item.requirement_ref}' does not resolve "
                "to exactly one non-cyclic ToolchainItem"
            )
        item = providers[0]
        seen.add(item.requirement_ref)
    return item.requirement_ref


def serialize_setup_plan(plan: SetupPlan) -> dict:
    return {
        "id": plan.id, "project_id": plan.project_id, "status": plan.status,
        "generation_id": plan.generation_id,
        "requires_user_approval": plan.requires_user_approval,
        "steps": [asdict(step) for step in plan.steps],
        "provided_requirement_ids": list(plan.provided_requirement_ids),
        "environment_target_executable": plan.environment_target_executable,
    }


def deserialize_setup_plan(data: dict) -> SetupPlan:
    return SetupPlan(
        id=data["id"], project_id=data["project_id"],
        steps=tuple(SetupStep(**step) for step in data["steps"]),
        requires_user_approval=data.get("requires_user_approval", True),
        status=data["status"],
        generation_id=data.get("generation_id", ""),
        provided_requirement_ids=tuple(data.get("provided_requirement_ids", ())),
        environment_target_executable=data.get("environment_target_executable"),
    )


def serialize_verification_plan(plan: VerificationPlan) -> dict:
    return {
        "run_id": plan.run_id, "project_root": plan.project_root,
        "project_kind": plan.project_kind, "area_count": plan.area_count,
        "steps": [asdict(step) for step in plan.steps],
    }


def deserialize_verification_plan(data: dict) -> VerificationPlan:
    return VerificationPlan(
        run_id=data["run_id"], project_root=data["project_root"],
        project_kind=data["project_kind"], area_count=data["area_count"],
        steps=tuple(VerificationStep(**step) for step in data["steps"]),
    )
