from pathlib import Path

import pytest

from app.local_secret_store import LocalSecretStore
from app.secret_resolver import (
    EmptySecretError,
    SecretNotFoundError,
    SecretResolutionError,
    SecretResolver,
)


def write_secret_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_existing_secret(tmp_path):
    secret_file = tmp_path / "secrets.yml"
    write_secret_file(
        secret_file,
        "secrets:\n  openrouter-api: \"test_value_123\"\n",
    )

    store = LocalSecretStore(secret_file)

    assert store.resolve("openrouter-api") == "test_value_123"


def test_unknown_secret(tmp_path):
    secret_file = tmp_path / "secrets.yml"
    write_secret_file(
        secret_file,
        "secrets:\n  openrouter-api: \"test_value_123\"\n",
    )

    store = LocalSecretStore(secret_file)

    with pytest.raises(SecretNotFoundError):
        store.resolve("does-not-exist")


def test_empty_secret(tmp_path):
    secret_file = tmp_path / "secrets.yml"
    write_secret_file(
        secret_file,
        "secrets:\n  openrouter-api: \"\"\n",
    )

    store = LocalSecretStore(secret_file)

    with pytest.raises(EmptySecretError):
        store.resolve("openrouter-api")


def test_file_not_found(tmp_path):
    missing_file = tmp_path / "does-not-exist.yml"

    store = LocalSecretStore(missing_file)

    with pytest.raises(SecretResolutionError):
        store.resolve("openrouter-api")


def test_invalid_yaml_structure_is_not_a_mapping(tmp_path):
    secret_file = tmp_path / "secrets.yml"
    write_secret_file(secret_file, "- first\n- second\n")

    store = LocalSecretStore(secret_file)

    with pytest.raises(SecretResolutionError):
        store.resolve("openrouter-api")


def test_missing_secrets_section(tmp_path):
    secret_file = tmp_path / "secrets.yml"
    write_secret_file(secret_file, "other: value\n")

    store = LocalSecretStore(secret_file)

    with pytest.raises(SecretResolutionError):
        store.resolve("openrouter-api")


def test_multiple_secrets(tmp_path):
    secret_file = tmp_path / "secrets.yml"
    write_secret_file(
        secret_file,
        "secrets:\n"
        "  openrouter-api: \"secret_one\"\n"
        "  another-secret: \"secret_two\"\n",
    )

    store = LocalSecretStore(secret_file)

    assert store.resolve("openrouter-api") == "secret_one"
    assert store.resolve("another-secret") == "secret_two"


def test_secret_value_not_in_error_messages(tmp_path):
    secret_value = "super_secret_value_do_not_leak"
    secret_file = tmp_path / "secrets.yml"
    write_secret_file(
        secret_file,
        f"secrets:\n  openrouter-api: \"{secret_value}\"\n",
    )

    store = LocalSecretStore(secret_file)

    with pytest.raises(SecretNotFoundError) as exc_info:
        store.resolve("unknown-secret")

    assert secret_value not in str(exc_info.value)


def test_satisfies_secret_resolver_protocol(tmp_path):
    secret_file = tmp_path / "secrets.yml"
    write_secret_file(
        secret_file,
        "secrets:\n  openrouter-api: \"test_value_123\"\n",
    )

    store = LocalSecretStore(secret_file)

    assert isinstance(store, SecretResolver)


def test_temporary_path_works(tmp_path):
    secret_file = tmp_path / "nested" / "secrets.yml"
    write_secret_file(
        secret_file,
        "secrets:\n  openrouter-api: \"nested_path_value\"\n",
    )

    store = LocalSecretStore(secret_file)

    assert store.resolve("openrouter-api") == "nested_path_value"
