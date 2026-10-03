"""TEST_037 / SUB_REQ_035-036; real registry, writer, trace and public receiver."""
import asyncio
import json
import threading
import time
from types import SimpleNamespace

import pytest
from app import engineering_council as m
from app import council_lifecycle as life
from app.council_models import CouncilInput, CouncilResult, ProposalSet
from app.diagnostic_trace import DiagnosticTrace, DiagnosticTraceStore
from tests.council_contract_support import contract_env, council, drain
from tests.test_productive_web_e2e import disposable_productive_web


def test_reservation_retention_and_copy_isolation():
    registry = life.CouncilDiagnosisRegistry(4096, 4096, 60)
    registry.admit('old', {})
    registry.complete('old')
    with pytest.raises(life.CouncilResourceError): registry.admit('new', {})
    retrieved = registry.get('old')
    retrieved['state'] = 'changed by caller'
    assert registry.get('old')['state'] == 'completed'
    assert registry.stats()['used_bytes'] == 4096


@pytest.mark.parametrize('field', ['outcome', 'resource_errors', 'unicode'])
def test_unexpected_size_is_bounded_in_bytes_and_visible(field):
    registry = life.CouncilDiagnosisRegistry(65536, 65536, 60)
    registry.admit('overflow', {})
    def change(record):
        if field == 'outcome': record['outcome'] = {'recommendation': 'x' * 100000}
        elif field == 'resource_errors': record['resource_errors'] = ['x' * 100000]
        else: record['outcome'] = {'decision_errors': ['😀' * 20000]}
    registry.update('overflow', change)
    record = registry.get('overflow')
    actual = len(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str).encode())
    assert actual <= 65536, ('uncharged critical record bytes', field, actual, registry.stats())
    assert record.get('size_exceeded') and record['omitted']
    assert record['run_id'] == 'overflow'


def test_critical_outcome_uses_existing_secret_redaction(contract_env):
    c = council()
    c._run_id = 'secret'
    contract_env.admit('secret', {})
    c._record_outcome(ProposalSet(), (), CouncilResult(id='secret', project_id='p',
        agent_errors=('AWS_SECRET_ACCESS_KEY="synthetic-contract-secret"',)))
    assert 'synthetic-contract-secret' not in json.dumps(m.council_diagnosis('secret'))


def test_failed_write_is_separate_from_functional_snapshot(contract_env, tmp_path, monkeypatch):
    c = council()
    c._trace_dir = tmp_path
    monkeypatch.setattr(life.os, 'fsync', lambda fd: (_ for _ in ()).throw(OSError('synthetic write error')))
    result = c.evaluate(CouncilInput(project_id='failed'))
    record = m.council_diagnosis(result.id)
    assert result.persistence_state == record['persistence']['state'] == 'failed'
    assert record['outcome']['result_id'] == result.id
    assert record['persistence']['error'] == 'OSError'
    assert m.council_resource_stats()['persistence']['busy'] == 0


def test_blocked_write_late_confirmation_only_updates_durability(contract_env, tmp_path, monkeypatch):
    c, release, reached = council(), threading.Event(), threading.Event()
    c._trace_dir = tmp_path
    real_sync = life.os.fsync
    def blocked(fd):
        reached.set()
        release.wait()
        return real_sync(fd)
    monkeypatch.setattr(life.os, 'fsync', blocked)
    started = time.monotonic()
    try:
        result = c.evaluate(CouncilInput(project_id='blocked'))
        assert reached.is_set() and time.monotonic() - started < c.operating_profile()['public_total_seconds'] + .08
        assert result.persistence_state == 'unconfirmed'
        original = repr(result)
        outcome = m.council_diagnosis(result.id)['outcome']
        assert m.council_resource_stats()['persistence']['busy'] == 1
        release.set()
        until = time.monotonic() + 3
        while m.council_diagnosis(result.id)['persistence']['state'] != 'confirmed' and time.monotonic() < until:
            time.sleep(.005)
        assert m.council_diagnosis(result.id)['persistence']['state'] == 'confirmed'
        assert repr(result) == original and m.council_diagnosis(result.id)['outcome'] == outcome
    finally:
        release.set()
        for thread in threading.enumerate():
            if thread.name == 'council-persist': thread.join(3)


