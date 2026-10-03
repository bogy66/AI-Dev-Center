"""Independent FIX014 boundary regressions. Synthetic providers/processes only.

Failures are intentionally ordinary assertions, never expected failures.
All paused workers are released and joined even when a regression fails.
"""
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.test_council_trace_independent_regressions import council, task
from app import engineering_council as m


@pytest.mark.parametrize("pause_at", ["delivery", "callback"])
def test_finalization_remains_bounded_after_terminal_activity(monkeypatch, pause_at):
    c=council(); t=task(c, 'terminal-delay')
    reached=threading.Event(); release=threading.Event(); outcomes=[]
    original=c._activity
    def activity(t,state,**kw):
        original(t,state,**kw)
        if state=='completed':
            reached.set(); release.wait(3)
    if pause_at == 'delivery':
        monkeypatch.setattr(c, '_activity', activity)
    else:
        def callback(**event):
            if event['runtime_state'] == 'completed':
                reached.set(); release.wait(3)
        c.set_activity_callback(callback)
    monkeypatch.setattr(m,'create_council_provider',lambda *a:SimpleNamespace(complete=lambda p:'{}'))
    monkeypatch.setattr(m,'_outer_deadline',lambda cfg:time.monotonic()+0.05)
    coordinator=threading.Thread(target=lambda:outcomes.extend(c._execute_parallel([t],'phase1')))
    try:
        coordinator.start(); assert reached.wait(1)
        coordinator.join(0.3)
        assert not coordinator.is_alive(), 'terminal activity disables the outer deadline while result delivery is stalled'
    finally:
        release.set(); coordinator.join(2)
        if t.worker:t.worker.join(2)
        assert not coordinator.is_alive()
        assert m.council_worker_stats()['live']==0


def test_provider_cannot_start_after_gate_check_races_finalization(monkeypatch):
    c=council(); t=task(c,'gate-race'); release=threading.Event(); checked=threading.Event(); calls=[]
    original=c._begin_provider_call
    def gate(t):
        allowed=original(t); checked.set(); release.wait(3); return allowed
    monkeypatch.setattr(c,'_begin_provider_call',gate)
    monkeypatch.setattr(m,'create_council_provider',lambda *a:SimpleNamespace(complete=lambda p:calls.append(p) or '{}'))
    monkeypatch.setattr(m,'_outer_deadline',lambda cfg:time.monotonic()+0.1)
    try:
        result=c._execute_parallel([t],'phase1')
        assert checked.is_set() and t.activity_closed.is_set() and not result[0].success
        release.set(); t.worker.join(1)
        assert calls==[], 'provider invoked after finalization between gate return and actual complete()'
    finally:
        release.set()
        if t.worker:t.worker.join(2)
        assert m.council_worker_stats()['live']==0


def test_reviewer_obeys_bounded_diagnostic_evidence_contract():
    from app.testing_stage import DiagnosisReviewer, TestingReviewRequest
    from app.project_test_runner import TestResult
    from app.diagnostic_evidence import _MAX_TOTAL_CHARS
    executor=Mock(); executor.run.return_value='{"decision":"rework_required","summary":"synthetic"}'
    result=TestResult(False,1,'a'*100000,'b'*100000,('synthetic',))
    DiagnosisReviewer(executor).review(TestingReviewRequest(None,result))
    assert len(executor.run.call_args.args[1])<=_MAX_TOTAL_CHARS


def test_branch_workspaces_do_not_consume_sibling_configuration(tmp_path):
    from app import verification as v
    roots={}; states={}
    class Runner(v.VerificationRunner):
        runner_type = "fake"
        def can_run(self,step):return True
        def execute(self,step,root):
            roots[step.step_id]=root
            state=root/'configuration'
            if step.step_id=='seed': (root/'seed').write_text('common')
            if step.step_id in ('left','right'): state.write_text(step.step_id)
            if step.step_id.endswith('_build'):states[step.step_id]=state.read_text()
            return v.VerificationStepResult(step.step_id,'root','pass','build','fake',True)
    def step(name,deps=()):
        return v.VerificationStep(name,'root','.','build','fake','fake','controlled_execution',depends_on=deps)
    steps=(step('seed'),step('left',('seed',)),step('right',('seed',)),step('left_build',('left',)),step('right_build',('right',)))
    result=v.ControlledRunnerRegistry([Runner()]).execute_plan(v.VerificationPlan('run',str(tmp_path),'fake',1,steps))
    assert result.passed
    assert list(tmp_path.iterdir())==[]
    assert all(not root.exists() for root in roots.values())
    assert states=={'left_build':'left','right_build':'right'}, 'sibling branch overwrites the configuration consumed by left_build'


