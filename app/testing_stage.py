"""Neutral, fail-safe diagnosis after a real test result."""
import json
from dataclasses import dataclass
from enum import Enum

from app.diagnostic_evidence import format_review_evidence


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
        # Test output is untrusted, possibly secret-bearing, unbounded text:
        # the reviewer's provider only receives the bounded, redacted
        # deterministic evidence contract (IF_REQ_025), never the raw repr.
        response = self._executor.run(
            "reviewer", format_review_evidence(request.test_result), "", "reviewer",
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


# Terminal S5.6 outcome for a verification that exceeded its execution
# budget without any diagnosed source-correctable cause: fail-closed
# (never accepted), and never a trigger for S5 -> S4 source rework or
# S5 -> S3 toolchain recovery (ARC_026, IF_REQ_026).
VERIFICATION_TIMEOUT = "verification_timeout"

# Step statuses that, alongside a timeout, carry no independent
# deterministic failure: BLOCKED only records that a dependency did not
# pass (here: the timed-out step).
_TIMEOUT_CONSEQUENCE_STATUSES = frozenset({"timeout", "blocked"})


# Terminal S5.6 outcome for a verification whose controlled execution
# infrastructure failed after the process had started (EXECUTION_ERROR):
# no valid project verdict exists, so it is fail-closed (never accepted)
# and never a trigger for S5 -> S4 source rework -- not even with a
# diagnosis -- or for S5 -> S3 toolchain recovery (ARC_026, IF_REQ_026).
VERIFICATION_EXECUTION_ERROR = "verification_execution_error"

# Step statuses that carry no valid project verdict of their own: an
# execution error, a timeout, and steps blocked behind them.
_EXECUTION_ERROR_CONSEQUENCE_STATUSES = frozenset({"execution_error", "timeout", "blocked"})


def is_execution_error_without_deterministic_failure(test_result) -> bool:
    """True when at least one step ended in EXECUTION_ERROR and no step
    delivered a real verdict failure (FAIL, INVALID_PLAN, ...): the
    verification did not establish PASS/FAIL of the project."""
    failures = getattr(test_result, "step_failures", ()) or ()
    statuses = [getattr(failure, "status", None) for failure in failures]
    return (
        "execution_error" in statuses
        and all(status in _EXECUTION_ERROR_CONSEQUENCE_STATUSES for status in statuses)
    )


def is_timeout_without_deterministic_failure(test_result) -> bool:
    """True when the result's only non-PASS evidence is an exceeded
    execution budget (plus steps blocked behind it) -- no real FAIL,
    EXECUTION_ERROR, ... alongside it."""
    if getattr(test_result, "timed_out", False) is not True:
        return False
    failures = getattr(test_result, "step_failures", ()) or ()
    return all(
        getattr(failure, "status", None) in _TIMEOUT_CONSEQUENCE_STATUSES
        for failure in failures
    )


class TestingStage:
    __test__ = False
    def __init__(self, reviewer): self._reviewer = reviewer
    def run(self, development_result, test_result):
        deterministic_failure = (
            not getattr(test_result, "passed", False)
            or getattr(test_result, "timed_out", False)
        )
        timeout_only = is_timeout_without_deterministic_failure(test_result)
        execution_error = is_execution_error_without_deterministic_failure(test_result)
        try:
            review = self._reviewer.review(TestingReviewRequest(development_result, test_result))
        except Exception:
            if execution_error:
                return TestingStageResult(VERIFICATION_EXECUTION_ERROR, test_result, None)
            if timeout_only:
                # No diagnosis at all -> no source-correctable cause.
                return TestingStageResult(VERIFICATION_TIMEOUT, test_result, None)
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
        if execution_error:
            # The diagnosis may describe the execution error, but it has
            # no authority to turn it into a source defect.
            return TestingStageResult(VERIFICATION_EXECUTION_ERROR, test_result, review)
        if timeout_only:
            # A timeout alone is not proof of a source defect: the single
            # bounded S5 -> S4 rework is used only when the diagnosis
            # explicitly identifies a source-correctable cause.
            if review.decision is ReviewDecision.REWORK_REQUIRED:
                return TestingStageResult(
                    "rework_required", test_result, review,
                    ReworkRequest(
                        "diagnosis identified a source-correctable cause of the verification timeout",
                        review.summary, development_result, test_result,
                    ),
                )
            return TestingStageResult(VERIFICATION_TIMEOUT, test_result, review)
        if deterministic_failure or review.decision is ReviewDecision.REWORK_REQUIRED:
            return TestingStageResult("rework_required", test_result, review, ReworkRequest("tests require rework", review.summary, development_result, test_result))
        return TestingStageResult("accepted", test_result, review)
