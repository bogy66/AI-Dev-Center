"""Independent FIX019 probes; synthetic providers, disposable trace/workspaces.

Lifecycle/start/slot cases belong to TEST_003; trace delivery has no suitable explicit lifecycle obligation.
Delivery budget/queue and repeat-run semantics have no explicit normative
obligation. Divergent workspace joins likewise need a semantics decision:
this probe records current fail-closed behavior, not a merge requirement.
Failing safety assertions remain ordinary failures, never xfailed.
"""
import asyncio
import inspect
import json
import shutil
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from app import engineering_council as m
from app.diagnostic_trace import DiagnosticTrace, DiagnosticTraceStore
from tests.test_council_trace_independent_regressions import council, task


def drain(lane):
    # settle deliberately stops immediately for an already-stalled receiver.
    # After releasing our own barrier, join its actual delivery thread.
    with lane._cond:
        threads = (lane._thread, lane._exiting)
    for thread in threads:
        if thread is not None:
            thread.join(3)
            assert not thread.is_alive()
    assert lane.settle(time.monotonic() + 3)


def settle(items):
    for item in items:
        if item.worker:
            item.worker.join(3)
            assert not item.worker.is_alive()
        for lane in (item.progress_lane, item.terminal_lane):
            drain(lane)
    assert m.council_worker_stats()['live'] == 0


def test_late_progress_cannot_regress_persisted_terminal_state(tmp_path, monkeypatch):
    """028: serial subscription cannot overtake its blocked thinking receiver.

    Callback-independent public diagnosis is separately required by TEST_037;
    terminal current state, rather than the final historical row, is binding.
    """
    c = council()
    item = task(c, 'late-persisted-progress')
    reached, release = threading.Event(), threading.Event()
    trace = DiagnosticTrace(DiagnosticTraceStore(tmp_path / 'events.jsonl'))

    def receiver(**event):
        state = event['runtime_state']
        if state == 'thinking':
            reached.set()
            release.wait()
        kind = state if state in ('completed', 'failed') else 'started'
        trace.record('synthetic', 'engineering_council', kind, kind, state, details=event)

    c.set_activity_callback(receiver)
    monkeypatch.setattr(m, 'create_council_provider', lambda *a: SimpleNamespace(complete=lambda p: '{}'))
    try:
        result = c._execute_parallel([item], 'phase1')
        assert reached.is_set() and result[0].success
        assert item.terminal_state == ('completed', None)
        assert c._call_records[-1].success
        assert not any(e.details['runtime_state'] == 'completed' for e in trace.store.read('synthetic'))
        assert c.notification_state()['activity']['unconfirmed'] >= 1
    finally:
        release.set()
        settle([item])
    # Public current state has its own invocation-aware terminal guard.
    states = [e.details['runtime_state'] for e in trace.store.read('synthetic')]
    from app import web_api
    session = web_api.Session('synthetic', str(tmp_path), 'probe', 'synthetic',
        web_api.TraceLevel.INFO, SimpleNamespace(events=[]))
    session.workflow_status = 'completed'
    session.project_setup_service = SimpleNamespace(get_diagnostic_trace=trace.get_trace)
    monkeypatch.setitem(web_api.sessions, 'fix019-late-activity', session)
    response = asyncio.run(web_api.get_state('fix019-late-activity'))
    assert response['workflow_status'] == 'completed'
    assert response['current_activity']['runtime_state'] == 'completed', (states, response['current_activity'])
    assert 'completed' in states, states
    # SUB_REQ_035 permits marked late historical facts; current state is guarded.


