"""Fail-safe local Git commit stage based on run-specific provenance."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
from pathlib import Path, PurePosixPath
import subprocess


@dataclass(frozen=True)
class GitCommitRequest:
    run_id: str
    project_root: str | Path
    commit_message: str
    development_status: str
    final_approval_status: str
    ready_for_git: bool
    provenance: dict
    all_provenance: dict = field(default_factory=dict)


@dataclass(frozen=True)
class GitCommitResult:
    run_id: str
    status: str
    commit_message: str
    paths: tuple[str, ...] = ()
    commit_hash: str | None = None
    blockers: tuple[str, ...] = ()
    error: str | None = None
    ready_for_publish: bool = False

    def to_record(self) -> dict:
        record = asdict(self)
        record["paths"] = list(self.paths)
        record["blockers"] = list(self.blockers)
        return record

    @classmethod
    def from_record(cls, record: dict) -> "GitCommitResult":
        return cls(
            run_id=record["run_id"],
            status=record["status"],
            commit_message=record["commit_message"],
            paths=tuple(record.get("paths", ())),
            commit_hash=record.get("commit_hash"),
            blockers=tuple(record.get("blockers", ())),
            error=record.get("error"),
            ready_for_publish=record.get("ready_for_publish", record.get("status") == "committed"),
        )


class ControlledGitStage:
    """Create one local commit without absorbing unrelated user changes."""

    def run(self, request: GitCommitRequest) -> GitCommitResult:
        blockers = self._gate_blockers(request)
        if blockers:
            return self._failed(request, blockers)

        root = Path(request.project_root).resolve()
        repository = self._git(root, "rev-parse", "--show-toplevel")
        if repository.returncode:
            return self._failed(request, ("project_root is not in an existing Git repository",))
        repo_root = Path(repository.stdout.strip()).resolve()
        if repo_root not in (root, *root.parents):
            return self._failed(request, ("Git repository does not contain project_root",))

        paths, blockers = self._safe_paths(request, root)
        if blockers:
            return self._failed(request, blockers)
        if not paths:
            return self._failed(request, ("no safely committable provenance paths",))

        staged_check = self._git(repo_root, "diff", "--cached", "--name-only", "-z")
        if staged_check.returncode:
            return self._failed(request, ("Git index check failed",), staged_check.stderr.strip())
        staged = self._nul_paths(staged_check.stdout)
        if staged:
            return self._failed(request, ("foreign or preexisting staged changes block the commit",))

        repo_paths = tuple((root / path).relative_to(repo_root).as_posix() for path in paths)
        changed = self._git(repo_root, "status", "--porcelain", "-z", "--", *repo_paths)
        if changed.returncode:
            return self._failed(request, ("Git status check failed",), changed.stderr.strip())
        if not changed.stdout:
            return GitCommitResult(request.run_id, "nothing_to_commit", request.commit_message, paths)

        added = self._git(repo_root, "add", "--", *repo_paths)
        if added.returncode:
            return self._failed(request, ("explicit staging failed",), added.stderr.strip())

        staged_check = self._git(repo_root, "diff", "--cached", "--name-only", "-z")
        if staged_check.returncode:
            return self._failed(request, ("post-staging index check failed",), staged_check.stderr.strip())
        staged_after = set(self._nul_paths(staged_check.stdout))
        if staged_after != set(repo_paths):
            return self._failed(request, ("staged paths differ from validated run paths",))

        committed = self._git(repo_root, "commit", "-m", request.commit_message)
        if committed.returncode:
            return self._failed(request, ("git commit failed",), committed.stderr.strip())
        commit_hash = self._git(repo_root, "rev-parse", "HEAD")
        if commit_hash.returncode:
            return self._failed(request, ("created commit hash could not be read",), commit_hash.stderr.strip())
        noted = self._git(
            repo_root, "notes", "--ref=ai-dev-center", "add", "-m",
            self._run_marker(request.run_id), commit_hash.stdout.strip(),
        )
        if noted.returncode:
            return self._failed(
                request, ("run ownership note could not be persisted",),
                noted.stderr.strip(),
            )
        return GitCommitResult(
            request.run_id, "committed", request.commit_message, paths,
            commit_hash.stdout.strip(), ready_for_publish=True,
        )

    @staticmethod
    def _gate_blockers(request: GitCommitRequest) -> tuple[str, ...]:
        blockers = []
        if not isinstance(request.run_id, str) or not request.run_id.strip():
            blockers.append("run_id is required")
        elif any(ord(character) < 32 or ord(character) == 127 for character in request.run_id):
            blockers.append("run_id contains control characters")
        if request.development_status != "accepted":
            blockers.append("development/testing result is not accepted")
        if request.final_approval_status != "approved":
            blockers.append("final human approval is not approved")
        if request.ready_for_git is not True:
            blockers.append("ready_for_git is not true")
        if not request.project_root:
            blockers.append("explicit project_root is required")
        message = request.commit_message
        if not isinstance(message, str) or not message.strip():
            blockers.append("commit message is empty")
        elif any(ord(character) < 32 or ord(character) == 127 for character in message):
            blockers.append("commit message contains control characters")
        if not isinstance(request.provenance, dict) or not request.provenance:
            blockers.append("run-specific provenance is missing")
        return tuple(blockers)

    def _safe_paths(self, request: GitCommitRequest, root: Path):
        safe = []
        blockers = []
        for relative, entry in sorted(request.provenance.items()):
            path = PurePosixPath(relative) if isinstance(relative, str) else PurePosixPath("")
            if not relative or path.is_absolute() or ".." in path.parts or path.as_posix().startswith("-"):
                blockers.append(f"invalid provenance path: {relative!r}")
                continue
            candidate = root.joinpath(*path.parts)
            if any(part.is_symlink() for part in (candidate, *candidate.parents) if part != root.parent):
                blockers.append(f"symlink path is not safe: {relative}")
                continue
            resolved = candidate.resolve()
            if root not in resolved.parents:
                blockers.append(f"path escapes project_root: {relative}")
                continue
            if not isinstance(entry, dict) or entry.get("project_root") != str(root):
                blockers.append(f"inconsistent project_root provenance: {relative}")
                continue
            baseline = entry.get("baseline")
            events = entry.get("events")
            if not isinstance(baseline, dict) or not isinstance(events, list) or not events:
                blockers.append(f"incomplete provenance: {relative}")
                continue
            if baseline.get("git_repository") is not True:
                blockers.append(f"baseline was not captured in Git: {relative}")
            if baseline.get("git_worktree_dirty_before") is True or baseline.get("git_untracked_before") is True:
                blockers.append(f"pre-run modified/untracked path: {relative}")
            if baseline.get("git_index_staged_before") is True:
                blockers.append(f"pre-run staged path: {relative}")
            if any(not isinstance(event, dict) or event.get("apply_success") is not True for event in events):
                blockers.append(f"unsuccessful or inconsistent provenance event: {relative}")
                continue
            final = events[-1]
            current_hash = self._hash(resolved)
            if final.get("file_exists_after") != resolved.is_file() or final.get("content_hash_after") != current_hash:
                blockers.append(f"current content differs from final provenance hash: {relative}")
            if self._is_mixed(request, root, relative):
                blockers.append(f"mixed run provenance: {relative}")
            if not blockers or not any(relative in blocker for blocker in blockers):
                safe.append(path.as_posix())
        return tuple(safe), tuple(blockers)

    @staticmethod
    def _run_marker(run_id: str) -> str:
        return f"AI-Dev-Center-Run: {run_id}"

    def current_head(self, project_root) -> str | None:
        result = self._git(Path(project_root).resolve(), "rev-parse", "HEAD")
        return result.stdout.strip().lower() if result.returncode == 0 else None

    def recover_committed_result(self, request, baseline_head):
        """Adopt only a uniquely provable run-marked child of the saved baseline."""
        if self._gate_blockers(request) or not baseline_head:
            return None
        root = Path(request.project_root).resolve()
        repository = self._git(root, "rev-parse", "--show-toplevel")
        if repository.returncode:
            return None
        repo_root = Path(repository.stdout.strip()).resolve()
        marker = self._run_marker(request.run_id)
        listed = self._git(repo_root, "notes", "--ref=ai-dev-center", "list")
        candidates = tuple(
            fields[1] for line in listed.stdout.splitlines()
            if len(fields := line.split()) == 2
        ) if not listed.returncode else ()
        expected_paths = tuple(sorted(request.provenance))
        proven = []
        for candidate in candidates:
            parents = self._git(repo_root, "show", "-s", "--format=%P", candidate)
            note = self._git(repo_root, "notes", "--ref=ai-dev-center", "show", candidate)
            changed = self._git(repo_root, "diff-tree", "--no-commit-id", "--name-only", "-r", "-z", candidate)
            repo_paths = tuple(sorted((root / path).relative_to(repo_root).as_posix() for path in expected_paths))
            if parents.returncode or parents.stdout.strip().lower() != baseline_head.lower():
                continue
            if note.returncode or note.stdout.strip() != marker:
                continue
            if changed.returncode or tuple(sorted(self._nul_paths(changed.stdout))) != repo_paths:
                continue
            if self._commit_matches_provenance(repo_root, root, candidate, request.provenance):
                proven.append(candidate.lower())
        if len(proven) != 1:
            return None
        return GitCommitResult(
            request.run_id, "committed", request.commit_message,
            expected_paths, proven[0], ready_for_publish=True,
        )

    def _commit_matches_provenance(self, repo_root, root, commit, provenance):
        for relative, entry in provenance.items():
            events = entry.get("events") if isinstance(entry, dict) else None
            if not isinstance(entry, dict) or entry.get("project_root") != str(root) or not isinstance(events, list) or not events:
                return False
            final = events[-1]
            if not isinstance(final, dict):
                return False
            repo_path = (root / relative).relative_to(repo_root).as_posix()
            blob = self._git_bytes(repo_root, "show", f"{commit}:{repo_path}")
            if final.get("file_exists_after") is True:
                if blob.returncode or hashlib.sha256(blob.stdout).hexdigest() != final.get("content_hash_after"):
                    return False
            elif blob.returncode == 0:
                return False
        return True

    @staticmethod
    def _is_mixed(request: GitCommitRequest, root: Path, relative: str) -> bool:
        for run_id, entries in request.all_provenance.items():
            if run_id == request.run_id or not isinstance(entries, dict):
                continue
            other = entries.get(relative)
            if isinstance(other, dict) and other.get("project_root") == str(root):
                return True
        return False

    @staticmethod
    def _hash(path: Path) -> str | None:
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None

    @staticmethod
    def _nul_paths(output: str) -> tuple[str, ...]:
        return tuple(path for path in output.split("\0") if path)

    @staticmethod
    def _git(cwd: Path, *args: str):
        try:
            return subprocess.run(
                ["git", *args], cwd=cwd, capture_output=True, text=True, check=False,
            )
        except OSError as error:
            return subprocess.CompletedProcess(["git", *args], 1, "", str(error))

    @staticmethod
    def _git_bytes(cwd: Path, *args: str):
        try:
            return subprocess.run(
                ["git", *args], cwd=cwd, capture_output=True, check=False,
            )
        except OSError as error:
            return subprocess.CompletedProcess(["git", *args], 1, b"", str(error).encode())

    @staticmethod
    def _failed(request, blockers, error=None):
        return GitCommitResult(
            request.run_id, "failed", request.commit_message,
            blockers=tuple(blockers), error=error,
        )
