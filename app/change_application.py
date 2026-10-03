"""Change Application & Provenance Attribution.

The one, central implementation of "apply a structured change-set to a
project, routed through RunChangeProvenance when available, under the
correct lifecycle phase" -- used identically for development changes
(Development Change Generation's output) and test changes (Test Change
Generation's output), for both the initial cycle and the rework cycle.
Mutation policy (how a change-set actually reaches the filesystem,
which phase label attributes it, and what "applied successfully"
means) belongs here and nowhere else; the change-generation components
never mutate the filesystem or provenance themselves.
"""
from __future__ import annotations

from app.developer_file_applier import DeveloperFileApplier

# The four lifecycle phases RunChangeProvenance/DiagnosticTrace already
# key events by -- unchanged from the pre-existing productive contract.
_PHASES = {
    ("development", False): "development",
    ("development", True): "rework_development",
    ("test", False): "test",
    ("test", True): "rework_test",
}


def phase_for(kind: str, is_rework: bool) -> str:
    try:
        return _PHASES[(kind, bool(is_rework))]
    except KeyError:
        raise ValueError(f"Unknown change kind: {kind!r}") from None


class ChangeApplicationService:
    """The one place a structured change-set actually reaches disk."""

    def __init__(self, file_applier_factory=DeveloperFileApplier):
        self._file_applier_factory = file_applier_factory

    def apply(self, project_path, changes, kind: str, is_rework: bool, provenance_recorder=None) -> dict:
        """Apply `changes` for `kind` ("development" | "test"), phase-labeled.

        Routes through `provenance_recorder.apply(applier, changes, phase)`
        when a recorder is present (the productive, run-attributed path);
        otherwise applies directly via the same applier. Either way,
        returns the same {"applied": [...], "skipped": [...]} contract.
        """
        phase = phase_for(kind, is_rework)
        applier = self._file_applier_factory(project_path)
        if provenance_recorder:
            return provenance_recorder.apply(applier, changes, phase)
        return applier.apply(changes)

    @staticmethod
    def status_for(result: dict) -> str:
        """success only when something was applied and nothing was skipped."""
        return "success" if result.get("applied") and not result.get("skipped") else "apply_failed"
