import re
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from collections.abc import Mapping
from typing import Any, Optional


class Status:
    """Lifecycle status values for a single requirement."""
    DISCOVERED = "discovered"
    SUSPECTED = "suspected"
    REQUIRED = "required"
    OPTIONAL = "optional"
    INSTALLED = "installed"
    MISSING = "missing"
    VERIFICATION_PENDING = "verification_pending"
    VERIFIED = "verified"
    FAILED = "failed"
    REJECTED = "rejected"


class RequirementType:
    """Generic requirement categories used during AI discovery."""
    EXECUTABLE = "executable"
    PYTHON_PACKAGE = "python_package"
    SYSTEM_PACKAGE = "system_package"
    SDK = "sdk"
    TOOLCHAIN = "toolchain"
    FLASHER = "flasher"
    HARDWARE_COMPONENT = "hardware_component"
    CONNECTION = "connection"
    BUILD_COMMAND = "build_command"
    TEST_COMMAND = "test_command"
    CONFIG_FILE = "config_file"
    VERSION_CONSTRAINT = "version_constraint"
    CAPABILITY = "capability"
    UNKNOWN = "unknown"


class SetupEffect:
    """Semantic setup capability/effect identities.

    These describe *what* kind of environment change is required, not
    *how* to perform it on a specific host.  They are not shell commands,
    package-manager argv, or executable paths.
    """
    PYTHON_PACKAGE_INSTALL = "python_package_install"
    PROJECT_TOOL_INSTALL = "project_tool_install"
    SYSTEM_PACKAGE_INSTALL = "system_package_install"
    CONTAINER_RUNTIME_SETUP = "container_runtime_setup"
    SYSTEM_CONFIGURATION = "system_configuration"
    DEVICE_ACCESS = "device_access"
    MANUAL = "manual"


_EFFECT_BY_TYPE = {
    RequirementType.PYTHON_PACKAGE: SetupEffect.PYTHON_PACKAGE_INSTALL,
    RequirementType.SYSTEM_PACKAGE: SetupEffect.SYSTEM_PACKAGE_INSTALL,
    RequirementType.EXECUTABLE: SetupEffect.PROJECT_TOOL_INSTALL,
    RequirementType.SDK: SetupEffect.PROJECT_TOOL_INSTALL,
    RequirementType.TOOLCHAIN: SetupEffect.PROJECT_TOOL_INSTALL,
    RequirementType.FLASHER: SetupEffect.PROJECT_TOOL_INSTALL,
}


def classify_setup_effect(
    req_type: str,
    name: str | None = None,
    install_method: str | None = None,
) -> str:
    """Map structured requirement semantics to a semantic setup effect.

    The returned effect is a SetupEffect identity, never a command or
    package-manager invocation.
    """
    if not req_type or not isinstance(req_type, str):
        return SetupEffect.MANUAL
    known = _EFFECT_BY_TYPE.get(req_type)
    if known is None:
        return SetupEffect.MANUAL
    has_name = bool(name and name.strip())
    has_method = bool(install_method and install_method.strip())
    if not has_name or not has_method:
        return SetupEffect.MANUAL
    return known


def _as_tuple(value):
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    try:
        return tuple(value)
    except TypeError:
        return ()


_UNSAFE_EXECUTABLE_RE = re.compile(r"\s")


