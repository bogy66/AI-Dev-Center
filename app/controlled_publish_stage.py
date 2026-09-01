"""Controlled publication of one persisted run commit to an existing remote."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
import subprocess


_REMOTE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_COMMIT_HASH = re.compile(r"[0-9a-fA-F]{40,64}\Z")


@dataclass(frozen=True)
class PublishRequest:
    run_id: str
    project_root: str | Path
    remote: str
    git_commit_status: str
    local_commit_hash: str | None
    ready_for_publish: bool
    publish_approval_status: str


@dataclass(frozen=True)
class PublishResult:
    run_id: str
    status: str
    local_commit_hash: str | None
    remote: str
    remote_ref: str | None = None
    published_commit_hash: str | None = None
    blockers: tuple[str, ...] = ()
    error: str | None = None

    def to_record(self) -> dict:
        record = asdict(self)
        record["blockers"] = list(self.blockers)
        return record

    @classmethod
    def from_record(cls, record: dict, *, status: str | None = None):
        return cls(
            run_id=record["run_id"],
            status=status or record["status"],
            local_commit_hash=record.get("local_commit_hash"),
            remote=record.get("remote", ""),
            remote_ref=record.get("remote_ref"),
            published_commit_hash=record.get("published_commit_hash"),
            blockers=tuple(record.get("blockers", ())),
            error=record.get("error"),
        )


class ControlledPublishStage:
    """Push exactly the persisted branch-tip commit without rewriting history."""

    def run(self, request: PublishRequest) -> PublishResult:
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

        remotes = self._git(repo_root, "remote")
        if remotes.returncode or request.remote not in remotes.stdout.splitlines():
            return self._failed(request, ("configured remote does not exist",))

        commit_hash = request.local_commit_hash.lower()
        exists = self._git(repo_root, "cat-file", "-e", f"{commit_hash}^{{commit}}")
        if exists.returncode:
            return self._failed(request, ("persisted run commit does not exist",))

        branch = self._git(repo_root, "symbolic-ref", "--quiet", "--short", "HEAD")
        if branch.returncode or not branch.stdout.strip():
            return self._failed(request, ("detached HEAD is not publishable",))
        branch_name = branch.stdout.strip()
        if self._git(repo_root, "check-ref-format", "--branch", branch_name).returncode:
            return self._failed(request, ("current branch name is invalid",))
        local_ref = f"refs/heads/{branch_name}"
        remote_ref = f"refs/heads/{branch_name}"

        tip = self._git(repo_root, "rev-parse", "--verify", local_ref)
        head = self._git(repo_root, "rev-parse", "--verify", "HEAD")
        if tip.returncode or head.returncode:
            return self._failed(request, ("branch tip could not be validated",))
        if tip.stdout.strip().lower() != commit_hash or head.stdout.strip().lower() != commit_hash:
            return self._failed(request, ("persisted run commit is not the current branch tip",))

        remote_hash = self._remote_hash(repo_root, request.remote, remote_ref)
        if remote_hash == commit_hash:
            return PublishResult(
                request.run_id, "already_published", commit_hash, request.remote,
                remote_ref, commit_hash,
            )

        refspec = f"{local_ref}:{remote_ref}"
        pushed = self._git(repo_root, "push", "--porcelain", "--", request.remote, refspec)
        if pushed.returncode:
            return self._failed(
                request, ("normal push failed",),
                f"git push failed with exit code {pushed.returncode}", remote_ref,
            )
        published_hash = self._remote_hash(repo_root, request.remote, remote_ref)
        if published_hash != commit_hash:
            return self._failed(
                request, ("remote ref verification failed",),
                "published commit could not be verified", remote_ref,
            )
        return PublishResult(
            request.run_id, "published", commit_hash, request.remote,
            remote_ref, commit_hash,
        )

    @staticmethod
    def _gate_blockers(request: PublishRequest) -> tuple[str, ...]:
        blockers = []
        if not isinstance(request.run_id, str) or not request.run_id.strip():
            blockers.append("run_id is required")
        if request.git_commit_status != "committed":
            blockers.append("successful GitCommitResult is required")
        if not isinstance(request.local_commit_hash, str) or not _COMMIT_HASH.fullmatch(request.local_commit_hash):
            blockers.append("valid persisted commit hash is required")
        if request.ready_for_publish is not True:
            blockers.append("ready_for_publish is not true")
        if request.publish_approval_status != "approved":
            blockers.append("publish human approval is not approved")
        if not request.project_root:
            blockers.append("explicit project_root is required")
        if not isinstance(request.remote, str) or not _REMOTE_NAME.fullmatch(request.remote):
            blockers.append("remote name is invalid")
        return tuple(blockers)

    def _remote_hash(self, root: Path, remote: str, remote_ref: str) -> str | None:
        result = self._git(root, "ls-remote", "--heads", "--", remote, remote_ref)
        if result.returncode:
            return None
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) == 2 and fields[1] == remote_ref and _COMMIT_HASH.fullmatch(fields[0]):
                return fields[0].lower()
        return None

    @staticmethod
    def _git(cwd: Path, *args: str):
        try:
            return subprocess.run(
                ["git", *args], cwd=cwd, capture_output=True, text=True, check=False,
            )
        except OSError as error:
            return subprocess.CompletedProcess(["git", *args], 1, "", str(error))

    @staticmethod
    def _failed(request, blockers, error=None, remote_ref=None):
        safe_remote = request.remote if isinstance(request.remote, str) and _REMOTE_NAME.fullmatch(request.remote) else ""
        return PublishResult(
            request.run_id, "failed", request.local_commit_hash, safe_remote,
            remote_ref=remote_ref, blockers=tuple(blockers), error=error,
        )
