from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest

from app.controlled_publish_stage import ControlledPublishStage, PublishRequest
from app.project_setup_application import ProjectSetupApplicationService
from app.publish_approval import PublishApprovalError
from app.workflow_manager import WorkflowManager


def _git(root, *args, check=True):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=check,
        capture_output=True, text=True,
    )


def _repository(tmp_path):
    remote = tmp_path / "remote.git"
    local = tmp_path / "work"
    remote.mkdir()
    local.mkdir()
    _git(remote, "init", "--bare")
    _git(local, "init")
    _git(local, "config", "user.email", "publish@example.com")
    _git(local, "config", "user.name", "Publish Test")
    branch = _git(local, "branch", "--show-current").stdout.strip()
    base = local / "base.txt"
    base.write_text("base\n", encoding="utf-8")
    _git(local, "add", "--", "base.txt")
    _git(local, "commit", "-m", "base")
    _git(local, "remote", "add", "origin", str(remote))
    _git(local, "push", "origin", f"refs/heads/{branch}:refs/heads/{branch}")
    run_file = local / "run.txt"
    run_file.write_text("run\n", encoding="utf-8")
    _git(local, "add", "--", "run.txt")
    _git(local, "commit", "-m", "run commit")
    run_hash = _git(local, "rev-parse", "HEAD").stdout.strip()
    base_hash = _git(local, "rev-parse", "HEAD^").stdout.strip()
    return local, remote, branch, run_hash, base_hash


def _service(tmp_path, *, commit_status="committed", commit_hash=None):
    local, remote, branch, run_hash, base_hash = _repository(tmp_path)
    manager = WorkflowManager(tmp_path / "workflow-state.json")
    state = manager.load()
    state["user_approval"] = {"status": "approved", "approved_by": "Setup", "approved_at": "now", "comment": None}
    state["final_approvals"]["run-1"] = {
        "status": "approved", "development_status": "accepted",
        "approved_by": "Final", "approved_at": "now", "comment": None,
    }
    state["change_provenance"]["run-1"] = {"run.txt": {"events": [{"apply_success": True}]}}
    state["git_commit_results"]["run-1"] = {
        "run_id": "run-1", "status": commit_status,
        "commit_message": "run commit", "paths": ["run.txt"],
        "commit_hash": run_hash if commit_hash is None else commit_hash,
        "blockers": [], "error": None, "ready_for_publish": commit_status == "committed",
    }
    manager.save(state)
    if commit_status == "committed":
        manager.create_publish_approval("run-1")
    service = ProjectSetupApplicationService(Mock(), workflow_manager=manager)
    return service, manager, local, remote, branch, run_hash, base_hash


def _remote_hash(remote, branch):
    return _git(remote, "rev-parse", f"refs/heads/{branch}").stdout.strip()


def test_committed_run_creates_separate_pending_publish_approval(tmp_path):
    service, manager, local, remote, branch, _, base_hash = _service(tmp_path)

    result = service.publish_approved_run("run-1", local, "origin")

    assert result.status == "failed"
    assert "not approved" in " ".join(result.blockers)
    state = manager.load()
    assert state["publish_approvals"]["run-1"]["status"] == "pending"
    assert state["publish_approvals"]["run-1"]["ready_for_publish"] is True
    assert state["final_approvals"]["run-1"]["status"] == "approved"
    assert _remote_hash(remote, branch) == base_hash


def test_rejected_publish_approval_is_terminal_and_does_not_push(tmp_path):
    service, _, local, remote, branch, _, base_hash = _service(tmp_path)
    service.decide_publish_approval("run-1", "rejected", "Human")

    result = service.publish_approved_run("run-1", local, "origin")

    assert result.status == "failed"
    assert _remote_hash(remote, branch) == base_hash
    with pytest.raises(PublishApprovalError, match="Cannot change"):
        service.decide_publish_approval("run-1", "approved", "Human")


def test_real_bare_remote_publish_uses_exact_ref_and_commit(tmp_path):
    service, manager, local, remote, branch, run_hash, _ = _service(tmp_path)
    approval = service.decide_publish_approval("run-1", "approved", "Human")

    result = service.publish_approved_run("run-1", local, "origin")

    assert approval.ready_for_publish is True
    assert result.status == "published"
    assert result.local_commit_hash == result.published_commit_hash == run_hash
    assert result.remote == "origin"
    assert result.remote_ref == f"refs/heads/{branch}"
    assert _remote_hash(remote, branch) == run_hash
    assert manager.load()["publish_results"]["run-1"]["status"] == "published"


