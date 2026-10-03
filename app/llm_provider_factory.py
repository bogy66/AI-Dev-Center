from app.ai_config import AIConfig, CouncilAgentConfig
from app.ai_requirement_discovery import LLMProvider
from app.openrouter_llm_provider import OpenRouterLLMProvider
from app.secret_resolver import SecretNotFoundError, SecretResolver


class UnknownProviderError(Exception):
    """Raised when the factory does not support the requested provider."""


class MissingSecretError(Exception):
    """Raised when a required secret cannot be resolved."""


class CouncilProviderConfigError(Exception):
    """Raised when a council agent config is invalid."""


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


def create_council_provider(
    agent_config: CouncilAgentConfig,
    secret_resolver: SecretResolver,
    ollama_url: str | None = None,
) -> LLMProvider:
    """Return an LLMProvider for a single Council agent.

    Each agent (A1, A2, A3, Chairman) gets its own independently configured
    provider, model, and timeout.  This function is deliberately separate from
    ``create_llm_provider`` because Council agents have per-agent configuration
    that differs from the global AI config.

    Supported providers: ``openrouter``, ``ollama``.
    """
    provider_name = agent_config.provider.lower()

    if provider_name == "openrouter":
        try:
            secret_value = secret_resolver.resolve("openrouter-api")
        except SecretNotFoundError as exc:
            raise MissingSecretError(
                f"Secret 'openrouter-api' not found for agent '{agent_config.role}'"
            ) from exc
        except Exception as exc:
            raise MissingSecretError(
                f"Failed to resolve secret for agent '{agent_config.role}': {exc}"
            ) from exc

        return OpenRouterLLMProvider(
            api_key=secret_value,
            model=agent_config.model,
            timeout=int(agent_config.timeout_seconds),
        )

    if provider_name == "ollama":
        if not ollama_url:
            raise CouncilProviderConfigError(
                "ollama_url must be set in council config when using ollama provider"
            )
        from app.ollama_adapter import OllamaAdapter
        return OllamaAdapter(
            url=ollama_url,
            model=agent_config.model,
            timeout=int(agent_config.timeout_seconds),
        )

    raise UnknownProviderError(
        f"Unsupported council agent provider: {agent_config.provider!r} "
        f"for agent '{agent_config.role}'"
    )
