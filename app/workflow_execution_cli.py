"""Explicit approval/execution entry point for a persisted workflow plan."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.ai_config import load_ai_config
from app.ai_requirement_discovery import AIRequirementDiscovery
from app.dev_workflow import DevelopmentWorkflow
from app.llm_provider_factory import create_llm_provider
from app.local_secret_store import LocalSecretStore
from app.python_package_executor import PythonPackageExecutor
from app.requirement_preflight import RequirementPreflight
from app.requirement_validator import RequirementValidator
from app.setup_approval import SetupApproval
from app.setup_planner import SetupPlanner
from app.workflow_plan_store import WorkflowPlanStore


def build_workflow(config) -> DevelopmentWorkflow:
    """Build a workflow with the real package executor."""
    secret_resolver = LocalSecretStore()
    provider = create_llm_provider(config, secret_resolver)
    executor = PythonPackageExecutor()

    discovery = AIRequirementDiscovery(
        llm_provider=provider,
        ai_model=config.model,
    )

    return DevelopmentWorkflow(
        discovery=discovery,
        validator=RequirementValidator,
        preflight=RequirementPreflight,
        planner=SetupPlanner(),
        executor=executor,
    )


def run_approved_execution(
    project_path: Path,
    *,
    workflow: DevelopmentWorkflow,
    plan_id: str,
    store: WorkflowPlanStore | None = None,
):
    """Load, approve and execute an existing persisted setup plan.

    No discovery or planning is performed here. The exact persisted plan
    identified by ``project_path.name`` and ``plan_id`` is used.
    """
    if store is None:
        store = WorkflowPlanStore(".workflow-plans")

    plan = store.load(project_path.name, plan_id)

    if plan.status != "pending_approval":
        raise RuntimeError(
            f"Expected pending_approval plan, got {plan.status!r}"
        )

    approved_plan = SetupApproval.approve(plan)
    results = workflow.execute_approved(approved_plan)

    store.save(approved_plan)

    return results, approved_plan


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Explicitly approve and execute a persisted development "
            "setup plan."
        )
    )
    parser.add_argument(
        "--approve",
        action="store_true",
        help="Explicitly approve and execute the stored setup plan.",
    )
    parser.add_argument(
        "--plan-id",
        required=True,
        help="ID of the persisted setup plan to execute.",
    )
    parser.add_argument(
        "project_path",
        help="Path to the project owning the setup plan.",
    )
    args = parser.parse_args()

    project_path = Path(args.project_path).expanduser().resolve()

    if not project_path.exists():
        print("Error: project path does not exist", file=sys.stderr)
        raise SystemExit(1)

    if not project_path.is_dir():
        print("Error: project path is not a directory", file=sys.stderr)
        raise SystemExit(1)

    if not args.approve:
        print(
            "Execution not approved. Use --approve to explicitly "
            "authorize setup execution.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    try:
        config = load_ai_config("config/ai-dev-center.yml")
        workflow = build_workflow(config)
        store = WorkflowPlanStore(".workflow-plans")

        results, approved_plan = run_approved_execution(
            project_path,
            workflow=workflow,
            plan_id=args.plan_id,
            store=store,
        )
    except Exception:
        print("Workflow execution failed.", file=sys.stderr)
        raise SystemExit(1)

    print(f"SetupPlan ID: {approved_plan.id}")
    print(f"SetupPlan status: {approved_plan.status}")
    print(f"Number of SetupSteps: {len(approved_plan.steps)}")
    print(f"Execution results: {len(results)}")

    for result in results:
        print("---")
        print(f"step_id: {result.step_id}")
        print(f"success: {result.success}")
        print(f"verification_passed: {result.verification_passed}")
        print(f"message: {result.message}")

    raise SystemExit(0)


if __name__ == "__main__":
    main()
