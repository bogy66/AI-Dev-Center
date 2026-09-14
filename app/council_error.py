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
    """Raised when the Chairman agent fails.

    `category` (CLAUDE-E2E-NIO-011A) classifies WHERE the failure
    occurred, so a caller can safely surface WHY without exposing raw
    prompts or provider internals, and so retry/repair policy can
    distinguish failure classes instead of treating every exception the
    same way:
      "provider_transport"      -- the Chairman provider call itself
                                    never produced a usable, parsed
                                    response after its own existing
                                    transport-level retry was exhausted.
      "no_valid_variant"        -- the Chairman returned zero final
                                    variants.
      "invalid_requirement_ref" -- a toolchain item referenced a
                                    requirement_ref that is not part of
                                    this CouncilInput.
      "invalid_recommendation"  -- the recommendation does not identify
                                    any of the returned final variants.
      "duplicate_variant_id"    -- (CLAUDE-ARCH-S2-014C) two or more
                                    final variants share the same id --
                                    an ambiguous identity that must never
                                    reach S2.3/S2.4/a human.
      "materializability_preference" -- the recommendation is not one
                                    of the automatically materializable
                                    final variants although at least one
                                    exists.
      "completeness_validation" -- (CLAUDE-E2E-NIO-010A) no final
                                    variant covers every binding
                                    Requirement.
    None when the category is not (yet) known -- e.g. for exceptions
    that are not raised by this module's own Chairman contract checks.
    """

    def __init__(self, message: str, *, category: str | None = None):
        self.category = category
        # The category is embedded into the message itself (not only
        # kept as an attribute) so it survives str(exc) -- the only form
        # that reaches CouncilResult.chairman_error once caught in
        # EngineeringCouncil.evaluate() (a plain str field, unchanged).
        if category:
            message = f"{message} [category={category}]"
        super().__init__(message)


class AgentParseError(CouncilError):
    """Raised when an agent returns invalid JSON that cannot be parsed."""

    def __init__(self, agent_id: str, message: str, raw_response: str = ""):
        self.agent_id = agent_id
        self.raw_response = raw_response
        super().__init__(f"Agent {agent_id}: {message}")