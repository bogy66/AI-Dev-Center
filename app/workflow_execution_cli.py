"""Explicit approval/execution entry point for a development workflow."""

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


MAX_FILE_SIZE = 1_000_000


def read_project_files(project_path: Path) -> tuple[list[dict], list[str]]:
    files: list[dict] = []
    warnings: list[str] = []

    for path in sorted(project_path.rglob("*")):
        if not path.is_file():
            continue

        try:
            size = path.stat().st_size
        except OSError:
            warnings.append(f"Skipping unreadable file: {path}")
            continue

        if size > MAX_FILE_SIZE:
            warnings.append(f"Skipping large file: {path}")
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            warnings.append(f"Skipping binary/unreadable file: {path}")
            continue

        files.append(
            {
                "path": str(path.relative_to(project_path)),
                "content": content,
            }
        )

    return files, warnings


def build_workflow(config) -> DevelopmentWorkflow:
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
):
    files, warnings = read_project_files(project_path)

    project_info = {
        "project_id": project_path.name,
        "project_path": str(project_path),
        "files": files,
    }

    workflow_result = workflow.run(
        project_info=project_info,
        project_id=project_path.name,
    )

    pending_plan = workflow_result.setup_plan

    if pending_plan.status != "pending_approval":
        raise RuntimeError(
            f"Expected pending_approval plan, got {pending_plan.status!r}"
        )

    approved_plan = SetupApproval.approve(pending_plan)
    results = workflow.execute_approved(approved_plan)

    return results, approved_plan, warnings


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Explicitly approve and execute a development setup plan."
    )
    parser.add_argument(
        "--approve",
        action="store_true",
        help="Explicitly approve and execute the generated setup plan.",
    )
    parser.add_argument("project_path")
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

        results, approved_plan, warnings = run_approved_execution(
            project_path,
            workflow=workflow,
        )
    except Exception:
        print("Workflow execution failed.", file=sys.stderr)
        raise SystemExit(1)

    for warning in warnings:
        print(warning, file=sys.stderr)

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
