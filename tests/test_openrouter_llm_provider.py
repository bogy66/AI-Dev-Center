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

    def test_provider_implements_llm_provider(self):
        provider = OpenRouterLLMProvider(api_key="key")
        # structural check: has complete method
        assert hasattr(provider, "complete")
        assert callable(provider.complete)
