from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from app.testing_stage import DiagnosisReviewer, ReviewDecision, ReviewResult, TestingStage


def _test(passed=True, timed_out=False):
    return SimpleNamespace(passed=passed, timed_out=timed_out, return_code=0, stdout="out", stderr="err")


@pytest.mark.parametrize("passed,timed_out,decision,status", [(True, False, ReviewDecision.ACCEPTED, "accepted"), (True, False, ReviewDecision.REWORK_REQUIRED, "rework_required"), (False, False, ReviewDecision.ACCEPTED, "rework_required"), (False, False, ReviewDecision.REWORK_REQUIRED, "rework_required"), (True, True, ReviewDecision.ACCEPTED, "rework_required")])
def test_fail_safe_testing_policy(passed, timed_out, decision, status):
    reviewer = Mock()
    reviewer.review.return_value = ReviewResult(decision, "diagnosis")
    test_result = _test(passed, timed_out)
    result = TestingStage(reviewer).run("development", test_result)
    reviewer.review.assert_called_once()
    assert result.status == status
    assert result.test_result is test_result
    assert (result.rework_request is None) is (status == "accepted")


def test_reviewer_failure_is_review_failed_without_retry():
    reviewer = Mock()
    reviewer.review.side_effect = RuntimeError("provider error")
    result = TestingStage(reviewer).run("development", _test())
    assert result.status == "review_failed"
    assert result.rework_request is None
    reviewer.review.assert_called_once()


@pytest.mark.parametrize("output", ["", "invalid"])
def test_diagnosis_reviewer_rejects_invalid_output(output):
    executor = Mock()
    executor.run.return_value = output
    with pytest.raises(ValueError):
        DiagnosisReviewer(executor).review(SimpleNamespace(test_result=_test()))
    executor.run.assert_called_once()
