from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.ai_config import AIConfig, DiscoveryConfig, load_ai_config


def _write_config(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "ai-dev-center.yml"
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


_VALID_CONFIG = """\
version: 1
ai:
  provider: openrouter
  model: deepseek/deepseek-v4-pro
  endpoint: https://openrouter.ai/api/v1
  authentication:
    type: secret_reference
    secret: openrouter-api
  timeout_seconds: 30
  discovery:
    enabled: true
    require_json: true
    max_requirements: 50
"""


def test_valid_config(tmp_path: Path) -> None:
    config = load_ai_config(_write_config(tmp_path, _VALID_CONFIG))

    assert config.version == 1
    assert config.provider == "openrouter"
    assert config.model == "deepseek/deepseek-v4-pro"
    assert config.endpoint == "https://openrouter.ai/api/v1"
    assert config.authentication.type == "secret_reference"
    assert config.authentication.secret == "openrouter-api"
    assert config.timeout_seconds == 30.0
    assert config.discovery.enabled is True
    assert config.discovery.require_json is True
    assert config.discovery.max_requirements == 50


def test_missing_version(tmp_path: Path) -> None:
    content = """\
ai:
  provider: openrouter
  model: deepseek/deepseek-v4-pro
  endpoint: https://openrouter.ai/api/v1
  authentication:
    type: secret_reference
    secret: openrouter-api
"""
    with pytest.raises(ValueError, match="version"):
        load_ai_config(_write_config(tmp_path, content))


def test_missing_ai(tmp_path: Path) -> None:
    content = """\
version: 1
"""
    with pytest.raises(ValueError, match="'ai' section"):
        load_ai_config(_write_config(tmp_path, content))


def test_missing_model(tmp_path: Path) -> None:
    content = """\
version: 1
ai:
  provider: openrouter
  endpoint: https://openrouter.ai/api/v1
  authentication:
    type: secret_reference
    secret: openrouter-api
"""
    with pytest.raises(ValueError, match="ai.model"):
        load_ai_config(_write_config(tmp_path, content))


def test_missing_provider(tmp_path: Path) -> None:
    content = """\
version: 1
ai:
  model: deepseek/deepseek-v4-pro
  endpoint: https://openrouter.ai/api/v1
  authentication:
    type: secret_reference
    secret: openrouter-api
"""
    with pytest.raises(ValueError, match="ai.provider"):
        load_ai_config(_write_config(tmp_path, content))


def test_missing_authentication_secret(tmp_path: Path) -> None:
    content = """\
version: 1
ai:
  provider: openrouter
  model: deepseek/deepseek-v4-pro
  endpoint: https://openrouter.ai/api/v1
  authentication:
    type: secret_reference
"""
    with pytest.raises(ValueError, match="ai.authentication.secret"):
        load_ai_config(_write_config(tmp_path, content))


def test_invalid_timeout(tmp_path: Path) -> None:
    content = """\
version: 1
ai:
  provider: openrouter
  model: deepseek/deepseek-v4-pro
  endpoint: https://openrouter.ai/api/v1
  timeout_seconds: -1
  authentication:
    type: secret_reference
    secret: openrouter-api
"""
    with pytest.raises(ValueError, match="timeout_seconds"):
        load_ai_config(_write_config(tmp_path, content))


def test_invalid_max_requirements(tmp_path: Path) -> None:
    content = """\
version: 1
ai:
  provider: openrouter
  model: deepseek/deepseek-v4-pro
  endpoint: https://openrouter.ai/api/v1
  authentication:
    type: secret_reference
    secret: openrouter-api
  discovery:
    max_requirements: 0
"""
    with pytest.raises(ValueError, match="max_requirements"):
        load_ai_config(_write_config(tmp_path, content))


def test_missing_discovery_uses_defaults(tmp_path: Path) -> None:
    content = """\
version: 1
ai:
  provider: openrouter
  model: deepseek/deepseek-v4-pro
  endpoint: https://openrouter.ai/api/v1
  authentication:
    type: secret_reference
    secret: openrouter-api
"""
    config = load_ai_config(_write_config(tmp_path, content))

    assert isinstance(config.discovery, DiscoveryConfig)
    assert config.discovery.enabled is True
    assert config.discovery.require_json is True
    assert config.discovery.max_requirements == 50
    assert config.timeout_seconds == 30.0
