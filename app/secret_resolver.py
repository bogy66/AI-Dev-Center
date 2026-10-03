from typing import Mapping, Protocol, runtime_checkable


class SecretResolutionError(Exception):
    """Base error for secret resolution failures."""


class SecretNotFoundError(SecretResolutionError):
    """Raised when a requested secret is not present in the source."""


class EmptySecretError(SecretResolutionError):
    """Raised when a requested secret is present but its value is empty."""


@runtime_checkable
class SecretResolver(Protocol):
    """Protocol for any object that can resolve a secret by name."""

    def resolve(self, secret_name: str) -> str:
        """Return the non-empty string value for *secret_name*."""


class SimpleSecretResolver:
    """Resolves secrets from an injectable mapping of secret name -> value.

    The resolver is deliberately generic.  It knows nothing about OpenRouter,
    DeepSeek, API calls, YAML files, or any other provider-specific detail.
    It never logs, prints, or otherwise reveals secret values.
    """

    def __init__(self, secrets: Mapping[str, str]) -> None:
        self._secrets = secrets

    def resolve(self, secret_name: str) -> str:
        if secret_name not in self._secrets:
            raise SecretNotFoundError(f"Secret '{secret_name}' not found.")

        value = self._secrets[secret_name]

        # Accept only non-empty string values.  Any other value is treated as
        # an invalid/empty secret and must not be returned.
        if isinstance(value, str) is False:
            raise SecretResolutionError(
                f"Secret '{secret_name}' has invalid type; expected str."
            )

        if value == "":
            raise EmptySecretError(f"Secret '{secret_name}' is empty.")

        return value