def test_branched_productive_cmake_runners_keep_separate_caches(tmp_path, monkeypatch):
    """Two valid CMake areas may depend on common generated input.

    Model CMake's source/cache identity check at the subprocess boundary;
    real plan execution/registry/isolation/CMakeRunner code remains in use.
    """
    from pathlib import Path
    from app import verification as v

    for name in ('left', 'right'):
        (tmp_path / name).mkdir()
        (tmp_path / name / 'CMakeLists.txt').write_text('# synthetic source')

    class Seed(v.VerificationRunner):
        runner_type = 'seed'
        def can_run(self, step):
            return step.runner_type == self.runner_type
        def execute(self, step, root):
            (root / 'generated-input').write_text('common')
            return v.VerificationStepResult(step.step_id, '.', 'pass', 'generate', 'seed', True)

    def execute(args, cwd, budget, **kwargs):
        if '-B' in args:
            directory = Path(args[args.index('-B') + 1])
            source = args[args.index('-S') + 1]
            cache = directory / 'CMakeCache.txt'
            if cache.exists() and cache.read_text() != source:
                return SimpleNamespace(returncode=1, stdout='', stderr='CMake cache belongs to another source directory', timed_out=False)
            assert (Path(cwd).parent / 'generated-input').read_text() == 'common'
            cache.write_text(source)
        else:
            directory = Path(args[args.index('--build') + 1])
            assert (directory / 'CMakeCache.txt').read_text() == str(cwd)
        return SimpleNamespace(returncode=0, stdout='', stderr='', timed_out=False)

    monkeypatch.setattr(v.shutil, 'which', lambda name: '/synthetic/' + name)
    monkeypatch.setattr(v, '_safe_exec', execute)
    seed = v.VerificationStep('seed', '.', '.', 'generate', 'synthetic', 'seed', 'controlled_execution')
    def step(name, area, kind, deps):
        return v.VerificationStep(name, area, area, kind, 'cmake', 'cmake', 'controlled_execution', depends_on=deps)
    steps = (seed, step('left-configure', 'left', 'configure', ('seed',)),
             step('right-configure', 'right', 'configure', ('seed',)),
             step('left-build', 'left', 'build', ('left-configure',)),
             step('right-build', 'right', 'build', ('right-configure',)))
    result = v.ControlledRunnerRegistry([Seed(), v.CMakeRunner()]).execute_plan(
        v.VerificationPlan('branched', str(tmp_path), 'cmake', 1, steps))
    assert not (tmp_path / '.ai-build').exists()
    assert not (tmp_path / 'generated-input').exists()
    assert result.passed, [(s.step_id, s.status, s.stderr, s.diagnostics) for s in result.steps]


def test_reviewer_redacts_split_credential_argv():
    from app.testing_stage import DiagnosisReviewer, TestingReviewRequest
    from app.project_test_runner import TestResult
    secret = 'independent-cli-credential'
    result = TestResult(False, 1, '', '', ('synthetic', '--password', secret))
    executor = Mock()
    executor.run.return_value = '{"decision":"rework_required","summary":"synthetic"}'
    DiagnosisReviewer(executor).review(TestingReviewRequest(None, result))
    assert secret not in executor.run.call_args.args[1]


def test_rework_redacts_split_credential_argv(tmp_path):
    from app.controlled_rework_stage import ReworkDevelopmentRequest
    from app.development_stage import DevelopmentRequest
    from app.testing_stage import ReworkRequest
    from app.project_test_runner import TestResult
    secret = 'independent-cli-credential'
    result = TestResult(False, 1, '', '', ('synthetic', '--password', secret))
    request = ReworkDevelopmentRequest(
        DevelopmentRequest('project', tmp_path, 'fix feature'), None, result, None,
        ReworkRequest('tests require rework', 'safe diagnosis', None, result))
    assert secret not in request.task