def _validate_verification_executable(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    stripped = value.strip()
    if _UNSAFE_EXECUTABLE_RE.search(stripped):
        return None
    return stripped


@dataclass(frozen=True)
class RequirementEvidence:
    """Structured evidence explaining why a requirement was proposed."""
    id: str
    source_type: str
    description: str
    source_file: Optional[str] = None
    snippet: Optional[str] = None
    confidence_contribution: Optional[float] = None
    url: Optional[str] = None


@dataclass(frozen=True)
class Requirement:
    """A single discovered, validated, installed, or verified requirement."""
    id: str
    name: str
    type: str
    purpose: str
    required: bool
    confidence: float
    evidence: tuple[RequirementEvidence, ...] = field(default_factory=tuple)
    source_file: Optional[str] = None
    detected_version: Optional[str] = None
    required_version: Optional[str] = None
    install_method: Optional[str] = None
    verification_method: Optional[str] = None
    verification_executable: str | None = None
    status: str = Status.DISCOVERED
    metadata: Mapping[str, Any] = field(default_factory=dict)

    # Explicit Python distribution identity; name remains a display label.
    # None is legacy/unknown, never an invitation to infer from name.
    technical_identity: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "evidence", _as_tuple(self.evidence))

        validated = _validate_verification_executable(self.verification_executable)
        if validated != self.verification_executable:
            object.__setattr__(self, "verification_executable", validated)

        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping")
        if not isinstance(self.metadata, MappingProxyType):
            object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True)
class RequirementActivation:
    """Per-workflow activation of a durable project requirement."""
    requirement_id: str
    active: bool
    blocks_current_operation: bool
    reason: str = ""

    def __post_init__(self):
        if not isinstance(self.requirement_id, str) or not self.requirement_id.strip():
            raise ValueError("requirement_id must be a non-empty string")
        if not isinstance(self.active, bool):
            raise TypeError("active must be a boolean")
        if not isinstance(self.blocks_current_operation, bool):
            raise TypeError("blocks_current_operation must be a boolean")
        if self.blocks_current_operation and not self.active:
            raise ValueError("an inactive requirement cannot block the current operation")

    @property
    def state(self) -> str:
        if not self.active:
            return "inactive"
        return "active_blocker" if self.blocks_current_operation else "active_non_blocking"


# Requirement types that describe a project-internal artifact the
# Developer is expected to create or edit as part of the requested
# development work (e.g. a missing project configuration file), as
# opposed to an external prerequisite (a tool, package, toolchain,
# piece of hardware, or connection) that must already exist before
# Development can meaningfully begin. Missing an artifact of one of
# these types is not, by itself, a reason to block the current
# operation - Development has not yet had the chance to produce it.
DEVELOPMENT_ARTIFACT_REQUIREMENT_TYPES = frozenset({
    RequirementType.CONFIG_FILE,
})


def _default_activation_for(requirement) -> "RequirementActivation":
    """Compute the default activation when none was explicitly supplied.

    This is the single, central place default activations are derived
    from requirement semantics; an explicitly supplied activation (see
    normalize_requirement_activations) always takes precedence over
    this default and remains the correct mechanism for overriding it
    on a per-requirement basis - this function does not invent a
    second, parallel way to express activation.
    """
    if requirement.required and requirement.type in DEVELOPMENT_ARTIFACT_REQUIREMENT_TYPES:
        return RequirementActivation(
            requirement_id=requirement.id,
            active=True,
            blocks_current_operation=False,
            reason=(
                "development-created artifact; expected to be produced by "
                "the requested development operation, not a "
                "pre-development prerequisite"
            ),
        )
    return RequirementActivation(
        requirement_id=requirement.id,
        active=requirement.required,
        blocks_current_operation=requirement.required,
        reason="compatibility default from project requirement",
    )


def normalize_requirement_activations(requirements, activations=None):
    """Return one exact, immutable activation per supplied requirement."""
    requirements_tuple = tuple(requirements)
    requirement_ids = {requirement.id for requirement in requirements_tuple}
    if len(requirement_ids) != len(requirements_tuple):
        raise ValueError("requirement ids must be unique for activation")
    supplied = {}
    for activation in tuple(activations or ()):
        if activation.requirement_id not in requirement_ids:
            raise ValueError(
                f"activation references unknown requirement: {activation.requirement_id}"
            )
        if activation.requirement_id in supplied:
            raise ValueError(
                f"duplicate activation for requirement: {activation.requirement_id}"
            )
        supplied[activation.requirement_id] = activation
    return tuple(
        supplied.get(requirement.id) or _default_activation_for(requirement)
        for requirement in requirements_tuple
    )


