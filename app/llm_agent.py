from __future__ import annotations
import json
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import PurePath
from collections.abc import Iterable, Mapping, Callable
from typing import Any, Protocol


class LLMProvider(Protocol):
    def complete(self, prompt: str) -> str:
        """Return a completion for the given prompt."""
        ...


class MCPServer(Protocol):
    def list_tools(self) -> list[Any]:
        """Return available tool definitions.

        Each tool object is expected to expose a ``name`` attribute.
        The agent will dispatch to a method on the MCPServer with the same
        name using keyword arguments.
        """
        ...


@dataclass
class AgentState:
    messages: list[dict[str, Any]] = field(default_factory=list)
    turn_count: int = 0
    complete: bool = False
    max_turns_reached: bool = False
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    last_error: str | None = None
    stop_reason: str | None = None


def _serialize_value(value: Any, _seen: set[int] | None = None) -> Any:
    """Recursively convert *value* to a JSON‑safe representation.

    Handles:
    - dataclasses → dict
    - dict → dict (recurse into keys/values)
    - PurePath (and its subclasses) → str
    - list, tuple, other Iterable → list (recurse into items)
    - primitives (str, int, float, bool, None) → pass through
    - unknown types → str(value) as final fallback
    """
    if _seen is None:
        _seen = set()

    obj_id = id(value)
    if obj_id in _seen:
        return "<circular>"
    _seen = _seen | {obj_id}

    recurse = lambda v: _serialize_value(v, _seen)

    # Dataclasses
    if is_dataclass(value) and not isinstance(value, type):
        data: dict[str, Any] = {}
        for fld in fields(value):
            data[fld.name] = recurse(getattr(value, fld.name))
        return data

    # Dictionaries
    if isinstance(value, Mapping):
        safe: dict[str, Any] = {}
        for key, val in value.items():
            safe_key = recurse(key) if isinstance(key, (dict, list, tuple)) else key
            if not isinstance(safe_key, str):
                safe_key = str(safe_key)
            safe[safe_key] = recurse(val)
        return safe

    # Path‑like objects
    if isinstance(value, PurePath):
        return str(value)

    # Tuples / sets / frozensets / other iterables – convert to list
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        return [recurse(item) for item in value]

    # Primitives
    if isinstance(value, (str, int, float, bool, type(None))):
        return value

    # Final fallback – preserve at least a string representation
    return str(value)


class AgentLLM:
    def __init__(self, llm_provider: LLMProvider, mcp_server: MCPServer, max_turns: int = 5):
        self.llm_provider = llm_provider
        self.mcp_server = mcp_server
        self.max_turns = max_turns

    def run(
        self,
        prompt: str,
        *,
        initial_messages: list[dict[str, Any]] | None = None,
        stop_condition: Callable[[dict[str, Any]], str | None] | None = None,
    ) -> AgentState:
        state = AgentState()
        messages = list(initial_messages or [])
        messages.append({"role": "user", "content": prompt})

        # Load the MCP tool registry once before processing the first LLM turn.
        tool_names = self._get_tool_names()

        while state.turn_count < self.max_turns:
            llm_prompt = self._build_prompt(messages)
            response = self.llm_provider.complete(llm_prompt)
            messages.append({"role": "assistant", "content": response})

            tool_calls = self._parse_tool_calls(response)
            if not tool_calls:
                state.complete = True
                state.messages = messages
                return state

            for call in tool_calls:
                tool_name = call.get("name")
                tool_args = call.get("arguments") or {}

                if not isinstance(tool_name, str):
                    result = {"error": "Tool call missing 'name'"}
                elif tool_name not in tool_names:
                    result = {"error": f"Unknown tool: {tool_name}"}
                else:
                    try:
                        # Dispatch to the matching MCPServer method by name.
                        method = getattr(self.mcp_server, tool_name, None)
                        if method is None:
                            result = {"error": f"Unknown tool: {tool_name}"}
                        else:
                            raw_result = method(**tool_args)
                            result = _serialize_value(raw_result)
                    except Exception as exc:
                        result = {"error": str(exc)}

                # Record the most recent tool error in AgentState.last_error.
                if isinstance(result, dict) and "error" in result:
                    state.last_error = result["error"]

                messages.append({
                    "role": "tool",
                    "tool_name": tool_name,
                    "content": json.dumps(result, default=str)
                })
                state.tool_calls.append({
                    "name": tool_name,
                    "arguments": tool_args,
                    "result": result
                })

                # Stop early if a tool result satisfies the supplied condition.
                if stop_condition is not None:
                    try:
                        stop_reason = stop_condition(result)
                        if stop_reason is not None:
                            state.stop_reason = stop_reason
                            state.complete = False
                            state.messages = messages
                            return state
                    except Exception:
                        # Ignore stop condition errors; continue loop.
                        pass

            state.turn_count += 1

        # Max turns exhausted without a clean completion.
        state.complete = False
        state.max_turns_reached = True
        state.last_error = f"Agent exceeded maximum turns ({self.max_turns})"
        state.messages = messages
        return state

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------
    def _get_tool_names(self) -> set[str]:
        """Return the set of tool names advertised by the MCP server.

        ``MCPServer.list_tools()`` is called exactly once per run.
        """
        try:
            tools = self.mcp_server.list_tools()
        except Exception:
            return set()

        names = set()
        for tool in tools:
            name = getattr(tool, "name", None)
            if isinstance(name, str):
                names.add(name)
        return names

    def _build_prompt(self, messages: list[dict[str, Any]]) -> str:
        parts = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if role == "tool":
                tool_name = msg.get("tool_name", "unknown")
                parts.append(f"[tool:{tool_name}] {content}")
            else:
                parts.append(f"{role}: {content}")
        return "\n".join(parts)

    def _parse_tool_calls(self, response: str) -> list[dict[str, Any]]:
        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            return []

        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]

        if isinstance(data, dict):
            tool_calls = data.get("tool_calls")
            if isinstance(tool_calls, list):
                return [tc for tc in tool_calls if isinstance(tc, dict)]

            # Preserve a malformed single tool call that is missing top-level
            # "name" but still has other tool-call-like keys.
            if any(key in data for key in ("name", "arguments")):
                return [data]

        return []
