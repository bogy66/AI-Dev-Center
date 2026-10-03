from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from app.gui import (
    sanitize_args,
    display_workflow_result,
    display_blocked_state,
    display_error,
    display_execution_result,
    display_agent_result,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_result(
    *,
    discovery_fallback=False,
    discovery_count=3,
    preflight_ready=True,
    plan_status="completed",
    plan_id="plan-1",
    steps=None,
):
    """Return a mock workflow result with the given attributes."""
    result = MagicMock()
    result.discovery_result.fallback_used = discovery_fallback
    result.discovery_result.requirements = [MagicMock() for _ in range(discovery_count)]
    result.preflight_result.overall_ready = preflight_ready
    result.setup_plan.status = plan_status
    result.setup_plan.id = plan_id
    result.setup_plan.steps = steps or []
    return result


def _capture_output(func, *args, **kwargs):
    console = Console(force_terminal=True, color_system="truecolor")
    with console.capture() as capture:
        func(console, *args, **kwargs)
    return capture.get()


# ---------------------------------------------------------------------------
# sanitize_args
# ---------------------------------------------------------------------------

def test_sanitize_args_redacts_sensitive_keys():
    args = {
        "api_key": "secret-123",
        "token": "abc",
        "password": "p@ss",
        "credential": "x",
        "bearer": "y",
        "normal": "visible",
    }
    sanitized = sanitize_args(args)
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["token"] == "[REDACTED]"
    assert sanitized["password"] == "[REDACTED]"
    assert sanitized["credential"] == "[REDACTED]"
    assert sanitized["bearer"] == "[REDACTED]"
    assert sanitized["normal"] == "visible"


def test_sanitize_args_case_insensitive():
    args = {"API_KEY": "val", "Secret": "val2"}
    sanitized = sanitize_args(args)
    assert sanitized["API_KEY"] == "[REDACTED]"
    assert sanitized["Secret"] == "[REDACTED]"


# ---------------------------------------------------------------------------
# display_workflow_result
# ---------------------------------------------------------------------------

@patch("app.gui.datetime")
def test_display_workflow_result_completed(mock_datetime):
    now = datetime(2025, 1, 1, 12, 0, 0)
    mock_datetime.now.return_value = now

    result = _make_mock_result(plan_status="completed")
    config = MagicMock()
    project_path = Path("/tmp/test-proj")
    elapsed = 2.5

    output = _capture_output(
        display_workflow_result, result, config, project_path, elapsed
    )

    assert "Project Header" in output
    assert "test-proj" in output
    assert "Completed" in output
    assert "Elapsed: 2.5s" in output
    assert "Workflow Timeline" in output
    assert "✓" in output
    assert "Activity Log" in output
    assert "3 requirements found" in output
    assert "all requirements satisfied" in output
    assert "setup plan created" in output
    assert "approved" in output
    assert "MCP Activity" in output
    assert "Setup Plan" in output
    assert "plan-1" in output


@patch("app.gui.datetime")
def test_display_workflow_result_pending_approval(mock_datetime):
    now = datetime(2025, 1, 1, 12, 0, 0)
    mock_datetime.now.return_value = now

    result = _make_mock_result(plan_status="pending_approval")
    config = MagicMock()
    project_path = Path("/tmp/test-proj")
    elapsed = 0.0

    output = _capture_output(
        display_workflow_result, result, config, project_path, elapsed
    )

    assert "Waiting for approval" in output
    assert "Approval Required" in output
    assert "workflow-execution-cli --approve --plan-id plan-1" in output


@patch("app.gui.datetime")
def test_display_workflow_result_blocked_discovery(mock_datetime):
    now = datetime(2025, 1, 1, 12, 0, 0)
    mock_datetime.now.return_value = now

    result = _make_mock_result(discovery_fallback=True, plan_status="completed")
    config = MagicMock()
    project_path = Path("/tmp/test-proj")
    elapsed = 0.0

    output = _capture_output(
        display_workflow_result, result, config, project_path, elapsed
    )

    assert "🚫" in output
    assert "blocked" in output


# ---------------------------------------------------------------------------
# display_blocked_state
# ---------------------------------------------------------------------------

def test_display_blocked_state():
    output = _capture_output(display_blocked_state, "fallback used")
    assert "Workflow blocked" in output
    assert "fallback used" in output


# ---------------------------------------------------------------------------
# display_error
# ---------------------------------------------------------------------------

def test_display_error():
    output = _capture_output(display_error, "something went wrong")
    assert "Workflow failed" in output
    assert "something went wrong" in output


# ---------------------------------------------------------------------------
# display_execution_result
# ---------------------------------------------------------------------------

def test_display_execution_result():
    results = [
        MagicMock(
            step_id="s1", success=True, verification_passed=True, message="ok"
        ),
        MagicMock(
            step_id="s2", success=False, verification_passed=False, message="fail"
        ),
    ]
    plan = MagicMock(id="plan-1", status="executed")
    elapsed = 1.2

    output = _capture_output(display_execution_result, results, plan, elapsed)

    assert "Execution completed in 1.2s" in output
    assert "plan-1" in output
    assert "executed" in output
    assert "s1" in output
    assert "✓" in output
    assert "✗" in output
    assert "ok" in output
    assert "fail" in output


# ---------------------------------------------------------------------------
# display_agent_result
# ---------------------------------------------------------------------------

def test_display_agent_result_error():
    result = MagicMock(error_message="connection refused")
    output = _capture_output(display_agent_result, result)
    assert "Error: connection refused" in output


def test_display_agent_result_approval_required():
    result = MagicMock(
        error_message=None,
        approval_required=True,
        project_id="proj-1",
        plan_id="plan-2",
        approval_status="pending",
    )
    output = _capture_output(display_agent_result, result)
    assert "Approval required" in output
    assert "proj-1" in output
    assert "plan-2" in output


def test_display_agent_result_completed():
    result = MagicMock(
        error_message=None,
        approval_required=False,
        project_id="proj-1",
        plan_id="plan-2",
        workflow_status="completed",
    )
    output = _capture_output(display_agent_result, result)
    assert "completed" in output
    assert "proj-1" in output
    assert "plan-2" in output
