"""Shared, bounded text-file reader for project inspection.

This reader explicitly excludes vendor, build, cache and VCS
directories.  It also protects sensitive files (``.env``, private
keys, credential manifests) from being read and later forwarded to
downstream consumers or LLM providers.
"""
from __future__ import annotations

from pathlib import Path
import re

MAX_FILE_SIZE = 1_000_000
_MAX_INSPECTION_FILES = 2_000

_EXCLUDE_DIRS = frozenset({
    ".git", "venv", ".venv", "node_modules", "__pycache__",
    ".cache", "dist", "build", ".pytest_cache", ".tox",
    ".eggs",
})

_SENSITIVE_NAME = re.compile(
    r"(?:"
    r"^\.env(\..*)?$|"
    r"\.pem$|\.key$|"
    r"^id_rsa$|^id_ed25519$|^id_ecdsa$|^id_dsa$|"
    r"^credentials\.(json|yaml|yml)$|"
    r"^secrets\.(yaml|yml)$|"
    r"^private_key\.pem$|"
    r"\.envrc$|"
    r"^\.netrc$"
    r")",
    re.IGNORECASE,
)


def _is_excluded(rel: str) -> bool:
    parts = rel.replace("\\", "/").split("/")
    for part in parts:
        if part in _EXCLUDE_DIRS:
            return True
        if part.endswith(".egg-info"):
            return True
    return False


def _is_sensitive(filename: str) -> bool:
    return bool(_SENSITIVE_NAME.fullmatch(filename))


def read_project_files(project_path: Path) -> tuple[list[dict], list[str]]:
    files: list[dict] = []
    warnings: list[str] = []
    count = 0

    try:
        all_entries = sorted(project_path.rglob("*"))
    except PermissionError:
        all_entries = []

    for path in all_entries:
        if not path.is_file():
            continue

        try:
            rel = path.relative_to(project_path).as_posix()
        except ValueError:
            warnings.append(f"Skipping path outside root: {path}")
            continue

        if _is_excluded(rel):
            continue

        basename = path.name
        if _is_sensitive(basename):
            continue

        try:
            size = path.stat().st_size
        except OSError:
            warnings.append(f"Skipping unreadable file: {rel}")
            continue

        if size > MAX_FILE_SIZE:
            warnings.append(f"Skipping large file: {rel}")
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            warnings.append(f"Skipping binary/unreadable file: {rel}")
            continue

        count += 1
        if count > _MAX_INSPECTION_FILES:
            warnings.append(
                f"File inspection limit reached ({_MAX_INSPECTION_FILES} files)"
            )
            break

        files.append({"path": rel, "content": content})

    return files, warnings