"""028 contract fixtures: synthetic contributors, private resources and stores.

Short test budgets are experimental schedules, not approved operating values.
No live provider, TEST_033/035, dispatcher or RLRC execution.
"""
from dataclasses import replace
import time
from types import SimpleNamespace

import pytest
from app import engineering_council as m
from app.council_lifecycle import CouncilDiagnosisRegistry, PersistenceWriter
from tests.test_council_trace_independent_regressions import council, task


@pytest.fixture
def contract_env(monkeypatch):
    profile = replace(m.DEFAULT_PROFILE, preparation_seconds=.02,
                      finalization_seconds=.03, volatile_retention_seconds=60)
    registry = CouncilDiagnosisRegistry(4 * 1024 * 1024, 65536, 60)
    pool = m._CouncilWorkerPool(16)
    writer = PersistenceWriter(8)
    monkeypatch.setattr(m, 'DEFAULT_PROFILE', profile)
    monkeypatch.setattr(m, '_DIAGNOSIS', registry)
    monkeypatch.setattr(m, '_WORKER_POOL', pool)
    monkeypatch.setattr(m, '_PERSISTENCE', writer)
    monkeypatch.setattr(m, '_NOTIFIERS', m._NotifierBudget(8))
    run_slots = m._RunSlots(16)
    monkeypatch.setattr(m, '_RUN_SLOTS', run_slots)
    instances = []
    original_init = m.EngineeringCouncil.__init__
    def tracked_init(instance, *args, **kwargs):
        original_init(instance, *args, **kwargs)
        instances.append(instance)
    monkeypatch.setattr(m.EngineeringCouncil, '__init__', tracked_init)
    monkeypatch.setattr(m, '_call_budget', lambda cfg: .12)
    monkeypatch.setattr(m, '_outer_deadline', lambda cfg: time.monotonic() + .12)
    monkeypatch.setattr(m, 'create_council_provider',
                        lambda *args: SimpleNamespace(complete=lambda p: '{"variants": []}'))
    yield registry
    # FIX029 preparation may outlive public completion. Keep its private
    # resources installed until confirmed exit, rather than leak into a later test.
    for instance in instances:
        thread = instance._body_thread
        if thread is not None and thread.ident is not None:
            join(thread)
    assert run_slots.stats()['busy'] == 0, 'contract probe left a Council run'
    assert pool.stats()['live'] == 0, 'contract probe left a provider worker'
    assert writer.stats()['busy'] == 0, 'contract probe left a persistence writer'
    assert m.council_notifier_stats()['live'] == 0, 'contract probe left a receiver'


def join(thread):
    if thread is not None:
        thread.join(3)
        assert not thread.is_alive()


def drain(lane):
    if lane is not None:
        with lane._cond:
            workers = (lane._thread, lane._exiting)
        for worker in workers:
            join(worker)
        assert lane.settle(time.monotonic() + 1)