def test_publish_is_idempotent_without_second_stage_call(tmp_path):
    service, manager, local, _, _, run_hash, _ = _service(tmp_path)
    service.decide_publish_approval("run-1", "approved")
    first = service.publish_approved_run("run-1", local, "origin")
    stage = Mock()
    reloaded = ProjectSetupApplicationService(
        Mock(), workflow_manager=WorkflowManager(manager.storage), controlled_publish_stage=stage,
    )

    second = reloaded.publish_approved_run("run-1", local, "origin")

    assert first.status == "published"
    assert second.status == "already_published"
    assert second.published_commit_hash == run_hash
    stage.run.assert_not_called()


def test_publish_state_crash_rechecks_remote_and_recovers_as_already_published(tmp_path, monkeypatch):
    service, manager, local, _, _, run_hash, _ = _service(tmp_path)
    service.decide_publish_approval("run-1", "approved")
    real_persist = manager.persist_publish_result
    crashed = {"done": False}

    def crash_once(state, run_id, result):
        if result.get("status") == "published" and not crashed["done"]:
            crashed["done"] = True
            raise RuntimeError("simulated publish state crash")
        return real_persist(state, run_id, result)

    monkeypatch.setattr(manager, "persist_publish_result", crash_once)
    with pytest.raises(RuntimeError, match="publish state crash"):
        service.publish_approved_run("run-1", local, "origin")
    assert manager.get_execution_state("run-1", "publish")["status"] == "started"

    recovered = ProjectSetupApplicationService(
        Mock(), workflow_manager=WorkflowManager(manager.storage),
    ).publish_approved_run("run-1", local, "origin")

    assert recovered.status == "already_published"
    assert recovered.published_commit_hash == run_hash
    assert WorkflowManager(manager.storage).get_execution_state("run-1", "publish")["status"] == "completed"


@pytest.mark.parametrize("commit_status", ["failed", "nothing_to_commit"])
def test_unsuccessful_git_commit_result_never_becomes_ready(tmp_path, commit_status):
    service, manager, local, remote, branch, _, base_hash = _service(
        tmp_path, commit_status=commit_status,
    )
    with pytest.raises(PublishApprovalError, match="committed run"):
        manager.create_publish_approval("run-1")

    result = service.publish_approved_run("run-1", local, "origin")

    assert result.status == "failed"
    assert _remote_hash(remote, branch) == base_hash


def test_missing_commit_basis_never_pushes(tmp_path):
    local, remote, branch, _, base_hash = _repository(tmp_path)
    manager = WorkflowManager(tmp_path / "state.json")
    result = ProjectSetupApplicationService(Mock(), workflow_manager=manager).publish_approved_run(
        "missing", local, "origin",
    )
    assert result.status == "failed"
    assert _remote_hash(remote, branch) == base_hash


@pytest.mark.parametrize("remote_name", ["missing", "-origin", "https://example.invalid/repo.git", "bad name"])
def test_missing_invalid_or_url_remote_is_blocked(tmp_path, remote_name):
    service, _, local, remote, branch, _, base_hash = _service(tmp_path)
    service.decide_publish_approval("run-1", "approved")

    result = service.publish_approved_run("run-1", local, remote_name)

    assert result.status == "failed"
    if "://" in remote_name:
        assert result.remote == ""
    assert _remote_hash(remote, branch) == base_hash
    assert _git(local, "remote").stdout.splitlines() == ["origin"]


def test_detached_head_is_fail_safe(tmp_path):
    service, _, local, remote, branch, run_hash, base_hash = _service(tmp_path)
    service.decide_publish_approval("run-1", "approved")
    _git(local, "checkout", "--detach", run_hash)

    result = service.publish_approved_run("run-1", local, "origin")

    assert result.status == "failed"
    assert "detached" in " ".join(result.blockers)
    assert _remote_hash(remote, branch) == base_hash


def test_nonexistent_persisted_commit_is_blocked(tmp_path):
    missing = "a" * 40
    service, _, local, remote, branch, _, base_hash = _service(tmp_path, commit_hash=missing)
    service.decide_publish_approval("run-1", "approved")

    result = service.publish_approved_run("run-1", local, "origin")

    assert result.status == "failed"
    assert "does not exist" in " ".join(result.blockers)
    assert _remote_hash(remote, branch) == base_hash


