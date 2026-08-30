"""Data models for the Multi-KI Engineering Council.

All dataclasses in this module are frozen and immutable.  They contain no
business logic, no LLM-specific code, and no framework-specific assumptions.

Existing models in ``requirement_model.py`` are NOT modified:
  Requirement, RequirementType, DiscoveryResult, ValidationResult,
  PreflightResult, SetupStep, SetupPlan
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.requirement_model import PreflightResult, Requirement


def _as_tuple(value):
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    try:
        return tuple(value)
    except TypeError:
        return ()


# ---------------------------------------------------------------------------
# Council Input
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CouncilInput:
    """All data the Council needs to produce variant proposals.

    Wiederverwendet Requirement und PreflightResult aus requirement_model.py.
    """

    requirements: tuple[Requirement, ...] = ()
    preflight: PreflightResult | None = None
    detected_stack: str | None = None
    adapter_requirements: dict[str, Any] | None = None
    project_id: str = ""
    project_files: tuple[str, ...] = ()
    platform: str = "linux"
    validation_warnings: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "requirements", _as_tuple(self.requirements))
        object.__setattr__(self, "project_files", _as_tuple(self.project_files))
        object.__setattr__(self, "validation_warnings", _as_tuple(self.validation_warnings))


# ---------------------------------------------------------------------------
# Toolchain Item (per-tool granularity)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolchainItem:
    """A single tool or requirement within a toolchain variant.

    This is NOT a SetupStep.  SetupSteps are derived later by the
    ToolchainMaterializer from ToolchainItems.
    """

    requirement_ref: str
    name: str
    type: str
    install_method: str | None = None
    version: str | None = None
    purpose: str = ""
    depends_on: tuple[str, ...] = ()
    state: str = "needs_install"
    environment_constraint: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "depends_on", _as_tuple(self.depends_on))


# ---------------------------------------------------------------------------
# Phase 1: Agent Proposals
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentProposal:
    """A single variant proposed by one agent in Phase 1."""

    variant_id: str
    agent_id: str
    agent_role: str
    name: str
    description: str = ""
    environment: str = "host"
    hardware_target: str | None = None
    connection: str | None = None
    capabilities: tuple[str, ...] = ()
    toolchain: tuple[ToolchainItem, ...] = ()
    advantages: tuple[str, ...] = ()
    disadvantages: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    confidence: float = 0.5
    feasibility: str = "medium"
    verification: str = ""
    test_strategy: dict[str, Any] | None = None
    agent_reasoning: str = ""
    raw_llm_response: str = ""
    generated_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        object.__setattr__(self, "capabilities", _as_tuple(self.capabilities))
        object.__setattr__(self, "toolchain", _as_tuple(self.toolchain))
        object.__setattr__(self, "advantages", _as_tuple(self.advantages))
        object.__setattr__(self, "disadvantages", _as_tuple(self.disadvantages))
        object.__setattr__(self, "risks", _as_tuple(self.risks))


@dataclass(frozen=True)
class ProposalSet:
    """All raw variant proposals from Phase 1 — before merging."""

    proposals: tuple[AgentProposal, ...] = ()
    phase_duration_ms: float = 0.0
    agent_errors: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "proposals", _as_tuple(self.proposals))
        object.__setattr__(self, "agent_errors", _as_tuple(self.agent_errors))


# ---------------------------------------------------------------------------
# Phase 2: Votes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentVote:
    """One agent's structured evaluation of one variant."""

    agent_id: str
    variant_id: str
    scores: dict[str, int] = field(default_factory=dict)
    would_recommend: bool = False
    reasoning: str = ""
    concerns: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "concerns", _as_tuple(self.concerns))


@dataclass(frozen=True)
class AgentVoteSet:
    """All votes from one agent in Phase 2."""

    agent_id: str
    agent_role: str = ""
    votes: tuple[AgentVote, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "votes", _as_tuple(self.votes))


# ---------------------------------------------------------------------------
# Phase 3: Chairman output
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MergeDecision:
    """Documents which variants were merged and why."""

    merged_variant_ids: tuple[str, ...] = ()
    resulting_variant_id: str = ""
    reason: str = ""

    def __post_init__(self):
        object.__setattr__(self, "merged_variant_ids", _as_tuple(self.merged_variant_ids))


