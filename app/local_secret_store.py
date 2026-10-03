from pathlib import Path

import yaml

from .secret_resolver import (
    EmptySecretError,
    SecretNotFoundError,
    SecretResolutionError,
)


class LocalSecretStore:
    """Reads secrets from a local YAML file outside the repository.

    The default location is ``~/.config/ai-dev-center/secrets.yml``.
    This class implements the ``SecretResolver`` protocol without
    inheriting from it, matching the existing ``SimpleSecretResolver``
    pattern.
    """

    DEFAULT_SECRETS_PATH = Path.home() / ".config" / "ai-dev-center" / "secrets.yml"

    def __init__(self, secrets_path: str | Path | None = None) -> None:
        if secrets_path is None:
            self._path = self.DEFAULT_SECRETS_PATH
        else:
            self._path = Path(secrets_path)

    def resolve(self, secret_name: str) -> str:
        """Return the non-empty string value for *secret_name*.

        Secret values are never logged, printed, or included in any
        exception message.
        """

        if not self._path.exists():
            raise SecretResolutionError(
                f"Secret file not found: {self._path}"
            )

        try:
            raw_text = self._path.read_text(encoding="utf-8")
        except OSError as exc:
            raise SecretResolutionError(
                f"Failed to read secret file {self._path}: {exc}"
            ) from exc

        try:
            data = yaml.safe_load(raw_text)
        except yaml.YAMLError:
            # Deliberately suppress the original YAML error.  YAML
            # exceptions may include the problematic line, which could
            # contain a secret value.
            raise SecretResolutionError(
                f"Invalid YAML in secret file {self._path}"
            )

        if not isinstance(data, dict):
            raise SecretResolutionError(
                f"Invalid secret file structure in {self._path}: expected a mapping"
            )

        secrets = data.get("secrets")
        if secrets is None:
            raise SecretResolutionError(
                f"Secret file {self._path} does not contain a 'secrets' section"
            )
        if not isinstance(secrets, dict):
            raise SecretResolutionError(
                f"Secret file {self._path} has invalid 'secrets' section; expected a mapping"
            )

        if secret_name not in secrets:
            raise SecretNotFoundError(f"Secret '{secret_name}' not found.")

        value = secrets[secret_name]
        if not isinstance(value, str):
            raise SecretResolutionError(
                f"Secret '{secret_name}' has invalid type; expected str."
            )

        if value == "":
            raise EmptySecretError(f"Secret '{secret_name}' is empty.")

        return value
