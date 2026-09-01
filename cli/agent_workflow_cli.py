from __future__ import annotations
import argparse

from app.canonical_composition import build_canonical_components


def _build_workflow():
    return build_canonical_components()


def start_command(args: argparse.Namespace) -> int:
    components = _build_workflow()
    result = components.service.plan_project_setup(args.project_id, args.project_path)
    components.plan_store.save(result.setup_plan)
    print(f"pending approval: project={args.project_id}, plan={result.setup_plan.id}")
    print(f"approval_status={result.setup_plan.status}")
    return 0


def approve_command(args: argparse.Namespace) -> int:
    components = _build_workflow()
    plan = components.plan_store.load(args.project_id, args.plan_id)
    approved = components.approval.approve(plan)
    components.plan_store.save(approved)
    print(f"approved: project={args.project_id}, plan={args.plan_id}")
    print("execution requires the canonical run-specific execution adapter")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agent-workflow-cli",
        description="Compatibility CLI routed to the canonical setup workflow.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="Run the setup workflow up to pending approval")
    start.add_argument("project_id")
    start.add_argument("project_path")
    start.set_defaults(func=start_command)

    approve = sub.add_parser("approve", help="Approve a pending plan without implicit execution")
    approve.add_argument("project_id")
    approve.add_argument("plan_id")
    approve.set_defaults(func=approve_command)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
