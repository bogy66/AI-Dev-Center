"""Independent Council/trace regressions; fake providers and temporary state only."""
from dataclasses import replace
from datetime import datetime
import json
import threading
import time
from types import SimpleNamespace

import pytest
from app import engineering_council as m
from app.ai_config import CouncilConfig
from app.diagnostic_trace import DiagnosticTrace, DiagnosticTraceStore, DiagnosticDetailLevel, render_diagnostic_trace_event


def council():
    return m.EngineeringCouncil(CouncilConfig(enabled=True), lambda _: 'unused')


def task(c, slot='same'):
    cfg=replace(c._config.environment_architect,model=slot)
    return m._AgentTask('A1','environment_architect',cfg,'synthetic','phase1',datetime.now())


def fake_provider(monkeypatch,release,workers):
    def complete(prompt):
        workers.append(threading.current_thread())
        assert release.wait(5)
        return '{"variants": []}'
    monkeypatch.setattr(m,'create_council_provider',lambda *a:SimpleNamespace(complete=complete))
    monkeypatch.setattr(m,'_outer_deadline',lambda cfg:time.monotonic()+0.1)


def cleanup(release,workers,coordinators=()):
    release.set()
    for t in [*coordinators,*workers]: t.join(3)
    assert all(not t.is_alive() for t in [*coordinators,*workers])
    assert m.council_worker_stats()['live']==0


def test_processwide_capacity_admission_and_release_across_instances(monkeypatch):
    assert m.council_worker_stats()['live']==0
    release=threading.Event(); workers=[]; cs=[council() for _ in range(24)]
    fake_provider(monkeypatch,release,workers)
    start=threading.Barrier(25)
    results=[]
    def run(i):
        start.wait(3)
        results.append(cs[i]._execute_parallel([task(cs[i],str(i))],'phase1'))
    coordinators=[threading.Thread(target=run,args=(i,)) for i in range(24)]
    try:
        for t in coordinators:t.start()
        start.wait(3)
        for t in coordinators:t.join(2)
        assert len(results)==24
        assert len(workers)==16
        assert m.council_worker_stats()['live']==16
        assert sum('capacity' in r[0].error for r in results)==8
        started=time.monotonic()
        r=council()._execute_parallel([task(cs[0],'overflow')],'phase1')
        assert time.monotonic()-started<0.2 and 'capacity' in r[0].error
        assert len(workers)==16
    finally:cleanup(release,workers,coordinators)
    # Actual completion releases capacity for a subsequent invocation.
    monkeypatch.setattr(m,'create_council_provider',lambda *a:SimpleNamespace(complete=lambda p:'{}'))
    assert council()._execute_parallel([task(cs[0],'after')],'phase1')[0].success


def test_same_slot_concurrent_timeouts_leave_at_most_one_abandoned_worker(monkeypatch):
    release=threading.Event(); workers=[]
    fake_provider(monkeypatch,release,workers)
    cs=[council(),council()]
    start=threading.Barrier(3)
    def run(c):
        start.wait(2); c._execute_parallel([task(c)],'phase1')
    coordinators=[threading.Thread(target=run,args=(c,)) for c in cs]
    try:
        for t in coordinators:t.start()
        start.wait(2)
        for t in coordinators:t.join(2)
        assert all(not t.is_alive() for t in coordinators)
        assert len(workers)<=1, f'{len(workers)} live abandoned workers share the same slot; stats={m.council_worker_stats()}'
    finally:cleanup(release,workers,coordinators)


def test_no_retry_can_start_after_concurrent_timeout(monkeypatch):
    c=council(); release=threading.Event(); reached=threading.Event(); calls=[]; worker=[]
    def complete(prompt):
        calls.append(1); worker.append(threading.current_thread())
        raise RuntimeError('synthetic provider error')
    monkeypatch.setattr(m,'create_council_provider',lambda *a:SimpleNamespace(complete=complete))
    monkeypatch.setattr(m,'_outer_deadline',lambda cfg:time.monotonic()+0.1)
    activity=c._activity; thinking=[]
    def observed(t,state,**kw):
        activity(t,state,**kw)
        if state=='thinking':
            thinking.append(1)
            if len(thinking)==2:
                reached.set(); assert release.wait(3)
    monkeypatch.setattr(c,'_activity',observed)
    t=task(c)
    try:
        result=c._execute_parallel([t],'phase1')
        assert reached.is_set() and t.activity_closed.is_set() and not result[0].success
        release.set(); t.worker.join(2)
        assert len(calls)==1, 'retry provider invocation started after timeout finalization'
    finally:cleanup(release,[t.worker] if t.worker else [])


