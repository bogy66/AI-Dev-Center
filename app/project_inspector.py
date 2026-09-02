"""Application-core project inspection with structured intelligence.

Delegates safe file traversal to ``project_files`` and enriches the
result with a typed ``ProjectIntelligence`` profile.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from app.project_files import read_project_files as _default_reader
from app.project_intelligence import ProjectIntelligence, inspect_project


class ProjectInspector:
    """Build structured project information without duplicating file reading."""

    def __init__(
        self,
        file_reader: Callable[[Path], tuple[list[dict], list[str]]] | None = None,
    ) -> None:
        self._file_reader = file_reader or _default_reader

    def inspect(self, project_id: str, project_path: str | Path) -> dict[str, Any]:
        """Return the project-info shape consumed by ``DevelopmentWorkflow``.

        Sensitive files are excluded by the safe file reader.
        """
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id must be a non-empty string")

        path = Path(project_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"project path does not exist: {path}")
        if not path.is_dir():
            raise NotADirectoryError(f"project path is not a directory: {path}")

        files, warnings = self._file_reader(path)
        return {
            "project_id": project_id,
            "project_path": str(path),
            "files": files,
            "warnings": warnings,
        }

    def build_intelligence(
        self, project_path: str | Path
    ) -> ProjectIntelligence:
        """Return the full typed project intelligence profile."""
        return inspect_project(project_path)

    def inspect_managed(
        self, project_id: str, project_path: str | Path
    ) -> tuple[dict[str, Any], ProjectIntelligence]:
        """Inspect once and return both legacy info and typed intelligence."""
        legacy = self.inspect(project_id, project_path)
        intelligence = inspect_project(project_path)
        return legacy, intelligence