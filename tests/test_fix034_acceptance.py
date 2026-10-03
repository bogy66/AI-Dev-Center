"""Permanent independent FIX033/034 probes, adapted from Claude scratchpads.

Synthetic transports only. Bounds are measured as UTF-8; weak references prove
actual retention and collection, without the fixture retaining the Council.
"""
import gc
import json
import pytest
import time
import weakref
from app import engineering_council as m
from app.council_models import CouncilInput
from tests.council_contract_support import council, drain
from tests.test_fix032_ownership import ownership, expire  # noqa: F401

def _run(project):
    c = council()
    try:
        c.evaluate(CouncilInput(project_id=project, detected_stack='x' * 200000))
    except RuntimeError as error:
        c._body_thread.join(3)
        return error
    raise AssertionError('not propagated')

def test_failure_after_replace_second_record(ownership, monkeypatch):
    calls = [0]; seen = []
    orig = m.EngineeringCouncil._record_outcome
    def rec(self, ps, vs, result):
        calls[0] += 1
        if calls[0] == 2:
            seen.append(weakref.ref(result))
            raise RuntimeError('synthetic failure in second record')
        return orig(self, ps, vs, result)
    monkeypatch.setattr(m.EngineeringCouncil, '_record_outcome', rec)
    error = _run('p-replace')
    expire(ownership); gc.collect()
    held = seen[0]()
    assert held is not None
    used = ownership.stats()['used_bytes']
    print('HELD', len(repr(held).encode()), 'USED', used)
    assert len(repr(held).encode()) <= used
    assert 'second record' in str(error)
    held = None; error = None; gc.collect()
    assert seen[0]() is None and ownership.stats()['used_bytes'] == 0

def test_storage_refused_then_failure(ownership, monkeypatch):
    seen = []
    monkeypatch.setattr(m.EngineeringCouncil, '_charge_result', lambda self, r: None)
    def rec(self, ps, vs, result):
        seen.append(weakref.ref(result)); raise RuntimeError('synthetic failure refused')
    monkeypatch.setattr(m.EngineeringCouncil, '_record_outcome', rec)
    error = _run('p-refused')
    expire(ownership); gc.collect()
    assert seen[0]() is not None
    st = ownership.stats(); print('REFUSED-HELD', len(repr(seen[0]()).encode()), st)
    assert st['used_bytes'] >= st['envelope_bytes']  # envelope held while result lives
    error = None; gc.collect()
    assert seen[0]() is None and ownership.stats()['used_bytes'] == 0

BIG = 'x' * 200000
size = lambda r: len(repr(r).encode())

def errors(reg, rid):
    rec = reg._records.get(rid) or {}
    return [e for e in rec.get('resource_errors', []) if 'stack cut' in e or 'not retainable' in e]

def exhaust_at_result(registry, monkeypatch):
    """Real pool exhaustion exactly when the deliberated result is charged.

    037 correction: these probes formerly set pool_bytes = envelope_bytes
    before admission and expected the run to proceed with an input the pool
    could not take. SUB_REQ_036/038 require such an admission to be refused
    before provider handover (see test_resource_contract_closure_037). The
    exhaustion is therefore moved behind admission: the input, prompts and
    responses are booked, and the result charge meets a really full pool
    (real reserve_extra, no stub), so the fail-closed path is still proven."""
    original = m.EngineeringCouncil._charge_result
    def charge(self, result):
        registry.pool_bytes = registry.stats()['used_bytes']
        return original(self, result)
    monkeypatch.setattr(m.EngineeringCouncil, '_charge_result', charge)


def test_refused_regular(ownership, monkeypatch):
    exhaust_at_result(ownership, monkeypatch)  # real exhaustion at result charge
    c = council(); r = c.evaluate(CouncilInput(project_id='refused', detected_stack=BIG))
    c._body_thread.join(3); drain(c._activity_lane); drain(c._result_subscription)
    print('\nREGULAR errs', errors(ownership, c._run_id))
    rid = c._run_id; del c; expire(ownership); gc.collect()
    st = ownership.stats()
    print('REGULAR held', size(r), 'marker', m.EngineeringCouncil._STACK_CUT_MARK in r.stack, 'stats', st)
    assert size(r) <= st['used_bytes'] and size(r) <= 8192
    ref = weakref.ref(r); del r; gc.collect()
    print('REGULAR after', ref() is None, ownership.stats())
    assert ref() is None and ownership.stats()['used_bytes'] == 0

def test_refused_then_exception(ownership, monkeypatch):
    exhaust_at_result(ownership, monkeypatch)
    seen = []
    def rec(self, ps, vs, result):
        seen.append(weakref.ref(result)); raise RuntimeError('synthetic finalization failure after refusal')
    monkeypatch.setattr(m.EngineeringCouncil, '_record_outcome', rec)
    c = council()
    try:
        c.evaluate(CouncilInput(project_id='refused-exc', detected_stack=BIG)); raise AssertionError
    except RuntimeError as e:
        c._body_thread.join(3); error = e
    print('\nEXC errs', errors(ownership, c._run_id), '| error:', error)
    del c; expire(ownership); gc.collect()
    held = seen[0](); st = ownership.stats()
    print('EXC held', size(held), 'traceback', error.__traceback__ is not None, 'stats', st)
    assert held is not None and size(held) <= st['used_bytes'] and size(held) <= 8192
    held = None; error = None; gc.collect()
    print('EXC after', seen[0]() is None, ownership.stats())
    assert seen[0]() is None and ownership.stats()['used_bytes'] == 0

