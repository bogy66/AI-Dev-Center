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

from app.requirement_model import PreflightResult, Requirement, RequirementActivation


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
    project_intelligence: dict[str, Any] | None = None
    requirement_activations: tuple[RequirementActivation, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "requirements", _as_tuple(self.requirements))
        object.__setattr__(self, "project_files", _as_tuple(self.project_files))
        object.__setattr__(self, "validation_warnings", _as_tuple(self.validation_warnings))
        object.__setattr__(
            self, "requirement_activations", _as_tuple(self.requirement_activations)
        )


# ---------------------------------------------------------------------------
# Toolchain Item (per-tool granularity)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolchainItem:
    """A single tool or requirement within a toolchain variant.

    This is NOT a SetupStep.  SetupSteps are derived later by the
    ToolchainMaterializer from ToolchainItems.

    name is a human/display label (e.g. "ESPHome CLI") and is not
    guaranteed to be a valid technical identifier for any package
    manager or tool system. technical_identity is the explicit,
    structured, ecosystem-neutral technical identity Council supplies
    when it differs from the display name — for a python_package item
    this means the exact PyPI distribution name (e.g. "esphome"); for
    an executable/tool item it would mean the resolved binary/tool
    identifier (e.g. "cmake"). A future ecosystem adapter (npm, cargo,
    etc.) would interpret the same field as its own package identity —
    this is intentionally one generic field, not one per ecosystem.

    provides_verification (CLAUDE-ARCH-S2-013F): the verification
    mechanism identities (e.g. "pytest", "npm_test", "esphome_validate",
    "pip_show" — ADC's own controlled Python distribution
    package-presence check, CLAUDE-ADC-S23-VERIFICATION-EVIDENCE-
    ARCHITECTURE-001) this SAME item can actually run — a structured, producer-declared
    capability relation, exactly mirroring how `provided_by` already
    declares an install-dependency relation between two ToolchainItems in
    this same variant. S2.3's Verification Feasibility check
    (app.engineering_decision) uses this to mechanically prove that a
    VerificationCoverage.mechanism is compatible with the toolchain
    identity its evidence names — never via a hard-coded mechanism/
    ecosystem lookup table and never via fuzzy string matching (e.g.
    "pytest contains py"). This item's own `state` ("unavailable"
    specifically) is reused, unchanged, as the controllability/
    observability signal: a mechanism whose backing tool ADC cannot even
    obtain is not one it can control or observe.
    """

    requirement_ref: str
    name: str
    type: str
    technical_identity: str | None = None
    install_method: str | None = None
    version: str | None = None
    purpose: str = ""
    depends_on: tuple[str, ...] = ()
    state: str = "needs_install"
    environment_constraint: str | None = None
    provided_by: str | None = None
    provides_verification: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "depends_on", _as_tuple(self.depends_on))
        object.__setattr__(self, "provides_verification", _as_tuple(self.provides_verification))


# ---------------------------------------------------------------------------
# Verification Coverage (CLAUDE-ARCH-S2-013E)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VerificationCoverage:
    """Structured, technology-neutral evidence that a candidate's
    verification approach actually covers specific binding Requirement(s)
    with a mechanism ADC can recognize and later observe/control.

    This is a PRE-EXECUTION feasibility artifact only (S2.3 Engineering
    Admissibility, "Verification Feasibility"): it never runs anything and
    never proves a test will pass — S5 Quality & Verification remains
    solely responsible for actually executing and assessing verification.
    A free-text justification alone (e.g. "run tests") is deliberately
    NOT sufficient; `kind` and `mechanism` must be structured tokens, and
    `evidence` must name a concrete, already-structured identity already
    present on the same candidate (a ToolchainItem's requirement_ref,
    name or technical_identity), never inferred from prose.

    requirement_refs: which binding Requirement id(s) this one mechanism
        covers — a single mechanism may cover several (Requirement E),
        and a candidate may declare several mechanisms that jointly
        cover it (Requirement F).
    kind: a small, closed, ecosystem-neutral semantic category describing
        WHAT KIND of check this is (never a specific tool) — one of
        "test_command", "build_command", "static_analysis", "probe",
        "smoke_test", "config_validation", "manual_review". Mirrors
        app.verification.VerificationStep.verification_kind's own
        technology-neutral categorisation (test/build/validate/...)
        without creating a second source of truth: this module never
        imports app.verification, and app.verification never needs to
        import this — they describe the same kind of thing at two
        different pipeline stages (S2 feasibility vs. S5 execution) and
        are intentionally allowed to evolve independently.
    mechanism: a single structured technology identity (e.g. "pytest",
        "npm_test", "cargo_test", "go_test", "ctest", "platformio_test",
        "esphome_validate", "http_probe") — never a shell command, never
        free prose, never a closed Python-only allowlist; any concrete,
        single-token identity naming a real verification technology is
        acceptable, regardless of ecosystem.
    evidence: the structured identity (ToolchainItem.requirement_ref,
        .name or .technical_identity already present on this SAME
        candidate) that grounds why this mechanism is actually available/
        applicable here. For "manual_review", "probe" and
        "config_validation" — kinds with nothing to install — evidence
        may instead name one of `requirement_refs` itself.
    human_governed (CLAUDE-ARCH-S2-013F): for kind="manual_review" only —
        must be explicitly True to represent that this manual step is a
        deliberately governed human verification path (compatible with
        ADC's existing Human Approval governance), never an
        unacknowledged, silently-assumed manual step. A manual_review
        entry with human_governed=False (the default) never counts as
        feasible coverage — mechanism compatibility for the other kinds
        instead comes from a matching ToolchainItem.provides_verification
        (see there); manual_review has nothing to install, so it is
        proven governed rather than tool-compatible.
    area (CLAUDE-ARCH-S2-014D): the `ProjectArea.path` this coverage
        entry's verification actually runs in — optional, default None.
        Closes the trusted-verification scope leak the Generalized
        Verification module's own trusted_verification_identity_groups()
        used to have (project-wide aggregation letting capability
        detected in one area corroborate an unrelated area's
        requirement): S2.3's compatibility check now only accepts
        independent Project Intelligence evidence whose OWN scope
        matches (or, for evidence mechanically detected at the project
        root, covers) this field — never evidence bound to a different,
        unrelated area. Leaving it unset is only ever compatible with
        evidence Project Intelligence itself detected at the project
        root (the one case that is honestly project-wide by filesystem
        containment, never a default applied on its behalf).
    """

    requirement_refs: tuple[str, ...]
    kind: str
    mechanism: str
    evidence: str = ""
    human_governed: bool = False
    area: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "requirement_refs", _as_tuple(self.requirement_refs))


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
    verification_coverage: tuple[VerificationCoverage, ...] = ()
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
        object.__setattr__(self, "verification_coverage", _as_tuple(self.verification_coverage))


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
    verification_coverage: tuple[VerificationCoverage, ...] = ()
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
        object.__setattr__(self, "verification_coverage", _as_tuple(self.verification_coverage))


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
    council_degraded: bool = False

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
