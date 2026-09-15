"""CLAUDE-E2E-003F PRODUCTIVE SYSTEM test.

Enters through the real, externally reachable Web/API HTTP boundary
(FastAPI TestClient against the actual `app` and its actual routes),
not a direct, hidden-argument ProjectSetupApplicationService call. This
is the "highest practical productive ADC application/service boundary"
requirement from CLAUDE-E2E-003E made concrete for CLAUDE-E2E-003F:
Part 8 there requires a real externally reachable adapter, not a
direct service call with test-supplied provenance.

Only the two genuinely LLM-dependent boundaries are replaced
(Discovery, Engineering Council) plus the separate Development/
Testing/Rework LLM boundary, matching the same, already-established
replacement pattern from tests/test_execution_target_authorization_system.py
(CLAUDE-E2E-003E). Everything else is real: the actual FastAPI routes
(/api/workflow/start, /api/state, /api/workflow/{id}/approval,
/api/workflow/{id}/execute), Session, WebSetupComponents,
ProjectSetupApplicationService, the new CLAUDE-E2E-003F shared
persist_setup_plan/approve_setup_plan/execute_approved_plan_from_store
functions, RequirementPreflight, ToolchainMaterializer,
WorkflowPlanStore (including the new council-reference persistence),
SetupApproval, PythonPackageExecutor's default runner, the real
execute_controlled/validate_request boundary, the real
DEFAULT_CAPABILITY_REGISTRY, a real subprocess pip install, and real
post-install verification.

Critically: this test never calls register_setup_step_targets directly
and never passes engineering_council_ref/chairman_approval_ref into
the application service itself. It only calls the same three HTTP
endpoints a real browser client would call
(start -> poll -> approval -> execute); if the productive wiring
introduced by CLAUDE-E2E-003F did not exist, this test would fail
exactly the way CLAUDE-E2E-003D proved the un-wired path fails.

Network dependency: a single real "pip install iniconfig" against an
isolated venv, the same tiny, already-pytest-transitive package used
throughout this task family's other real-integration tests. Skips
(does not fail) if genuinely no network access is available.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import venv
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.ai_config import load_ai_config
from app.controlled_rework_stage import ControlledReworkResult
from app.council_models import CouncilResult, CouncilVariant, ToolchainItem
from app.development_testing_stage import DevelopmentTestingResult
from app.dev_workflow import DevelopmentWorkflow
from app.project_context import ProjectDefinitionStore, ProjectRegistry
from app.python_package_executor import PythonPackageExecutor
from app.requirement_model import (
    DiscoveryResult, Requirement, RequirementActivation, RequirementType,
)
from app.requirement_preflight import RequirementPreflight
from app.requirement_validator import RequirementValidator
from app.setup_approval import SetupApproval
from app.toolchain_materializer import ToolchainMaterializer
from app.web_api import (
    WebSetupComponents, app, get_project_registry, get_web_setup_components,
    sessions,
)
from app.workflow_manager import WorkflowManager
from app.workflow_plan_store import WorkflowPlanStore

TEST_PACKAGE = "iniconfig"
AI_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "ai-dev-center.yml",
)


@pytest.fixture(autouse=True)
def clean_web_state():
    sessions.clear()
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def _build_isolated_toolchain(tmp_path, name):
    toolchain_dir = tmp_path / name
    venv.EnvBuilder(with_pip=True, clear=True).create(toolchain_dir)
    return str(toolchain_dir / "bin" / "python")


def _network_unavailable(text: str) -> bool:
    text = text.lower()
    return "temporary failure" in text or "network" in text or "resolve" in text


class _FakeDiscovery:
    def __init__(self, requirement: Requirement):
        self._requirement = requirement

    def discover(self, project_info, project_id, user_request=None):
        return DiscoveryResult(
            id="disc-web-system", source="fixture", project_id=project_id,
            requirements=(self._requirement,),
            activations=(
                RequirementActivation(self._requirement.id, True, True, "fixture"),
            ),
        )


class _FakeCouncil:
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
            id="council-web-system", project_id=self._project_id,
            variants=(variant,), recommendation="variant-1", council_complete=True,
        )


class _FakeReworkStage:
    def run(self, request):
        testing_result = DevelopmentTestingResult(
            development_result=None, test_changes={}, apply_result={},
            test_result=None,
            testing_stage_result=SimpleNamespace(status="accepted"),
            verification_result=None,
        )
        return ControlledReworkResult(initial_result=testing_result, rework_executed=False)


def _wait_for_plan(client, session_id):
    state = None
    for _ in range(200):
        state = client.get(f"/api/state/{session_id}").json()
        if state["plan_id"] or state["workflow_status"] == "failed":
            return state
        time.sleep(0.01)
    return state


def _wait_for_engineering_selection(client, session_id):
    """CLAUDE-ARCH-S2-013C: wait for the productive S2.4 pause."""
    state = None
    for _ in range(200):
        state = client.get(f"/api/state/{session_id}").json()
        if state["workflow_status"] in ("pending_engineering_selection", "failed"):
            return state
        time.sleep(0.01)
    return state


def test_web_http_boundary_executes_approved_target_after_path_drift(tmp_path, monkeypatch):
    target_a = _build_isolated_toolchain(tmp_path, "toolchain-a")
    project_path = tmp_path / "project"
    project_path.mkdir()
    prior_path = os.environ.get("PATH", "")
    monkeypatch.setenv("PATH", f"{os.path.dirname(target_a)}:{prior_path}")

    requirement = Requirement(
        technical_identity=TEST_PACKAGE,
        id="req-web-system", name=TEST_PACKAGE,
        type=RequirementType.PYTHON_PACKAGE, purpose="test dependency",
        required=True, confidence=0.9,
    )
    project_id = "proj-web-system"

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
    from app.project_setup_application import ProjectSetupApplicationService
    service = ProjectSetupApplicationService(
        development_workflow=workflow,
        workflow_manager=WorkflowManager(storage=str(tmp_path / "workflow_state.json")),
        technical_config=load_ai_config(AI_CONFIG_PATH),
        project_definition_store=ProjectDefinitionStore(path=str(tmp_path / "definitions.json")),
    )
    plan_store = WorkflowPlanStore(tmp_path / "plans")
    components = WebSetupComponents(service, plan_store, SetupApproval, workflow)
    app.dependency_overrides[get_web_setup_components] = lambda: components
    registry = ProjectRegistry(ProjectDefinitionStore(tmp_path / "project-registry.json"))
    app.dependency_overrides[get_project_registry] = lambda: registry

    client = TestClient(app)

    # --- Real HTTP boundary: start planning ---
    start = client.post("/api/workflow/start", json={
        "project_name": project_id,
        "project_directory": str(project_path),
        "task_description": "Create hello world",
    })
    assert start.status_code == 202
    session_id = start.json()["session_id"]

    state = _wait_for_engineering_selection(client, session_id)
    assert state["workflow_status"] == "pending_engineering_selection", state
    # CLAUDE-ARCH-S2-013C: run() stops at the productive S2.4 boundary;
    # explicitly accept the Chairman recommendation through the real
    # HTTP boundary to resume towards a SetupPlan.
    accept = client.post(
        f"/api/workflow/{session_id}/engineering-decision", json={"action": "accept"},
    )
    assert accept.status_code == 200, accept.json()

    state = _wait_for_plan(client, session_id)
    assert state["plan_id"], f"planning did not produce a plan: {state}"
    plan_id = state["plan_id"]

    # The plan's target_executable was resolved while Target A was on
    # PATH -- confirm the real, persisted plan actually pinned it.
    persisted_plan = plan_store.load(project_id, plan_id)
    assert persisted_plan.steps[0].target_executable == target_a
    assert plan_store.load_council_reference(project_id, plan_id) == (
        "council-web-system", "variant-1",
    )

    # --- PATH MUTATION: Target A's directory removed from PATH ---
    monkeypatch.setenv("PATH", prior_path)
    target_b = __import__("shutil").which("python") or sys.executable
    assert target_b != target_a, "test setup invalid: PATH mutation had no effect"
    # Baseline snapshot: target_b (the real, ambient interpreter used to
    # run this test suite) may already have TEST_PACKAGE importable as a
    # transitive dependency of the test harness itself (e.g. pytest
    # depends on iniconfig) -- unrelated pre-existing environment state,
    # not something this operation could ever have caused. Compare
    # against this baseline rather than asserting absolute absence.
    check_b_before = subprocess.run(
        [target_b, "-c", f"import {TEST_PACKAGE}"],
        capture_output=True, text=True, timeout=30,
    )

    # --- Real HTTP boundary: approve ---
    approval = client.post(f"/api/workflow/{session_id}/approval")
    assert approval.status_code == 200
    assert approval.json() == {"plan_id": plan_id, "status": "approved"}

    # --- Real HTTP boundary: execute ---
    execution = client.post(f"/api/workflow/{session_id}/execute")
    body = execution.json()

    if execution.status_code != 200 and _network_unavailable(str(body)):
        pytest.skip(f"No network access for a real pip install: {body}")

    assert execution.status_code == 200, body
    assert body["development_status"] == "accepted"
    assert len(body["results"]) == 1
    assert body["results"][0]["success"] is True
    assert body["results"][0]["verification_passed"] is True

    # --- Independent real confirmation: Target A actually has the package ---
    check_a = subprocess.run(
        [target_a, "-c", f"import {TEST_PACKAGE}; print({TEST_PACKAGE}.__file__)"],
        capture_output=True, text=True, timeout=30,
    )
    assert check_a.returncode == 0
    assert "toolchain-a" in check_a.stdout

    # --- Target B was never touched by this operation ---
    check_b = subprocess.run(
        [target_b, "-c", f"import {TEST_PACKAGE}"],
        capture_output=True, text=True, timeout=30,
    )
    assert check_b.returncode == check_b_before.returncode, "Target B must remain untouched"