@dataclass(frozen=True)
class RequirementSet:
    """Container for all requirements belonging to a workflow run."""
    id: str
    project_id: str
    requirements: tuple[Requirement, ...] = field(default_factory=tuple)
    source: str = "unknown"
    overall_status: str = Status.DISCOVERED
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        object.__setattr__(self, "requirements", _as_tuple(self.requirements))


@dataclass(frozen=True)
class DiscoveryResult:
    """Output of the requirement discovery stage."""
    id: str
    source: str
    project_id: str
    requirements: tuple[Requirement, ...] = field(default_factory=tuple)
    conversation_trace_id: Optional[str] = None
    ai_model: Optional[str] = None
    fallback_used: bool = False
    warnings: tuple[str, ...] = field(default_factory=tuple)
    generated_at: datetime = field(default_factory=datetime.now)
    activations: tuple[RequirementActivation, ...] = field(default_factory=tuple)

    def __post_init__(self):
        object.__setattr__(self, "requirements", _as_tuple(self.requirements))
        object.__setattr__(self, "activations", _as_tuple(self.activations))
        object.__setattr__(self, "warnings", _as_tuple(self.warnings))


@dataclass(frozen=True)
class ValidationResult:
    """Output of the requirement validation stage."""
    id: str
    valid: bool
    requirements: tuple[Requirement, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    normalized_requirements: tuple[Requirement, ...] = field(default_factory=tuple)
    required_requirements: tuple[Requirement, ...] = field(default_factory=tuple)
    optional_requirements: tuple[Requirement, ...] = field(default_factory=tuple)
    rejected_requirements: tuple[Requirement, ...] = field(default_factory=tuple)
    activations: tuple[RequirementActivation, ...] = field(default_factory=tuple)

    def __post_init__(self):
        object.__setattr__(self, "requirements", _as_tuple(self.requirements))
        object.__setattr__(self, "errors", _as_tuple(self.errors))
        object.__setattr__(self, "warnings", _as_tuple(self.warnings))
        object.__setattr__(
            self, "normalized_requirements", _as_tuple(self.normalized_requirements)
        )
        object.__setattr__(
            self, "required_requirements", _as_tuple(self.required_requirements)
        )
        object.__setattr__(
            self, "optional_requirements", _as_tuple(self.optional_requirements)
        )
        object.__setattr__(
            self, "rejected_requirements", _as_tuple(self.rejected_requirements)
        )
        object.__setattr__(self, "activations", _as_tuple(self.activations))


@dataclass(frozen=True)
class PreflightRequirementResult:
    """Per‑requirement result of the environment preflight stage.

    target_executable is the immutable execution-target identity (an
    already-resolved executable path) this specific requirement's
    check used, when that requirement's type has an execution-target
    concept at all — e.g. for a python_package requirement it is the
    Python interpreter checked. It is intentionally per-requirement
    rather than per-preflight-run: a single project can contain
    multiple ecosystems, and each requirement's adapter resolves and
    owns its own target independently. Requirement types with no such
    concept (e.g. a plain EXECUTABLE lookup via PATH) leave this None.
    """
    requirement_id: str
    present: bool
    detected_version: Optional[str] = None
    satisfied: bool = False
    warning: Optional[str] = None
    active: bool = True
    blocks_current_operation: bool = True
    target_executable: Optional[str] = None


@dataclass(frozen=True)
class PreflightResult:
    """Generic result of environment preflight checking.

    This model contains no stack‑ or framework‑specific fields.
    """
    id: str
    project_id: str
    overall_ready: bool
    results: tuple[PreflightRequirementResult, ...] = field(default_factory=tuple)
    missing_requirements: tuple[Requirement, ...] = field(default_factory=tuple)
    already_installed: tuple[Requirement, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    activations: tuple[RequirementActivation, ...] = field(default_factory=tuple)
    inactive_requirements: tuple[Requirement, ...] = field(default_factory=tuple)
    project_requirements: tuple[Requirement, ...] = field(default_factory=tuple)

    def __post_init__(self):
        object.__setattr__(self, "results", _as_tuple(self.results))
        object.__setattr__(
            self, "missing_requirements", _as_tuple(self.missing_requirements)
        )
        object.__setattr__(
            self, "already_installed", _as_tuple(self.already_installed)
        )
        object.__setattr__(self, "warnings", _as_tuple(self.warnings))
        object.__setattr__(self, "activations", _as_tuple(self.activations))
        object.__setattr__(
            self, "inactive_requirements", _as_tuple(self.inactive_requirements)
        )
        object.__setattr__(
            self, "project_requirements", _as_tuple(self.project_requirements)
        )


@dataclass(frozen=True)
class SetupStep:
    """A single step in a setup/installation plan.

    target_executable carries the exact, immutable execution-target
    identity (an already-resolved executable path) this step's own
    requirement was checked against during Preflight — e.g. for a
    python_package step, the Python interpreter to install into. It is
    ecosystem-neutral central vocabulary: whatever adapter executes
    this step interprets it according to its own semantics.
    """
    id: str
    requirement_id: str
    action: str
    install_method: Optional[str] = None
    package: Optional[str] = None
    version: Optional[str] = None
    command: Optional[str] = None
    verification_after: Optional[str] = None
    is_approved: bool = False
    setup_effect: Optional[str] = None
    target_executable: Optional[str] = None


def _new_generation_id() -> str:
    import uuid
    return uuid.uuid4().hex


@dataclass(frozen=True)
class SetupPlan:
    """Ordered, user‑approvable setup plan."""
    id: str
    project_id: str
    steps: tuple[SetupStep, ...] = field(default_factory=tuple)
    requires_user_approval: bool = True
    rollback_steps: tuple[SetupStep, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    status: str = "pending_approval"
    created_at: datetime = field(default_factory=datetime.now)
    requirement_activations: tuple[RequirementActivation, ...] = field(default_factory=tuple)
    deferred_requirement_ids: tuple[str, ...] = field(default_factory=tuple)
    deferred_requirements: tuple[Requirement, ...] = field(default_factory=tuple)
    provided_requirement_ids: tuple[str, ...] = field(default_factory=tuple)
    unsupported_backend_effects: tuple[str, ...] = field(default_factory=tuple)
    # CLAUDE-E2E-003I: identifies exactly ONE materialized setup decision
    # ("generation"), independent of the stable, per-project plan.id.
    # Generated centrally (default_factory), never client-suppliable --
    # every fresh SetupPlan() construction that does not explicitly pass
    # generation_id gets a new, random one, so a genuinely new
    # materialization (a new ToolchainMaterializer.materialize() call)
    # always produces a new generation_id, while dataclasses.replace()
    # (used by SetupApproval.approve()/reject() and by save/load round
    # trips) preserves the exact same one -- retry, restart and approval
    # of the SAME materialized decision never change it. Ecosystem-neutral:
    # a plain identifier, no toolchain-specific meaning.
    generation_id: str = field(default_factory=_new_generation_id)

    def __post_init__(self):
        object.__setattr__(self, "steps", _as_tuple(self.steps))
        object.__setattr__(self, "rollback_steps", _as_tuple(self.rollback_steps))
        object.__setattr__(self, "warnings", _as_tuple(self.warnings))
        object.__setattr__(
            self, "requirement_activations", _as_tuple(self.requirement_activations)
        )
        object.__setattr__(
            self, "deferred_requirement_ids", _as_tuple(self.deferred_requirement_ids)
        )
        object.__setattr__(
            self, "deferred_requirements", _as_tuple(self.deferred_requirements)
        )
        object.__setattr__(
            self, "provided_requirement_ids", _as_tuple(self.provided_requirement_ids)
        )
        object.__setattr__(
            self, "unsupported_backend_effects", _as_tuple(self.unsupported_backend_effects)
        )
