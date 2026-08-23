from dataclasses import dataclass, field
from typing import Protocol, Any


# --------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------
@dataclass(frozen=True)
class DiscoveredRequirement:
    """A single requirement discovered for a test environment."""
    name: str
    kind: str  # executable, python_package, hardware, capability, toolchain, connection, unknown
    required_for: str
    source: str
    evidence: str
    confidence: str  # high, medium, low


@dataclass(frozen=True)
class RequirementSet:
    """A collection of discovered requirements."""
    requirements: list[DiscoveredRequirement] = field(default_factory=list)


# --------------------------------------------------------------------
# Discovery source protocol
# --------------------------------------------------------------------
class DiscoverySource(Protocol):
    """Protocol for a source that can discover requirements for a project."""

    def discover(self, project_info: dict[str, Any], stack_context: str | None = None) -> list[DiscoveredRequirement]:
        """Return a list of discovered requirements for the given project."""
        ...


# --------------------------------------------------------------------
# AIRequirementDiscovery
# --------------------------------------------------------------------
class AIRequirementDiscovery:
    """Discovers requirements for a project using an injectable DiscoverySource.

    The class is stack‑neutral and does not contain any ESPHome, ESP32,
    pytest or other framework‑specific logic.
    """

    def __init__(self, source: DiscoverySource):
        self._source = source

    def discover(
        self,
        project_info: dict[str, Any],
        stack_context: str | None = None,
    ) -> RequirementSet:
        """Run the discovery source and return a RequirementSet."""
        discovered = self._source.discover(project_info, stack_context)
        return RequirementSet(requirements=list(discovered))
