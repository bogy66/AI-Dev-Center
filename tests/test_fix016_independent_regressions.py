"""FIX016 independent boundary checks; local synthetic providers only.

Pauses model indefinite blocking until the bounded-return assertion is made.
All paused threads are released and joined in finally blocks.
"""
import inspect
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app import engineering_council as m
from tests.test_council_trace_independent_regressions import council, task


def finish(release, coordinator, tasks):
    release.set()
    coordinator.join(3)
    for item in tasks:
        if item.worker:
            item.worker.join(3)
            assert not item.worker.is_alive()
    assert not coordinator.is_alive()
    assert m.council_worker_stats()['live'] == 0
    for thread in threading.enumerate():
        if thread.name.startswith('council-notify-'):
            thread.join(3)
            assert not thread.is_alive()
    assert m.council_notifier_stats()['live'] == 0


def test_provider_start_claim_does_not_prove_actual_handover(monkeypatch):
    """028: complete() entry is retractable preparation, not handover.

    This unverified test binding may enter after its earlier claim; actual
    transport closure is protected by TEST_036 component and native probes.
    """
    c = council()
    item = task(c, 'last-check-race')
    reached, release = threading.Event(), threading.Event()
    calls, results = [], []
    code = m.EngineeringCouncil._invoke_provider.__code__
    lines, first = inspect.getsourcelines(m.EngineeringCouncil._invoke_provider)
    call_line = first + next(i for i, line in enumerate(lines) if 'return provider.complete(' in line)

    def trace(frame, event, arg):
        if frame.f_code is code and event == 'line' and frame.f_lineno == call_line:
            reached.set()
            release.wait()
        return trace

    original = c._run_admitted_agent

    def traced(t):
        sys.settrace(trace)
        try:
            return original(t)
        finally:
            sys.settrace(None)

    monkeypatch.setattr(c, '_run_admitted_agent', traced)
    monkeypatch.setattr(m, 'create_council_provider', lambda *a: SimpleNamespace(complete=lambda p: calls.append(p) or '{}'))
    monkeypatch.setattr(m, '_outer_deadline', lambda cfg: time.monotonic() + 0.15)
    coordinator = threading.Thread(target=lambda: results.extend(c._execute_parallel([item], 'phase1')))
    try:
        coordinator.start()
        assert reached.wait(1)
        coordinator.join(1)
        assert not coordinator.is_alive() and item.activity_closed.is_set()
        assert not results[0].success and calls == []
        release.set()
        item.worker.join(1)
        assert calls == [item.prompt]
        assert item.handover_boundary == m.UNVERIFIED_BOUNDARY
        assert len(c._call_records) == 1 and not c._call_records[0].success
        assert item.terminal_state == ('failed', 'timeout')
    finally:
        finish(release, coordinator, [item])


@pytest.mark.parametrize('state', ['waiting', 'failed'])
def test_coordinator_callback_cannot_block_deadline(monkeypatch, state):
    c = council()
    item = task(c, 'coordinator-callback-' + state)
    reached, release = threading.Event(), threading.Event()
    provider_release = threading.Event()
    results = []

    def callback(**event):
        if event['runtime_state'] == state:
            reached.set()
            release.wait()

    def complete(prompt):
        provider_release.wait()
        return '{}'

    c.set_activity_callback(callback)
    monkeypatch.setattr(m, 'create_council_provider', lambda *a: SimpleNamespace(complete=complete))
    monkeypatch.setattr(m, '_outer_deadline', lambda cfg: time.monotonic() + 0.05)
    coordinator = threading.Thread(target=lambda: results.extend(c._execute_parallel([item], 'phase1')))
    try:
        coordinator.start()
        assert reached.wait(1)
        coordinator.join(0.25)
        assert not coordinator.is_alive(), f'{state} callback blocks Council coordinator past deadline'
    finally:
        provider_release.set()
        finish(release, coordinator, [item])


