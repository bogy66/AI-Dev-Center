import json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from app.testing_stage import (
    DiagnosisReviewer, ReviewDecision, ReviewResult, TestingReviewRequest,
    TestingStage,
)


def _test(passed=True, timed_out=False):
    return SimpleNamespace(passed=passed, timed_out=timed_out,
                           return_code=0, stdout="out", stderr="err")


def _review_response(decision="accepted", summary="diagnostic summary"):
    return json.dumps({"decision": decision, "summary": summary})


@pytest.mark.parametrize("passed,timed_out,decision,status", [
    (True, False, ReviewDecision.ACCEPTED, "accepted"),
    (True, False, ReviewDecision.REWORK_REQUIRED, "rework_required"),
    (False, False, ReviewDecision.ACCEPTED, "rework_required"),
    (False, False, ReviewDecision.REWORK_REQUIRED, "rework_required"),
    (True, True, ReviewDecision.ACCEPTED, "rework_required"),
])
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


# ------------------------------------------------------------------
# Structured JSON review contract tests
# ------------------------------------------------------------------


def test_valid_accepted_json():
    executor = Mock()
    executor.run.return_value = _review_response("accepted", "Tests passed, output is clean.")
    result = DiagnosisReviewer(executor).review(
        TestingReviewRequest("dev", _test(passed=True)),
    )
    assert result.decision == ReviewDecision.ACCEPTED
    assert result.summary == "Tests passed, output is clean."


def test_valid_rework_required_json():
    executor = Mock()
    executor.run.return_value = _review_response("rework_required", "Two tests failed, std err shows exception.")
    result = DiagnosisReviewer(executor).review(
        TestingReviewRequest("dev", _test(passed=False)),
    )
    assert result.decision == ReviewDecision.REWORK_REQUIRED
    assert result.summary == "Two tests failed, std err shows exception."


def test_summary_preserved():
    executor = Mock()
    executor.run.return_value = _review_response("accepted", "All 5 tests passed cleanly.")
    result = DiagnosisReviewer(executor).review(
        TestingReviewRequest("dev", _test()),
    )
    assert result.summary == "All 5 tests passed cleanly."


def test_invalid_json_rejected():
    executor = Mock()
    executor.run.return_value = "not json"
    with pytest.raises(ValueError, match="Invalid reviewer output"):
        DiagnosisReviewer(executor).review(
            TestingReviewRequest("dev", _test()),
        )


def test_prose_rejected():
    executor = Mock()
    executor.run.return_value = "The tests look good, decision: ACCEPTED"
    with pytest.raises(ValueError, match="Invalid reviewer output"):
        DiagnosisReviewer(executor).review(
            TestingReviewRequest("dev", _test()),
        )


def test_legacy_exact_string_rejected():
    executor = Mock()
    executor.run.return_value = "ACCEPTED"
    with pytest.raises(ValueError, match="Invalid reviewer output"):
        DiagnosisReviewer(executor).review(
            TestingReviewRequest("dev", _test()),
        )


def test_legacy_rework_string_rejected():
    executor = Mock()
    executor.run.return_value = "REWORK_REQUIRED"
    with pytest.raises(ValueError, match="Invalid reviewer output"):
        DiagnosisReviewer(executor).review(
            TestingReviewRequest("dev", _test()),
        )


def test_unsupported_decision_rejected():
    executor = Mock()
    executor.run.return_value = json.dumps({
        "decision": "unknown_status", "summary": "some text",
    })
    with pytest.raises(ValueError, match="Invalid reviewer output"):
        DiagnosisReviewer(executor).review(
            TestingReviewRequest("dev", _test()),
        )


def test_missing_decision_rejected():
    executor = Mock()
    executor.run.return_value = json.dumps({"summary": "no decision key"})
    with pytest.raises(ValueError, match="Invalid reviewer output"):
        DiagnosisReviewer(executor).review(
            TestingReviewRequest("dev", _test()),
        )


