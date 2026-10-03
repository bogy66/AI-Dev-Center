"""TEST_038 / SUB_REQ_037-038: bounded serial lanes and counted resources."""
import threading
import time
from types import SimpleNamespace

import pytest
from app import engineering_council as m
from app.council_models import CouncilInput
from app.council_lifecycle import CouncilDiagnosisRegistry, CouncilResourceError
from tests.council_contract_support import contract_env, council, task, join, drain


def test_serial_bounded_queue_and_distinct_delivery_states(contract_env):
    lane = m._DeliveryLane('serial-contract', pending_limit=2)
    release, reached = threading.Event(), threading.Event()
    deliveries = []
    def blocked():
        reached.set()
        release.wait()
        deliveries.append('first')
    try:
        assert lane.post(blocked)
        assert reached.wait(1)
        assert lane.post(lambda: deliveries.append('second'))
        assert lane.post(lambda: (_ for _ in ()).throw(ValueError('receiver error')))
        assert not lane.post(lambda: deliveries.append('overflow'))
        assert lane.delivery_counts() == {'delivered': 0, 'failed': 0, 'skipped': 1, 'unconfirmed': 3}
        assert deliveries == [] and m.council_notifier_stats()['live'] == 1
        release.set()
        drain(lane)
        assert deliveries == ['first', 'second']
        assert lane.delivery_counts() == {'delivered': 2, 'failed': 1, 'skipped': 1, 'unconfirmed': 0}
    finally:
        release.set()
        drain(lane)


def test_closed_queue_counts_omitted_deliveries(contract_env):
    lane, release, reached = m._DeliveryLane('close-contract'), threading.Event(), threading.Event()
    try:
        lane.post(lambda: (reached.set(), release.wait()))
        assert reached.wait(1)
        for _ in range(3): assert lane.post(lambda: None)
        assert lane.close() == 3
        assert lane.delivery_counts()['skipped'] == 3, 'close discarded delivery facts without accounting'
        assert lane.delivery_counts()['unconfirmed'] == 1
    finally:
        release.set()
        drain(lane)


@pytest.mark.parametrize('kind', ['activity', 'results'])
def test_blocked_subscription_across_repeated_public_runs(contract_env, kind):
    c, release, reached = council(), threading.Event(), threading.Event()
    running, peak = [], []
    def receiver(**event):
        running.append(1)
        peak.append(len(running))
        reached.set()
        release.wait()
        running.pop()
    getattr(c, 'set_' + ('activity' if kind == 'activity' else 'result') + '_callback')(receiver)
    lane = c._activity_lane if kind == 'activity' else c._result_subscription
    try:
        first = c.evaluate(CouncilInput(project_id='first'))
        assert reached.is_set()
        second = c.evaluate(CouncilInput(project_id='second'))
        assert first.id != second.id
        assert m.council_diagnosis(first.id)['outcome']['result_id'] == first.id
        assert m.council_diagnosis(second.id)['outcome']['result_id'] == second.id
        assert peak == [1] and lane.delivery_counts()['delivered'] == 0
        assert lane.delivery_counts()['unconfirmed'] <= lane.pending_limit + 1
    finally:
        release.set()
        drain(lane)


def test_diagnosis_overload_refuses_before_provider_and_preserves_prior(contract_env, monkeypatch):
    # 037 correction: formerly a pool of exactly one envelope, so the first
    # run could not book its own input and was expected to run anyway
    # (SUB_REQ_036/038 forbid that). Now the pool takes one run's envelope
    # and working data but never a second envelope beside the retained one.
    registry = CouncilDiagnosisRegistry(2 * 65536 - 1, 65536, 60)
    monkeypatch.setattr(m, '_DIAGNOSIS', registry)
    first = council().evaluate(CouncilInput(project_id='old'))
    calls = []
    monkeypatch.setattr(m, 'create_council_provider', lambda *args: calls.append(args))
    with pytest.raises(CouncilResourceError): council().evaluate(CouncilInput(project_id='rejected'))
    assert calls == [] and registry.get(first.id)['outcome']['result_id'] == first.id