def test_slot_admission_survives_thread_bootstrap_observation(monkeypatch):
    """A real admitted thread has ident before Thread.start marks it alive.

    Pause only Python bootstrap, then perform the public stats observation
    that is allowed to prune. This converts the intermittent race into a
    reproducible schedule without changing admission/acquisition logic.
    """
    c = council()
    item = task(c, 'bootstrap-slot')
    reached, release = threading.Event(), threading.Event()
    outcomes = []
    real_thread = threading.Thread
    code = real_thread._bootstrap_inner.__code__
    lines, first = inspect.getsourcelines(real_thread._bootstrap_inner)
    pause_line = first + next(i for i, line in enumerate(lines) if 'self._started.set()' in line)

    def trace(frame, event, arg):
        if frame.f_code is code and event == 'line' and frame.f_lineno == pause_line:
            reached.set()
            release.wait()
        return trace

    class PausedBootstrap(real_thread):
        def _bootstrap(self):
            sys.settrace(trace)
            try:
                super()._bootstrap()
            finally:
                sys.settrace(None)

    starter = real_thread(target=lambda: outcomes.extend(c._execute_parallel([item], 'phase1')))
    monkeypatch.setattr(m.threading, 'Thread', PausedBootstrap)
    monkeypatch.setattr(m, 'create_council_provider', lambda *a: SimpleNamespace(complete=lambda p: '{}'))
    try:
        starter.start()
        assert reached.wait(2)
        observed = m.council_worker_stats()
        release.set()
        starter.join(3)
        assert not starter.is_alive()
        assert observed['live'] == 1, ('admitted worker pruned during bootstrap', outcomes)
        assert outcomes[0].success, outcomes[0].error
    finally:
        release.set()
        starter.join(3)
        settle([item])


def test_notifier_budget_drops_terminal_but_keeps_internal_outcome(monkeypatch):
    """Exhaustion is lossy, including terminal notifications; no delivery retry."""
    budget = m._NotifierBudget(2)
    monkeypatch.setattr(m, '_NOTIFIERS', budget)
    reached = [threading.Event(), threading.Event()]
    release = threading.Event()
    lanes = [m._DeliveryLane('budget-' + str(i)) for i in range(2)]
    delivered = []
    c = council()
    item = task(c, 'exhausted-delivery')
    c.set_activity_callback(lambda **e: delivered.append(e))
    monkeypatch.setattr(m, 'create_council_provider', lambda *a: SimpleNamespace(complete=lambda p: '{}'))
    try:
        for i, lane in enumerate(lanes):
            assert lane.post(lambda i=i: (reached[i].set(), release.wait()))
        assert all(e.wait(1) for e in reached)
        result = c._execute_parallel([item], 'phase1')
        assert result[0].success and item.terminal_state == ('completed', None)
        assert c._call_records[-1].success and delivered == []
        stats = budget.stats()
        assert stats['live'] == stats['capacity'] == 2
        assert stats['dropped'] >= 4
    finally:
        release.set()
        for lane in lanes:
            drain(lane)
        settle([item])
    assert budget.stats()['live'] == 0
    assert delivered == []  # Capacity returning does not replay the loss.


def test_delivery_thread_and_pending_queue_are_bounded(monkeypatch):
    budget = m._NotifierBudget(1)
    monkeypatch.setattr(m, '_NOTIFIERS', budget)
    lane = m._DeliveryLane('queue-probe')
    reached, release = threading.Event(), threading.Event()
    try:
        assert lane.post(lambda: (reached.set(), release.wait()))
        assert reached.wait(1)
        admitted = sum(lane.post(lambda: None) for _ in range(1000))
        assert admitted == lane.pending_limit
        assert budget.stats()['live'] == budget.stats()['capacity'] == 1
        assert len(lane._queue) == lane.pending_limit
        assert lane.delivery_counts()['skipped'] == 1000 - admitted
        assert lane.close() == admitted
        # Close-discard accounting is independently asserted by TEST_038;
        # its current product failure must not be encoded as desired behavior.
    finally:
        release.set()
        drain(lane)
    assert budget.stats()['live'] == 0


def test_repeated_public_evaluate_uses_fresh_lanes_and_persists_calls(tmp_path, monkeypatch):
    """A stalled old result receiver may overlap a new run; snapshots survive."""
    from app.council_models import CouncilInput
    c = council()
    c._trace_dir = tmp_path
    reached, release = threading.Event(), threading.Event()
    old, new = [], []
    lanes = []

    def stalled(**event):
        reached.set()
        release.wait()
        old.append(event)

    c.set_result_callback(stalled)
    original_result = c._result
    def record_lane(**event):
        if c._result_lane not in lanes:
            lanes.append(c._result_lane)
        original_result(**event)

    monkeypatch.setattr(c, '_result', record_lane)
    monkeypatch.setattr(m, 'create_council_provider', lambda *a: SimpleNamespace(complete=lambda p: '{"variants": []}'))
    try:
        started = time.monotonic()
        first = c.evaluate(CouncilInput(project_id='old'))
        assert reached.is_set() and old == []
        assert time.monotonic() - started < 1
        c.set_result_callback(lambda **e: new.append(e))
        started = time.monotonic()
        second = c.evaluate(CouncilInput(project_id='new'))
        assert time.monotonic() - started < 1
        assert first.id != second.id and len(lanes) == 2
        assert lanes[0] is not lanes[1] and new
        assert first.total_llm_calls == second.total_llm_calls == 3
        for project, result in (('old', first), ('new', second)):
            stored = json.loads((tmp_path / project / (result.id + '.json')).read_text())
            assert stored['council_result_id'] == result.id
            assert len(stored['agent_call_records']) == 3
        assert c._result_lane is None
    finally:
        release.set()
        for lane in lanes:
            drain(lane)
    assert old and m.council_notifier_stats()['live'] == 0