def _late(ownership, monkeypatch, project, stack=BIG):
    late = []
    orig_p1 = m.EngineeringCouncil._phase1_independent_proposals
    def slow(self, ci):
        time.sleep(0.8); return orig_p1(self, ci)
    orig = m.EngineeringCouncil._evaluate_admitted
    def body(self, ci):
        r = orig(self, ci); late.append(r); return r
    monkeypatch.setattr(m.EngineeringCouncil, '_phase1_independent_proposals', slow)
    monkeypatch.setattr(m.EngineeringCouncil, '_evaluate_admitted', body)
    orig_prof = m.EngineeringCouncil.operating_profile
    monkeypatch.setattr(m.EngineeringCouncil, 'operating_profile',
        lambda self: dict(orig_prof(self), public_total_seconds=.3))
    claims = []
    orig_claim = m.EngineeringCouncil._claim_finalization
    def claim(self):
        ok = orig_claim(self); claims.append(ok); return ok
    monkeypatch.setattr(m.EngineeringCouncil, '_claim_finalization', claim)
    c = council(); public = c.evaluate(CouncilInput(project_id=project, detected_stack=stack))
    c._body_thread.join(5); assert not c._body_thread.is_alive()
    drain(c._activity_lane); drain(c._result_subscription)
    print(f'\n{project} errs', errors(ownership, c._run_id), 'claims', claims, 'same', public is late[0])
    assert claims == [False] and public is not late[0]
    diagnostic = m.council_diagnosis(c._run_id)
    critical_bytes = len(json.dumps(diagnostic, ensure_ascii=False,
                                   sort_keys=True, default=str).encode('utf-8'))
    call_bytes = sum(size(record) for record in c._call_records)
    combined = critical_bytes + call_bytes + size(public) + size(late[0])
    assert combined <= ownership.stats()['used_bytes'], (combined, ownership.stats())
    assert call_bytes > 0 and diagnostic['outcome']
    del c
    return public, late

def test_late_charged(ownership, monkeypatch):
    public, late = _late(ownership, monkeypatch, 'late-charged')
    expire(ownership); gc.collect(); st = ownership.stats()
    print('LATE-CHARGED public', size(public), 'late', size(late[0]), 'stats', st)
    assert size(public) + size(late[0]) <= st['used_bytes']
    assert 'public deadline' in repr(public)
    del public; late.clear(); gc.collect()
    print('LATE-CHARGED after', ownership.stats()); assert ownership.stats()['used_bytes'] == 0

@pytest.mark.parametrize('stack', [BIG, '😀' * 100000, "'\n\\" * 100000])
def test_late_refused(ownership, monkeypatch, stack):
    exhaust_at_result(ownership, monkeypatch)
    public, late = _late(ownership, monkeypatch, 'late-refused', stack)
    expire(ownership); gc.collect(); st = ownership.stats()
    print('LATE-REFUSED public', size(public), 'late', size(late[0]), 'stats', st)
    assert size(public) + size(late[0]) <= st['used_bytes'] and size(late[0]) <= 8192
    del public; late.clear(); gc.collect()
    print('LATE-REFUSED after', ownership.stats()); assert ownership.stats()['used_bytes'] == 0


def test_supported_project_identity_fits_refused_envelope(ownership, monkeypatch):
    """SUB_REQ_036: public Council input has no project_id length bound."""
    from app.web_api import StartRequest
    project = '😀' * 50000
    request = StartRequest(project_name=project, project_directory='/synthetic',
                           task_description='synthetic')
    assert request.project_name == project
    # 037 correction: formerly pool_bytes = envelope_bytes before admission,
    # which (SUB_REQ_036/038) must refuse the unbookable input instead of
    # running; that refusal is proven in test_resource_contract_closure_037.
    # Here the pool is really exhausted right after admission, so the
    # identity refusal must still fit the existing booking.
    original = m.EngineeringCouncil._evaluate_admitted
    def exhausted(self, value):
        ownership.pool_bytes = ownership.stats()['used_bytes']
        return original(self, value)
    monkeypatch.setattr(m.EngineeringCouncil, '_evaluate_admitted', exhausted)
    c = council()
    result = c.evaluate(CouncilInput(project_id=request.project_name))
    c._body_thread.join(3)
    assert not c._body_thread.is_alive()
    drain(c._activity_lane)
    drain(c._result_subscription)
    try:
        assert not result.council_complete
        assert result.id == c._run_id and len(result.id) == 20
        actual = len(repr(result).encode('utf-8'))
        booked = ownership.stats()['used_bytes']
        assert actual <= booked, ('unbounded supported project identity', actual, booked)
    finally:
        expire(ownership)
        del result, c
        gc.collect()


def test_traceback_held_input_remains_charged(ownership, monkeypatch):
    """SUB_REQ_036: retained references count regardless of input origin."""
    refs = []
    def fail(self, *args, **kwargs):
        raise RuntimeError('synthetic finalization with retained input')
    monkeypatch.setattr(m.EngineeringCouncil, '_record_outcome', fail)
    def capture():
        c = council()
        value = CouncilInput(project_id='input-owner', project_files=('😀' * 200000,))
        refs.append(weakref.ref(value))
        try:
            c.evaluate(value)
        except RuntimeError as error:
            c._body_thread.join(3)
            assert not c._body_thread.is_alive()
            drain(c._activity_lane)
            drain(c._result_subscription)
            return error
        raise AssertionError('not propagated')
    error = capture()
    try:
        expire(ownership)
        gc.collect()
        assert refs[0]() is not None and error.__traceback__ is not None
        actual = len(repr(refs[0]()).encode('utf-8'))
        booked = ownership.stats()['used_bytes']
        assert actual <= booked, ('traceback retains uncharged CouncilInput', actual, booked)
    finally:
        error = None
        gc.collect()
