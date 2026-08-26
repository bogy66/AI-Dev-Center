"""Convert MCPServer ToolDefinition objects to OpenAI/OpenRouter tool schemas.

This module is intentionally minimal.  It does not import any other
application components beyond the ToolDefinition dataclass.
"""

from __future__ import annotations

from app.mcp_server import ToolDefinition


def tool_definition_to_openai(tool_def: ToolDefinition) -> dict:
    """Return an OpenAI-compatible tool schema for *tool_def*.

    The returned dictionary has the shape::

        {
            "type": "function",
            "function": {
                "name": "<tool name>",
                "description": "<tool description>",
                "parameters": <input_schema>
            }
        }

    The ``input_schema`` is passed through unchanged.
    """
    return {
        "type": "function",
        "function": {
            "name": tool_def.name,
            "description": tool_def.description,
            "parameters": tool_def.input_schema,
        },
    }


def tools_to_openai(tool_defs: list[ToolDefinition]) -> list[dict]:
    """Convert a list of ToolDefinition objects to a list of OpenAI tool schemas."""
    return [tool_definition_to_openai(td) for td in tool_defs]
