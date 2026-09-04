from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import datetime
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.controlled_git_stage import GitCommitResult
from app.diagnostic_trace import (
    DiagnosticDetailLevel, DiagnosticTrace, DiagnosticTraceError,
    DiagnosticTraceStore, render_diagnostic_trace_event,
)
from app.execution_identity import ADC_IMPLEMENTATION_VERSION, execution_identity
from app.dev_workflow import DevelopmentWorkflow
from app.project_setup_application import ProjectSetupApplicationService
from app.workflow_manager import WorkflowManager


def test_execution_identity_versions_contract_without_fabricated_model_version():
    deterministic = execution_identity("requirement_validation")
    assert deterministic == {
        "entity": "requirement_validation",
        "entity_version": 1,
        "implementation_version": ADC_IMPLEMENTATION_VERSION,
    }

    ai_actor = execution_identity(
        "council_agent_a3_review", provider="openrouter", model="configured-model",
    )
    assert ai_actor["provider"] == "openrouter"
    assert ai_actor["model"] == "configured-model"
    assert "model_version" not in ai_actor


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


def test_council_projection_is_nested_bounded_and_excludes_private_fields(tmp_path):
    trace, path = _trace(tmp_path)
    trace.record(
        "run", "engineering_council", "completed", "completed", "A1 proposal",
        details={
            "diagnostic_level": "INFO", "result_kind": "proposal",
            "council_output": {
                "info": {"summary": "Safe proposal", "risks": ["bounded risk"]},
                "very_verbose": {
                    "capabilities": ["build"],
                    "prompt": "secret prompt", "reasoning": "private thought",
                    "raw_response": "raw model response", "api_key": "secret-key",
                    "verification": "unsafe-verifier --run && execute-next",
                    "command": "unsafe-command --flag",
                },
            },
        },
    )

    output = trace.get_trace("run")[0].details["council_output"]
    assert output["info"]["summary"] == "Safe proposal"
    assert output["very_verbose"]["capabilities"] == ["build"]
    raw = path.read_text(encoding="utf-8")
    for forbidden in (
        "secret prompt", "private thought", "raw model response", "secret-key",
        "unsafe-verifier", "unsafe-command",
    ):
        assert forbidden not in raw


def test_interface_projection_persists_safe_xy_and_rejects_unsafe_payloads(tmp_path):
    trace, path = _trace(tmp_path)
    trace.record(
        "run", "requirement_discovery", "completed", "completed",
        "Requirement Discovery transformed its input",
        details={
            "diagnostic_level": "NORMAL", "result_kind": "interface",
            "interface_stage": "requirement_discovery",
            "interface_data": {
                "info": {"x": {"type": "future_domain_payload", "interface": "mcp",
                                 "source": "future_agent", "destination": "requirement_discovery",
                                 "data": {"requirement_count": 1}},
                         "f": {"entity": "requirement_discovery",
                               "entity_version": 1,
                               "implementation_version": "adc-python-1"},
                         "y": {"type": "requirement_set", "interface": "internal",
                               "source": "requirement_discovery", "destination": "validator",
                               "data": {"requirement_count": 1}}},
                "very_verbose": {
                    "x": {"type": "user_request", "interface": "web",
                          "source": "web", "destination": "requirement_discovery",
                          "data": {"user_request": "Create ESPHome project",
                                   "prompt": "internal prompt", "token": "secret-token"}},
                    "f": {"entity": "requirement_discovery",
                          "entity_version": 1,
                          "implementation_version": "adc-python-1",
                          "provider": "safe-provider", "model": "safe-model",
                          "command": "unsafe processor command"},
                    "y": {"type": "requirement_set", "interface": "internal",
                          "source": "requirement_discovery", "destination": "validator",
                          "data": {"requirements": [{"name": "esphome",
                                                      "command": "unsafe --execute"}]}},
                },
            },
        },
    )

    interface = trace.get_trace("run")[0].details["interface_data"]
    assert interface["info"]["x"]["type"] == "future_domain_payload"
    assert interface["info"]["x"]["interface"] == "mcp"
    assert interface["very_verbose"]["x"]["data"]["user_request"] == "Create ESPHome project"
    for endpoint in ("x", "y"):
        assert {"type", "interface", "source", "destination", "data"} <= set(
            interface["very_verbose"][endpoint]
        )
    assert interface["very_verbose"]["f"] == {
        "entity": "requirement_discovery", "entity_version": 1,
        "implementation_version": "adc-python-1",
        "provider": "safe-provider", "model": "safe-model",
    }
    assert "model_version" not in interface["very_verbose"]["f"]
    assert interface["very_verbose"]["y"]["data"]["requirements"][0]["name"] == "esphome"
    raw = path.read_text(encoding="utf-8")
    for forbidden in ("internal prompt", "secret-token", "unsafe --execute",
                      "unsafe processor command"):
        assert forbidden not in raw