@pytest.mark.parametrize('text,secret',[
    ('AWS_SECRET_ACCESS_KEY="prefix-secret-'+ 'x'*10000, 'prefix-secret-'),
    ('"AWS_SECRET_ACCESS_KEY": "prefix-secret-'+ 'x'*10000, 'prefix-secret-'),
    ('\\"AWS_SECRET_ACCESS_KEY\\": \\"escaped-secret-'+ 'x'*10000, 'escaped-secret-'),
    ('-----BEGIN RSA PRIVATE KEY-----pem-secret-'+ 'x'*10000, 'pem-secret-'),
    ('https://user:url-secret-'+ 'x'*10000+'@example.invalid/', 'url-secret-'),
    ('https://user:url-secret-'+ 'x'*600+'@example.invalid/', 'url-secret-'),
    ('SESSION="session-secret-', 'session-secret-'),
    ('BEARER=bearer-secret-', 'bearer-secret-'),
])
def test_boundary_forms_persistence_and_levels(tmp_path,text,secret):
    trace=DiagnosticTrace(DiagnosticTraceStore(tmp_path/'events.jsonl'))
    for offset in (0,90,490,2990):
        value='z '* (offset//2)+text
        event=trace.record('run','development','started','started',value,source=value,
                           details={'effective_prompt':value,'council_output':{'very_verbose':{'summary':value}}})
        leaks=['persisted'] if secret in trace.store.path.read_text() else []
        for level in DiagnosticDetailLevel:
            if secret in render_diagnostic_trace_event(event,level):leaks.append(level.value)
        assert not leaks, f'credential survives at offset {offset}: {leaks}'


@pytest.mark.parametrize('leaf',[0,True,None,'漢字😀\n"\\'])
def test_documented_serialized_character_budget_includes_overhead(tmp_path,leaf):
    trace=DiagnosticTrace(DiagnosticTraceStore(tmp_path/'events.jsonl'))
    value={'very_verbose':{'reviews':[[leaf]*50 for _ in range(50)],'scores':[[leaf]*50 for _ in range(50)]}}
    event=trace.record('run','development','started','started','safe',details={
        'council_output':value,'interface_data':value,'execution_identity':value,
        'diagnostics':[leaf]*50,'effective_prompt':'😀'*10000})
    serialized=json.dumps(event.details,ensure_ascii=False,sort_keys=True)
    print('json_characters',len(serialized),'utf8_bytes',len(serialized.encode()),'rendered',len(render_diagnostic_trace_event(event,'VERY_VERBOSE')))
    assert len(serialized)<=40000, 'documented total serialized JSON character budget exceeded'


def test_completed_before_deadline_never_gets_second_timeout_terminal(monkeypatch):
    c=council(); release=threading.Event(); activities=[]; deadline_values=[]
    c.set_activity_callback(lambda **kw:activities.append(kw))
    first=task(c,'first'); second=task(c,'second'); second.agent_id='A2'
    def factory(config,*args):
        def complete(prompt):
            if config.model=='second':assert release.wait(3)
            return '{}'
        return SimpleNamespace(complete=complete)
    monkeypatch.setattr(m,'create_council_provider',factory)
    def deadline(config):
        value=time.monotonic()+0.2;deadline_values.append(value);return value
    monkeypatch.setattr(m,'_outer_deadline',deadline)
    commit=c._commit_task_state
    finished=[]
    def delayed_commit(t):
        commit(t)
        if t is first:
            release.set(); second.worker.join(1)
            finished.append(time.monotonic())
            time.sleep(0.25) # coordinator descheduled; provider already finished
    monkeypatch.setattr(c,'_commit_task_state',delayed_commit)
    try:
        result=c._execute_parallel([first,second],'phase1')
        assert finished[0]<min(deadline_values), 'probe must finish provider before deadline'
        terminal=[a['runtime_state'] for a in activities if a['actor']=='Agent A2' and a['runtime_state'] in {'completed','failed'}]
        assert terminal==['completed'] and result[1].success, f'contradictory finalized lifecycle: {terminal}'
    finally:cleanup(release,[t.worker for t in (first,second) if t.worker])