def test_missing_summary_rejected():
    executor = Mock()
    executor.run.return_value = json.dumps({"decision": "accepted"})
    with pytest.raises(ValueError, match="Invalid reviewer output"):
        DiagnosisReviewer(executor).review(
            TestingReviewRequest("dev", _test()),
        )


def test_empty_summary_rejected():
    executor = Mock()
    executor.run.return_value = json.dumps({
        "decision": "accepted", "summary": "",
    })
    with pytest.raises(ValueError, match="Invalid reviewer output"):
        DiagnosisReviewer(executor).review(
            TestingReviewRequest("dev", _test()),
        )


def test_whitespace_only_summary_rejected():
    executor = Mock()
    executor.run.return_value = json.dumps({
        "decision": "accepted", "summary": "   ",
    })
    with pytest.raises(ValueError, match="Invalid reviewer output"):
        DiagnosisReviewer(executor).review(
            TestingReviewRequest("dev", _test()),
        )


def test_non_dict_root_rejected():
    executor = Mock()
    executor.run.return_value = json.dumps(["decision", "accepted"])
    with pytest.raises(ValueError, match="Invalid reviewer output"):
        DiagnosisReviewer(executor).review(
            TestingReviewRequest("dev", _test()),
        )


def test_decision_not_string_rejected():
    executor = Mock()
    executor.run.return_value = json.dumps({
        "decision": 1, "summary": "text",
    })
    with pytest.raises(ValueError, match="Invalid reviewer output"):
        DiagnosisReviewer(executor).review(
            TestingReviewRequest("dev", _test()),
        )


def test_summary_with_leading_whitespace_trimmed():
    executor = Mock()
    executor.run.return_value = json.dumps({
        "decision": "accepted", "summary": "  all good  ",
    })
    result = DiagnosisReviewer(executor).review(
        TestingReviewRequest("dev", _test()),
    )
    assert result.summary == "all good"


def test_reviewer_prompt_has_no_legacy_exact_string_output():
    from app.agent_executor import ProviderAgentExecutor

    class RP:
        def __init__(self): self.prompt = None
        def complete(self, p, max_tokens=None): self.prompt = p; return _review_response()

    p = RP()
    ProviderAgentExecutor(p).run("reviewer", "test output here", "", "reviewer")
    assert "Return exactly ACCEPTED" not in p.prompt
    assert "ACCEPTED or REWORK_REQUIRED" not in p.prompt
    assert '"decision"' in p.prompt
    assert '"summary"' in p.prompt


def test_reviewer_contract_precedes_test_result():
    from app.agent_executor import ProviderAgentExecutor

    class RP:
        def __init__(self): self.prompt = None
        def complete(self, p, max_tokens=None): self.prompt = p; return _review_response()

    p = RP()
    ProviderAgentExecutor(p).run("reviewer", "test-failed: assert 1 == 2", "", "reviewer")
    contract_idx = p.prompt.index('"decision"')
    result_idx = p.prompt.index("test-failed")
    assert contract_idx < result_idx, (
        f"contract (idx {contract_idx}) must precede test result (idx {result_idx})"
    )


def test_failed_test_not_accepted_by_reviewer():
    executor = Mock()
    executor.run.return_value = _review_response("accepted", "looks fine")
    result = TestingStage(DiagnosisReviewer(executor)).run(
        "development", _test(passed=False),
    )
    assert result.status == "rework_required"


def test_timed_out_test_not_accepted_by_reviewer():
    executor = Mock()
    executor.run.return_value = _review_response("accepted", "passed eventually")
    result = TestingStage(DiagnosisReviewer(executor)).run(
        "development", _test(passed=True, timed_out=True),
    )
    assert result.status == "rework_required"


def test_invalid_reviewer_returns_review_failed():
    executor = Mock()
    executor.run.return_value = "prose is not accepted"
    result = TestingStage(DiagnosisReviewer(executor)).run(
        "development", _test(),
    )
    assert result.status == "review_failed"
    assert result.review_result is None
    assert result.rework_request is None