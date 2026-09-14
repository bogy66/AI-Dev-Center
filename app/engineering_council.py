"""Multi-KI Engineering Council — Orchestrator.

Runs three phases with a total of 7 separate LLM calls:
  Phase 1: A1, A2, A3 in parallel → AgentProposals (3 calls, isolated)
  Phase 2: A1, A2, A3 in parallel → AgentVoteSets    (3 calls, isolated votes)
  Phase 3: Chairman sequentially → CouncilResult      (1 call)

The Council is platform-neutral.  It contains no ESP32-, ESPHome-, or
any other stack-specific logic.  All stack awareness comes from the
CouncilInput provided by the caller.
"""

from __future__ import annotations

import json
import re
import threading
import uuid
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any, Callable

from app.ai_config import CouncilAgentConfig, CouncilConfig
from app.ai_requirement_discovery import LLMProvider
from app.council_error import (
    AgentParseError,
    CouncilChairmanError,
    CouncilFailedError,
)
from app.council_models import (
    AgentCallRecord,
    AgentProposal,
    AgentVote,
    AgentVoteSet,
    CouncilInput,
    CouncilResult,
    CouncilTrace,
    CouncilVariant,
    MergeDecision,
    ProposalSet,
    ToolchainItem,
    VerificationCoverage,
)
from app.council_prompts import (
    AGENT_ROLE_ENV_ARCHITECT,
    AGENT_ROLE_ENV_ARCHITECT_REVIEW,
    AGENT_ROLE_RISK,
    AGENT_ROLE_RISK_REVIEW,
    AGENT_ROLE_TOOLCHAIN,
    AGENT_ROLE_TOOLCHAIN_REVIEW,
    build_phase1_prompt,
    build_phase2_review_prompt,
    build_chairman_prompt,
)
from app.llm_provider_factory import create_council_provider
from app.logger import get_logger
from app.secret_resolver import SecretResolver
from app.execution_identity import execution_identity
from app.engineering_decision import (
    EngineeringReworkRequest,
    categorize_admissibility_reasons,
    validate_variants,
)
from app.engineering_decision import _format_candidate_evidence
from app.toolchain_materializer import ToolchainMaterializer
from app.verification import all_trusted_verification_groups

logger = get_logger("council")

AGENT_ROLES = {
    "A1": "environment_architect",
    "A2": "toolchain_integrator",
    "A3": "risk_assessor",
}

PHASE1_ROLE_PROMPTS = {
    "environment_architect": AGENT_ROLE_ENV_ARCHITECT,
    "toolchain_integrator": AGENT_ROLE_TOOLCHAIN,
    "risk_assessor": AGENT_ROLE_RISK,
}

PHASE2_ROLE_PROMPTS = {
    "environment_architect": AGENT_ROLE_ENV_ARCHITECT_REVIEW,
    "toolchain_integrator": AGENT_ROLE_TOOLCHAIN_REVIEW,
    "risk_assessor": AGENT_ROLE_RISK_REVIEW,
}

_AGENT_ID_TO_CONFIG_KEY = {
    "A1": "environment_architect",
    "A2": "toolchain_integrator",
    "A3": "risk_assessor",
}

_MAX_RETRIES = 1  # 1 initial try + 1 retry = 2 total

# CLAUDE-ADC-E2E-VERIFICATION-EVIDENCE-FIX-001: sentinel distinguishing
# "this candidate text failed to parse" from a genuinely parsed JSON
# value of `None` (a bare `null` document) -- `is not _JSON_PARSE_FAILED`
# must be used instead of `is not None` so a legitimately parsed null
# is never mistaken for a parse failure and retried against the next
# candidate/fallback.
_JSON_PARSE_FAILED = object()
_TOTAL_RETRY_MULTIPLIER = _MAX_RETRIES + 1
_TIMEOUT_GRACE_SECONDS = 15


def _outer_deadline(config: CouncilAgentConfig) -> float:
    """Total bounded deadline covering all permitted same-phase provider calls."""
    return time.monotonic() + config.timeout_seconds * _TOTAL_RETRY_MULTIPLIER + _TIMEOUT_GRACE_SECONDS


def _failure_category(error: Exception) -> str:
    """CLAUDE-E2E-NIO-011A: the safe, deterministic category for a
    Chairman-synthesis-validation failure. Prefers CouncilChairmanError's
    own `.category`; falls back to the inline "[category=...]" tag used
    by _validate_toolchain_requirement_refs()'s ValueError (which cannot
    carry a real attribute, since it is a plain ValueError shared with
    other, non-Chairman-specific callers); "unknown" only if neither is
    present."""
    category = getattr(error, "category", None)
    if category:
        return category
    return _failure_category_from_text(str(error))


def _failure_category_from_text(message: str) -> str:
    """Extracts the LAST "[category=...]" tag in a message -- for a
    combined bounded-repair-exhausted message that embeds both attempts'
    tags, the last one is attempt 2's, the decisive/final outcome."""
    marker = "[category="
    start = message.rfind(marker)
    if start != -1:
        end = message.find("]", start)
        if end != -1:
            return message[start + len(marker):end]
    return "unknown"


# CLAUDE-ADC-COUNCIL-DIAGNOSTIC-CAPTURE-001 (corrected by CLAUDE-ADC-
# COUNCIL-DIAGNOSTIC-TRACE-INTEGRATION-FIX-001): bounded, deterministic
# reason vocabulary for a Phase-1 agent result that decoded successfully
# (res.success and res.parsed truthy -- a genuine LLM/parse failure is
# already covered by the existing agent_errors path and is NEVER
# reclassified here) but retained ZERO usable proposals. Every branch
# below is a read-only classification of data _phase1_independent_
# proposals() already computed for its own unchanged control flow --
# this diagnostic layer never feeds back into which proposals are kept,
# how many, or whether the Council is complete/degraded.
#
# CLAUDE-ADC-COUNCIL-DIAGNOSTIC-TRACE-INTEGRATION-FIX-001: the original
# CLAUDE-ADC-COUNCIL-DIAGNOSTIC-CAPTURE-001 task persisted this evidence
# to a NEW, dedicated JSONL file it opened itself
# (.diagnostic-traces/council_zero_proposal_events.jsonl) -- a parallel
# diagnostic subsystem the current task corrects. This evidence is now
# folded into the SAME central app.diagnostic_trace.DiagnosticTrace
# pipeline every other DevelopmentWorkflow/EngineeringCouncil diagnostic
# already uses, through the EXISTING set_result_callback()/self._result()
# composition path (see _emit_structured_results()'s "no usable
# structured proposal" branch) -- EngineeringCouncil never opens a file
# for this itself.
_REASON_EMPTY_OBJECT = "empty_object"
_REASON_MISSING_VARIANTS = "missing_variants"
_REASON_EMPTY_VARIANTS = "empty_variants"
_REASON_ALL_CANDIDATES_REJECTED = "all_candidates_rejected"
_REASON_OTHER_INTERNAL = "other_internal"


def _safe_len(value: Any) -> int | None:
    """len(value) for anything sized (list, dict, string, tuple, set,
    ...), else None -- never raises. Shared by the "how many candidates
    were even present" diagnostic field and by _is_empty_container()
    below, so both agree on exactly what "sized" means."""
    try:
        return len(value)
    except TypeError:
        return None


def _is_empty_container(value: Any) -> bool:
    """True only for a genuinely empty, sized value (list, dict, string,
    tuple, set, ...) -- len(value) == 0. False for anything with no
    meaningful length (an int/float/bool) AND, just as importantly, for
    ANY NONEMPTY value regardless of its type.

    CLAUDE-ADC-COUNCIL-DIAGNOSTIC-HARDENING-FIX-001 (Codex review
    CDX-ADC-COUNCIL-DIAGNOSTIC-TRACE-REVIEW-001, finding F2): a nonempty
    malformed "variants" value (e.g. a dict or a string the LLM emitted
    instead of a list) must never be silently coerced into looking
    "empty" merely because it fails an `isinstance(..., list)` check --
    it genuinely carries content, just not in the expected shape. An
    EMPTY container of any of these types (e.g. "variants": {} or
    "variants": "") carries exactly as little information as an empty
    list and is honestly described the same way."""
    return _safe_len(value) == 0


def _classify_zero_proposal_reason(
    parsed: Any, variants_field: Any, rejected_candidates: list[dict],
) -> str:
    """Pure, deterministic classification of WHY one Phase-1 agent
    result -- already known to have decoded successfully and to have
    retained zero proposals -- ended up empty. Reads only the already-
    parsed structures the caller already has; never re-parses, never
    inspects raw text.

    A root that is not a mapping at all (e.g. the LLM's entire response
    decoded to `null`, a bare number, or an empty list) is neither of
    the two dict-shaped branches below and is never silently coerced
    into "empty_variants" -- it is the one narrowly-scoped, deterministic
    "other_internal" case.

    A present "variants" value is classified by ACTUAL emptiness
    (_is_empty_container()), never by type alone: a nonempty dict/string/
    other malformed shape is never "empty_variants" (F2, above) -- it
    either genuinely reflects rejected per-item processing
    ("all_candidates_rejected", whenever the caller's own loop over it
    -- unchanged -- produced at least one rejection) or falls back to
    the same explicit, deterministic "other_internal" this function
    already used for a non-mapping root."""
    if not isinstance(parsed, dict):
        return _REASON_OTHER_INTERNAL
    if not parsed:
        return _REASON_EMPTY_OBJECT
    if "variants" not in parsed:
        return _REASON_MISSING_VARIANTS
    if _is_empty_container(variants_field):
        return _REASON_EMPTY_VARIANTS
    if rejected_candidates:
        return _REASON_ALL_CANDIDATES_REJECTED
    # Unreachable in practice: the caller only invokes this when zero
    # proposals were retained from a non-empty `variants_field`, and its
    # own loop (unchanged) appends every failed item to
    # rejected_candidates -- a nonempty, iterable `variants_field` with
    # no rejections would already have retained at least one proposal.
    # Kept as an explicit, safe, deterministic fallback rather than a
    # silently-assumed "cannot happen".
    return _REASON_OTHER_INTERNAL


