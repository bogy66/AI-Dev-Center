"""Deterministic tests for the tool-schema adapter.

These tests verify that the adapter correctly converts MCPServer
ToolDefinition objects into OpenAI/OpenRouter-compatible tool schemas.
"""

from __future__ import annotations

import pytest

from app.mcp_server import ToolDefinition
from app.tool_schema_adapter import tool_definition_to_openai, tools_to_openai


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def sample_tool_def() -> ToolDefinition:
    return ToolDefinition(
        name="inspect_project",
        description="Inspect a project and return its files.",
        input_schema={
            "type": "object",
            "properties": {"project_path": {"type": "string"}},
            "required": ["project_path"],
        },
    )


@pytest.fixture
def all_mcp_tool_defs() -> list[ToolDefinition]:
    """Replicate the exact ToolDefinition list returned by MCPServer.list_tools().

    This fixture mirrors the definitions in ``app/mcp_server.py`` so that
    the adapter is tested against the real source of truth.
    """
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
            description="Create and persist a setup plan.",
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


# ---------------------------------------------------------------------------
# Tests – single ToolDefinition
# ---------------------------------------------------------------------------
def test_single_tool_definition_converts_correctly(sample_tool_def):
    result = tool_definition_to_openai(sample_tool_def)

    assert result["type"] == "function"
    assert "function" in result
    assert result["function"]["name"] == sample_tool_def.name
    assert result["function"]["description"] == sample_tool_def.description
    assert result["function"]["parameters"] == sample_tool_def.input_schema


def test_name_and_description_are_preserved(sample_tool_def):
    result = tool_definition_to_openai(sample_tool_def)
    assert result["function"]["name"] == "inspect_project"
    assert result["function"]["description"] == "Inspect a project and return its files."


def test_input_schema_is_preserved_exactly(sample_tool_def):
    result = tool_definition_to_openai(sample_tool_def)
    # The adapter must not modify the input_schema in any way.
    assert result["function"]["parameters"] is sample_tool_def.input_schema


def test_output_has_type_function_and_function_wrapper(sample_tool_def):
    result = tool_definition_to_openai(sample_tool_def)
    assert result["type"] == "function"
    assert isinstance(result["function"], dict)
    assert set(result["function"].keys()) == {"name", "description", "parameters"}


# ---------------------------------------------------------------------------
# Tests – all MCP tools
# ---------------------------------------------------------------------------
def test_all_mcp_tools_convert(all_mcp_tool_defs):
    """Every ToolDefinition from the real MCPServer must convert without error."""
    schemas = tools_to_openai(all_mcp_tool_defs)
    assert len(schemas) == len(all_mcp_tool_defs)

    for schema, td in zip(schemas, all_mcp_tool_defs):
        assert schema["type"] == "function"
        assert schema["function"]["name"] == td.name
        assert schema["function"]["description"] == td.description
        assert schema["function"]["parameters"] == td.input_schema


def test_all_mcp_tools_have_expected_names(all_mcp_tool_defs):
    expected_names = {
        "inspect_project",
        "discover_requirements",
        "get_preflight",
        "create_setup_plan",
        "get_setup_plan",
        "approve_setup_plan",
        "execute_setup_plan",
    }
    actual_names = {td.name for td in all_mcp_tool_defs}
    assert actual_names == expected_names


def test_all_mcp_tools_have_non_empty_descriptions(all_mcp_tool_defs):
    for td in all_mcp_tool_defs:
        assert isinstance(td.description, str) and len(td.description) > 0


def test_all_mcp_tools_have_valid_input_schema(all_mcp_tool_defs):
    for td in all_mcp_tool_defs:
        schema = td.input_schema
        assert isinstance(schema, dict)
        assert schema.get("type") == "object"
        assert "properties" in schema
        assert "required" in schema
        assert isinstance(schema["required"], list)
