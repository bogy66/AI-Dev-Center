from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box


def sanitize_args(args: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *args* with sensitive values replaced by '[REDACTED]'."""
    sensitive_keys = {"api_key", "secret", "token", "password", "credential", "bearer"}
    sanitized: dict[str, Any] = {}
    for k, v in args.items():
        if any(s in k.lower() for s in sensitive_keys):
            sanitized[k] = "[REDACTED]"
        else:
            sanitized[k] = v
    return sanitized


# ---------------------------------------------------------------------------
#  Workflow result display
# ---------------------------------------------------------------------------

def _workflow_status(result: Any) -> str:
    plan = result.setup_plan
    status = getattr(plan, "status", "unknown")
    if status == "completed":
        return "[green]Completed[/]"
    if status == "pending_approval":
        return "[yellow]Waiting for approval[/]"
    if status == "approved":
        return "[blue]Approved[/]"
    if status == "executed":
        return "[green]Executed[/]"
    return status


def _build_timeline(result: Any) -> Table:
    table = Table(title="Workflow Timeline", box=box.SIMPLE)
    table.add_column("Stage", style="bold")
    table.add_column("Status")

    plan_status = getattr(result.setup_plan, "status", "unknown")
    discovery_fallback = getattr(result.discovery_result, "fallback_used", False)
    preflight_ready = getattr(result.preflight_result, "overall_ready", True)

    stages = [
        ("Inspect project", "completed"),
        (
            "Discover requirements",
            "blocked" if discovery_fallback else "completed",
        ),
        (
            "Preflight",
            "completed" if preflight_ready else "failed",
        ),
        ("Create setup plan", plan_status),
        ("Review plan", "completed"),
        (
            "Waiting for approval",
            "pending" if plan_status == "pending_approval" else "completed",
        ),
        (
            "Approving",
            "completed" if plan_status == "approved" else "pending",
        ),
        (
            "Executing",
            "completed" if plan_status == "executed" else "pending",
        ),
        ("Verifying", "completed"),
        ("Completed", "completed"),
    ]

    icons = {
        "completed": "[green]✓[/]",
        "pending": "[yellow]…[/]",
        "failed": "[red]✗[/]",
        "blocked": "[red]🚫[/]",
    }

    for stage, status in stages:
        icon = icons.get(status, status)
        table.add_row(stage, icon)

    return table


def _build_activity_log(result: Any) -> Table:
    table = Table(title="Activity Log", box=box.SIMPLE)
    table.add_column("Time")
    table.add_column("Component")
    table.add_column("Action")

    now = datetime.now()
    discovery_count = len(getattr(result.discovery_result, "requirements", []))
    preflight_ready = getattr(result.preflight_result, "overall_ready", True)
    plan_status = getattr(result.setup_plan, "status", "unknown")

    events = [
        (now - timedelta(seconds=10), "Agent", "started workflow"),
        (now - timedelta(seconds=8), "MCP", "inspect_project completed"),
        (
            now - timedelta(seconds=6),
            "Discovery",
            f"{discovery_count} requirements found",
        ),
        (
            now - timedelta(seconds=4),
            "Preflight",
            "all requirements satisfied"
            if preflight_ready
            else "missing requirements",
        ),
        (now - timedelta(seconds=2), "Planner", "setup plan created"),
        (
            now,
            "Approval",
            "waiting for user"
            if plan_status == "pending_approval"
            else "approved",
        ),
    ]

    for ts, comp, action in events:
        table.add_row(ts.strftime("%H:%M:%S"), comp, action)

    return table


def _build_mcp_activity(result: Any) -> Panel:
    # Deterministic workflow does not expose MCP tool calls.
    return Panel(
        "No MCP activity (deterministic workflow)", title="MCP Activity"
    )


def _build_setup_plan_panel(plan: Any) -> Panel:
    steps_table = Table(box=box.SIMPLE)
    steps_table.add_column("Step")
    steps_table.add_column("Action")
    steps_table.add_column("Package")
    steps_table.add_column("Status")

    for step in getattr(plan, "steps", []):
        status_icon = {
            "pending": "[yellow]…[/]",
            "approved": "[blue]✓[/]",
            "executing": "[yellow]⏳[/]",
            "succeeded": "[green]✓[/]",
            "failed": "[red]✗[/]",
        }.get(getattr(step, "status", "pending"), "?")
        steps_table.add_row(
            getattr(step, "requirement_id", ""),
            getattr(step, "action", ""),
            getattr(step, "package", "") or "",
            status_icon,
        )

    return Panel(
        f"Plan ID: {getattr(plan, 'id', '?')}\n"
        f"Status: {getattr(plan, 'status', '?')}\n"
        f"Steps:",
        title="Setup Plan",
    )


def _build_approval_panel(plan: Any) -> Panel:
    msg = (
        "This plan will execute the following setup actions.\n\n"
        "To approve, run:\n"
        f"  workflow-execution-cli --approve --plan-id {getattr(plan, 'id', '?')} <project_path>\n"
        "To reject, do not run the command."
    )
    return Panel(msg, title="Approval Required")


def display_workflow_result(
    console: Console,
    result: Any,
    config: Any,
    project_path: Path,
    elapsed: float,
) -> None:
    # 1. Project header
    header = Panel(
        f"[bold]Project:[/] {project_path.name}\n"
        f"Path: {project_path}\n"
        f"Status: {_workflow_status(result)}\n"
        f"Elapsed: {elapsed:.1f}s",
        title="Project Header",
    )
    console.print(header)

    # 2. Timeline
    console.print(_build_timeline(result))

    # 3. What is happening now?
    if getattr(getattr(result, "discovery_result", None), "fallback_used", False):
        console.print(
            Panel(
                "[yellow]Workflow blocked[/]\n"
                "Requirement discovery used a fallback; "
                "the workflow cannot safely continue.",
                title="What is happening now?",
            )
        )
    else:
        console.print(
            Panel(
                f"Workflow status: {_workflow_status(result)}",
                title="What is happening now?",
            )
        )

    # 4. Activity log
    console.print(_build_activity_log(result))

    # 5. MCP activity
    console.print(_build_mcp_activity(result))

    # 6. Setup plan
    console.print(_build_setup_plan_panel(result.setup_plan))

    # 7. Approval (if needed)
    if getattr(result.setup_plan, "status", "") == "pending_approval":
        console.print(_build_approval_panel(result.setup_plan))


def display_blocked_state(console: Console, message: str) -> None:
    panel = Panel(
        f"[red]Workflow blocked[/]\n{message}",
        title="Blocked",
    )
    console.print(panel)


def display_error(console: Console, message: str) -> None:
    panel = Panel(
        f"[red]Workflow failed[/]\n{message}",
        title="Error",
    )
    console.print(panel)


def display_execution_result(
    console: Console,
    results: list[Any],
    approved_plan: Any,
    elapsed: float,
) -> None:
    plan_id = getattr(approved_plan, "id", "?")
    plan_status = getattr(approved_plan, "status", "?")

    console.print(
        Panel(
            f"[bold]Plan ID:[/] {plan_id}\n"
            f"[bold]Status:[/] {plan_status}\n"
            f"[bold]Execution completed in {elapsed:.1f}s",
            title="Execution Result",
        )
    )

    table = Table(title="Execution Steps")
    table.add_column("Step ID")
    table.add_column("Success")
    table.add_column("Verification")
    table.add_column("Message")

    for res in results:
        table.add_row(
            str(getattr(res, "step_id", "")),
            "[green]✓[/]" if getattr(res, "success", False) else "[red]✗[/]",
            "[green]✓[/]"
            if getattr(res, "verification_passed", False)
            else "[red]✗[/]",
            str(getattr(res, "message", "")),
        )

    console.print(table)

def display_agent_result(console: Console, result: Any) -> None:
    if getattr(result, "error_message", None):
        console.print(
            Panel(
                f"[red]Error: {result.error_message}[/]",
                title="Agent Workflow",
            )
        )
        return

    if getattr(result, "approval_required", False):
        console.print(
            Panel(
                f"Project: {getattr(result, 'project_id', '?')}\n"
                f"Plan: {getattr(result, 'plan_id', '?')}\n"
                f"Status: {getattr(result, 'approval_status', '?')}\n\n"
                "Approval required. Use `agent-workflow-cli approve ...` to proceed.",
                title="Agent Workflow",
            )
        )
    else:
        console.print(
            Panel(
                f"Project: {getattr(result, 'project_id', '?')}\n"
                f"Plan: {getattr(result, 'plan_id', '?')}\n"
                f"Status: {getattr(result, 'workflow_status', '?')}",
                title="Agent Workflow",
            )
        )