_MAX_CANDIDATE_IDENTIFIER_LENGTH = 200
# CLAUDE-ADC-COUNCIL-DIAGNOSTIC-PRIVACY-HARDENING-FIX-002 (Codex
# rereview CDX-ADC-COUNCIL-DIAGNOSTIC-HARDENING-REREVIEW-002, finding H1
# -- HIGH): a STRICT POSITIVE allowlist, not a "reject known-bad
# characters" denylist. The prior policy only rejected whitespace/
# control characters, which a compact (whitespace-free) JSON fragment
# such as `{"agent_reasoning":"...","credentials":{"secret":"..."}}`
# trivially satisfies while still being a fully structured, nested
# payload. Every real requirement/toolchain identifier in this codebase
# (see tests/*.py, app/*.py -- "req-1", "req-esphome-fw", ...) is a
# short alphanumeric token optionally joined with "-"/"_"/"." ; nothing
# else is ever a legitimate identifier, so nothing else is accepted --
# JSON/structured punctuation (quotes, braces, brackets, colons, equals
# signs, commas, slashes, backslashes) can never pass this regex
# regardless of whitespace.
_SAFE_CANDIDATE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _sanitized_candidate_identifier(value: Any) -> str | None:
    """CLAUDE-ADC-COUNCIL-DIAGNOSTIC-HARDENING-FIX-001/-PRIVACY-
    HARDENING-FIX-002 (Codex review CDX-ADC-COUNCIL-DIAGNOSTIC-TRACE-
    REVIEW-001 finding F1, hardened further by CDX-ADC-COUNCIL-
    DIAGNOSTIC-HARDENING-REREVIEW-002 finding H1 -- both HIGH, privacy
    bypass): a candidate's own requirement_ref/provided_by value is
    untrusted LLM output, read from a variant_data entry that is ALREADY
    being rejected here precisely because something about its shape is
    invalid -- there is no guarantee it is even a string, still less
    that it looks like a real identifier.
    `_candidate_rejection_diagnostic()` used to do `str(value)`
    unconditionally: for a nested object such as
    `{"agent_reasoning": "...", "credentials": {"secret": "sk-..."}}`,
    that flattens the ENTIRE nested structure -- including any forbidden
    key/value it carries -- into what DiagnosticTrace's own recursive
    allowlisting can only ever see as one ordinary, already-scalar
    string value; `_redact()`'s regexes only match an actual
    `key=value`/`key: value` shape in running text, not a Python dict
    repr. An EARLIER fix rejected only whitespace/control characters,
    which a COMPACT (no-whitespace) JSON string --
    `{"agent_reasoning":"...","credentials":{"secret":"..."}}` -- still
    satisfies while carrying exactly the same forbidden nested content.
    Central-trace allowlisting alone cannot catch either shape (it never
    re-parses a string value's own textual content); sanitization MUST
    happen here, at the producer, with a POSITIVE policy for what an
    identifier IS allowed to look like, never a denylist of what it must
    not contain.

    Returns the value UNCHANGED (stripped) only when it is already a
    plain string that, after stripping, consists ENTIRELY of
    `_SAFE_CANDIDATE_IDENTIFIER_RE` characters (letters, digits, `_`,
    `-`, `.`) and is no longer than a real requirement/toolchain
    identifier could reasonably be -- never re-stringified from any
    other type, never accepted merely for lacking whitespace. Returns
    None for anything else (wrong type, empty after stripping, too long,
    or containing ANY character outside that positive set -- including
    but not limited to quotes, braces, brackets, colons, equals signs,
    commas, slashes, backslashes, and all whitespace/control characters)
    so the caller drops it from the identifier list entirely rather than
    ever falling back to `str(value)`. Presence/type information for a
    rejected value is captured separately, by type name only (see
    _candidate_rejection_diagnostic()'s own `*_invalid_types` fields) --
    never by echoing the value or any part of it."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped or len(stripped) > _MAX_CANDIDATE_IDENTIFIER_LENGTH:
        return None
    if not _SAFE_CANDIDATE_IDENTIFIER_RE.match(stripped):
        return None
    return stripped


# CLAUDE-ADC-COUNCIL-DIAGNOSTIC-PRIVACY-HARDENING-FIX-002 (Codex
# rereview CDX-ADC-COUNCIL-DIAGNOSTIC-HARDENING-REREVIEW-002, finding H2
# -- HIGH): the ONLY categories app.engineering_council's own,
# hand-written validation code can legitimately raise while building a
# Phase-1 candidate (see _validate_toolchain_requirement_refs()'s own
# tagged ValueError). Every other possible failure inside
# _build_proposal_from_dict() -- a generic ValueError/TypeError from
# `float(data.get("confidence", ...))`, a malformed toolchain entry
# passed to ToolchainItem(...), etc. -- carries no trusted category tag
# of its own, and its exception message may itself echo arbitrary
# LLM-controlled input (e.g. confidence="[category=SOME_CANARY]" makes
# `float()` raise a ValueError whose OWN text embeds exactly that
# string). This CLOSED allowlist is the trust boundary: only a category
# that is a member of this exact, hand-maintained set may ever reach the
# persisted diagnostic; anything else -- however it was produced, and
# regardless of whether it superficially LOOKS like a legitimate tag --
# becomes "unknown", the same deterministic fallback
# _failure_category_from_text() already uses when no tag is present at
# all.
_TRUSTED_CANDIDATE_REJECTION_CATEGORIES = frozenset({"invalid_requirement_ref"})


def _trusted_candidate_rejection_category(exc: Exception) -> str:
    """CLAUDE-ADC-COUNCIL-DIAGNOSTIC-PRIVACY-HARDENING-FIX-002 (H2):
    `_failure_category()`/`_failure_category_from_text()` were designed
    for Chairman-synthesis-validation failures, where the only code that
    ever raises a "[category=...]"-tagged exception is this module's own
    trusted synthesis-repair path -- reusing that same text-extraction
    for a Phase-1 candidate-build failure is unsafe, because
    `_build_proposal_from_dict()` can also raise a completely generic,
    untagged exception whose message text is influenced by untrusted
    LLM-controlled input. This wraps `_failure_category()`'s own
    extraction (kept, unmodified, and still used unchanged for its
    original Chairman-side callers) with one additional check: the
    result must be a member of `_TRUSTED_CANDIDATE_REJECTION_CATEGORIES`
    or it is replaced with "unknown" -- so an attacker-crafted value
    that happens to produce a string matching the `[category=...]`
    pattern can never smuggle arbitrary text into a persisted diagnostic
    field merely by picking a tag this allowlist doesn't recognize."""
    category = _failure_category(exc)
    if category in _TRUSTED_CANDIDATE_REJECTION_CATEGORIES:
        return category
    return "unknown"


def _candidate_rejection_diagnostic(variant_data: Any, exc: Exception) -> dict:
    """Bounded, deterministic per-candidate rejection evidence for one
    Phase-1 variant_data entry that failed to build into an
    AgentProposal: a category drawn ONLY from
    `_TRUSTED_CANDIDATE_REJECTION_CATEGORIES`
    (_trusted_candidate_rejection_category(), CLAUDE-ADC-COUNCIL-
    DIAGNOSTIC-PRIVACY-HARDENING-FIX-002 finding H2 -- never
    `_failure_category()`'s raw, text-extracted result, which a
    generic/untagged exception's own message could be made to echo
    arbitrary LLM-controlled text through), plus -- only when present on
    this exact candidate's own toolchain entries, never the full
    candidate payload -- the offending requirement_ref/provided_by
    values, SANITIZED by _sanitized_candidate_identifier() (finding F1/
    H1): a value that is not already a safe, bounded, positively-
    allowlisted identifier string is NEVER stringified into the
    identifier lists -- only its Python type name is recorded, in a
    separate, explicitly-named field, so "something invalid was here,
    and what kind" remains visible without ever persisting its content.
    Carries no free-text exception message, no prompt, no raw
    response."""
    toolchain = variant_data.get("toolchain") if isinstance(variant_data, dict) else None
    if not isinstance(toolchain, list):
        toolchain = []

    requirement_refs: set[str] = set()
    requirement_ref_invalid_types: set[str] = set()
    provided_by: set[str] = set()
    provided_by_invalid_types: set[str] = set()

    for item in toolchain:
        if not isinstance(item, dict):
            continue
        raw_ref = item.get("requirement_ref")
        if raw_ref not in (None, ""):
            sanitized = _sanitized_candidate_identifier(raw_ref)
            if sanitized is not None:
                requirement_refs.add(sanitized)
            else:
                requirement_ref_invalid_types.add(type(raw_ref).__name__)
        raw_provided_by = item.get("provided_by")
        if raw_provided_by not in (None, ""):
            sanitized = _sanitized_candidate_identifier(raw_provided_by)
            if sanitized is not None:
                provided_by.add(sanitized)
            else:
                provided_by_invalid_types.add(type(raw_provided_by).__name__)

    return {
        "category": _trusted_candidate_rejection_category(exc),
        "rejected_requirement_refs": sorted(requirement_refs),
        "rejected_provided_by": sorted(provided_by),
        "rejected_requirement_ref_invalid_types": sorted(requirement_ref_invalid_types),
        "rejected_provided_by_invalid_types": sorted(provided_by_invalid_types),
    }


_FAILURE_SUBSYSTEM_BY_CATEGORY = {
    "provider_transport": "S2.2",
    "no_valid_variant": "S2.2",
    "invalid_recommendation": "S2.2",
    "invalid_requirement_ref": "S2.2",
    "completeness_validation": "S2.3",
    "platform_constraint": "S2.3",
    "materializability_conflict": "S2.3",
    "verification_coverage": "S2.3",
    "admissibility_validation": "S2.3",
}


def _failure_subsystem(category: str) -> str:
    """CLAUDE-ARCH-S2-012A, Part 28: maps a safe failure category to the
    S2 Subsubsystem that actually OWNS the corresponding rule, for
    Diagnostic Trace fault localization (e.g. a future failure
    classifiable approximately as "S2.2 PASS / S2.3 NIO:
    platform_constraint / S2.4 NOT REACHED / S2.5 NOT REACHED / S3 NOT
    REACHED"). Protocol-only failures (malformed/missing/invalid
    recommendation, transport) are S2.2's own; every engineering-
    admissibility category is S2.3's, since S2.2's own early check only
    ever calls INTO S2.3's validate_variants() rather than owning any
    admissibility rule itself."""
    return _FAILURE_SUBSYSTEM_BY_CATEGORY.get(category, "S2.2")


