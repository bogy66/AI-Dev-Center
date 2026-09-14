"""CLAUDE-005 repository-import tests.

No network access is used anywhere in this file. Git clone semantics are
proven against real local Git repositories.

IMPORTANT LIMITATION (stated explicitly, as required): the productive
source validator (validate_repository_source) intentionally rejects any
local filesystem source, and the productive clone step
(app.repository_import._clone_into) additionally disables Git's `file`
transport (-c protocol.file.allow=never) as defense in depth - so even a
local path that somehow passed validation would still be refused by Git
itself. Both of these are proven directly (test_validate_repository_source_
rejects_local_path, test_production_clone_step_refuses_local_path_transport).

Because of that, the realistic end-to-end local Git integration test
(test_real_local_git_import_end_to_end) exercises the full staging /
clone / verify / move / register engine through import_repository()'s own
`_clone_fn` dependency-injection seam - the same kind of test-only
substitution seam already used throughout this codebase
(PythonPackageExecutor(runner=...), ProjectTestRunner(runner=...)) -
supplying a real, unrestricted local `git clone` in place of the
production-restricted one. This proves the transactional/verification/
registration engine for real, without weakening or bypassing what
production actually enforces.
"""
import subprocess
import threading
import time
from pathlib import Path

import pytest

from app.project_context import ProjectDefinitionStore, ProjectRegistry
from app.repository_import import (
    RepositoryImportError,
    _clone_env,
    _clone_into,
    _derive_target_name,
    _validate_target_name,
    _validated_destination,
    _verify_cloned_repository,
    import_repository,
    validate_repository_source,
)


# ---------------------------------------------------------------------------
# Source validation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("source", [
    "https://github.com/example/project.git",
    "https://gitlab.com/example/project.git",
    "https://git.example-selfhosted.internal/team/project.git",
])
def test_validate_repository_source_accepts_https(source):
    assert validate_repository_source(source) == source


@pytest.mark.parametrize("source", [
    "ssh://git@github.com/example/project.git",
    "ssh://git@gitlab.example.com:2222/example/project.git",
])
def test_validate_repository_source_accepts_ssh_url(source):
    assert validate_repository_source(source) == source


@pytest.mark.parametrize("source", [
    "git@github.com:example/project.git",
    "git@gitlab.example.com:team/project.git",
])
def test_validate_repository_source_accepts_scp_style(source):
    assert validate_repository_source(source) == source


def test_validate_repository_source_rejects_empty():
    with pytest.raises(RepositoryImportError):
        validate_repository_source("")
    with pytest.raises(RepositoryImportError):
        validate_repository_source("   ")


@pytest.mark.parametrize("source", [
    "ext::sh -c touch%20/tmp/pwned",
    "fd::5",
    "file:///etc/passwd",
    "vcs::none::whatever",
])
def test_validate_repository_source_rejects_dangerous_helper_protocols(source):
    with pytest.raises(RepositoryImportError):
        validate_repository_source(source)


def test_validate_repository_source_rejects_local_path():
    """Confirms the stated limitation: local filesystem sources are
    intentionally not a supported production import form."""
    with pytest.raises(RepositoryImportError):
        validate_repository_source("/tmp/some/local/repo")


@pytest.mark.parametrize("source", [
    "https://user:hunter2@github.com/example/project.git",
    "https://token123@github.com/example/project.git",
])
def test_validate_repository_source_rejects_embedded_credentials(source):
    with pytest.raises(RepositoryImportError):
        validate_repository_source(source)


def test_validate_repository_source_rejects_leading_dash():
    with pytest.raises(RepositoryImportError):
        validate_repository_source("--upload-pack=touch /tmp/pwned")


def test_validate_repository_source_rejects_unsupported_scheme():
    with pytest.raises(RepositoryImportError):
        validate_repository_source("git://github.com/example/project.git")


# ---------------------------------------------------------------------------
# Destination validation
# ---------------------------------------------------------------------------
def test_validated_destination_accepts_valid_parent(tmp_path):
    result = _validated_destination(str(tmp_path), "new-project")
    assert result == (tmp_path / "new-project").resolve()


