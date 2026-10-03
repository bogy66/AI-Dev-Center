"""Independent local surrogates; no hooks, compilers, installs or providers."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest


def test_git_metadata_is_not_an_allowed_generated_change_target(tmp_path):
    from app.developer_file_applier import DeveloperFileApplier
    target=tmp_path/'.git'/'config'
    target.parent.mkdir()
    target.write_text('inert baseline\n')
    result=DeveloperFileApplier(tmp_path).apply({'changes':[{'file':'.git/config','action':'update','content':'inert changed\n'}]})
    assert result['applied']==[], 'generated changes may write .git metadata'
    assert target.read_text()=='inert baseline\n'


def test_reviewer_input_excludes_secret_values():
    from app.testing_stage import DiagnosisReviewer,TestingReviewRequest
    from app.project_test_runner import TestResult
    executor=Mock()
    executor.run.return_value='{"decision":"rework_required","summary":"safe"}'
    evidence=TestResult(False,1,'AWS_ACCESS_KEY_ID=AKIA_REVIEW_SENTINEL','TOKEN=review-private',('synthetic',))
    DiagnosisReviewer(executor).review(TestingReviewRequest(None,evidence))
    prompt=executor.run.call_args.args[1]
    assert 'AKIA_REVIEW_SENTINEL' not in prompt and 'review-private' not in prompt


@pytest.mark.parametrize('statuses',[('pass','unsupported'),('fail','tool_unavailable')])
def test_mixed_verification_outcomes_keep_authoritative_failure(tmp_path,statuses):
    from app.verification import VerificationResult,VerificationStepResult
    from tests.test_development_testing_stage import _verification_stage,_request
    steps=tuple(VerificationStepResult(str(i),'root',status,'test','fake',status=='pass') for i,status in enumerate(statuses))
    result=VerificationResult('run',steps,'fail')
    stage,_,_=_verification_stage(result)
    outcome=stage.run(_request(tmp_path))
    assert outcome.verification_result is result
    if statuses[0]=='pass':
        assert outcome.status!='accepted', 'aggregate FAIL (unsupported step) became accepted'
    else:
        assert outcome.status!='tool_unavailable', 'independent deterministic FAIL routed solely as missing tool'


def test_cmake_build_receives_configure_state_in_protected_workspace(tmp_path,monkeypatch):
    from app import verification as v
    configure=v.VerificationStep('configure','root','.','configure','cmake','cmake','controlled_execution')
    build=v.VerificationStep('build','root','.','build','cmake','cmake','controlled_execution',depends_on=('configure',))
    monkeypatch.setattr(v.shutil,'which',lambda tool:'/synthetic/'+tool)
    seen=[]
    def execute(args,cwd,budget,**kw):
        builddir=Path(args[args.index('-B')+1] if '-B' in args else args[args.index('--build')+1])
        marker=builddir/'inert-configure-state'
        if '-B' in args:
            marker.write_text('configured')
            code=0
        else:
            code=0 if marker.exists() else 1
        seen.append((str(builddir),code))
        return SimpleNamespace(returncode=code,stdout='',stderr='',timed_out=False)
    monkeypatch.setattr(v,'_safe_exec',execute)
    plan=v.VerificationPlan('run',str(tmp_path),'cmake',1,(configure,build))
    result=v.ControlledRunnerRegistry([v.CMakeRunner()]).execute_plan(plan)
    assert not (tmp_path/'.ai-build').exists(), 'real target mutated'
    assert result.passed, f'configure state discarded between dependent steps: {seen}'


def test_repeated_distinct_runs_of_same_project_are_possible(tmp_path):
    from tests.test_canonical_execution_lifecycle import _service,_result
    calls=[]
    workflow=SimpleNamespace(execute_approved_and_run_development=lambda p,r:calls.append(r.run_id) or _result())
    service=_service(tmp_path,workflow)
    for run in ('first-run','second-run'):
        service.execute_approved_setup_and_development(SimpleNamespace(id='plan'), 'project',tmp_path/'project','task',run)
        assert service._workflow_manager.get_execution_state(run)['status']=='completed'
    assert calls==['first-run','second-run']


@pytest.mark.parametrize('alias', [False, True])
def test_git_metadata_rejected_through_direct_and_symlink_targets(tmp_path, alias):
    from app.developer_file_applier import DeveloperFileApplier
    metadata = tmp_path / '.git'
    metadata.mkdir()
    target = metadata / 'config'
    target.write_text('original')
    if alias:
        (tmp_path / 'alias').symlink_to(metadata, target_is_directory=True)
    name = 'alias/config' if alias else '.git/config'
    result = DeveloperFileApplier(tmp_path).apply({'changes': [
        {'file': name, 'action': 'update', 'content': 'changed'}]})
    assert result['applied'] == []
    assert result['skipped'] == [{'file': name, 'reason': 'unsafe_path'}]
    assert target.read_text() == 'original'


def test_mixed_failure_preserves_both_step_records_through_real_diagnosis(tmp_path):
    from app.verification import VerificationResult, VerificationStepResult
    from app.testing_stage import TestingStage, ReviewResult, ReviewDecision
    from app.diagnostic_evidence import format_test_result_evidence
    from tests.test_development_testing_stage import _verification_stage, _request
    failed = VerificationStepResult('unit', 'root', 'fail', 'test', 'fake', False,
                                    return_code=1, stderr='assertion mismatch')
    missing = VerificationStepResult('build', 'root', 'tool_unavailable', 'build', 'fake', False,
                                     unavailable_tool='syntheticcc', diagnostics='syntheticcc missing')
    evidence = VerificationResult('run', (failed, missing), 'fail')
    stage, _, _ = _verification_stage(evidence)
    reviewer = Mock()
    reviewer.review.return_value = ReviewResult(ReviewDecision.ACCEPTED, 'synthetic opinion')
    stage._testing_stage = TestingStage(reviewer)
    result = stage.run(_request(tmp_path))
    assert result.status == 'rework_required'
    assert result.verification_result is evidence
    assert [(s.step_id, s.status) for s in result.test_result.step_failures] == [
        ('unit', 'fail'), ('build', 'tool_unavailable')]
    assert result.testing_stage_result.rework_request.test_result is result.test_result
    rendered = format_test_result_evidence(result.test_result)
    assert 'assertion mismatch' in rendered and 'syntheticcc missing' in rendered


def test_mixed_failure_then_source_rework_preserves_missing_tool_recovery_plan(tmp_path, monkeypatch):
    from app import verification as v
    from app.controlled_rework_stage import ControlledReworkStage
    from app.testing_stage import TestingStage, ReviewResult, ReviewDecision
    from tests.test_development_testing_stage import _verification_stage, _request
    failed = v.VerificationStepResult('unit', 'root', 'fail', 'test', 'fake', False,
                                     return_code=1, diagnostics='assertion mismatch')
    missing = v.VerificationStepResult('build', 'root', 'tool_unavailable', 'build', 'fake', False,
                                      unavailable_tool='syntheticcc', diagnostics='syntheticcc missing')
    passed = v.VerificationStepResult('unit', 'root', 'pass', 'test', 'fake', True)
    initial = v.VerificationResult('run', (failed, missing), 'fail')
    after_rework = v.VerificationResult('run', (passed, missing), 'fail')
    steps = tuple(v.VerificationStep(name, 'root', '.', kind, 'fake', 'fake', 'controlled_execution')
                  for name, kind in (('unit', 'test'), ('build', 'build')))
    plan = v.VerificationPlan('run', str(tmp_path), 'fake', 1, steps)
    monkeypatch.setattr(v, 'build_verification_plan', lambda intelligence, run_id: plan)
    stage, _, registry = _verification_stage(initial)
    registry.execute_plan.side_effect = [initial, after_rework]
    reviewer = Mock()
    reviewer.review.return_value = ReviewResult(ReviewDecision.ACCEPTED, 'synthetic opinion')
    stage._testing_stage = TestingStage(reviewer)
    outcome = ControlledReworkStage(stage).run(_request(tmp_path))
    assert outcome.initial_result.status == 'rework_required'
    assert len(outcome.initial_result.test_result.step_failures) == 2
    assert outcome.rework_executed
    assert registry.execute_plan.call_count == 2
    assert outcome.final_result.status == 'tool_unavailable'
    assert outcome.final_result.verification_plan is plan
    assert outcome.final_result.verification_result is after_rework
