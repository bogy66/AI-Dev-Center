"""Deterministic tests for the native OpenRouter tool-calling adapter."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from app.openrouter_llm_provider import (
    OpenRouterAPIError,
    OpenRouterError,
    OpenRouterLLMProvider,
    StructuredCompletionResult,
)
from app.diagnostic_trace import DiagnosticTraceRecorder, TraceLevel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_response(ok=True, status_code=200, json_data=None, text=""):
    response = MagicMock()
    response.ok = ok
    response.status_code = status_code
    response.text = text
    response.json.return_value = json_data
    return response


def make_provider(session=None, recorder=None):
    provider = OpenRouterLLMProvider(
        api_key="test-key",
        model="test-model",
        session=session or MagicMock(),
    )
    return provider, recorder


@pytest.fixture
def mock_session():
    return MagicMock()


@pytest.fixture
def recorder():
    return DiagnosticTraceRecorder(run_id="test-run", trace_level=TraceLevel.DEBUG)


# ---------------------------------------------------------------------------
# Tests – request payload
# ---------------------------------------------------------------------------
def test_tools_are_included_in_request(mock_session):
    provider, _ = make_provider(session=mock_session)
    tools = [
        {
            "type": "function",
            "function": {"name": "tool_a", "description": "A", "parameters": {}},
        }
    ]
    mock_session.post.return_value = make_response(
        json_data={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
    )

    provider.complete_with_tools("hello", tools)

    call = mock_session.post.call_args
    assert call is not None
    kwargs = call.kwargs
    payload = kwargs.get("json")
    assert payload is not None
    assert payload["tools"] == tools


def test_tools_passed_unchanged(mock_session):
    provider, _ = make_provider(session=mock_session)
    tools = [
        {
            "type": "function",
            "function": {
                "name": "inspect_project",
                "description": "Inspect",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    mock_session.post.return_value = make_response(
        json_data={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
    )

    provider.complete_with_tools("hello", tools)

    payload = mock_session.post.call_args.kwargs["json"]
    assert payload["tools"] == tools
    assert payload["tools"][0]["function"]["name"] == "inspect_project"


# ---------------------------------------------------------------------------
# Tests – structured results
# ---------------------------------------------------------------------------
def test_one_native_tool_call(mock_session):
    provider, _ = make_provider(session=mock_session)
    response_json = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "inspect_project",
                                "arguments": '{"project_path": "/tmp"}',
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }
    mock_session.post.return_value = make_response(json_data=response_json)

    result = provider.complete_with_tools("prompt", [])

    assert isinstance(result, StructuredCompletionResult)
    assert result.content == ""
    assert result.finish_reason == "tool_calls"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["id"] == "call_1"
    assert result.tool_calls[0]["name"] == "inspect_project"
    assert result.tool_calls[0]["arguments"] == '{"project_path": "/tmp"}'


def test_multiple_native_tool_calls(mock_session):
    provider, _ = make_provider(session=mock_session)
    response_json = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "tool_a", "arguments": "{}"},
                        },
                        {
                            "id": "call_2",
                            "type": "function",
                            "function": {"name": "tool_b", "arguments": "{}"},
                        },
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }
    mock_session.post.return_value = make_response(json_data=response_json)

    result = provider.complete_with_tools("prompt", [])

    assert len(result.tool_calls) == 2
    assert result.tool_calls[0]["name"] == "tool_a"
    assert result.tool_calls[1]["name"] == "tool_b"


def test_text_only_response(mock_session):
    provider, _ = make_provider(session=mock_session)
    response_json = {
        "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}]
    }
    mock_session.post.return_value = make_response(json_data=response_json)

    result = provider.complete_with_tools("prompt", [])

    assert result.content == "hello"
    assert result.finish_reason == "stop"
    assert result.tool_calls == []


def test_finish_reason(mock_session):
    provider, _ = make_provider(session=mock_session)
    response_json = {
        "choices": [{"message": {"content": "done"}, "finish_reason": "stop"}]
    }
    mock_session.post.return_value = make_response(json_data=response_json)

    result = provider.complete_with_tools("prompt", [])

    assert result.finish_reason == "stop"


# ---------------------------------------------------------------------------
# Tests – error handling
# ---------------------------------------------------------------------------
def test_malformed_response_raises(mock_session):
    provider, _ = make_provider(session=mock_session)
    mock_session.post.return_value = make_response(json_data={"unexpected": True})

    with pytest.raises(OpenRouterError):
        provider.complete_with_tools("prompt", [])


def test_invalid_json_response_raises(mock_session):
    provider, _ = make_provider(session=mock_session)
    response = make_response(json_data=None)
    response.json.side_effect = ValueError("bad json")
    mock_session.post.return_value = response

    with pytest.raises(OpenRouterError):
        provider.complete_with_tools("prompt", [])


def test_provider_http_error(mock_session):
    provider, _ = make_provider(session=mock_session)
    mock_session.post.return_value = make_response(ok=False, status_code=401, text="Unauthorized")

    with pytest.raises(OpenRouterAPIError) as exc_info:
        provider.complete_with_tools("prompt", [])

    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# Tests – diagnostic trace
# ---------------------------------------------------------------------------
def test_trace_events_on_success(mock_session, recorder):
    provider, _ = make_provider(session=mock_session, recorder=recorder)
    tools = [
        {
            "type": "function",
            "function": {"name": "tool_a", "description": "A", "parameters": {}},
        }
    ]
    response_json = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "tool_a", "arguments": "{}"},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }
    mock_session.post.return_value = make_response(json_data=response_json)

    provider.complete_with_tools("prompt", tools, recorder=recorder)

    events = recorder.events
    event_names = {e.event for e in events}
    assert "provider_request_started" in event_names
    assert "provider_response_received" in event_names
    assert "tool_calls_detected" in event_names

    # Safe metadata: no secrets
    for event in events:
        metadata = event.metadata or {}
        assert "api_key" not in metadata
        assert "authorization" not in metadata
        assert "full_prompt" not in metadata
        assert "full_response" not in metadata


def test_trace_events_on_http_error(mock_session, recorder):
    provider, _ = make_provider(session=mock_session, recorder=recorder)
    mock_session.post.return_value = make_response(ok=False, status_code=500, text="Server Error")

    with pytest.raises(OpenRouterAPIError):
        provider.complete_with_tools("prompt", [], recorder=recorder)

    events = recorder.events
    event_names = {e.event for e in events}
    assert "provider_request_started" in event_names
    assert "provider_response_received" in event_names
    assert "provider_request_failed" in event_names


def test_trace_events_on_malformed_response(mock_session, recorder):
    provider, _ = make_provider(session=mock_session, recorder=recorder)
    mock_session.post.return_value = make_response(json_data={"bad": "shape"})

    with pytest.raises(OpenRouterError):
        provider.complete_with_tools("prompt", [], recorder=recorder)

    events = recorder.events
    event_names = {e.event for e in events}
    assert "provider_request_started" in event_names
    assert "provider_response_received" in event_names
    assert "provider_response_malformed" in event_names
