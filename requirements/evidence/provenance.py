"""Repository/artifact/environment provenance capture for Evidence events.

Kept deliberately small: enough to make Evidence meaningful and reproducible
without dumping the whole environment or any secret-bearing content.
"""

import platform
import subprocess
import sys


def repository_identity(repo_root):
    """Return {"commit": str|None, "dirty": bool, "worktree": str}.

    Never pretends a dirty worktree is a clean commit: if uncommitted
    changes are present, dirty=True is recorded alongside the commit that
    was actually checked out.
    """
    commit = None
    dirty = False
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root, capture_output=True, text=True, timeout=10,
        ).stdout.strip() or None
    except Exception:
        commit = None
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root, capture_output=True, text=True, timeout=10,
        ).stdout
        dirty = bool(status.strip())
    except Exception:
        dirty = False
    return {"commit": commit, "dirty": dirty, "worktree": str(repo_root)}


def runtime_environment(testbed, profile=None):
    """Return {"os": ..., "platform": ..., "testbed": ..., "profile": ...}."""
    return {
        "os": platform.system(),
        "platform": platform.platform(),
        "testbed": testbed,
        "profile": profile,
    }


def python_tool_versions(extra=None):
    """Return a compact {"python": ...} dict, optionally merged with extra
    caller-supplied tool versions (e.g. {"pytest": "9.1.1"})."""
    versions = {"python": sys.version.split()[0]}
    if extra:
        versions.update(extra)
    return versions
