"""Typed YAML configuration loader for AI-Dev-Center.

This module loads and validates the AI configuration file.  It contains no
API-call logic and no provider-specific behaviour.  Authentication secrets
are represented by their reference name only; real secret values are never
read from the YAML file.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


def _ensure_mapping(value: Any, name: str) -> dict:
    """Return *value* as a mapping or raise a validation error."""
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a mapping")
    return value


def _require_non_empty_string(value: Any, name: str) -> str:
    """Validate that *value* is a non-empty string."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _validate_timeout(value: Any) -> float:
    """Validate ``ai.timeout_seconds`` and return it as a float."""
    if value is None:
        return 30.0

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("ai.timeout_seconds must be a positive number")

    if value <= 0:
        raise ValueError("ai.timeout_seconds must be a positive number")

    return float(value)


def _validate_max_requirements(value: Any) -> int:
    """Validate ``ai.discovery.max_requirements``."""
    if value is None:
        return 50

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("ai.discovery.max_requirements must be a positive integer")

    if value <= 0:
        raise ValueError("ai.discovery.max_requirements must be a positive integer")

    return value


def _parse_authentication(data: Any) -> AuthenticationConfig:
    auth_data = _ensure_mapping(data, "ai.authentication")

    auth_type = _require_non_empty_string(
        auth_data.get("type"), "ai.authentication.type"
    )
    secret = _require_non_empty_string(
        auth_data.get("secret"), "ai.authentication.secret"
    )

    return AuthenticationConfig(type=auth_type, secret=secret)


def _parse_discovery(data: Any) -> DiscoveryConfig:
    if data is None:
        return DiscoveryConfig()

    discovery_data = _ensure_mapping(data, "ai.discovery")

    enabled = discovery_data.get("enabled", True)
    require_json = discovery_data.get("require_json", True)
    max_requirements = discovery_data.get("max_requirements", 50)

    if not isinstance(enabled, bool):
        raise ValueError("ai.discovery.enabled must be a boolean")

    if not isinstance(require_json, bool):
        raise ValueError("ai.discovery.require_json must be a boolean")

    max_requirements = _validate_max_requirements(max_requirements)

    return DiscoveryConfig(
        enabled=enabled,
        require_json=require_json,
        max_requirements=max_requirements,
    )


@dataclass(frozen=True)
class AuthenticationConfig:
    """Authentication information for the AI provider."""

    type: str
    secret: str


@dataclass(frozen=True)
class DiscoveryConfig:
    """Configuration for AI-driven requirement discovery."""

    enabled: bool = True
    require_json: bool = True
    max_requirements: int = 50


@dataclass(frozen=True)
class AIConfig:
    """Typed representation of the AI-Dev-Center AI configuration."""

    version: int
    provider: str
    model: str
    endpoint: str
    authentication: AuthenticationConfig
    timeout_seconds: float
    discovery: DiscoveryConfig


def parse_ai_config(data: dict[str, Any]) -> AIConfig:
    """Validate a raw YAML mapping and return a typed :class:`AIConfig`."""
    data = _ensure_mapping(data, "configuration")

    version = data.get("version")
    if version is None:
        raise ValueError("version is required")

    if isinstance(version, bool) or not isinstance(version, int):
        raise ValueError("version must be an integer")

    if version <= 0:
        raise ValueError("version must be a positive integer")

    ai_data = data.get("ai")
    if ai_data is None:
        raise ValueError("'ai' section is required")

    ai_data = _ensure_mapping(ai_data, "'ai'")

    provider = _require_non_empty_string(ai_data.get("provider"), "ai.provider")
    model = _require_non_empty_string(ai_data.get("model"), "ai.model")
    endpoint = _require_non_empty_string(ai_data.get("endpoint"), "ai.endpoint")

    timeout_seconds = _validate_timeout(ai_data.get("timeout_seconds"))

    authentication = _parse_authentication(ai_data.get("authentication"))
    discovery = _parse_discovery(ai_data.get("discovery"))

    return AIConfig(
        version=version,
        provider=provider,
        model=model,
        endpoint=endpoint,
        authentication=authentication,
        timeout_seconds=timeout_seconds,
        discovery=discovery,
    )


def load_ai_config(path: str | Path) -> AIConfig:
    """Load and validate an AI-Dev-Center YAML config file.

    Parameters:
        path: Filesystem path to the YAML file.

    Returns:
        A fully validated :class:`AIConfig` instance.

    Raises:
        ValueError: If the file cannot be read, contains invalid YAML,
            or fails semantic validation.
    """
    path = Path(path)

    try:
        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in {path}: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"Cannot read config file {path}: {exc}") from exc

    if raw is None:
        raise ValueError("Configuration file is empty")

    return parse_ai_config(raw)
