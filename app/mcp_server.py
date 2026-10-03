"""Thin MCP server that exposes existing AI Dev Center workflow tools.

The server contains no business logic.  Every tool delegates to an existing
component from the surrounding application.  This module only adapts those
components into callable tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.project_setup_application import (
    approve_setup_plan as _approve_setup_plan_centrally,
    execute_approved_setup_from_store as _execute_approved_setup_from_store,
    persist_setup_plan as _persist_setup_plan,
)
from app.setup_approval import SetupApprovalError


class MCPEngineeringSelectionPendingError(RuntimeError):
    """Raised when planning stops at the productive S2.4 Human Engineering
    Authority boundary (CLAUDE-ARCH-S2-013C) -- at least one admissible
    engineering candidate exists, but no SetupPlan can be materialized
    until an explicit human engineering selection is made. This MCP
    adapter does not (yet) implement an interactive selection tool; it
    fails closed with this safe, structured error rather than crashing on
    a missing SetupPlan or silently persisting one that was never
    produced."""


class MCPCentralServiceRequiredError(RuntimeError):
    """Raised when a productive MCP tool (plan/approve/execute setup)
    is invoked without a central ProjectSetupApplicationService.

    Productive setup planning, approval and execution must always go
    through the same central application/business path Web/API uses --
    there is no narrower, MCP-local alternate path left to silently
    fall back to (CLAUDE-E2E-003G). A missing service is a controlled,
    explicit failure, never a trust-boundary bypass.
    """


@dataclass(frozen=True)
class ToolDefinition:
    """Description of a single MCP tool."""

    name: str
    description: str
    input_schema: dict[str, Any]


class MCPServer:
    """Expose existing workflow functions as deterministic MCP tools."""

    def __init__(
        self,
        *,
        project_scanner: Any,
        discovery: Any,
        preflight: Any,
        planner: Any,
        plan_store: Any,
        approval: Any,
        development_workflow: Any,
        project_inspector: Any = None,
        service: Any = None,
    ) -> None:
        self._project_scanner = project_scanner
        self._project_inspector = project_inspector
        self._discovery = discovery
        self._preflight = preflight
        self._planner = planner
        self._plan_store = plan_store
        self._approval = approval
        self._development_workflow = development_workflow
        self._service = service

    def inspect_project(self, project_path: str) -> dict[str, Any]:
        """Inspect a project and return its structure."""
        if self._project_inspector is not None:
            return self._project_inspector.inspect(
                Path(project_path).name, project_path,
            )
        return {
            "project_path": project_path,
            "files": self._project_scanner.scan(project_path),
        }

    def discover_requirements(self, project_path: str) -> Any:
        """Run requirement discovery for a project."""
        return self._discovery.discover(project_path)

    def get_preflight(self, requirements: Any, project_id: str) -> Any:
        """Run preflight checks for the given requirements."""
        return self._preflight.check(requirements, project_id)

    def create_setup_plan(
        self, requirements: Any, preflight_result: Any, project_id: str
    ) -> Any:
        """Create and persist a setup plan for the supplied requirements."""
        if self._planner is None:
            raise RuntimeError(
                "create_setup_plan is deprecated; use canonical plan_project_setup"
            )
        plan = self._planner.plan(requirements, preflight_result, project_id)
        return self._plan_store.save(plan)

    @staticmethod
    def _resolved_project_root(project_root: str) -> str:
        """Validate project_root the same way productive ADC execution does.

        Duplicated in this module (rather than imported from web_api.py)
        deliberately: MCP is its own adapter and must not depend on
        another adapter's internals. The check itself — an existing,
        resolvable directory — is identical.
        """
        if not isinstance(project_root, str) or not project_root.strip():
            raise ValueError("project_root is required and must be a non-empty string.")
        try:
            path = Path(project_root).expanduser().resolve(strict=True)
        except (FileNotFoundError, OSError, RuntimeError) as error:
            raise FileNotFoundError("project_root does not exist.") from error
        if not path.is_dir():
            raise NotADirectoryError("project_root must be an existing directory.")
        return str(path)

    def plan_project_setup(
        self, project_id: str, project_root: str,
        task_description: str | None = None,
        project_info: dict[str, Any] | None = None,
    ) -> Any:
        """Plan a project setup through the same central
        ProjectSetupApplicationService.plan_project_setup() contract
        Web/API uses -- Project Intelligence/Context, Requirement
        Discovery, Validation, Preflight, Engineering Council and
        Toolchain Materialization all happen through that one central
        path, never a narrower MCP-local reconstruction of it
        (CLAUDE-E2E-003G). This is why a plan produced here resolves a
        real target_executable exactly like a Web-originated plan does
        -- both go through the identical RequirementPreflight call with
        a real, ADC-derived project context, not a client-supplied
        `project_info` dict (accepted here only for lenient backward
        compatibility with older callers; it is not used by this
        central path).

        Requires this server to have been constructed with a real
        `service` (ProjectSetupApplicationService); without one,
        planning through the productive central path is impossible,
        and this fails closed (MCPCentralServiceRequiredError) rather
        than falling back to the narrower DevelopmentWorkflow.run()
        call this method used before CLAUDE-E2E-003G.
        """
        if self._service is None:
            raise MCPCentralServiceRequiredError(
                "plan_project_setup requires a central "
                "ProjectSetupApplicationService; none was configured "
                "for this MCP server."
            )
        resolved_root = self._resolved_project_root(project_root)
        entry_data = {"project_id": project_id}
        if task_description:
            entry_data["task_description"] = task_description
        workflow_result = self._service.plan_project_setup(
            project_id, resolved_root,
            entry_interface="mcp", entry_data=entry_data,
        )
        setup_plan = workflow_result.setup_plan
        if setup_plan is None:
            raise MCPEngineeringSelectionPendingError(
                "Planning stopped at the human engineering-selection "
                "boundary; at least one admissible candidate exists but "
                "no explicit human selection has been made yet."
            )
        # persist_setup_plan is the same central, adapter-agnostic
        # persistence step Web/API uses (CLAUDE-E2E-003F): it saves the
        # plan and, when the Council result carries a usable
        # id/recommendation, the Engineering Council reference needed
        # later to authorize execution targets -- MCP does not
        # duplicate this logic with its own bespoke persistence.
        _persist_setup_plan(
            self._plan_store, setup_plan,
            getattr(workflow_result, "council_result", None),
        )
        self._plan_store.save_project_root(project_id, resolved_root)
        return setup_plan

    def get_setup_plan(self, project_id: str, plan_id: str) -> Any:
        """Load a previously saved setup plan."""
        return self._plan_store.load(project_id, plan_id)

    def approve_setup_plan(self, project_id: str, plan_id: str) -> Any:
        """Approve an existing setup plan through the same central
        approve_setup_plan() contract Web/API uses, so this exact
        approval is durably recorded as a real DiagnosticTraceEvent --
        the same mechanism Web/API uses, producing the same kind of
        genuine human_approval_ref later consumed by
        register_setup_step_targets().

        Requires this server to have been constructed with a real
        `service`; without one, this fails closed
        (MCPCentralServiceRequiredError) rather than approving through
        the older, untraced self._approval.approve(plan) path this
        method used before CLAUDE-E2E-003G.
        """
        if self._service is None:
            raise MCPCentralServiceRequiredError(
                "approve_setup_plan requires a central "
                "ProjectSetupApplicationService; none was configured "
                "for this MCP server."
            )
        return _approve_setup_plan_centrally(
            self._service, self._plan_store, project_id, plan_id,
        )

    def execute_setup_plan(self, project_id: str, plan_id: str) -> Any:
        """Execute a saved, approved setup plan through the same
        central setup-execution contract Web/API's own setup phase
        uses (execute_approved_setup_from_store), narrowed to setup
        execution only (no development/testing/rework cycle, matching
        this tool's existing product scope). This method never
        bypasses the existing approval workflow, and it never falls
        back to unconfined execution: the project_root validated and
        persisted by plan_project_setup is required here, fail-closed.

        Authorization (register_setup_step_targets(), reading the
        Engineering Council reference from the same ADC-owned
        plan_store persistence plan_project_setup wrote -- never from a
        caller-supplied value) happens inside
        execute_approved_setup_from_store() itself; this method does
        not reimplement that conditional. When no council reference was
        ever persisted for this plan, registration is skipped and
        execution falls back to the bootstrap capability's PATH-based
        resolution -- not a security failure, an honest absence of the
        additional pinning guarantee.

        Requires this server to have been constructed with a real
        `service`; without one, this fails closed
        (MCPCentralServiceRequiredError) rather than executing through
        the older, unauthorized self._development_workflow.execute_approved()
        call this method used directly before CLAUDE-E2E-003F/G.
        """
        if self._service is None:
            raise MCPCentralServiceRequiredError(
                "execute_setup_plan requires a central "
                "ProjectSetupApplicationService; none was configured "
                "for this MCP server."
            )
        plan = self._plan_store.load(project_id, plan_id)
        if getattr(plan, "status", None) != "approved":
            raise SetupApprovalError(f"Setup plan {plan_id} is not approved")

        project_root = self._plan_store.load_project_root(project_id)
        if not project_root:
            raise SetupApprovalError(
                f"No validated project_root is associated with project "
                f"'{project_id}'; call plan_project_setup with an explicit "
                f"project_root before executing its setup plan."
            )

        return _execute_approved_setup_from_store(
            self._service, self._plan_store, project_id, plan_id, project_root,
        )

    def list_tools(self) -> list[ToolDefinition]:
        """Return tool metadata for all exposed MCP tools."""
        return [
            ToolDefinition(
                name="inspect_project",
                description="Inspect a project and return its files.",
                input_schema={
                    "type": "object",
                    "properties": {"project_path": {"type": "string"}},
                    "required": ["project_path"],
                },
            ),
            ToolDefinition(
                name="discover_requirements",
                description="Discover requirements for a project.",
                input_schema={
                    "type": "object",
                    "properties": {"project_path": {"type": "string"}},
                    "required": ["project_path"],
                },
            ),
            ToolDefinition(
                name="get_preflight",
                description="Run preflight checks for requirements.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "requirements": {"type": "object"},
                        "project_id": {"type": "string"},
                    },
                    "required": ["requirements", "project_id"],
                },
            ),
            ToolDefinition(
                name="create_setup_plan",
                description=(
                    "Deprecated compatibility tool; use plan_project_setup "
                    "for canonical Council-based planning."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "requirements": {"type": "object"},
                        "preflight_result": {"type": "object"},
                        "project_id": {"type": "string"},
                    },
                    "required": ["requirements", "preflight_result", "project_id"],
                },
            ),
            ToolDefinition(
                name="plan_project_setup",
                description=(
                    "Plan a project through the same central ADC "
                    "application/business workflow Web/API uses."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string"},
                        "project_root": {
                            "type": "string",
                            "description": (
                                "Existing, resolvable filesystem directory for "
                                "this project. Required so setup execution can "
                                "later route through the central controlled "
                                "execution boundary instead of failing closed. "
                                "Project Intelligence/Context is derived from "
                                "this root by central ADC logic, not supplied "
                                "by the caller."
                            ),
                        },
                        "task_description": {
                            "type": "string",
                            "description": "Optional user task description.",
                        },
                        "project_info": {
                            "type": "object",
                            "description": (
                                "Deprecated; accepted only for backward "
                                "compatibility and not used by the central "
                                "planning path."
                            ),
                        },
                    },
                    "required": ["project_id", "project_root"],
                },
            ),
            ToolDefinition(
                name="get_setup_plan",
                description="Load a saved setup plan.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string"},
                        "plan_id": {"type": "string"},
                    },
                    "required": ["project_id", "plan_id"],
                },
            ),
            ToolDefinition(
                name="approve_setup_plan",
                description="Approve an existing setup plan.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string"},
                        "plan_id": {"type": "string"},
                    },
                    "required": ["project_id", "plan_id"],
                },
            ),
            ToolDefinition(
                name="execute_setup_plan",
                description="Execute a saved, approved setup plan.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string"},
                        "plan_id": {"type": "string"},
                    },
                    "required": ["project_id", "plan_id"],
                },
            ),
        ]