def test_divergent_join_is_refused_even_for_disjoint_outputs(tmp_path):
    from app import verification as v
    seen, roots = [], []

    class Runner(v.VerificationRunner):
        runner_type = 'synthetic'
        def can_run(self, step):
            return True
        def execute(self, step, root):
            seen.append(step.step_id)
            roots.append(root)
            (root / step.step_id).write_text(step.step_id)
            return v.VerificationStepResult(step.step_id, '.', 'pass', 'build', self.runner_type, True)

    def step(name, deps=()):
        return v.VerificationStep(name, '.', '.', 'build', 'synthetic', 'synthetic', 'controlled_execution', depends_on=deps)

    plan = v.VerificationPlan('join', str(tmp_path), 'synthetic', 1,
        (step('seed'), step('left', ('seed',)), step('right', ('seed',)), step('join', ('left', 'right'))))
    result = v.ControlledRunnerRegistry([Runner()]).execute_plan(plan)
    assert not result.passed
    assert seen == ['seed', 'left', 'right']
    assert 'diverged workspace branches' in str(result.steps[-1].diagnostics)
    assert list(tmp_path.iterdir()) == []
    assert all(not root.exists() for root in roots)


def test_native_branched_cmake_build_and_ctest_preserve_shadow_state(tmp_path):
    """Native prerequisite probe; no _safe_exec/process/tool substitutions.

    CTest planning is currently deferred. This exercises the existing runner
    route with an explicit verification plan, not automatic CTest admission.
    Missing tools remain an explicit evidence gap, never surrogate success.
    """
    from app import verification as v
    missing = [name for name in ('cmake', 'ctest', 'cc', 'make') if not shutil.which(name)]
    if missing:
        pytest.skip('native prerequisite missing: ' + ', '.join(missing))
    for area in ('left', 'right'):
        source = tmp_path / area
        source.mkdir()
        (source / 'CMakeLists.txt').write_text(
            'cmake_minimum_required(VERSION 3.10)\nproject(probe C)\n'
            'add_executable(probe main.c)\n'
            'target_include_directories(probe PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/..")\n'
            'enable_testing()\nadd_test(NAME smoke COMMAND probe)\n')
        (source / 'main.c').write_text('#include "generated.h"\nint main(void) { return GENERATED == 19 ? 0 : 1; }\n')
    before = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}

    class Seed(v.VerificationRunner):
        runner_type = 'seed'
        def can_run(self, step):
            return step.runner_type == self.runner_type
        def execute(self, step, root):
            (root / 'generated.h').write_text('#define GENERATED 19\n')
            return v.VerificationStepResult(step.step_id, '.', 'pass', 'generate', 'seed', True)

    steps = [v.VerificationStep('seed', '.', '.', 'generate', 'synthetic', 'seed', 'controlled_execution')]
    for area in ('left', 'right'):
        previous = 'seed'
        for kind in ('configure', 'build', 'test'):
            name = area + '-' + kind
            steps.append(v.VerificationStep(name, area, area, kind, 'ctest' if kind == 'test' else 'cmake',
                'cmake', 'controlled_execution', depends_on=(previous,), execution_budget_seconds=30))
            previous = name
    result = v.ControlledRunnerRegistry([Seed(), v.CMakeRunner()]).execute_plan(
        v.VerificationPlan('native-branches', str(tmp_path), 'cmake', 1, tuple(steps)))
    assert result.passed, [(s.step_id, s.status, s.stderr, s.diagnostics) for s in result.steps]
    assert all(s.return_code == 0 for s in result.steps if s.runner_type == 'cmake')
    after = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert before == after