def test_confirmed_reload_preserves_critical_completion_diagnosis(contract_env, tmp_path):
    c = council()
    c._trace_dir = tmp_path
    result = c.evaluate(CouncilInput(project_id='reload'))
    assert result.persistence_state == 'confirmed'
    stored = json.loads((tmp_path / 'reload' / (result.id + '.json')).read_text())
    # Actual confirmed file, not the volatile registry. No invented reload API.
    serialized = json.dumps(stored)
    assert 'invocation_id' in serialized and 'handover' in serialized, 'confirmed trace omits lifecycle causes'
    assert 'persistence' in serialized and 'council_complete' in serialized


def test_public_query_retrieves_critical_diagnosis_when_callbacks_block(
    contract_env, disposable_productive_web, monkeypatch,
):
    """Real canonical workflow receiver -> store -> public production query.

    Only external contributors and the receiver's blocking schedule are
    synthetic. FIX019 wakeup, if explicitly selected, is an ASGI surrogate.
    """
    from app import web_api
    _, project, compose = disposable_productive_web
    components = compose()
    service = components.service
    c = components.development_workflow._council
    trace = service._diagnostic_trace
    release, reached = threading.Event(), threading.Event()
    record = trace.record
    def blocked(*args, **kwargs):
        if threading.current_thread().name.startswith('council-notify-'):
            reached.set()
            release.wait()
        return record(*args, **kwargs)
    monkeypatch.setattr(trace, 'record', blocked)
    session = web_api.Session('contract-public', str(project), 'probe', 'workflow',
        web_api.TraceLevel.INFO, SimpleNamespace(events=[]))
    session.project_setup_service = service
    monkeypatch.setitem(web_api.sessions, 'contract-public', session)
    try:
        planning = service.plan_project_setup('public', project, 'workflow',
            entry_data={'task_description': 'Inspect this disposable project'})
        result = planning.council_result
        session.workflow_status = 'completed'
        assert reached.is_set() and m.council_diagnosis(result.id)['outcome']
        # Exercise routing and JSON serialization as well as the receiver.
        # Native in-process ASGI, without TestClient's cross-thread wakeup.
        import httpx
        async def query_public_routes():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web_api.app),
                                         base_url='http://local-asgi') as client:
                public = await client.get('/api/workflow/contract-public/diagnostic-trace')
                state = await client.get('/api/state/contract-public')
                assert public.status_code == state.status_code == 200
                return public.json(), state.json()
        public, state = asyncio.run(query_public_routes())
        combined = json.dumps({'trace': public, 'state': state})
        assert c._run_id in combined and result.id in combined, 'internal registry never reaches public query'
        assert 'handover' in combined and 'persistence' in combined, 'public query lacks critical lifecycle causes'
    finally:
        release.set()
        drain(c._activity_lane)
        drain(c._result_subscription)


def test_public_terminal_state_allows_marked_late_history(tmp_path):
    from app.web_api import _current_activity_event
    trace = DiagnosticTrace(DiagnosticTraceStore(tmp_path / 'events.jsonl'))
    for state in ('thinking', 'completed', 'thinking', 'completed'):
        trace.record('run', 'engineering_council', 'completed' if state == 'completed' else 'started', 'completed' if state == 'completed' else 'started', state,
                     details={'invocation_id': 'one', 'runtime_state': state})
    events = trace.get_trace('run')
    assert events[-2].details['runtime_state'] == 'thinking'
    assert _current_activity_event(events).details['runtime_state'] == 'completed'


def test_service_held_prompt_copies_count_against_memory_limits(contract_env):
    c = council()
    result = c.evaluate(CouncilInput(project_id='copies', project_files=('synthetic/' + 'x' * 200000,)))
    held = sum(len(prompt.encode()) for prompt in c._effective_prompts.values())
    charged = contract_env.stats()['used_bytes']
    assert held <= charged, ('service-held copies omitted from storage accounting', held, charged)
    assert m.council_diagnosis(result.id) is not None


def test_storage_reservation_exhaustion_refuses_before_provider(contract_env, tmp_path, monkeypatch):
    writer = life.PersistenceWriter(1)
    monkeypatch.setattr(m, '_PERSISTENCE', writer)
    assert writer.reserve()
    c = council()
    c._trace_dir = tmp_path
    calls = []
    monkeypatch.setattr(m, 'create_council_provider', lambda *args: calls.append(args))
    try:
        with pytest.raises(life.CouncilResourceError): c.evaluate(CouncilInput(project_id='refused'))
        assert calls == []
        assert writer.stats()['busy'] == 1
    finally:
        writer.release()


