"""CLAUDE-ADC-RESOURCE-CONTRACT-CLOSURE-037: permanent boundary probes.

SUB_REQ_036/038/040: a run's working data (admitted input, invocation
prompts, provider responses) is booked before it is used for work; when the
pool cannot take it, that work does not happen. A booking ends only when the
last service-side owner (public call, run body, invocation -- a quarantined
worker included --, propagated exception) is actually gone.

Synthetic providers only; private registries and pools; real reserve/release.
"""
import gc
import threading
import time
import weakref
from types import SimpleNamespace

import pytest
from app import council_lifecycle as life
from app import engineering_council as m
from app.council_models import CouncilInput
from tests.council_contract_support import council, drain
from tests.test_fix032_ownership import ownership, expire, completed  # noqa: F401


def _provider(monkeypatch, complete):
    calls = []
    def make(*args):
        def call(prompt):
            calls.append(threading.current_thread())
            return complete(prompt)
        return SimpleNamespace(complete=call)
    monkeypatch.setattr(m, 'create_council_provider', make)
    return calls


def _settle(c):
    c._body_thread.join(3)
    assert not c._body_thread.is_alive()
    drain(c._activity_lane)
    drain(c._result_subscription)


def _invocations(run_id):
    return list((m.council_diagnosis(run_id) or {}).get('invocations', {}).values())


def test_unbookable_input_refuses_admission_bounded_and_recovers(ownership, monkeypatch):
    calls = _provider(monkeypatch, lambda prompt: '{"variants": []}')
    ownership.pool_bytes = ownership.envelope_bytes  # input cannot be booked
    c = council()
    value = CouncilInput(project_id='input-refused', detected_stack='x' * 200000)
    ref = weakref.ref(value)
    with pytest.raises(life.CouncilResourceError, match='input of') as refused:
        c.evaluate(value)
    error = refused.value
    # No provider work and no run; nothing stays booked.
    assert calls == [] and c._body_thread is None
    assert ownership.stats()['used_bytes'] == 0
    assert m._RUN_SLOTS.stats()['busy'] == 0
    # The refusal itself is bounded: a message, no service context, and no
    # frame of the service keeps the refused input.
    assert len(str(error)) < 300
    assert error.__context__ is None and error.__cause__ is None
    del value
    gc.collect()
    assert ref() is None, 'admission refusal keeps the unbooked input alive'
    # Healthy repetition after actual capacity is available again.
    ownership.pool_bytes = 4 * 1024 * 1024
    result = c.evaluate(CouncilInput(project_id='input-retry', detected_stack='x' * 200000))
    _settle(c)
    assert result.project_id == 'input-retry' and len(calls) == 3
    error = refused = None
    expire(ownership)
    del result, c
    gc.collect()
    assert ownership.stats()['used_bytes'] == 0


def test_unbookable_prompt_starts_no_invocation(ownership, monkeypatch):
    calls = _provider(monkeypatch, lambda prompt: '{"variants": []}')
    original = m.EngineeringCouncil._phase1_independent_proposals
    def exhausted(self, value):
        ownership.pool_bytes = ownership.stats()['used_bytes']  # input booked, nothing more
        return original(self, value)
    monkeypatch.setattr(m.EngineeringCouncil, '_phase1_independent_proposals', exhausted)
    c = council()
    result = c.evaluate(CouncilInput(project_id='prompt-refused'))
    _settle(c)
    assert calls == [], 'an invocation ran with an unbooked prompt'
    entries = _invocations(c._run_id)
    assert len(entries) == 3
    assert {e['failure_category'] for e in entries} == {'resource_exhausted'}
    assert not result.council_complete
    assert any('prompt of' in (r.error or '') for r in c._call_records)
    ownership.pool_bytes = 4 * 1024 * 1024
    expire(ownership)
    del result, c
    gc.collect()
    assert ownership.stats()['used_bytes'] == 0


def test_unbookable_response_is_dropped_and_not_retried(ownership, monkeypatch):
    started = threading.Barrier(3)  # all three prompts are booked by now
    def complete(prompt):
        started.wait(2)
        ownership.pool_bytes = ownership.stats()['used_bytes']  # response cannot be booked
        return '{"variants": [' + '"x",' * 20000 + '"x"]}'
    calls = _provider(monkeypatch, complete)
    c = council()
    result = c.evaluate(CouncilInput(project_id='response-refused'))
    _settle(c)
    assert len(calls) == 3, 'one provider call per contributor, no retry'
    entries = _invocations(c._run_id)
    assert {e['failure_category'] for e in entries} == {'resource_exhausted'}
    assert not result.council_complete and not result.variants
    assert all('provider response of' in (r.error or '') for r in c._call_records)
    ownership.pool_bytes = 4 * 1024 * 1024
    expire(ownership)
    del result, c
    gc.collect()
    assert ownership.stats()['used_bytes'] == 0


def test_quarantined_worker_keeps_working_data_booked_until_it_ends(ownership, monkeypatch):
    release = threading.Event()
    prompt_bytes = []
    def complete(prompt):
        prompt_bytes.append(len(prompt.encode()))
        assert release.wait(10)
        return '{"variants": []}'
    workers = _provider(monkeypatch, complete)
    c = council()
    try:
        result = c.evaluate(CouncilInput(project_id='quarantine',
                                         project_files=('synthetic/' + 'x' * 100000,)))
        _settle(c)
        assert len(workers) == 3 and all(w.is_alive() for w in workers)
        assert m._WORKER_POOL.stats()['abandoned'] == 3
        expire(ownership)
        del result, c
        gc.collect()
        # Public completion, body end, retention expiry and collection of the
        # instance do not release what the still-running workers hold.
        held = sum(prompt_bytes)
        assert held > 300000
        assert ownership.stats()['extra_bytes'] >= held, (
            'quarantined work holds unbooked prompts', held, ownership.stats())
    finally:
        release.set()
        for worker in workers:
            worker.join(3)
    assert all(not w.is_alive() for w in workers)
    gc.collect()
    assert ownership.stats()['used_bytes'] == 0
    assert m._WORKER_POOL.stats()['live'] == 0


