"""Normalisation helper for native OpenRouter / OpenAI structured tool-call arguments.

This module is intentionally self‑contained and does not depend on any other
application components.
"""

from __future__ import annotations

import json

from typing import Any


class ArgumentNormalizationError(ValueError):
    """Raised when tool-call arguments cannot be normalised to a plain dict."""


def normalize_tool_arguments(raw_arguments: Any) -> dict[str, Any]:
    """Return a plain dict representation of *raw_arguments*.

    Behaviour
    ---------
    * ``dict``                              → returned unchanged
    * ``str``                               → parsed with ``json.loads``
      - parsed ``dict``                     → returned
      - parsed ``None`` (JSON null)         → ``{}``
      - any other JSON value                → ``ArgumentNormalizationError``
    * any other type                        → ``ArgumentNormalizationError``
    """
    # ------------------------------------------------------------------
    # Already a plain dict – the happy path.
    # ------------------------------------------------------------------
    if isinstance(raw_arguments, dict):
        return raw_arguments

    # ------------------------------------------------------------------
    # String – try to interpret as JSON.
    # ------------------------------------------------------------------
    if isinstance(raw_arguments, str):
        try:
            parsed = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            raise ArgumentNormalizationError(
                "Failed to parse JSON argument string"
            ) from exc

        if isinstance(parsed, dict):
            return parsed

        if parsed is None:
            return {}

        raise ArgumentNormalizationError(
            f"Expected JSON object for arguments but got {type(parsed).__name__}"
        )

    # ------------------------------------------------------------------
    # Anything else is invalid.
    # ------------------------------------------------------------------
    raise ArgumentNormalizationError(
        f"Unsupported argument type: {type(raw_arguments).__name__}"
    )
