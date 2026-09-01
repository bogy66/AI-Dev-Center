import os
from unittest.mock import Mock

import pytest

from app.agent_workflow import AgentWorkflow, AgentWorkflowResult
from app.mcp_server import MCPServer
from app.setup_approval import SetupApprovalError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_mcp_server(**overrides) -> MCPServer:
    return MCPServer(
        project_scanner=overrides.get("project_scanner", Mock()),
        discovery=overrides.get("discovery", Mock()),
        preflight=overrides.get("preflight", Mock()),
        planner=overrides.get("planner", Mock()),
        plan_store=overrides.get("plan_store", Mock()),
        approval=overrides.get("approval", Mock()),
        development_workflow=overrides.get("development_workflow", Mock()),
    )


def make_workflow(**overrides) -> AgentWorkflow:
    return AgentWorkflow(make_mcp_server(**overrides))


# ---------------------------------------------------------------------------
# Tests for _build_project_info (unit tests that can be run without a real
# MCPServer)
# ---------------------------------------------------------------------------

class TestBuildProjectInfo:
    def test_reads_files_and_includes_content(self, tmp_path):
        file = tmp_path / "hello.py"
        file.write_text("print('hello')")
        inspected = ["hello.py"]
        info = AgentWorkflow._build_project_info(str(tmp_path), inspected)
        assert info["project_id"] == tmp_path.name
        assert info["project_path"] == str(tmp_path)
        assert len(info["files"]) == 1
        assert info["files"][0]["path"] == "hello.py"
        assert info["files"][0]["content"] == "print('hello')"

    def test_skips_large_files(self, tmp_path):
        file = tmp_path / "big.txt"
        file.write_text("a" * 1_500_000)
        inspected = ["big.txt"]
        info = AgentWorkflow._build_project_info(str(tmp_path), inspected)
        assert info["files"] == []

    def test_skips_binary_files(self, tmp_path):
        file = tmp_path / "image.png"
        file.write_bytes(b"\x89PNG\r\n\x1a\n")
        inspected = ["image.png"]
        info = AgentWorkflow._build_project_info(str(tmp_path), inspected)
        assert info["files"] == []


# ---------------------------------------------------------------------------
# inspect_and_plan
# ---------------------------------------------------------------------------

class TestInspectAndPlan:
    def test_success(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        (project / "a.py").write_text("content")
        wf = make_workflow()
        wf._server._project_scanner.scan.return_value = ["a.py"]
        plan_mock = Mock(id="plan-1", status="pending_approval")
        wf._server._development_workflow.run.return_value = Mock(setup_plan=plan_mock)
        wf._server._plan_store.load.return_value = plan_mock
        result = wf.inspect_and_plan("proj", str(project))
        assert result.plan_id == "plan-1"
        assert result.setup_plan is plan_mock
        assert result.final_workflow_status == "pending_approval"

    def test_uses_canonical_mcp_planning_with_project_info(self, tmp_path):
        project = tmp_path / "dummy_project"
        project.mkdir()
        (project / "a.py").write_text("hello a")
        wf = make_workflow()
        wf._server._project_scanner.scan.return_value = ["a.py"]
        plan = Mock(id="plan-1", status="pending_approval")
        wf._server._development_workflow.run.return_value = Mock(setup_plan=plan)
        wf._server._plan_store.load.return_value = plan
        wf.inspect_and_plan("dummy_project", str(project))
        args, _ = wf._server._development_workflow.run.call_args
        project_info = args[0]
        assert project_info["files"] == [{"path": "a.py", "content": "hello a"}]
        assert args[1] == "dummy_project"
        wf._server._planner.plan.assert_not_called()

    def test_inspect_failure(self):
        wf = make_workflow()
        wf._server._project_scanner.scan.side_effect = RuntimeError("scan error")

        result = wf.inspect_and_plan("proj", "/tmp/proj")

        assert result.final_workflow_status == "inspect_failed"
        assert "scan error" in result.error_message

    def test_canonical_planning_failure(self):
        wf = make_workflow()
        wf._server._project_scanner.scan.return_value = []
        wf._server._development_workflow.run.side_effect = RuntimeError("disc error")
        result = wf.inspect_and_plan("proj", "/tmp/proj")
        assert result.final_workflow_status == "plan_creation_failed"
        assert "disc error" in result.error_message

    def test_plan_retrieval_failure(self):
        wf = make_workflow()
        wf._server._project_scanner.scan.return_value = []
        wf._server._discovery.discover.return_value = Mock(fallback_used=False)
        wf._server._preflight.check.return_value = Mock()
        plan_mock = Mock(id="p3", status="pending_approval")
        wf._server._planner.plan.return_value = plan_mock
        wf._server._plan_store.save.return_value = (
            "/tmp/.workflow-plans/proj/p3.json"
        )
        wf._server._plan_store.load.side_effect = RuntimeError("load error")

        result = wf.inspect_and_plan("proj", "/tmp/proj")

        assert result.final_workflow_status == "plan_retrieval_failed"


# ---------------------------------------------------------------------------
# approve
# ---------------------------------------------------------------------------

class TestApprove:
    def test_approval_success(self):
        wf = make_workflow()
        approved_plan = Mock(status="approved")
        wf._server._plan_store.load.return_value = Mock(
            status="pending_approval"
        )
        wf._server._approval.approve.return_value = approved_plan

        result = wf.approve("proj", "plan-1")

        assert result.final_workflow_status == "approved"
        assert result.approval_status == "approved"
        assert result.setup_plan is approved_plan

    def test_approval_rejected(self):
        wf = make_workflow()
        wf._server._plan_store.load.return_value = Mock(
            status="pending_approval"
        )
        wf._server._approval.approve.side_effect = SetupApprovalError(
            "Cannot approve plan with status 'approved'"
        )

        result = wf.approve("proj", "plan-1")

        assert result.final_workflow_status == "approval_rejected"
        assert "Cannot approve" in result.error_message

    def test_approval_failure(self):
        wf = make_workflow()
        wf._server._plan_store.load.return_value = Mock(
            status="pending_approval"
        )
        wf._server._approval.approve.side_effect = RuntimeError("boom")

        result = wf.approve("proj", "plan-1")

        assert result.final_workflow_status == "approval_failed"


# ---------------------------------------------------------------------------
# execute
# ---------------------------------------------------------------------------

class TestExecute:
    def test_execution_success(self):
        wf = make_workflow()
        exec_result = object()
        plan = Mock(status="approved")
        wf._server._plan_store.load.return_value = plan
        wf._server._development_workflow.execute_approved.return_value = (
            exec_result
        )

        result = wf.execute("proj", "plan-1")

        assert result.final_workflow_status == "executed"
        assert result.execution_results is exec_result

    def test_execution_not_approved(self):
        wf = make_workflow()
        plan = Mock(status="pending_approval")
        wf._server._plan_store.load.return_value = plan
        # execute_setup_plan will raise SetupApprovalError
        result = wf.execute("proj", "plan-1")

        assert result.final_workflow_status == "execution_not_approved"
        assert "not approved" in result.error_message

    def test_execution_failure_other(self):
        wf = make_workflow()
        plan = Mock(status="approved")
        wf._server._plan_store.load.return_value = plan
        wf._server._development_workflow.execute_approved.side_effect = (
            RuntimeError("exec error")
        )

        result = wf.execute("proj", "plan-1")

        assert result.final_workflow_status == "execution_failed"
        assert "exec error" in result.error_message