def _terminal_event(tmp_path, *, council_phase="phase1"):
    trace, _ = _trace(tmp_path)
    return trace.record(
        "terminal-run", "engineering_council", "completed", "completed",
        "Council activity completed",
        details={
            "actor": "Agent A1", "actor_role": "solution_architect",
            "runtime_state": "completed", "council_phase": council_phase,
            "provider": "safe-provider", "model": "safe-model", "duration_ms": 12,
            "interface_data": {
                "info": {
                    "x": {"type": "requirements", "interface": "internal"},
                    "f": {"entity": "council_agent_a1_proposal", "entity_version": 1,
                          "implementation_version": "adc-python-1",
                          "provider": "safe-provider", "model": "safe-model"},
                    "y": {"type": "proposal", "interface": "internal"},
                },
                "verbose": {
                    "x": {"type": "requirements", "interface": "internal",
                          "source": "validation", "destination": "Agent A1",
                          "data": {"requirement_count": 2}},
                    "f": {"entity": "council_agent_a1_proposal", "entity_version": 1,
                          "implementation_version": "adc-python-1",
                          "provider": "safe-provider", "model": "safe-model"},
                    "y": {"type": "proposal", "interface": "internal",
                          "source": "Agent A1", "destination": "council",
                          "data": {"proposal_count": 1}},
                },
                "very_verbose": {
                    "x": {"type": "requirements", "interface": "internal",
                          "source": "validation", "destination": "Agent A1",
                          "data": {"requirements": [{"name": "safe-tool"}]}},
                    "f": {"entity": "council_agent_a1_proposal", "entity_version": 1,
                          "implementation_version": "adc-python-1",
                          "provider": "safe-provider", "model": "safe-model"},
                    "y": {"type": "proposal", "interface": "internal",
                          "source": "Agent A1", "destination": "council",
                          "data": {"proposals": [{"name": "safe proposal"}]}},
                },
            },
            "council_output": {
                "info": {"summary": "safe summary"},
                "verbose": {"summary": "safe summary", "risks": ["safe risk"]},
                "very_verbose": {"summary": "safe summary", "advantages": ["safe"]},
            },
        },
    )


def test_terminal_normal_is_compact_and_does_not_fabricate_fields(tmp_path):
    event = _terminal_event(tmp_path)
    rendered = render_diagnostic_trace_event(event, DiagnosticDetailLevel.NORMAL)

    assert rendered.startswith("[TRACE] engineering_council")
    assert "Phase 1 — Proposals" in rendered
    assert "Agent A1 (solution_architect)" in rendered
    assert "status=completed" in rendered and "activity=completed" in rendered
    assert "x — Input" not in rendered and "model_version" not in rendered


def test_terminal_info_renders_concise_x_f_y_identity(tmp_path):
    rendered = render_diagnostic_trace_event(_terminal_event(tmp_path), "INFO")

    assert "x — Input: type=requirements interface=internal" in rendered
    assert "f — Processor: entity=council_agent_a1_proposal" in rendered
    assert "provider=safe-provider model=safe-model" in rendered
    assert "y — Output: type=proposal interface=internal" in rendered
    assert "requirement_count" not in rendered


def test_terminal_verbose_renders_structured_xy_context_and_council(tmp_path):
    rendered = render_diagnostic_trace_event(_terminal_event(tmp_path), "VERBOSE")

    assert "source=validation destination=Agent A1" in rendered
    assert 'data={"requirement_count": 2}' in rendered
    assert "Context: provider=safe-provider model=safe-model duration_ms=12" in rendered
    assert '"risks": ["safe risk"]' in rendered


def test_terminal_very_verbose_uses_richest_existing_safe_projection(tmp_path):
    rendered = render_diagnostic_trace_event(_terminal_event(tmp_path), "VERY_VERBOSE")

    assert '"requirements": [{"name": "safe-tool"}]' in rendered
    assert '"proposals": [{"name": "safe proposal"}]' in rendered
    assert '"advantages": ["safe"]' in rendered