@pytest.mark.parametrize("provider_hangs", [False, True])
def test_blocked_thinking_callback_does_not_leave_terminal_diagnosis_pending(monkeypatch, provider_hangs):
    c = council()
    item = task(c, 'terminal-diagnosis')
    provider_release = threading.Event()
    reached, release = threading.Event(), threading.Event()
    delivered, results = [], []

    def callback(**event):
        if event['runtime_state'] == 'thinking':
            reached.set()
            release.wait()
        delivered.append(event['runtime_state'])

    c.set_activity_callback(callback)
    def complete(prompt):
        if provider_hangs:
            provider_release.wait()
        return '{}'

    monkeypatch.setattr(m, 'create_council_provider', lambda *a: SimpleNamespace(complete=complete))
    monkeypatch.setattr(m, '_outer_deadline', lambda cfg: time.monotonic() + 0.05)
    coordinator = threading.Thread(target=lambda: results.extend(c._execute_parallel([item], 'phase1')))
    try:
        coordinator.start()
        assert reached.wait(1)
        coordinator.join(0.3)
        assert not coordinator.is_alive()
        # Notification latency cannot turn a healthy provider into a failure.
        # A genuinely hung provider retains the original timeout protection.
        assert results[0].success is not provider_hangs
        terminal = 'failed' if provider_hangs else 'completed'
        assert terminal not in delivered, 'subscription must not overlap its blocked callback'
        assert c.notification_state()['activity']['unconfirmed'] >= 1
        assert item.terminal_state[0] == terminal
    finally:
        provider_release.set()
        finish(release, coordinator, [item])
        release.set()
        for lane in (item.progress_lane, item.terminal_lane):
            assert lane.settle(time.monotonic() + 3)
        assert terminal in delivered


def test_healthy_same_slot_waiters_succeed_and_release_capacity(monkeypatch):
    cs = [council(), council()]
    items = [task(c, 'healthy-slot') for c in cs]
    reached, release, waiting = threading.Event(), threading.Event(), threading.Event()
    calls, results = [], [None, None]
    original = m._WORKER_POOL.acquire_slot

    def acquire(worker, cancelled):
        if worker is items[1].worker:
            waiting.set()
        return original(worker, cancelled)

    def complete(prompt):
        calls.append(threading.current_thread())
        if len(calls) == 1:
            reached.set()
            release.wait()
        return '{}'

    monkeypatch.setattr(m._WORKER_POOL, 'acquire_slot', acquire)
    monkeypatch.setattr(m, 'create_council_provider', lambda *a: SimpleNamespace(complete=complete))
    monkeypatch.setattr(m, '_outer_deadline', lambda cfg: time.monotonic() + 2)
    coordinators = [threading.Thread(target=lambda i=i: results.__setitem__(i, cs[i]._execute_parallel([items[i]], 'phase1'))) for i in range(2)]
    try:
        coordinators[0].start()
        assert reached.wait(1)
        coordinators[1].start()
        assert waiting.wait(1)
        assert len(calls) == 1
        assert m.council_worker_stats()['live'] == 2
        release.set()
        for coordinator in coordinators:
            coordinator.join(1)
        assert all(result and result[0].success for result in results)
        assert len(calls) == 2
    finally:
        for coordinator in coordinators:
            if coordinator.ident is not None:
                finish(release, coordinator, items)


@pytest.mark.parametrize('consumer', ['reviewer', 'rework'])
@pytest.mark.parametrize('syntax', ['split', 'equals'])
def test_argv_credentials_with_spaces_are_redacted_as_whole_arguments(tmp_path, consumer, syntax):
    from app.project_test_runner import TestResult
    from app.testing_stage import DiagnosisReviewer, TestingReviewRequest, ReworkRequest
    from app.controlled_rework_stage import ReworkDevelopmentRequest
    from app.development_stage import DevelopmentRequest
    value = 'secret-head CANARY_MIDDLE CANARY_TAIL'
    argv = ('synthetic', '--password', value) if syntax == 'split' else ('synthetic', '--password=' + value)
    result = TestResult(False, 1, '', '', argv)
    if consumer == 'reviewer':
        executor = Mock()
        executor.run.return_value = '{"decision":"rework_required","summary":"synthetic"}'
        DiagnosisReviewer(executor).review(TestingReviewRequest(None, result))
        rendered = executor.run.call_args.args[1]
    else:
        rendered = ReworkDevelopmentRequest(DevelopmentRequest('project', tmp_path, 'fix'), None, result, None,
            ReworkRequest('failed', 'safe', None, result)).task
    assert all(part not in rendered for part in value.split()), 'argument credential fragments reach the LLM input'


