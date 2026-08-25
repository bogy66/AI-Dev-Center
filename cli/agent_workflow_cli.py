from __future__ import annotations
import argparse
import sys
from pathlib import Path

from app.agent_setup_workflow import AgentSetupWorkflow
from app.openrouter_llm_provider import OpenRouterLLMProvider
from app.mcp_server import MCPServer


def _build_workflow() -> AgentSetupWorkflow:
    llm = OpenRouterLLMProvider()
    mcp = MCPServer()
    return AgentSetupWorkflow(llm, mcp)


def start_command(args: argparse.Namespace) -> int:
    workflow = _build_workflow()
    result = workflow.start_setup_workflow(args.project_id, args.project_path)
    if result.approval_required:
        print(f"pending approval: project={result.project_id}, plan={result.plan_id}")
        print(f"approval_status={result.approval_status}")
        return 0
    if result.error_message:
        print(f"error: {result.error_message}", file=sys.stderr)
        return 1
    print(f"unexpected result: {result.agent_status}")
    return 1


def approve_command(args: argparse.Namespace) -> int:
    workflow = _build_workflow()
    result = workflow.approve_and_execute(args.project_id, args.plan_id)
    if result.workflow_status == "completed":
        print(f"completed: project={result.project_id}, plan={result.plan_id}")
        return 0
    if result.error_message:
        print(f"error: {result.error_message}", file=sys.stderr)
        return 1
    print(f"unexpected result: {result.workflow_status}")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agent-workflow-cli",
        description="Run the LLM agent setup workflow through MCP tools.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="Run the setup workflow up to pending approval")
    start.add_argument("project_id")
    start.add_argument("project_path")
    start.set_defaults(func=start_command)

    approve = sub.add_parser("approve", help="Approve and execute a pending plan")
    approve.add_argument("project_id")
    approve.add_argument("plan_id")
    approve.set_defaults(func=approve_command)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
