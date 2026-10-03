"""Run-scoped, hash-based provenance for controlled file application."""
from __future__ import annotations
import hashlib
from pathlib import Path, PurePosixPath
import subprocess

from app.safe_project_path import resolve_safe_path


class RunChangeProvenance:
    def __init__(self, workflow_manager, run_id, project_root):
        self._manager = workflow_manager
        self._run_id = run_id
        self._root = Path(project_root).resolve()

    def capture_working_tree_baseline(self) -> None:
        """CLAUDE-E2E-NIO-006B/006C: capture, once, the full STATE (not
        merely the path membership) of every path already untracked/
        modified in the project's working tree BEFORE this run's own
        mutating actions begin. This is what lets a later Controlled Git
        delivery distinguish pre-existing foreign content a real user
        independently owns -- unchanged throughout the run, safe to
        leave untouched, must never block delivery -- from EITHER a
        genuinely new, run-introduced unapproved side effect, OR an
        additional unauthorized mutation applied to a path that was
        already dirty at run start (CLAUDE-E2E-NIO-006C: a path-only
        baseline cannot tell these apart, since the path itself never
        changes). Per path, records the real `git status` class (e.g.
        "??", " M") and a real content hash (or None for a path that
        does not currently exist as a file, e.g. a pending deletion) --
        never a timestamp, never anything inferred from a filename or
        extension. Artifact/tool neutral throughout. Explicit, not
        implicit in __init__, so constructing a RunChangeProvenance
        never has an unexpected subprocess side effect for callers
        (including the many existing unit tests) that never intend to
        use this specific capability."""
        result = subprocess.run(
            ["git", "-C", str(self._root), "status", "--porcelain", "-z"],
            capture_output=True, text=True, check=False,
        )
        entries = [entry for entry in result.stdout.split("\0") if entry] if not result.returncode else []
        state = {
            entry[3:]: {
                "status": entry[:2],
                "content_hash": self._hash(self._root / entry[3:]),
            }
            for entry in entries
        }
        self._manager.capture_working_tree_baseline(self._run_id, state)

    def apply(self, applier, changes, phase):
        # Consume S4.3's own path-safety decision rather than an
        # independent one: an unsafe requested path is skipped here too
        # (no baseline capture, no hash/git access on the escaped
        # target, no event) and left entirely to `applier.apply()`'s own
        # normal `skipped` classification -- never raised, so provenance
        # being enabled can never change whether/how an unsafe path is
        # reported compared to direct application.
        paths = [change.get("file") for change in changes.get("changes", [])]
        safe_paths = [path for path in paths if resolve_safe_path(self._root, path) is not None]
        for path in safe_paths:
            self._capture_baseline(path, phase)
        result = applier.apply(changes)
        applied = set(result.get("applied", []))
        for path in safe_paths:
            self._record_event(path, phase, path in applied)
        return result

    def _path(self, relative):
        resolved = resolve_safe_path(self._root, relative)
        if resolved is None:
            raise ValueError("Invalid provenance path")
        return resolved, PurePosixPath(relative).as_posix()

    @staticmethod
    def _hash(path):
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None

    def _git_flags(self, path):
        base = ["git", "-C", str(self._root)]
        repository = subprocess.run(base + ["rev-parse", "--is-inside-work-tree"], capture_output=True, text=True, check=False)
        if repository.returncode or repository.stdout.strip() != "true":
            return {"git_repository": False, "git_tracked_before": None, "git_worktree_dirty_before": None, "git_index_staged_before": None, "git_untracked_before": None}
        tracked = subprocess.run(base + ["ls-files", "--error-unmatch", "--", path], capture_output=True, text=True, check=False).returncode == 0
        status = subprocess.run(base + ["status", "--porcelain", "--", path], capture_output=True, text=True, check=False).stdout[:2]
        return {"git_repository": True, "git_tracked_before": tracked, "git_worktree_dirty_before": len(status) > 1 and status[1] != " ", "git_index_staged_before": bool(status and status[0] != " "), "git_untracked_before": status == "??"}

    def _capture_baseline(self, relative, phase):
        path, relative = self._path(relative)
        self._manager.capture_provenance_baseline(self._run_id, str(self._root), relative, phase, {
            "file_existed_before": path.exists(), "content_hash_before": self._hash(path), **self._git_flags(relative),
        })

    def _record_event(self, relative, phase, success):
        path, relative = self._path(relative)
        self._manager.record_provenance_event(self._run_id, relative, {
            "phase": phase, "file_exists_after": path.exists(), "content_hash_after": self._hash(path) if success else None, "apply_success": success,
        })