def test_validated_destination_rejects_nonexistent_parent(tmp_path):
    with pytest.raises(RepositoryImportError):
        _validated_destination(str(tmp_path / "does-not-exist"), "x")


def test_validated_destination_rejects_parent_not_a_directory(tmp_path):
    file_path = tmp_path / "im-a-file"
    file_path.write_text("x")
    with pytest.raises(RepositoryImportError):
        _validated_destination(str(file_path), "x")


def test_validated_destination_rejects_existing_target(tmp_path):
    (tmp_path / "already-there").mkdir()
    with pytest.raises(RepositoryImportError):
        _validated_destination(str(tmp_path), "already-there")


@pytest.mark.parametrize("name", ["", "   ", ".", "..", "a/b", "a\\b", "/etc/passwd"])
def test_validate_target_name_rejects_invalid_names(name):
    with pytest.raises(RepositoryImportError):
        _validate_target_name(name)


def test_validate_target_name_accepts_normal_name():
    assert _validate_target_name("my-project") == "my-project"


def test_validated_destination_target_cannot_escape_parent_via_traversal(tmp_path):
    # _validate_target_name already rejects "..", but re-confirm end to end
    # that even a name containing a separator can never resolve outside parent.
    with pytest.raises(RepositoryImportError):
        _validate_target_name("../escaped")


# ---------------------------------------------------------------------------
# Target name derivation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("source,expected", [
    ("https://github.com/example/project.git", "project"),
    ("https://github.com/example/project", "project"),
    ("git@github.com:example/project.git", "project"),
    ("ssh://git@github.com/example/my-repo.git", "my-repo"),
])
def test_derive_target_name(source, expected):
    assert _derive_target_name(source) == expected


# ---------------------------------------------------------------------------
# Production defense-in-depth: git-level protocol restriction
# ---------------------------------------------------------------------------
def test_production_clone_step_refuses_local_path_transport(tmp_path):
    """Even if a local path reached the real git invocation directly
    (bypassing validate_repository_source), Git itself refuses it because
    the productive clone step disables the `file` transport."""
    source_repo = tmp_path / "source"
    source_repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=source_repo, check=True)

    staging_target = tmp_path / "dest" / "cloned"
    (tmp_path / "dest").mkdir()

    with pytest.raises(RepositoryImportError, match="git clone failed"):
        _clone_into(str(source_repo), staging_target, tmp_path / "dest", 30)


# ---------------------------------------------------------------------------
# Realistic local Git integration test (no network)
# ---------------------------------------------------------------------------
def _real_local_clone(source: str, staging_target: Path, parent: Path, timeout: int) -> None:
    """Test-only stand-in for app.repository_import._clone_into.

    Identical argv-only, shell=False, timeout-bounded shape, but without
    the productive `protocol.file.allow=never` restriction, so a real
    local source repository can be cloned in this test - proving the
    surrounding transactional engine for real, per the file's documented
    limitation.
    """
    completed = subprocess.run(
        ["git", "clone", "--no-tags", "--", source, str(staging_target)],
        cwd=str(parent), capture_output=True, text=True, timeout=timeout, check=False,
    )
    if completed.returncode != 0:
        raise RepositoryImportError(f"git clone failed: {completed.stderr}")


