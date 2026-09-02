import os
import json
import requests
from dataclasses import dataclass
from typing import Any, List, Optional

from app.ai_requirement_discovery import LLMProvider
from app.diagnostic_trace import DiagnosticTraceRecorder, TraceLevel


class OpenRouterError(Exception):
    """Base exception for OpenRouter provider errors."""


class OpenRouterAPIError(OpenRouterError):
    """Raised when the OpenRouter API returns an HTTP error."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"OpenRouter API error {status_code}: {message}")


@dataclass
class StructuredCompletionResult:
    """Structured result returned by ``complete_with_tools``."""

    content: str
    finish_reason: str
    tool_calls: list[dict[str, Any]]


class OpenRouterLLMProvider:
    """LLM provider that uses the OpenRouter API with DeepSeek models."""

    DEFAULT_MODEL = "deepseek/deepseek-v4-pro"  # DeepSeek V4 Pro
    DEFAULT_TIMEOUT = 30  # seconds

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[int] = None,
        session: Optional[requests.Session] = None,
    ):
        self._api_key = api_key or os.environ.get("OPENROUTER_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
        if not self._api_key:
            raise ValueError(
                "OpenRouter API key must be provided via api_key argument or "
                "OPENROUTER_API_KEY / DEEPSEEK_API_KEY environment variable."
            )
        self._model = model or self.DEFAULT_MODEL
        self._timeout = timeout if timeout is not None else self.DEFAULT_TIMEOUT
        self._session = session or requests.Session()

    def complete(self, prompt: str) -> str:
        """Send a completion request to OpenRouter and return the response text."""
        return self._complete(prompt, structured_json=False)

    def complete_structured(self, prompt: str) -> str:
        """Request a provider-enforced JSON object response."""
        return self._complete(prompt, structured_json=True)

    def _complete(self, prompt: str, *, structured_json: bool) -> str:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if structured_json:
            payload["response_format"] = {"type": "json_object"}
        try:
            response = self._session.post(
                url,
                headers=headers,
                json=payload,
                timeout=self._timeout,
            )
        except requests.exceptions.Timeout as exc:
            raise OpenRouterError("Request timed out") from exc
        except requests.exceptions.ConnectionError as exc:
            raise OpenRouterError("Connection error") from exc
        except requests.exceptions.RequestException as exc:
            raise OpenRouterError(f"Request failed: {exc}") from exc

        if not response.ok:
            raise OpenRouterAPIError(
                status_code=response.status_code,
                message=response.text,
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise OpenRouterError("Invalid JSON response") from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenRouterError("Unexpected response structure") from exc

        return content

    def complete_with_tools(
        self,
        prompt: str,
        tools: list[dict[str, Any]],
        recorder: Optional[DiagnosticTraceRecorder] = None,
    ) -> StructuredCompletionResult:
        """Send a native OpenAI-compatible tool-calling request to OpenRouter.

        Returns a structured result containing ``content``, ``finish_reason``,
        and ``tool_calls``.  Arguments are **not** normalized here; they are
        returned exactly as the API supplied them.
        """
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "tools": tools,
        }

        if recorder:
            tool_names = [
                t.get("function", {}).get("name", "") for t in tools
            ]
            recorder.record(
                level=TraceLevel.DEBUG,
                component="OpenRouter",
                event="provider_request_started",
                action="complete_with_tools",
                status="started",
                metadata={
                    "model": self._model,
                    "tool_count": len(tools),
                    "tool_names": tool_names,
                },
            )

        try:
            response = self._session.post(
                url,
                headers=headers,
                json=payload,
                timeout=self._timeout,
            )
        except requests.exceptions.Timeout as exc:
            if recorder:
                recorder.record(
                    level=TraceLevel.ERROR,
                    component="OpenRouter",
                    event="provider_request_failed",
                    action="complete_with_tools",
                    status="failed",
                    metadata={"model": self._model, "reason": "timeout"},
                )
            raise OpenRouterError("Request timed out") from exc
        except requests.exceptions.ConnectionError as exc:
            if recorder:
                recorder.record(
                    level=TraceLevel.ERROR,
                    component="OpenRouter",
                    event="provider_request_failed",
                    action="complete_with_tools",
                    status="failed",
                    metadata={"model": self._model, "reason": "connection_error"},
                )
            raise OpenRouterError("Connection error") from exc
        except requests.exceptions.RequestException as exc:
            if recorder:
                recorder.record(
                    level=TraceLevel.ERROR,
                    component="OpenRouter",
                    event="provider_request_failed",
                    action="complete_with_tools",
                    status="failed",
                    metadata={"model": self._model, "reason": "request_exception"},
                )
            raise OpenRouterError(f"Request failed: {exc}") from exc

        if recorder:
            recorder.record(
                level=TraceLevel.DEBUG,
                component="OpenRouter",
                event="provider_response_received",
                action="complete_with_tools",
                status="success",
                metadata={"model": self._model, "http_status": response.status_code},
            )

        if not response.ok:
            if recorder:
                recorder.record(
                    level=TraceLevel.ERROR,
                    component="OpenRouter",
                    event="provider_request_failed",
                    action="complete_with_tools",
                    status="failed",
                    metadata={
                        "model": self._model,
                        "http_status": response.status_code,
                    },
                )
            raise OpenRouterAPIError(
                status_code=response.status_code,
                message=response.text,
            )

        try:
            data = response.json()
        except ValueError as exc:
            if recorder:
                recorder.record(
                    level=TraceLevel.ERROR,
                    component="OpenRouter",
                    event="provider_response_malformed",
                    action="complete_with_tools",
                    status="failed",
                    metadata={"model": self._model, "reason": "invalid_json"},
                )
            raise OpenRouterError("Invalid JSON response") from exc

        try:
            choice = data["choices"][0]
            message = choice.get("message", {})
            content = message.get("content")
            finish_reason = choice.get("finish_reason", "")
            raw_tool_calls = message.get("tool_calls")
        except (KeyError, IndexError, TypeError) as exc:
            if recorder:
                recorder.record(
                    level=TraceLevel.ERROR,
                    component="OpenRouter",
                    event="provider_response_malformed",
                    action="complete_with_tools",
                    status="failed",
                    metadata={"model": self._model, "reason": "missing_fields"},
                )
            raise OpenRouterError("Unexpected response structure") from exc

        tool_calls = []
        if raw_tool_calls is not None:
            if not isinstance(raw_tool_calls, list):
                if recorder:
                    recorder.record(
                        level=TraceLevel.ERROR,
                        component="OpenRouter",
                        event="provider_response_malformed",
                        action="complete_with_tools",
                        status="failed",
                        metadata={"model": self._model, "reason": "tool_calls_not_list"},
                    )
                raise OpenRouterError("tool_calls is not a list")

            for tc in raw_tool_calls:
                if not isinstance(tc, dict):
                    continue
                try:
                    tool_call = {
                        "id": tc.get("id"),
                        "name": tc.get("function", {}).get("name"),
                        "arguments": tc.get("function", {}).get("arguments"),
                    }
                except AttributeError:
                    # If "function" is not a dict, skip this entry.
                    continue
                tool_calls.append(tool_call)

        if recorder and tool_calls:
            recorder.record(
                level=TraceLevel.DEBUG,
                component="OpenRouter",
                event="tool_calls_detected",
                action="complete_with_tools",
                status="success",
                metadata={
                    "model": self._model,
                    "tool_call_count": len(tool_calls),
                    "finish_reason": finish_reason,
                },
            )

        return StructuredCompletionResult(
            content=content or "",
            finish_reason=finish_reason,
            tool_calls=tool_calls,
        )
