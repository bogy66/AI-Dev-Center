"""TEST_036 / SUB_REQ_033-034. Component probes are transport surrogates;
native HTTP/TLS/proxy probes are in test_council_contract_native_transport.
"""
import socket
import threading
import time
from types import SimpleNamespace

import pytest
import urllib3.connection
from app import engineering_council as m
from app import council_lifecycle as life
from tests.council_contract_support import contract_env, council, task, join


def test_closure_and_budget_cover_each_actual_handover():
    lock, closed, sent = threading.Lock(), threading.Event(), []
    gate = life.HandoverGate(lock, closed.is_set, 2)
    gate.hand_over(lambda: sent.append('first'))
    gate.hand_over(lambda: sent.append('automatic retry'))
    with pytest.raises(life.HandoverRefused):
        gate.hand_over(lambda: sent.append('over budget'))
    with lock:
        closed.set()
    with pytest.raises(life.HandoverRefused):
        gate.hand_over(lambda: sent.append('after close'))
    assert sent == ['first', 'automatic retry']
    assert gate.summary()['remote_uncertain'] == 2
    assert gate.summary()['refused_budget'] == gate.summary()['refused_after_close'] == 1
    unrelated = life.HandoverGate(threading.Lock(), lambda: False, 1)
    unrelated.hand_over(lambda: sent.append('unrelated'))
    assert unrelated.summary()['handovers'] == 1


def test_failed_first_write_remains_counted_and_uncertain():
    gate = life.HandoverGate(threading.Lock(), lambda: False, 1)
    def failed():
        raise socket.timeout('synthetic first write')
    with pytest.raises(socket.timeout):
        gate.hand_over(failed)
    assert gate.summary()['handovers'] == gate.summary()['remote_uncertain'] == 1
    assert gate.summary()['remote_confirmed'] == 0
    with pytest.raises(life.HandoverRefused):
        gate.hand_over(lambda: None)


def test_unverified_binding_is_exposed_without_transport_claim(contract_env):
    c = council()
    item = task(c)
    c._run_id = 'unverified'
    contract_env.admit(c._run_id, {})
    result = c._execute_parallel([item], 'phase1')
    join(item.worker)
    assert result[0].success
    record = m.council_diagnosis(c._run_id)['invocations'][item.invocation_id]
    assert record['handover']['boundary'] == life.UNVERIFIED_BOUNDARY
    assert record['handover'].get('remote_confirmed', 0) == 0


@pytest.mark.parametrize('late_failure', [False, True])
def test_late_outcome_cannot_change_snapshot_or_retry(contract_env, monkeypatch, late_failure):
    c, release, reached = council(), threading.Event(), threading.Event()
    calls = []
    def complete(prompt):
        calls.append(prompt)
        reached.set()
        release.wait()
        if late_failure:
            raise RuntimeError('late synthetic failure')
        return '{}'
    monkeypatch.setattr(m, 'create_council_provider', lambda *a: SimpleNamespace(complete=complete))
    c._run_id = 'late'
    contract_env.admit('late', {})
    item = task(c)
    try:
        result = c._execute_parallel([item], 'phase1')
        assert reached.is_set() and not result[0].success
        before = (repr(result), repr(c._call_records), item.terminal_state)
        release.set()
        join(item.worker)
        assert before == (repr(result), repr(c._call_records), item.terminal_state)
        assert len(calls) == 1
        additions = m.council_diagnosis('late')['late_additions']
        assert additions and additions[0]['invocation_id'] == item.invocation_id
        assert additions[0]['event_time'] <= additions[0]['received_time']
    finally:
        release.set()
        join(item.worker)