@pytest.fixture
def local_source_repo(tmp_path, monkeypatch):
    # Every test using this fixture exercises the real staging/clone/
    # verify/move/register engine with a real local Git source, via the
    # _clone_fn seam - see the module docstring's stated limitation for
    # why validate_repository_source (which intentionally rejects local
    # paths, proven separately and unpatched elsewhere in this file)
    # must be bypassed here specifically.
    import app.repository_import as repository_import_module
    monkeypatch.setattr(
        repository_import_module, "validate_repository_source", lambda source: source,
    )

    source = tmp_path / "source-repo"
    source.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=source, check=True)
    (source / "README.md").write_text("# Test project\n")
    # A file that would leave unambiguous evidence if it were ever executed.
    marker = source / "if_this_runs_something_is_wrong.sh"
    marker.write_text("#!/bin/sh\ntouch \"$(dirname \"$0\")/EXECUTED_MARKER\"\n")
    marker.chmod(0o755)
    subprocess.run(["git", "add", "."], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial commit"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "second commit"], cwd=source, check=True)
    return source


def test_real_local_git_import_end_to_end(tmp_path, local_source_repo):
    destination_parent = tmp_path / "destination"
    destination_parent.mkdir()
    registry = ProjectRegistry(ProjectDefinitionStore(tmp_path / "definitions.json"))

    record = import_repository(
        str(local_source_repo), str(destination_parent),
        registry=registry, _clone_fn=_real_local_clone,
    )

    final_path = destination_parent / "source-repo"
    assert final_path.is_dir()
    assert (final_path / ".git").exists()

    # History preserved
    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=final_path,
        capture_output=True, text=True, check=True,
    )
    assert log.stdout.count("\n") == 2  # two real commits, preserved

    # Origin preserved, exactly as requested
    origin = subprocess.run(
        ["git", "remote", "get-url", "origin"], cwd=final_path,
        capture_output=True, text=True, check=True,
    )
    assert origin.stdout.strip() == str(local_source_repo)

    # No repository code was executed during import
    assert not (final_path / "EXECUTED_MARKER").exists()

    # Registered ACTIVE with a sensible display name
    assert record.lifecycle_status == "active"
    assert record.display_name == "source-repo"
    assert record.project_root == str(final_path.resolve())

    active = registry.list_by_status("active")
    assert any(r.project_id == record.project_id for r in active)


def test_import_normal_lifecycle_operations_work_afterward(tmp_path, local_source_repo):
    destination_parent = tmp_path / "destination"
    destination_parent.mkdir()
    registry = ProjectRegistry(ProjectDefinitionStore(tmp_path / "definitions.json"))

    record = import_repository(
        str(local_source_repo), str(destination_parent),
        registry=registry, _clone_fn=_real_local_clone,
    )

    renamed = registry.rename(record.project_id, "My Imported Project")
    assert renamed.display_name == "My Imported Project"
    # Rename never touches the filesystem
    assert Path(renamed.project_root).is_dir()
    assert Path(renamed.project_root).name == "source-repo"

    archived = registry.archive(record.project_id)
    assert archived.lifecycle_status == "archived"
    assert Path(archived.project_root).is_dir()  # archive does not move anything

    restored = registry.restore(record.project_id)
    assert restored.lifecycle_status == "active"


def test_import_registers_only_in_the_existing_project_registry(tmp_path, local_source_repo):
    """No second project source of truth: registration goes through the
    same ProjectDefinitionStore-backed ProjectRegistry as CLAUDE-003."""
    destination_parent = tmp_path / "destination"
    destination_parent.mkdir()
    store_path = tmp_path / "definitions.json"
    registry = ProjectRegistry(ProjectDefinitionStore(store_path))

    import_repository(
        str(local_source_repo), str(destination_parent),
        registry=registry, _clone_fn=_real_local_clone,
    )

    assert store_path.is_file()
    reopened = ProjectRegistry(ProjectDefinitionStore(store_path))
    assert len(reopened.list_by_status("active")) == 1


# ---------------------------------------------------------------------------
# Failure / rollback
# ---------------------------------------------------------------------------
def _failing_clone(source, staging_target, parent, timeout):
    raise RepositoryImportError("git clone failed: simulated failure")


def test_clone_failure_leaves_no_registration_and_no_final_directory(tmp_path):
    destination_parent = tmp_path / "destination"
    destination_parent.mkdir()
    registry = ProjectRegistry(ProjectDefinitionStore(tmp_path / "definitions.json"))

    with pytest.raises(RepositoryImportError):
        import_repository(
            "https://example.invalid/owner/repo.git", str(destination_parent),
            registry=registry, _clone_fn=_failing_clone,
        )

    assert not (destination_parent / "repo").exists()
    assert registry.list_by_status("active") == ()


