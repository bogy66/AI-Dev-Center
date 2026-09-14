import hashlib
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest

from app.change_provenance import RunChangeProvenance
from app.controlled_git_stage import ControlledGitStage, GitCommitRequest
from app.developer_file_applier import DeveloperFileApplier
from app.project_setup_application import ProjectSetupApplicationService
from app.workflow_manager import WorkflowManager


def _git(root, *args, check=True):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=check,
        capture_output=True, text=True,
    )


def _repo(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Controlled Test")
    path = tmp_path / "src" / "run.txt"
    path.parent.mkdir()
    path.write_text("before\n", encoding="utf-8")
    _git(tmp_path, "add", "--", "src/run.txt")
    _git(tmp_path, "commit", "-m", "initial")
    return path


def _approved_service(tmp_path, *, content="after\n", run_id="run-1", pre_baseline=None, post_baseline=None):
    """pre_baseline(tmp_path) runs BEFORE the run's working-tree baseline
    is captured -- anything it creates/modifies is pre-existing foreign
    content, safe to leave untouched (CLAUDE-E2E-NIO-006B Part 5.2/5.3).
    post_baseline(tmp_path) runs AFTER the baseline is captured -- a
    genuinely new, run-introduced change that must block delivery if it
    is not part of the approved provenance (Part 5.4)."""
    path = _repo(tmp_path)
    # CLAUDE-E2E-NIO-006A: ADC's own bookkeeping (WorkflowManager state)
    # lives in ADC's own installation working directory in real
    # production (canonical_composition.py's bare WorkflowManager()
    # default), never inside the separate, user-owned project directory
    # commit_approved_run() actually commits from -- mirrored here via a
    # sibling path outside the git-tracked project root, exactly like
    # tests/real_system/real_system_e2e.py's own owned/project split.
    # Colocating it inside tmp_path (the project's own git repo root, as
    # this helper previously did) is a test-fixture artifact that made
    # ADC's own state file itself look like an unaccounted working-tree
    # change once commit_approved_run() started checking for those.
    manager = WorkflowManager(tmp_path.parent / f"{tmp_path.name}-workflow-state.json")
    recorder = RunChangeProvenance(manager, run_id, tmp_path)
    if pre_baseline is not None:
        pre_baseline(tmp_path)
    # CLAUDE-E2E-NIO-006B: captured here, mirroring the one real
    # production call site (ProjectSetupApplicationService.
    # execute_approved_setup_and_development()), which captures it
    # immediately after constructing RunChangeProvenance and before any
    # of the run's own mutating actions.
    recorder.capture_working_tree_baseline()
    if post_baseline is not None:
        post_baseline(tmp_path)
    recorder.apply(
        DeveloperFileApplier(tmp_path),
        {"changes": [{"file": "src/run.txt", "action": "update", "content": content}]},
        "development",
    )
    manager.create_final_approval(run_id, "accepted")
    manager.decide_final_approval(run_id, "approved", "Human")
    return ProjectSetupApplicationService(Mock(), workflow_manager=manager), manager, path


def test_real_repo_commits_only_safe_run_paths_and_returns_existing_hash(tmp_path):
    service, _, _ = _approved_service(tmp_path)

    result = service.commit_approved_run("run-1", tmp_path, "controlled commit")

    assert result.status == "committed"
    assert result.paths == ("src/run.txt",)
    assert _git(tmp_path, "cat-file", "-e", f"{result.commit_hash}^{{commit}}").returncode == 0
    assert _git(tmp_path, "show", "--pretty=", "--name-only", result.commit_hash).stdout.strip() == "src/run.txt"


def test_preexisting_foreign_untracked_file_does_not_block_the_approved_commit(tmp_path):
    """CLAUDE-E2E-NIO-006B Part 5.2: a foreign untracked file that
    already existed BEFORE this run's working-tree baseline was
    captured is pre-existing, user-owned content -- ADC must commit the
    approved change successfully and leave it completely untouched,
    never blocking delivery merely because unrelated foreign content
    happens to be present in the repository."""
    def pre_baseline(root):
        (root / "notes.txt").write_text("private", encoding="utf-8")

    service, _, _ = _approved_service(tmp_path, pre_baseline=pre_baseline)
    foreign = tmp_path / "notes.txt"

    result = service.commit_approved_run("run-1", tmp_path, "controlled commit")

    assert result.status == "committed"
    assert result.paths == ("src/run.txt",)
    assert foreign.read_text(encoding="utf-8") == "private"
    assert "?? notes.txt" in _git(tmp_path, "status", "--short").stdout


def test_new_foreign_untracked_file_introduced_during_the_run_blocks_commit(tmp_path):
    """CLAUDE-E2E-NIO-006B Part 5.4 (generic, non-ESPHome-specific
    counterpart to the permanent Real-E2E regression below): a path that
    was clean at the run's working-tree baseline but becomes untracked
    DURING the run, outside approved provenance, must still block
    delivery -- proving the fix is not merely "commit always succeeds
    now" but genuinely restores the pre-existing/new distinction. Never
    staged, committed, or deleted either way."""
    service, _, _ = _approved_service(tmp_path)
    foreign = tmp_path / "notes.txt"
    foreign.write_text("private", encoding="utf-8")

    result = service.commit_approved_run("run-1", tmp_path, "controlled commit")

    assert result.status == "failed"
    assert any("notes.txt" in blocker for blocker in result.blockers)
    assert foreign.read_text(encoding="utf-8") == "private"
    assert _git(tmp_path, "rev-list", "--count", "HEAD").stdout.strip() == "1"
    assert "?? notes.txt" in _git(tmp_path, "status", "--short").stdout


def test_mixed_preexisting_and_new_foreign_changes_only_the_new_one_blocks(tmp_path):
    """CLAUDE-E2E-NIO-006B Part 5.5: a pre-existing foreign untracked
    file must not block delivery on its own, but a SEPARATE, genuinely
    new unapproved path introduced during the same run must still block
    it -- proving the two are never conflated."""
    def pre_baseline(root):
        (root / "old-notes.txt").write_text("already here", encoding="utf-8")

    service, _, _ = _approved_service(tmp_path, pre_baseline=pre_baseline)
    old_foreign = tmp_path / "old-notes.txt"
    new_foreign = tmp_path / "new-side-effect.txt"
    new_foreign.write_text("new", encoding="utf-8")

    result = service.commit_approved_run("run-1", tmp_path, "controlled commit")

    assert result.status == "failed"
    assert any("new-side-effect.txt" in blocker for blocker in result.blockers)
    assert not any("old-notes.txt" in blocker for blocker in result.blockers)
    assert old_foreign.read_text(encoding="utf-8") == "already here"
    assert new_foreign.read_text(encoding="utf-8") == "new"
    assert _git(tmp_path, "rev-list", "--count", "HEAD").stdout.strip() == "1"


def test_preexisting_tracked_modification_mutated_again_during_run_blocks_commit(tmp_path):
    """CLAUDE-E2E-NIO-006C Part 5.5: a path-only baseline cannot detect
    this -- a tracked foreign file already modified BEFORE the run
    baseline is captured is mutated AGAIN, by an unapproved side effect,
    DURING the run, while remaining the exact same path. The path was
    already dirty at run start, but its STATE changed further -- this
    must still block delivery, name the path, and never stage, commit,
    revert, or delete it."""
    def pre_baseline(root):
        tracked = root / "foreign.txt"
        tracked.write_text("base", encoding="utf-8")
        _git(root, "add", "--", "foreign.txt")
        _git(root, "commit", "-m", "foreign base")
        tracked.write_text("user modified v1", encoding="utf-8")

    def post_baseline(root):
        (root / "foreign.txt").write_text(
            "user modified v2 -- additional unapproved mutation", encoding="utf-8",
        )

    service, _, _ = _approved_service(tmp_path, pre_baseline=pre_baseline, post_baseline=post_baseline)
    tracked = tmp_path / "foreign.txt"

    result = service.commit_approved_run("run-1", tmp_path, "controlled commit")

    assert result.status == "failed"
    assert any("foreign.txt" in blocker for blocker in result.blockers)
    assert tracked.read_text(encoding="utf-8") == "user modified v2 -- additional unapproved mutation"
    assert _git(tmp_path, "rev-list", "--count", "HEAD").stdout.strip() == "2"


def test_preexisting_untracked_file_content_changed_again_during_run_blocks_commit(tmp_path):
    """CLAUDE-E2E-NIO-006C Part 5.6: an untracked foreign file already
    present BEFORE the run baseline has its CONTENT changed again
    DURING the run -- its git status class ("??") never changes, so a
    status-only baseline would also miss this; only a real content
    fingerprint proves the additional mutation. Must block delivery,
    name the path, and never stage, commit, revert, or delete it."""
    def pre_baseline(root):
        (root / "notes.txt").write_text("v1", encoding="utf-8")

    def post_baseline(root):
        (root / "notes.txt").write_text("v2 -- additional unapproved mutation", encoding="utf-8")

    service, _, _ = _approved_service(tmp_path, pre_baseline=pre_baseline, post_baseline=post_baseline)
    foreign = tmp_path / "notes.txt"

    result = service.commit_approved_run("run-1", tmp_path, "controlled commit")

    assert result.status == "failed"
    assert any("notes.txt" in blocker for blocker in result.blockers)
    assert foreign.read_text(encoding="utf-8") == "v2 -- additional unapproved mutation"
    assert _git(tmp_path, "rev-list", "--count", "HEAD").stdout.strip() == "1"


def test_verification_tool_side_effect_blocks_commit_instead_of_false_success(tmp_path):
    """CLAUDE-E2E-NIO-006A: a real Real-System-E2E reached 93% and failed
    immediately after commit_approved_run() reported "committed" while
    the project working tree still contained an untracked .gitignore --
    created as a side effect of the real `esphome compile` subprocess
    (a controlled, ADC-invoked external tool run during verification,
    not a provenance-tracked developer-file-application change, and not
    a pre-existing foreign file a human placed there independently).

    Reproduces the exact discovered shape: a real ESPHome-generated
    .gitignore (whose own content is `.esphome/`, hiding ESPHome's own
    build-cache directory from `git status` entirely -- so only
    .gitignore itself appears untracked, exactly matching the real E2E
    evidence) appears in the working tree alongside the run's own
    legitimate, fully-provenance-tracked change. The commit must not
    report success while this remains unaccounted for -- REQ: a
    "committed" outcome must mean the working tree is fully accounted
    for by the approved provenance, not merely that the intended paths
    were themselves correctly staged.
    """
    service, _, tracked = _approved_service(tmp_path)
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(".esphome/\nsecrets.yaml\n", encoding="utf-8")
    esphome_cache = tmp_path / ".esphome"
    esphome_cache.mkdir()
    (esphome_cache / "build_cache").write_text("cache", encoding="utf-8")

    result = service.commit_approved_run("run-1", tmp_path, "controlled commit")

    assert result.status == "failed"
    assert any(".gitignore" in blocker for blocker in result.blockers)
    # Never silently stage, commit, or delete the unaccounted artifact.
    assert gitignore.read_text(encoding="utf-8") == ".esphome/\nsecrets.yaml\n"
    assert _git(tmp_path, "rev-list", "--count", "HEAD").stdout.strip() == "1"
    assert "?? .gitignore" in _git(tmp_path, "status", "--short").stdout


def test_foreign_staged_change_blocks_and_index_is_unchanged(tmp_path):
    service, _, _ = _approved_service(tmp_path)
    foreign = tmp_path / "foreign.txt"
    foreign.write_text("staged", encoding="utf-8")
    _git(tmp_path, "add", "--", "foreign.txt")
    before = _git(tmp_path, "write-tree").stdout.strip()

    result = service.commit_approved_run("run-1", tmp_path, "blocked")

    assert result.status == "failed"
    assert "staged" in " ".join(result.blockers)
    assert _git(tmp_path, "write-tree").stdout.strip() == before
    assert _git(tmp_path, "rev-list", "--count", "HEAD").stdout.strip() == "1"


@pytest.mark.parametrize("staged", [False, True])
def test_preexisting_dirty_run_path_is_blocked(tmp_path, staged):
    path = _repo(tmp_path)
    path.write_text("user\n", encoding="utf-8")
    if staged:
        _git(tmp_path, "add", "--", "src/run.txt")
    manager = WorkflowManager(tmp_path / ".state.json")
    RunChangeProvenance(manager, "run", tmp_path).apply(
        DeveloperFileApplier(tmp_path),
        {"changes": [{"file": "src/run.txt", "action": "update", "content": "ai\n"}]},
        "development",
    )
    manager.create_final_approval("run", "accepted")
    manager.decide_final_approval("run", "approved")

    result = ProjectSetupApplicationService(Mock(), workflow_manager=manager).commit_approved_run(
        "run", tmp_path, "blocked",
    )

    assert result.status == "failed"
    expected = "staged" if staged else "modified"
    assert expected in " ".join(result.blockers)


def test_foreign_modified_and_untracked_paths_remain_untouched(tmp_path):
    """CLAUDE-E2E-NIO-006B Part 5.3: a tracked foreign file already
    modified, and a foreign file already untracked, BEFORE this run's
    working-tree baseline was captured -- both pre-existing, user-owned
    changes ADC must leave completely untouched while still committing
    the approved change successfully. (CLAUDE-E2E-NIO-006A had
    previously made this scenario fail closed as an over-broad
    correction; 006B restores the original, correct expectation using
    the explicit pre-run baseline instead of blocking indiscriminately.)"""
    def pre_baseline(root):
        tracked = root / "foreign.txt"
        tracked.write_text("base", encoding="utf-8")
        _git(root, "add", "--", "foreign.txt")
        _git(root, "commit", "-m", "foreign base")
        tracked.write_text("user modified", encoding="utf-8")
        (root / "untracked.txt").write_text("user untracked", encoding="utf-8")

    service, _, _ = _approved_service(tmp_path, pre_baseline=pre_baseline)
    tracked = tmp_path / "foreign.txt"
    untracked = tmp_path / "untracked.txt"

    result = service.commit_approved_run("run-1", tmp_path, "controlled")

    assert result.status == "committed"
    assert result.paths == ("src/run.txt",)
    assert tracked.read_text(encoding="utf-8") == "user modified"
    assert untracked.read_text(encoding="utf-8") == "user untracked"
    status = _git(tmp_path, "status", "--short").stdout
    assert " M foreign.txt" in status and "?? untracked.txt" in status


def test_after_hash_tampering_blocks_commit(tmp_path):
    service, _, path = _approved_service(tmp_path)
    path.write_text("tampered\n", encoding="utf-8")

    result = service.commit_approved_run("run-1", tmp_path, "blocked")

    assert result.status == "failed"
    assert "hash" in " ".join(result.blockers)


def test_success_is_persisted_and_second_call_does_not_commit_again(tmp_path):
    service, manager, _ = _approved_service(tmp_path)
    state = manager.load()
    state["user_approval"] = {
        "status": "approved", "approved_by": "Human", "approved_at": "now", "comment": "setup",
    }
    manager.save(state)
    first = service.commit_approved_run("run-1", tmp_path, "once")
    count = _git(tmp_path, "rev-list", "--count", "HEAD").stdout

    reloaded = ProjectSetupApplicationService(
        Mock(), workflow_manager=WorkflowManager(manager.storage),
    ).commit_approved_run("run-1", tmp_path, "ignored second message")

    assert reloaded == first
    assert _git(tmp_path, "rev-list", "--count", "HEAD").stdout == count
    state = WorkflowManager(manager.storage).load()
    assert state["git_commit_results"]["run-1"]["commit_hash"] == first.commit_hash
    assert state["git_commit_results"]["run-1"]["ready_for_publish"] is True
    assert state["publish_approvals"]["run-1"]["status"] == "pending"
    assert state["user_approval"]["status"] == "approved"
    assert state["final_approvals"]["run-1"]["status"] == "approved"
    assert state["change_provenance"]["run-1"]


def test_commit_state_crash_recovers_only_proven_run_commit(tmp_path, monkeypatch):
    service, manager, _ = _approved_service(tmp_path)
    real_persist = manager.persist_git_commit_result
    crashed = {"done": False}

    def crash_once(state, run_id, result):
        if result.get("status") == "committed" and not crashed["done"]:
            crashed["done"] = True
            raise RuntimeError("simulated state crash")
        return real_persist(state, run_id, result)

    monkeypatch.setattr(manager, "persist_git_commit_result", crash_once)
    with pytest.raises(RuntimeError, match="state crash"):
        service.commit_approved_run("run-1", tmp_path, "recoverable")
    run_commit = _git(tmp_path, "rev-parse", "HEAD").stdout.strip()
    assert manager.get_execution_state("run-1", "git")["status"] == "started"

    recovered = ProjectSetupApplicationService(
        Mock(), workflow_manager=WorkflowManager(manager.storage),
    ).commit_approved_run("run-1", tmp_path, "recoverable")

    assert recovered.status == "committed"
    assert recovered.commit_hash == run_commit
    state = WorkflowManager(manager.storage).load()
    assert state["git_commit_results"]["run-1"]["commit_hash"] == run_commit
    assert state["execution_lifecycles"]["run-1"]["git"]["recovered"] is True


def test_foreign_new_head_is_not_adopted_as_run_commit_after_state_crash(tmp_path, monkeypatch):
    service, manager, _ = _approved_service(tmp_path)
    real_persist = manager.persist_git_commit_result

    def crash_commit_state(state, run_id, result):
        if result.get("status") == "committed":
            raise RuntimeError("simulated state crash")
        return real_persist(state, run_id, result)

    monkeypatch.setattr(manager, "persist_git_commit_result", crash_commit_state)
    with pytest.raises(RuntimeError):
        service.commit_approved_run("run-1", tmp_path, "recoverable")
    run_commit = _git(tmp_path, "rev-parse", "HEAD").stdout.strip()
    foreign = tmp_path / "foreign.txt"
    foreign.write_text("foreign\n", encoding="utf-8")
    _git(tmp_path, "add", "--", "foreign.txt")
    _git(tmp_path, "commit", "-m", "foreign")
    foreign_head = _git(tmp_path, "rev-parse", "HEAD").stdout.strip()

    recovered = ProjectSetupApplicationService(
        Mock(), workflow_manager=WorkflowManager(manager.storage),
    ).commit_approved_run("run-1", tmp_path, "recoverable")

    assert recovered.commit_hash == run_commit
    assert recovered.commit_hash != foreign_head


def test_nothing_to_commit_is_structured_and_persisted(tmp_path):
    service, manager, path = _approved_service(tmp_path, content="before\n")

    result = service.commit_approved_run("run-1", tmp_path, "no change")

    assert result.status == "nothing_to_commit"
    assert result.commit_hash is None
    assert WorkflowManager(manager.storage).load()["git_commit_results"]["run-1"]["status"] == "nothing_to_commit"
    assert path.read_text(encoding="utf-8") == "before\n"


def test_existing_repository_is_required_and_git_init_is_never_attempted(tmp_path):
    path = tmp_path / "run.txt"
    path.write_text("after", encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    provenance = {
        "run.txt": {
            "project_root": str(tmp_path.resolve()),
            "baseline": {
                "git_repository": True,
                "git_worktree_dirty_before": False,
                "git_index_staged_before": False,
                "git_untracked_before": False,
            },
            "events": [{
                "apply_success": True, "file_exists_after": True,
                "content_hash_after": digest,
            }],
        }
    }

    result = ControlledGitStage().run(GitCommitRequest(
        "run", tmp_path, "message", "accepted", "approved", True, provenance,
    ))

    assert result.status == "failed"
    assert "existing Git repository" in " ".join(result.blockers)
    assert not (tmp_path / ".git").exists()


@pytest.mark.parametrize(
    "development,approval,ready,provenance,needle",
    [
        ("rework_required", "approved", True, {"x": {}}, "not accepted"),
        ("accepted", "pending", False, {"x": {}}, "not approved"),
        ("accepted", "approved", False, {"x": {}}, "not true"),
        ("accepted", "approved", True, {}, "missing"),
    ],
)
def test_contract_gates_fail_without_git_mutation(tmp_path, development, approval, ready, provenance, needle):
    request = GitCommitRequest(
        "run", tmp_path, "message", development, approval, ready, provenance,
    )

    result = ControlledGitStage().run(request)

    assert result.status == "failed"
    assert needle in " ".join(result.blockers)
    assert not (tmp_path / ".git").exists()


@pytest.mark.parametrize("message", ["", "bad\nmessage", "bad\x00message"])
def test_commit_message_validation_blocks_empty_and_control_characters(tmp_path, message):
    result = ControlledGitStage().run(
        GitCommitRequest("run", tmp_path, message, "accepted", "approved", True, {"x": {}}),
    )
    assert result.status == "failed"
    assert "message" in " ".join(result.blockers)


def test_message_starting_with_option_is_literal_argument(tmp_path):
    service, _, _ = _approved_service(tmp_path)

    result = service.commit_approved_run("run-1", tmp_path, "--author=attacker")

    assert result.status == "committed"
    assert _git(tmp_path, "log", "-1", "--format=%B").stdout.strip() == "--author=attacker"


def test_path_traversal_absolute_option_and_symlink_escape_are_blocked(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    target = outside / "target.txt"
    target.write_text("x", encoding="utf-8")
    (tmp_path / "link.txt").symlink_to(target)
    base = {"project_root": str(tmp_path.resolve()), "baseline": {"git_repository": True}, "events": [{"apply_success": True}]}
    for path in ("../escape", "/absolute", "-option", "link.txt"):
        result = ControlledGitStage().run(GitCommitRequest(
            "run", tmp_path, "message", "accepted", "approved", True, {path: base},
        ))
        assert result.status == "failed"


def test_mixed_provenance_blocks(tmp_path):
    service, manager, _ = _approved_service(tmp_path)
    state = manager.load()
    state["change_provenance"]["other-run"] = {
        "src/run.txt": state["change_provenance"]["run-1"]["src/run.txt"]
    }
    manager.save(state)

    result = service.commit_approved_run("run-1", tmp_path, "blocked")

    assert result.status == "failed"
    assert "mixed" in " ".join(result.blockers)


def test_controlled_stage_uses_fixed_argv_and_forbidden_git_actions_are_absent():
    source = Path("app/controlled_git_stage.py").read_text(encoding="utf-8")
    assert '"add", "--", *repo_paths' in source
    for forbidden in (
        '"add", "."', '"add", "-A"', '"add", "--all"', "shell=True",
        '"reset"', '"restore"', '"checkout"', '"clean"', '"stash"',
        '"init"', '"push"', '"fetch"', '"pull"', '"merge"', '"rebase"',
        '"branch"', '"switch"', '"cherry-pick"', '"--allow-empty"',
    ):
        assert forbidden not in source


def test_git_commit_failure_is_structured_without_recovery(tmp_path, monkeypatch):
    service, manager, _ = _approved_service(tmp_path)
    stage = ControlledGitStage()
    real_git = stage._git

    def fail_commit(cwd, *args):
        if args and args[0] == "commit":
            return subprocess.CompletedProcess(args, 1, "", "identity missing")
        return real_git(cwd, *args)

    monkeypatch.setattr(stage, "_git", fail_commit)
    service = ProjectSetupApplicationService(Mock(), workflow_manager=manager, controlled_git_stage=stage)

    result = service.commit_approved_run("run-1", tmp_path, "fails")

    assert result.status == "failed"
    assert result.error == "identity missing"
    assert "src/run.txt" in _git(tmp_path, "diff", "--cached", "--name-only").stdout