def _build_chairman_repair_prompt(original_prompt: str, error: Exception) -> str:
    """CLAUDE-E2E-NIO-011A, Part 5: the smallest targeted repair request
    -- reuses the ORIGINAL Chairman prompt verbatim (which already
    contains every proposal, cross-review, and binding-Requirement/
    Constraint fact the Chairman needs) and appends only the exact,
    already-safe, deterministic rejection reason (never raw prompts,
    credentials, or Chain-of-Thought -- `error` is always one of this
    module's own short, structured messages, the same ones already
    proven safe for diagnostics in CLAUDE-PRE-E2E-009C/CLAUDE-E2E-
    NIO-010A). Asks the Chairman to correct ONLY that deficiency rather
    than re-deriving a solution from scratch, and never invents,
    merges, or repairs a variant on ADC's own authority -- the Chairman
    remains the sole synthesizer (Part 7/8).

    CLAUDE-ARCH-S2-012D: when `error` is an EngineeringReworkRequest
    carrying an identity conflict, one additional static, technology-
    neutral hint sentence is appended, naming the exact offending item(s)
    already computed by S2.3 (identity_conflict_detail) and pointing at
    the ALREADY-DOCUMENTED technical_identity contract every synthesis
    prompt already states (see app.council_prompts). Root cause of
    Real-System-E2E #8: the prior repair prompt exposed only a bare
    `materializability_conflict=True` boolean, giving the Chairman no way
    to know WHICH toolchain item needed a technical_identity correction,
    so its one bounded repair attempt could not target the actual defect.
    This hint is itself deterministic, structured evidence -- it
    identifies the offending item, it never invents a fix or a value on
    ADC's own authority.

    CLAUDE-ADC-S23-INSTALL-METHOD-PRODUCER-REPAIR-FIX-001: an
    EngineeringReworkRequest carrying an install_method conflict
    (identity already resolved, but install_method itself does not match
    the controlled executor's fixed compatibility contract -- see
    app.engineering_decision._binding_item_rejection_category()) instead
    gets its OWN, distinct hint naming the exact offending item(s)
    (install_method_conflict_detail) and restating the closed
    install_method shape contract app.council_prompts already documents
    for Phase-1/Chairman synthesis, never the technical_identity hint --
    identity was never the problem for this category, so repeating that
    hint would misdirect the Chairman's one bounded repair attempt at a
    field that is already correct (root cause: a real Real-System-E2E run
    reached this exact defect with a genuinely valid technical_identity
    and a repair attempt that only ever knew how to suggest fixing
    technical_identity). The two hints are independent and both may be
    emitted when a variant genuinely carries both kinds of offending
    items."""
    hint = ""
    if (
        isinstance(error, EngineeringReworkRequest)
        and error.identity_conflict
        and error.identity_conflict_detail
    ):
        hint = (
            "\nHinweis zum Materialisierbarkeits-Mangel (fehlende/ungueltige "
            "technische Identitaet): die folgenden Toolchain-Items sind "
            "betroffen: "
            f"{', '.join(error.identity_conflict_detail)}. "
            "Falls es sich um ein python_package-Item handelt, setze "
            "technical_identity auf die exakte installierbare "
            "Distributionskennung (z.B. \"esphome\"), wenn der "
            "Anzeigename dafuer nicht bereits geeignet ist -- exakt wie "
            "oben im Schema bereits gefordert."
        )
    if (
        isinstance(error, EngineeringReworkRequest)
        and error.install_method_conflict
        and error.install_method_conflict_detail
    ):
        hint = hint + (
            "\nHinweis zum Materialisierbarkeits-Mangel (install_method): "
            "die folgenden Toolchain-Items sind betroffen: "
            f"{', '.join(error.install_method_conflict_detail)}. Die "
            "technische Identitaet dieser Items ist bereits gueltig -- "
            "korrigiere AUSSCHLIESSLICH install_method, niemals "
            "technical_identity oder name. install_method muss fuer ein "
            "python_package-Item exakt eine der folgenden Formen haben: "
            "\"pip\", \"python_package\", \"pip install <technical_identity>\" "
            "oder \"python -m pip install <technical_identity>\" -- kein "
            "zusammengesetzter Shell-Befehl, keine venv-Aktivierung, kein "
            "Docker-Kommando. Eine venv-, Container- oder Host-Platzierung "
            "gehoert ausschliesslich in \"environment\"/\"purpose\"/"
            "\"description\", niemals in install_method oder name."
        )
    if (
        isinstance(error, EngineeringReworkRequest)
        and error.verification_feasibility_conflict
        and error.verification_feasibility_conflict_detail
    ):
        # CLAUDE-ARCH-S2-013F: name the exact mechanism/evidence pair and
        # the precise compatibility/control reason S2.3 computed (see
        # app.engineering_decision._verification_feasibility_gap_diagnostics()),
        # the same "name the exact field at fault" precedent 012D
        # established for materializability, applied to verification
        # feasibility so a bounded repair can target the real defect.
        hint = hint + (
            "\nHinweis zum Verifikations-Mangel (S2.3 Verification "
            "Feasibility): "
            f"{'; '.join(error.verification_feasibility_conflict_detail)}. "
            "Korrigiere entweder den mechanism-Wert auf einen, den das "
            "referenzierte ToolchainItem tatsaechlich in seinem eigenen "
            "provides_verification deklariert, oder die evidence auf ein "
            "ToolchainItem DERSELBEN Variante, das den bereits gewaehlten "
            "mechanism deklariert -- exakt wie oben im Schema unter "
            "VERIFICATION_COVERAGE gefordert. Bei kind=\"manual_review\" "
            "setze zusaetzlich \"human_governed\": true."
        )
    return (
        f"{original_prompt}\n\n"
        "---\n"
        "KORREKTUR ERFORDERLICH: Deine vorherige Antwort wurde von der "
        "deterministischen Validierung abgelehnt:\n"
        f"{error}\n"
        f"{hint}\n\n"
        "Behebe AUSSCHLIESSLICH diesen konkreten Mangel. Nutze weiterhin "
        "ausschliesslich die oben aufgefuehrten Requirements, "
        "Agenten-Vorschlaege und Bewertungen -- erfinde keine neuen "
        "Requirements oder Vorschlaege. Gib erneut eine vollstaendige, "
        "valide JSON-Antwort im exakt gleichen Schema zurueck."
    )


@dataclass
class _AgentTask:
    agent_id: str
    role: str
    config: CouncilAgentConfig
    prompt: str
    phase: str
    started_at: datetime
    activity_closed: threading.Event = field(default_factory=threading.Event)


@dataclass
class _AgentResult:
    agent_id: str
    success: bool
    parsed: dict[str, Any] | None = None
    raw_response: str = ""
    error: str | None = None


@dataclass(frozen=True)
class _CouncilQuorum:
    complete: bool
    degraded: bool
    phase1_agents: int
    phase2_agents: int


def _get_agent_config(council_config: CouncilConfig, agent_id: str) -> CouncilAgentConfig:
    role = _AGENT_ID_TO_CONFIG_KEY[agent_id]
    return getattr(council_config, role)


def _parse_verification_coverage(data: list) -> tuple[VerificationCoverage, ...]:
    """CLAUDE-ARCH-S2-013E: parses the (optional, additive) structured
    verification_coverage array an agent/Chairman JSON response may
    supply, exactly mirroring the toolchain-item parsing style already
    established for technical_identity -- never invents a mechanism/kind/
    evidence value the response itself did not provide."""
    return tuple(
        VerificationCoverage(
            requirement_refs=tuple(vc.get("requirement_refs", []) or []),
            kind=vc.get("kind", ""),
            mechanism=vc.get("mechanism", ""),
            evidence=vc.get("evidence", ""),
            human_governed=bool(vc.get("human_governed", False)),
        )
        for vc in (data or [])
    )


