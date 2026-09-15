"""Planning-only development stage built from existing change components."""
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.change_application import ChangeApplicationService
from app.developer_file_applier import DeveloperFileApplier
from app.structured_change_generation import generate_structured_changes


@dataclass(frozen=True)
class DevelopmentRequest:
    project_id: str
    project_path: str | Path
    task: str
    run_id: str | None = None
    provenance_recorder: object | None = None


@dataclass(frozen=True)
class DevelopmentResult:
    status: str
    generated_changes: dict[str, Any]
    applied_changes: dict[str, Any]


class DeveloperAgent:
    """Development Change Generation: generate structured changes only.

    Never mutates the filesystem or provenance -- that is exclusively
    ChangeApplicationService's responsibility.
    """
    def __init__(self, executor):
        self._executor = executor

    def generate_changes(self, request: DevelopmentRequest) -> dict[str, Any]:
        return generate_structured_changes(self._executor, "developer", request.task, "changes")


class DevelopmentStage:
    """Orchestrates change generation then change application for development changes."""

    def __init__(self, developer_agent: DeveloperAgent, file_applier_factory=DeveloperFileApplier,
                 change_application: ChangeApplicationService | None = None):
        self._developer_agent = developer_agent
        self._change_application = change_application or ChangeApplicationService(file_applier_factory)

    def run(self, request: DevelopmentRequest) -> DevelopmentResult:
        changes = self._developer_agent.generate_changes(request)
        is_rework = bool(getattr(request, "rework_request", None))
        result = self._change_application.apply(
            request.project_path, changes, "development", is_rework,
            provenance_recorder=request.provenance_recorder,
        )
        status = ChangeApplicationService.status_for(result)
        return DevelopmentResult(status, changes, result)
