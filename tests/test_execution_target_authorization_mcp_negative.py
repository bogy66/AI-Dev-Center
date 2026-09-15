"""CLAUDE-E2E-003G Part 8: negative productive cases for the MCP
planning/approval/execution central-path parity, driven through the
real MCP JSON-RPC tool boundary (never a direct, hidden-argument
service call).
"""
from __future__ import annotations

import os
import subprocess

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
from tests.test_execution_target_authorization_mcp import (
    _call, _FixedDiscovery, _plan_via_mcp_with_explicit_selection,
)

AI_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "ai-dev-center.yml",
)


class _CompleteCouncil:
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
            id="council-neg", project_id=self._project_id,
            variants=(variant,), recommendation="variant-1", council_complete=True,
        )


class _IncompleteCouncil:
    """A Council run that never reached a Chairman recommendation --
    persist_setup_plan must not fabricate a council reference for it."""

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
            id="council-neg-incomplete", project_id=self._project_id,
            variants=(variant,), recommendation=None, council_complete=False,
        )


def _build_server(tmp_path, requirement, project_id, council, *, with_service=True):
    from app.setup_execution_state import SetupExecutionStateStore

    workflow = DevelopmentWorkflow(
        discovery=_FixedDiscovery(requirement), validator=RequirementValidator,
        preflight=RequirementPreflight, executor=PythonPackageExecutor(),
        council=council, materializer=ToolchainMaterializer(),
        execution_state_store=SetupExecutionStateStore(tmp_path / "exec-state.json"),
    )
    service = None
    if with_service:
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


def _raw_call(handler, name, arguments):
    handler.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}})
    return handler.handle({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    })


def _requirement(req_id="req-neg"):
    return Requirement(
        technical_identity=PACKAGE_NAME,
        id=req_id, name=PACKAGE_NAME, type=RequirementType.PYTHON_PACKAGE,
        purpose="test dependency", required=True, confidence=0.9,
    )


class TestMissingSetupApprovalBlocksExecution:
    def test_execute_setup_plan_rejects_a_pending_approval_plan(self, tmp_path, monkeypatch):
        target_a = build_isolated_toolchain(tmp_path, "toolchain-a", build_local_wheel_index(tmp_path))
        project_path = tmp_path / "project"
        project_path.mkdir()
        monkeypatch.setenv("PATH", f"{os.path.dirname(target_a)}:{os.environ.get('PATH', '')}")
        project_id = "proj-neg-approval"
        handler, plan_store, service, workflow = _build_server(
            tmp_path, _requirement(), project_id, _CompleteCouncil("req-neg", project_id),
        )
        plan = _plan_via_mcp_with_explicit_selection(
            handler, service, workflow, plan_store, project_id, str(project_path),
        )

        response = _raw_call(handler, "execute_setup_plan", {
            "project_id": project_id, "plan_id": plan["id"],
        })

        assert "error" in response
        assert "not approved" in response["error"]["message"]


class TestMissingCouncilProvenanceFailsClosedUnderDrift:
    def test_incomplete_council_result_blocks_planning_before_any_plan_is_persisted(
        self, tmp_path, monkeypatch,
    ):
        """An incomplete Council run (no Chairman recommendation) fails
        closed even earlier than "no pinning": the central
        ProjectSetupApplicationService.plan_project_setup() itself
        blocks planning outright, so no plan -- and therefore no
        council reference, no approval, no execution -- can ever exist
        for it. There is no persisted-but-unprotected intermediate
        state to drift-attack."""
        target_a = build_isolated_toolchain(tmp_path, "toolchain-a", build_local_wheel_index(tmp_path))
        project_path = tmp_path / "project"
        project_path.mkdir()
        monkeypatch.setenv("PATH", f"{os.path.dirname(target_a)}:{os.environ.get('PATH', '')}")
        project_id = "proj-neg-noprov"
        handler, plan_store, service, workflow = _build_server(
            tmp_path, _requirement(), project_id, _IncompleteCouncil("req-neg", project_id),
        )

        response = _raw_call(handler, "plan_project_setup", {
            "project_id": project_id, "project_root": str(project_path),
        })

        assert "error" in response
        # No plan was ever persisted for this blocked planning attempt.
        with pytest.raises(Exception):
            plan_store.load(project_id, f"plan-{project_id}")


class TestWrongProjectScopeFailsClosed:
    def test_execute_setup_plan_with_wrong_project_id_cannot_find_the_plan(self, tmp_path, monkeypatch):
        target_a = build_isolated_toolchain(tmp_path, "toolchain-a", build_local_wheel_index(tmp_path))
        project_path = tmp_path / "project"
        project_path.mkdir()
        monkeypatch.setenv("PATH", f"{os.path.dirname(target_a)}:{os.environ.get('PATH', '')}")
        project_id = "proj-neg-scope-a"
        handler, plan_store, service, workflow = _build_server(
            tmp_path, _requirement(), project_id, _CompleteCouncil("req-neg", project_id),
        )
        plan = _plan_via_mcp_with_explicit_selection(
            handler, service, workflow, plan_store, project_id, str(project_path),
        )
        _call(handler, "approve_setup_plan", {"project_id": project_id, "plan_id": plan["id"]})

        response = _raw_call(handler, "execute_setup_plan", {
            "project_id": "proj-neg-scope-b", "plan_id": plan["id"],
        })

        assert "error" in response


