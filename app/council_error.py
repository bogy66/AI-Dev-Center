"""Error types for the Multi-KI Engineering Council."""

from __future__ import annotations


class CouncilError(Exception):
    """Base exception for all Council-related errors."""


class CouncilFailedError(CouncilError):
    """Raised when the Council cannot produce a valid result.

    This is raised when too many agents fail — never silently swallows errors.
    """

    def __init__(self, message: str, agent_errors: dict[str, str] | None = None):
        self.agent_errors = agent_errors or {}
        super().__init__(message)


class CouncilChairmanError(CouncilError):
    """Raised when the Chairman agent fails."""


class AgentParseError(CouncilError):
    """Raised when an agent returns invalid JSON that cannot be parsed."""

    def __init__(self, agent_id: str, message: str, raw_response: str = ""):
        self.agent_id = agent_id
        self.raw_response = raw_response
        super().__init__(f"Agent {agent_id}: {message}")