from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.controlled_git_stage import GitCommitResult
from app.diagnostic_trace import (
    DiagnosticTrace, DiagnosticTraceError, DiagnosticTraceStore,
)
from app.dev_workflow import DevelopmentWorkflow
from app.project_setup_application import ProjectSetupApplicationService
from app.workflow_manager import WorkflowManager


def _trace(tmp_path):
    path = tmp_path / "trace" / "events.jsonl"
    return DiagnosticTrace(DiagnosticTraceStore(path)), path


def test_event_persists_reloads_and_read_is_non_mutating(tmp_path):
    trace, path = _trace(tmp_path)
    event = trace.record("run-a", "testing", "started", "started", "Tests started")
    before = path.read_bytes()

    loaded = DiagnosticTrace(DiagnosticTraceStore(path)).get_trace("run-a")
    loaded_again = trace.get_trace("run-a")

    assert loaded == loaded_again == (event,)
    assert path.read_bytes() == before
    assert datetime.fromisoformat(event.timestamp).utcoffset().total_seconds() == 0
    assert trace.get_trace("unknown") == ()


def test_sequence_is_monotone_stable_and_runs_are_isolated(tmp_path):
    trace, path = _trace(tmp_path)
    trace.record("run-a", "development", "started", "started", "Development started")
    trace.record("run-b", "testing", "started", "started", "Tests started")
    trace.record("run-a", "development", "completed", "completed", "Development completed")

    assert [event.sequence for event in trace.get_trace("run-a")] == [1, 2]
    assert [event.sequence for event in trace.get_trace("run-b")] == [1]
    assert [event.sequence for event in DiagnosticTraceStore(path).read("run-a")] == [1, 2]


def test_concurrent_writes_have_no_duplicate_sequence_or_corrupt_json(tmp_path):
    trace, path = _trace(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(
            lambda number: trace.record("run", "testing", "completed", "passed", f"Test cycle {number}"),
            range(40),
        ))
    events = trace.get_trace("run")
    assert sorted(event.sequence for event in events) == list(range(1, 41))
    assert len({event.event_id for event in events}) == 40
    for line in path.read_text(encoding="utf-8").splitlines():
        assert json.loads(line)["run_id"] == "run"


def test_terminal_result_deduplication_uses_related_result_identifier(tmp_path):
    trace, _ = _trace(tmp_path)
    first = trace.record("run", "controlled_publish", "published", "published", "Published", related_result_id="publish-result-1")
    second = trace.record("run", "controlled_publish", "published", "published", "Published again", related_result_id="publish-result-1")
    assert second == first
    assert len(trace.get_trace("run")) == 1


def test_secret_redaction_and_detail_allowlist_protect_persisted_jsonl(tmp_path):
    trace, path = _trace(tmp_path)
    secrets = [
        "api_key=KEY-123", "Bearer bearer-456", "password: pass-789",
        "https://user:pw-000@example.test/repo", "Authorization: Bearer auth-111",
        "-----BEGIN OPENSSH PRIVATE KEY-----private-222-----END OPENSSH PRIVATE KEY-----",
    ]
    trace.record(
        "run", "controlled_publish", "failed", "failed", " | ".join(secrets),
        details={
            "failure_summary": "token=detail-333",
            "remote": "https://user:remote-444@example.test/repo",
            "environment": {"SECRET": "env-555"},
            "headers": {"Authorization": "Bearer header-666"},
            "file_content": "content-777",
        },
    )
    raw = path.read_text(encoding="utf-8")
    for secret in ("KEY-123", "bearer-456", "pass-789", "pw-000", "auth-111", "private-222", "detail-333", "remote-444", "env-555", "header-666", "content-777"):
        assert secret not in raw
    assert "environment" not in raw and "headers" not in raw and "file_content" not in raw
    assert "[REDACTED]" in raw


def test_safe_runtime_activity_metadata_excludes_prompt_and_reasoning(tmp_path):
    trace, path = _trace(tmp_path)
    trace.record(
        "run", "engineering_council", "started", "started",
        "Agent A2 thinking",
        details={
            "actor": "Agent A2", "actor_role": "toolchain_integrator",
            "runtime_state": "thinking", "council_phase": "phase1",
            "provider": "deterministic", "model": "test-model",
            "prompt": "must not persist", "reasoning": "must not persist",
        },
    )

    event = trace.get_trace("run")[0]
    assert event.details["actor"] == "Agent A2"
    assert event.details["runtime_state"] == "thinking"
    assert "prompt" not in event.details and "reasoning" not in event.details
    assert "must not persist" not in path.read_text(encoding="utf-8")


def test_invalid_contract_and_persistence_failure_are_explicit(tmp_path):
    trace, _ = _trace(tmp_path)
    with pytest.raises(ValueError, match="phase"):
        trace.record("run", "llm_generated_phase", "started", "started", "bad")
    blocking_file = tmp_path / "not-a-directory"
    blocking_file.write_text("x", encoding="utf-8")
    broken = DiagnosticTrace(DiagnosticTraceStore(blocking_file / "events.jsonl"))
    with pytest.raises(DiagnosticTraceError, match="append failed"):
        broken.record("run", "testing", "started", "started", "Tests")