def test_first_write_lock_does_not_extend_call_deadline(contract_env, monkeypatch):
    """SURROGATE socket honours settimeout, real mixin/HTTPConnection.send.

    The configured first-write timeout must fit the remaining public/call
    budget; waiting for the invocation lock is part of that elapsed time.
    """
    reached = threading.Event()
    class Socket:
        timeout = None
        def gettimeout(self): return self.timeout
        def settimeout(self, value): self.timeout = value
        def sendall(self, data):
            reached.set()
            time.sleep(self.timeout)
            raise socket.timeout('first-byte send stalled')
    class Connection(life._GatedConnectionMixin, urllib3.connection.HTTPConnection):
        pass
    provider = SimpleNamespace()
    def bind(p, gate, send_timeout):
        connection = Connection('127.0.0.1')
        connection.sock = Socket()
        connection._adc_gate = gate
        connection._adc_send_timeout = send_timeout
        def complete(prompt):
            connection._adc_pending = True
            connection.send(b'POST /synthetic HTTP/1.1\r\n')
        p.complete = complete
        return True
    monkeypatch.setattr(m, 'bind_handover_gate', bind)
    monkeypatch.setattr(m, 'create_council_provider', lambda *a: provider)
    c, item = council(), None
    item = task(c)
    started = time.monotonic()
    try:
        result = c._execute_parallel([item], 'phase1')
        elapsed = time.monotonic() - started
        assert reached.is_set() and not result[0].success
        assert elapsed <= .12 + .08, ('first write blocked deadline closure', elapsed)
    finally:
        join(item.worker)


@pytest.mark.parametrize('scope', ['contributor_call', 'phase', 'council'])
def test_timeout_scope_is_identified_and_does_not_mix_invocations(contract_env, monkeypatch, scope):
    c, release, reached = council(), threading.Event(), threading.Event()
    c._run_id = 'scope-' + scope
    contract_env.admit(c._run_id, {})
    now = time.monotonic()
    profile = c.operating_profile()
    profile['phase_seconds']['phase1'] = .03 if scope == 'phase' else .2
    c._run = m._CouncilRun(c._run_id, now, now + (.05 if scope == 'council' else 1), profile)
    monkeypatch.setattr(m, '_outer_deadline', lambda cfg: time.monotonic() + (.03 if scope == 'contributor_call' else .5))
    def complete(prompt):
        reached.set()
        release.wait()
        return '{}'
    monkeypatch.setattr(m, 'create_council_provider', lambda *a: SimpleNamespace(complete=complete))
    item = task(c, scope)
    try:
        result = c._execute_parallel([item], 'phase1')
        assert reached.is_set() and not result[0].success
        record = m.council_diagnosis(c._run_id)['invocations'][item.invocation_id]
        assert record['timeout_scope'] == scope
    finally:
        release.set()
        join(item.worker)


def test_nonterminal_attempt_failure_can_retry_without_resetting_budget(contract_env, monkeypatch):
    c, calls = council(), []
    def complete(prompt):
        calls.append(prompt)
        if len(calls) == 1: raise TimeoutError('synthetic attempt timeout')
        return '{}'
    monkeypatch.setattr(m, 'create_council_provider', lambda *a: SimpleNamespace(complete=complete))
    item = task(c, 'attempt')
    try:
        result = c._execute_parallel([item], 'phase1')
        assert result[0].success and len(calls) == 2
        assert len(c._call_records) == 2 and not c._call_records[0].success
        assert c._call_records[1].success
        assert item.deadline - time.monotonic() <= .12
    finally: join(item.worker)


@pytest.mark.parametrize('status', [401, 429, 503])
def test_rejected_response_does_not_confirm_provider_acceptance(status):
    """SUB_REQ_034 distinguishes irreversible transfer from acceptance.

    A rejection (potentially generated by a proxy) cannot be counted as
    confirmed provider acceptance merely because HTTP headers arrived.
    """
    gate = life.HandoverGate(threading.Lock(), lambda: False, 1)
    gate.hand_over(lambda: None)
    gate.response_received(status)
    assert gate.summary()['handovers'] == 1
    assert gate.summary()['remote_confirmed'] == 0, ('rejection counted as acceptance', status)
