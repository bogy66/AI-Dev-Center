"""Persistence-first independent sentinel and real-boundary regressions."""
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app import development_lifecycle
from app.controlled_rework_stage import ControlledReworkStage
from app.dev_workflow import DevelopmentWorkflow, _LiveDevelopmentLifecycleTrace
from app.diagnostic_trace import DiagnosticTrace, DiagnosticTraceStore, DiagnosticDetailLevel, render_diagnostic_trace_event
from tests.test_development_testing_stage import _request, _stage


SENTINELS = [
    ("AWS_ACCESS_KEY_ID=AKIA_AUDIT_SENTINEL", "AKIA_AUDIT_SENTINEL"),
    *[(f"{name}=audit_value_{index}_private", f"audit_value_{index}_private") for index, name in enumerate([
        "AWS_SECRET_ACCESS_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY",
        "API_KEY", "PASSWORD", "TOKEN", "BEARER", "Cookie", "Session", "api_key", "password", "token",
    ])],
    ('Authorization: Basic YXVkaXQ6c2VjcmV0', 'YXVkaXQ6c2VjcmV0'),
    ('Authorization: Bearer audit_auth_private', 'audit_auth_private'),
    ('Bearer audit_bearer_private', 'audit_bearer_private'),
    ('ghp_' + 'Q' * 36, 'ghp_' + 'Q' * 36),
    ('eyJabcdefghijk.eyJlmnopqrstuv.wxyzABCDEFGH', 'eyJabcdefghijk.eyJlmnopqrstuv.wxyzABCDEFGH'),
    ('sk-' + 'Q' * 40, 'sk-' + 'Q' * 40),
    ('STATUS_V3_KEY=' + 'a1' * 32, 'a1' * 32),
    ('"key": "' + 'b2' * 32 + '"', 'b2' * 32),
    ('"aws_access_key_id": "json_private_sentinel"', 'json_private_sentinel'),
]


@pytest.mark.parametrize("text,secret", SENTINELS)
def test_secret_absent_from_persistence_and_every_level(tmp_path, text, secret):
    path = tmp_path / "events.jsonl"
    trace = DiagnosticTrace(DiagnosticTraceStore(path))
    event = trace.record("isolated", "development", "started", "started", text,
                         source=text, related_result_id=text,
                         details={"effective_prompt": f"Task: {text} end",
                                  "diagnostics": [text, {"summary": text}],
                                  "failure_summary": text,
                                  "council_output": {"very_verbose": {"summary": text, "risks": [text, {"description": text}]}},
                                  "interface_data": {"info": {"input": {"description": text}, "output": [text]}}})
    raw = path.read_text()
    leaks = ["persisted"] if secret in raw else []
    for level in DiagnosticDetailLevel:
        if secret in render_diagnostic_trace_event(event, level):
            leaks.append(level.value)
    assert not leaks, f"secret {secret} exposed in {leaks}"


