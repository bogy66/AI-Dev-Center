"""Shared, bounded text-file reader for project inspection."""

from __future__ import annotations

from pathlib import Path


MAX_FILE_SIZE = 1_000_000


def read_project_files(project_path: Path) -> tuple[list[dict], list[str]]:
    """Read eligible project files and return any inspection warnings."""
    files: list[dict] = []
    warnings: list[str] = []

    for path in sorted(project_path.rglob("*")):
        if not path.is_file():
            continue

        try:
            size = path.stat().st_size
        except OSError:
            warnings.append(f"Skipping unreadable file: {path}")
            continue

        if size > MAX_FILE_SIZE:
            warnings.append(f"Skipping large file: {path}")
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            warnings.append(f"Skipping binary/unreadable file: {path}")
            continue

        files.append(
            {
                "path": str(path.relative_to(project_path)),
                "content": content,
            }
        )

    return files, warnings
