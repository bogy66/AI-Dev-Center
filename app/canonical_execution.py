"""Process-local project ownership for canonical mutating workflow stages."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading
import uuid


class CanonicalExecutionError(RuntimeError):
    """Base error for deterministic execution lifecycle rejection."""


class ConcurrentExecutionError(CanonicalExecutionError):
    pass


class ExecutionReentryError(CanonicalExecutionError):
    pass


class RecoveryRequiredError(CanonicalExecutionError):
    pass


PROCESS_OWNER_ID = uuid.uuid4().hex
_registry_lock = threading.Lock()
_owners: dict[str, tuple[str, str, str]] = {}


def project_key(project_root: str | Path) -> str:
    if not project_root:
        raise ValueError("project_root is required")
    return str(Path(project_root).expanduser().resolve(strict=False))


@dataclass(frozen=True)
class ProjectExecutionLease:
    project_root: str
    run_id: str
    stage: str
    token: str

    def release(self) -> None:
        with _registry_lock:
            if _owners.get(self.project_root) == (self.run_id, self.stage, self.token):
                _owners.pop(self.project_root, None)


def acquire_project_execution(project_root, run_id: str, stage: str) -> ProjectExecutionLease:
    key = project_key(project_root)
    token = uuid.uuid4().hex
    with _registry_lock:
        if key in _owners:
            raise ConcurrentExecutionError(
                "A mutating canonical execution is already active for this project"
            )
        _owners[key] = (run_id, stage, token)
    return ProjectExecutionLease(key, run_id, stage, token)
