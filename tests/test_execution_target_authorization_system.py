"""CLAUDE-E2E-003E SYSTEM test (Part 10: 1 required deterministic
system test), entering through the highest practical productive ADC
application/service boundary: ProjectSetupApplicationService itself -
the exact object app/web_api.py and app/mcp_server.py both delegate
to.

Only the two genuinely LLM-dependent boundaries are replaced, matching
the task's own allowed-replacement category ("LLM generation"):
  - Requirement Discovery (a deterministic DiscoveryResult fixture)
  - Engineering Council (a deterministic CouncilResult fixture, the
    same style of replacement tests/test_real_productive_integration.py
    already established for CLAUDE-E2E-003D)
  - The Development/Testing/Rework stage's own LLM-backed Developer
    agent (a deterministic ControlledReworkResult fixture) - this is a
    separate LLM boundary fused into execute_approved_setup_and_development
    by DevelopmentWorkflow, legitimately replaceable via its existing
    controlled_rework_stage constructor injection point without
    touching anything this test is actually about (execution-target
    authorization).

Everything else is real and wired exactly as production wires it:
RequirementPreflight, RequirementValidator, ToolchainMaterializer,
PythonPackageExecutor (default-constructed), WorkflowPlanStore, real
SetupApproval, real project_context composition via a real AIConfig
(load_ai_config against the repository's own shipped config), the real
DEFAULT_CAPABILITY_REGISTRY, real execute_controlled/validate_request,
a real subprocess pip install, and real post-install verification.

Network dependency: a single real "pip install iniconfig" against an
isolated venv, the same tiny, already-pytest-transitive package used
throughout this task's other real-integration tests. Skips (does not
fail) if genuinely no network access is available.
"""
from __future__ import annotations

import os
import subprocess
import sys
import venv
from types import SimpleNamespace

import pytest

from app.ai_config import load_ai_config
from app.approved_plan_content import ApprovedPlanContentStore
from app.controlled_rework_stage import ControlledReworkResult
from app.council_models import CouncilResult, CouncilVariant, ToolchainItem
from app.development_testing_stage import DevelopmentTestingResult
from app.dev_workflow import DevelopmentWorkflow
from app.project_context import ProjectDefinitionStore
from app.project_setup_application import ProjectSetupApplicationService
from app.python_package_executor import PythonPackageExecutor
from app.requirement_model import (
    DiscoveryResult, Requirement, RequirementActivation, RequirementType,
)
from app.requirement_preflight import RequirementPreflight
from app.requirement_validator import RequirementValidator
from app.toolchain_materializer import ToolchainMaterializer
from app.workflow_manager import WorkflowManager
from app.workflow_plan_store import WorkflowPlanStore

TEST_PACKAGE = "iniconfig"
AI_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "ai-dev-center.yml",
)


def _build_isolated_toolchain(tmp_path, name):
    toolchain_dir = tmp_path / name
    venv.EnvBuilder(with_pip=True, clear=True).create(toolchain_dir)
    return str(toolchain_dir / "bin" / "python")


def _network_unavailable(execution_result) -> bool:
    message = (execution_result.message or "").lower()
    return "temporary failure" in message or "network" in message or "resolve" in message


class _FakeDiscovery:
    """Stand-in for AI-driven Requirement Discovery: a fixed,
    deterministic result naming exactly the one requirement this test
    is about. Not a mock of a real Discovery object's internals - a
    fixture in its place, matching this task's LLM-replacement rule."""

    def __init__(self, requirement: Requirement):
        self._requirement = requirement

    def discover(self, project_info, project_id, user_request=None):
        return DiscoveryResult(
            id="disc-system", source="fixture", project_id=project_id,
            requirements=(self._requirement,),
            activations=(
                RequirementActivation(self._requirement.id, True, True, "fixture"),
            ),
        )


class _FakeCouncil:
    """Stand-in for Engineering Council LLM generation."""

    def __init__(self, requirement_id: str, project_id: str):
        self._requirement_id = requirement_id
        self._project_id = project_id

    def evaluate(self, council_input):
        item = ToolchainItem(
            requirement_ref=self._requirement_id, name=TEST_PACKAGE,
            type=RequirementType.PYTHON_PACKAGE,
            install_method=f"pip install {TEST_PACKAGE}",
        )
        variant = CouncilVariant(id="variant-1", name="variant-1", toolchain=(item,))
        return CouncilResult(
            id="council-system", project_id=self._project_id,
            variants=(variant,), recommendation="variant-1", council_complete=True,
        )


class _FakeReworkStage:
    """Stand-in for the LLM-backed Developer agent inside the
    Development/Testing/Rework stage - a separate LLM boundary from
    Discovery/Council, unrelated to execution-target authorization,
    which this test is not exercising."""

    def run(self, request):
        testing_result = DevelopmentTestingResult(
            development_result=None, test_changes={}, apply_result={},
            test_result=None,
            testing_stage_result=SimpleNamespace(status="accepted"),
            verification_result=None,
        )
        return ControlledReworkResult(initial_result=testing_result, rework_executed=False)


