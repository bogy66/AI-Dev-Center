"""Independent SUB_REQ_036–038 ownership checks; no fixture holds owners alive."""
import gc
import threading
import time
import weakref
from dataclasses import replace
from types import SimpleNamespace

import pytest
from app import engineering_council as m
from app import council_lifecycle as life
from app.council_models import CouncilInput
from tests.council_contract_support import council, drain


@pytest.fixture
def ownership(monkeypatch):
    registry = life.CouncilDiagnosisRegistry(4 * 1024 * 1024, 65536, 60)
    monkeypatch.setattr(m, '_DIAGNOSIS', registry)
    monkeypatch.setattr(m, '_WORKER_POOL', m._CouncilWorkerPool(16))
    monkeypatch.setattr(m, '_PERSISTENCE', life.PersistenceWriter(8))
    monkeypatch.setattr(m, '_NOTIFIERS', m._NotifierBudget(8))
    monkeypatch.setattr(m, '_RUN_SLOTS', m._RunSlots(16))
    monkeypatch.setattr(m, 'DEFAULT_PROFILE', replace(m.DEFAULT_PROFILE,
        preparation_seconds=.02, finalization_seconds=.03))
    monkeypatch.setattr(m, '_outer_deadline', lambda cfg: time.monotonic() + .5)
    monkeypatch.setattr(m, 'create_council_provider',
        lambda *args: SimpleNamespace(complete=lambda prompt: '{"variants": []}'))
    yield registry
    assert m._RUN_SLOTS.stats()['busy'] == m._PERSISTENCE.stats()['busy'] == 0
    assert m._WORKER_POOL.stats()['live'] == m._NOTIFIERS.stats()['live'] == 0


def expire(registry):
    with registry._lock:
        for record in registry._records.values():
            record['_expires_at'] = time.monotonic() - 1
    registry.stats()


def completed(project):
    c = council()
    result = c.evaluate(CouncilInput(project_id=project))
    c._body_thread.join(3)
    assert not c._body_thread.is_alive()
    drain(c._activity_lane)
    drain(c._result_subscription)
    return c, result


def test_instance_and_session_result_release(ownership, monkeypatch):
    from app.web_api import Session, TraceLevel, sessions
    c, result = completed('owner-release')
    session = Session('ownership', '/synthetic', 'probe', 'workflow', TraceLevel.INFO,
                      SimpleNamespace(events=[]))
    session.pending_engineering_selection = SimpleNamespace(selection=SimpleNamespace(council_result=result))
    monkeypatch.setitem(sessions, session.project_id, session)
    owner_ref, result_ref = weakref.ref(c), weakref.ref(result)
    expire(ownership)
    assert ownership.stats()['used_bytes'] >= len(repr(result).encode())
    del c, result
    gc.collect()
    assert owner_ref() is None
    assert result_ref() is not None
    assert ownership.stats()['used_bytes'] > 0
    sessions.pop(session.project_id)
    del session
    gc.collect()
    assert result_ref() is None
    assert ownership.stats()['used_bytes'] == 0


def test_unbookable_result_fails_closed_and_releases(ownership, monkeypatch):
    # Actual capacity exhaustion when the result is charged; the real
    # reserve/release implementation stays active. 037 correction: formerly
    # the pool held exactly one envelope from before admission, so the input
    # itself was unbookable and the run was expected to proceed anyway --
    # SUB_REQ_036/038 require that admission to be refused (proven in
    # test_resource_contract_closure_037).
    original = m.EngineeringCouncil._charge_result
    def charge(self, result):
        ownership.pool_bytes = ownership.stats()['used_bytes']
        return original(self, result)
    monkeypatch.setattr(m.EngineeringCouncil, '_charge_result', charge)
    c, result = completed('unbookable')
    assert not result.council_complete and not result.council_degraded
    assert 'storage' in repr(result)
    expire(ownership)
    del c
    gc.collect()
    assert ownership.stats()['used_bytes'] > 0
    del result
    gc.collect()
    assert ownership.stats()['used_bytes'] == 0


def test_queue_coalescing_close_and_actual_release(ownership):
    lane = m._DeliveryLane('ownership', pending_limit=4)
    entered, release = threading.Event(), threading.Event()
    class Payload: pass
    def post(key, size, block=False):
        payload = Payload()
        ref = weakref.ref(payload)
        def deliver():
            assert payload is not None
            if block:
                entered.set()
                assert release.wait(3)
        assert lane.post(deliver, key=key, payload_bytes=size)
        return ref
    try:
        inflight = post('active', 100, True)
        assert entered.wait(1)
        old = post('progress', 200)
        new = post('progress', 300)
        gc.collect()
        assert old() is None and new() is not None
        assert ownership.stats()['used_bytes'] == 400
        assert lane.close() == 1
        gc.collect()
        assert new() is None and inflight() is not None
        assert ownership.stats()['used_bytes'] == 100
    finally:
        release.set()
        drain(lane)
    gc.collect()
    assert inflight() is None and ownership.stats()['used_bytes'] == 0