class TestClientSuppliedProvenanceIsRejected:
    def test_execute_setup_plan_rejects_unexpected_provenance_arguments(self, tmp_path, monkeypatch):
        target_a = build_isolated_toolchain(tmp_path, "toolchain-a", build_local_wheel_index(tmp_path))
        project_path = tmp_path / "project"
        project_path.mkdir()
        monkeypatch.setenv("PATH", f"{os.path.dirname(target_a)}:{os.environ.get('PATH', '')}")
        project_id = "proj-neg-trust"
        handler, plan_store, service, workflow = _build_server(
            tmp_path, _requirement(), project_id, _CompleteCouncil("req-neg", project_id),
        )
        plan = _plan_via_mcp_with_explicit_selection(
            handler, service, workflow, plan_store, project_id, str(project_path),
        )
        _call(handler, "approve_setup_plan", {"project_id": project_id, "plan_id": plan["id"]})

        response = _raw_call(handler, "execute_setup_plan", {
            "project_id": project_id, "plan_id": plan["id"],
            "engineering_council_ref": "attacker-supplied",
            "chairman_approval_ref": "attacker-supplied",
            "target_executable": "/attacker/controlled/python",
        })

        assert "error" in response, (
            "execute_setup_plan has no parameter for any of these "
            "values -- an unexpected keyword argument must fail closed, "
            "never be silently accepted as trusted provenance"
        )


class TestMissingCentralServiceFailsClosed:
    def test_all_three_productive_tools_fail_closed_without_a_service(self, tmp_path):
        handler, plan_store, service, workflow = _build_server(
            tmp_path, _requirement(), "proj-neg-noservice", _CompleteCouncil("req-neg", "proj-neg-noservice"),
            with_service=False,
        )
        project_path = tmp_path / "project"
        project_path.mkdir()

        plan_response = _raw_call(handler, "plan_project_setup", {
            "project_id": "proj-neg-noservice", "project_root": str(project_path),
        })
        assert "error" in plan_response

        approve_response = _raw_call(handler, "approve_setup_plan", {
            "project_id": "proj-neg-noservice", "plan_id": "plan-x",
        })
        assert "error" in approve_response

        execute_response = _raw_call(handler, "execute_setup_plan", {
            "project_id": "proj-neg-noservice", "plan_id": "plan-x",
        })
        assert "error" in execute_response


class TestStaleOrMissingPlanIdentityFailsClosed:
    def test_execute_setup_plan_with_a_plan_id_that_was_never_saved(self, tmp_path):
        handler, plan_store, service, workflow = _build_server(
            tmp_path, _requirement(), "proj-neg-stale", _CompleteCouncil("req-neg", "proj-neg-stale"),
        )

        response = _raw_call(handler, "execute_setup_plan", {
            "project_id": "proj-neg-stale", "plan_id": "plan-never-existed",
        })

        assert "error" in response


class TestRetryDoesNotDuplicateOrCorruptExecution:
    def test_executing_an_already_executed_plan_again_does_not_raise(self, tmp_path, monkeypatch):
        target_a = build_isolated_toolchain(tmp_path, "toolchain-a", build_local_wheel_index(tmp_path))
        project_path = tmp_path / "project"
        project_path.mkdir()
        monkeypatch.setenv("PATH", f"{os.path.dirname(target_a)}:{os.environ.get('PATH', '')}")
        project_id = "proj-neg-retry"
        handler, plan_store, service, workflow = _build_server(
            tmp_path, _requirement(), project_id, _CompleteCouncil("req-neg", project_id),
        )
        plan = _plan_via_mcp_with_explicit_selection(
            handler, service, workflow, plan_store, project_id, str(project_path),
        )
        _call(handler, "approve_setup_plan", {"project_id": project_id, "plan_id": plan["id"]})

        first = _call(handler, "execute_setup_plan", {"project_id": project_id, "plan_id": plan["id"]})
        assert first[0]["success"] is True

        # A second execute_setup_plan call for the same plan must not
        # raise due to a "capability already registered" conflict (the
        # re-registration is for the identical target/scope/provenance)
        # and pip installing an already-satisfied package is itself a
        # real, idempotent no-op -- not a silent double-mutation.
        second = _call(handler, "execute_setup_plan", {"project_id": project_id, "plan_id": plan["id"]})
        assert second[0]["success"] is True

        check_a = subprocess.run(
            [target_a, "-c", f"import {PACKAGE_IMPORT_NAME}"],
            capture_output=True, text=True, timeout=30,
        )
        assert check_a.returncode == 0
