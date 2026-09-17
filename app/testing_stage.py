"""Neutral, fail-safe diagnosis after a real test result."""
import json
from dataclasses import dataclass
from enum import Enum


class ReviewDecision(str, Enum):
    ACCEPTED = "accepted"
    REWORK_REQUIRED = "rework_required"


@dataclass(frozen=True)
class TestingReviewRequest:
    development_result: object
    test_result: object


@dataclass(frozen=True)
class ReviewResult:
    decision: ReviewDecision
    summary: str


@dataclass(frozen=True)
class ReworkRequest:
    reason: str
    diagnostics: str
    development_result: object
    test_result: object


@dataclass(frozen=True)
class TestingStageResult:
    status: str
    test_result: object
    review_result: ReviewResult | None
    rework_request: ReworkRequest | None = None


class DiagnosisReviewer:
    def __init__(self, executor): self._executor = executor

    def review(self, request):
        response = self._executor.run(
            "reviewer", str(request.test_result), "", "reviewer",
        )
        try:
            parsed = json.loads(response)
        except json.JSONDecodeError:
            raise ValueError("Invalid reviewer output") from None
        if not isinstance(parsed, dict):
            raise ValueError("Invalid reviewer output")
        decision_raw = parsed.get("decision")
        if decision_raw not in {ReviewDecision.ACCEPTED.value,
                                 ReviewDecision.REWORK_REQUIRED.value}:
            raise ValueError("Invalid reviewer output")
        summary = parsed.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("Invalid reviewer output")
        return ReviewResult(ReviewDecision(decision_raw), summary.strip())


class TestingStage:
    __test__ = False
    def __init__(self, reviewer): self._reviewer = reviewer
    def run(self, development_result, test_result):
        deterministic_failure = (
            not getattr(test_result, "passed", False)
            or getattr(test_result, "timed_out", False)
        )
        try:
            review = self._reviewer.review(TestingReviewRequest(development_result, test_result))
        except Exception:
            # S5.6: a real deterministic test failure must force rework
            # independently of reviewer availability/opinion. Reviewer
            # infrastructure failure must never erase or downgrade a real
            # test failure into an unhandled review_failed outcome.
            if deterministic_failure:
                return TestingStageResult(
                    "rework_required", test_result, None,
                    ReworkRequest(
                        "tests require rework",
                        "DiagnosisReviewer unavailable; deterministic test "
                        "evidence indicates failure",
                        development_result, test_result,
                    ),
                )
            return TestingStageResult("review_failed", test_result, None)
        if deterministic_failure or review.decision is ReviewDecision.REWORK_REQUIRED:
            return TestingStageResult("rework_required", test_result, review, ReworkRequest("tests require rework", review.summary, development_result, test_result))
        return TestingStageResult("accepted", test_result, review)
