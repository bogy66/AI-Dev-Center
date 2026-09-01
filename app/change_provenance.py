"""Run-scoped, hash-based provenance for controlled file application."""
from __future__ import annotations
import hashlib
from pathlib import Path, PurePosixPath
import subprocess


class RunChangeProvenance:
    def __init__(self, workflow_manager, run_id, project_root):
        self._manager = workflow_manager
        self._run_id = run_id
        self._root = Path(project_root).resolve()

    def apply(self, applier, changes, phase):
        paths = [change.get("file") for change in changes.get("changes", [])]
        for path in paths:
            self._capture_baseline(path, phase)
        result = applier.apply(changes)
        applied = set(result.get("applied", []))
        for path in paths:
            self._record_event(path, phase, path in applied)
        return result

    def _path(self, relative):
        path = PurePosixPath(relative or "")
        if not relative or path.is_absolute() or ".." in path.parts:
            raise ValueError("Invalid provenance path")
        resolved = (self._root / path).resolve()
        if self._root not in (resolved, *resolved.parents):
            raise ValueError("Provenance path escapes project root")
        return resolved, path.as_posix()

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
