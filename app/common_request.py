"""Normalized adapter input for the canonical setup-planning use case."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class RequestIntent(str, Enum):
    """Intents supported by the application core today."""

    PLAN_PROJECT_SETUP = "plan_project_setup"


@dataclass(frozen=True)
class CommonRequest:
    """Adapter-neutral request data for a single setup-planning operation."""

    project_id: str
    project_info: dict[str, Any]
    intent: RequestIntent
    user_request: str | None = None
    source_interface: str | None = None
