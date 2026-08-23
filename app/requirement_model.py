from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from collections.abc import Mapping
from typing import Optional, Any


# ---------------------------------------------------------------------------
# Generic status and type constants (framework‑ and stack‑neutral)
# ---------------------------------------------------------------------------
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


def _as_tuple(value):
    """Return *value* as a tuple, converting lists and other iterables."""
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    # Fallback for any other iterable, e.g. a generator
    try:
        return tuple(value)
    except TypeError:
        return ()


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------
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
    status: str = Status.DISCOVERED
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # Make evidence immutable by converting to tuple.
        object.__setattr__(self, "evidence", _as_tuple(self.evidence))

        # Make metadata immutable by converting to MappingProxyType.
        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping")
        if not isinstance(self.metadata, MappingProxyType):
            object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


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

    def __post_init__(self):
        object.__setattr__(self, "requirements", _as_tuple(self.requirements))
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

    def __post_init__(self):
        object.__setattr__(self, "requirements", _as_tuple(self.requirements))
        object.__setattr__(self, "errors", _as_tuple(self.errors))
        object.__setattr__(self, "warnings", _as_tuple(self.warnings))
        object.__setattr__(self, "normalized_requirements", _as_tuple(self.normalized_requirements))
        object.__setattr__(self, "required_requirements", _as_tuple(self.required_requirements))
        object.__setattr__(self, "optional_requirements", _as_tuple(self.optional_requirements))
        object.__setattr__(self, "rejected_requirements", _as_tuple(self.rejected_requirements))


@dataclass(frozen=True)
class PreflightRequirementResult:
    """Per‑requirement result of the environment preflight stage."""
    requirement_id: str
    present: bool
    detected_version: Optional[str] = None
    satisfied: bool = False
    warning: Optional[str] = None


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

    def __post_init__(self):
        object.__setattr__(self, "results", _as_tuple(self.results))
        object.__setattr__(self, "missing_requirements", _as_tuple(self.missing_requirements))
        object.__setattr__(self, "already_installed", _as_tuple(self.already_installed))
        object.__setattr__(self, "warnings", _as_tuple(self.warnings))


@dataclass(frozen=True)
class SetupStep:
    """A single step in a setup/installation plan."""
    id: str
    requirement_id: str
    action: str
    install_method: Optional[str] = None
    package: Optional[str] = None
    version: Optional[str] = None
    command: Optional[str] = None
    verification_after: Optional[str] = None
    is_approved: bool = False


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

    def __post_init__(self):
        object.__setattr__(self, "steps", _as_tuple(self.steps))
        object.__setattr__(self, "rollback_steps", _as_tuple(self.rollback_steps))
        object.__setattr__(self, "warnings", _as_tuple(self.warnings))