@pytest.mark.parametrize(
    ("phase", "label", "actor"),
    (("phase1", "Phase 1 — Proposals", "Agent A1"),
     ("phase2", "Phase 2 — Reviews", "Agent A1"),
     ("phase3", "Phase 3 — Chairman", "Chairman")),
)
def test_terminal_distinguishes_council_phases(tmp_path, phase, label, actor):
    event = _terminal_event(tmp_path, council_phase=phase)
    if actor == "Chairman":
        event = replace(event, details={**event.details, "actor": actor,
                                        "actor_role": "chairman"})

    rendered = render_diagnostic_trace_event(event, "VERBOSE")

    assert label in rendered and actor in rendered


def test_terminal_rendering_preserves_safety_and_does_not_mutate_event(tmp_path):
    trace, _ = _trace(tmp_path)
    event = trace.record(
        "safe-terminal", "engineering_council", "completed", "completed",
        "Safe summary token=hidden-token",
        details={
            "actor": "Agent A2",
            "interface_data": {
                "very_verbose": {
                    "x": {"type": "input", "interface": "internal",
                          "data": {"prompt": "private prompt", "api_key": "key-1"}},
                    "f": {"entity": "processor", "command": "unsafe --run"},
                    "y": {"type": "output", "interface": "internal",
                          "data": {"reasoning": "private reasoning"}},
                },
            },
            "council_output": {"very_verbose": {
                "summary": "safe", "raw_response": "private response",
                "verification": "unsafe verifier --run",
            }},
        },
    )
    before = asdict(event)

    rendered = render_diagnostic_trace_event(event, "VERY_VERBOSE")

    assert asdict(event) == before
    assert "[REDACTED]" in rendered
    for forbidden in ("hidden-token", "private prompt", "key-1", "unsafe --run",
                      "private reasoning", "private response", "unsafe verifier"):
        assert forbidden not in rendered


def test_terminal_detail_levels_are_progressively_richer(tmp_path):
    event = _terminal_event(tmp_path)
    rendered = [
        render_diagnostic_trace_event(event, level)
        for level in DiagnosticDetailLevel
    ]
    assert len(rendered[0]) < len(rendered[1]) < len(rendered[2]) < len(rendered[3])


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


class TestPromptVisibility:
    """Tests that effective prompts are visible only at VERY_VERBOSE level."""

    _SAMPLE_PROMPT = (
        "You are the Requirement Discovery Analyst of AI-Dev-Center. "
        "Return a JSON object with the single key requirements."
    )

    def _trace_with_prompt(self, tmp_path):
        trace, path = _trace(tmp_path)
        event = trace.record(
            "run-prompt", "requirement_discovery", "started", "started",
            "Thinking",
            details={
                "effective_prompt": self._SAMPLE_PROMPT,
                "runtime_state": "thinking",
                "actor": "Requirement discovery provider",
                "model": "test-model",
                "provider": "TestProvider",
            },
        )
        return event

    def test_normal_level_does_not_expose_prompt(self, tmp_path):
        event = self._trace_with_prompt(tmp_path)
        rendered = render_diagnostic_trace_event(event, DiagnosticDetailLevel.NORMAL)
        assert "Effective-Prompt" not in rendered
        assert self._SAMPLE_PROMPT not in rendered

    def test_info_level_does_not_expose_prompt(self, tmp_path):
        event = self._trace_with_prompt(tmp_path)
        rendered = render_diagnostic_trace_event(event, DiagnosticDetailLevel.INFO)
        assert "Effective-Prompt" not in rendered
        assert self._SAMPLE_PROMPT not in rendered

    def test_verbose_level_does_not_expose_prompt(self, tmp_path):
        event = self._trace_with_prompt(tmp_path)
        rendered = render_diagnostic_trace_event(event, DiagnosticDetailLevel.VERBOSE)
        assert "Effective-Prompt" not in rendered
        assert self._SAMPLE_PROMPT not in rendered

    def test_very_verbose_level_exposes_prompt(self, tmp_path):
        event = self._trace_with_prompt(tmp_path)
        rendered = render_diagnostic_trace_event(
            event, DiagnosticDetailLevel.VERY_VERBOSE,
        )
        assert "Effective-Prompt" in rendered
        assert "Requirement Discovery Analyst of AI-Dev-Center" in rendered

    def test_very_verbose_prompt_passes_through_sanitization(self, tmp_path):
        trace, path = _trace(tmp_path)
        event = trace.record(
            "run-sanitize", "requirement_discovery", "started", "started",
            "Thinking",
            details={
                "effective_prompt": "Bearer abc123 password=secret-value api_key=deadbeef",
                "runtime_state": "thinking",
                "actor": "Requirement discovery provider",
                "model": "test-model",
                "provider": "TestProvider",
            },
        )
        rendered = render_diagnostic_trace_event(
            event, DiagnosticDetailLevel.VERY_VERBOSE,
        )
        assert "[REDACTED]" in rendered
        assert "deadbeef" not in rendered
        assert "secret-value" not in rendered

    def test_effective_prompt_not_in_trace_without_explicit_include(self, tmp_path):
        trace, path = _trace(tmp_path)
        event = trace.record(
            "run-no-prompt", "requirement_discovery", "started", "started",
            "Thinking",
            details={
                "runtime_state": "thinking",
                "actor": "Requirement discovery provider",
            },
        )
        rendered = render_diagnostic_trace_event(
            event, DiagnosticDetailLevel.VERY_VERBOSE,
        )
        assert "Effective-Prompt" not in rendered

    def test_no_second_trace_system_created(self, tmp_path):
        trace, path = _trace(tmp_path)
        event = trace.record(
            "run-single-trace", "requirement_discovery", "started", "started",
            "Thinking",
            details={
                "effective_prompt": self._SAMPLE_PROMPT,
                "runtime_state": "thinking",
            },
        )
        events = trace.get_trace("run-single-trace")
        assert len(events) == 1
        assert events[0].phase == "requirement_discovery"


