"""S4.3-owned, single authoritative project-root path-safety policy.

The one shared definition of "is this requested relative path safe to
mutate/read within a project" -- used identically by DeveloperFileApplier
(S4.3 Change Application, the only place a generated change ever reaches
disk) and by RunChangeProvenance (S4.4 Change Provenance & Attribution,
which consumes this SAME decision rather than establishing an
independent one). Neither component may duplicate or diverge from this
policy: an unsafe path must be classified identically everywhere,
whether provenance is enabled or not.

Purely project-root/filesystem safety -- generic across any repository
or toolchain, no language/build/test-runner assumption of any kind.
"""
from __future__ import annotations

from pathlib import Path, PurePosixPath


def resolve_safe_path(project_root: Path, requested: object) -> Path | None:
    """Return the resolved absolute path for `requested` under
    `project_root`, or None when it is unsafe.

    Rejected, fail-closed, as unsafe:
      - an empty, missing, or non-string `requested` value;
      - an absolute path;
      - any parent-traversal segment ("..") anywhere in the path;
      - a path that names the project root itself (never a valid file
        target for create/update/delete);
      - a path whose RESOLVED location (after following any symlink)
        does not lie inside `project_root` -- this is what also catches
        a syntactically relative path that escapes through a symlink.
    """
    if not requested or not isinstance(requested, str):
        return None

    pure = PurePosixPath(requested)
    if pure.is_absolute() or ".." in pure.parts:
        return None

    resolved = (project_root / requested).resolve()
    if resolved == project_root:
        return None
    if project_root not in resolved.parents:
        return None
    return resolved
