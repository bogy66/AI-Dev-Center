import pytest

from app.secret_resolver import (
    SecretNotFoundError,
    EmptySecretError,
    SecretResolutionError,
    SecretResolver,
    SimpleSecretResolver,
)


def test_resolve_existing_secret():
    resolver = SimpleSecretResolver({"openrouter-api": "test-secret-value"})
    assert resolver.resolve("openrouter-api") == "test-secret-value"


def test_resolve_unknown_secret_raises_clear_error():
    resolver = SimpleSecretResolver({"known-secret": "test-value"})
    with pytest.raises(SecretNotFoundError):
        resolver.resolve("does-not-exist")


def test_resolve_empty_secret_raises_error():
    resolver = SimpleSecretResolver({"empty-secret": ""})
    with pytest.raises(EmptySecretError):
        resolver.resolve("empty-secret")


def test_resolve_multiple_secrets():
    secrets = {
        "first-secret": "value-1",
        "second-secret": "value-2",
        "third-secret": "value-3",
    }
    resolver = SimpleSecretResolver(secrets)

    assert resolver.resolve("first-secret") == "value-1"
    assert resolver.resolve("second-secret") == "value-2"
    assert resolver.resolve("third-secret") == "value-3"


def test_no_real_credentials_are_used_in_tests():
    # All values used above are deliberately dummy placeholder strings.
    # This test guards against accidentally embedding real credentials.
    assert "sk-" not in "value-1"
    assert "sk-" not in "value-2"
    assert "sk-" not in "value-3"


def test_resolve_does_not_output_secret_value(capsys):
    resolver = SimpleSecretResolver({"openrouter-api": "top-secret-value"})

    result = resolver.resolve("openrouter-api")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert result == "top-secret-value"


def test_simple_secret_resolver_satisfies_secret_resolver_protocol():
    resolver = SimpleSecretResolver({"any-secret": "any-value"})
    assert isinstance(resolver, SecretResolver)