def test_rework_timeline_contains_fail_diagnosis_rework_and_second_test(tmp_path):
    trace, _ = _trace(tmp_path)
    workflow = DevelopmentWorkflow(Mock(), Mock(), Mock(), diagnostic_trace=trace)
    development = lambda: SimpleNamespace(status="success", applied_changes={"applied": ["src/a.c"], "skipped": []})
    cycle = lambda passed, status: SimpleNamespace(
        development_result=development(),
        test_changes={"changes": [{"file": "test/a.yml"}]},
        apply_result={"applied": ["test/a.yml"]},
        test_result=SimpleNamespace(passed=passed, timed_out=False, return_code=0 if passed else 1),
        testing_stage_result=SimpleNamespace(status=status),
    )
    result = SimpleNamespace(
        initial_result=cycle(False, "rework_required"),
        rework_result=cycle(True, "accepted"),
        rework_executed=True,
    )
    workflow._trace_development_cycles("run", result)
    events = trace.get_trace("run")
    statuses = [(event.phase, event.status) for event in events]
    assert statuses.index(("testing", "failed")) < statuses.index(("diagnosis_review", "rework_required"))
    assert statuses.index(("diagnosis_review", "rework_required")) < statuses.index(("controlled_rework", "rework_required"))
    assert statuses.index(("controlled_rework", "started")) < max(index for index, value in enumerate(statuses) if value == ("testing", "passed"))


def test_git_result_and_publish_pending_are_traced_with_commit_hash(tmp_path):
    trace, _ = _trace(tmp_path)
    manager = WorkflowManager(tmp_path / "state.json")
    state = manager.load()
    state["final_approvals"]["run"] = {"status": "approved", "development_status": "accepted"}
    manager.save(state)
    git_stage = Mock()
    commit_hash = "a" * 40
    git_stage.run.return_value = GitCommitResult("run", "committed", "message", ("src/a.cpp",), commit_hash, ready_for_publish=True)
    service = ProjectSetupApplicationService(Mock(), workflow_manager=manager, controlled_git_stage=git_stage, diagnostic_trace=trace)

    service.commit_approved_run("run", tmp_path, "message")

    events = service.get_diagnostic_trace("run")
    committed = next(event for event in events if event.status == "committed")
    assert committed.details["commit_hash"] == commit_hash
    assert any(event.phase == "publish_approval" and event.status == "pending" for event in events)


def test_trace_content_cannot_approve_or_release_publish_gate(tmp_path):
    trace, _ = _trace(tmp_path)
    manager = WorkflowManager(tmp_path / "state.json")
    state = manager.load()
    state["git_commit_results"]["run"] = {"status": "committed", "commit_hash": "a" * 40}
    state["publish_approvals"]["run"] = {"status": "pending", "ready_for_publish": True}
    manager.save(state)
    trace.record("run", "publish_approval", "approved", "approved", "Synthetic trace says approved")
    stage = Mock()
    stage.run.return_value = SimpleNamespace(
        run_id="run", status="failed", local_commit_hash="a" * 40,
        remote="origin", remote_ref=None, published_commit_hash=None,
        blockers=("publish human approval is not approved",), error=None,
        to_record=lambda: {"run_id": "run", "status": "failed"},
    )
    service = ProjectSetupApplicationService(Mock(), workflow_manager=manager, controlled_publish_stage=stage, diagnostic_trace=trace)

    service.publish_approved_run("run", tmp_path, "origin")

    request = stage.run.call_args.args[0]
    assert request.publish_approval_status == "pending"
    assert manager.load()["publish_approvals"]["run"]["status"] == "pending"


def test_all_canonical_phases_and_statuses_are_representable(tmp_path):
    trace, _ = _trace(tmp_path)
    phases = (
        "common_request", "project_inspection", "requirement_discovery",
        "requirement_validation", "preflight", "engineering_council",
        "toolchain_materialization", "setup_plan", "setup_approval",
        "setup_execution", "development", "test_generation", "testing",
        "diagnosis_review", "controlled_rework", "final_approval",
        "change_provenance", "controlled_git", "publish_approval",
        "controlled_publish", "workflow_end",
    )
    for phase in phases:
        trace.record("run", phase, "completed", "completed", f"{phase} completed")
    for status in ("pending", "rejected", "blocked", "failed", "timeout", "rework_required", "committed", "published", "already_published", "nothing_to_commit"):
        trace.record("statuses", "workflow_end", status, status, f"Status {status}")
    assert {event.phase for event in trace.get_trace("run")} == set(phases)
    assert {event.status for event in trace.get_trace("statuses")} == {"pending", "rejected", "blocked", "failed", "timeout", "rework_required", "committed", "published", "already_published", "nothing_to_commit"}


def test_read_only_web_api_delegates_to_application_service(tmp_path):
    import asyncio
    from app import web_api

    trace, path = _trace(tmp_path)
    trace.record("run-api", "testing", "completed", "passed", "Tests passed")
    service = Mock()
    service.get_diagnostic_trace.side_effect = trace.get_trace
    session = SimpleNamespace(run_id="run-api", project_setup_service=service)
    web_api.sessions["safe-session"] = session
    before = path.read_bytes()
    try:
        response = asyncio.run(web_api.get_central_diagnostic_trace("safe-session"))
        missing = asyncio.run(web_api.get_central_diagnostic_trace("../trace-file"))
    finally:
        web_api.sessions.pop("safe-session", None)

    assert response["run_id"] == "run-api"
    assert response["events"][0]["sequence"] == 1
    assert response["events"][0]["status"] == "passed"
    service.get_diagnostic_trace.assert_called_once_with("run-api")
    assert missing.status_code == 404
    assert path.read_bytes() == before
