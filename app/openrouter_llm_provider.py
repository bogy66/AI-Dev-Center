import os
import requests
from typing import Optional
from app.ai_requirement_discovery import LLMProvider


class OpenRouterError(Exception):
    """Base exception for OpenRouter provider errors."""


class OpenRouterAPIError(OpenRouterError):
    """Raised when the OpenRouter API returns an HTTP error."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"OpenRouter API error {status_code}: {message}")


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
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
        }
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
