"""Structural guard for the single productive business-workflow boundary."""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import app.canonical_composition as composition


PRODUCTIVE_ADAPTERS = (
    "app/api.py",
    "app/web_api.py",
    "app/mcp_server.py",
    "app/mcp_transport.py",
    "app/workflow_cli.py",
    "app/workflow_execution_cli.py",
    "cli/agent_workflow_cli.py",
)
FORBIDDEN_MODULES = {
    "app.agent_orchestrator",
    "app.git_manager",
    "app.workflow_publisher",
    "app.setup_planner",
}


def test_productive_adapters_do_not_import_legacy_business_workflows():
    root = Path(__file__).parents[1]
    violations = []
    for relative_path in PRODUCTIVE_ADAPTERS:
        tree = ast.parse((root / relative_path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in FORBIDDEN_MODULES:
                violations.append(f"{relative_path}: {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in FORBIDDEN_MODULES:
                        violations.append(f"{relative_path}: {alias.name}")
    assert violations == []


@pytest.mark.parametrize("council", [None, SimpleNamespace(enabled=False)])
def test_shared_composition_rejects_invalid_council_before_secrets(
    monkeypatch, council
):
    load_config = Mock(return_value=SimpleNamespace(council=council))
    secret_store = Mock()
    provider_factory = Mock()
    monkeypatch.setattr(composition, "load_ai_config", load_config)
    monkeypatch.setattr(composition, "LocalSecretStore", secret_store)
    monkeypatch.setattr(composition, "create_llm_provider", provider_factory)

    with pytest.raises(
        composition.WorkflowExecutionError,
        match="Engineering Council configuration must be enabled",
    ):
        composition.build_canonical_components()

    secret_store.assert_not_called()
    provider_factory.assert_not_called()


def test_visible_help_and_pitch_describe_canonical_boundaries():
    root = Path(__file__).parents[1]
    help_text = (root / "web/index.html").read_text(encoding="utf-8")
    pitch_text = (root / "web/app.js").read_text(encoding="utf-8")

    assert "Web, API, CLI and MCP are communication adapters" in help_text
    assert "Setup Approval before setup execution" in help_text
    assert "not presented as productive capabilities" in help_text
    assert "Web, API, CLI and MCP are adapters" in pitch_text
    assert "Setup Approval, Final Approval and Publish Approval" in pitch_text
    assert "outside the current productive scope" in pitch_text
    assert "Workflow / Agent orchestration" not in pitch_text
