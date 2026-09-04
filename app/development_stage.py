"""Planning-only development stage built from existing change components."""
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.developer_changes import DeveloperChanges
from app.developer_file_applier import DeveloperFileApplier


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
    """Generate structured changes only; it never applies them."""
    def __init__(self, executor):
        self._executor = executor

    def generate_changes(self, request: DevelopmentRequest) -> dict[str, Any]:
        response = self._executor.run("developer", request.task, "", "developer")
        try:
            return DeveloperChanges.parse_structured(response)
        except ValueError as structured_error:
            repair_response = self._executor.run(
                "developer",
                (
                    "Your previous response violated the required output format. "
                    "Return ONLY a valid JSON object with exactly this structure: "
                    '{"changes": [{"file": "relative/path", "action": "create|update|delete", '
                    '"content": "complete file content"}], "tests": ["test"]}. '
                    "Include all previously identified changes. "
                    "No markdown, no commentary outside the JSON."
                ),
                "",
                "developer",
            )
            try:
                return DeveloperChanges.parse_structured(repair_response)
            except ValueError:
                raise structured_error


class DevelopmentStage:
    def __init__(self, developer_agent: DeveloperAgent, file_applier_factory=DeveloperFileApplier):
        self._developer_agent = developer_agent
        self._file_applier_factory = file_applier_factory

    def run(self, request: DevelopmentRequest) -> DevelopmentResult:
        changes = self._developer_agent.generate_changes(request)
        applier = self._file_applier_factory(request.project_path)
        phase = "rework_development" if getattr(request, "rework_request", None) else "development"
        result = request.provenance_recorder.apply(applier, changes, phase) if request.provenance_recorder else applier.apply(changes)
        status = "success" if result["applied"] and not result["skipped"] else "apply_failed"
        return DevelopmentResult(status, changes, result)
