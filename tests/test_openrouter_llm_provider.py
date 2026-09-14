import os
import pytest
import requests
from unittest.mock import MagicMock
from app.openrouter_llm_provider import (
    OpenRouterLLMProvider,
    OpenRouterError,
    OpenRouterAPIError,
)


class TestOpenRouterLLMProvider:
    def test_uses_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "env-key")
        provider = OpenRouterLLMProvider()
        assert provider._api_key == "env-key"

    def test_uses_api_key_from_argument(self):
        provider = OpenRouterLLMProvider(api_key="arg-key")
        assert provider._api_key == "arg-key"

    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        with pytest.raises(ValueError, match="API key"):
            OpenRouterLLMProvider()

    def test_default_model(self):
        provider = OpenRouterLLMProvider(api_key="key")
        assert provider._model == OpenRouterLLMProvider.DEFAULT_MODEL

    def test_custom_model(self):
        provider = OpenRouterLLMProvider(api_key="key", model="custom-model")
        assert provider._model == "custom-model"

    def test_successful_response(self):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello, world!"}}]
        }
        mock_session.post.return_value = mock_response

        provider = OpenRouterLLMProvider(api_key="key", session=mock_session)
        result = provider.complete("prompt")
        assert result == "Hello, world!"
        mock_session.post.assert_called_once()
        call_args = mock_session.post.call_args
        assert call_args[0][0] == "https://openrouter.ai/api/v1/chat/completions"
        headers = call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer key"
        payload = call_args[1]["json"]
        assert payload["model"] == OpenRouterLLMProvider.DEFAULT_MODEL
        assert payload["messages"] == [{"role": "user", "content": "prompt"}]
        assert "response_format" not in payload

    def test_structured_completion_requests_json_object_response(self):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "choices": [{"message": {"content": '{"requirements": []}'}}]
        }
        mock_session.post.return_value = mock_response
        provider = OpenRouterLLMProvider(api_key="key", session=mock_session)

        result = provider.complete_structured("prompt")

        assert result == '{"requirements": []}'
        payload = mock_session.post.call_args.kwargs["json"]
        assert payload["response_format"] == {"type": "json_object"}

    def test_http_error(self):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 400
        mock_response.text = "Bad request"
        mock_session.post.return_value = mock_response

        provider = OpenRouterLLMProvider(api_key="key", session=mock_session)
        with pytest.raises(OpenRouterAPIError) as exc_info:
            provider.complete("prompt")
        assert exc_info.value.status_code == 400
        assert "Bad request" in str(exc_info.value)

    def test_invalid_json_response(self):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.side_effect = ValueError("invalid json")
        mock_session.post.return_value = mock_response

        provider = OpenRouterLLMProvider(api_key="key", session=mock_session)
        with pytest.raises(OpenRouterError, match="Invalid JSON"):
            provider.complete("prompt")

    def test_missing_choices(self):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {}
        mock_session.post.return_value = mock_response

        provider = OpenRouterLLMProvider(api_key="key", session=mock_session)
        with pytest.raises(OpenRouterError, match="Unexpected response"):
            provider.complete("prompt")

    def test_timeout(self):
        mock_session = MagicMock()
        mock_session.post.side_effect = requests.exceptions.Timeout()
        provider = OpenRouterLLMProvider(api_key="key", session=mock_session)
        with pytest.raises(OpenRouterError, match="timed out"):
            provider.complete("prompt")

    def test_connection_error(self):
        mock_session = MagicMock()
        mock_session.post.side_effect = requests.exceptions.ConnectionError()
        provider = OpenRouterLLMProvider(api_key="key", session=mock_session)
        with pytest.raises(OpenRouterError, match="Connection error"):
            provider.complete("prompt")

    def test_read_timeout_wrapped_as_connection_error_is_still_classified_as_timeout(self):
        """CLAUDE-E2E-NIO-007A: a real Real-System-E2E observed
        "TimeoutError: The read operation timed out" surfacing as
        requests.exceptions.ConnectionError, misreported by ADC as a
        bare "Connection error". Mechanically confirmed root cause:
        requests.models.Response.iter_content() itself contains
        `except ReadTimeoutError as e: raise ConnectionError(e)` --
        a genuine urllib3 read timeout that occurs while consuming the
        response BODY (as opposed to during the initial connect/header
        phase, which requests' own HTTPAdapter.send() correctly maps to
        ReadTimeout) is deliberately re-wrapped by requests itself as a
        bare ConnectionError, with the original ReadTimeoutError as its
        sole constructor argument. A real timeout must still be
        classifiable as a timeout despite this wrapping."""
        import urllib3.exceptions

        mock_session = MagicMock()
        read_timeout = urllib3.exceptions.ReadTimeoutError(
            None, "/api/v1/chat/completions", "Read timed out.",
        )
        mock_session.post.side_effect = requests.exceptions.ConnectionError(read_timeout)
        provider = OpenRouterLLMProvider(api_key="key", session=mock_session)
        with pytest.raises(OpenRouterError, match="timed out"):
            provider.complete("prompt")

    def test_genuine_connection_error_without_a_wrapped_timeout_is_unaffected(self):
        """The fix for the case above must not reclassify a real,
        non-timeout connection failure (e.g. DNS failure, connection
        refused) -- covered already by test_connection_error, this adds
        an explicit check that a ConnectionError wrapping a NON-timeout
        cause (e.g. a plain OSError) still reports "Connection error"."""
        mock_session = MagicMock()
        mock_session.post.side_effect = requests.exceptions.ConnectionError(
            OSError("Name or service not known"),
        )
        provider = OpenRouterLLMProvider(api_key="key", session=mock_session)
        with pytest.raises(OpenRouterError, match="Connection error"):
            provider.complete("prompt")

    def test_provider_implements_llm_provider(self):
        provider = OpenRouterLLMProvider(api_key="key")
        # structural check: has complete method
        assert hasattr(provider, "complete")
        assert callable(provider.complete)

    def test_max_tokens_included_in_payload(self):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "OK"}}]
        }
        mock_session.post.return_value = mock_response

        provider = OpenRouterLLMProvider(api_key="key", session=mock_session)
        provider.complete("prompt", max_tokens=512)
        payload = mock_session.post.call_args.kwargs["json"]
        assert payload["max_tokens"] == 512

    def test_max_tokens_omitted_when_none(self):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "OK"}}]
        }
        mock_session.post.return_value = mock_response

        provider = OpenRouterLLMProvider(api_key="key", session=mock_session)
        provider.complete("prompt")
        payload = mock_session.post.call_args.kwargs["json"]
        assert "max_tokens" not in payload
