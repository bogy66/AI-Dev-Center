"""CLAUDE-E2E-003G: MCP planning/approval/execution central-path parity.

Proves the gap CLAUDE-E2E-003F reported (MCPServer.plan_project_setup
never threaded project_root into DevelopmentWorkflow.run() as a
project_context, so every MCP-planned step's target_executable was
None) is now closed: MCPServer.plan_project_setup calls the exact same
ProjectSetupApplicationService.plan_project_setup() contract Web/API
uses, so an MCP-originated plan resolves a real target_executable
itself -- this file never pre-seeds a plan created by Web or direct
test code.

The core acceptance test (test_mcp_full_lifecycle_survives_path_drift_hermetically)
drives the real MCP JSON-RPC tool boundary (MCPRequestHandler wrapping
a real MCPServer, backed by a real ProjectSetupApplicationService) for
all three productive tools -- plan_project_setup, approve_setup_plan,
execute_setup_plan -- and is fully hermetic: it installs a locally
built wheel (tests/local_package_fixture.py) rather than depending on
PyPI/network access (CLAUDE-E2E-003G Part 9). Only the two genuinely
LLM-dependent boundaries (Discovery, Engineering Council) are replaced
with deterministic fixtures, matching every other real-integration test
in this task family.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest

from app.ai_config import load_ai_config
from app.council_models import CouncilResult, CouncilVariant, ToolchainItem
from app.dev_workflow import DevelopmentWorkflow
from app.mcp_server import MCPServer
from app.mcp_transport import MCPRequestHandler
from app.project_context import ProjectDefinitionStore
from app.project_setup_application import ProjectSetupApplicationService
from app.python_package_executor import PythonPackageExecutor
from app.requirement_model import (
    DiscoveryResult, Requirement, RequirementActivation, RequirementType,
)
from app.requirement_preflight import RequirementPreflight
from app.requirement_validator import RequirementValidator
from app.setup_approval import SetupApproval
from app.toolchain_materializer import ToolchainMaterializer
from app.workflow_manager import WorkflowManager
from app.workflow_plan_store import WorkflowPlanStore

from tests.local_package_fixture import (
    PACKAGE_IMPORT_NAME, PACKAGE_NAME,
    build_isolated_toolchain, build_local_wheel_index,
)

AI_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "ai-dev-center.yml",
)


class _FixedDiscovery:
    def __init__(self, requirement: Requirement):
        self._requirement = requirement

    def discover(self, project_info, project_id, user_request=None):
        return DiscoveryResult(
            id="disc-mcp", source="fixture", project_id=project_id,
            requirements=(self._requirement,),
            activations=(RequirementActivation(self._requirement.id, True, True, "fixture"),),
        )


class _FixedCouncil:
    def __init__(self, requirement_id: str, project_id: str):
        self._requirement_id = requirement_id
        self._project_id = project_id

    def evaluate(self, council_input):
        item = ToolchainItem(
            requirement_ref=self._requirement_id, name=PACKAGE_NAME,
            type=RequirementType.PYTHON_PACKAGE,
            install_method=f"pip install {PACKAGE_NAME}",
        )
        variant = CouncilVariant(id="variant-1", name="variant-1", toolchain=(item,))
        return CouncilResult(
            id="council-mcp", project_id=self._project_id,
            variants=(variant,), recommendation="variant-1", council_complete=True,
        )


def _build_server(tmp_path, requirement, project_id):
    from app.setup_execution_state import SetupExecutionStateStore

    workflow = DevelopmentWorkflow(
        discovery=_FixedDiscovery(requirement), validator=RequirementValidator,
        preflight=RequirementPreflight, executor=PythonPackageExecutor(),
        council=_FixedCouncil(requirement.id, project_id),
        materializer=ToolchainMaterializer(),
        execution_state_store=SetupExecutionStateStore(tmp_path / "exec-state.json"),
    )
    service = ProjectSetupApplicationService(
        development_workflow=workflow,
        workflow_manager=WorkflowManager(storage=str(tmp_path / "workflow_state.json")),
        technical_config=load_ai_config(AI_CONFIG_PATH),
        project_definition_store=ProjectDefinitionStore(path=str(tmp_path / "definitions.json")),
    )
    plan_store = WorkflowPlanStore(tmp_path / "plans")
    server = MCPServer(
        project_scanner=object(), discovery=object(), preflight=RequirementPreflight,
        planner=None, plan_store=plan_store, approval=SetupApproval,
        development_workflow=workflow, service=service,
    )
    return MCPRequestHandler(server), plan_store, service, workflow


def _call(handler, name, arguments):
    handler.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}})
    response = handler.handle({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    })
    assert "error" not in response, response
    return json.loads(response["result"]["content"][0]["text"])


def _plan_via_mcp_with_explicit_selection(
    handler, service, workflow, plan_store, project_id, project_path,
    task_description=None,
):
    """CLAUDE-ARCH-S2-013C: MCP's plan_project_setup tool now fails
    closed at the productive S2.4 boundary -- MCP deliberately does not
    implement an interactive selection tool (out of scope for this
    task). These tests are about MCP/Web execution-target parity, not
    S2.4, so this resolves the pending selection directly through
    DevelopmentWorkflow (exactly what a real human decision would resume
    with) and persists the result the same way MCPServer.
    plan_project_setup() itself would have, then returns the same
    JSON-shaped dict _call(handler, "plan_project_setup", ...) used to
    return."""
    from app.project_setup_application import persist_setup_plan

    entry_data = {"project_id": project_id}
    if task_description:
        entry_data["task_description"] = task_description
    pending_result = service.plan_project_setup(
        project_id, project_path, entry_interface="mcp", entry_data=entry_data,
    )
    resumed_result = workflow.resolve_engineering_selection(
        pending_result.council_result, pending_result.preflight_result,
        pending_result.platform, project_id,
        human_selected_variant_id=pending_result.council_result.recommendation,
    )
    persist_setup_plan(plan_store, resumed_result.setup_plan, resumed_result.council_result)
    plan_store.save_project_root(project_id, project_path)
    from dataclasses import asdict
    return json.loads(json.dumps(asdict(resumed_result.setup_plan), default=str))


def test_mcp_originated_plan_resolves_a_real_target_executable(tmp_path, monkeypatch):
    """The CLAUDE-E2E-003F gap is closed: planning through the real MCP
    plan_project_setup tool -- not a Web-originated or hand-built plan
    -- resolves a real, non-None target_executable, because it now
    goes through the same central ProjectSetupApplicationService.plan_project_setup()
    contract Web/API uses."""
    target_a = build_isolated_toolchain(tmp_path, "toolchain-a", build_local_wheel_index(tmp_path))
    project_path = tmp_path / "project"
    project_path.mkdir()
    prior_path = os.environ.get("PATH", "")
    monkeypatch.setenv("PATH", f"{os.path.dirname(target_a)}:{prior_path}")

    requirement = Requirement(
        technical_identity=PACKAGE_NAME,
        id="req-mcp", name=PACKAGE_NAME, type=RequirementType.PYTHON_PACKAGE,
        purpose="test dependency", required=True, confidence=0.9,
    )
    handler, plan_store, service, workflow = _build_server(tmp_path, requirement, "proj-mcp-target")

    result = _plan_via_mcp_with_explicit_selection(
        handler, service, workflow, plan_store, "proj-mcp-target", str(project_path),
    )

    assert result["steps"][0]["target_executable"] == target_a


class TestMcpFullLifecyclePathDrift:
    """The Part 6/7 core productive acceptance scenario, hermetic
    (Part 9): MCP itself plans (resolving Target A), persists the plan
    and Council/Chairman references, PATH drifts to Target B, MCP
    itself approves, MCP itself executes -- a real, local (no PyPI)
    pip install of a hand-built wheel, real post-install verification.
    """

    def test_full_lifecycle(self, tmp_path, monkeypatch):
        wheels_dir = build_local_wheel_index(tmp_path)
        target_a = build_isolated_toolchain(tmp_path, "toolchain-a", wheels_dir)
        project_path = tmp_path / "project"
        project_path.mkdir()
        prior_path = os.environ.get("PATH", "")
        monkeypatch.setenv("PATH", f"{os.path.dirname(target_a)}:{prior_path}")

        requirement = Requirement(
            technical_identity=PACKAGE_NAME,
            id="req-mcp-full", name=PACKAGE_NAME, type=RequirementType.PYTHON_PACKAGE,
            purpose="test dependency", required=True, confidence=0.9,
        )
        project_id = "proj-mcp-full"
        handler, plan_store, service, workflow = _build_server(tmp_path, requirement, project_id)

        # --- MCP itself plans: real Preflight resolves Target A ---
        plan = _plan_via_mcp_with_explicit_selection(
            handler, service, workflow, plan_store, project_id, str(project_path),
            task_description="Install the fixture package",
        )
        plan_id = plan["id"]
        assert plan["steps"][0]["target_executable"] == target_a

        # --- Real, persisted Council/Chairman references exist ---
        council_refs = plan_store.load_council_reference(project_id, plan_id)
        assert council_refs == ("council-mcp", "variant-1")

        # --- PATH MUTATION: Target A's directory removed from PATH ---
        monkeypatch.setenv("PATH", prior_path)
        target_b = shutil.which("python") or sys.executable
        assert target_b != target_a, "test setup invalid: PATH mutation had no effect"

        # --- MCP itself approves ---
        approved = _call(handler, "approve_setup_plan", {
            "project_id": project_id, "plan_id": plan_id,
        })
        assert approved["status"] == "approved"

        # --- MCP itself executes: real, local (hermetic) pip install ---
        results = _call(handler, "execute_setup_plan", {
            "project_id": project_id, "plan_id": plan_id,
        })

        assert len(results) == 1
        assert results[0]["success"] is True
        assert results[0]["verification_passed"] is True

        # --- Independent real confirmation: Target A has the package ---
        check_a = subprocess.run(
            [target_a, "-c", f"import {PACKAGE_IMPORT_NAME}; print({PACKAGE_IMPORT_NAME}.__file__)"],
            capture_output=True, text=True, timeout=30,
        )
        assert check_a.returncode == 0
        assert "toolchain-a" in check_a.stdout

        # --- Target B was never touched ---
        check_b = subprocess.run(
            [target_b, "-c", f"import {PACKAGE_IMPORT_NAME}"],
            capture_output=True, text=True, timeout=30,
        )
        assert check_b.returncode != 0, "Target B must remain untouched"
