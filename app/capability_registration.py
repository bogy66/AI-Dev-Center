"""Central contracts for approval-aware capability registration."""
from __future__ import annotations

from dataclasses import dataclass

from app.council_models import CouncilResult, CouncilVariant
from app.execution import CapabilityRegistration
from app.project_intelligence import ProjectIntelligence


class CapabilityRegistrationError(Exception):
    """Raised when the authority chain cannot produce a registration."""


@dataclass(frozen=True)
class CapabilityRegistrationRequest:
    request_id: str
    project_id: str
    project_intelligence: ProjectIntelligence
    council_result: CouncilResult
    capability: str
    executable_names: tuple[str, ...]
    allowed_operations: tuple[str, ...]
    project_scope: str | None = None

    def recommended_variant(self) -> CouncilVariant:
        recommendation = self.council_result.recommendation
        for variant in self.council_result.variants:
            if variant.id == recommendation:
                return variant
        raise CapabilityRegistrationError("Chairman recommendation is missing or invalid")


@dataclass(frozen=True)
class CapabilityRegistrationResult:
    request_id: str
    status: str
    registration: CapabilityRegistration | None = None
    blockers: tuple[str, ...] = ()

