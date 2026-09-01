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


def _approved_service(tmp_path, *, content="after\n", run_id="run-1"):
    path = _repo(tmp_path)
    manager = WorkflowManager(tmp_path / ".workflow-state.json")
    recorder = RunChangeProvenance(manager, run_id, tmp_path)
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
    foreign = tmp_path / "notes.txt"
    foreign.write_text("private", encoding="utf-8")

    result = service.commit_approved_run("run-1", tmp_path, "controlled commit")

    assert result.status == "committed"
    assert result.paths == ("src/run.txt",)
    assert _git(tmp_path, "cat-file", "-e", f"{result.commit_hash}^{{commit}}").returncode == 0
    assert _git(tmp_path, "show", "--pretty=", "--name-only", result.commit_hash).stdout.strip() == "src/run.txt"
    assert foreign.read_text(encoding="utf-8") == "private"
    assert "?? notes.txt" in _git(tmp_path, "status", "--short").stdout


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
    service, _, _ = _approved_service(tmp_path)
    tracked = tmp_path / "foreign.txt"
    tracked.write_text("base", encoding="utf-8")
    _git(tmp_path, "add", "--", "foreign.txt")
    _git(tmp_path, "commit", "-m", "foreign base")
    tracked.write_text("user modified", encoding="utf-8")
    untracked = tmp_path / "untracked.txt"
    untracked.write_text("user untracked", encoding="utf-8")

    result = service.commit_approved_run("run-1", tmp_path, "controlled")

    assert result.status == "committed"
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
