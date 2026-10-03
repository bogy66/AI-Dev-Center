"""TEST_039 / SUB_REQ_039-040: elapsed budgets and isolated process exit."""
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from tests.test_productive_web_e2e import disposable_productive_web

from app import engineering_council as m
from app.council_models import CouncilInput
from tests.council_contract_support import contract_env, council, task, join


def test_profile_declared_and_tolerance_never_added():
    c = council()
    profile = c.operating_profile()
    assert profile['provisional']
    assert profile['public_total_seconds'] == 865
    assert profile['phase_seconds']['phase3'] == 3 * m._call_budget(c._config.chairman)
    assert m._TIMEOUT_GRACE_SECONDS == 15
    assert profile['diagnosis_envelope_bytes'] == 65536
    assert profile['public_total_seconds'] == profile['preparation_seconds'] + sum(profile['phase_seconds'].values()) + profile['finalization_seconds']


def test_phase_repair_never_resets_deadline(contract_env):
    c = council()
    entered = time.monotonic()
    c._run = m._CouncilRun('phase', entered, entered + .2, c.operating_profile())
    first = c._phase_limit('phase3')
    time.sleep(.01)
    assert c._phase_limit('phase3') == first
    assert first[0] <= c._run.public_deadline - c._run.profile['finalization_seconds']


def test_preparation_delay_is_inside_public_deadline(contract_env, monkeypatch):
    c = council()
    original = m.build_phase1_prompt
    calls = []
    monkeypatch.setattr(m, 'create_council_provider', lambda *a: calls.append(a))
    def delayed(*args):
        if not getattr(delayed, 'used', False):
            delayed.used = True
            time.sleep(c.operating_profile()['public_total_seconds'] + .15)
        return original(*args)
    monkeypatch.setattr(m, 'build_phase1_prompt', delayed)
    started = time.monotonic()
    result = c.evaluate(CouncilInput(project_id='prepare'))
    assert calls == [] and not result.council_complete
    elapsed = time.monotonic() - started
    assert elapsed <= c.operating_profile()['public_total_seconds'] + .08, ('unbounded synchronous preparation', elapsed)


def test_late_worker_claim_rejected_even_when_coordinator_runs_late(contract_env, monkeypatch):
    c, reached, release = council(), threading.Event(), threading.Event()
    item = task(c)
    def complete(prompt):
        reached.set()
        release.wait()
        return '{}'
    monkeypatch.setattr(m, 'create_council_provider', lambda *a: SimpleNamespace(complete=complete))
    original_start = c._start_agent_call
    def delayed_start(t):
        value = original_start(t)
        assert reached.wait(1)
        time.sleep(.16)
        release.set()
        join(t.worker)
        return value
    monkeypatch.setattr(c, '_start_agent_call', delayed_start)
    try:
        result = c._execute_parallel([item], 'phase1')
        assert not result[0].success and item.terminal_state == ('failed', 'timeout')
    finally:
        release.set()
        join(item.worker)


def test_owner_process_exits_with_permanently_blocked_worker_and_receiver(tmp_path):
    """Native process with synthetic permanent blockage, 3 s test exit bound.

    Experimental measurement only; no approved shutdown value is invented.
    Restart process imports/queries but must not resubmit uncertain work.
    """
    code = '''
import json, threading, time
from types import SimpleNamespace
from app import engineering_council as m
from tests.test_council_trace_independent_regressions import council, task
c = council()
release = threading.Event()
m._outer_deadline = lambda cfg: time.monotonic() + .08
m.create_council_provider = lambda *a: SimpleNamespace(complete=lambda p: release.wait())
c.set_activity_callback(lambda **event: release.wait())
c._execute_parallel([task(c)], 'phase1')
print(json.dumps(m.council_resource_stats()), flush=True)
'''
    started = time.monotonic()
    completed = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[1],
                               capture_output=True, text=True, timeout=3)
    assert completed.returncode == 0, completed.stderr
    stats = json.loads(completed.stdout.splitlines()[-1])
    assert stats['workers']['live'] == stats['workers']['abandoned'] == 1
    assert stats['notifiers']['live'] == 1
    assert time.monotonic() - started < 3
    restart = subprocess.run([sys.executable, '-c', 'from app.engineering_council import council_resource_stats; import json; print(json.dumps(council_resource_stats()))'],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=3)
    assert restart.returncode == 0, restart.stderr
    assert json.loads(restart.stdout)['workers']['live'] == 0


def test_three_chairman_calls_match_existing_structural_and_content_flow(
    contract_env, disposable_productive_web,
):
    from tests.test_productive_web_e2e import RecoveryReworkProvider
    _, project, compose = disposable_productive_web
    providers = {role: RecoveryReworkProvider(role, project / 'absent-esphome', True)
                 for role in ('discovery', 'environment_architect', 'toolchain_integrator', 'risk_assessor', 'chairman')}
    components = compose(providers=providers)
    started = time.monotonic()
    result = components.service.plan_project_setup('chairman-profile', project, 'chairman-flow',
        entry_data={'task_description': 'Configure this disposable project'})
    c = components.development_workflow._council
    assert len(providers['chairman'].responses) == c._chairman_attempts == 3
    assert result.council_result.council_complete
    assert result.engineering_selection.validations[0].admissible
    assert len([record for record in c._call_records if record.phase == 'phase3']) == 3
    elapsed = time.monotonic() - started
    print('experimental_three_chairman_flow_seconds', round(elapsed, 6))
    assert c._run.phase_limits['phase3'] <= c._run.public_deadline - c._run.profile['finalization_seconds']


@pytest.mark.parametrize('schedule', range(20))
def test_bootstrap_registration_remains_counted_under_forced_schedule(contract_env, monkeypatch, schedule):
    from tests.test_fix019_architecture_regressions import test_slot_admission_survives_thread_bootstrap_observation
    test_slot_admission_survives_thread_bootstrap_observation(monkeypatch)
