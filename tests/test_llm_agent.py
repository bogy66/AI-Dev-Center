from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.llm_agent import AgentLLM, AgentState, LLMProvider, MCPServer


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------
class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        if not self.responses:
            return '{"tool_calls": []}'
        return self.responses.pop(0)


class FakeMCPServer:
    """Simulates a real MCPServer whose tools are regular methods.

    ``list_tools`` returns SimpleNamespace objects with a ``name`` attribute.
    Tool dispatch uses ``getattr(self, name)``, matching the real MCP server.
    """
    def __init__(self, handlers=None):
        if handlers is None:
            handlers = {"test_tool": lambda **kwargs: {"ok": True}}
        self._handlers = handlers
        self.list_tools_called = False

    def list_tools(self):
        self.list_tools_called = True
        names = list(self._handlers.keys())
        if not names:
            names = ["test_tool"]
        return [SimpleNamespace(name=name) for name in names]

    def __getattr__(self, name):
        if name in self._handlers:
            def callable_tool(**kwargs):
                return self._handlers[name](**kwargs)
            return callable_tool
        raise AttributeError(name)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_clean_completion_when_no_tool_calls():
    llm = FakeLLM(['{"tool_calls": []}'])
    server = FakeMCPServer()
    agent = AgentLLM(llm, server)

    state = agent.run("hello")

    assert state.complete is True
    assert state.tool_calls == []
    assert state.max_turns_reached is False
    assert llm.calls
    assert server.list_tools_called is True


def test_executes_tool_and_completes():
    responses = [
        '{"tool_calls": [{"name": "test_tool", "arguments": {"a": 1}}]}',
        '{"tool_calls": []}',
    ]
    llm = FakeLLM(responses)
    server = FakeMCPServer()
    agent = AgentLLM(llm, server)

    state = agent.run("please run tool")

    assert state.complete is True
    assert state.turn_count == 1
    assert len(state.tool_calls) == 1
    assert state.tool_calls[0]["name"] == "test_tool"
    assert state.tool_calls[0]["arguments"] == {"a": 1}
    assert state.tool_calls[0]["result"] == {"ok": True}


def test_unknown_tool_handling():
    responses = [
        '{"tool_calls": [{"name": "missing_tool", "arguments": {}}]}',
        '{"tool_calls": []}',
    ]
    llm = FakeLLM(responses)
    server = FakeMCPServer()
    agent = AgentLLM(llm, server)

    state = agent.run("please run unknown tool")

    assert state.complete is True
    assert len(state.tool_calls) == 1
    result = state.tool_calls[0]["result"]
    assert "error" in result
    assert "Unknown tool" in result["error"]


def test_tool_exception_handling():
    def failing_tool(**kwargs):
        raise RuntimeError("boom")

    server = FakeMCPServer(handlers={"test_tool": failing_tool})
    responses = [
        '{"tool_calls": [{"name": "test_tool", "arguments": {}}]}',
        '{"tool_calls": []}',
    ]
    llm = FakeLLM(responses)
    agent = AgentLLM(llm, server)

    state = agent.run("run tool that fails")

    assert state.complete is True
    assert len(state.tool_calls) == 1
    result = state.tool_calls[0]["result"]
    assert "error" in result
    assert result["error"] == "boom"


def test_max_turns_protection():
    responses = [
        '{"tool_calls": [{"name": "test_tool", "arguments": {}}]}',
    ] * 3  # more than enough
    llm = FakeLLM(responses)
    server = FakeMCPServer()
    agent = AgentLLM(llm, server, max_turns=2)

    state = agent.run("run tool forever")

    assert state.complete is False
    assert state.max_turns_reached is True
    assert state.turn_count == 2
    assert state.last_error is not None
    assert "Maximum turns" in state.last_error or "Agent exceeded" in state.last_error
    assert len(state.tool_calls) == 2


def test_invalid_json_is_clean_completion():
    llm = FakeLLM(["not valid json"])
    server = FakeMCPServer()
    agent = AgentLLM(llm, server)

    state = agent.run("hello")

    assert state.complete is True
    assert state.tool_calls == []
    assert state.max_turns_reached is False


def test_json_safe_result_serialization():
    """Ensure tools returning non‑JSON‑friendly objects are serialized structurally."""
    @dataclass
    class Info:
        x: int
        path: Path

    def complex_tool(**kwargs):
        return {"info": Info(7, Path("/tmp/data")), "tuple": (1, 2)}

    server = FakeMCPServer(handlers={"complex_tool": complex_tool})
    responses = [
        '{"tool_calls": [{"name": "complex_tool", "arguments": {}}]}',
        '{"tool_calls": []}',
    ]
    llm = FakeLLM(responses)
    agent = AgentLLM(llm, server)

    state = agent.run("run complex tool")

    assert state.complete is True
    result = state.tool_calls[0]["result"]
    assert isinstance(result, dict)
    assert result["info"]["x"] == 7
    assert result["info"]["path"] == str(Path("/tmp/data"))
    assert result["tuple"] == [1, 2]


def test_max_turns_no_recurse():
    """Verify loop does not recurse when max_turns is reached."""
    responses = [
        '{"tool_calls": [{"name": "test_tool", "arguments": {}}]}',
    ]
    llm = FakeLLM(responses)
    server = FakeMCPServer()
    agent = AgentLLM(llm, server, max_turns=1)

    state = agent.run("start")

    assert state.complete is False
    assert state.max_turns_reached is True
    assert state.turn_count == 1
    assert state.last_error is not None
    assert len(state.tool_calls) == 1


def test_missing_name_in_tool_call():
    responses = [
        '{"tool_calls": [{"arguments": {}}]}',
        '{"tool_calls": []}',
    ]
    llm = FakeLLM(responses)
    server = FakeMCPServer()
    agent = AgentLLM(llm, server)

    state = agent.run("ask")

    assert state.complete is True
    assert len(state.tool_calls) == 1
    result = state.tool_calls[0]["result"]
    assert result.get("error") == "Tool call missing 'name'"