class TestDiagnosticDetailLevels:
    """Tests for the central five-level diagnostic model."""

    def test_exactly_five_levels(self):
        levels = set(DiagnosticDetailLevel)
        assert levels == {"NONE", "NORMAL", "INFO", "VERBOSE", "VERY_VERBOSE"}

    def test_none_suppresses_presentation(self, tmp_path):
        trace, path = _trace(tmp_path)
        event = trace.record(
            "run-a", "testing", "started", "started", "Testing",
            details={"model": "x", "provider": "y"},
        )
        rendered = render_diagnostic_trace_event(event, DiagnosticDetailLevel.NONE)
        assert rendered == ""

    def test_none_does_not_destroy_collection(self, tmp_path):
        trace, path = _trace(tmp_path)
        trace.record(
            "run-audit", "testing", "started", "started", "Audit test",
            details={"model": "x"},
        )
        events = trace.get_trace("run-audit")
        assert len(events) == 1
        assert events[0].phase == "testing"

    def test_none_rank_below_normal(self):
        from app.diagnostic_trace import _DIAGNOSTIC_DETAIL_RANK
        assert _DIAGNOSTIC_DETAIL_RANK[DiagnosticDetailLevel.NONE] == -1
        assert (_DIAGNOSTIC_DETAIL_RANK[DiagnosticDetailLevel.NONE] <
                _DIAGNOSTIC_DETAIL_RANK[DiagnosticDetailLevel.NORMAL])

    def test_effective_prompt_retention_is_usable(self, tmp_path):
        trace, path = _trace(tmp_path)
        prompt = "You are the Requirement Discovery Analyst of AI-Dev-Center." * 20
        event = trace.record(
            "run-prompt", "requirement_discovery", "started", "started",
            "Thinking",
            details={
                "effective_prompt": prompt,
                "actor": "Requirement discovery provider",
            },
        )
        stored = event.details.get("effective_prompt", "")
        assert len(stored) > 500
        assert "AI-Dev-Center" in stored

    def test_none_render_returns_empty_string_for_all_events(self, tmp_path):
        trace, path = _trace(tmp_path)
        event = trace.record(
            "run-x", "engineering_council", "started", "started",
            "Testing",
            details={
                "council_output": {"info": {"summary": "X"}},
                "interface_data": {"info": {"x": {"type": "t"}}},
                "effective_prompt": "prompt",
            },
        )
        rendered = render_diagnostic_trace_event(event, DiagnosticDetailLevel.NONE)
        assert rendered == ""
