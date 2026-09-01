from app.change_provenance import RunChangeProvenance
from app.developer_file_applier import DeveloperFileApplier
from app.workflow_manager import WorkflowManager
from app.development_stage import DevelopmentRequest
from app.development_testing_stage import DevelopmentTestingStage
from app.controlled_rework_stage import ControlledReworkStage
from app.testing_stage import ReworkRequest
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
import subprocess


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)


def _repository(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    path = tmp_path / "src" / "a.py"
    path.parent.mkdir()
    path.write_text("A\n", encoding="utf-8")
    _git(tmp_path, "add", "src/a.py")
    _git(tmp_path, "commit", "-m", "initial")
    return path


def test_records_initial_baseline_and_ordered_events_without_overwriting_it(tmp_path):
    target = tmp_path / "src" / "a.py"
    target.parent.mkdir()
    target.write_text("USER", encoding="utf-8")
    manager = WorkflowManager(tmp_path / "state.json")
    recorder = RunChangeProvenance(manager, "run-1", tmp_path)
    applier = DeveloperFileApplier(tmp_path)

    recorder.apply(applier, {"changes": [{"file": "src/a.py", "action": "update", "content": "AI1"}]}, "development")
    recorder.apply(applier, {"changes": [{"file": "src/a.py", "action": "update", "content": "AI2"}]}, "rework_development")

    entry = manager.load()["change_provenance"]["run-1"]["src/a.py"]
    assert entry["baseline"]["file_existed_before"] is True
    assert entry["baseline"]["content_hash_before"] != entry["events"][-1]["content_hash_after"]
    assert [event["phase"] for event in entry["events"]] == ["development", "rework_development"]


def test_records_new_run_file_and_rejects_traversal(tmp_path):
    manager = WorkflowManager(tmp_path / "state.json")
    recorder = RunChangeProvenance(manager, "run-1", tmp_path)
    applier = DeveloperFileApplier(tmp_path)

    recorder.apply(applier, {"changes": [{"file": "src/new.py", "action": "create", "content": "x"}]}, "test")
    entry = manager.load()["change_provenance"]["run-1"]["src/new.py"]
    assert entry["baseline"]["file_existed_before"] is False
    assert entry["events"][0]["file_exists_after"] is True


def test_dirty_and_staged_git_baselines_are_distinguished(tmp_path):
    path = _repository(tmp_path)
    manager = WorkflowManager(tmp_path / "state.json")
    recorder = RunChangeProvenance(manager, "dirty", tmp_path)
    path.write_text("A\nUSER\n", encoding="utf-8")
    before = recorder._hash(path)
    recorder.apply(DeveloperFileApplier(tmp_path), {"changes": [{"file": "src/a.py", "action": "update", "content": "A\nUSER\nAI\n"}]}, "development")
    dirty = manager.load()["change_provenance"]["dirty"]["src/a.py"]
    assert dirty["baseline"]["git_tracked_before"] is True
    assert dirty["baseline"]["git_worktree_dirty_before"] is True
    assert dirty["baseline"]["git_index_staged_before"] is False
    assert dirty["baseline"]["content_hash_before"] == before
    assert dirty["events"][0]["content_hash_after"] != before

    _git(tmp_path, "add", "src/a.py")
    recorder2 = RunChangeProvenance(manager, "staged", tmp_path)
    recorder2.apply(DeveloperFileApplier(tmp_path), {"changes": [{"file": "src/a.py", "action": "update", "content": "AI2\n"}]}, "rework_development")
    staged = manager.load()["change_provenance"]["staged"]["src/a.py"]
    assert staged["baseline"]["git_tracked_before"] is True
    assert staged["baseline"]["git_index_staged_before"] is True


def test_runs_are_isolated_after_persistence_reload(tmp_path):
    manager = WorkflowManager(tmp_path / "state.json")
    applier = DeveloperFileApplier(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("A", encoding="utf-8")
    RunChangeProvenance(manager, "run-A", tmp_path).apply(applier, {"changes": [{"file": "src/a.py", "action": "update", "content": "A1"}]}, "development")
    RunChangeProvenance(manager, "run-B", tmp_path).apply(applier, {"changes": [{"file": "src/a.py", "action": "update", "content": "B1"}]}, "test")

    entries = WorkflowManager(tmp_path / "state.json").load()["change_provenance"]
    assert entries["run-A"]["src/a.py"]["baseline"] != entries["run-B"]["src/a.py"]["baseline"]
    assert [e["phase"] for e in entries["run-A"]["src/a.py"]["events"]] == ["development"]
    assert [e["phase"] for e in entries["run-B"]["src/a.py"]["events"]] == ["test"]


def test_rework_keeps_original_baseline_and_orders_events(tmp_path):
    path = tmp_path / "src" / "a.py"
    path.parent.mkdir()
    path.write_text("A", encoding="utf-8")
    manager = WorkflowManager(tmp_path / "state.json")
    recorder = RunChangeProvenance(manager, "run-1", tmp_path)
    applier = DeveloperFileApplier(tmp_path)
    original = recorder._hash(path)
    recorder.apply(applier, {"changes": [{"file": "src/a.py", "action": "update", "content": "A DEV"}]}, "development")
    recorder.apply(applier, {"changes": [{"file": "src/a.py", "action": "update", "content": "A DEV REWORK"}]}, "rework_development")
    entry = manager.load()["change_provenance"]["run-1"]["src/a.py"]
    assert entry["baseline"]["content_hash_before"] == original
    assert [event["phase"] for event in entry["events"]] == ["development", "rework_development"]
    assert entry["events"][-1]["content_hash_after"] == recorder._hash(path)


def test_foreign_untracked_and_modified_paths_are_not_touched(tmp_path):
    run_path = _repository(tmp_path)
    user_path = tmp_path / "src" / "user.py"
    user_path.write_text("USER", encoding="utf-8")
    _git(tmp_path, "add", "src/user.py")
    _git(tmp_path, "commit", "-m", "user")
    user_path.write_text("USER LOCAL", encoding="utf-8")
    notes = tmp_path / "private_notes.txt"
    notes.write_bytes(b"private")
    manager = WorkflowManager(tmp_path / "state.json")
    RunChangeProvenance(manager, "run", tmp_path).apply(DeveloperFileApplier(tmp_path), {"changes": [{"file": "src/a.py", "action": "update", "content": "AI"}]}, "development")
    entries = manager.load()["change_provenance"]["run"]
    assert notes.read_bytes() == b"private"
    assert user_path.read_text(encoding="utf-8") == "USER LOCAL"
    assert "private_notes.txt" not in entries and "src/user.py" not in entries
    assert " M src/user.py" in _git(tmp_path, "status", "--porcelain").stdout


def test_non_git_and_traversal_are_fail_safe(tmp_path):
    manager = WorkflowManager(tmp_path / "state.json")
    recorder = RunChangeProvenance(manager, "run", tmp_path)
    recorder.apply(DeveloperFileApplier(tmp_path), {"changes": [{"file": "new.py", "action": "create", "content": "x"}]}, "test")
    entry = manager.load()["change_provenance"]["run"]["new.py"]
    assert entry["baseline"]["git_repository"] is False
    assert entry["events"][0]["file_exists_after"] is True
    outside = tmp_path.parent / "outside.txt"
    with __import__("pytest").raises(ValueError, match="Invalid provenance path"):
        recorder.apply(DeveloperFileApplier(tmp_path), {"changes": [{"file": "../outside.txt", "action": "create", "content": "bad"}]}, "development")
    assert not outside.exists()


def test_provenance_preserves_setup_and_final_approvals_across_reload(tmp_path):
    manager = WorkflowManager(tmp_path / "state.json")
    state = manager._default_state()
    state["user_approval"] = {"status": "approved", "approved_by": "Udo", "approved_at": "now", "comment": "setup"}
    state["final_approvals"] = {"run-final": {"status": "approved", "development_status": "accepted", "approved_by": "Udo", "approved_at": "now", "comment": "final"}}
    manager.save(state)
    manager.capture_provenance_baseline("run-a", str(tmp_path), "a.py", "development", {"content_hash_before": None})
    manager.record_provenance_event("run-a", "a.py", {"phase": "development", "apply_success": True})
    loaded = WorkflowManager(tmp_path / "state.json").load()
    assert loaded["user_approval"]["status"] == "approved"
    assert loaded["final_approvals"]["run-final"]["status"] == "approved"
    assert loaded["change_provenance"]["run-a"]["a.py"]["events"]


def test_provenance_updates_preserve_other_runs_and_latest_persisted_state(tmp_path):
    storage = tmp_path / "state.json"
    first = WorkflowManager(storage)
    first.capture_provenance_baseline("run-a", str(tmp_path), "a.py", "development", {"content_hash_before": "a"})
    stale = first.load()
    second = WorkflowManager(storage)
    second.capture_provenance_baseline("run-b", str(tmp_path), "b.py", "test", {"content_hash_before": "b"})
    second.record_provenance_event("run-b", "b.py", {"phase": "test", "apply_success": True})
    first.record_provenance_event("run-a", "a.py", {"phase": "development", "apply_success": True})
    loaded = WorkflowManager(storage).load()["change_provenance"]
    assert loaded["run-a"]["a.py"]["events"]
    assert loaded["run-b"]["b.py"]["events"]
    assert stale["change_provenance"]["run-a"] != loaded["run-b"]


def test_development_testing_stage_records_test_phase_with_real_applier(tmp_path):
    manager = WorkflowManager(tmp_path / "state.json")
    recorder = RunChangeProvenance(manager, "run-test", tmp_path)
    request = DevelopmentRequest("project", tmp_path, "task", "run-test", recorder)
    development = Mock(); development.run.return_value = SimpleNamespace()
    generator = Mock(); generator.generate.return_value = {"changes": [{"file": "test_feature.py", "action": "create", "content": "x"}]}
    applier = DeveloperFileApplier(tmp_path); factory = Mock(return_value=applier)
    runner = Mock(); runner.run.return_value = SimpleNamespace()
    review = Mock(); review.run.return_value = SimpleNamespace(status="accepted")
    DevelopmentTestingStage(development, generator, factory, runner, review).run(request)
    entry = WorkflowManager(tmp_path / "state.json").load()["change_provenance"]["run-test"]["test_feature.py"]
    assert list(WorkflowManager(tmp_path / "state.json").load()["change_provenance"]) == ["run-test"]
    assert entry["baseline"]["content_hash_before"] is None
    assert entry["events"][0]["phase"] == "test"
    assert entry["events"][0]["content_hash_after"] == recorder._hash(tmp_path / "test_feature.py")
    factory.assert_called_once_with(tmp_path)


def test_controlled_rework_stage_records_rework_test_in_same_run(tmp_path):
    manager = WorkflowManager(tmp_path / "state.json")
    recorder = RunChangeProvenance(manager, "run-rework", tmp_path)
    request = DevelopmentRequest("project", tmp_path, "task", "run-rework", recorder)
    development = Mock(); development.run.return_value = SimpleNamespace()
    generator = Mock(); generator.generate.side_effect = [
        {"changes": [{"file": "test_feature.py", "action": "create", "content": "one"}]},
        {"changes": [{"file": "test_feature.py", "action": "update", "content": "two"}]},
    ]
    factory = Mock(side_effect=lambda root: DeveloperFileApplier(root))
    runner = Mock(); runner.run.return_value = SimpleNamespace()
    rework = ReworkRequest("reason", "diagnostics", object(), object())
    review = Mock(); review.run.side_effect = [SimpleNamespace(status="rework_required", rework_request=rework), SimpleNamespace(status="accepted", rework_request=None)]
    ControlledReworkStage(DevelopmentTestingStage(development, generator, factory, runner, review)).run(request)
    entry = WorkflowManager(tmp_path / "state.json").load()["change_provenance"]["run-rework"]["test_feature.py"]
    assert list(WorkflowManager(tmp_path / "state.json").load()["change_provenance"]) == ["run-rework"]
    assert [event["phase"] for event in entry["events"]] == ["test", "rework_test"]
    assert entry["baseline"]["content_hash_before"] is None
    assert entry["events"][-1]["content_hash_after"] == recorder._hash(tmp_path / "test_feature.py")
    assert factory.call_count == 2


def test_provenance_captures_baseline_applies_once_then_records_after(tmp_path, monkeypatch):
    manager = WorkflowManager(tmp_path / "state.json")
    recorder = RunChangeProvenance(manager, "run-order", tmp_path)
    calls = []
    original_baseline = recorder._capture_baseline
    original_after = recorder._record_event
    monkeypatch.setattr(recorder, "_capture_baseline", lambda path, phase: (calls.append("baseline"), original_baseline(path, phase))[1])
    monkeypatch.setattr(recorder, "_record_event", lambda path, phase, success: (calls.append("after"), original_after(path, phase, success))[1])
    applier = Mock()
    applier.apply.side_effect = lambda changes: (calls.append("apply"), {"applied": ["a.py"], "skipped": []})[1]

    recorder.apply(applier, {"changes": [{"file": "a.py", "action": "create", "content": "x"}]}, "development")

    assert calls == ["baseline", "apply", "after"]
    applier.apply.assert_called_once()


def test_failed_apply_keeps_baseline_without_successful_after_event(tmp_path):
    target = tmp_path / "a.py"
    target.write_text("before", encoding="utf-8")
    manager = WorkflowManager(tmp_path / "state.json")
    recorder = RunChangeProvenance(manager, "run-failure", tmp_path)
    applier = Mock()
    applier.apply.side_effect = OSError("write failed")

    with pytest.raises(OSError, match="write failed"):
        recorder.apply(applier, {"changes": [{"file": "a.py", "action": "update", "content": "after"}]}, "development")

    entry = manager.load()["change_provenance"]["run-failure"]["a.py"]
    assert entry["baseline"]["content_hash_before"] == recorder._hash(target)
    assert entry["events"] == []
    applier.apply.assert_called_once()


def test_foreign_staged_path_remains_untouched_by_run_provenance(tmp_path):
    run_path = _repository(tmp_path)
    staged_path = tmp_path / "src" / "user_staged.py"
    staged_path.write_text("BASE", encoding="utf-8")
    _git(tmp_path, "add", "src/user_staged.py")
    _git(tmp_path, "commit", "-m", "user file")
    staged_path.write_bytes(b"USER STAGED")
    _git(tmp_path, "add", "src/user_staged.py")
    staged_index = _git(tmp_path, "show", ":src/user_staged.py").stdout.encode()
    manager = WorkflowManager(tmp_path / "state.json")

    RunChangeProvenance(manager, "run", tmp_path).apply(
        DeveloperFileApplier(tmp_path),
        {"changes": [{"file": "src/a.py", "action": "update", "content": "AI"}]},
        "development",
    )

    entries = manager.load()["change_provenance"]["run"]
    assert staged_path.read_bytes() == b"USER STAGED"
    assert _git(tmp_path, "show", ":src/user_staged.py").stdout.encode() == staged_index
    assert "M  src/user_staged.py" in _git(tmp_path, "status", "--porcelain").stdout
    assert "src/user_staged.py" not in entries
    assert run_path.read_text(encoding="utf-8") == "AI"