def test_additional_foreign_local_commit_blocks_without_push(tmp_path):
    service, _, local, remote, branch, _, base_hash = _service(tmp_path)
    service.decide_publish_approval("run-1", "approved")
    (local / "foreign.txt").write_text("foreign", encoding="utf-8")
    _git(local, "add", "--", "foreign.txt")
    _git(local, "commit", "-m", "foreign local commit")

    result = service.publish_approved_run("run-1", local, "origin")

    assert result.status == "failed"
    assert "branch tip" in " ".join(result.blockers)
    assert _remote_hash(remote, branch) == base_hash


def test_real_non_fast_forward_fails_without_repair(tmp_path):
    service, _, local, remote, branch, _, base_hash = _service(tmp_path)
    other = tmp_path / "other"
    _git(tmp_path, "clone", str(remote), str(other))
    _git(other, "config", "user.email", "other@example.com")
    _git(other, "config", "user.name", "Other")
    _git(other, "checkout", branch)
    (other / "other.txt").write_text("remote advance", encoding="utf-8")
    _git(other, "add", "--", "other.txt")
    _git(other, "commit", "-m", "remote advance")
    _git(other, "push", "origin", f"refs/heads/{branch}:refs/heads/{branch}")
    advanced_hash = _remote_hash(remote, branch)
    assert advanced_hash != base_hash
    service.decide_publish_approval("run-1", "approved")

    result = service.publish_approved_run("run-1", local, "origin")

    assert result.status == "failed"
    assert result.error and "exit code" in result.error
    assert _remote_hash(remote, branch) == advanced_hash


def test_push_failure_does_not_persist_credentials(tmp_path, monkeypatch):
    service, manager, local, _, _, _, _ = _service(tmp_path)
    service.decide_publish_approval("run-1", "approved")
    stage = ControlledPublishStage()
    real_git = stage._git

    def auth_failure(cwd, *args):
        if args and args[0] == "push":
            return subprocess.CompletedProcess(args, 1, "", "https://token-secret@example.invalid")
        return real_git(cwd, *args)

    monkeypatch.setattr(stage, "_git", auth_failure)
    service = ProjectSetupApplicationService(
        Mock(), workflow_manager=manager, controlled_publish_stage=stage,
    )
    result = service.publish_approved_run("run-1", local, "origin")

    assert result.status == "failed"
    serialized = str(manager.load()["publish_results"]["run-1"])
    assert "token-secret" not in serialized


def test_publish_state_preserves_all_approvals_provenance_commit_and_other_runs(tmp_path):
    service, manager, local, _, _, _, _ = _service(tmp_path)
    state = manager.load()
    state["git_commit_results"]["other"] = {"status": "failed"}
    state["publish_approvals"]["other"] = {"status": "rejected", "ready_for_publish": False}
    state["publish_results"]["other"] = {"status": "failed"}
    manager.save(state)
    service.decide_publish_approval("run-1", "approved")
    service.publish_approved_run("run-1", local, "origin")

    loaded = WorkflowManager(manager.storage).load()
    assert loaded["user_approval"]["status"] == "approved"
    assert loaded["final_approvals"]["run-1"]["status"] == "approved"
    assert loaded["change_provenance"]["run-1"]
    assert loaded["git_commit_results"]["run-1"]["status"] == "committed"
    assert loaded["publish_approvals"]["run-1"]["status"] == "approved"
    assert loaded["publish_results"]["run-1"]["status"] == "published"
    assert loaded["publish_results"]["other"]["status"] == "failed"


def test_controlled_publish_uses_fixed_argv_and_has_no_forbidden_mutations():
    source = Path("app/controlled_publish_stage.py").read_text(encoding="utf-8")
    assert '"push", "--porcelain", "--", request.remote, refspec' in source
    assert 'local_ref = f"refs/heads/{branch_name}"' in source
    for forbidden in (
        "shell=True", '"--force"', '"-f"', '"--force-with-lease"',
        '"--force-if-includes"', '"--delete"', '"init"', '"add"',
        '"commit"', '"reset"', '"restore"', '"checkout"', '"clean"',
        '"stash"', '"merge"', '"rebase"', '"cherry-pick"', '"tag"',
        '"remote", "add"', '"remote", "remove"', '"remote", "set-url"',
        '"fetch"',
    ):
        assert forbidden not in source