@pytest.mark.parametrize('transitive', [False, True])
def test_dependency_chain_retains_all_predecessor_state(tmp_path, transitive):
    from app import verification as v
    observed, roots = {}, []

    class Runner(v.VerificationRunner):
        runner_type = 'synthetic'
        def can_run(self, step):
            return True
        def execute(self, step, root):
            roots.append(root)
            observed[step.step_id] = {p.name for p in root.iterdir()}
            (root / step.step_id).write_text(step.step_id)
            return v.VerificationStepResult(step.step_id, '.', 'pass', 'build', self.runner_type, True)

    def step(name, deps=()):
        return v.VerificationStep(name, '.', '.', 'build', 'synthetic', 'synthetic', 'controlled_execution', depends_on=deps)

    steps = (step('a'), step('b', ('a',)), step('c', ('a', 'b') if transitive else ('b',)))
    result = v.ControlledRunnerRegistry([Runner()]).execute_plan(v.VerificationPlan('chain', str(tmp_path), 'synthetic', 1, steps))
    assert result.passed
    assert observed == {'a': set(), 'b': {'a'}, 'c': {'a', 'b'}}
    assert list(tmp_path.iterdir()) == []
    assert all(not p.exists() for p in roots)


def test_result_callback_cannot_block_public_evaluate(monkeypatch):
    from app.council_models import CouncilInput
    c = council()
    reached, release = threading.Event(), threading.Event()
    results = []

    def callback(**event):
        reached.set()
        release.wait()

    c.set_result_callback(callback)
    monkeypatch.setattr(m, 'create_council_provider', lambda *a: SimpleNamespace(complete=lambda p: '{"variants": []}'))
    monkeypatch.setattr(m, '_outer_deadline', lambda cfg: time.monotonic() + 0.05)
    coordinator = threading.Thread(target=lambda: results.append(c.evaluate(CouncilInput(project_id='synthetic'))))
    try:
        coordinator.start()
        assert reached.wait(1)
        coordinator.join(0.25)
        assert m.council_worker_stats()['live'] == 0
        assert not coordinator.is_alive(), 'public evaluate() hangs in result callback after all provider workers ended'
    finally:
        finish(release, coordinator, [])


def test_waiter_timeout_does_not_quarantine_healthy_holder(monkeypatch):
    holder, waiter = council(), council()
    items = [task(holder, 'holder-with-waiter'), task(waiter, 'holder-with-waiter')]
    reached, release = threading.Event(), threading.Event()
    calls, results = [], []

    def complete(prompt):
        calls.append(1)
        reached.set()
        release.wait()
        return '{}'

    monkeypatch.setattr(m, 'create_council_provider', lambda *a: SimpleNamespace(complete=complete))
    # Bind budgets to config identity before either coordinator starts.
    # Provider entry precedes deadline construction in the coordinator.
    monkeypatch.setattr(m, '_outer_deadline', lambda cfg: time.monotonic() + (2 if cfg is items[0].config else 0.05))
    coordinator = threading.Thread(target=lambda: results.extend(holder._execute_parallel([items[0]], 'phase1')))
    try:
        coordinator.start()
        assert reached.wait(1)
        result = waiter._execute_parallel([items[1]], 'phase1')
        assert not result[0].success
        items[1].worker.join(1)
        assert not items[1].worker.is_alive()
        stats = m.council_worker_stats()
        assert stats['live'] == 1 and stats['abandoned'] == 0
        assert len(calls) == 1
        release.set()
        coordinator.join(1)
        assert results[0].success
    finally:
        finish(release, coordinator, items)
