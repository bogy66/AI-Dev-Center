import pytest
from unittest.mock import MagicMock, patch

from app.reviewer_agent import ReviewerAgent


def test_reviewer_changes_required_when_tester_not_completed():
    reviewer = ReviewerAgent()
    state = {
        "tester": {
            "status": "pending",
            "result": None
        }
    }

    result = reviewer.review("mock_project", state)

    assert result["status"] == "changes_required"
    assert result["result"] == "Testergebnis fehlt"


def test_reviewer_changes_required_when_tester_failed():
    reviewer = ReviewerAgent()
    state = {
        "tester": {
            "status": "completed",
            "result": "FAIL"
        }
    }

    result = reviewer.review("mock_project", state)

    assert result["status"] == "changes_required"
    assert result["result"] == "Tests nicht erfolgreich"


def test_reviewer_approved_when_git_diff_succeeds():
    reviewer = ReviewerAgent()
    state = {
        "tester": {
            "status": "completed",
            "result": "PASS"
        }
    }

    with patch.object(reviewer.git, 'diff', return_value={
        "code": 0,
        "stdout": "diff output",
        "stderr": ""
    }):
        result = reviewer.review("mock_project", state)

    assert result["status"] == "approved"
    assert result["result"] == "Review erfolgreich"


def test_reviewer_review_failed_when_git_diff_fails():
    reviewer = ReviewerAgent()
    state = {
        "tester": {
            "status": "completed",
            "result": "PASS"
        }
    }

    git_error = "fatal: not a git repository"
    with patch.object(reviewer.git, 'diff', return_value={
        "code": 1,
        "stdout": "",
        "stderr": git_error
    }):
        result = reviewer.review("mock_project", state)

    assert result["status"] == "review_failed"
    assert result["result"] == git_error


def test_reviewer_changes_required_when_git_diff_returns_changes():
    reviewer = ReviewerAgent()
    state = {
        "tester": {
            "status": "completed",
            "result": "PASS"
        }
    }

    with patch.object(reviewer.git, 'diff', return_value={
        "code": 0,
        "stdout": "diff output with changes",
        "stderr": ""
    }):
        result = reviewer.review("mock_project", state)

    assert result["status"] == "approved"
    assert result["result"] == "Review erfolgreich"
