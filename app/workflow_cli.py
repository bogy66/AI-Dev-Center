from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.ai_config import load_ai_config
from app.ai_requirement_discovery import AIRequirementDiscovery
from app.dev_workflow import DevelopmentWorkflow, WorkflowExecutionError
from app.engineering_council import EngineeringCouncil
from app.llm_provider_factory import create_llm_provider
from app.local_secret_store import LocalSecretStore
from app.project_intelligence import inspect_project
from app.project_files import MAX_FILE_SIZE, read_project_files
from app.requirement_preflight import RequirementPreflight
from app.requirement_validator import RequirementValidator
from app.toolchain_materializer import ToolchainMaterializer
from app.workflow_plan_store import WorkflowPlanStore


def build_workflow(config):
    council_config = config.council
    if council_config is None or not getattr(council_config, "enabled", False):
        raise WorkflowExecutionError(
            "Engineering Council configuration must be enabled."
        )

    secret_resolver = LocalSecretStore()
    provider = create_llm_provider(config, secret_resolver)

    discovery = AIRequirementDiscovery(
        llm_provider=provider,
        ai_model=config.model,
    )
    council = EngineeringCouncil(
        council_config=council_config,
        secret_resolver=secret_resolver,
    )

    return DevelopmentWorkflow(
        discovery=discovery,
        validator=RequirementValidator,
        preflight=RequirementPreflight,
        council=council,
        materializer=ToolchainMaterializer(),
    )


def print_result(config, result) -> None:
    print(f"Provider: {config.provider}")
    print(f"Model: {config.model}")
    print(f"Discovery fallback: {result.discovery_result.fallback_used}")
    print(f"Number of requirements: {len(result.discovery_result.requirements)}")

    print(f"Validation valid: {result.validation_result.valid}")
    print(f"Normalized: {len(result.validation_result.normalized_requirements)}")
    print(f"Rejected: {len(result.validation_result.rejected_requirements)}")

    print(f"Preflight ready: {result.preflight_result.overall_ready}")
    print(f"Missing count: {len(result.preflight_result.missing_requirements)}")
    print(f"Warning count: {len(result.preflight_result.warnings)}")

    print(f"SetupPlan status: {result.setup_plan.status}")
    print(f"Number of SetupSteps: {len(result.setup_plan.steps)}")

    for step in result.setup_plan.steps:
        print("---")
        print(f"requirement_id: {step.requirement_id}")
        print(f"action: {step.action}")
        print(f"package: {step.package}")
        print(f"version: {step.version}")
        print(f"is_approved: {step.is_approved}")

    print(f"SetupPlan ID: {result.setup_plan.id}")

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the AI-Dev-Center development workflow."
    )
    parser.add_argument("project_path", help="Path to the project to analyze")
    args = parser.parse_args()

    project_path = Path(args.project_path).expanduser().resolve()

    if not project_path.exists():
        print("Error: project path does not exist", file=sys.stderr)
        raise SystemExit(1)

    if not project_path.is_dir():
        print("Error: project path is not a directory", file=sys.stderr)
        raise SystemExit(1)

    try:
        config = load_ai_config("config/ai-dev-center.yml")
    except Exception as exc:
        print(f"Error loading AI config: {exc}", file=sys.stderr)
        raise SystemExit(1)

    try:
        intelligence = inspect_project(project_path)

        for warning in intelligence.warnings:
            print(warning, file=sys.stderr)

        files, file_warnings = read_project_files(project_path)
        for warning in file_warnings:
            print(warning, file=sys.stderr)

        project_info = intelligence.to_summary()
        project_info["project_id"] = project_path.name
        project_info["project_path"] = str(project_path)
        project_info["files"] = files

        workflow = build_workflow(config)
        result = workflow.run(
            project_info=project_info,
            project_id=project_path.name,
        )

        store = WorkflowPlanStore(".workflow-plans")
        store.save(result.setup_plan)

    except WorkflowExecutionError as exc:
        print(f"Workflow blocked: {exc}", file=sys.stderr)
        raise SystemExit(2)
    except Exception as exc:
        print(f"Workflow failed: {exc}", file=sys.stderr)
        raise SystemExit(1)

    print_result(config, result)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
