"""Application-core project inspection based on the established CLI reader."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from app.project_files import read_project_files


class ProjectInspector:
    """Build structured project information without duplicating file reading."""

    def __init__(self, file_reader: Callable[[Path], tuple[list[dict], list[str]]] = read_project_files) -> None:
        self._file_reader = file_reader

    def inspect(self, project_id: str, project_path: str | Path) -> dict[str, Any]:
        """Return the project-info shape consumed by ``DevelopmentWorkflow``."""
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