def test_concurrent_quarantine_and_recovery_after_actual_release(contract_env, monkeypatch):
    pool = m._CouncilWorkerPool(2)
    monkeypatch.setattr(m, '_WORKER_POOL', pool)
    release, entered = threading.Event(), [threading.Event(), threading.Event()]
    cs = [council(), council()]
    items = [task(c, str(i)) for i, c in enumerate(cs)]
    def factory(cfg, *args):
        def complete(prompt):
            entered[int(cfg.model)].set()
            release.wait()
            return '{}'
        return SimpleNamespace(complete=complete)
    monkeypatch.setattr(m, 'create_council_provider', factory)
    results = [None, None]
    owners = [threading.Thread(target=lambda i=i: results.__setitem__(i, cs[i]._execute_parallel([items[i]], 'phase1'))) for i in range(2)]
    try:
        for owner in owners: owner.start()
        assert all(event.wait(1) for event in entered)
        for owner in owners: join(owner)
        assert pool.stats() == {'live': 2, 'abandoned': 2, 'capacity': 2}
        rejected = task(council(), 'rejected')
        result = council()._execute_parallel([rejected], 'phase1')
        assert not result[0].success and rejected.worker is None
        assert rejected.terminal_state[1] == 'resource_exhausted'
        release.set()
        for item in items: join(item.worker)
        assert pool.stats()['live'] == 0
        monkeypatch.setattr(m, 'create_council_provider', lambda *a: SimpleNamespace(complete=lambda p: '{}'))
        healthy = task(council(), 'healthy')
        assert council()._execute_parallel([healthy], 'phase1')[0].success
        join(healthy.worker)
    finally:
        release.set()
        for owner in owners: join(owner)
        for item in items: join(item.worker)


@pytest.mark.parametrize('schedule', range(20))
def test_same_slot_timeout_schedule_preserves_single_quarantine(contract_env, monkeypatch, schedule):
    from tests.test_council_trace_independent_regressions import test_same_slot_concurrent_timeouts_leave_at_most_one_abandoned_worker
    test_same_slot_concurrent_timeouts_leave_at_most_one_abandoned_worker(monkeypatch)
def test_same_instance_concurrent_admission_is_atomic(contract_env, monkeypatch):
    """SUB_REQ_038: refuse overlap or isolate it; never mix run identities."""
    from app.council_models import CouncilInput, CouncilResult
    c = council()
    barrier = threading.Barrier(2)
    release = threading.Event()
    entered = []
    results, errors, callers = [], [], []
    profile = c.operating_profile()
    def synchronized_profile():
        try:
            barrier.wait(.15)
        except threading.BrokenBarrierError:
            # An atomic refusal before profile calculation is equally valid.
            pass
        return profile
    def body(value):
        entered.append((value.project_id, c._run_id))
        release.wait(2)
        return CouncilResult(id=c._run_id, project_id=value.project_id)
    monkeypatch.setattr(c, 'operating_profile', synchronized_profile)
    monkeypatch.setattr(c, '_evaluate_admitted', body)
    def call(project):
        try:
            results.append(c.evaluate(CouncilInput(project_id=project)))
        except Exception as exc:
            errors.append(exc)
    try:
        callers = [threading.Thread(target=call, args=(project,)) for project in ('one', 'two')]
        for thread in callers:
            thread.start()
        until = time.monotonic() + 1
        while len(entered) < 2 and time.monotonic() < until:
            time.sleep(.005)
        release.set()
        for thread in callers:
            thread.join(3)
        assert all(not thread.is_alive() for thread in callers)
        assert not errors or all(isinstance(exc, m.CouncilResourceError) for exc in errors), errors
        assert len({result.id for result in results}) == len(results), (
            'concurrent public operations mixed their immutable identities', entered, results)
    finally:
        release.set()
        for thread in callers:
            thread.join(3)
        if c._body_thread:
            c._body_thread.join(3)