def test_retained_protocols_remain_charged_after_diagnosis_expiry(contract_env):
    """SUB_REQ_036: expiry of a booking does not free service-held objects."""
    c = council()
    result = c.evaluate(CouncilInput(project_id='expired-protocol'))
    c._body_thread.join(3)
    assert c._call_records, 'probe must retain actual productive call records'
    with contract_env._lock:
        contract_env._records[c._run_id]['_expires_at'] = time.monotonic() - 1
    assert contract_env.get(result.id) is None
    held = sum(len(repr(record).encode()) for record in c._call_records)
    assert held <= contract_env.stats()['used_bytes'], (
        'ADC Council still owns protocols after their reservation expires', held,
        contract_env.stats())


def test_run_thread_start_failure_releases_admission_reservations(contract_env, tmp_path, monkeypatch):
    """SUB_REQ_036/038: failed admission must not poison future capacity."""
    c = council()
    c._trace_dir = tmp_path
    original = threading.Thread.start
    def fail_run(thread):
        if thread.name.startswith('council-run-'):
            raise RuntimeError('synthetic native thread creation failure')
        return original(thread)
    monkeypatch.setattr(threading.Thread, 'start', fail_run)
    try:
        with pytest.raises(RuntimeError, match='synthetic native'):
            c.evaluate(CouncilInput(project_id='start-failed'))
        assert m._PERSISTENCE.stats()['busy'] == 0, 'unused persistence slot leaked'
        assert contract_env.stats()['used_bytes'] == 0, 'unused diagnosis reservation leaked'
    finally:
        # Explicit probe cleanup, after assertions; never hide leaked capacity.
        if m._PERSISTENCE.stats()['busy']:
            m._PERSISTENCE.release()


def test_web_owned_result_is_charged_after_registry_expiry(
    contract_env, disposable_productive_web, monkeypatch,
):
    """SUB_REQ_036: productive Web pause retains ADC-owned result references."""
    from app import web_api
    _, project, compose = disposable_productive_web
    components = compose()
    session = web_api.Session('retained-web', str(project), 'Inspect project', 'web-retention',
                              web_api.TraceLevel.INFO,
                              web_api.DiagnosticTraceRecorder('web-retention'))
    monkeypatch.setitem(web_api.sessions, session.project_id, session)
    web_api._run_initial_planning(session, components)
    pending = session.pending_engineering_selection
    assert pending is not None, 'probe must reach productive S2.4 Web pause'
    result = pending.selection.council_result
    assert result is not None
    c = components.development_workflow._council
    c._body_thread.join(3)
    drain(c._activity_lane)
    drain(c._result_subscription)
    with contract_env._lock:
        for record in contract_env._records.values():
            record['_expires_at'] = time.monotonic() - 1
    assert contract_env.get(result.id) is None
    assert web_api.sessions[session.project_id].pending_engineering_selection.selection.council_result is result
    assert len(repr(result).encode()) <= contract_env.stats()['used_bytes'], (
        'Web service owns Council result with no surviving storage reservation',
        contract_env.stats())


def test_blocked_notification_prompt_remains_charged(contract_env):
    """SUB_REQ_036/037: an in-flight callback still owns its queued payload.

    The test retains only a byte count, never an external prompt reference.
    The productive lane's invocation closure retains the actual dictionary.
    """
    c = council()
    reached, release = threading.Event(), threading.Event()
    prompt_bytes = []
    def receiver(**event):
        if event.get('effective_prompt'):
            prompt_bytes.append(len(event['effective_prompt'].encode()))
            reached.set()
            release.wait()
    c.set_activity_callback(receiver)
    try:
        c.evaluate(CouncilInput(project_id='blocked-prompt', project_files=('synthetic/' + 'x' * 200000,)))
        assert reached.wait(1), 'probe must block an actual prompt-bearing notification'
        assert c.notification_state()['activity']['unconfirmed'] > 0
        assert prompt_bytes[0] <= contract_env.stats()['used_bytes'], (
            'in-flight notification retains a prompt after its charge is released',
            prompt_bytes[0], contract_env.stats())
    finally:
        release.set()
        drain(c._activity_lane)