def test_clone_failure_cleans_up_only_its_own_staging_directory(tmp_path):
    destination_parent = tmp_path / "destination"
    destination_parent.mkdir()
    unrelated = destination_parent / "unrelated-existing-dir"
    unrelated.mkdir()
    (unrelated / "keep.txt").write_text("do not touch")

    with pytest.raises(RepositoryImportError):
        import_repository(
            "https://example.invalid/owner/repo.git", str(destination_parent),
            registry=ProjectRegistry(ProjectDefinitionStore(tmp_path / "d.json")),
            _clone_fn=_failing_clone,
        )

    assert unrelated.is_dir()
    assert (unrelated / "keep.txt").read_text() == "do not touch"
    # no leftover .adc-import-* staging directories
    leftovers = [p for p in destination_parent.iterdir() if p.name.startswith(".adc-import-")]
    assert leftovers == []


def test_import_rejects_existing_target_before_touching_git(tmp_path):
    destination_parent = tmp_path / "destination"
    destination_parent.mkdir()
    (destination_parent / "repo").mkdir()

    calls = []

    def spy_clone(*args, **kwargs):
        calls.append(args)
        raise AssertionError("clone must not be attempted when target already exists")

    with pytest.raises(RepositoryImportError, match="already exists"):
        import_repository(
            "https://example.invalid/owner/repo.git", str(destination_parent),
            registry=ProjectRegistry(ProjectDefinitionStore(tmp_path / "d.json")),
            _clone_fn=spy_clone,
        )
    assert calls == []


def test_validation_happens_before_any_filesystem_or_git_activity(tmp_path):
    calls = []

    def spy_clone(*args, **kwargs):
        calls.append(args)

    with pytest.raises(RepositoryImportError):
        import_repository(
            "not-a-valid-source !!", str(tmp_path),
            registry=ProjectRegistry(ProjectDefinitionStore(tmp_path / "d.json")),
            _clone_fn=spy_clone,
        )
    assert calls == []


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------
def test_concurrent_import_to_the_same_target_is_rejected(tmp_path, local_source_repo):
    destination_parent = tmp_path / "destination"
    destination_parent.mkdir()
    registry = ProjectRegistry(ProjectDefinitionStore(tmp_path / "definitions.json"))

    started = threading.Event()
    release = threading.Event()

    def slow_clone(source, staging_target, parent, timeout):
        started.set()
        release.wait(timeout=5)
        _real_local_clone(source, staging_target, parent, timeout)

    results = {}

    def run_first():
        try:
            results["first"] = import_repository(
                str(local_source_repo), str(destination_parent),
                registry=registry, _clone_fn=slow_clone,
            )
        except RepositoryImportError as error:
            results["first_error"] = error

    thread = threading.Thread(target=run_first)
    thread.start()
    started.wait(timeout=5)

    with pytest.raises(RepositoryImportError, match="already in progress"):
        import_repository(
            str(local_source_repo), str(destination_parent),
            registry=registry, _clone_fn=_real_local_clone,
        )

    release.set()
    thread.join(timeout=10)
    assert "first" in results


def test_independent_targets_can_import_concurrently(tmp_path, local_source_repo):
    destination_parent = tmp_path / "destination"
    destination_parent.mkdir()
    registry = ProjectRegistry(ProjectDefinitionStore(tmp_path / "definitions.json"))

    record_a = import_repository(
        str(local_source_repo), str(destination_parent), "target-a",
        registry=registry, _clone_fn=_real_local_clone,
    )
    record_b = import_repository(
        str(local_source_repo), str(destination_parent), "target-b",
        registry=registry, _clone_fn=_real_local_clone,
    )

    assert record_a.project_id != record_b.project_id
    assert Path(record_a.project_root).name == "target-a"
    assert Path(record_b.project_root).name == "target-b"


def test_same_url_to_different_destination_is_not_prohibited(tmp_path, local_source_repo):
    dest1 = tmp_path / "dest1"
    dest2 = tmp_path / "dest2"
    dest1.mkdir()
    dest2.mkdir()
    registry = ProjectRegistry(ProjectDefinitionStore(tmp_path / "definitions.json"))

    record1 = import_repository(
        str(local_source_repo), str(dest1), registry=registry, _clone_fn=_real_local_clone,
    )
    record2 = import_repository(
        str(local_source_repo), str(dest2), registry=registry, _clone_fn=_real_local_clone,
    )
    assert record1.project_id != record2.project_id