def test_concurrent_admission_refused_while_capacity_held_then_recovers(ownership, monkeypatch):
    calls = _provider(monkeypatch, lambda prompt: '{"variants": []}')
    entered, release = threading.Event(), threading.Event()
    original = m.EngineeringCouncil._evaluate_admitted
    def body(self, value):
        if value.project_id == 'holder':
            # Pool full beyond this run: no second envelope fits.
            ownership.pool_bytes = ownership.stats()['used_bytes'] + ownership.envelope_bytes - 1
            entered.set()
            assert release.wait(5)
        return original(self, value)
    monkeypatch.setattr(m.EngineeringCouncil, '_evaluate_admitted', body)
    first, results = council(), []
    caller = threading.Thread(target=lambda: results.append(
        first.evaluate(CouncilInput(project_id='holder'))))
    caller.start()
    try:
        assert entered.wait(2)
        other = council()
        with pytest.raises(life.CouncilResourceError):
            other.evaluate(CouncilInput(project_id='overload'))
        assert calls == [] and other._body_thread is None
    finally:
        release.set()
        caller.join(5)
    _settle(first)
    assert len(results) == 1 and len(calls) == 3
    ownership.pool_bytes = 4 * 1024 * 1024
    again = other.evaluate(CouncilInput(project_id='after-release'))
    _settle(other)
    assert again.project_id == 'after-release'
    expire(ownership)
    results.clear()
    del again, other, first
    gc.collect()
    assert ownership.stats()['used_bytes'] == 0


def test_body_exception_in_gc_cycle_keeps_run_data_booked(ownership, monkeypatch):
    calls = _provider(monkeypatch, lambda prompt: '{"variants": []}')
    original = m.EngineeringCouncil._evaluate_admitted
    def fail(self, value):
        original(self, value)
        error = RuntimeError('synthetic late body failure')
        error.cycle = error  # collectable only by the cycle collector
        raise error
    monkeypatch.setattr(m.EngineeringCouncil, '_evaluate_admitted', fail)
    c = council()
    try:
        c.evaluate(CouncilInput(project_id='cycle', detected_stack='y' * 150000))
        raise AssertionError('not propagated')
    except RuntimeError as caught:
        error = caught
    _settle(c)
    assert len(calls) == 3
    expire(ownership)
    del c
    gc.collect()
    assert ownership.stats()['extra_bytes'] >= 150000, 'traceback-held input lost its booking'
    error = None
    gc.collect()
    assert ownership.stats()['used_bytes'] == 0


def test_pending_persistence_payload_booked_until_writer_drops_it(ownership, monkeypatch, tmp_path):
    reached, release = threading.Event(), threading.Event()
    real_sync = life.os.fsync
    def blocked(fd):
        reached.set()
        assert release.wait(5)
        return real_sync(fd)
    monkeypatch.setattr(life.os, 'fsync', blocked)
    c = council()
    c._trace_dir = tmp_path
    try:
        result = c.evaluate(CouncilInput(project_id='persist', detected_stack='z' * 100000))
        assert reached.wait(2) and result.persistence_state == 'unconfirmed'
        _settle(c)
        expire(ownership)
        rid = c._run_id
        del c
        gc.collect()
        # The pending payload carries the 100 KB stack and stays booked.
        assert ownership.stats()['extra_bytes'] >= 100000
    finally:
        release.set()
    until = time.monotonic() + 3
    while m._PERSISTENCE.stats()['busy'] and time.monotonic() < until:
        time.sleep(.01)
    assert m._PERSISTENCE.stats()['busy'] == 0
    assert (tmp_path / 'persist' / f'{rid}.json').exists()
    del result
    gc.collect()
    assert ownership.stats()['used_bytes'] == 0


def test_run_thread_start_failure_releases_input_booking(ownership, monkeypatch):
    original = threading.Thread.start
    def fail_run(thread):
        if thread.name.startswith('council-run-'):
            raise RuntimeError('synthetic native thread creation failure')
        return original(thread)
    monkeypatch.setattr(threading.Thread, 'start', fail_run)
    calls = _provider(monkeypatch, lambda prompt: '{"variants": []}')
    c = council()
    value = CouncilInput(project_id='start-failed', detected_stack='s' * 100000)
    ref = weakref.ref(value)
    with pytest.raises(RuntimeError, match='synthetic native') as failed:
        c.evaluate(value)
    assert calls == [] and ownership.stats()['used_bytes'] == 0
    del value
    gc.collect()
    assert ref() is None, 'start failure traceback keeps the unbooked input'
    assert 'synthetic native' in str(failed.value)
    monkeypatch.setattr(threading.Thread, 'start', original)
    result = c.evaluate(CouncilInput(project_id='start-retry'))
    _settle(c)
    assert result.project_id == 'start-retry'
    failed = None
    expire(ownership)
    del result, c
    gc.collect()
    assert ownership.stats()['used_bytes'] == 0
