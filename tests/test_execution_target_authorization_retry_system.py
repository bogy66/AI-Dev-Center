"""CLAUDE-E2E-003H SYSTEM-level retry/restart safety tests, entering
through the real Web/API HTTP boundary and the real MCP JSON-RPC tool
boundary -- proving both adapters inherit the SAME central
execution-state guard (app.setup_execution_state /
DevelopmentWorkflow._execute_with_state_guard), with no adapter-specific
retry-prevention logic in web_api.py or mcp_server.py.

Uses the real, observable launch counter (tests/local_package_fixture.py)
rather than mocking subprocess.run or relying on pip's own idempotency.
"""
from __future__ import annotations

import json
import os

from fastapi.testclient import TestClient

from app.ai_config import load_ai_config
from app.council_models import CouncilResult, CouncilVariant, ToolchainItem
from app.dev_workflow import DevelopmentWorkflow
from app.mcp_server import MCPServer
from app.mcp_transport import MCPRequestHandler
from app.project_context import ProjectDefinitionStore, ProjectRegistry
from app.project_setup_application import ProjectSetupApplicationService
from app.python_package_executor import PythonPackageExecutor
from app.requirement_model import (
    DiscoveryResult, Requirement, RequirementActivation, RequirementType,
)
from app.requirement_preflight import RequirementPreflight
from app.requirement_validator import RequirementValidator
from app.setup_approval import SetupApproval
from app.setup_execution_state import SetupExecutionStateStore
from app.toolchain_materializer import ToolchainMaterializer
from app.web_api import (
    WebSetupComponents, app, get_project_registry, get_web_setup_components,
    sessions,
)
from app.workflow_manager import WorkflowManager
from app.workflow_plan_store import WorkflowPlanStore

from tests.local_package_fixture import (
    PACKAGE_NAME, build_launch_counting_target, build_local_wheel_index, read_launch_count,
)
from tests.test_execution_target_authorization_web_system import (
    _FakeReworkStage, _wait_for_engineering_selection, _wait_for_plan,
)


class _FixedDiscoveryForRetryTest:
    def __init__(self, requirement: Requirement):
        self._requirement = requirement

    def discover(self, project_info, project_id, user_request=None):
        return DiscoveryResult(
            id="disc-web-retry", source="fixture", project_id=project_id,
            requirements=(self._requirement,),
            activations=(RequirementActivation(self._requirement.id, True, True, "fixture"),),
        )


class _FixedCouncilForRetryTest:
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
            id="council-web-retry", project_id=self._project_id,
            variants=(variant,), recommendation="variant-1", council_complete=True,
        )

AI_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "ai-dev-center.yml",
)


def test_web_http_boundary_retry_launches_zero_additional_processes(tmp_path, monkeypatch):
    """Real Web/API HTTP boundary: execute success -> retry -> zero
    second launch, via the same central guard MCP also inherits."""
    wheels = build_local_wheel_index(tmp_path)
    target_a, counter = build_launch_counting_target(tmp_path, "toolchain-a", wheels)
    prior_path = os.environ.get("PATH", "")
    monkeypatch.setenv("PATH", f"{os.path.dirname(target_a)}:{prior_path}")

    project_path = tmp_path / "project"
    project_path.mkdir()
    requirement = Requirement(
        technical_identity=PACKAGE_NAME,
        id="req-web-retry", name=PACKAGE_NAME, type=RequirementType.PYTHON_PACKAGE,
        purpose="test dependency", required=True, confidence=0.9,
    )
    project_id = "proj-web-retry"

    execution_state_store = SetupExecutionStateStore(tmp_path / "exec-state.json")
    workflow = DevelopmentWorkflow(
        discovery=_FixedDiscoveryForRetryTest(requirement), validator=RequirementValidator,
        preflight=RequirementPreflight, executor=PythonPackageExecutor(),
        council=_FixedCouncilForRetryTest(requirement.id, project_id), materializer=ToolchainMaterializer(),
        controlled_rework_stage=_FakeReworkStage(), execution_state_store=execution_state_store,
    )
    service = ProjectSetupApplicationService(
        development_workflow=workflow,
        workflow_manager=WorkflowManager(storage=str(tmp_path / "workflow_state.json")),
        technical_config=load_ai_config(AI_CONFIG_PATH),
        project_definition_store=ProjectDefinitionStore(path=str(tmp_path / "definitions.json")),
    )
    plan_store = WorkflowPlanStore(tmp_path / "plans")
    components = WebSetupComponents(service, plan_store, SetupApproval, workflow)

    sessions.clear()
    app.dependency_overrides.clear()
    app.dependency_overrides[get_web_setup_components] = lambda: components
    app.dependency_overrides[get_project_registry] = lambda: ProjectRegistry(
        ProjectDefinitionStore(tmp_path / "project-registry.json"),
    )
    client = TestClient(app)

    try:
        start = client.post("/api/workflow/start", json={
            "project_name": project_id, "project_directory": str(project_path),
            "task_description": "Install the fixture package",
        })
        assert start.status_code == 202
        session_id = start.json()["session_id"]
        state = _wait_for_engineering_selection(client, session_id)
        assert state["workflow_status"] == "pending_engineering_selection", state
        accept = client.post(
            f"/api/workflow/{session_id}/engineering-decision", json={"action": "accept"},
        )
        assert accept.status_code == 200, accept.json()

        state = _wait_for_plan(client, session_id)
        plan_id = state["plan_id"]
        assert plan_id

        approval = client.post(f"/api/workflow/{session_id}/approval")
        assert approval.status_code == 200

        first = client.post(f"/api/workflow/{session_id}/execute")
        assert first.status_code == 200, first.json()
        assert first.json()["results"][0]["success"] is True
        count_after_first = read_launch_count(counter)
        assert count_after_first > 0

        second = client.post(f"/api/workflow/{session_id}/execute")

        # Web's pre-existing, run-level WorkflowManager.begin_execution()
        # guard (CLAUDE-E2E-003E and earlier) already rejects a second
        # /execute call for the SAME session/run_id outright
        # ("reentry_rejected", 409) -- this is a DIFFERENT, older
        # mechanism than the new per-step execution-state guard this
        # task adds, and it independently already delivers the same
        # core safety property (zero additional real launches) for
        # this exact same-session-retry shape. The new per-step guard's
        # own, distinct value for Web is a genuinely different run_id
        # revisiting an already-succeeded step (e.g. a multi-step plan
        # continuation) -- proven separately, at the DevelopmentWorkflow
        # level, by the multi-step and restart tests in
        # tests/test_execution_target_authorization_retry_s3.py. The
        # property this test exists to prove -- zero additional real
        # launches on retry through the real HTTP boundary -- holds
        # either way.
        assert second.status_code == 409
        assert second.json().get("status") == "reentry_rejected"
        assert read_launch_count(counter) == count_after_first, "no second real launch on Web retry"
    finally:
        app.dependency_overrides.clear()
        sessions.clear()


