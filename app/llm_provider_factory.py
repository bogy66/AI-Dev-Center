from app.ai_config import AIConfig
from app.ai_requirement_discovery import LLMProvider
from app.openrouter_llm_provider import OpenRouterLLMProvider
from app.secret_resolver import SecretNotFoundError, SecretResolver


class UnknownProviderError(Exception):
    """Raised when the factory does not support the requested provider."""


class MissingSecretError(Exception):
    """Raised when a required secret cannot be resolved."""


def create_llm_provider(config: AIConfig, secret_resolver: SecretResolver) -> LLMProvider:
    """Return an LLMProvider according to the given AIConfig and SecretResolver.

    This factory is deliberately generic.  It knows nothing about real secret
    values, never logs them, and never reads secrets directly from YAML.
    """
    provider_name = config.provider.lower()

    if provider_name != "openrouter":
        raise UnknownProviderError(
            f"Unsupported AI provider: {config.provider!r}"
        )

    # Resolve the secret through the injected resolver.  The resolver
    # guarantees that the returned value is a non‑empty string.
    try:
        secret_value = secret_resolver.resolve(config.authentication.secret)
    except SecretNotFoundError as exc:
        raise MissingSecretError(
            f"Secret '{config.authentication.secret}' not found"
        ) from exc
    except Exception as exc:
        raise MissingSecretError(
            f"Failed to resolve secret '{config.authentication.secret}': {exc}"
        ) from exc

    # OpenRouterLLMProvider currently does not accept an `endpoint` parameter.
    # When the provider gains that capability, the factory can be extended
    # to pass config.endpoint as well.
    return OpenRouterLLMProvider(
        api_key=secret_value,
        model=config.model,
        timeout=int(config.timeout_seconds),
        # endpoint is not supported yet, so we do not pass it.
    )