def test_effective_prompt_cap_and_boundary_redaction(tmp_path):
    trace = DiagnosticTrace(DiagnosticTraceStore(tmp_path / "events.jsonl"))
    for offset in (0, 2950, 2990, 3000):
        event = trace.record("run", "development", "started", "started", "Safe",
                             details={"effective_prompt": "x " * (offset // 2) + "AWS_ACCESS_KEY_ID=AKIA_AUDIT_SENTINEL " + "z" * 1000000})
        assert len(event.details["effective_prompt"]) <= 3000
        raw = trace.store.path.read_text()
        assert "AKIA_AUDIT_SENTINEL" not in raw
        for level in ("NORMAL", "INFO", "VERBOSE"):
            assert "effective_prompt=" not in render_diagnostic_trace_event(event, level)
    assert trace.store.path.stat().st_size < 16000


@pytest.mark.parametrize("level", ["normal", "info", "verbose", "very_verbose"])
def test_projection_requires_mapping_retains_safe_nested_metadata(tmp_path, level):
    trace = DiagnosticTrace(DiagnosticTraceStore(tmp_path / "events.jsonl"))
    rejected = trace.record("run", "development", "started", "started", "Safe",
                            details={"council_output": {level: "response " * 100000}})
    assert level not in rejected.details["council_output"]
    safe = trace.record("run", "development", "completed", "completed", "Safe",
                        details={"council_output": {level: {"summary": "Safe metadata", "risks": ["TOKEN=private_value"]}}})
    assert safe.details["council_output"][level]["summary"] == "Safe metadata"
    assert "private_value" not in trace.store.path.read_text()


def test_large_structured_string_payload_is_bounded(tmp_path):
    trace = DiagnosticTrace(DiagnosticTraceStore(tmp_path / "events.jsonl"))
    huge = {"very_verbose": {"reviews": [{"description": "x" * 100000} for _ in range(100)]}}
    event = trace.record("run", "development", "started", "started", "safe", details={
        "council_output": huge, "interface_data": huge, "effective_prompt": "y" * 1000000})
    persisted = trace.store.path.stat().st_size
    rendered = len(render_diagnostic_trace_event(event, "VERY_VERBOSE"))
    print(f"large-string persisted={persisted} rendered={rendered}")
    assert persisted < 50000 and rendered < 50000


def test_structural_fanout_has_total_budget_even_without_strings(tmp_path):
    trace = DiagnosticTrace(DiagnosticTraceStore(tmp_path / "events.jsonl"))
    # Only 127551 scalar leaves: modest input, but exceeds the stated 20k
    # structured-detail budget because numeric leaves consume no budget.
    payload = {"scores": [[0] * 50 for _ in range(50)]}
    payload = {"reviews": [payload for _ in range(50)]}
    event = trace.record("run", "development", "started", "started", "safe",
                         details={"council_output": {"very_verbose": payload}})
    persisted = trace.store.path.stat().st_size
    rendered = len(render_diagnostic_trace_event(event, "VERY_VERBOSE"))
    print(f"numeric-fanout persisted={persisted} rendered={rendered}")
    assert persisted < 100000 and rendered < 100000, "structural payload escapes total detail budget"


def _workflow(tmp_path):
    trace = DiagnosticTrace(DiagnosticTraceStore(tmp_path / "events.jsonl"))
    return DevelopmentWorkflow(Mock(), Mock(), Mock(), diagnostic_trace=trace), trace


@pytest.mark.parametrize("failure", [None, "development_apply", "test_apply"])
def test_stage_boundaries_are_persisted_around_actual_execution(tmp_path, failure):
    workflow, trace = _workflow(tmp_path)
    stage, development, generator, _, applier, runner, review, *_ = _stage()
    spans = {}
    methods = {"development": development.run, "test_generation": generator.generate,
               "test_apply": applier.apply, "testing": runner.run, "diagnosis_review": review.run}
    for phase, method in methods.items():
        old = method.side_effect
        def invoke(*args, _phase=phase, _old=old, **kwargs):
            spans[_phase] = [datetime.now(timezone.utc)]
            if _phase in {"development", "test_generation", "testing"}:
                assert any(e.phase == _phase and e.event_type == "started" for e in trace.get_trace("run"))
                assert not any(e.phase == _phase and e.event_type in {"completed", "failed"} for e in trace.get_trace("run"))
            value = _old(*args, **kwargs)
            if failure == "development_apply" and _phase == "development":
                value.status = "apply_failed"
            if failure == "test_apply" and _phase == "test_apply":
                value = {"applied": [], "skipped": ["test_feature.py"]}
            spans[_phase].append(datetime.now(timezone.utc))
            return value
        method.side_effect = invoke
    live = _LiveDevelopmentLifecycleTrace(workflow, "run")
    with development_lifecycle.observing(live):
        result = stage.run(_request(tmp_path))
    events = trace.get_trace("run")
    for phase in {"development", "test_generation", "testing"} & spans.keys():
        matching = [e for e in events if e.phase == phase]
        assert len(matching) == 2
        assert datetime.fromisoformat(matching[0].timestamp) <= spans[phase][0]
        assert datetime.fromisoformat(matching[-1].timestamp) >= spans[phase][1]
    if failure:
        assert not any(e.phase in {"testing", "diagnosis_review"} for e in events)
    else:
        assert datetime.fromisoformat(next(e.timestamp for e in events if e.phase == "change_provenance")) >= spans["test_apply"][1]
        assert datetime.fromisoformat(events[-1].timestamp) >= spans["diagnosis_review"][1]
    workflow._trace_development_cycles("run", SimpleNamespace(initial_result=result), skip_cycles=live.cycles)
    assert trace.get_trace("run") == events
    workflow._trace_development_cycles("fallback", SimpleNamespace(initial_result=result))
    fallback = trace.get_trace("fallback")
    assert fallback and all(e.details.get("timing") == "post_hoc" and e.summary.startswith("Recorded after execution:") for e in fallback)
    assert [e.sequence for e in events] == list(range(1, len(events) + 1))


def test_rework_real_boundary_order_and_sequence(tmp_path):
    from app.testing_stage import ReworkRequest
    workflow, trace = _workflow(tmp_path)
    stage, _, _, _, _, _, review, *_ = _stage()
    review.run.side_effect = [
        SimpleNamespace(status="rework_required", rework_request=ReworkRequest("test", "test", None, None)),
        SimpleNamespace(status="accepted", rework_request=None),
    ]
    live = _LiveDevelopmentLifecycleTrace(workflow, "run")
    with development_lifecycle.observing(live):
        result = ControlledReworkStage(stage).run(_request(tmp_path))
    events = trace.get_trace("run")
    assert result.rework_executed
    phases = [(e.phase, e.event_type) for e in events]
    assert phases.index(("diagnosis_review", "rework_required")) < phases.index(("controlled_rework", "started"))
    assert phases[-1] == ("controlled_rework", "completed")
    assert sum(p == ("development", "started") for p in phases) == 2
    assert [e.sequence for e in events] == list(range(1, len(events) + 1))
    workflow._trace_development_cycles("run", result, skip_cycles=live.cycles)
    assert trace.get_trace("run") == events


def test_quoted_secret_crossing_redaction_scan_window_never_leaks(tmp_path):
    trace = DiagnosticTrace(DiagnosticTraceStore(tmp_path / "events.jsonl"))
    trace.record("run", "development", "started", "started", "safe", details={
        "effective_prompt": '\"AWS_ACCESS_KEY_ID\": \"AKIA_AUDIT_SENTINEL' + 'x' * 10000 + '\"'})
    assert "AKIA_AUDIT_SENTINEL" not in trace.store.path.read_text()


def test_depth_key_count_and_list_length_caps(tmp_path):
    from app.diagnostic_trace import COUNCIL_OUTPUT_KEYS
    trace = DiagnosticTrace(DiagnosticTraceStore(tmp_path / "events.jsonl"))
    deep = "beyond_depth_sentinel"
    for _ in range(15):
        deep = {"description": deep}
    keys = {key: 1 for key in sorted(COUNCIL_OUTPUT_KEYS) if key not in {"normal", "info", "verbose", "very_verbose"}}
    event = trace.record("run", "development", "started", "started", "safe", details={
        "council_output": {"very_verbose": {"description": deep, "reviews": list(range(100)), "scores": keys}},
    })
    output = event.details["council_output"]["very_verbose"]
    assert "beyond_depth_sentinel" not in trace.store.path.read_text()
    assert len(output["reviews"]) == 50
    assert len(output["scores"]) <= 80
    assert "[TRUNCATED]" in json.dumps(output)
