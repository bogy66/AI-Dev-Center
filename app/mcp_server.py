"""Thin MCP server that exposes existing AI Dev Center workflow tools.

The server contains no business logic.  Every tool delegates to an existing
component from the surrounding application.  This module only adapts those
components into callable tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.setup_approval import SetupApprovalError


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
    ) -> None:
        self._project_scanner = project_scanner
        self._project_inspector = project_inspector
        self._discovery = discovery
        self._preflight = preflight
        self._planner = planner
        self._plan_store = plan_store
        self._approval = approval
        self._development_workflow = development_workflow

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
        self, project_info: dict[str, Any], project_id: str, project_root: str,
    ) -> Any:
        """Create and persist a setup plan through the canonical workflow.

        project_root must be an existing, resolvable directory. It is
        validated and persisted alongside the plan so that a later
        execute_setup_plan call can route actual execution through the
        central controlled execution boundary instead of falling back to
        unconfined direct process creation.
        """
        resolved_root = self._resolved_project_root(project_root)
        workflow_result = self._development_workflow.run(
            project_info,
            project_id,
        )
        setup_plan = workflow_result.setup_plan
        self._plan_store.save(setup_plan)
        self._plan_store.save_project_root(project_id, resolved_root)
        return setup_plan

    def get_setup_plan(self, project_id: str, plan_id: str) -> Any:
        """Load a previously saved setup plan."""
        return self._plan_store.load(project_id, plan_id)

    def approve_setup_plan(self, project_id: str, plan_id: str) -> Any:
        """Approve an existing setup plan."""
        plan = self._plan_store.load(project_id, plan_id)
        approved_plan = self._approval.approve(plan)
        self._plan_store.save(approved_plan)
        return approved_plan

    def execute_setup_plan(self, project_id: str, plan_id: str) -> Any:
        """Execute a saved, approved setup plan.

        This method never bypasses the existing approval workflow. It
        also never falls back to unconfined execution: the project_root
        validated and persisted by plan_project_setup is required here,
        fail-closed, so the configured executor's default runner always
        routes through the central controlled execution boundary.
        """
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

        return self._development_workflow.execute_approved(plan, project_root)

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
                description="Plan a project through the canonical development workflow.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "project_info": {"type": "object"},
                        "project_id": {"type": "string"},
                        "project_root": {
                            "type": "string",
                            "description": (
                                "Existing, resolvable filesystem directory for "
                                "this project. Required so setup execution can "
                                "later route through the central controlled "
                                "execution boundary instead of failing closed."
                            ),
                        },
                    },
                    "required": ["project_info", "project_id", "project_root"],
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