@dataclass(frozen=True)
class CouncilVariant:
    """A consolidated (possibly merged) variant from the Chairman."""

    id: str
    name: str
    description: str = ""
    origin_agents: tuple[str, ...] = ()
    merged_from: tuple[str, ...] = ()

    environment: str = "host"
    hardware_target: str | None = None
    connection: str | None = None
    capabilities: tuple[str, ...] = ()
    toolchain: tuple[ToolchainItem, ...] = ()

    advantages: tuple[str, ...] = ()
    disadvantages: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    confidence: float = 0.5
    feasibility: str = "medium"
    verification: str = ""
    test_strategy: dict[str, Any] | None = None

    votes: tuple[AgentVote, ...] = ()
    average_scores: dict[str, float] = field(default_factory=dict)
    consensus_level: str = "unknown"
    minority_opinions: tuple[str, ...] = ()

    rank: int = 0
    total_score: float = 0.0

    def __post_init__(self):
        object.__setattr__(self, "origin_agents", _as_tuple(self.origin_agents))
        object.__setattr__(self, "merged_from", _as_tuple(self.merged_from))
        object.__setattr__(self, "capabilities", _as_tuple(self.capabilities))
        object.__setattr__(self, "toolchain", _as_tuple(self.toolchain))
        object.__setattr__(self, "advantages", _as_tuple(self.advantages))
        object.__setattr__(self, "disadvantages", _as_tuple(self.disadvantages))
        object.__setattr__(self, "risks", _as_tuple(self.risks))
        object.__setattr__(self, "votes", _as_tuple(self.votes))
        object.__setattr__(self, "minority_opinions", _as_tuple(self.minority_opinions))


@dataclass(frozen=True)
class CouncilResult:
    """Complete output of the Engineering Council."""

    id: str
    project_id: str
    stack: str = ""
    variants: tuple[CouncilVariant, ...] = ()
    rejected_variants: tuple[CouncilVariant, ...] = ()
    recommendation: str | None = None
    reasoning: str = ""
    merge_decisions: tuple[MergeDecision, ...] = ()
    agent_errors: tuple[str, ...] = ()
    chairman_error: str | None = None
    council_complete: bool = True
    total_llm_calls: int = 0
    generated_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        object.__setattr__(self, "variants", _as_tuple(self.variants))
        object.__setattr__(self, "rejected_variants", _as_tuple(self.rejected_variants))
        object.__setattr__(self, "merge_decisions", _as_tuple(self.merge_decisions))
        object.__setattr__(self, "agent_errors", _as_tuple(self.agent_errors))


# ---------------------------------------------------------------------------
# Audit / Trace
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentCallRecord:
    """Audit record for a single LLM call."""

    agent_id: str
    role: str
    provider: str
    model: str
    temperature: float
    phase: str
    started_at: datetime = field(default_factory=datetime.now)
    duration_ms: float = 0.0
    success: bool = False
    error: str | None = None
    raw_response_snippet: str = ""
    structured_output_summary: str = ""


@dataclass(frozen=True)
class CouncilTrace:
    """Complete audit trail of one Council run."""

    id: str
    project_id: str
    council_result_id: str = ""

    council_input_summary: dict[str, Any] = field(default_factory=dict)
    agent_call_records: tuple[AgentCallRecord, ...] = ()
    raw_proposals: tuple[AgentProposal, ...] = ()
    vote_sets: tuple[AgentVoteSet, ...] = ()
    merge_decisions: tuple[MergeDecision, ...] = ()
    total_duration_ms: float = 0.0
    errors: tuple[str, ...] = ()
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        object.__setattr__(self, "agent_call_records", _as_tuple(self.agent_call_records))
        object.__setattr__(self, "raw_proposals", _as_tuple(self.raw_proposals))
        object.__setattr__(self, "vote_sets", _as_tuple(self.vote_sets))
        object.__setattr__(self, "merge_decisions", _as_tuple(self.merge_decisions))
        object.__setattr__(self, "errors", _as_tuple(self.errors))