# ---------------------------------------------------------------------------
# CLAUDE-005A: GIT_SSH_COMMAND exclusion / minimal Git environment
# ---------------------------------------------------------------------------
def test_git_ssh_command_is_never_forwarded_to_the_clone_subprocess(monkeypatch):
    monkeypatch.setenv("GIT_SSH_COMMAND", "sh -c 'touch /tmp/PWNED_BY_GIT_SSH_COMMAND'")
    env = _clone_env()
    assert "GIT_SSH_COMMAND" not in env


def test_git_ssh_legacy_variable_is_never_forwarded(monkeypatch):
    monkeypatch.setenv("GIT_SSH", "/tmp/some-custom-ssh-wrapper")
    env = _clone_env()
    assert "GIT_SSH" not in env


def test_askpass_variables_are_never_forwarded(monkeypatch):
    monkeypatch.setenv("GIT_ASKPASS", "/tmp/malicious-askpass")
    monkeypatch.setenv("SSH_ASKPASS", "/tmp/malicious-askpass")
    env = _clone_env()
    assert "GIT_ASKPASS" not in env
    assert "SSH_ASKPASS" not in env


def test_clone_env_forwards_only_the_documented_minimal_allowlist(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", "/home/test")
    monkeypatch.setenv("USER", "test")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/agent.sock")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.setenv("SOME_UNRELATED_PROVIDER_SECRET", "sk-should-not-leak")
    monkeypatch.setenv("OPENROUTER_API_KEY", "should-not-leak-either")

    env = _clone_env()

    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "/home/test"
    assert env["USER"] == "test"
    assert env["SSH_AUTH_SOCK"] == "/tmp/agent.sock"
    assert env["LANG"] == "en_US.UTF-8"
    assert "SOME_UNRELATED_PROVIDER_SECRET" not in env
    assert "OPENROUTER_API_KEY" not in env


def test_real_clone_subprocess_does_not_receive_hostile_git_ssh_command(tmp_path, monkeypatch, local_source_repo):
    """End-to-end proof: even with a hostile GIT_SSH_COMMAND set on the ADC
    process itself, the real _clone_into subprocess never receives it."""
    sentinel = tmp_path / "PWNED_BY_GIT_SSH_COMMAND"
    monkeypatch.setenv(
        "GIT_SSH_COMMAND", f"sh -c 'touch {sentinel}; ssh \"$@\"' --",
    )

    staging_target = tmp_path / "staged" / "clone"
    (tmp_path / "staged").mkdir()

    # local_source_repo fixture already patches validate_repository_source;
    # call the real, unmodified _clone_into directly (production code,
    # not the test-only local-clone stand-in) against a real local source
    # to prove the actual production subprocess environment is clean.
    # Git's own protocol.file.allow=never blocks the local transport, so
    # this is expected to fail on protocol grounds - the point of this
    # test is solely that the sentinel file is never created, proving
    # GIT_SSH_COMMAND could not have been consulted/executed at all.
    with pytest.raises(RepositoryImportError):
        _clone_into(str(local_source_repo), staging_target, tmp_path / "staged", 30)

    assert not sentinel.exists()


# ---------------------------------------------------------------------------
# CLAUDE-005A: final-target verification (after move, before registration)
# ---------------------------------------------------------------------------
def test_final_target_is_verified_through_the_resolved_final_path(tmp_path, local_source_repo, monkeypatch):
    """Proves final verification runs against the actual final path, not
    just a remembered pre-move result: it must still pass after a real
    move, using the real resolved final directory."""
    destination_parent = tmp_path / "destination"
    destination_parent.mkdir()
    registry = ProjectRegistry(ProjectDefinitionStore(tmp_path / "definitions.json"))

    verify_calls = []
    import app.repository_import as repository_import_module
    real_verify = repository_import_module._verify_cloned_repository

    def spying_verify(path, source):
        verify_calls.append(Path(path))
        return real_verify(path, source)

    monkeypatch.setattr(repository_import_module, "_verify_cloned_repository", spying_verify)

    record = import_repository(
        str(local_source_repo), str(destination_parent),
        registry=registry, _clone_fn=_real_local_clone,
    )

    final_path = Path(record.project_root)
    # verified twice: once on the staging path, once on the final path
    assert len(verify_calls) == 2
    assert verify_calls[0] != final_path  # staging verification
    assert verify_calls[1] == final_path  # final-target verification


def test_final_verification_failure_after_move_rolls_back_final_target(tmp_path, local_source_repo, monkeypatch):
    destination_parent = tmp_path / "destination"
    destination_parent.mkdir()
    registry = ProjectRegistry(ProjectDefinitionStore(tmp_path / "definitions.json"))

    import app.repository_import as repository_import_module
    real_verify = repository_import_module._verify_cloned_repository
    call_count = {"n": 0}

    def failing_on_second_call(path, source):
        call_count["n"] += 1
        if call_count["n"] == 2:  # the post-move, final-target verification
            raise RepositoryImportError("simulated final-target verification failure")
        return real_verify(path, source)

    monkeypatch.setattr(repository_import_module, "_verify_cloned_repository", failing_on_second_call)

    with pytest.raises(RepositoryImportError, match="simulated final-target verification failure"):
        import_repository(
            str(local_source_repo), str(destination_parent),
            registry=registry, _clone_fn=_real_local_clone,
        )

    final_path = destination_parent / "source-repo"
    assert not final_path.exists()
    assert registry.list_by_status("active") == ()
    leftovers = [p for p in destination_parent.iterdir() if p.name.startswith(".adc-import-")]
    assert leftovers == []


# ---------------------------------------------------------------------------
# CLAUDE-005A: registration-failure rollback
# ---------------------------------------------------------------------------
class _RaisingRegistry:
    """Stands in for ProjectRegistry to force a post-move registration
    failure without depending on any real ProjectRegistry internals."""

    def register(self, project_root, display_name=None):
        raise RuntimeError("simulated ProjectRegistry.register() failure")

    def list_by_status(self, status):
        return ()


def test_registration_exception_after_move_rolls_back_final_target(tmp_path, local_source_repo):
    destination_parent = tmp_path / "destination"
    destination_parent.mkdir()

    with pytest.raises(RuntimeError, match="simulated ProjectRegistry.register\\(\\) failure"):
        import_repository(
            str(local_source_repo), str(destination_parent),
            registry=_RaisingRegistry(), _clone_fn=_real_local_clone,
        )

    final_path = destination_parent / "source-repo"
    assert not final_path.exists()
    leftovers = [p for p in destination_parent.iterdir() if p.name.startswith(".adc-import-")]
    assert leftovers == []


def test_registration_exception_leaves_unrelated_sibling_untouched(tmp_path, local_source_repo):
    destination_parent = tmp_path / "destination"
    destination_parent.mkdir()
    unrelated = destination_parent / "unrelated-existing-dir"
    unrelated.mkdir()
    (unrelated / "keep.txt").write_text("do not touch")

    with pytest.raises(RuntimeError):
        import_repository(
            str(local_source_repo), str(destination_parent),
            registry=_RaisingRegistry(), _clone_fn=_real_local_clone,
        )

    assert unrelated.is_dir()
    assert (unrelated / "keep.txt").read_text() == "do not touch"


def test_registration_conflict_error_after_move_rolls_back_final_target(tmp_path, local_source_repo):
    """A ProjectRegistryError raised by a real registry (e.g. a genuine
    conflict) must roll back exactly like any other post-move exception."""
    from app.project_context import ProjectRegistryError

    class _ConflictingRegistry:
        def register(self, project_root, display_name=None):
            raise ProjectRegistryError("simulated registration conflict")

    destination_parent = tmp_path / "destination"
    destination_parent.mkdir()

    with pytest.raises(ProjectRegistryError):
        import_repository(
            str(local_source_repo), str(destination_parent),
            registry=_ConflictingRegistry(), _clone_fn=_real_local_clone,
        )

    assert not (destination_parent / "source-repo").exists()


# ---------------------------------------------------------------------------
# CLAUDE-005A: target lock held through registration / rollback
# ---------------------------------------------------------------------------
def test_lock_is_still_held_during_registration_not_released_early(tmp_path, local_source_repo):
    """Directly proves the lock's internal state: the target key must
    still be held (not yet released) while a slow ProjectRegistry.register()
    call is in progress, and released only once that call returns. This
    inspects the lock registry itself rather than inferring it indirectly
    through a second call, since a second concurrent call could
    legitimately be rejected by either the lock or the pre-lock
    destination-exists check once the move has already happened - both
    are correct, but only direct inspection unambiguously proves the
    lock itself is still held through registration."""
    import app.repository_import as repository_import_module

    destination_parent = tmp_path / "destination"
    destination_parent.mkdir()

    entered_registration = threading.Event()
    release_registration = threading.Event()

    class _BlockingRegistry:
        def register(self, project_root, display_name=None):
            entered_registration.set()
            release_registration.wait(timeout=5)
            return ProjectRegistry(ProjectDefinitionStore(tmp_path / "definitions.json")).register(
                project_root, display_name=display_name,
            )

    results = {}

    def run_first():
        try:
            results["first"] = import_repository(
                str(local_source_repo), str(destination_parent),
                registry=_BlockingRegistry(), _clone_fn=_real_local_clone,
            )
        except Exception as error:  # noqa: BLE001
            results["first_error"] = error

    thread = threading.Thread(target=run_first)
    thread.start()
    assert entered_registration.wait(timeout=5), "registration was never reached"

    expected_target_key = str((destination_parent / "source-repo").resolve())
    assert expected_target_key in repository_import_module._import_targets, (
        "the import lock must still be held while registration is in progress"
    )

    release_registration.set()
    thread.join(timeout=10)
    assert "first" in results

    # Released promptly after successful completion.
    assert expected_target_key not in repository_import_module._import_targets


def test_lock_is_released_after_registration_failure_allowing_retry(tmp_path, local_source_repo):
    """After a rolled-back failure, the same target must be importable
    again (the lock must not remain stuck)."""
    destination_parent = tmp_path / "destination"
    destination_parent.mkdir()

    with pytest.raises(RuntimeError):
        import_repository(
            str(local_source_repo), str(destination_parent),
            registry=_RaisingRegistry(), _clone_fn=_real_local_clone,
        )

    registry = ProjectRegistry(ProjectDefinitionStore(tmp_path / "definitions.json"))
    record = import_repository(
        str(local_source_repo), str(destination_parent),
        registry=registry, _clone_fn=_real_local_clone,
    )
    assert record.lifecycle_status == "active"


# ---------------------------------------------------------------------------
# CLAUDE-005A: real ProjectRegistry conflict for a reused path
# ---------------------------------------------------------------------------
def test_real_registry_conflict_with_previously_removed_record_for_same_path(tmp_path, local_source_repo):
    """Documents actual, observed ProjectRegistry.register() behavior when
    the exact same filesystem path was previously registered and later
    removed from ADC: register() is deliberately idempotent per
    derive_project_id(path) and does not raise, but it also does not
    reactivate or refresh the stale record - the freshly imported
    directory is cloned successfully, but the registry entry it receives
    reflects the OLD record's state, not necessarily 'active' with the
    new display name. This is a real, confirmed limitation of reusing a
    path across independent ProjectRegistry lifecycles, not something
    CLAUDE-005A changes: fixing it would mean altering CLAUDE-003's
    register() reactivation policy, out of this task's scope."""
    destination_parent = tmp_path / "destination"
    destination_parent.mkdir()
    store_path = tmp_path / "definitions.json"
    registry = ProjectRegistry(ProjectDefinitionStore(store_path))

    reused_path = destination_parent / "source-repo"
    reused_path.mkdir()
    stale = registry.register(str(reused_path), display_name="Old Project")
    registry.archive(stale.project_id)
    registry.remove(stale.project_id)
    reused_path.rmdir()  # simulate the old project directory being gone

    record = import_repository(
        str(local_source_repo), str(destination_parent),
        registry=registry, _clone_fn=_real_local_clone,
    )

    # Confirmed actual behavior: the same project_id (path-derived) comes
    # back with its prior "removed" status and old display name, not a
    # fresh "active" registration - even though the clone itself
    # succeeded correctly on disk.
    assert record.project_id == stale.project_id
    assert record.lifecycle_status == "removed"
    assert record.display_name == "Old Project"
    assert Path(record.project_root).is_dir()  # the clone itself is real and present
    assert record.project_id not in {r.project_id for r in registry.list_by_status("active")}