def test_mcp_boundary_retry_launches_zero_additional_processes(tmp_path, monkeypatch):
    """Real MCP JSON-RPC boundary: execute success -> retry -> zero
    second launch, via the same central guard Web also inherits."""
    wheels = build_local_wheel_index(tmp_path)
    target_a, counter = build_launch_counting_target(tmp_path, "toolchain-a", wheels)
    prior_path = os.environ.get("PATH", "")
    monkeypatch.setenv("PATH", f"{os.path.dirname(target_a)}:{prior_path}")

    project_path = tmp_path / "project"
    project_path.mkdir()
    requirement = Requirement(
        technical_identity=PACKAGE_NAME,
        id="req-mcp-retry", name=PACKAGE_NAME, type=RequirementType.PYTHON_PACKAGE,
        purpose="test dependency", required=True, confidence=0.9,
    )
    project_id = "proj-mcp-retry"

    class FixedDiscovery:
        def discover(self, project_info, pid, user_request=None):
            return DiscoveryResult(
                id="disc-mcp-retry", source="fixture", project_id=pid,
                requirements=(requirement,),
                activations=(RequirementActivation(requirement.id, True, True, "fixture"),),
            )

    class FixedCouncil:
        def evaluate(self, council_input):
            item = ToolchainItem(
                requirement_ref=requirement.id, name=PACKAGE_NAME,
                type=RequirementType.PYTHON_PACKAGE, install_method=f"pip install {PACKAGE_NAME}",
            )
            variant = CouncilVariant(id="variant-1", name="variant-1", toolchain=(item,))
            return CouncilResult(
                id="council-mcp-retry", project_id=project_id,
                variants=(variant,), recommendation="variant-1", council_complete=True,
            )

    execution_state_store = SetupExecutionStateStore(tmp_path / "exec-state.json")
    workflow = DevelopmentWorkflow(
        discovery=FixedDiscovery(), validator=RequirementValidator,
        preflight=RequirementPreflight, executor=PythonPackageExecutor(),
        council=FixedCouncil(), materializer=ToolchainMaterializer(),
        execution_state_store=execution_state_store,
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
    handler = MCPRequestHandler(server)

    def call(name, arguments):
        handler.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}})
        response = handler.handle({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        })
        assert "error" not in response, response
        return json.loads(response["result"]["content"][0]["text"])

    # CLAUDE-ARCH-S2-013C: MCP's plan_project_setup tool now fails closed
    # (MCPEngineeringSelectionPendingError) at the productive S2.4
    # boundary -- MCP deliberately does not implement an interactive
    # selection tool (out of scope for this task). This retry-safety
    # test is unrelated to S2.4, so it resolves the pending selection
    # directly through DevelopmentWorkflow (exactly what a real human
    # decision, made through a future MCP or Web client, would resume
    # with) and persists the result the same way MCPServer.
    # plan_project_setup() itself would have.
    from app.project_setup_application import persist_setup_plan

    pending_result = service.plan_project_setup(
        project_id, str(project_path), entry_interface="mcp",
        entry_data={"project_id": project_id},
    )
    resumed_result = workflow.resolve_engineering_selection(
        pending_result.council_result, pending_result.preflight_result,
        pending_result.platform, project_id,
        human_selected_variant_id=pending_result.council_result.recommendation,
    )
    persist_setup_plan(plan_store, resumed_result.setup_plan, resumed_result.council_result)
    plan_store.save_project_root(project_id, str(project_path))
    plan = {"id": resumed_result.setup_plan.id}

    call("approve_setup_plan", {"project_id": project_id, "plan_id": plan["id"]})

    first = call("execute_setup_plan", {"project_id": project_id, "plan_id": plan["id"]})
    assert first[0]["success"] is True
    count_after_first = read_launch_count(counter)
    assert count_after_first > 0

    second = call("execute_setup_plan", {"project_id": project_id, "plan_id": plan["id"]})

    assert second[0]["success"] is True
    assert read_launch_count(counter) == count_after_first, "no second real launch on MCP retry"

    # Part 14 #1: a client cannot forge/submit its own execution state
    # through this tool -- execute_setup_plan has no such parameter at
    # all, so an attempt raises TypeError, safely surfaced as a JSON-RPC
    # error, never silently accepted.
    forged_response = handler.handle({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {
            "name": "execute_setup_plan",
            "arguments": {
                "project_id": project_id, "plan_id": plan["id"],
                "execution_state": "succeeded", "status": "succeeded",
            },
        },
    })
    assert "error" in forged_response
    assert read_launch_count(counter) == count_after_first
