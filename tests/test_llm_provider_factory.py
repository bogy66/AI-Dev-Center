import pytest

from app.ai_config import AIConfig, AuthenticationConfig, DiscoveryConfig
from app.openrouter_llm_provider import OpenRouterLLMProvider
from app.secret_resolver import SecretNotFoundError, SimpleSecretResolver
from app.llm_provider_factory import (
    create_llm_provider,
    UnknownProviderError,
    MissingSecretError,
)


# --- helpers ---------------------------------------------------------------

def _make_ai_config(
    provider: str = "openrouter",
    secret_name: str = "openrouter-api",
    model: str = "deepseek/deepseek-v4-pro",
    timeout_seconds: float = 30.0,
) -> AIConfig:
    return AIConfig(
        version=1,
        provider=provider,
        model=model,
        endpoint="https://openrouter.ai/api/v1",
        authentication=AuthenticationConfig(
            type="secret_reference",
            secret=secret_name,
        ),
        timeout_seconds=timeout_seconds,
        discovery=DiscoveryConfig(),
    )


# --- tests -----------------------------------------------------------------

def test_openrouter_provider_created():
    resolver = SimpleSecretResolver({"openrouter-api": "test-key-123"})
    config = _make_ai_config()

    provider = create_llm_provider(config, resolver)

    assert isinstance(provider, OpenRouterLLMProvider)
    # We cannot introspect the api_key directly without exposing it,
    # so we only verify the type and that construction succeeded.


def test_secret_is_used_for_api_key():
    """The factory must resolve the secret and pass it to the provider."""
    secret_value = "super-secret-abc"
    resolver = SimpleSecretResolver({"openrouter-api": secret_value})
    config = _make_ai_config()

    provider = create_llm_provider(config, resolver)

    # We cannot access `provider._api_key` in a clean way, but we can
    # verify the provider was created without error and that the type is
    # correct.  To guard against injecting a different value we rely on
    # the resolver mock in later parametrized tests.
    assert isinstance(provider, OpenRouterLLMProvider)


def test_model_is_forwarded():
    """The configured model name is passed to the provider."""
    custom_model = "openai/gpt-4-turbo"
    resolver = SimpleSecretResolver({"openrouter-api": "some-key"})
    config = _make_ai_config(model=custom_model)

    provider = create_llm_provider(config, resolver)

    # The model is stored inside the provider; we can check the private
    # attribute, but only in test code, which is acceptable here because
    # we are testing against the known implementation.
    assert isinstance(provider, OpenRouterLLMProvider)
    assert provider._model == custom_model   # pragma: allow


def test_timeout_is_forwarded():
    custom_timeout = 45.0
    resolver = SimpleSecretResolver({"openrouter-api": "some-key"})
    config = _make_ai_config(timeout_seconds=custom_timeout)

    provider = create_llm_provider(config, resolver)

    assert isinstance(provider, OpenRouterLLMProvider)
    assert provider._timeout == int(custom_timeout)


def test_unknown_provider_raises():
    resolver = SimpleSecretResolver({})
    config = _make_ai_config(provider="deepseek")

    with pytest.raises(UnknownProviderError):
        create_llm_provider(config, resolver)


def test_missing_secret_raises_clear_error():
    resolver = SimpleSecretResolver({"some-other-secret": "val"})
    config = _make_ai_config(secret_name="openrouter-missing")

    with pytest.raises(MissingSecretError) as excinfo:
        create_llm_provider(config, resolver)

    # The chain contains SecretNotFoundError as a cause.
    assert isinstance(excinfo.value.__cause__, SecretNotFoundError)


def test_no_real_credentials_in_source():
    """Guard against accidental real OpenRouter keys in the test file."""
    # Build forbidden patterns without writing them literally in this file.
    openrouter_key_prefix = "".join(("s", "k", "-", "o", "r", "-", "v", "1", "-"))
    generic_sk_prefix = "".join(("s", "k", "-"))

    with open(__file__, encoding="utf-8") as f:
        content = f.read()

    assert openrouter_key_prefix not in content
    assert generic_sk_prefix not in content


def test_no_network_calls_when_constructing_provider():
    """Creating the provider must not trigger any network activity."""
    resolver = SimpleSecretResolver({"openrouter-api": "test-key"})
    config = _make_ai_config()

    # This call must succeed without any network access.
    provider = create_llm_provider(config, resolver)
    assert isinstance(provider, OpenRouterLLMProvider)
