"""Independent lifecycle contracts. Deliberate product failures remain failures."""
from copy import deepcopy
from datetime import datetime
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from app import engineering_council as module
from app.ai_config import CouncilConfig
from app.engineering_council import EngineeringCouncil, _AgentTask


def setup_call(monkeypatch, release, *, raises=False):
    council = EngineeringCouncil(CouncilConfig(enabled=True), lambda _: "unused")
    activities, calls, workers = [], [], []
    council.set_activity_callback(lambda **event: activities.append(event))
    def complete(prompt):
        workers.append(threading.current_thread())
        calls.append(prompt)
        assert release.wait(5), "test must release synthetic provider"
        if raises:
            raise RuntimeError("synthetic late exception")
        return '{"variants": []}'
    monkeypatch.setattr(module, "create_council_provider", lambda *a: SimpleNamespace(complete=complete))
    monkeypatch.setattr(module, "_outer_deadline", lambda config: time.monotonic() + 0.08)
    def task():
        return _AgentTask("A1", "environment_architect", council._config.environment_architect,
                          "synthetic prompt", "phase1", datetime.now())
    return council, activities, calls, workers, task


@pytest.mark.parametrize("raises", [False, True])
def test_abandoned_completion_cannot_mutate_finalized_call_records(monkeypatch, raises):
    release = threading.Event()
    council, activities, calls, workers, task = setup_call(monkeypatch, release, raises=raises)
    try:
        started = time.monotonic()
        result = council._execute_parallel([task()], "phase1")
        assert time.monotonic() - started < 0.8
        assert result[0].success is False and "deadline" in result[0].error
        before_result = deepcopy(result)
        before_records = deepcopy(council._call_records)
        before_activity = deepcopy(activities)
        release.set()
        for worker in workers:
            worker.join(timeout=2)
        assert calls == ["synthetic prompt"], "retry after abandonment"
        assert result == before_result
        assert activities == before_activity, "second terminal lifecycle state"
        assert council._call_records == before_records, "late provider mutated finalized shared call records"
    finally:
        release.set()
        for worker in workers:
            worker.join(timeout=2)


def test_repeated_hung_providers_do_not_accumulate_live_workers(monkeypatch):
    release = threading.Event()
    council, _, _, workers, task = setup_call(monkeypatch, release)
    baseline = len(threading.enumerate())
    try:
        counts = []
        for _ in range(5):
            assert not council._execute_parallel([task()], "phase1")[0].success
            counts.append(len(threading.enumerate()) - baseline)
        assert counts[-1] <= 1, f"persistent abandoned workers accumulate per invocation: {counts}"
    finally:
        release.set()
        for worker in workers:
            worker.join(timeout=2)


def test_hung_provider_does_not_hold_interpreter_exit():
    script = '''
import threading, time
from datetime import datetime
from types import SimpleNamespace
from app import engineering_council as m
from app.ai_config import CouncilConfig
c = m.EngineeringCouncil(CouncilConfig(enabled=True), lambda _: "unused")
def complete(prompt):
    threading.Event().wait(60)
m.create_council_provider = lambda *a: SimpleNamespace(complete=complete)
m._outer_deadline = lambda config: time.monotonic() + 0.08
t = m._AgentTask("A1", "environment_architect", c._config.environment_architect, "fake", "phase1", datetime.now())
r = c._execute_parallel([t], "phase1")
assert not r[0].success and "deadline" in r[0].error
print("deadline-returned", flush=True)
'''
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=4)
    assert result.returncode == 0 and "deadline-returned" in result.stdout


def test_no_new_retry_after_late_exception(monkeypatch):
    release = threading.Event()
    council, activities, calls, workers, task = setup_call(monkeypatch, release, raises=True)
    try:
        abandoned = task()
        council._execute_parallel([abandoned], "phase1")
        assert abandoned.activity_closed.is_set()
        release.set()
        for worker in workers:
            worker.join(timeout=2)
        assert calls == ["synthetic prompt"]
        assert [a["runtime_state"] for a in activities].count("failed") == 1
    finally:
        release.set()
        for worker in workers:
            worker.join(timeout=2)


def test_public_council_result_stays_stable_but_finalized_records_must_too(monkeypatch, tmp_path):
    from tests.test_engineering_council import (
        _make_council_config, _make_council_input, _make_phase1_response,
        _make_phase2_response, _make_chairman_response, FakeLLMProvider,
    )
    release = threading.Event()
    workers, factory_calls, activities, structured = [], {}, [], []
    ids = ["A2-var-1", "A3-var-1"]
    def blocked(prompt):
        workers.append(threading.current_thread())
        assert release.wait(5)
        return _make_phase1_response("A1", 1)
    def factory(config, *args):
        count = factory_calls.get(config.model, 0)
        factory_calls[config.model] = count + 1
        if config.model == "model-ea" and count == 0:
            return SimpleNamespace(complete=blocked)
        if config.model == "model-ch":
            return FakeLLMProvider([_make_chairman_response(ids)])
        if count == 0:
            agent = {"model-ti": "A2", "model-ra": "A3"}[config.model]
            return FakeLLMProvider([_make_phase1_response(agent, 1)])
        return FakeLLMProvider([_make_phase2_response(config.role, ids)])
    monkeypatch.setattr(module, "create_council_provider", factory)
    monkeypatch.setattr(module, "_outer_deadline", lambda config: time.monotonic() + 0.15)
    council = EngineeringCouncil(_make_council_config(), lambda _: "unused", trace_dir=tmp_path)
    council.set_activity_callback(lambda **event: activities.append(event))
    council.set_result_callback(lambda **event: structured.append(event))
    try:
        result = council.evaluate(_make_council_input())
        assert result.council_complete and result.council_degraded and result.variants
        assert any("deadline" in error for error in result.agent_errors)
        snapshot = deepcopy((result, activities, structured, council._call_records))
        persisted = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
        release.set()
        for worker in workers:
            worker.join(timeout=2)
        assert (result, activities, structured) == snapshot[:3]
        assert {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == persisted
        assert council._call_records == snapshot[3], "completed public run acquired a late call record"
    finally:
        release.set()
        for worker in workers:
            worker.join(timeout=2)
