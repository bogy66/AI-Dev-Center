from typing import Protocol, Any
from app.requirement_model import Requirement, RequirementSet, Status


class DiscoverySource(Protocol):
    """Protocol for a source that can discover requirements for a project."""

    def discover(
        self,
        project_info: dict[str, Any],
        stack_context: str | None = None,
    ) -> list[Requirement]:
        ...


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
        project_id = project_info.get("project_id", "") or "unknown"
        return RequirementSet(
            id=f"discovery-set-{project_id}",
            project_id=project_id,
            requirements=discovered,
            source="ai",
            overall_status=Status.DISCOVERED,
        )
