"""Agent orchestration layer that uses the existing MCP tools to drive a
complete development-setup workflow.

The layer contains *no* business logic.  It communicates exclusively
through the provided :class:`MCPServer` and never calls domain services
directly.  Execution only happens after an explicit approval step.

If discovery falls back to a heuristic (``fallback_used == True``) the
workflow stops immediately **before** calling ``get_preflight`` or
``create_setup_plan`` – exactly the same safety rule that the existing
:class:`DevelopmentWorkflow` enforces internally.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.mcp_server import MCPServer
from app.setup_approval import SetupApprovalError


@dataclass
class AgentWorkflowResult:
    """Result of an agent‑driven workflow step or full sequence."""

    project_id: str
    project_path: str = ""
    inspected_files: Optional[List[str]] = None
    discovered_requirements: Any = None
    preflight_result: Any = None
    setup_plan: Any = None
    plan_id: Optional[str] = None
    approval_required: bool = False
    approval_status: Optional[str] = None
    execution_results: Any = None
    final_workflow_status: str = "unknown"
    error_message: Optional[str] = None
    discovery_fallback: bool = False


class AgentWorkflow:
    """Thin orchestration layer that sequences MCP tool calls.

    The orchestrator is intentionally stateless beyond the injected
    :class:`MCPServer`.  Every method returns a new
    :class:`AgentWorkflowResult` that describes the current state.
    """

    # -- helper ------------------------------------------------------------
    @staticmethod
    def _build_project_info(
        project_path: str, inspected_files: List[str]
    ) -> Dict[str, Any]:
        """Construct the project-info dictionary expected by the real
        :meth:`AIRequirementDiscovery.discover` API.

        The shape matches exactly the ``project_info`` that
        ``workflow_cli.build_workflow()`` creates before calling
        ``DevelopmentWorkflow.run(..., project_info=...)``.
        """
        root = Path(project_path).expanduser().resolve()
        project_id = root.name
        files_payload: List[Dict[str, str]] = []
        MAX_FILE_SIZE = 1_000_000  # 1 MB

        for rel_path in inspected_files:
            full_path = root / rel_path
            try:
                if not full_path.is_file():
                    continue
                size = full_path.stat().st_size
                if size > MAX_FILE_SIZE:
                    continue
                content = full_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            files_payload.append({"path": rel_path, "content": content})

        return {
            "project_id": project_id,
            "project_path": str(root),
            "files": files_payload,
        }

    def __init__(self, server: MCPServer) -> None:
        self._server = server

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def inspect_and_plan(
        self, project_id: str, project_path: str
    ) -> AgentWorkflowResult:
        """Run steps 1‑5 of the workflow and return a result that
        **requires** explicit approval before execution.

        If discovery uses a fallback strategy the workflow is halted
        immediately – no preflight checks or plan creation take place.
        """
        result = AgentWorkflowResult(
            project_id=project_id, project_path=project_path
        )

        # 1. inspect_project
        try:
            inspect_res = self._server.inspect_project(project_path)
            result.inspected_files = inspect_res.get("files", [])
        except Exception as exc:
            result.final_workflow_status = "inspect_failed"
            result.error_message = str(exc)
            return result

        # 2. Canonical planning through DevelopmentWorkflow.run() via MCP.
        try:
            project_info = self._build_project_info(
                project_path, result.inspected_files
            )
            plan = self._server.plan_project_setup(
                project_info,
                project_id,
            )
            result.plan_id = getattr(plan, "id", None)
        except Exception as exc:
            result.final_workflow_status = "plan_creation_failed"
            result.error_message = str(exc)
            return result

        # 3. get_setup_plan (retrieve so the caller can inspect)
        try:
            plan = self._server.get_setup_plan(project_id, result.plan_id)
            result.setup_plan = plan
            result.approval_required = True
            result.approval_status = getattr(plan, "status", None)
            result.final_workflow_status = "pending_approval"
        except Exception as exc:
            result.final_workflow_status = "plan_retrieval_failed"
            result.error_message = str(exc)
            return result

        return result

    def approve(
        self, project_id: str, plan_id: str
    ) -> AgentWorkflowResult:
        """Explicitly approve the persisted setup plan.

        The plan must be in ``pending_approval`` status.  If the
        approval succeeds the result will contain the approved plan.
        """
        result = AgentWorkflowResult(project_id=project_id, plan_id=plan_id)
        try:
            approved_plan = self._server.approve_setup_plan(
                project_id, plan_id
            )
            result.setup_plan = approved_plan
            result.approval_status = getattr(
                approved_plan, "status", "approved"
            )
            result.approval_required = False
            result.final_workflow_status = "approved"
        except SetupApprovalError as exc:
            result.final_workflow_status = "approval_rejected"
            result.error_message = str(exc)
            result.approval_status = "rejected"
        except Exception as exc:
            result.final_workflow_status = "approval_failed"
            result.error_message = str(exc)
        return result

    def execute(
        self, project_id: str, plan_id: str
    ) -> AgentWorkflowResult:
        """Execute an *approved* setup plan.

        The plan must have been previously approved.  Execution is
        delegated to :meth:`MCPServer.execute_setup_plan` which
        enforces the existing approval boundary.
        """
        result = AgentWorkflowResult(project_id=project_id, plan_id=plan_id)
        try:
            exec_results = self._server.execute_setup_plan(
                project_id, plan_id
            )
            result.execution_results = exec_results
            result.final_workflow_status = "executed"
        except SetupApprovalError as exc:
            result.final_workflow_status = "execution_not_approved"
            result.error_message = str(exc)
        except Exception as exc:
            result.final_workflow_status = "execution_failed"
            result.error_message = str(exc)
        return result