class EngineeringCouncil:
    """Multi-Agent Engineering Council with 3 phases and 7 LLM calls.

    Phase 1: 3 independent agents propose variants (parallel, isolated).
    Phase 2: 3 agents cross-review all proposals (parallel, votes isolated).
    Phase 3: Chairman synthesises CouncilResult (1 call).

    The Council NEVER performs installations, activates hardware, or
    executes destructive actions.  It ONLY produces data.
    """

    def __init__(
        self,
        council_config: CouncilConfig,
        secret_resolver: SecretResolver,
        trace_dir: Path | None = None,
    ):
        if not council_config.enabled:
            raise ValueError("CouncilConfig.enabled must be True")
        self._config = council_config
        self._secret_resolver = secret_resolver
        self._trace_dir = trace_dir
        self._call_records: list[AgentCallRecord] = []
        self._run_id: str = ""
        self._activity_callback: Callable[..., None] | None = None
        self._result_callback: Callable[..., None] | None = None
        self._effective_prompts: dict[str, str] = {}
        # CLAUDE-E2E-NIO-011A: bounded Chairman-synthesis-repair
        # bookkeeping for THIS evaluate() run only -- reset at the start
        # of _phase3_chairman_synthesis(), read back by
        # _emit_structured_results() to expose safe failure diagnostics
        # (never a new CouncilResult field, to avoid an unrelated schema
        # change for what is purely observability bookkeeping).
        self._chairman_attempts: int = 0
        self._chairman_repair_used: bool = False
        # CLAUDE-ADC-COUNCIL-DIAGNOSTIC-TRACE-INTEGRATION-FIX-001: SAME
        # kind of per-evaluate()-run-only bookkeeping as
        # _chairman_attempts above -- reset at the start of
        # _phase1_independent_proposals(), read back by
        # _emit_structured_results() to fold bounded zero-retained-
        # proposal branch evidence into the existing central
        # DiagnosticTrace event for that agent. Never a new CouncilResult
        # field, never persisted by this class itself.
        self._zero_proposal_diagnostics: dict[str, dict] = {}

    def set_activity_callback(self, callback: Callable[..., None] | None) -> None:
        """Project safe Council runtime activity into the central trace."""
        self._activity_callback = callback

    def set_result_callback(self, callback: Callable[..., None] | None) -> None:
        """Project safe structured Council work products into the central trace."""
        self._result_callback = callback

    def _result(self, **result) -> None:
        if self._result_callback is None:
            return
        try:
            self._result_callback(**result)
        except Exception:
            logger.debug("Central Council result recording failed", exc_info=True)

    def _activity(
        self, task: _AgentTask, state: str, *, force: bool = False,
        failure_category: str | None = None,
    ) -> None:
        if task.activity_closed.is_set() and not force:
            return
        if self._activity_callback is None:
            return
        try:
            operation = {"phase1": "proposal", "phase2": "review"}.get(
                task.phase, task.phase,
            )
            details = dict(
                actor=f"Agent {task.agent_id}" if task.agent_id != "C" else "Chairman",
                actor_role=task.role,
                runtime_state=state,
                council_phase=task.phase,
                provider=task.config.provider,
                model=task.config.model,
                execution_identity=execution_identity(
                    "chairman" if task.agent_id == "C" else f"council_agent_{task.agent_id.lower()}_{operation}",
                    provider=task.config.provider, model=task.config.model,
                    actor=task.agent_id, phase=task.phase,
                ),
            )
            if failure_category:
                details["failure_category"] = failure_category
            if state == "thinking" and task.prompt:
                details["effective_prompt"] = task.prompt
            self._activity_callback(**details)
        except Exception:
            # Observability must never change Council decisions or execution.
            logger.debug("Central Council activity recording failed", exc_info=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(self, council_input: CouncilInput) -> CouncilResult:
        """Run the full multi-agent council and return the synthesised result.

        Raises:
            CouncilFailedError: If too few agents succeeded to produce
                a meaningful result.
        """
        self._run_id = f"council-{uuid.uuid4().hex[:12]}"
        self._call_records.clear()
        started = datetime.now()

        phase1_start = time.monotonic()
        proposal_set = self._phase1_independent_proposals(council_input)
        phase1_ms = (time.monotonic() - phase1_start) * 1000
        proposal_set = ProposalSet(
            proposals=proposal_set.proposals,
            phase_duration_ms=phase1_ms,
            agent_errors=proposal_set.agent_errors,
        )

        vote_sets: tuple[AgentVoteSet, ...] = ()
        vote_errors: tuple[str, ...] = ()
        if proposal_set.proposals:
            vote_sets, vote_errors = self._phase2_cross_review(proposal_set)

        chairman_error: str | None = None
        council_result: CouncilResult

        if not proposal_set.proposals:
            chairman_error = "Keine Variantenvorschläge aus Phase 1 — keine Agenten erfolgreich."
            council_result = self._build_empty_result(council_input, chairman_error)
        else:
            try:
                council_result = self._phase3_chairman_synthesis(
                    proposal_set, vote_sets, council_input
                )
            except Exception as exc:
                chairman_error = str(exc)
                council_result = self._build_empty_result(council_input, chairman_error)

        total_errors = list(proposal_set.agent_errors)
        total_errors.extend(vote_errors)
        if chairman_error:
            total_errors.append(f"Chairman: {chairman_error}")

        quorum = self._evaluate_quorum(
            proposal_set,
            vote_sets,
            council_result,
            chairman_error,
            tuple(total_errors),
        )

        if not council_result.variants and not proposal_set.agent_errors:
            council_result = CouncilResult(
                id=self._run_id,
                project_id=council_input.project_id,
                stack=council_input.detected_stack or "",
                agent_errors=tuple(total_errors),
                chairman_error=chairman_error,
                council_complete=False,
                council_degraded=False,
                total_llm_calls=len(self._call_records),
            )

        council_result = CouncilResult(
            id=council_result.id or self._run_id,
            project_id=council_result.project_id or council_input.project_id,
            stack=council_result.stack or council_input.detected_stack or "",
            variants=council_result.variants,
            rejected_variants=council_result.rejected_variants,
            recommendation=council_result.recommendation,
            reasoning=council_result.reasoning,
            merge_decisions=council_result.merge_decisions,
            agent_errors=tuple(total_errors),
            chairman_error=chairman_error,
            council_complete=quorum.complete,
            council_degraded=quorum.degraded,
            total_llm_calls=len(self._call_records),
        )

        self._emit_structured_results(
            council_input, proposal_set, vote_sets, council_result,
        )

        if self._trace_dir:
            self._persist_trace(council_input, proposal_set, vote_sets, council_result, started)

        return council_result

    @staticmethod
    def _evaluate_quorum(
        proposal_set: ProposalSet,
        vote_sets: tuple[AgentVoteSet, ...],
        council_result: CouncilResult,
        chairman_error: str | None,
        unresolved_errors: tuple[str, ...],
    ) -> _CouncilQuorum:
        """Evaluate the single authoritative Council completion policy."""
        phase1_agents = len({proposal.agent_id for proposal in proposal_set.proposals})
        phase2_agents = len({vote_set.agent_id for vote_set in vote_sets})
        variant_ids = {variant.id for variant in council_result.variants}
        chairman_valid = (
            chairman_error is None
            and bool(variant_ids)
            and council_result.recommendation in variant_ids
        )
        complete = (
            phase1_agents >= 2
            and phase2_agents >= 2
            and chairman_valid
        )
        normal = (
            complete
            and phase1_agents == 3
            and phase2_agents == 3
            and not unresolved_errors
        )
        return _CouncilQuorum(
            complete=complete,
            degraded=complete and not normal,
            phase1_agents=phase1_agents,
            phase2_agents=phase2_agents,
        )

    def _emit_structured_results(
        self, council_input: CouncilInput, proposal_set: ProposalSet,
        vote_sets: tuple[AgentVoteSet, ...], council_result: CouncilResult,
    ) -> None:
        """Emit bounded projections only; never raw responses or reasoning fields."""
        def duration_for(agent_id, phase):
            return sum(
                record.duration_ms for record in self._call_records
                if record.agent_id == agent_id and record.phase == phase
            )

        def typed(data, data_type, source, destination):
            return {
                "type": data_type, "interface": "internal",
                "source": source, "destination": destination, "data": data,
            }

        requirements = [{
            "id": item.id, "name": item.name, "type": item.type,
            "purpose": item.purpose, "required": item.required,
        } for item in council_input.requirements]
        phase1_x_info = {
            "requirement_count": len(requirements),
            "stack": council_input.detected_stack or "",
        }
        phase1_x_verbose = {
            **phase1_x_info, "requirements": requirements,
            "project_files": list(council_input.project_files),
            "validation_warnings": list(council_input.validation_warnings),
        }

        proposal_agents = {proposal.agent_id for proposal in proposal_set.proposals}
        for proposal in proposal_set.proposals:
            tools = [{
                "requirement_ref": tool.requirement_ref, "name": tool.name,
                "type": tool.type, "version": tool.version,
                "purpose": tool.purpose, "depends_on": list(tool.depends_on),
                "state": tool.state,
                "environment_constraint": tool.environment_constraint,
            } for tool in proposal.toolchain]
            info = {
                "summary": proposal.description or proposal.name,
                "name": proposal.name, "risks": list(proposal.risks[:3]),
                "constraints": list(proposal.disadvantages[:3]),
            }
            verbose = {**info,
                "variant_id": proposal.variant_id,
                "environment": proposal.environment,
                "capabilities": list(proposal.capabilities),
                "toolchain": [{"name": item["name"], "type": item["type"],
                               "state": item["state"], "purpose": item["purpose"]}
                              for item in tools],
                "advantages": list(proposal.advantages),
                "feasibility": proposal.feasibility,
            }
            very_verbose = {**verbose,
                "hardware_target": proposal.hardware_target,
                "connection": proposal.connection,
                "confidence": proposal.confidence,
                "toolchain": tools,
                "disadvantages": list(proposal.disadvantages),
            }
            prompt_key = f"{proposal.agent_id}:phase1"
            if prompt_key in self._effective_prompts:
                very_verbose["effective_prompt"] = self._effective_prompts[prompt_key]
            config = _get_agent_config(self._config, proposal.agent_id)
            self._result(
                actor=f"Agent {proposal.agent_id}", actor_role=proposal.agent_role,
                council_phase="phase1", result_kind="proposal",
                provider=config.provider, model=config.model,
                duration_ms=duration_for(proposal.agent_id, "phase1"),
                summary=f"{proposal.agent_id} proposal: {proposal.name}",
                council_output={"info": info, "verbose": verbose,
                                "very_verbose": very_verbose},
                interface_data={
                    "normal": {"summary": "Proposal input produced a structured proposal."},
                    "info": {"x": typed(phase1_x_info, "council_input", "engineering_council", f"council_agent_{proposal.agent_id.lower()}_proposal"),
                             "f": execution_identity(f"council_agent_{proposal.agent_id.lower()}_proposal", provider=config.provider, model=config.model, actor=proposal.agent_id, phase="phase1"),
                             "y": typed({"available": True, "name": proposal.name}, "proposal", f"council_agent_{proposal.agent_id.lower()}_proposal", "engineering_council")},
                    "verbose": {"x": typed(phase1_x_verbose, "council_input", "engineering_council", f"council_agent_{proposal.agent_id.lower()}_proposal"), "f": execution_identity(f"council_agent_{proposal.agent_id.lower()}_proposal", provider=config.provider, model=config.model, actor=proposal.agent_id, phase="phase1"), "y": typed(verbose, "proposal", f"council_agent_{proposal.agent_id.lower()}_proposal", "engineering_council")},
                    "very_verbose": {"x": typed(phase1_x_verbose, "council_input", "engineering_council", f"council_agent_{proposal.agent_id.lower()}_proposal"), "f": execution_identity(f"council_agent_{proposal.agent_id.lower()}_proposal", provider=config.provider, model=config.model, actor=proposal.agent_id, phase="phase1"), "y": typed(very_verbose, "proposal", f"council_agent_{proposal.agent_id.lower()}_proposal", "engineering_council")},
                },
            )
        for agent_id in sorted(set(AGENT_ROLES) - proposal_agents):
            config = _get_agent_config(self._config, agent_id)
            empty = {"summary": "No usable structured proposal produced."}
            # CLAUDE-ADC-COUNCIL-DIAGNOSTIC-TRACE-INTEGRATION-FIX-001:
            # fold the bounded zero-retained-proposal branch evidence
            # (see _phase1_independent_proposals()/_build_zero_proposal_
            # diagnostic()) into this SAME, already-existing central
            # DiagnosticTrace event -- never a second, parallel
            # diagnostic sink. Present ONLY in the "verbose"/
            # "very_verbose" projections (DiagnosticDetailLevel.VERBOSE
            # and above); "info" stays the existing minimal summary so
            # NORMAL/INFO never expose it (render_diagnostic_trace_
            # event()'s own level-gated _terminal_projection() picks
            # "info" at INFO and "verbose" at VERBOSE+ -- see that
            # function's own preference order).
            diagnostic = self._zero_proposal_diagnostics.get(agent_id)
            verbose_output = {**empty, **diagnostic} if diagnostic else dict(empty)
            self._result(
                actor=f"Agent {agent_id}", actor_role=AGENT_ROLES[agent_id],
                council_phase="phase1", result_kind="proposal",
                provider=config.provider, model=config.model,
                duration_ms=duration_for(agent_id, "phase1"),
                summary=empty["summary"],
                council_output={"info": empty, "verbose": verbose_output,
                                "very_verbose": verbose_output},
                interface_data={
                    "normal": {"summary": "Proposal input produced no usable structured proposal."},
                    "info": {"x": typed(phase1_x_info, "council_input", "engineering_council", f"council_agent_{agent_id.lower()}_proposal"), "f": execution_identity(f"council_agent_{agent_id.lower()}_proposal", provider=config.provider, model=config.model, actor=agent_id, phase="phase1"), "y": typed({"available": False}, "proposal", f"council_agent_{agent_id.lower()}_proposal", "engineering_council")},
                    "verbose": {"x": typed(phase1_x_verbose, "council_input", "engineering_council", f"council_agent_{agent_id.lower()}_proposal"), "f": execution_identity(f"council_agent_{agent_id.lower()}_proposal", provider=config.provider, model=config.model, actor=agent_id, phase="phase1"), "y": typed({"available": False}, "proposal", f"council_agent_{agent_id.lower()}_proposal", "engineering_council")},
                    "very_verbose": {"x": typed(phase1_x_verbose, "council_input", "engineering_council", f"council_agent_{agent_id.lower()}_proposal"), "f": execution_identity(f"council_agent_{agent_id.lower()}_proposal", provider=config.provider, model=config.model, actor=agent_id, phase="phase1"), "y": typed({"available": False}, "proposal", f"council_agent_{agent_id.lower()}_proposal", "engineering_council")},
                },
            )

        review_agents = {vote_set.agent_id for vote_set in vote_sets}
        proposals_for_review = [{
            "variant_id": item.variant_id, "name": item.name,
            "description": item.description, "environment": item.environment,
            "capabilities": list(item.capabilities), "risks": list(item.risks),
        } for item in proposal_set.proposals]
        for vote_set in vote_sets:
            reviews = [{
                "variant_id": vote.variant_id,
                "would_recommend": vote.would_recommend,
                "concerns": list(vote.concerns), "scores": vote.scores,
            } for vote in vote_set.votes]
            info_reviews = [{
                "variant_id": item["variant_id"],
                "would_recommend": item["would_recommend"],
                "concerns": item["concerns"][:3],
            } for item in reviews]
            config = _get_agent_config(self._config, vote_set.agent_id)
            review_very_verbose = {
                "summary": f"Reviewed {len(reviews)} variants",
                "reviews": reviews,
            }
            prompt_key = f"{vote_set.agent_id}:phase2"
            if prompt_key in self._effective_prompts:
                review_very_verbose["effective_prompt"] = self._effective_prompts[prompt_key]
            self._result(
                actor=f"Agent {vote_set.agent_id}", actor_role=vote_set.agent_role,
                council_phase="phase2", result_kind="review",
                provider=config.provider, model=config.model,
                duration_ms=duration_for(vote_set.agent_id, "phase2"),
                summary=f"{vote_set.agent_id} reviewed {len(reviews)} variants",
                council_output={
                    "info": {"summary": f"Reviewed {len(reviews)} variants",
                             "reviews": info_reviews},
                    "verbose": {"summary": f"Reviewed {len(reviews)} variants",
                                "reviews": reviews},
                    "very_verbose": review_very_verbose,
                },
                interface_data={
                    "normal": {"summary": "Proposal variants produced a structured review."},
                    "info": {"x": typed({"proposal_count": len(proposals_for_review)}, "proposal_set", "engineering_council", f"council_agent_{vote_set.agent_id.lower()}_review"),
                             "f": execution_identity(f"council_agent_{vote_set.agent_id.lower()}_review", provider=config.provider, model=config.model, actor=vote_set.agent_id, phase="phase2"),
                             "y": typed({"review_count": len(reviews)}, "review_set", f"council_agent_{vote_set.agent_id.lower()}_review", "engineering_council")},
                    "verbose": {"x": typed({"proposals": proposals_for_review}, "proposal_set", "engineering_council", f"council_agent_{vote_set.agent_id.lower()}_review"),
                                "f": execution_identity(f"council_agent_{vote_set.agent_id.lower()}_review", provider=config.provider, model=config.model, actor=vote_set.agent_id, phase="phase2"),
                                "y": typed({"reviews": info_reviews}, "review_set", f"council_agent_{vote_set.agent_id.lower()}_review", "engineering_council")},
                    "very_verbose": {"x": typed({"proposals": proposals_for_review}, "proposal_set", "engineering_council", f"council_agent_{vote_set.agent_id.lower()}_review"),
                                     "f": execution_identity(f"council_agent_{vote_set.agent_id.lower()}_review", provider=config.provider, model=config.model, actor=vote_set.agent_id, phase="phase2"),
                                     "y": typed({"reviews": reviews}, "review_set", f"council_agent_{vote_set.agent_id.lower()}_review", "engineering_council")},
                },
            )
        for agent_id in sorted(set(AGENT_ROLES) - review_agents):
            config = _get_agent_config(self._config, agent_id)
            empty = {"summary": "No usable structured review produced."}
            self._result(
                actor=f"Agent {agent_id}", actor_role=AGENT_ROLES[agent_id],
                council_phase="phase2", result_kind="review",
                provider=config.provider, model=config.model,
                duration_ms=duration_for(agent_id, "phase2"),
                summary=empty["summary"],
                council_output={"info": empty, "verbose": empty,
                                "very_verbose": empty},
                interface_data={
                    "normal": {"summary": "Proposal variants produced no usable structured review."},
                    "info": {"x": typed({"proposal_count": len(proposals_for_review)}, "proposal_set", "engineering_council", f"council_agent_{agent_id.lower()}_review"),
                             "f": execution_identity(f"council_agent_{agent_id.lower()}_review", provider=config.provider, model=config.model, actor=agent_id, phase="phase2"),
                             "y": typed({"available": False}, "review_set", f"council_agent_{agent_id.lower()}_review", "engineering_council")},
                    "verbose": {"x": typed({"proposals": proposals_for_review}, "proposal_set", "engineering_council", f"council_agent_{agent_id.lower()}_review"),
                                "f": execution_identity(f"council_agent_{agent_id.lower()}_review", provider=config.provider, model=config.model, actor=agent_id, phase="phase2"),
                                "y": typed({"available": False}, "review_set", f"council_agent_{agent_id.lower()}_review", "engineering_council")},
                    "very_verbose": {"x": typed({"proposals": proposals_for_review}, "proposal_set", "engineering_council", f"council_agent_{agent_id.lower()}_review"),
                                     "f": execution_identity(f"council_agent_{agent_id.lower()}_review", provider=config.provider, model=config.model, actor=agent_id, phase="phase2"),
                                     "y": typed({"available": False}, "review_set", f"council_agent_{agent_id.lower()}_review", "engineering_council")},
                },
            )

        selected = next(
            (variant for variant in council_result.variants
             if variant.id == council_result.recommendation), None,
        )
        selected_name = selected.name if selected else None
        council_status = (
            "degraded" if council_result.council_degraded
            else "complete" if council_result.council_complete
            else "incomplete"
        )
        # CLAUDE-E2E-NIO-011A, Part 3: Real-System-E2E #6 exposed that a
        # concrete, already-computed council_result.chairman_error was
        # silently never surfaced here -- the human only ever saw the
        # generic "No final recommendation produced." fallback below,
        # even though a rich, safe, per-variant rejection reason already
        # existed internally (see the 010A completeness check and the
        # other _parse_chairman_result()/_phase3_chairman_synthesis()
        # CouncilChairmanError sites, all of which raise only our own
        # short, structured, already-redaction-safe messages -- never
        # raw prompts, Chain-of-Thought, or credentials).
        chairman_info = {
            "summary": (
                f"Selected {selected_name or council_result.recommendation}"
                if council_result.recommendation
                else (
                    f"Chairman failed: {council_result.chairman_error[:500]}"
                    if council_result.chairman_error
                    else "No final recommendation produced."
                )
            ),
            "recommendation": council_result.recommendation,
            "selected_approach": selected_name,
            "status": council_status,
            "council_complete": council_result.council_complete,
            "council_degraded": council_result.council_degraded,
            "chairman_error": (
                council_result.chairman_error[:1000] if council_result.chairman_error else None
            ),
            "chairman_failure_category": (
                _failure_category_from_text(council_result.chairman_error)
                if council_result.chairman_error else None
            ),
            "chairman_failure_subsystem": (
                _failure_subsystem(_failure_category_from_text(council_result.chairman_error))
                if council_result.chairman_error else None
            ),
            "chairman_attempts": self._chairman_attempts or None,
        }
        chairman_verbose = {**chairman_info,
            "preferred_variants": [variant.name for variant in council_result.variants],
            "rejected_variants": [variant.name for variant in council_result.rejected_variants],
            "merge_decisions": [{
                "merged_variant_ids": list(item.merged_variant_ids),
                "resulting_variant_id": item.resulting_variant_id,
                "reason": item.reason,
            } for item in council_result.merge_decisions],
        }
        chairman_very_verbose = {**chairman_verbose,
            "result_id": council_result.id,
            "council_complete": council_result.council_complete,
            "council_degraded": council_result.council_degraded,
            "error_count": len(council_result.agent_errors) + bool(council_result.chairman_error),
            "total_llm_calls": council_result.total_llm_calls,
            "variant_ids": [variant.id for variant in council_result.variants],
        }
        if "C:phase3" in self._effective_prompts:
            chairman_very_verbose["effective_prompt"] = self._effective_prompts["C:phase3"]
        self._result(
            actor="Chairman", actor_role="chairman", council_phase="phase3",
            result_kind="chairman_decision", provider=self._config.chairman.provider,
            model=self._config.chairman.model,
            duration_ms=duration_for("C", "phase3"),
            summary=chairman_info["summary"],
            council_output={"info": chairman_info, "verbose": chairman_verbose,
                            "very_verbose": chairman_very_verbose},
            interface_data={
                "normal": {"summary": "Council proposals and reviews produced a Chairman decision."},
                "info": {
                    "x": typed({"proposal_count": len(proposal_set.proposals),
                                "review_count": len(vote_sets)}, "council_review_set",
                               "engineering_council", "chairman"),
                    "f": execution_identity("chairman", provider=self._config.chairman.provider, model=self._config.chairman.model, actor="C", phase="phase3"),
                    "y": typed({"recommendation": council_result.recommendation,
                                "council_complete": council_result.council_complete,
                                "council_degraded": council_result.council_degraded},
                               "chairman_decision", "chairman", "engineering_council"),
                },
                "verbose": {
                    "x": typed({"proposals": proposals_for_review,
                          "reviews": [{"agent_id": item.agent_id,
                                       "review_count": len(item.votes)}
                                      for item in vote_sets]}, "council_review_set",
                               "engineering_council", "chairman"),
                    "f": execution_identity("chairman", provider=self._config.chairman.provider, model=self._config.chairman.model, actor="C", phase="phase3"),
                    "y": typed(chairman_verbose, "chairman_decision",
                               "chairman", "engineering_council"),
                },
                "very_verbose": {
                    "x": typed({"proposals": proposals_for_review,
                          "reviews": [{"agent_id": item.agent_id,
                                       "reviews": [{"variant_id": vote.variant_id,
                                                    "would_recommend": vote.would_recommend,
                                                    "concerns": list(vote.concerns),
                                                    "scores": vote.scores}
                                                   for vote in item.votes]}
                                      for item in vote_sets]}, "council_review_set",
                               "engineering_council", "chairman"),
                    "f": execution_identity("chairman", provider=self._config.chairman.provider, model=self._config.chairman.model, actor="C", phase="phase3"),
                    "y": typed(chairman_very_verbose, "chairman_decision",
                               "chairman", "engineering_council"),
                },
            },
        )

    # ------------------------------------------------------------------
    # Phase 1 — Independent Proposals
    # ------------------------------------------------------------------

    def _phase1_independent_proposals(self, council_input: CouncilInput) -> ProposalSet:
        # CLAUDE-ADC-COUNCIL-DIAGNOSTIC-TRACE-INTEGRATION-FIX-001: reset
        # for THIS evaluate() run only -- read back by
        # _emit_structured_results() (same lifecycle as
        # self._chairman_attempts/_chairman_repair_used above).
        self._zero_proposal_diagnostics = {}
        tasks = [
            _AgentTask(
                agent_id=aid,
                role=AGENT_ROLES[aid],
                config=_get_agent_config(self._config, aid),
                prompt=build_phase1_prompt(
                    council_input,
                    PHASE1_ROLE_PROMPTS[AGENT_ROLES[aid]],
                    self._config.max_variants_per_agent,
                ),
                phase="phase1",
                started_at=datetime.now(),
            )
            for aid in ("A1", "A2", "A3")
        ]

        results = self._execute_parallel(tasks, "phase1")

        all_proposals: list[AgentProposal] = []
        agent_errors: list[str] = []

        for res in results:
            if res.success and res.parsed:
                # CLAUDE-ADC-COUNCIL-DIAGNOSTIC-CAPTURE-001: `variants_field`
                # is read via the SAME, unchanged `res.parsed.get("variants",
                # [])` call the loop below already used -- diagnostics only
                # ever observe data this method already computed, never a
                # second parse/lookup, and the loop's own control flow
                # (what gets appended to all_proposals/agent_errors) is
                # byte-for-byte unchanged.
                variants_field = res.parsed.get("variants", [])
                retained_before = len(all_proposals)
                rejected_candidates: list[dict] = []
                for variant_data in variants_field:
                    try:
                        proposal = self._build_proposal_from_dict(
                            res.agent_id,
                            AGENT_ROLES.get(res.agent_id, ""),
                            variant_data,
                            res.raw_response,
                            council_input,
                        )
                        all_proposals.append(proposal)
                    except Exception as exc:
                        agent_errors.append(f"{res.agent_id}: build proposal failed — {exc}")
                        rejected_candidates.append(
                            _candidate_rejection_diagnostic(variant_data, exc)
                        )
                if len(all_proposals) == retained_before:
                    self._zero_proposal_diagnostics[res.agent_id] = (
                        self._build_zero_proposal_diagnostic(
                            council_input, res, variants_field, rejected_candidates,
                        )
                    )
            else:
                agent_errors.append(f"{res.agent_id}: {res.error or 'unknown error'}")
                if res.success:
                    # CLAUDE-ADC-COUNCIL-DIAGNOSTIC-CAPTURE-001: reached
                    # only when `res.success` is True but `res.parsed`
                    # is itself falsy (e.g. the LLM's entire response
                    # decoded to `{}` or `null`) -- decoded successfully,
                    # zero usable proposals, exactly the same diagnostic
                    # class as the branches above, just never reaching
                    # the `.get("variants", ...)` lookup at all. The
                    # `agent_errors` line above is completely unchanged
                    # by this -- this only ADDS the bounded diagnostic
                    # record alongside it.
                    self._zero_proposal_diagnostics[res.agent_id] = (
                        self._build_zero_proposal_diagnostic(
                            council_input, res, None, [],
                        )
                    )

        return ProposalSet(
            proposals=tuple(all_proposals),
            agent_errors=tuple(agent_errors),
        )

    def _phase1_attempt_count(self, agent_id: str) -> int:
        """How many Phase-1 LLM call attempts self._call_records already
        recorded for this agent -- read from the existing per-attempt
        AgentCallRecord bookkeeping _run_single_agent() already appends
        to; never a new capture surface. actor/phase/provider/model are
        NOT re-derived here: _emit_structured_results()'s existing
        self._result(actor=..., provider=..., model=..., council_phase=
        "phase1", ...) call already carries them for this same event."""
        return sum(
            1 for record in self._call_records
            if record.agent_id == agent_id and record.phase == "phase1"
        )

    def _build_zero_proposal_diagnostic(
        self, council_input: CouncilInput, res: "_AgentResult",
        variants_field: Any, rejected_candidates: list[dict],
    ) -> dict:
        """CLAUDE-ADC-COUNCIL-DIAGNOSTIC-TRACE-INTEGRATION-FIX-001: bounded,
        allowlisted-fields-only branch-classification evidence for a
        Phase-1 agent result that decoded successfully but retained zero
        proposals -- never raw prompts/responses/reasoning, never
        unbounded text. Pure data only: this method never persists
        anything itself. The caller stores the result in
        self._zero_proposal_diagnostics; _emit_structured_results() folds
        it into the SAME central DiagnosticTrace event this agent's
        "no usable structured proposal" outcome already produces via the
        existing set_result_callback()/self._result() composition path
        -- never a second, parallel diagnostic sink."""
        parsed = res.parsed
        return {
            "reason": _classify_zero_proposal_reason(
                parsed, variants_field, rejected_candidates,
            ),
            "root_parsed_type": type(parsed).__name__,
            "variants_field_present": (
                isinstance(parsed, dict) and "variants" in parsed
            ),
            "variants_field_type": (
                type(variants_field).__name__ if variants_field is not None else None
            ),
            "variants_field_count": _safe_len(variants_field),
            "requirement_ids": sorted(
                requirement.id for requirement in council_input.requirements
            ),
            "rejected_candidates": rejected_candidates,
            "attempt": self._phase1_attempt_count(res.agent_id),
        }

    def _build_proposal_from_dict(
        self,
        agent_id: str,
        agent_role: str,
        data: dict,
        raw_response: str,
        council_input: CouncilInput,
    ) -> AgentProposal:
        self._validate_toolchain_requirement_refs(
            data.get("toolchain", []), council_input
        )
        toolchain = tuple(
            ToolchainItem(
                requirement_ref=t.get("requirement_ref", ""),
                name=t.get("name", ""),
                technical_identity=t.get("technical_identity"),
                type=t.get("type", ""),
                install_method=t.get("install_method"),
                version=t.get("version"),
                purpose=t.get("purpose", ""),
                depends_on=tuple(t.get("depends_on", []) or []),
                state=t.get("state", "needs_install"),
                environment_constraint=t.get("environment_constraint"),
                provided_by=t.get("provided_by"),
                provides_verification=tuple(t.get("provides_verification", []) or []),
            )
            for t in data.get("toolchain", [])
        )

        return AgentProposal(
            variant_id=data.get("variant_id", f"{agent_id}-var-{uuid.uuid4().hex[:6]}"),
            agent_id=agent_id,
            agent_role=agent_role,
            name=data.get("name", f"{agent_id} Vorschlag"),
            description=data.get("description", ""),
            environment=data.get("environment", "host"),
            hardware_target=data.get("hardware_target"),
            connection=data.get("connection"),
            capabilities=tuple(data.get("capabilities", []) or []),
            toolchain=toolchain,
            advantages=tuple(data.get("advantages", []) or []),
            disadvantages=tuple(data.get("disadvantages", []) or []),
            risks=tuple(data.get("risks", []) or []),
            confidence=float(data.get("confidence", 0.5)),
            feasibility=data.get("feasibility", "medium"),
            verification=data.get("verification", ""),
            verification_coverage=_parse_verification_coverage(data.get("verification_coverage", [])),
            test_strategy=data.get("test_strategy"),
            agent_reasoning=data.get("agent_reasoning", ""),
            raw_llm_response=raw_response,
        )

    @staticmethod
    def _validate_toolchain_requirement_refs(
        toolchain: list[dict[str, Any]], council_input: CouncilInput
    ) -> None:
        """Require every toolchain item to reference this Council input."""
        requirement_ids = {requirement.id for requirement in council_input.requirements}
        for item in toolchain:
            requirement_ref = item.get("requirement_ref")
            if (
                not isinstance(requirement_ref, str)
                or not requirement_ref.strip()
                or requirement_ref not in requirement_ids
            ):
                raise ValueError(
                    "toolchain requirement_ref must exactly reference a current "
                    "CouncilInput requirement [category=invalid_requirement_ref]"
                )
            provided_by = item.get("provided_by")
            if provided_by is not None and (
                not isinstance(provided_by, str)
                or not provided_by.strip()
                or provided_by not in requirement_ids
            ):
                raise ValueError(
                    "toolchain provided_by must reference a current CouncilInput requirement"
                )

    # ------------------------------------------------------------------
    # Phase 2 — Cross-Review
    # ------------------------------------------------------------------

    def _phase2_cross_review(self, proposal_set: ProposalSet) -> tuple[tuple[AgentVoteSet, ...], tuple[str, ...]]:
        variants_json = json.dumps(
            [
                {
                    "variant_id": p.variant_id,
                    "agent_id": p.agent_id,
                    "agent_role": p.agent_role,
                    "name": p.name,
                    "description": p.description,
                    "environment": p.environment,
                    "hardware_target": p.hardware_target,
                    "connection": p.connection,
                    "capabilities": list(p.capabilities),
                    "toolchain": [
                        {
                            "requirement_ref": t.requirement_ref,
                            "name": t.name,
                            "technical_identity": t.technical_identity,
                            "type": t.type,
                            "install_method": t.install_method,
                            "version": t.version,
                            "purpose": t.purpose,
                            "depends_on": list(t.depends_on),
                            "state": t.state,
                            "environment_constraint": t.environment_constraint,
                            "provided_by": t.provided_by,
                            "provides_verification": list(t.provides_verification),
                        }
                        for t in p.toolchain
                    ],
                    "advantages": list(p.advantages),
                    "disadvantages": list(p.disadvantages),
                    "risks": list(p.risks),
                    "confidence": p.confidence,
                    "feasibility": p.feasibility,
                    "verification": p.verification,
                    "agent_reasoning": p.agent_reasoning,
                }
                for p in proposal_set.proposals
            ],
            indent=2,
            ensure_ascii=False,
        )

        tasks = [
            _AgentTask(
                agent_id=aid,
                role=AGENT_ROLES[aid],
                config=_get_agent_config(self._config, aid),
                prompt=build_phase2_review_prompt(
                    variants_json, PHASE2_ROLE_PROMPTS[AGENT_ROLES[aid]]
                ),
                phase="phase2",
                started_at=datetime.now(),
            )
            for aid in ("A1", "A2", "A3")
        ]

        results = self._execute_parallel(tasks, "phase2")

        vote_sets: list[AgentVoteSet] = []
        vote_errors: list[str] = []
        for res in results:
            if res.success and res.parsed:
                votes = tuple(
                    AgentVote(
                        agent_id=res.agent_id,
                        variant_id=v.get("variant_id", ""),
                        scores=v.get("scores", {}),
                        would_recommend=bool(v.get("would_recommend", False)),
                        reasoning=v.get("reasoning", ""),
                        concerns=tuple(v.get("concerns", []) or []),
                    )
                    for v in res.parsed.get("votes", [])
                )
                vote_sets.append(AgentVoteSet(
                    agent_id=res.agent_id,
                    agent_role=res.parsed.get("agent_role", ""),
                    votes=votes,
                ))
            else:
                vote_errors.append(f"{res.agent_id}: {res.error or 'unknown error'}")

        return tuple(vote_sets), tuple(vote_errors)

    # ------------------------------------------------------------------
    # Phase 3 — Chairman Synthesis
    # ------------------------------------------------------------------

    def _phase3_chairman_synthesis(
        self,
        proposal_set: ProposalSet,
        vote_sets: tuple[AgentVoteSet, ...],
        council_input: CouncilInput,
    ) -> CouncilResult:
        proposals_json = json.dumps(
            [
                {
                    "variant_id": p.variant_id,
                    "agent_id": p.agent_id,
                    "name": p.name,
                    "description": p.description,
                    "environment": p.environment,
                    "hardware_target": p.hardware_target,
                    "connection": p.connection,
                    "capabilities": list(p.capabilities),
                    "toolchain": [
                        {
                            "requirement_ref": t.requirement_ref,
                            "name": t.name,
                            "technical_identity": t.technical_identity,
                            "type": t.type,
                            "install_method": t.install_method,
                            "version": t.version,
                            "state": t.state,
                            "environment_constraint": t.environment_constraint,
                            "provided_by": t.provided_by,
                            "provides_verification": list(t.provides_verification),
                        }
                        for t in p.toolchain
                    ],
                    "controlled_setup": {
                        **ToolchainMaterializer().assess_variant(
                            CouncilVariant(
                                id=p.variant_id,
                                name=p.name,
                                toolchain=p.toolchain,
                            ),
                            council_input.preflight,
                        ),
                        "selection_guidance": (
                            "required_when_available"
                        ),
                    },
                    "advantages": list(p.advantages),
                    "disadvantages": list(p.disadvantages),
                    "risks": list(p.risks),
                }
                for p in proposal_set.proposals
            ],
            indent=2,
            ensure_ascii=False,
        )

        votes_json = json.dumps(
            [
                {
                    "agent_id": vs.agent_id,
                    "agent_role": vs.agent_role,
                    "votes": [
                        {
                            "variant_id": v.variant_id,
                            "scores": v.scores,
                            "would_recommend": v.would_recommend,
                            "reasoning": v.reasoning,
                            "concerns": list(v.concerns),
                        }
                        for v in vs.votes
                    ],
                }
                for vs in vote_sets
            ],
            indent=2,
            ensure_ascii=False,
        )

        prompt = build_chairman_prompt(proposals_json, votes_json, council_input)
        chairman_config = self._config.chairman

        task = _AgentTask(
            agent_id="C", role="chairman",
            config=chairman_config, prompt=prompt,
            phase="phase3", started_at=datetime.now(),
        )

        result = self._execute_parallel([task], "phase3")[0]

        if not result.success or not result.parsed:
            # CLAUDE-E2E-NIO-011A, Part 9.G: the Chairman provider call
            # already went through its OWN existing, separately-bounded
            # transport-level retry (_run_single_agent: 1 initial + 1
            # retry for both timeouts and malformed JSON, unchanged).
            # Reaching here means THAT policy is exhausted -- this is a
            # transport failure, never Engineering-synthesis-repairable,
            # and must never be confused with the bounded repair below
            # (which only ever runs once _parse_chairman_result() has
            # received a genuinely parsed response and rejected its
            # CONTENT, not its transport).
            self._chairman_attempts = 1
            raise CouncilChairmanError(
                f"Chairman failed: {result.error or 'no parsed output'}",
                category="provider_transport",
            )

        self._chairman_attempts = 1
        try:
            council_result = self._parse_chairman_result(result.parsed, council_input)
        except (CouncilChairmanError, ValueError) as first_error:
            # CLAUDE-E2E-NIO-011A, Part 5/6: the Chairman's own synthesis
            # PROTOCOL output was structurally rejected (transport
            # already succeeded -- this is categorically NOT a provider
            # failure). Rather than terminating planning immediately
            # (010A's own prior behaviour) or re-running the entire
            # Council, give the Chairman exactly ONE targeted repair
            # attempt armed with the exact deterministic rejection
            # reason, reusing the SAME proposals/votes/binding-
            # Requirement context already in `prompt` -- never a second,
            # independent Engineering Council run, and never a Python-
            # side merge of two Engineering solutions (Part 7/8: only
            # the Chairman synthesizes; deterministic code only
            # validates). This repair budget is shared with the
            # admissibility-triggered repair below -- at most ONE repair
            # attempt total, whichever fires first.
            self._chairman_repair_used = True
            repair_prompt = _build_chairman_repair_prompt(prompt, first_error)
            repair_task = _AgentTask(
                agent_id="C", role="chairman",
                config=chairman_config, prompt=repair_prompt,
                phase="phase3", started_at=datetime.now(),
            )
            repair_result = self._execute_parallel([repair_task], "phase3")[0]
            self._chairman_attempts = 2

            if not repair_result.success or not repair_result.parsed:
                raise CouncilChairmanError(
                    "Chairman synthesis failed after 2 attempt(s) (bounded "
                    f"repair exhausted); attempt 1: {first_error}; "
                    "attempt 2: Chairman failed: "
                    f"{repair_result.error or 'no parsed output'}",
                    category="provider_transport",
                ) from first_error

            try:
                council_result = self._parse_chairman_result(repair_result.parsed, council_input)
            except (CouncilChairmanError, ValueError) as second_error:
                raise CouncilChairmanError(
                    "Chairman synthesis failed after 2 attempt(s) (bounded "
                    f"repair exhausted); attempt 1: {first_error}; "
                    f"attempt 2: {second_error}",
                    category=_failure_category(second_error),
                ) from second_error
            # A structural repair already used the whole repair budget --
            # return the (now structurally valid) result as-is.
            # CLAUDE-ARCH-S2-012B: council_complete=True here reports
            # ONLY that the synthesis protocol is now structurally
            # complete -- it says nothing about S2.3 admissibility,
            # which is a separate, later concern (see class docstring).
            return council_result

        # CLAUDE-ARCH-S2-012B: the synthesis protocol succeeded on the
        # FIRST attempt. S2.2 now consults S2.3 (the single admissibility
        # authority, never re-implemented here) ONLY to decide whether a
        # bonus, still-bounded repair attempt is worth trying -- this
        # consultation NEVER changes whether this function returns
        # normally, and council_result.council_complete is ALREADY True
        # at this point regardless of the outcome below. If a repair is
        # attempted and STILL does not satisfy S2.3, or the repair call
        # itself fails, the ORIGINAL structurally-valid council_result is
        # kept and returned -- council_complete=True can therefore
        # coexist with an S2.3 rejection (including zero admissible
        # candidates), exactly as the documented governance requires.
        rework = self._admissibility_rework_evidence(council_result, council_input)
        if rework is not None:
            self._chairman_repair_used = True
            repair_prompt = _build_chairman_repair_prompt(prompt, rework)
            repair_task = _AgentTask(
                agent_id="C", role="chairman",
                config=chairman_config, prompt=repair_prompt,
                phase="phase3", started_at=datetime.now(),
            )
            repair_result = self._execute_parallel([repair_task], "phase3")[0]
            self._chairman_attempts = 2
            if repair_result.success and repair_result.parsed:
                try:
                    council_result = self._parse_chairman_result(repair_result.parsed, council_input)
                except (CouncilChairmanError, ValueError):
                    # The repair attempt itself broke the protocol --
                    # keep the ORIGINAL, structurally-valid result rather
                    # than failing a synthesis that already succeeded.
                    pass
            # A repair_result transport failure is likewise not a reason
            # to fail an already-structurally-complete synthesis -- keep
            # the original council_result.
        return council_result

    def _admissibility_rework_evidence(
        self, council_result: CouncilResult, council_input: CouncilInput,
    ) -> "EngineeringReworkRequest | None":
        """CLAUDE-ARCH-S2-012B: consults S2.3's own validate_variants()
        (never a duplicated rule) to decide whether the Chairman's
        recommendation is worth a bonus repair attempt. Returns None
        when admissible (or when the recommendation cannot be resolved
        to a real variant, which _parse_chairman_result() already
        guarantees cannot happen for a structurally valid result) --
        never raises, never affects council_complete."""
        recommended_variant = next(
            (v for v in council_result.variants if v.id == council_result.recommendation), None,
        )
        if recommended_variant is None:
            return None
        admissibility = validate_variants(
            (recommended_variant,), council_input.preflight, council_input.platform,
            all_trusted_verification_groups(council_input.project_intelligence),
        )[0]
        if admissibility.admissible:
            return None
        return EngineeringReworkRequest.from_validation(
            admissibility, platform=council_input.platform,
        )

    def _parse_chairman_result(self, parsed: dict, council_input: CouncilInput) -> CouncilResult:
        variants: list[CouncilVariant] = []
        for v in parsed.get("variants", []):
            self._validate_toolchain_requirement_refs(
                v.get("toolchain", []), council_input
            )
            variants.append(CouncilVariant(
                id=v.get("id", ""),
                name=v.get("name", ""),
                description=v.get("description", ""),
                origin_agents=tuple(v.get("origin_agents", []) or []),
                merged_from=tuple(v.get("merged_from", []) or []),
                rank=v.get("rank", 0),
                total_score=float(v.get("total_score", 0.0)),
                consensus_level=v.get("consensus_level", "unknown"),
                minority_opinions=tuple(v.get("minority_opinions", []) or []),
                environment=v.get("environment", "host"),
                hardware_target=v.get("hardware_target"),
                connection=v.get("connection"),
                capabilities=tuple(v.get("capabilities", []) or []),
                toolchain=tuple(
                    ToolchainItem(
                        requirement_ref=t.get("requirement_ref", ""),
                        name=t.get("name", ""),
                        technical_identity=t.get("technical_identity"),
                        type=t.get("type", ""),
                        install_method=t.get("install_method"),
                        version=t.get("version"),
                        purpose=t.get("purpose", ""),
                        depends_on=tuple(t.get("depends_on", []) or []),
                        state=t.get("state", "needs_install"),
                        environment_constraint=t.get("environment_constraint"),
                        provided_by=t.get("provided_by"),
                        provides_verification=tuple(t.get("provides_verification", []) or []),
                    )
                    for t in v.get("toolchain", [])
                ),
                advantages=tuple(v.get("advantages", []) or []),
                disadvantages=tuple(v.get("disadvantages", []) or []),
                risks=tuple(v.get("risks", []) or []),
                confidence=float(v.get("confidence", 0.5)),
                feasibility=v.get("feasibility", "medium"),
                verification=v.get("verification", ""),
                verification_coverage=_parse_verification_coverage(v.get("verification_coverage", [])),
                test_strategy=v.get("test_strategy"),
            ))

        rejected = tuple(
            CouncilVariant(
                id=rv.get("id", ""),
                name=rv.get("name", ""),
                description=rv.get("description", ""),
                origin_agents=tuple(rv.get("origin_agents", []) or []),
                merged_from=tuple(rv.get("merged_from", []) or []),
                rank=rv.get("rank", 99),
                total_score=float(rv.get("total_score", 0.0)),
                consensus_level=rv.get("consensus_level", "unknown"),
            )
            for rv in parsed.get("rejected_variants", [])
        )

        merges = tuple(
            MergeDecision(
                merged_variant_ids=tuple(md.get("merged_variant_ids", []) or []),
                resulting_variant_id=md.get("resulting_variant_id", ""),
                reason=md.get("reason", ""),
            )
            for md in parsed.get("merge_decisions", [])
        )

        recommendation = parsed.get("recommendation")
        variant_ids = {variant.id for variant in variants}
        if not variants:
            raise CouncilChairmanError(
                "Chairman produced no valid final variant",
                category="no_valid_variant",
            )
        # CLAUDE-ARCH-S2-014C (F3): a variant id must be unique and stable
        # across Council output -> S2.3 -> displayed engineering selection
        # -> human POST accept/select -> S2.5 EngineeringDecision -> S3
        # handoff. `variant_ids` above is a SET -- it silently collapses
        # duplicate ids, which let two DIFFERENT CouncilVariant objects
        # (different toolchain/verification_coverage/name) share one id.
        # Downstream code that resolves "the variant with id X" by
        # `next(v for v in variants if v.id == X)` (first match) and code
        # that instead builds a `{v.id: v for v in variants}` dict (last
        # match wins) would then silently resolve to TWO DIFFERENT
        # objects for the SAME id -- exactly the "human sees variant A,
        # submits its id, selector resolves variant B" defect
        # CDX-REVIEW-S2-014A reproduced. Structural protocol integrity
        # (this function's own, unchanged scope) is exactly where this
        # ambiguity must be rejected -- before S2.3, S2.4 or a human ever
        # sees it. Never silently renamed, never resolved by picking
        # first/last -- an ambiguous identity is a synthesis-protocol
        # defect, reported the same way every other structural violation
        # here is.
        if len(variants) != len(variant_ids):
            seen: set[str] = set()
            duplicate_ids = sorted({
                variant.id for variant in variants
                if variant.id in seen or seen.add(variant.id)
            })
            raise CouncilChairmanError(
                "Chairman produced two or more final variants sharing the "
                f"same id -- variant identity must be unique: {duplicate_ids!r}",
                category="duplicate_variant_id",
            )
        if not recommendation or recommendation not in variant_ids:
            raise CouncilChairmanError(
                "Chairman recommendation must identify a final Council "
                f"variant; got {recommendation!r}, known final variant ids: "
                f"{sorted(variant_ids)}",
                category="invalid_recommendation",
            )

        # CLAUDE-ARCH-S2-012B: _parse_chairman_result() is S2.2's own
        # SYNTHESIS PROTOCOL parser -- it validates only structural/
        # protocol integrity (valid requirement_ref references, at least
        # one final variant, a recommendation that identifies one of
        # them) and NEVER calls into S2.3's admissibility authority.
        # CLAUDE-ARCH-S2-012A previously added an S2.3 admissibility
        # check right here, which made `council_complete` conflate
        # "synthesis protocol succeeded" with "S2.3 considers the
        # recommendation admissible" -- an independent review correctly
        # rejected that: council_complete=True must be able to coexist
        # with an S2.3 rejection of the very same recommendation (see
        # _phase3_chairman_synthesis()'s _admissibility_rework_evidence()
        # for where that consultation now happens instead, WITHOUT
        # gating this function's return value). See the module/class
        # docstring update and the completion report for the full
        # RED-before-fix evidence.
        return CouncilResult(
            id=self._run_id,
            project_id=council_input.project_id,
            stack=council_input.detected_stack or "",
            variants=tuple(sorted(variants, key=lambda v: v.rank)),
            rejected_variants=rejected,
            recommendation=recommendation,
            reasoning=parsed.get("reasoning", ""),
            merge_decisions=merges,
            council_complete=True,
        )

    # ------------------------------------------------------------------
    # Parallel execution
    # ------------------------------------------------------------------

    def _execute_parallel(self, tasks: list[_AgentTask], phase: str) -> list[_AgentResult]:
        results_by_agent: dict[str, _AgentResult] = {}
        executor = ThreadPoolExecutor(max_workers=len(tasks))
        try:
            for task in tasks:
                self._activity(task, "waiting")
            futures = {executor.submit(self._run_single_agent, t): t for t in tasks}
            deadlines = {
                future: _outer_deadline(task.config)
                for future, task in futures.items()
            }
            pending = set(futures)

            while pending:
                now = time.monotonic()
                expired = {future for future in pending if deadlines[future] <= now}
                for future in expired:
                    task = futures[future]
                    task.activity_closed.set()
                    self._activity(
                        task, "failed", force=True, failure_category="timeout",
                    )
                    future.cancel()
                    error = "provider call exceeded its configured deadline"
                    results_by_agent[task.agent_id] = _AgentResult(
                        agent_id=task.agent_id, success=False, error=error,
                    )
                    self._call_records.append(AgentCallRecord(
                        agent_id=task.agent_id,
                        role=task.role,
                        provider=task.config.provider,
                        model=task.config.model,
                        temperature=task.config.temperature,
                        phase=phase,
                        started_at=task.started_at,
                        duration_ms=(task.config.timeout_seconds * _TOTAL_RETRY_MULTIPLIER + _TIMEOUT_GRACE_SECONDS) * 1000,
                        success=False,
                        error=error,
                    ))
                pending.difference_update(expired)
                if not pending:
                    break

                next_deadline = min(deadlines[future] for future in pending)
                completed, _ = wait(
                    pending,
                    timeout=max(0.0, next_deadline - time.monotonic()),
                    return_when=FIRST_COMPLETED,
                )
                for future in completed:
                    task = futures[future]
                    pending.remove(future)
                    try:
                        results_by_agent[task.agent_id] = future.result()
                    except Exception as exc:
                        self._activity(
                            task, "failed", failure_category="provider_failure",
                        )
                        logger.warning(f"Council agent {task.agent_id} failed: {exc}")
                        results_by_agent[task.agent_id] = _AgentResult(
                            agent_id=task.agent_id,
                            success=False,
                            error=str(exc),
                        )
                        self._call_records.append(AgentCallRecord(
                            agent_id=task.agent_id,
                            role=task.role,
                            provider=task.config.provider,
                            model=task.config.model,
                            temperature=task.config.temperature,
                            phase=phase,
                            started_at=task.started_at,
                            duration_ms=0,
                            success=False,
                            error=str(exc),
                        ))
        finally:
            # A context manager or wait=True would block on a provider that
            # violated its own HTTP timeout. Running calls cannot be killed by
            # ThreadPoolExecutor; close their activity and return control.
            executor.shutdown(wait=False, cancel_futures=True)

        return [results_by_agent[task.agent_id] for task in tasks]

    # ------------------------------------------------------------------
    # Single agent call with retry
    # ------------------------------------------------------------------

    def _run_single_agent(self, task: _AgentTask) -> _AgentResult:
        self._activity(task, "preparing")
        try:
            provider = create_council_provider(
                task.config,
                self._secret_resolver,
                self._config.ollama_url,
            )
        except Exception:
            self._activity(task, "failed", failure_category="provider_configuration")
            raise

        last_raw = ""
        for attempt in range(_MAX_RETRIES + 1):
            started = datetime.now()
            try:
                self._activity(task, "thinking")
                self._effective_prompts[f"{task.agent_id}:{task.phase}"] = task.prompt
                raw = provider.complete(task.prompt)
                last_raw = raw
                self._activity(task, "reviewing")
                duration_ms = (datetime.now() - started).total_seconds() * 1000
                parsed = self._parse_json_response(raw, task.agent_id)

                self._call_records.append(AgentCallRecord(
                    agent_id=task.agent_id,
                    role=task.role,
                    provider=task.config.provider,
                    model=task.config.model,
                    temperature=task.config.temperature,
                    phase=task.phase,
                    started_at=task.started_at,
                    duration_ms=duration_ms,
                    success=True,
                    raw_response_snippet=raw[:500],
                    structured_output_summary=str(list(parsed.keys()))[:500],
                ))

                result = _AgentResult(
                    agent_id=task.agent_id,
                    success=True,
                    parsed=parsed,
                    raw_response=raw,
                )
                self._activity(task, "completed")
                return result

            except Exception as exc:
                duration_ms = (datetime.now() - started).total_seconds() * 1000
                is_parse = isinstance(exc, AgentParseError)
                error_msg = (
                    f"JSON parse error (attempt {attempt + 1})"
                    if is_parse else f"{type(exc).__name__}: {exc}"
                )
                self._call_records.append(AgentCallRecord(
                    agent_id=task.agent_id,
                    role=task.role,
                    provider=task.config.provider,
                    model=task.config.model,
                    temperature=task.config.temperature,
                    phase=task.phase,
                    started_at=task.started_at,
                    duration_ms=duration_ms,
                    success=False,
                    error=error_msg,
                    raw_response_snippet=last_raw[:500] if last_raw else "",
                ))
                if attempt >= _MAX_RETRIES:
                    failure_cat = "invalid_json" if is_parse else "provider_failure"
                    self._activity(task, "failed", failure_category=failure_cat)
                    logger.warning(f"Agent {task.agent_id}: failed after {attempt + 1} attempts — {exc}")
                    return _AgentResult(
                        agent_id=task.agent_id,
                        success=False,
                        error=f"{'JSON parse' if is_parse else 'Provider'} error after {attempt + 1} attempts: {exc}",
                        raw_response=last_raw,
                    )
                if is_parse:
                    task.prompt = (
                        f"{task.prompt}\n\n"
                        f"DEINE VORHERIGE ANTWORT WAR KEIN VALIDES JSON. "
                        f"BITTE NUR VALIDES JSON ZURÜCKGEBEN — KEIN BEGLEITTEXT."
                    )

        return _AgentResult(
            agent_id=task.agent_id,
            success=False,
            error="Max retries exceeded",
            raw_response=last_raw,
        )

    def _parse_json_response(self, raw: str, agent_id: str) -> dict[str, Any]:
        """CLAUDE-ADC-E2E-VERIFICATION-EVIDENCE-FIX-001: each candidate
        text below is now tried with strict JSON first and, only if that
        fails, once more with `json.loads(..., strict=False)` before
        being treated as unparseable. LLMs routinely emit a literal,
        unescaped newline/tab inside a JSON string value (a multi-line
        shell command, a diagnostic message) instead of the RFC 8259-
        required \\n/\\t escape; Python's strict-mode parser rejects the
        ENTIRE response for that alone ("Invalid control character..."),
        forcing a wasted retry round-trip even though the JSON is
        otherwise well-formed. `strict=False` relaxes only that one
        literal-control-character-inside-a-string restriction -- it
        still requires genuinely valid JSON syntax (matching braces,
        quoted keys, valid escapes, no trailing commas, ...), so a
        response that is actually malformed still fails both attempts
        and still triggers the existing retry-then-fail path unchanged;
        structured-output validation is not diluted."""
        text = raw.strip()
        exceptions = []

        def _parse(candidate: str, label: str):
            try:
                return json.loads(candidate)
            except json.JSONDecodeError as e:
                exceptions.append(f"{label}{e}")
            try:
                return json.loads(candidate, strict=False)
            except json.JSONDecodeError as e:
                exceptions.append(f"{label}non-strict: {e}")
                return _JSON_PARSE_FAILED

        # Versuch 1: direktes JSON
        result = _parse(text, "")
        if result is not _JSON_PARSE_FAILED:
            return result

        # Versuch 2: JSON in Markdown-Codeblock
        import re
        m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if m:
            result = _parse(m.group(1).strip(), "codeblock: ")
            if result is not _JSON_PARSE_FAILED:
                return result

        # Versuch 3: erste { … } im Text
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            result = _parse(m.group(0), "brace-extraction: ")
            if result is not _JSON_PARSE_FAILED:
                return result

        raise AgentParseError(
            agent_id,
            f"Could not parse JSON: {'; '.join(exceptions)}",
            raw_response=raw,
        )

    # ------------------------------------------------------------------
    # Degraded / empty results
    # ------------------------------------------------------------------

    def _build_empty_result(self, council_input: CouncilInput, chairman_error: str) -> CouncilResult:
        return CouncilResult(
            id=self._run_id,
            project_id=council_input.project_id,
            stack=council_input.detected_stack or "",
            chairman_error=chairman_error,
            council_complete=False,
        )

    # ------------------------------------------------------------------
    # Trace persistence
    # ------------------------------------------------------------------

    def _persist_trace(
        self,
        council_input: CouncilInput,
        proposal_set: ProposalSet,
        vote_sets: tuple[AgentVoteSet, ...],
        council_result: CouncilResult,
        started_at: datetime,
    ) -> None:
        trace = CouncilTrace(
            id=self._run_id,
            project_id=council_input.project_id,
            council_result_id=council_result.id,
            council_input_summary={
                "project_id": council_input.project_id,
                "detected_stack": council_input.detected_stack,
                "platform": council_input.platform,
                "requirement_count": len(council_input.requirements),
                "requirements": [
                    {"id": r.id, "name": r.name, "type": r.type, "required": r.required}
                    for r in council_input.requirements
                ],
                "preflight_ready": (
                    council_input.preflight.overall_ready
                    if council_input.preflight else False
                ),
            },
            agent_call_records=tuple(self._call_records),
            raw_proposals=proposal_set.proposals,
            vote_sets=vote_sets,
            merge_decisions=council_result.merge_decisions,
            total_duration_ms=(datetime.now() - started_at).total_seconds() * 1000,
            errors=tuple(
                list(proposal_set.agent_errors)
                + ([f"Chairman: {council_result.chairman_error}"]
                   if council_result.chairman_error else [])
            ),
            started_at=started_at,
        )

        try:
            trace_subdir = self._trace_dir / council_input.project_id
            trace_subdir.mkdir(parents=True, exist_ok=True)

            path = trace_subdir / f"{self._run_id}.json"
            serialized = self._serialize_trace(trace)
            with path.open("w", encoding="utf-8") as f:
                json.dump(serialized, f, indent=2, ensure_ascii=False, default=str)

            logger.info(f"CouncilTrace persisted: {path}")
        except Exception as exc:
            logger.warning(f"Failed to persist CouncilTrace: {exc}")

    @staticmethod
    def _serialize_trace(trace: CouncilTrace) -> dict[str, Any]:
        return {
            "id": trace.id,
            "project_id": trace.project_id,
            "council_result_id": trace.council_result_id,
            "council_input_summary": trace.council_input_summary,
            "agent_call_records": [
                {
                    "agent_id": r.agent_id,
                    "role": r.role,
                    "provider": r.provider,
                    "model": r.model,
                    "temperature": r.temperature,
                    "phase": r.phase,
                    "started_at": r.started_at.isoformat(),
                    "duration_ms": r.duration_ms,
                    "success": r.success,
                    "error": r.error,
                    "raw_response_snippet": r.raw_response_snippet,
                    "structured_output_summary": r.structured_output_summary,
                }
                for r in trace.agent_call_records
            ],
            "raw_proposal_count": len(trace.raw_proposals),
            "vote_set_count": len(trace.vote_sets),
            "merge_decision_count": len(trace.merge_decisions),
            "total_duration_ms": trace.total_duration_ms,
            "errors": list(trace.errors),
            "started_at": trace.started_at.isoformat(),
            "completed_at": trace.completed_at.isoformat(),
        }
