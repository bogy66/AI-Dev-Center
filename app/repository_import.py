"""Import an existing remote Git repository as a normal ADC project.

CLONE -> VERIFY -> REGISTER. Nothing else. Cloning must never trigger any
repository code execution, dependency install, build, test, or LLM/provider
call: the imported repository is untrusted project content until a human
starts the normal ADC workflow on it explicitly.

This is a JUSTIFIED SPECIAL CASE relative to app.execution.execute_controlled:
that boundary confines execution to an *existing* project_root and validates
a registered capability for a project already known to ADC. Before a clone
succeeds there is no project_root and nothing to register yet, so this
module implements its own small, explicit, argv-only Git bootstrap step
instead - the same architectural pattern already used by
app.greenfield_project.GreenfieldProjectMaterializer for `git init`.

Provider-neutral by design: this module only ever validates a Git URL/SCP
form and hands it to `git clone`. It contains no GitHub-specific (or any
other provider-specific) logic or API integration.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path
from urllib.parse import urlparse

from app.project_context import ProjectDefinitionStore, ProjectRecord, ProjectRegistry


class RepositoryImportError(Exception):
    """Raised for any invalid source/destination or a failed/unsafe clone."""


_SCP_LIKE = re.compile(
    r"^[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+:[A-Za-z0-9_./~-]+$"
)
_ALLOWED_URL_SCHEMES = frozenset({"https", "ssh"})
_DANGEROUS_PREFIXES = ("ext:", "fd:", "file:", "vcs::", "ext::", "fd::")
_CREDENTIAL_URL_PATTERN = re.compile(r"https?://[^/\s]*:[^/\s]*@")

_DEFAULT_CLONE_TIMEOUT_SECONDS = 600
_VERIFY_TIMEOUT_SECONDS = 30

_import_lock_registry = threading.Lock()
_import_targets: set[str] = set()


@dataclass(frozen=True)
class RepositoryImportRequest:
    source: str
    destination_parent: str
    target_name: str | None = None


def _git_executable() -> str:
    found = shutil.which("git")
    if not found:
        raise RepositoryImportError("git executable was not found.")
    return found


def validate_repository_source(source: str) -> str:
    """Validate and normalize a Git repository source (URL or SCP form).

    Accepts https:// and ssh:// URLs and normal SCP-style SSH syntax
    (user@host:path). Rejects embedded-credential HTTPS URLs, external
    helper protocols (ext::, fd::, file://, ...), and anything that looks
    like a command-line flag rather than a source.
    """
    if not isinstance(source, str) or not source.strip():
        raise RepositoryImportError("Repository source is required.")
    src = source.strip()
    if any(ch in src for ch in ("\x00", "\n", "\r")):
        raise RepositoryImportError("Repository source contains invalid characters.")
    if src.startswith("-"):
        raise RepositoryImportError(
            "Repository source must not begin with '-'."
        )
    lowered = src.lower()
    if lowered.startswith(_DANGEROUS_PREFIXES):
        raise RepositoryImportError(
            "This repository source form is not permitted."
        )

    if re.match(r"^[A-Za-z][A-Za-z0-9+.\-]*://", src) is None:
        # No URL scheme present: only normal SCP-style SSH syntax is
        # accepted (e.g. git@github.com:owner/repository.git).
        if not _SCP_LIKE.match(src):
            raise RepositoryImportError(
                "Unrecognized repository source form. Use an https:// URL, "
                "an ssh:// URL, or SCP-style SSH syntax "
                "(user@host:owner/repository.git)."
            )
        return src

    parsed = urlparse(src)
    if parsed.scheme not in _ALLOWED_URL_SCHEMES:
        raise RepositoryImportError(
            f"Unsupported repository source scheme: '{parsed.scheme}'. "
            "Only https and ssh are supported."
        )
    if not parsed.netloc:
        raise RepositoryImportError("Repository source must include a host.")
    if parsed.password:
        raise RepositoryImportError(
            "Repository URLs with an embedded password/token are not "
            "permitted. Use normal Git credential-helper or SSH-agent "
            "authentication."
        )
    if parsed.scheme == "https" and parsed.username:
        # An HTTPS URL's "username" slot is commonly used to smuggle a
        # bare access token (e.g. https://<token>@host/...); SSH's
        # username slot is the normal, safe login-account form
        # (e.g. ssh://git@host/..., equivalent to SCP-style git@host:...)
        # and is intentionally not rejected here.
        raise RepositoryImportError(
            "Repository URLs with an embedded credential are not "
            "permitted. Use normal Git credential-helper authentication."
        )
    return src


def _derive_target_name(source: str) -> str:
    trimmed = source.strip().rstrip("/")
    tail = trimmed.split("/")[-1]
    if tail.endswith(".git"):
        tail = tail[:-4]
    tail = tail.strip()
    if not tail or tail in (".", "..") or "/" in tail or "\\" in tail or "\x00" in tail:
        raise RepositoryImportError(
            "Could not derive a safe target directory name from the source; "
            "please provide one explicitly."
        )
    return tail


def _validate_target_name(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise RepositoryImportError("Target directory name must not be empty.")
    candidate = name.strip()
    if candidate in (".", ".."):
        raise RepositoryImportError("Target directory name is invalid.")
    if "/" in candidate or "\\" in candidate or "\x00" in candidate:
        raise RepositoryImportError(
            "Target directory name must not contain path separators."
        )
    if Path(candidate).is_absolute():
        raise RepositoryImportError(
            "Target directory name must not be an absolute path."
        )
    return candidate


def _validated_destination(destination_parent: str, target_name: str) -> Path:
    if not isinstance(destination_parent, str) or not destination_parent.strip():
        raise RepositoryImportError("Destination parent directory is required.")
    try:
        parent = Path(destination_parent).expanduser().resolve(strict=True)
    except (FileNotFoundError, OSError, RuntimeError) as error:
        raise RepositoryImportError(
            "Destination parent directory does not exist."
        ) from error
    if not parent.is_dir():
        raise RepositoryImportError(
            "Destination parent must be an existing directory."
        )

    target = parent / target_name
    resolved_target = target.resolve()
    if resolved_target.parent != parent:
        raise RepositoryImportError(
            "Resolved target directory escapes the selected destination parent."
        )
    if resolved_target.exists():
        raise RepositoryImportError(
            f"Target directory already exists: {resolved_target}"
        )
    return resolved_target


_CLONE_ENV_EXACT_KEYS = ("PATH", "HOME", "USER", "SSH_AUTH_SOCK")
_CLONE_ENV_PREFIXES = ("LANG", "LC_")


def _clone_env() -> dict[str, str]:
    """Minimum environment required for normal Git authentication.

    Strictly an allowlist, not a general environment passthrough: only
    PATH/HOME/USER/SSH_AUTH_SOCK and LANG/LC_* are forwarded. Unrelated
    provider secrets are never inherited.

    GIT_SSH_COMMAND is deliberately excluded: Git's own documented
    semantics run its contents through a shell, which is incompatible
    with this module's argv-only execution claim. GIT_SSH (the older,
    non-shell mechanism) and GIT_ASKPASS/SSH_ASKPASS (arbitrary-helper
    invocation) are excluded too, for the same reason and because
    normal SSH authentication already works through ~/.ssh/config (via
    HOME) and an SSH agent (via SSH_AUTH_SOCK) without needing any of
    them. This is an allowlist, so anything not explicitly listed here
    is excluded by construction, not by a maintained denylist.
    """
    env: dict[str, str] = {}
    for key in _CLONE_ENV_EXACT_KEYS:
        value = os.environ.get(key)
        if value is not None:
            env[key] = value
    for key, value in os.environ.items():
        if any(key.startswith(prefix) for prefix in _CLONE_ENV_PREFIXES):
            env[key] = value
    return env


def _safe_stderr(stderr: str) -> str:
    text = (stderr or "").strip()
    text = _CREDENTIAL_URL_PATTERN.sub("https://[redacted-credentials]@", text)
    return text[:500]


def _acquire_import_lock(target_key: str) -> None:
    with _import_lock_registry:
        if target_key in _import_targets:
            raise RepositoryImportError(
                "An import is already in progress for this destination."
            )
        _import_targets.add(target_key)


def _release_import_lock(target_key: str) -> None:
    with _import_lock_registry:
        _import_targets.discard(target_key)


def _verify_cloned_repository(path: Path, source: str) -> None:
    if not path.is_dir():
        raise RepositoryImportError("Clone did not produce a directory.")
    if not (path / ".git").exists():
        raise RepositoryImportError("Clone did not produce a Git repository.")

    git_exe = _git_executable()
    work_tree_check = subprocess.run(
        [git_exe, "rev-parse", "--is-inside-work-tree"],
        cwd=str(path), capture_output=True, text=True,
        timeout=_VERIFY_TIMEOUT_SECONDS, check=False, env=_clone_env(),
    )
    if work_tree_check.returncode != 0 or work_tree_check.stdout.strip() != "true":
        raise RepositoryImportError("Cloned directory is not a valid Git work tree.")

    origin_check = subprocess.run(
        [git_exe, "remote", "get-url", "origin"],
        cwd=str(path), capture_output=True, text=True,
        timeout=_VERIFY_TIMEOUT_SECONDS, check=False, env=_clone_env(),
    )
    if origin_check.returncode != 0 or not origin_check.stdout.strip():
        raise RepositoryImportError("Cloned repository has no 'origin' remote.")
    if origin_check.stdout.strip() != source:
        raise RepositoryImportError(
            "Cloned repository's origin does not match the requested source."
        )


def _clone_into(source: str, staging_target: Path, parent: Path, timeout: int) -> None:
    git_exe = _git_executable()
    try:
        completed = subprocess.run(
            [
                git_exe,
                "-c", "protocol.ext.allow=never",
                "-c", "protocol.fd.allow=never",
                "-c", "protocol.file.allow=never",
                "clone", "--no-tags", "--",
                source, str(staging_target),
            ],
            cwd=str(parent), capture_output=True, text=True,
            timeout=timeout, check=False, env=_clone_env(),
        )
    except subprocess.TimeoutExpired as error:
        raise RepositoryImportError(
            f"git clone timed out after {timeout} seconds."
        ) from error
    if completed.returncode != 0:
        raise RepositoryImportError(
            f"git clone failed: {_safe_stderr(completed.stderr)}"
        )


def _stage_clone_finalize_and_register(
    validated_source: str, resolved_target: Path, parent: Path, name: str,
    timeout: int, clone_fn, registry: ProjectRegistry,
) -> ProjectRecord:
    """Stage -> clone -> verify staging -> move -> verify final -> register.

    clone_fn is a (source, staging_target, parent, timeout) -> None
    dependency-injection seam, exactly like this codebase's existing
    CommandRunner seams (PythonPackageExecutor, ProjectTestRunner): the
    productive default is always the real, fully-restricted _clone_into.
    Only tests substitute it, to exercise this real transactional/
    verification/registration engine against a real local Git source,
    since production's own protocol restrictions correctly refuse to
    clone a local path at all (see tests/test_repository_import.py for
    why that split is necessary and what it does and does not prove).

    Rollback contract: once this call has moved its own staging clone
    into resolved_target, ANY subsequent failure here (final-target
    verification, or ProjectRegistry.register() raising) removes that
    same final target before propagating the error. This invocation may
    only ever delete resolved_target because it independently confirmed,
    immediately before its own move, that resolved_target did not yet
    exist and that this move is what created it — never a pre-existing
    path, and never anything this invocation did not itself create.
    """
    if resolved_target.exists():
        raise RepositoryImportError(
            f"Target directory already exists: {resolved_target}"
        )

    staging = Path(tempfile.mkdtemp(prefix=".adc-import-", dir=str(parent)))
    moved_by_this_call = False
    try:
        staging_target = staging / name
        clone_fn(validated_source, staging_target, parent, timeout)
        _verify_cloned_repository(staging_target, validated_source)

        if resolved_target.exists():
            raise RepositoryImportError(
                f"Target directory already exists: {resolved_target}"
            )
        shutil.move(str(staging_target), str(resolved_target))
        moved_by_this_call = True

        # Final-target verification: re-checked through the actual
        # resolved final path, not merely reusing the pre-move staging
        # result, so nothing about the move itself can go unnoticed.
        _verify_cloned_repository(resolved_target, validated_source)

        return registry.register(str(resolved_target), display_name=name)
    except BaseException:
        if moved_by_this_call:
            shutil.rmtree(resolved_target, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def import_repository(
    source: str,
    destination_parent: str,
    target_name: str | None = None,
    *,
    timeout: int = _DEFAULT_CLONE_TIMEOUT_SECONDS,
    registry: ProjectRegistry | None = None,
    _clone_fn=None,
) -> ProjectRecord:
    """Clone a repository and register it as a normal active ADC project.

    Transaction: VALIDATE -> acquire target lock -> stage in an
    ADC-owned temp dir inside the destination parent -> clone -> verify
    staging -> move into place -> verify final target -> register ->
    release target lock. The lock is held across the entire
    finalization, including registration, so a same-target import can
    never observe or race a half-finished transaction. Any failure
    after the move (final-target verification, or a ProjectRegistry
    conflict/exception) removes the final target this invocation
    created and leaves no ProjectRegistry entry; a failure before the
    move leaves no final directory at all. Only importer-created
    temporary staging content — and, on post-move failure, the final
    target this exact call created — is ever removed; no pre-existing
    path is ever touched.

    _clone_fn is an internal test seam only (see
    _stage_clone_finalize_and_register); productive callers must never
    pass it. Resolved at call time (not as an early-bound default) so
    tests may also monkeypatch the module-level _clone_into directly.
    """
    validated_source = validate_repository_source(source)
    name = _validate_target_name(target_name) if target_name else _derive_target_name(validated_source)
    resolved_target = _validated_destination(destination_parent, name)
    parent = resolved_target.parent
    clone_fn = _clone_fn if _clone_fn is not None else _clone_into
    active_registry = registry or ProjectRegistry(ProjectDefinitionStore())

    target_key = str(resolved_target)
    _acquire_import_lock(target_key)
    try:
        return _stage_clone_finalize_and_register(
            validated_source, resolved_target, parent, name, timeout,
            clone_fn, active_registry,
        )
    finally:
        _release_import_lock(target_key)