def test_independent_parallel_instances(ownership, monkeypatch):
    barrier = threading.Barrier(2)
    original = m.EngineeringCouncil._evaluate_admitted
    def body(self, *args, **kwargs):
        barrier.wait(2)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(m.EngineeringCouncil, '_evaluate_admitted', body)
    results, errors = [], []
    def run(project):
        try: results.append(completed(project))
        except BaseException as exc: errors.append(exc)
    threads = [threading.Thread(target=run, args=(p,)) for p in ('one', 'two')]
    for thread in threads: thread.start()
    for thread in threads: thread.join(3)
    assert all(not thread.is_alive() for thread in threads)
    assert not errors
    assert {result.project_id for _, result in results} == {'one', 'two'}
    assert len({result.id for _, result in results}) == 2
    expire(ownership)
    results.clear()
    gc.collect()
    assert ownership.stats()['used_bytes'] == 0


def test_retained_exception_traceback_keeps_data_charged(ownership, monkeypatch):
    original = m.EngineeringCouncil._evaluate_admitted
    refs = []
    def fail_after_result(self, value):
        retained = original(self, value)
        refs.append(weakref.ref(retained))
        raise RuntimeError('synthetic retained completion traceback')
    monkeypatch.setattr(m.EngineeringCouncil, '_evaluate_admitted', fail_after_result)
    def capture():
        c = council()
        owner = weakref.ref(c)
        try:
            c.evaluate(CouncilInput(project_id='traceback'))
        except RuntimeError as error:
            c._body_thread.join(3)
            return error, owner
        raise AssertionError('exception not propagated')
    error, owner = capture()
    expire(ownership)
    gc.collect()
    assert owner() is not None and refs[0]() is not None
    assert ownership.stats()['used_bytes'] >= len(repr(refs[0]()).encode())
    del error
    gc.collect()
    assert owner() is None and refs[0]() is None
    assert ownership.stats()['used_bytes'] == 0


def test_same_instance_refusal_starts_no_second_body_and_recovers(ownership, monkeypatch):
    c = council()
    entered, release = threading.Event(), threading.Event()
    original = m.EngineeringCouncil._evaluate_admitted
    calls, results = [], []
    def body(self, value):
        calls.append(value.project_id)
        entered.set()
        assert release.wait(3)
        return original(self, value)
    monkeypatch.setattr(m.EngineeringCouncil, '_evaluate_admitted', body)
    caller = threading.Thread(target=lambda: results.append(c.evaluate(CouncilInput(project_id='first'))))
    caller.start()
    try:
        assert entered.wait(1)
        booked = ownership.stats()['used_bytes']
        with pytest.raises(life.CouncilResourceError, match='instance busy'):
            c.evaluate(CouncilInput(project_id='overlap'))
        assert calls == ['first'] and ownership.stats()['used_bytes'] == booked
    finally:
        release.set()
        caller.join(3)
        c._body_thread.join(3)
    assert not caller.is_alive() and len(results) == 1
    second = c.evaluate(CouncilInput(project_id='healthy'))
    c._body_thread.join(3)
    assert second.project_id == 'healthy' and second.id != results[0].id
    expire(ownership)
    results.clear()
    del second, c, original, body
    gc.collect()
    assert ownership.stats()['used_bytes'] == 0


def test_finalization_exception_keeps_large_result_charged(ownership, monkeypatch):
    """SUB_REQ_036: a propagated finalization traceback is a result owner too."""
    original = m.EngineeringCouncil._charge_result
    refs = []
    def charge(self, result):
        refs.append(weakref.ref(result))
        return original(self, result)
    def fail_record(self, *args, **kwargs):
        raise RuntimeError('synthetic finalization failure after result reservation')
    monkeypatch.setattr(m.EngineeringCouncil, '_charge_result', charge)
    monkeypatch.setattr(m.EngineeringCouncil, '_record_outcome', fail_record)
    def capture():
        c = council()
        try:
            c.evaluate(CouncilInput(project_id='finalization-error', detected_stack='x' * 200000))
        except RuntimeError as error:
            c._body_thread.join(3)
            return error
        raise AssertionError('finalization error not propagated')
    error = capture()
    try:
        expire(ownership)
        gc.collect()
        assert refs[0]() is not None, 'traceback must actually retain the result'
        retained_bytes = len(repr(refs[0]()).encode())
        assert retained_bytes <= ownership.stats()['used_bytes'], (
            'propagated finalization traceback retains an uncharged result',
            retained_bytes, ownership.stats())
    finally:
        error = None
        gc.collect()
        assert refs[0]() is None
        assert ownership.stats()["used_bytes"] == 0
