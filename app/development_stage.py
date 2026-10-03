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
    # IF_REQ_038: TargetEnvironmentContext established by the S3->S4
    # handoff before generation (app.target_environment). None = no
    # context was established for this request (unknown, never confirmed).
    target_environment: object | None = None


@dataclass(frozen=True)
class DevelopmentResult:
    status: str
    generated_changes: dict[str, Any]
    # None when S4.3 was never invoked for this cycle (an empty S4.1
    # change set) -- truthfully "no application attempt occurred",
    # never an empty apply result fabricated for a skipped S4.3.
    applied_changes: dict[str, Any] | None
    # Redacted S4.1 evidence for diagnosis (counts, booleans, fixed
    # classification tokens only): generated_change_count,
    # apply_attempted, repair_attempted and, where applicable,
    # initial_parse_error_class.
    generation_evidence: dict[str, Any] | None = None


class DeveloperAgent:
    """Development Change Generation: generate structured changes only.

    Never mutates the filesystem or provenance -- that is exclusively
    ChangeApplicationService's responsibility.
    """
    def __init__(self, executor):
        self._executor = executor

    def generate_changes(self, request: DevelopmentRequest) -> dict[str, Any]:
        # SUB_REQ_041: the established target-environment context reaches
        # the generator as part of its task. Without one, the task is
        # passed on unchanged -- nothing is claimed about the environment.
        task = request.task
        context = getattr(request, "target_environment", None)
        if context is not None:
            task = f"{task}\n\n{context.render_for_generator()}"
        return generate_structured_changes(self._executor, "developer", task, "changes")


class DevelopmentStage:
    """Orchestrates change generation then change application for development changes."""

    def __init__(self, developer_agent: DeveloperAgent, file_applier_factory=DeveloperFileApplier,
                 change_application: ChangeApplicationService | None = None):
        self._developer_agent = developer_agent
        self._change_application = change_application or ChangeApplicationService(file_applier_factory)

    def run(self, request: DevelopmentRequest) -> DevelopmentResult:
        changes = self._developer_agent.generate_changes(request)
        evidence = dict(getattr(changes, "generation_evidence", None) or {})
        generated = changes.get("changes") if isinstance(changes, dict) else None
        evidence["generated_change_count"] = len(generated) if isinstance(generated, (list, tuple)) else 0
        context = getattr(request, "target_environment", None)
        if context is not None:
            evidence["target_environment_state"] = context.evidence_token()
        if not generated:
            # S4.1 critical invariant (ARC_016): an empty development
            # change set MUST fail -- S4.1 has no no-op authority. It
            # fails closed HERE, before S4.3: no application attempt
            # occurred, so none is reported (applied_changes None). The
            # existing S4 terminal status is kept; the evidence tells
            # an empty generation apart from a rejected application.
            evidence["apply_attempted"] = False
            return DevelopmentResult("apply_failed", changes, None, evidence)
        is_rework = bool(getattr(request, "rework_request", None))
        result = self._change_application.apply(
            request.project_path, changes, "development", is_rework,
            provenance_recorder=request.provenance_recorder,
        )
        status = ChangeApplicationService.status_for(result)
        evidence["apply_attempted"] = True
        return DevelopmentResult(status, changes, result, evidence)