class TestSystemExecutionTargetSurvivesPathDrift:
    """SYSTEM: project/setup request -> real ProjectSetupApplicationService
    -> deterministic Discovery/Council/Rework fixtures only -> real
    Preflight -> real Materializer -> real persistence -> real reload
    -> real approval -> real capability authorization -> PATH drift ->
    real execution -> real verification -> real final workflow result.
    """

    def test_approved_target_executes_successfully_after_path_drift(self, tmp_path, monkeypatch):
        target_a = _build_isolated_toolchain(tmp_path, "toolchain-a")
        project_path = tmp_path / "project"
        project_path.mkdir()
        prior_path = os.environ.get("PATH", "")
        monkeypatch.setenv("PATH", f"{os.path.dirname(target_a)}:{prior_path}")

        requirement = Requirement(
            technical_identity=TEST_PACKAGE,
            id="req-system", name=TEST_PACKAGE,
            type=RequirementType.PYTHON_PACKAGE, purpose="test dependency",
            required=True, confidence=0.9,
        )
        project_id = "proj-system-test"

        from app.setup_execution_state import SetupExecutionStateStore

        workflow = DevelopmentWorkflow(
            discovery=_FakeDiscovery(requirement),
            validator=RequirementValidator,
            preflight=RequirementPreflight,
            executor=PythonPackageExecutor(),
            council=_FakeCouncil(requirement.id, project_id),
            materializer=ToolchainMaterializer(),
            controlled_rework_stage=_FakeReworkStage(),
            execution_state_store=SetupExecutionStateStore(tmp_path / "exec-state.json"),
        )
        content_store = ApprovedPlanContentStore(tmp_path / "approved-content.json")
        service = ProjectSetupApplicationService(
            development_workflow=workflow,
            workflow_manager=WorkflowManager(storage=str(tmp_path / "workflow_state.json")),
            technical_config=load_ai_config(AI_CONFIG_PATH),
            project_definition_store=ProjectDefinitionStore(path=str(tmp_path / "definitions.json")),
            approved_content_store=content_store,
        )
        plan_store = WorkflowPlanStore(tmp_path / "plans")

        # --- PLANNING: real service, real Preflight, real Materializer ---
        pending_result = service.plan_project_setup(project_id, str(project_path), "run-system")
        # CLAUDE-ARCH-S2-013C: real planning now stops at the productive
        # S2.4 boundary; explicitly accept the Chairman recommendation
        # (the only admissible candidate here) to resume towards a
        # SetupPlan -- this test is about execution-target path-drift
        # survival, not S2.4, so it resolves the pending selection
        # directly rather than exercising a Web/MCP adapter.
        plan_result = workflow.resolve_engineering_selection(
            pending_result.council_result, pending_result.preflight_result,
            pending_result.platform, project_id,
            human_selected_variant_id=pending_result.council_result.recommendation,
        )
        council_result = plan_result.council_result
        setup_plan = plan_result.setup_plan
        assert setup_plan.steps[0].target_executable == target_a

        # --- REAL persistence ---
        plan_store.save(setup_plan)
        plan_store.save_council_reference(
            project_id, setup_plan.id, council_result.id, council_result.recommendation,
        )

        # --- REAL reload + REAL approval ---
        loaded_plan = plan_store.load(project_id, setup_plan.id)
        approved_plan = self._approve(loaded_plan)
        # CLAUDE-E2E-003I-B: record_approved() is what approve_setup_plan()
        # itself calls at the real Human Approval moment -- simulated
        # explicitly here since this test approves directly via
        # SetupApproval.approve() (through the local _approve() helper)
        # rather than through that shared function.
        content_store.record_approved(approved_plan)
        plan_store.save(approved_plan)
        council_ref, chairman_ref = plan_store.load_council_reference(project_id, setup_plan.id)

        # --- PATH MUTATION: Target A's directory removed from PATH ---
        monkeypatch.setenv("PATH", prior_path)
        target_b = __import__("shutil").which("python") or sys.executable
        assert target_b != target_a, "test setup invalid: PATH mutation had no effect"

        # --- REAL execution through the real application-service boundary ---
        reloaded_for_exec = plan_store.load(project_id, setup_plan.id)
        result = service.execute_approved_setup_and_development(
            reloaded_for_exec, project_id, str(project_path), "Create hello world",
            engineering_council_ref=council_ref, chairman_approval_ref=chairman_ref,
        )

        setup_results = result.setup_execution_results
        if setup_results and not setup_results[0].success and _network_unavailable(setup_results[0]):
            pytest.skip(f"No network access for a real pip install: {setup_results[0].message}")

        assert len(setup_results) == 1
        assert setup_results[0].success is True
        assert setup_results[0].verification_passed is True
        assert result.controlled_rework_result.status == "accepted"

        # --- Independent real confirmation: Target A actually has the package ---
        check_a = subprocess.run(
            [target_a, "-c", f"import {TEST_PACKAGE}; print({TEST_PACKAGE}.__file__)"],
            capture_output=True, text=True, timeout=30,
        )
        assert check_a.returncode == 0
        assert "toolchain-a" in check_a.stdout

    @staticmethod
    def _approve(plan):
        from app.setup_approval import SetupApproval
        return SetupApproval.approve(plan)
