"""S2 Engineering candidate validation and variant selection
(CLAUDE-PRE-E2E-009B, corrected by CLAUDE-PRE-E2E-009C).

CLAUDE-ARCH-S2-012A -- Subsubsystem ownership of THIS module:

  S2.3 Engineering Admissibility (the SINGLE technical admissibility
  authority inside S2): validate_variants(), validate_candidates(),
  admissible_variants(), CandidateValidation, and every _covers_*/
  _violates_*/_is_materializable_* rule. Nothing else in ADC may
  independently re-implement these rules -- other Subsubsystems
  (S2.2's early rework check, in app/engineering_council.py) call
  THESE functions rather than re-deriving their own notion of
  admissibility (Part 10: "Cross-use is allowed. Duplicated AUTHORITY
  is not.").

  S2.4 Human Engineering Authority: resolve_human_engineering_selection()
  and describe_engineering_variant_selection() -- consumes ONLY S2.3's
  already-computed CandidateValidation set; decides WHICH admissible
  candidate is chosen (Chairman recommendation, honored unless a human
  override is given) and by WHOM (chairman/human/sole_admissible);
  never re-evaluates technical admissibility itself.

  S2.5 Engineering Decision & S3 Handoff: build_engineering_decision()
  and the EngineeringDecision artifact itself -- the only artifact
  that may normally cross the S2 -> S3 boundary (consumed by
  ToolchainMaterializer.materialize_decision() in
  app/toolchain_materializer.py, which performs no S2 selection logic
  of its own).

  select_engineering_variant() is the S2.3 -> S2.4 -> S2.5 PIPELINE
  entry point (kept as a single call for the overwhelming majority of
  callers that just want "the decision"), but is now a thin composition
  of three independently callable, independently testable functions --
  it does not itself decide or validate anything.

Documented ADC governance (ADC_Zielbild_Ausfuehrliche_Beschreibung.txt,
Abschnitt 2, "ZENTRALES GOVERNANCE-PRINZIP"):

    Council erzeugt Alternativen.
    Chairman: Synthese und Auswahl der Empfehlung.
    Der Benutzer kann die Empfehlung akzeptieren oder sich bewusst fuer
    eine andere zulaessige Variante entscheiden.
    ADC soll NICHT versuchen, bei identischem Input immer dieselbe
    Loesungsklasse zu erzwingen.

CLAUDE-PRE-E2E-009B introduced real, valuable deterministic checks (binding
Requirement coverage, Constraint compliance, materializability) but wired
them into a single function that ALSO picked a "winner" among every
technically admissible candidate -- preferring mutation-free candidates and
breaking remaining ties with a structural hash -- and only fell back to the
Chairman's own recommendation when it happened to already be the computed
winner. That silently overrode an admissible Chairman recommendation
whenever a different admissible candidate looked more efficient by the
resolver's own criteria, which contradicts the documented governance: ADC
may reject an INADMISSIBLE candidate, but it must never choose WHICH
admissible candidate the Chairman or the human is allowed to prefer.

CLAUDE-PRE-E2E-009C separates the two responsibilities this module now
provides:

  1. Validation (this module keeps 009B's real checks, unchanged in
     substance): validate_candidates() classifies every CouncilVariant the
     Council actually proposed as admissible or inadmissible, with reasons.
     This is the ONLY thing the deterministic layer decides on its own.

  2. Selection (corrected in 009C): select_engineering_variant() honors
     whichever admissible candidate the Chairman recommended, or -- when
     given -- an explicit human override, rather than computing its own
     "preferred" candidate among several admissible ones. It never silently
     substitutes a different candidate for an inadmissible recommendation;
     it raises ChairmanRecommendationInadmissibleError instead, exposing the
     remaining admissible alternatives so a new recommendation or an
     explicit human selection can be obtained.

Producer -> Artifact -> Consumer:
Producer: EngineeringCouncil's Chairman synthesis (a real LLM call)
produces a CouncilResult with candidate CouncilVariants and a
`recommendation` id -- legitimately non-deterministic prose/candidate
generation, never made byte-deterministic here.
Artifact: EngineeringDecision, deterministically derived from CouncilResult
plus the already-computed PreflightResult/platform, but ONLY once a
specific admissible candidate has actually been selected (by the Chairman's
recommendation, or by an explicit human override) -- never invented by this
module on its own when more than one candidate is admissible.
Consumer: ToolchainMaterializer.materialize() (S3) calls
select_engineering_variant() and builds the SetupPlan from
decision.variant; it does not duplicate any admissibility logic itself.

EngineeringSolutionClass (app.engineering_solution_class) remains useful
here purely as classification/comparison evidence attached to each
CandidateValidation -- it is never used to force one admissible
architecture over another.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.council_models import CouncilResult, CouncilVariant, ToolchainItem, VerificationCoverage
from app.engineering_solution_class import (
    EngineeringSolutionClass,
    classify_engineering_solution,
)
from app.python_distribution import (
    distribution_names_match,
    environment_target_matches,
    is_valid_distribution_identifier,
    parse_pip_show_requirement,
    resolve_environment_python_target,
)
from app.requirement_model import PreflightResult, RequirementType, SetupStep


def _safe_candidate_label(variant: CouncilVariant) -> str:
    """A short, safe identifier for one candidate in diagnostic evidence:
    id plus a truncated name. CouncilVariant.name is short Chairman/agent
    prose (a label, not a paragraph), but is still defensively capped --
    never the unbounded description/advantages/disadvantages/risks
    fields, which are excluded entirely (CLAUDE-E2E-NIO-010A, Part 7: no
    giant prompt dumps)."""
    name = (variant.name or "")[:60]
    return f"{variant.id}({name})" if name else variant.id


def _format_candidate_evidence(validations: tuple["CandidateValidation", ...]) -> str:
    """Renders the per-candidate admissibility evidence this task requires
    (CLAUDE-E2E-NIO-010A, Part 7) as one safe, compact, deterministic
    string: candidate id/name, its EngineeringSolutionClass environment
    model, admissible=True/False, and -- only when inadmissible -- the
    concise structural reasons (which already embed the relevant
    Requirement/Constraint identities, e.g. "missing binding requirement
    coverage: ['req-platformio']"). Contains only our own short,
    deterministic reason strings and structural fields -- never LLM prose
    (description/advantages/disadvantages/risks), never Chain-of-Thought,
    never secrets/credentials/executable commands. Reused both by
    exception messages (visible directly in a traceback, no extra
    trace-reading step needed) and by diagnostic trace detail summaries."""
    parts = []
    for validation in validations:
        label = _safe_candidate_label(validation.variant)
        env = validation.solution_class.environment_model
        if validation.admissible:
            parts.append(f"{label}[env={env}]: admissible")
        else:
            parts.append(f"{label}[env={env}]: inadmissible ({'; '.join(validation.reasons)})")
    return " | ".join(parts) if parts else "no candidates were proposed"


class NoEligibleEngineeringCandidateError(Exception):
    """Raised when NOT A SINGLE proposed CouncilVariant is technically
    admissible (binding Requirement coverage + Constraint compliance +
    materializability). This is a genuine dead end -- there is no
    admissible candidate for the Chairman or a human to choose from at
    all -- never silently resolved by letting an inadmissible candidate
    become binding merely because S3 would later demote its unsupported
    steps to manual_review.

    Carries `validations` (CLAUDE-E2E-NIO-010A, Part 7): the full
    per-candidate CandidateValidation set, so the actual rejection reason
    for EVERY proposed candidate is visible directly in the exception --
    both programmatically (`.validations`) and in the message itself,
    rather than only the previous generic sentence that gave no way to
    mechanically determine why zero candidates were admissible."""

    def __init__(self, message: str, *, validations: tuple["CandidateValidation", ...] = ()):
        if validations:
            message = f"{message} Per-candidate evidence: {_format_candidate_evidence(validations)}"
        super().__init__(message)
        self.validations = validations


class ChairmanRecommendationInadmissibleError(Exception):
    """Raised when the recommendation actually offered for selection (the
    Chairman's own recommendation, or an explicit human override) refers to
    a CouncilVariant that IS among the Council's proposed candidates but
    fails technical validation. ADC must not execute it and must not
    silently substitute a different candidate while still presenting the
    result as if it were that recommendation -- the caller is expected to
    obtain a new Chairman recommendation or an explicit human selection
    from `admissible`."""

    def __init__(
        self, message: str, *, recommendation_id: str,
        admissible: tuple[CouncilVariant, ...],
        rejected: tuple["CandidateValidation", ...],
    ):
        if rejected:
            message = (
                f"{message} Per-candidate evidence: "
                f"{_format_candidate_evidence(rejected)}"
            )
        super().__init__(message)
        self.recommendation_id = recommendation_id
        self.admissible = admissible
        self.rejected = rejected


class EngineeringVariantNotFoundError(Exception):
    """Raised when a selection (Chairman recommendation or human override)
    names a variant id that the Council never actually proposed -- distinct
    from ChairmanRecommendationInadmissibleError, which is for a candidate
    that WAS proposed but fails validation."""


class EngineeringSelectionRequiredError(Exception):
    """Raised when more than one CouncilVariant is admissible and neither a
    Chairman recommendation nor an explicit human selection was given.
    Multiple admissible Engineering solutions may legitimately coexist
    (Host, venv, Docker, VM, ...); the deterministic layer must not pick
    one on its own in that situation -- an explicit recommendation or human
    selection is required."""


@dataclass(frozen=True)
class EngineeringReworkRequest:
    """S2.3 -> S2.2 rework boundary artifact (CLAUDE-ARCH-S2-012A, Part 8).
    The formal, technology-neutral evidence S2.3 hands back to S2.2 when a
    Chairman-synthesized candidate is structurally repairable: S2.2 uses
    this to build its bounded, targeted repair prompt (unchanged 011A
    strategy -- at most one repair, never a full Council rerun); S2.3
    itself never repairs, merges, or substitutes a candidate.

    Contains only our own short, deterministic, already-safe fields --
    never Chain-of-Thought, raw private prompts, secrets, API keys,
    credentials, or unrestricted LLM prose (CLAUDE-E2E-NIO-011A, Part 3
    diagnostic-safety precedent, reused here).

    `identity_conflict`/`identity_conflict_detail` and
    `install_method_conflict`/`install_method_conflict_detail`
    (CLAUDE-ADC-S23-INSTALL-METHOD-PRODUCER-REPAIR-FIX-001): a strict
    refinement of `materializability_conflict` (kept unchanged, still set
    whenever EITHER category applies, for full backward compatibility)
    that splits its detail by CandidateValidation.unmaterializable_items'
    already-computed rejection_category, so app.engineering_council's
    repair-prompt builder can tell an "identity_missing_or_invalid" defect
    (technical_identity/name is not a usable distribution identifier)
    apart from an "install_method_incompatible" one (identity resolved,
    but install_method does not match the controlled executor's
    compatibility contract) and target its one bounded repair hint at the
    actual field at fault -- never both, when only one is actually wrong.
    These two categories are mutually exclusive PER ITEM (see
    _binding_item_rejection_category()), but a variant with several
    offending items could in principle carry both; each set is therefore
    independent, not either/or, at the EngineeringReworkRequest level."""

    rejected_candidate_id: str
    reason_codes: tuple[str, ...]
    missing_requirement_ids: tuple[str, ...] = ()
    platform_conflict: str | None = None
    materializability_conflict: bool = False
    materializability_conflict_detail: tuple[str, ...] = ()
    identity_conflict: bool = False
    identity_conflict_detail: tuple[str, ...] = ()
    install_method_conflict: bool = False
    install_method_conflict_detail: tuple[str, ...] = ()
    verification_feasibility_conflict: bool = False
    verification_feasibility_gap_ids: tuple[str, ...] = ()
    verification_feasibility_conflict_detail: tuple[str, ...] = ()
    repair_attempt: int = 1

    @classmethod
    def from_validation(
        cls, validation: "CandidateValidation", *, platform: str | None = None,
        repair_attempt: int = 1,
    ) -> "EngineeringReworkRequest":
        """Builds the rework artifact directly from an S2.3
        CandidateValidation -- never re-derives or guesses evidence that
        validate_variants() already computed.

        CLAUDE-ADC-ZIELBILD-DIFF-FIX-001 (D1): every field below is read
        directly from validate_variants()'s own already-computed
        structured CandidateValidation fields -- never by re-parsing or
        re-classifying `reasons`' own human-readable presentation text
        (which remains presentation/diagnostic-only). This includes
        `materializability_conflict`/`materializability_conflict_detail`,
        which previously re-derived their content with a regex over
        `reasons` (CLAUDE-ARCH-S2-012D); they now reuse the exact same
        `unmaterializable_items` structured evidence
        `identity_conflict_detail`/`install_method_conflict_detail`
        already relied on (CLAUDE-ADC-S23-INSTALL-METHOD-PRODUCER-
        REPAIR-FIX-001), since every unmaterializable item is, by
        construction, either an identity or an install-method defect."""
        identity_detail = tuple(
            f"{req_id} (item name={name!r})"
            for req_id, name, category in validation.unmaterializable_items
            if category == "identity_missing_or_invalid"
        )
        install_method_detail = tuple(
            f"{req_id} (item name={name!r})"
            for req_id, name, category in validation.unmaterializable_items
            if category == "install_method_incompatible"
        )
        materializability_detail = tuple(
            f"{req_id} (item name={name!r})"
            for req_id, name, _category in validation.unmaterializable_items
        )
        return cls(
            rejected_candidate_id=validation.variant.id,
            # D1: the exact set of simultaneously-applicable structured
            # failure categories -- never collapsed to the single,
            # first-match category categorize_admissibility_reasons()
            # itself still returns for its own, separate Diagnostic
            # Trace fault-localization contract (unchanged).
            reason_codes=_admissibility_reason_categories(validation),
            missing_requirement_ids=validation.missing_binding_requirement_ids,
            platform_conflict=platform if validation.platform_conflict else None,
            materializability_conflict=bool(validation.unmaterializable_items),
            materializability_conflict_detail=materializability_detail,
            identity_conflict=bool(identity_detail),
            identity_conflict_detail=identity_detail,
            install_method_conflict=bool(install_method_detail),
            install_method_conflict_detail=install_method_detail,
            verification_feasibility_conflict=bool(validation.verification_feasibility_gap_ids),
            verification_feasibility_gap_ids=validation.verification_feasibility_gap_ids,
            verification_feasibility_conflict_detail=validation.verification_feasibility_gap_diagnostics,
            repair_attempt=repair_attempt,
        )


@dataclass(frozen=True)
class CandidateValidation:
    """The deterministic technical-admissibility verdict for exactly one
    CouncilVariant the Council actually proposed, plus its technology-
    neutral EngineeringSolutionClass (kept purely as classification/
    comparison evidence -- see module docstring). `reasons` is non-empty
    only when `admissible` is False.

    `unmaterializable_items` (CLAUDE-ADC-S23-INSTALL-METHOD-PRODUCER-
    REPAIR-FIX-001): the exact (requirement_ref, item.name,
    rejection_category) triples _unmaterializable_binding_requirements()
    computed for this variant -- purely additive structured evidence
    alongside `reasons` (never a substitute for it, never altering
    `reasons`' own text/failure_summary behavior). Empty whenever the
    variant has no materializability defect. Lets EngineeringReworkRequest
    .from_validation() distinguish "identity_missing_or_invalid" from
    "install_method_incompatible" without re-deriving or duplicating the
    classification, and without parsing it back out of human-readable
    reason text."""

    variant: CouncilVariant
    solution_class: EngineeringSolutionClass
    admissible: bool
    reasons: tuple[str, ...] = ()
    unmaterializable_items: tuple[tuple[str, str, str | None], ...] = ()
    # CLAUDE-ADC-ZIELBILD-DIFF-FIX-001 (D1): the same per-category
    # verdicts validate_variants() already computed to build `reasons`'
    # own human-readable text, kept here too as their own structured,
    # machine-consumable fields -- never re-derived later by parsing
    # `reasons` (presentation/diagnostic text only). See
    # EngineeringReworkRequest.from_validation(), the S2.3 -> S2.2
    # rework boundary this exists for.
    duplicate_variant_identity: bool = False
    missing_binding_requirement_ids: tuple[str, ...] = ()
    platform_conflict: bool = False
    verification_feasibility_gap_ids: tuple[str, ...] = ()
    verification_feasibility_gap_diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class EngineeringDecision:
    """The Engineering solution actually handed to S3: exactly one
    admissible CouncilVariant that was actively selected -- by the
    Chairman's recommendation, by an explicit human override, or because it
    was the sole admissible candidate -- never a candidate the deterministic
    layer preferred on its own among several admissible ones."""

    variant: CouncilVariant
    solution_class: EngineeringSolutionClass
    selection_authority: str  # "chairman" | "human" | "sole_admissible"


@dataclass(frozen=True)
class EngineeringVariantSelection:
    """The smallest technology-neutral contract representing a Council
    variant decision for human/UI consumption (CLAUDE-PRE-E2E-009C, Part 5):
    the full Council result, the Chairman's own recommendation id, every
    candidate's validation (admissible or rejected-with-reasons), which
    variant id is currently selected (if any), and the authority behind
    that selection. Building this never raises -- unlike
    select_engineering_variant(), it is meant to be presented to a human
    even when nothing could yet be automatically selected."""

    council_result: CouncilResult
    chairman_recommendation: str | None
    validations: tuple[CandidateValidation, ...]
    selected_variant_id: str | None
    selection_authority: str  # "chairman" | "human" | "sole_admissible" | "none"
    # CLAUDE-ADC-ZIELBILD-DIFF-FIX-001 (D2): set only when
    # selection_authority == "none", to a bounded, machine-readable
    # status distinguishing WHY selection is unresolved -- never a raw
    # exception string. One of "no_eligible_candidate",
    # "recommendation_inadmissible", "selection_required",
    # "selected_variant_not_found". None whenever selection resolved.
    unresolved_reason: str | None = None

    @property
    def admissible_variants(self) -> tuple[CouncilVariant, ...]:
        return tuple(v.variant for v in self.validations if v.admissible)

    @property
    def rejected_variants(self) -> tuple[CandidateValidation, ...]:
        return tuple(v for v in self.validations if not v.admissible)


def _binding_requirement_ids(preflight: PreflightResult | None) -> frozenset[str]:
    """The exact, already-structured set of requirement ids that are
    (a) required, (b) still missing/unsatisfied, and (c) blocking for
    the current operation -- i.e. genuinely binding on validation, as
    opposed to a required-but-forward-looking or already-satisfied
    requirement. Reuses RequirementPreflight's own already-computed
    missing_requirements/activations -- never re-derived or guessed here."""
    if preflight is None:
        return frozenset()
    blocking_ids = {
        activation.requirement_id
        for activation in preflight.activations
        if activation.blocks_current_operation
    }
    return frozenset(
        requirement.id
        for requirement in preflight.missing_requirements
        if requirement.required and requirement.id in blocking_ids
    )


def _covers_binding_requirements(variant: CouncilVariant, binding_ids: frozenset[str]) -> bool:
    covered = {item.requirement_ref for item in variant.toolchain}
    return binding_ids <= covered


def _environment_scoped_binding_requirement_ids(
    preflight: PreflightResult | None,
    variant: CouncilVariant,
    project_root: str | None,
) -> frozenset[str]:
    """CLAUDE-ADC-ZIELBILD-DIFF-FIX-001 (A5): a required, blocking
    PYTHON_PACKAGE requirement Preflight already found satisfied is
    binding candidate coverage too -- UNLESS that satisfaction evidence
    was proven for the SAME concrete Python target this variant's own
    `environment` would actually use (the same `environment_target_
    matches()` authority ToolchainMaterializer.materialize_decision()
    itself relies on for FIX-004, never a second, competing rule).
    RequirementPreflight always stamps a single, pre-candidate,
    host-style target; a "venv" candidate targets an entirely different
    interpreter, so host-side satisfaction proves nothing about it -- the
    requirement must still be covered by the candidate's own toolchain
    in that case, or it is rejected as an omission instead of silently
    disappearing because it happened to be "not missing" for a different
    target.

    Gated exactly like materialize_decision() itself: without a real
    project_root, a "host" candidate cannot be bound to a specific
    target here either and keeps trusting Preflight's satisfaction
    unchanged -- this only ever narrows the "host, no project_root"
    case's existing behavior for "venv" candidates, never for "host"."""
    if preflight is None or project_root is None and variant.environment != "venv":
        return frozenset()
    already_installed = getattr(preflight, "already_installed", ()) or ()
    if not already_installed:
        return frozenset()
    blocking_ids = {
        activation.requirement_id
        for activation in preflight.activations
        if activation.blocks_current_operation
    }
    result_by_id = {result.requirement_id: result for result in preflight.results}
    binding: set[str] = set()
    for requirement in already_installed:
        if (
            requirement.type != RequirementType.PYTHON_PACKAGE
            or not requirement.required
            or requirement.id not in blocking_ids
        ):
            continue
        preflight_result = result_by_id.get(requirement.id)
        evidence_target = preflight_result.target_executable if preflight_result else None
        if environment_target_matches(variant.environment, evidence_target, project_root):
            continue
        binding.add(requirement.id)
    return frozenset(binding)


def _requirement_by_id(preflight: PreflightResult | None, requirement_id: str):
    """The SAME, already-computed S1 Requirement object Preflight already
    holds for this id -- reused, never re-derived or guessed. Searches
    both `missing_requirements` (the common case: a binding requirement
    is by definition still missing) and `already_installed` (a binding
    requirement can also be one Preflight found already satisfied but
    still required to be represented in this operation).

    CLAUDE-ADC-S23-STRICT-IDENTITY-ENVIRONMENT-BINDING-FIX-004: fails
    closed on ambiguity, the smallest central rule for every caller of
    this function -- zero matching requirements is unresolved (unchanged:
    returns None), exactly one is usable (returns it, unchanged), and
    MORE than one sharing the same id (whether both live in the same
    collection or split across `missing_requirements`/
    `already_installed`) is treated as unresolved too, never silently
    resolved to whichever one happens to appear first (or last). A
    duplicated id makes "which Requirement is this?" genuinely
    ambiguous -- for a trust decision (e.g. binding a pip_show
    verification claim to a specific S1-authored `verification_method`),
    an ambiguous answer must never be treated as a definite one."""
    if preflight is None:
        return None
    candidates = [
        requirement
        for requirement in (
            tuple(preflight.missing_requirements)
            + tuple(getattr(preflight, "already_installed", ()) or ())
        )
        if requirement.id == requirement_id
    ]
    if len(candidates) != 1:
        return None
    return candidates[0]


def _toolchain_item_identity(item: ToolchainItem) -> str:
    return (item.technical_identity or item.name or "").strip()


def _toolchain_item_matches_requirement_semantics(
    item: ToolchainItem, requirement,
) -> bool:
    """Check type, explicit package identity and declared exact version.

    Python identity uses only structured technical_identity on both sides,
    with central PEP 503 equality. Unknown Requirement identity fails closed.
    Missing item identity retains the existing materializer-owned diagnostic.
    Other ecosystems retain their existing exact display/technical comparison.
    """
    if item.type != requirement.type:
        return False
    if requirement.type == RequirementType.PYTHON_PACKAGE:
        requirement_identity = requirement.technical_identity
        if not is_valid_distribution_identifier(requirement_identity):
            return False
        if not item.technical_identity:
            return True
        if not is_valid_distribution_identifier(item.technical_identity):
            return False
        if not distribution_names_match(item.technical_identity, requirement_identity):
            return False
    else:
        requirement_identity = (requirement.name or "").strip()
        if not requirement_identity:
            return False
        item_identity = _toolchain_item_identity(item)
        if not item_identity or item_identity.lower() != requirement_identity.lower():
            return False
    if (
        requirement.required_version
        and item.version
        and item.version.strip() != requirement.required_version.strip()
    ):
        return False
    return True


def _semantically_unsatisfied_binding_requirements(
    variant: CouncilVariant, binding_ids: frozenset[str], preflight: PreflightResult | None,
) -> tuple[str, ...]:
    """CLAUDE-ARCH-S2-014C (F4): the exact, sorted binding requirement
    ids that are NOT satisfied -- either because no toolchain item
    references them at all (the pre-existing _covers_binding_
    requirements() check, preserved unchanged as the "missing entirely"
    case), or because the referencing item(s) fail semantic compatibility
    with the Requirement's own structured fields (see
    _toolchain_item_matches_requirement_semantics()). One correctly
    satisfied requirement never hides another that is missing or
    semantically wrong -- every binding id is checked independently and
    ALL failures are returned, not just the first.

    When no structured Requirement object can be resolved for an id at
    all (preflight is None, or the id is genuinely unknown to it), this
    function cannot mechanically prove OR disprove semantic
    compatibility -- ref-membership (already covered by
    _covers_binding_requirements()) remains the only evidence available,
    exactly as it always has been; this is a TARGET AMBIGUITY for THAT
    id's version/identity dimensions specifically, not a silent pass."""
    unsatisfied: list[str] = []
    for requirement_id in binding_ids:
        items = tuple(
            item for item in variant.toolchain if item.requirement_ref == requirement_id
        )
        if not items:
            unsatisfied.append(requirement_id)
            continue
        requirement = _requirement_by_id(preflight, requirement_id)
        if requirement is None:
            continue
        if not any(
            _toolchain_item_matches_requirement_semantics(item, requirement)
            for item in items
        ):
            unsatisfied.append(requirement_id)
    return tuple(sorted(unsatisfied))


def _violates_platform_constraint(variant: CouncilVariant, platform: str | None) -> bool:
    """A structural, technology-neutral Constraint check: a toolchain
    item whose own environment_constraint disagrees with the input's
    platform can never be legitimately proposed for this project,
    regardless of what the Chairman's prose claims."""
    if not platform:
        return False
    return any(
        item.environment_constraint and item.environment_constraint != platform
        for item in variant.toolchain
    )


def _binding_item_rejection_category(item: ToolchainItem, step: SetupStep) -> str | None:
    """CLAUDE-ADC-S23-INSTALL-METHOD-PRODUCER-REPAIR-FIX-001: the exact,
    single classification of WHY a controlled binding item failed to
    reach action="install" -- "identity_missing_or_invalid" (neither
    technical_identity nor the display name is a policy-valid
    distribution identifier -- classify_item() never even reaches the
    install_method check in this case) vs. "install_method_incompatible"
    (identity resolved, but install_method does not match the controlled
    executor's own compatibility contract for it). These are mutually
    exclusive by construction in ToolchainMaterializer._materialize_item()'s
    own control flow. Returns None when the item already reached
    action="install" (nothing to classify).

    This is the ONE place this distinction is computed -- shared by
    _unmaterializable_binding_requirements() (S2.3 admissibility / the
    Chairman rework loop) and binding_materializer_diagnostics() (S2.3
    observability/tracing), so a rework hint and a trace diagnostic can
    never independently disagree about why the same item was rejected."""
    if step.action == "install":
        return None
    is_python_package = item.type == RequirementType.PYTHON_PACKAGE
    identity_resolved = bool(step.package)
    if is_python_package and not identity_resolved:
        return "identity_missing_or_invalid"
    if identity_resolved:
        return "install_method_incompatible"
    return None


def _unmaterializable_binding_requirements(
    variant: CouncilVariant, binding_ids: frozenset[str],
) -> tuple[tuple[str, str, str | None], ...]:
    """CLAUDE-ARCH-S2-012D: the exact (requirement_ref, item.name,
    rejection_category) triples for every binding toolchain item whose
    effect IS a currently controlled one (so it SHOULD be automatable)
    but whose concrete representation still fails to materialize as
    "install" -- e.g. a python_package item whose display `name`
    ("ESPHome CLI") is not itself a valid distribution identifier and
    whose `technical_identity` was left unset, exactly the
    Real-System-E2E #8 shape. A requirement type with no controlled
    executor at all (SDK, EXECUTABLE, TOOLCHAIN, FLASHER, SYSTEM_PACKAGE,
    ...) is SUPPOSED to become manual_review; that is never included
    here. Reuses ToolchainMaterializer's own, unduplicated classification
    logic (classify_item()) and app.execution's own controlled-effect
    registry -- never a second, heuristic notion of "controlled" defined
    here. Returning the exact offending (id, name) pairs -- not just a
    boolean -- is what lets the bounded S2.2 repair prompt name the
    precise defect instead of a bare "materializability_conflict=True"
    flag (CLAUDE-ARCH-S2-012D root cause: insufficient diagnostic
    information prevented the Chairman's one allowed repair attempt from
    correcting the exact field at fault).

    CLAUDE-ADC-S23-INSTALL-METHOD-PRODUCER-REPAIR-FIX-001: each offender
    triple's third element is now the item's rejection_category (see
    _binding_item_rejection_category(), reused unduplicated from
    binding_materializer_diagnostics()) so a caller can further
    distinguish an identity defect from an install_method defect --
    purely additive: every existing caller that only reads the first two
    elements (requirement_ref, name) is unaffected."""
    from app.execution import is_controlled_setup_effect
    from app.requirement_model import classify_setup_effect
    from app.toolchain_materializer import ToolchainMaterializer

    materializer = ToolchainMaterializer()
    offenders: list[tuple[str, str, str | None]] = []
    for item in variant.toolchain:
        if item.requirement_ref not in binding_ids:
            continue
        effect = classify_setup_effect(item.type, item.name, item.install_method)
        if not is_controlled_setup_effect(effect):
            continue
        step = materializer.classify_item(item)
        if step.action != "install":
            offenders.append((
                item.requirement_ref, item.name,
                _binding_item_rejection_category(item, step),
            ))
    return tuple(offenders)


def _classify_install_method_for_diagnostics(
    setup_effect: str | None, install_method: str | None, package: str | None,
) -> str:
    """CLAUDE-ADC-S23-MATERIALIZER-DIAGNOSTICS-001: a bounded, closed set of
    structural labels describing the SHAPE of install_method against the
    exact same recognized-shape contract
    is_install_method_compatible_with_controlled_executor() itself enforces
    -- never the install_method text itself, and never a second,
    independent compatibility decision (this never overrides or duplicates
    that function's own True/False verdict; it only names WHICH shape, if
    any, install_method already matches, for diagnosability). Only the
    python_package_install effect currently has a registered install-method
    shape contract (app.execution.CONTROLLED_SETUP_EFFECTS); any other
    controlled effect added later without also registering one here
    correctly reports "no_validator_registered", never a guessed shape.

    CLAUDE-ADC-S23-MATERIALIZER-DIAGNOSTICS-FIX-001/002 (CDX-ADC-S23-
    MATERIALIZER-DIAGNOSTICS-REVIEW-001/CDX-ADC-S23-MATERIALIZER-
    DIAGNOSTICS-FIX-REVIEW-001): total/safe for a non-string install_method
    (e.g. bytes, or an arbitrary object whose own __bool__ raises) that
    reached this diagnostic boundary -- never inspects or persists that
    value's content, and never lets the string-only regex matching below
    (which would otherwise raise TypeError on a bytes-like object, the
    original defect this guards against) see it. `None` is identified by
    identity (`is None`), never by truthiness -- so a non-string value is
    rejected BEFORE `bool()`, `in`, or any regex/content inspection ever
    runs on it (FIX-001's own `if not install_method:` first still called
    `bool(install_method)` on every non-string value too, which would
    itself raise for a value whose `__bool__` is broken; FIX-002 corrects
    this ordering). Reported as its own bounded "non_string_type" label,
    distinct from every string-shape label below, so this observational
    function is provably total for any Python value and can never replace
    or mask the real, already-correct S2.3/materializer outcome (which
    itself never reaches install_method-shape logic at all for a binding
    item whose identity resolution already failed -- see
    is_install_method_compatible_with_controlled_executor()'s own
    `controlled and package` guard in _materialize_item())."""
    from app.requirement_model import SetupEffect

    if install_method is None:
        return "empty_or_none"
    if not isinstance(install_method, str):
        return "non_string_type"
    if not install_method:
        return "empty_or_none"
    if setup_effect != SetupEffect.PYTHON_PACKAGE_INSTALL:
        return "no_validator_registered"
    from app.python_package_executor import (
        INSTALL_METHOD_COMMAND_PATTERNS,
        SUPPORTED_INSTALL_METHOD_MARKERS,
    )

    if install_method in SUPPORTED_INSTALL_METHOD_MARKERS:
        return "bareword_marker"
    for pattern in INSTALL_METHOD_COMMAND_PATTERNS:
        match = pattern.fullmatch(install_method)
        if match is not None:
            if package and distribution_names_match(match.group(1), package):
                return "recognized_command_pattern_package_match"
            return "recognized_command_pattern_package_mismatch"
    return "unrecognized_shape"


def binding_materializer_diagnostics(
    variant: CouncilVariant, preflight: PreflightResult | None,
) -> tuple[dict, ...]:
    """CLAUDE-ADC-S23-MATERIALIZER-DIAGNOSTICS-001: the smallest central
    diagnostic instrumentation needed to mechanically distinguish, for each
    binding toolchain item of this FINAL candidate variant, exactly why
    ToolchainMaterializer's classify_item() did or did not resolve it to a
    genuinely automatable "install" SetupStep -- proven ambiguous from live
    evidence alone (CLAUDE-ADC-S23-MATERIALIZER-ROOTCAUSE-001) because
    neither the persisted council_output/interface_data projections nor the
    truncated raw effective_prompt text reliably carry technical_identity
    for the FINAL (post-Chairman-merge) item.

    Purely observational and side-effect-free: computed independently of,
    and never consulted by, validate_variants()/_unmaterializable_binding_
    requirements() -- this function changes no admissibility or
    materialization decision. It reuses ONLY the exact same already-public
    functions _materialize_item() itself uses (classify_setup_effect,
    is_controlled_setup_effect, is_valid_distribution_identifier,
    is_install_method_compatible_with_controlled_executor,
    ToolchainMaterializer.classify_item()) so it can never disagree with,
    weaken, or duplicate the real materializer decision.

    Distinguishes the two disjoint ways a controlled binding item can still
    fail to reach action="install": identity_missing_or_invalid (neither
    technical_identity nor the display name is a policy-valid distribution
    identifier -- classify_item() never even reaches the install_method
    check in this case) vs. install_method_incompatible (identity resolved,
    but install_method does not match the controlled executor's own
    compatibility contract for it). These are mutually exclusive by
    construction in _materialize_item()'s own control flow, never guessed
    at or inferred here.

    Never returns a raw, possibly-invalid identifier or install_method
    string: only bounded booleans, Python type names, and a fixed
    classification label; the resolved identifier is included (as
    "safe_identifier") ONLY when it is already policy-valid -- exactly the
    value ToolchainMaterializer itself would use as SetupStep.package."""
    from app.execution import (
        is_controlled_setup_effect,
        is_install_method_compatible_with_controlled_executor,
    )
    from app.python_distribution import is_valid_distribution_identifier
    from app.requirement_model import classify_setup_effect
    from app.toolchain_materializer import ToolchainMaterializer

    binding_ids = _binding_requirement_ids(preflight)
    materializer = ToolchainMaterializer()
    diagnostics: list[dict] = []
    for item in variant.toolchain:
        if item.requirement_ref not in binding_ids:
            continue
        effect = classify_setup_effect(item.type, item.name, item.install_method)
        if not is_controlled_setup_effect(effect):
            continue

        is_python_package = item.type == RequirementType.PYTHON_PACKAGE
        technical_identity_valid = (
            is_valid_distribution_identifier(item.technical_identity) if is_python_package else None
        )
        name_valid = (
            is_valid_distribution_identifier(item.name) if is_python_package else None
        )

        step = materializer.classify_item(item)
        identity_resolved = bool(step.package)
        install_method_compatible = (
            is_install_method_compatible_with_controlled_executor(
                effect, item.install_method, step.package,
            ) if identity_resolved else None
        )

        # CLAUDE-ADC-S23-INSTALL-METHOD-PRODUCER-REPAIR-FIX-001: reuses
        # the exact same classifier _unmaterializable_binding_
        # requirements() now also uses, so this trace diagnostic and the
        # Chairman rework loop can never independently disagree about
        # why the same item was rejected.
        rejection_category = _binding_item_rejection_category(item, step)

        diagnostics.append({
            "variant_id": variant.id,
            "requirement_ref": item.requirement_ref,
            "type": item.type,
            "name": item.name,
            "technical_identity_present": bool(item.technical_identity),
            "technical_identity_python_type": type(item.technical_identity).__name__,
            "technical_identity_check_applicable": is_python_package,
            "technical_identity_valid": technical_identity_valid,
            "name_valid_as_identifier": name_valid,
            "safe_identifier": step.package if identity_resolved else None,
            "install_method_python_type": type(item.install_method).__name__,
            "install_method_classification": _classify_install_method_for_diagnostics(
                effect, item.install_method, step.package if identity_resolved else None,
            ),
            "install_method_compatible": install_method_compatible,
            "materializer_action": step.action,
            "materializer_rejection_category": rejection_category,
        })
    return tuple(diagnostics)


def _is_materializable_for_binding_requirements(
    variant: CouncilVariant, binding_ids: frozenset[str],
) -> bool:
    """True when every toolchain item covering a binding requirement
    materializes into either a genuinely automatable ("install")
    SetupStep, OR a legitimately, explicitly-manual one -- a valid
    controlled OR explicitly-manual execution model. See
    _unmaterializable_binding_requirements() for the exact-evidence
    variant of this same check."""
    return not _unmaterializable_binding_requirements(variant, binding_ids)


def _binding_requirements_needing_verification(
    preflight: PreflightResult | None, binding_ids: frozenset[str],
) -> tuple[str, ...]:
    """S2.3, CLAUDE-ARCH-S2-012B (Gate E): the exact, already-structured
    subset of binding requirement ids whose OWN Requirement.
    verification_method is set -- i.e. the current, existing S1 contract
    (app.requirement_model.Requirement.verification_method, validated
    non-empty-when-present by RequirementValidator, already surfaced to
    the Chairman prompt) already says THIS requirement demands
    verification. Never invents a new Requirement-level contract; only
    reads the one that already exists."""
    if preflight is None:
        return ()
    return tuple(
        requirement.id
        for requirement in preflight.missing_requirements
        if requirement.id in binding_ids and requirement.verification_method
    )


_RECOGNIZED_VERIFICATION_KINDS = frozenset({
    "test_command", "build_command", "static_analysis",
    "probe", "smoke_test", "config_validation", "manual_review",
})

# Kinds with nothing installable to point evidence at (nothing to run
# through a package manager/executable) -- evidence for these may
# instead name one of the requirement ids the mechanism itself claims to
# cover, rather than a ToolchainItem identity.
_SELF_EVIDENCED_VERIFICATION_KINDS = frozenset({
    "manual_review", "probe", "config_validation",
})

# CLAUDE-ARCH-S2-014C (F2, case 4): the only ToolchainItem.state values
# the Chairman/Phase-1 prompt schema actually documents
# ("already_installed|needs_install|unavailable" -- app.council_prompts).
# A controllability check must be a POSITIVE allowlist, never merely
# "not unavailable" -- a malformed/unknown value (a typo, a hallucinated
# state, e.g. "garbage") must fail closed exactly like "unavailable"
# does, not silently pass through as if it were a recognized state.
_CONTROLLABLE_TOOLCHAIN_STATES = frozenset({"needs_install", "already_installed"})

_UNSAFE_MECHANISM_RE = re.compile(r"\s")


def _is_structured_verification_token(value: str | None) -> bool:
    """True when *value* is a single, structured token -- e.g. 'pytest',
    'npm_test', 'cargo_test', 'esphome_validate' -- never free prose like
    'run the test suite'. Deliberately technology-neutral: any concrete
    single-token technology identity qualifies, never a closed Python-
    only allowlist (CLAUDE-ARCH-S2-013E)."""
    return bool(value) and isinstance(value, str) and bool(value.strip()) and (
        _UNSAFE_MECHANISM_RE.search(value.strip()) is None
    )


def _resolve_toolchain_item_for_evidence(
    evidence: str, variant: CouncilVariant,
) -> ToolchainItem | None:
    """The SAME candidate-local ToolchainItem *evidence* names, matched
    by requirement_ref, name or technical_identity -- unchanged identity
    resolution from CLAUDE-ARCH-S2-013E, factored out so both grounding
    and compatibility can share it."""
    for item in variant.toolchain:
        if evidence in (item.requirement_ref, item.name, item.technical_identity):
            return item
    return None


def _verification_coverage_refs_are_valid(
    coverage: "VerificationCoverage", binding_ids: frozenset[str],
) -> bool:
    """CLAUDE-ARCH-S2-014C (F1): closes the phantom/foreign
    requirement_ref gap CDX-REVIEW-S2-014A reproduced. Every id in
    `coverage.requirement_refs` must resolve to a currently-binding
    requirement (`binding_ids` -- computed by S1/Preflight, never by the
    Council/Chairman) -- never a phantom string the SAME LLM call
    invented, never a foreign id copied from another candidate/context,
    never a non-binding/irrelevant id smuggled in alongside a real one.

    Applied BEFORE grounding/compatibility are even considered, and
    applied identically to every verification kind (test_command,
    build_command, static_analysis, smoke_test, probe, config_validation,
    manual_review) -- self-evidenced kinds (probe/config_validation/
    manual_review) are the ones CDX-REVIEW-S2-014A actually reproduced
    the defect on, precisely because their own grounding rule accepts
    `evidence in coverage.requirement_refs` as sufficient: that check is
    a TAUTOLOGY the LLM fully controls (evidence and requirement_refs are
    declared by the SAME call) and proves nothing about whether the
    referenced id is even real. Requiring every ref to independently
    belong to `binding_ids` closes that tautology for every kind, not
    only the self-evidenced ones.

    Fail-closed and all-or-nothing: an entry that mixes one real ref with
    one phantom ref is REJECTED IN FULL (never partially honored for the
    real ref) -- a coverage entry may not smuggle a phantom past S2.3 by
    riding alongside something legitimate."""
    if not coverage.requirement_refs:
        return False
    return all(ref in binding_ids for ref in coverage.requirement_refs)


def _verification_coverage_is_grounded(
    coverage: "VerificationCoverage", variant: CouncilVariant,
) -> bool:
    """CLAUDE-ARCH-S2-013E: a verification mechanism is only "available/
    applicable to this candidate" when its evidence names a concrete,
    already-structured identity that genuinely exists on the SAME
    candidate -- a ToolchainItem's requirement_ref, name or
    technical_identity. For kinds with nothing installable to point at
    (_SELF_EVIDENCED_VERIFICATION_KINDS), evidence may instead name one
    of the requirement ids the mechanism itself claims to cover. Never
    inferred from free-text phrasing -- an exact structured-identity
    match only.

    Retained unchanged as the structural-grounding predicate; kept
    separate from CLAUDE-ARCH-S2-013F's
    `_verification_coverage_is_compatible()` so 013E's own grounding
    contract stays independently testable and is not silently folded
    into the newer, stricter check."""
    evidence = (coverage.evidence or "").strip()
    if not evidence:
        return False
    if _resolve_toolchain_item_for_evidence(evidence, variant) is not None:
        return True
    if coverage.kind in _SELF_EVIDENCED_VERIFICATION_KINDS and evidence in coverage.requirement_refs:
        return True
    return False


# CLAUDE-ARCH-S2-014D: the project-root scope marker a trusted group
# carries when Project Intelligence detected its capability at the
# project's own root -- honestly project-wide by simple filesystem
# containment, never a default applied to area-local evidence on its
# behalf. Intentionally duplicated (never imported) from the Generalized
# Verification module's own identical constant: S2.3 must stay free of
# any dependency on S5 execution code (see tests/
# test_s2_subsubsystem_architecture.py's own source-inspection boundary
# test), exactly like this module's independent kind/mechanism vocabulary
# already is, by design, allowed to evolve separately from S5's.
_PROJECT_GLOBAL_SCOPE = "."

# CLAUDE-ADC-S23-VERIFICATION-EVIDENCE-ARCHITECTURE-FIX-002: the fixed,
# central, closed-set mechanism token for Python distribution
# package-presence verification (ADC's own controlled equivalent of
# `pip show <technical_identity>`). Intentionally duplicated (never
# imported) from the Generalized Verification module's own identical
# constant, for the exact same reason _PROJECT_GLOBAL_SCOPE above already
# is: S2.3 must stay free of any dependency on S5 execution code.
#
# CORRECTED ARCHITECTURE (independent review CDX-ADC-S23-VERIFICATION-
# EVIDENCE-ARCHITECTURE-REVIEW-001 rejected the prior one): coverage
# entries claiming this mechanism are NEVER corroborated through
# `trusted_groups` (the Project-Intelligence-derived
# TrustedVerificationGroup set used for pytest/esphome/cmake/...) at
# all -- see _python_package_verification_capability() below, which is
# the sole, item-scoped, pre-install CAPABILITY check this mechanism
# uses instead. The prior architecture treated Python distributions
# present in ADC's OWN CONTROLLER PROCESS's environment
# (importlib.metadata.distributions() read from the running ADC
# process, never the actual install/verification target) as
# PROJECT_GLOBAL_SCOPE trusted evidence; that conflated "importable by
# ADC itself" with "will be present in the target this candidate
# actually installs into", which are unrelated facts about unrelated
# Python environments. That evidence source has been removed entirely
# (see the Generalized Verification module's own history) rather than
# repaired, because no
# repair of a controller-environment-derived PROJECT_GLOBAL group could
# ever honestly prove anything about a DIFFERENT target
# executable/environment.
_PACKAGE_PRESENCE_MECHANISM = "pip_show"


def _scope_is_covered(group_scope: str, requirement_scope: str | None) -> bool:
    """CLAUDE-ARCH-S2-014D: True exactly when a trusted group detected at
    `group_scope` may corroborate a candidate's claim about
    `requirement_scope` (VerificationCoverage.area, candidate-declared and
    optional).

    Root-scoped evidence (`group_scope == _PROJECT_GLOBAL_SCOPE`) always
    covers -- the project root is, by filesystem containment, an ancestor
    of every area, so it is the one mechanically-derived "project-global"
    exception. Otherwise a candidate that never declared a scope at all
    can only ever be covered by that one honestly-global case (fail
    closed: no implicit project-wide fallback may legitimize evidence
    Project Intelligence actually found in one specific, unrelated area).
    A candidate that DID declare a scope is covered by an exact match, or
    by a trusted group whose own scope is a real path ANCESTOR of the
    declared scope (e.g. group_scope="backend" covers
    requirement_scope="backend/sub") -- never by mere string-prefix
    overlap (group_scope="backend" must never cover
    requirement_scope="backend-other"; the boundary is always a real path
    separator).

    Compares real `/`-separated path SEGMENTS, never raw string
    prefixes: a naive `requirement_scope.startswith(group_scope + "/")`
    would wrongly accept a path-traversal scope like
    "area-a/../area-b" as covered by "area-a" (it IS a literal string
    prefix match, even though it actually resolves to a completely
    different area) -- any segment that is empty, "." or ".." makes the
    declared scope mechanically unresolvable and therefore never
    covered, exactly like any other malformed self-declared value."""
    if group_scope == _PROJECT_GLOBAL_SCOPE:
        return True
    if requirement_scope is None:
        return False
    if requirement_scope == group_scope:
        return True
    requirement_parts = requirement_scope.split("/")
    scope_parts = group_scope.split("/")
    if any(part in ("", ".", "..") for part in requirement_parts):
        return False
    return (
        len(requirement_parts) > len(scope_parts)
        and requirement_parts[:len(scope_parts)] == scope_parts
    )


def _independently_corroborated(
    item_identity: str, mechanism: str, trusted_groups: tuple, requirement_scope: str | None = None,
) -> bool:
    """True exactly when Project Intelligence independently detected ONE
    real capability whose interchangeable identities cover BOTH the
    ToolchainItem's own identity and the claimed mechanism -- i.e. the
    candidate's own self-declaration (provides_verification) is
    corroborated by evidence the SAME Agent/Chairman call never
    produced. A candidate-local identity that merely happens to exist
    (013F's grounding) is not enough; neither is a mechanism token that
    merely looks structurally valid -- both must trace back to the SAME
    independently-detected capability.

    CLAUDE-ARCH-S2-014D additionally requires that SAME capability's own
    detected scope to cover `requirement_scope`
    (VerificationCoverage.area) -- closes the project-wide aggregation
    leak where capability genuinely detected in one area could
    corroborate an unrelated area's requirement (see
    `_scope_is_covered()`). Each `trusted_groups` entry is a
    TrustedVerificationGroup (duck-typed here, never imported by name --
    see the module-boundary note above): `.identities` (unchanged
    frozenset meaning) and `.scope` (its own ProjectArea.path).

    Identity matching is byte-exact membership for every mechanism this
    function is ever called for -- unchanged since before CLAUDE-ADC-S23-
    VERIFICATION-EVIDENCE-ARCHITECTURE-001. `_PACKAGE_PRESENCE_MECHANISM`
    ("pip_show") coverage NEVER reaches this function at all (see
    `_verification_coverage_is_compatible()`'s own dedicated branch and
    `_python_package_verification_capability()`, CLAUDE-ADC-S23-
    VERIFICATION-EVIDENCE-ARCHITECTURE-FIX-002) -- there is therefore no
    PEP 503 fuzzy-matching special case here, and no risk of a real
    distribution's name and the fixed mechanism token colliding inside
    the same unordered `.identities` set."""
    return any(
        _identity_corroborates(item_identity, mechanism, group.identities)
        and _scope_is_covered(group.scope, requirement_scope)
        for group in trusted_groups
    )


def _identity_corroborates(
    item_identity: str, mechanism: str, group_identities: frozenset[str],
) -> bool:
    """The one shared identity-membership rule both
    `_independently_corroborated()` (admissibility) and
    `_verification_coverage_incompatibility_reason()` (diagnostics) use,
    so they can never independently disagree about whether an identity
    is corroborated. Byte-exact membership only, for both the
    candidate's own identity and the claimed mechanism -- no fuzzy
    matching, no PEP 503 normalization (that only ever applies to
    Python-distribution PACKAGE IDENTITY, e.g. in
    `_toolchain_item_matches_requirement_semantics()` and
    `is_supported_python_package_install_method()`, never to a
    verification mechanism token, and never here: this function is never
    called for `_PACKAGE_PRESENCE_MECHANISM` coverage -- see
    `_verification_coverage_is_compatible()`)."""
    return item_identity in group_identities and mechanism in group_identities


# CLAUDE-ADC-S23-VERIFICATION-EVIDENCE-ARCHITECTURE-FIX-002: the exact,
# closed set of CouncilVariant.environment values ADC's real
# install/verification architecture (RequirementPreflight ->
# ToolchainMaterializer -> PythonPackageExecutor) can actually resolve a
# single real target Python executable for. "host" (the machine's own
# interpreter) and "venv" (an isolated project venv's interpreter) are,
# from the executor's own point of view, the IDENTICAL mechanism -- both
# are simply "a resolved python executable path" (see
# app.python_distribution.resolve_target_python_executable() and
# RequirementPreflight.check()'s target_executable parameter; neither
# function nor PythonPackageExecutor branches on the environment string
# at all). No controlled execution path anywhere in this codebase ever
# invokes a container runtime (docker/podman/...), so a candidate that
# merely LABELS its environment "container"/"docker"/anything else is
# never treated as though ADC could actually install into and verify
# inside one -- membership in this fixed set, never inference from the
# string's spelling or any other candidate-declared field.
_CONTROLLED_PYTHON_PACKAGE_ENVIRONMENTS = frozenset({"host", "venv"})


def _python_package_structural_capability(
    item: ToolchainItem, variant: CouncilVariant, project_root: str | None = None,
) -> "SetupStep | None":
    """The CLAUDE-ADC-S23-VERIFICATION-EVIDENCE-ARCHITECTURE-FIX-002
    capability chain (type/environment/effect/classify_item), factored
    out so both `_python_package_verification_capability()` and its
    diagnostic counterpart can tell "structurally not a controlled
    install at all" apart from "structurally fine, but the identity
    binding (FIX-003) itself is what failed" without duplicating this
    logic or letting the two checks silently drift apart. Returns the
    classified SetupStep (with a real `.package`) when every structural
    check passes, else None.

    CLAUDE-ADC-S23-STRICT-IDENTITY-ENVIRONMENT-BINDING-FIX-004 adds two
    independent, additive corrections on top of the unchanged FIX-002
    chain:

    1. Explicit technical_identity, never ToolchainMaterializer's own
       display-name fallback. ToolchainMaterializer.classify_item()
       legitimately falls back from an invalid/missing
       `technical_identity` to `item.name` for the unrelated,
       ALREADY-ACCEPTED question "can this item become a controlled
       INSTALL step at all" (CLAUDE-ARCH-S2-012D precedent, kept
       unchanged there -- see that method's own docstring). That
       fallback is not acceptable for the STRICTER question this
       function answers: "does ADC have a controlled, target-specific
       package-PRESENCE-VERIFICATION capability for this exact item".
       `item.technical_identity` must itself already be a valid,
       structured distribution identifier -- never `item.name`, never
       description/purpose/display text -- or this returns None before
       ToolchainMaterializer is even consulted, regardless of what a
       display-name fallback would otherwise have permitted.
    2. Real target-capability, not just structural shape.
       `variant.environment` alone ("venv" is a member of the fixed,
       closed set) previously proved nothing about whether a "venv"
       candidate has an actual, existing venv interpreter to install
       into/verify against -- a project with no `.venv` at all still
       structurally passed. `project_root` is threaded through to
       `resolve_environment_python_target()` -- the SAME central
       authority materialize_decision() itself uses, never a second,
       competing resolver -- and the result is forwarded into
       `ToolchainMaterializer.classify_item()`, so an unresolved target
       (e.g. `<project_root>/.venv/bin/python` does not exist, or
       `project_root` itself is unknown for a "venv" candidate) makes
       this candidate's capability false at S2.3 itself, exactly the
       same way materialize_decision() would later fail it closed to
       manual_review -- the S2.3 capability claim can therefore never be
       false relative to what materialization would actually do.
    """
    if item.type != RequirementType.PYTHON_PACKAGE:
        return None
    if variant.environment not in _CONTROLLED_PYTHON_PACKAGE_ENVIRONMENTS:
        return None
    if not is_valid_distribution_identifier(item.technical_identity):
        return None
    from app.execution import is_controlled_setup_effect
    from app.requirement_model import classify_setup_effect
    from app.toolchain_materializer import ToolchainMaterializer

    effect = classify_setup_effect(item.type, item.name, item.install_method)
    if not is_controlled_setup_effect(effect):
        return None
    environment_resolution = resolve_environment_python_target(
        variant.environment, project_root,
    )
    step = ToolchainMaterializer().classify_item(
        item, environment_resolution=environment_resolution,
    )
    if step.action != "install" or not step.package:
        return None
    if not distribution_names_match(step.package, item.technical_identity):
        # Defense-in-depth only: ToolchainMaterializer._materialize_item()
        # already prefers a valid technical_identity first, so this can
        # only differ if that producer-side rule itself ever changes --
        # never silently trust a different, materializer-chosen identity
        # for THIS explicit-identity-only capability boundary.
        return None
    return step


def _python_package_verification_capability(
    item: ToolchainItem, variant: CouncilVariant,
    preflight: PreflightResult | None = None,
    project_root: str | None = None,
) -> bool:
    """CLAUDE-ADC-S23-VERIFICATION-EVIDENCE-ARCHITECTURE-FIX-002: THE
    corrected S2.3 trust source for VerificationCoverage.mechanism ==
    `_PACKAGE_PRESENCE_MECHANISM` ("pip_show").

    PRE-INSTALL capability, never POST-INSTALL presence: this function
    never claims, checks, or requires that `item`'s package already
    exists anywhere -- not in ADC's own controller process, not on the
    host, not in any venv. It proves something narrower and sufficient
    for admissibility: that ADC's OWN controlled executor architecture
    -- never anything the candidate self-declares -- WILL perform a
    controlled, SAME-target post-install verification once this item is
    actually installed. Actual presence is proven later, after
    installation, by app.python_package_executor.PythonPackageExecutor
    (unchanged by this fix) -- see that module's `_run_verification()`.

    The capability chain, entirely mechanical and reusing existing,
    unduplicated rules (never a second, competing notion of
    "installable"/"controlled"):

      1. item.type must be PYTHON_PACKAGE -- this capability is
         Python-distribution-specific and says nothing about any other
         ecosystem.
      2. variant.environment must be one of the fixed, closed target
         classes ADC's real executor architecture actually resolves a
         real target executable for (`_CONTROLLED_PYTHON_PACKAGE_
         ENVIRONMENTS` above) -- never inferred from the string.
      3. The item's setup effect must be a currently controlled one
         (app.execution.is_controlled_setup_effect, unchanged).
      4. `ToolchainMaterializer.classify_item(item)` -- the SAME,
         unduplicated classification ToolchainMaterializer itself uses
         to decide whether this exact item becomes an automatable
         "install" SetupStep (CLAUDE-ARCH-S2-012D / CLAUDE-ADC-S23-
         INSTALL-METHOD-PRODUCER-REPAIR-FIX-001, unchanged: valid
         technical_identity, install_method compatible with the
         controlled executor) -- must resolve to action="install".

    When classify_item() resolves to "install", PythonPackageExecutor.
    execute() is the ADC-controlled component that will actually run: it
    resolves exactly ONE target Python executable
    (SetupStep.target_executable, stamped by RequirementPreflight onto
    this SAME requirement_ref and never re-resolved later) and uses that
    EXACT SAME executable for both the pip install AND the post-install
    distribution-metadata verification. That SAME-target binding is a
    static, already-existing property of PythonPackageExecutor's own
    code (see its `execute()`/`_run_verification()`), not a runtime fact
    this function re-derives, predicts, or needs external evidence for --
    establishing that classify_item() resolves to "install" is therefore
    sufficient to independently know SAME-target post-install
    verification WILL happen.

    A candidate's own `provides_verification=("pip_show",)` declaration
    is checked separately by this function's caller (unchanged 013G
    rule) and is NEVER, by itself, capability evidence here: a candidate
    that declares it but whose item fails any check above (an
    unrecognized/incompatible install_method, an invalid
    technical_identity, a non-Python-package type, or
    environment="container"/"docker" with no controlled container
    backend) remains inadmissible.

    CLAUDE-ADC-S23-VERIFICATION-IDENTITY-TARGET-BINDING-FIX-003 adds one
    more, independent binding requirement: capability alone (classify_
    item() resolving to "install") only proves ADC COULD perform a
    controlled, same-target install+verify for *this item's own*
    distribution -- it says nothing about whether that is actually the
    distribution the covered Requirement's own, S1-authored
    `verification_method` asked to have verified. Without this check, a
    candidate whose item.technical_identity is "esphome" could satisfy a
    Requirement whose verification_method literally reads
    "pip show requests" merely because "esphome" itself happens to be a
    valid, installable identity -- an unrelated package's presence claim
    would silently pass. `item.requirement_ref`'s own Requirement (the
    SAME S1 object Preflight already resolved, never re-derived or
    candidate-suppliable -- see `_requirement_by_id()`) must therefore
    independently parse, via the one fixed, controlled
    "pip show <distribution>" grammar (app.python_distribution.
    parse_pip_show_requirement -- never arbitrary shell parsing, never
    executed), to a distribution that PEP-503-normalizes to the EXACT
    same distribution `step.package` names (the identity
    ToolchainMaterializer.classify_item() itself already resolved and
    will actually install) -- reusing the SAME, central
    distribution_names_match() identity rule every other Python-package
    identity comparison in ADC already uses, never a second, competing
    normalization. A Requirement with no verification_method at all, or
    one that is not exactly this one controlled shape (a compound
    command, a pipe, a wrapper, extra flags, a different package, an
    empty package, or any other free-form text), can never establish
    this capability -- fail closed, never a partial/best-effort match.

    `project_root` (CLAUDE-ADC-S23-STRICT-IDENTITY-ENVIRONMENT-BINDING-
    FIX-004): forwarded unchanged to `_python_package_structural_
    capability()` -- see that function's own docstring for why S2.3
    itself must now know whether the candidate's selected environment
    has an actual, resolvable target before granting capability."""
    step = _python_package_structural_capability(item, variant, project_root)
    if step is None:
        return False
    requirement = _requirement_by_id(preflight, item.requirement_ref)
    if requirement is None:
        return False
    required_distribution = parse_pip_show_requirement(requirement.verification_method)
    if required_distribution is None:
        return False
    return (
        requirement.type == RequirementType.PYTHON_PACKAGE
        and is_valid_distribution_identifier(requirement.technical_identity)
        and distribution_names_match(requirement.technical_identity, required_distribution)
        and distribution_names_match(required_distribution, step.package)
    )


def _verification_coverage_is_compatible(
    coverage: "VerificationCoverage", variant: CouncilVariant,
    trusted_groups: tuple = (),
    governed_manual_verification_ids: frozenset[str] = frozenset(),
    preflight: PreflightResult | None = None,
    project_root: str | None = None,
) -> bool:
    """CLAUDE-ARCH-S2-013F/013G: closes the residual mechanical gaps left
    by CLAUDE-ARCH-S2-013E's and 013F's own independent reviews.

    013F closed: grounding alone (evidence names a real, candidate-local
    identity) is not enough -- a structurally valid but ecosystem-
    mismatched pair such as (mechanism="pytest", evidence=<a real npm
    ToolchainItem's identity>) must still fail. It introduced
    `ToolchainItem.provides_verification` -- a producer-declared
    capability relation -- and reused `ToolchainItem.state=="unavailable"`
    for controllability.

    013G closes the NEXT gap 013F's own independent review found:
    `provides_verification` is declared by the SAME Agent/Chairman that
    produces the candidate, so an LLM can still self-certify an invented
    or incompatible capability (e.g. declaring both mechanism="pytest"
    AND provides_verification=("pytest",) on a candidate that has
    nothing to do with pytest). A producer-declared claim can therefore
    never be the last word; it must additionally be corroborated by
    independent, trusted ADC evidence:

      LLM claim (mechanism)
        -> structured candidate declaration (provides_verification)
        -> independent/trusted ADC capability evidence (trusted_groups,
           from Project Intelligence's own deterministic, pre-Council
           detection -- see _trusted_verification_identity_groups())
        -> compatibility (both the item's identity AND the mechanism
           trace back to the SAME independently-detected capability)
        -> controllability/observability (ToolchainItem.state, unchanged)

    `manual_review` has nothing installable to be compatible with, so it
    is proven GOVERNED instead of tool-compatible: evidence must still
    self-reference a covered requirement (013E's existing grounding
    rule, unchanged), `VerificationCoverage.human_governed` must be
    explicitly True (013F, unchanged, still necessary but -- per the
    SAME self-certification concern -- no longer sufficient alone), AND
    every requirement_ref this entry claims to cover must independently
    appear in `governed_manual_verification_ids` -- ids ADC itself (not
    the Council/Chairman) has already recognized as having an actual
    governed human-verification path. No productive caller yet populates
    this set (see the module-level note on this parameter's callers);
    until one does, manual_review correctly never establishes coverage
    in production -- an explicit, honest, fail-closed limitation, not an
    oversight.

    Fail-closed: whenever compatibility/control/governance cannot be
    mechanically established from data the SAME candidate/LLM call did
    not itself produce, this returns False and the requirement stays
    uncovered -- it never falls back to accepting on ambiguity, and an
    empty `trusted_groups`/`governed_manual_verification_ids` (no
    independent evidence supplied at all) always fails every non-empty
    claim rather than silently skipping the check."""
    evidence = (coverage.evidence or "").strip()
    if not evidence:
        return False

    if coverage.kind == "manual_review":
        return (
            evidence in coverage.requirement_refs
            and coverage.human_governed is True
            and bool(coverage.requirement_refs)
            and all(ref in governed_manual_verification_ids for ref in coverage.requirement_refs)
        )

    item = _resolve_toolchain_item_for_evidence(evidence, variant)
    if item is not None:
        if item.state not in _CONTROLLABLE_TOOLCHAIN_STATES:
            return False
        if coverage.mechanism not in item.provides_verification:
            return False
        if coverage.mechanism == _PACKAGE_PRESENCE_MECHANISM:
            # CLAUDE-ADC-S23-VERIFICATION-EVIDENCE-ARCHITECTURE-FIX-002:
            # pre-install CAPABILITY, never presence, and never
            # corroborated through trusted_groups -- see
            # _python_package_verification_capability(). FIX-003 also
            # binds this to the covered Requirement's own
            # verification_method identity -- see that function. Note:
            # this whole-entry check is only reached directly for a
            # SINGLE-ref coverage entry -- _verification_feasibility_
            # gaps() (FIX-004) handles a multi-ref pip_show entry itself,
            # per-ref, via _pip_show_coverage_credited_refs(), so one
            # compatible item can never corroborate an unrelated
            # requirement_ref riding alongside it in the same entry.
            return _python_package_verification_capability(item, variant, preflight, project_root)
        item_identity = item.technical_identity or item.name or item.requirement_ref
        return _independently_corroborated(
            item_identity, coverage.mechanism, trusted_groups, coverage.area,
        )

    if coverage.kind in _SELF_EVIDENCED_VERIFICATION_KINDS and evidence in coverage.requirement_refs:
        return True

    return False


def _pip_show_coverage_credited_refs(
    coverage: "VerificationCoverage", variant: CouncilVariant,
    preflight: PreflightResult | None = None,
    project_root: str | None = None,
) -> frozenset[str]:
    """CLAUDE-ADC-S23-STRICT-IDENTITY-ENVIRONMENT-BINDING-FIX-004: closes
    the cross-requirement corroboration gap CDX-ADC-S23-VERIFICATION-
    IDENTITY-TARGET-BINDING-REVIEW-003 reproduced -- a `pip_show`
    VerificationCoverage entry's `evidence` string names exactly ONE
    ToolchainItem, but its `requirement_refs` may legitimately list
    several. The OLD code checked capability ONCE, for the single
    evidence-resolved item, and then credited EVERY listed ref with that
    one verdict -- so one compatible package's own coverage could
    silently corroborate a completely unrelated requirement_ref riding
    alongside it in the same entry (e.g. an entry covering both
    Requirement A, whose own `pip show <dist>` genuinely matches item A,
    and Requirement B, whose own `pip show <other-dist>` does NOT match
    the item actually claiming B).

    Every requirement_ref is therefore proven independently here, never
    inherited from a sibling ref's own result: for each ref, this
    resolves THAT ref's own claiming ToolchainItem through the actual
    current model association -- `item.requirement_ref == ref` (the
    SAME association ToolchainMaterializer/Preflight themselves use to
    bind an item to its requirement), never the coverage entry's shared
    `evidence` string, which only ever names one of them. A ref with no
    such item, an item in a non-controllable state, or an item that
    never declared this mechanism at all is never credited -- and each
    ref's own item must independently pass
    `_python_package_verification_capability()` (structural capability
    AND the covered Requirement's own `verification_method` identity
    match) before that specific ref is credited. Two independently
    valid refs (two different items, each genuinely matching its own
    requirement's `pip show` shape) are both credited -- this is
    strictly a fail-closed NARROWING of which refs get credited, never a
    new way to credit one that could not already pass
    `_python_package_verification_capability()` on its own merits."""
    credited: set[str] = set()
    for ref in coverage.requirement_refs:
        item = next(
            (candidate for candidate in variant.toolchain if candidate.requirement_ref == ref),
            None,
        )
        if item is None:
            continue
        if item.state not in _CONTROLLABLE_TOOLCHAIN_STATES:
            continue
        if coverage.mechanism not in item.provides_verification:
            continue
        if _python_package_verification_capability(item, variant, preflight, project_root):
            credited.add(ref)
    return frozenset(credited)


def _verification_coverage_incompatibility_reason(
    coverage: "VerificationCoverage", variant: CouncilVariant,
    trusted_groups: tuple = (),
    governed_manual_verification_ids: frozenset[str] = frozenset(),
    binding_ids: frozenset[str] = frozenset(),
    preflight: PreflightResult | None = None,
    project_root: str | None = None,
) -> str:
    """CLAUDE-ARCH-S2-013F/013G/014C repair evidence: names the EXACT
    mechanical reason one verification_coverage entry did not establish
    coverage -- which candidate, which requirement, which declared
    mechanism, which referenced evidence/capability, and the precise
    compatibility/control/governance/ref-validity reason -- so a bounded
    Chairman repair (see app.engineering_council's targeted-repair
    prompt, unchanged 011A/012D strategy) can correct the actual defect
    instead of guessing, exactly like CLAUDE-ARCH-S2-012D's
    materializability_conflict_detail already does for materializability."""
    if not _verification_coverage_refs_are_valid(coverage, binding_ids):
        phantom = [ref for ref in coverage.requirement_refs if ref not in binding_ids]
        return (
            f"requirement_refs={coverage.requirement_refs!r} contains "
            f"phantom/foreign/non-binding id(s) {phantom!r} -- the entire "
            "entry is rejected, including any legitimate ref it rides "
            "alongside (CLAUDE-ARCH-S2-014C)"
        )
    if coverage.kind not in _RECOGNIZED_VERIFICATION_KINDS:
        return f"kind={coverage.kind!r} is not a recognized verification kind"
    if not _is_structured_verification_token(coverage.mechanism):
        return f"mechanism={coverage.mechanism!r} is not a single structured token"
    evidence = (coverage.evidence or "").strip()
    if not evidence:
        return "evidence is empty"
    if coverage.kind == "manual_review":
        if evidence not in coverage.requirement_refs:
            return f"evidence={evidence!r} does not self-reference a covered requirement"
        if coverage.human_governed is not True:
            return "human_governed is not True (manual_review requires explicit governance)"
        ungoverned = [ref for ref in coverage.requirement_refs if ref not in governed_manual_verification_ids]
        return (
            "no actual governed ADC human-verification path is recognized for "
            f"requirement(s) {ungoverned!r} (human_governed=True alone is a "
            "candidate self-declaration, not independent ADC evidence)"
        )
    item = _resolve_toolchain_item_for_evidence(evidence, variant)
    if item is not None:
        if item.state not in _CONTROLLABLE_TOOLCHAIN_STATES:
            return (
                f"evidence={evidence!r} resolves to a ToolchainItem with "
                f"state={item.state!r}, not one of {sorted(_CONTROLLABLE_TOOLCHAIN_STATES)} "
                "-- ADC cannot control/observe this mechanism"
            )
        if coverage.mechanism not in item.provides_verification:
            return (
                f"mechanism={coverage.mechanism!r} not in evidence={evidence!r}'s "
                f"declared provides_verification={item.provides_verification!r}"
            )
        item_identity = item.technical_identity or item.name or item.requirement_ref
        if coverage.mechanism == _PACKAGE_PRESENCE_MECHANISM:
            # CLAUDE-ADC-S23-VERIFICATION-EVIDENCE-ARCHITECTURE-FIX-002:
            # this mechanism is never corroborated through trusted_groups
            # -- see _python_package_verification_capability() for the
            # exact, item-scoped, pre-install capability chain.
            if _python_package_verification_capability(item, variant, preflight, project_root):
                return (
                    f"mechanism={coverage.mechanism!r} and evidence identity="
                    f"{item_identity!r} ARE independently capability-"
                    "corroborated (this coverage entry is not the reason "
                    "its requirement is a gap)"
                )
            # CLAUDE-ADC-S23-VERIFICATION-IDENTITY-TARGET-BINDING-FIX-003:
            # only surface the identity-binding-specific diagnostic when
            # every OTHER structural precondition already passed (i.e.
            # the identity binding is genuinely the sole reason capability
            # was denied) -- never when an unrelated structural defect
            # (unsupported install_method, invalid identity, wrong
            # environment, ...) is the real cause, so this message is
            # never misleading about which check actually failed.
            structural_step = _python_package_structural_capability(item, variant, project_root)
            if structural_step is not None:
                requirement = _requirement_by_id(preflight, item.requirement_ref)
                required_distribution = parse_pip_show_requirement(
                    requirement.verification_method if requirement is not None else None,
                )
                if requirement is None:
                    return (
                        f"mechanism={coverage.mechanism!r} evidence={evidence!r}: "
                        f"no S1 Requirement is resolvable for "
                        f"{item.requirement_ref!r} to check its verification_method "
                        "against -- CLAUDE-ADC-S23-VERIFICATION-IDENTITY-TARGET-"
                        "BINDING-FIX-003"
                    )
                if required_distribution is None:
                    return (
                        f"mechanism={coverage.mechanism!r} evidence={evidence!r}: "
                        f"Requirement {item.requirement_ref!r}'s own "
                        f"verification_method={requirement.verification_method!r} "
                        "is not the controlled 'pip show <distribution>' shape "
                        "(no compound command, pipe, wrapper, flags, or free "
                        "prose is ever accepted) -- CLAUDE-ADC-S23-VERIFICATION-"
                        "IDENTITY-TARGET-BINDING-FIX-003"
                    )
                if not distribution_names_match(required_distribution, structural_step.package):
                    return (
                        f"mechanism={coverage.mechanism!r} evidence={evidence!r}: "
                        f"Requirement {item.requirement_ref!r}'s verification_method "
                        f"names distribution {required_distribution!r}, which does "
                        f"not identify the SAME Python distribution as this item's "
                        f"own resolved identity {structural_step.package!r} -- a "
                        "package-presence verification requirement must describe "
                        "exactly the selected package item, never a different one "
                        "(CLAUDE-ADC-S23-VERIFICATION-IDENTITY-TARGET-BINDING-FIX-003)"
                    )
            return (
                f"mechanism={coverage.mechanism!r} evidence={evidence!r} "
                f"(item identity={item_identity!r}): ADC has no controlled, "
                "target-specific Python-package verification CAPABILITY for "
                "this item -- requires item.type=PYTHON_PACKAGE, "
                f"variant.environment={variant.environment!r} in the fixed "
                f"set {sorted(_CONTROLLED_PYTHON_PACKAGE_ENVIRONMENTS)!r} "
                "(never inferred from the string), a controlled setup "
                "effect, and ToolchainMaterializer.classify_item() "
                "resolving to action='install' -- a candidate's own "
                "provides_verification declaration alone is never "
                "sufficient, and this is never corroborated by any "
                "environment-wide/controller-process evidence"
            )
        capability_exists_elsewhere = any(
            _identity_corroborates(item_identity, coverage.mechanism, group.identities)
            for group in trusted_groups
        )
        if capability_exists_elsewhere:
            # CLAUDE-ARCH-S2-014D: the identity/mechanism pair IS
            # independently trusted somewhere -- just not at a scope
            # this coverage entry's own declared `area` can draw on.
            return (
                f"mechanism={coverage.mechanism!r} and evidence identity="
                f"{item_identity!r} are independently corroborated only for "
                f"area(s) outside {coverage.area!r} (VerificationCoverage.area) "
                "-- CLAUDE-ARCH-S2-014D: capability Project Intelligence "
                "detected in one area/path never legitimizes an unrelated "
                "area/path's requirement, and evidence with no declared area "
                "is only ever covered by capability detected at the project "
                "root"
            )
        return (
            f"mechanism={coverage.mechanism!r} and evidence identity="
            f"{item_identity!r} are only corroborated by the candidate's own "
            "provides_verification declaration -- no independent Project "
            "Intelligence evidence traces both to the same real capability "
            "(a self-certified provides_verification value alone cannot "
            "establish verification feasibility)"
        )
    if coverage.kind in _SELF_EVIDENCED_VERIFICATION_KINDS:
        return (
            f"evidence={evidence!r} neither self-references a covered "
            "requirement nor resolves to a candidate-local ToolchainItem"
        )
    return f"evidence={evidence!r} does not resolve to any candidate-local ToolchainItem"


def _verification_feasibility_gap_diagnostics(
    variant: CouncilVariant, gap_ids: tuple[str, ...],
    trusted_groups: tuple = (),
    governed_manual_verification_ids: frozenset[str] = frozenset(),
    binding_ids: frozenset[str] = frozenset(),
    preflight: PreflightResult | None = None,
    project_root: str | None = None,
) -> tuple[str, ...]:
    """Per-gap-requirement diagnostic detail lines for the rejection
    reason text -- one per verification_coverage entry that claimed the
    requirement but failed, or a single "no entry references it" line
    when nothing on the candidate even attempted coverage."""
    diagnostics: list[str] = []
    for req_id in gap_ids:
        entries = tuple(c for c in variant.verification_coverage if req_id in c.requirement_refs)
        if not entries:
            diagnostics.append(f"{req_id}: no verification_coverage entry references this requirement")
            continue
        for coverage in entries:
            diagnostics.append(
                f"{req_id}: mechanism={coverage.mechanism!r} evidence={coverage.evidence!r} -> "
                f"{_verification_coverage_incompatibility_reason(coverage, variant, trusted_groups, governed_manual_verification_ids, binding_ids, preflight, project_root)}"
            )
    return tuple(diagnostics)


def _verification_feasibility_gaps(
    variant: CouncilVariant, preflight: PreflightResult | None, binding_ids: frozenset[str],
    trusted_groups: tuple = (),
    governed_manual_verification_ids: frozenset[str] = frozenset(),
    project_root: str | None = None,
) -> tuple[str, ...]:
    """S2.3 Verification Feasibility (CLAUDE-ARCH-S2-013E, closing the
    CLAUDE-ARCH-S2-013A LOW-MEDIUM finding): the exact, sorted binding
    requirement ids that need verification (per S1's own, unchanged
    Requirement.verification_method contract) but for which this
    candidate's structured verification_coverage does NOT establish a
    mechanically meaningful chain: binding Requirement -> a recognized,
    technology-neutral mechanism KIND -> a concrete, structured mechanism
    identity -> evidence grounding it in this SAME candidate's own
    toolchain. A merely non-empty CouncilVariant.verification free-text
    field (e.g. "run tests") is deliberately NEVER sufficient on its own
    -- this function looks exclusively at verification_coverage. A
    binding requirement with no verification_method at all never
    triggers this (irrelevant/non-binding verification information must
    never cause a false rejection, unchanged since CLAUDE-ARCH-S2-012B
    Gate E). This function only ESTABLISHES that a legitimate
    verification route exists -- it never executes anything and never
    predicts a pass/fail outcome; S5 Quality & Verification remains
    solely responsible for that."""
    needing = _binding_requirements_needing_verification(preflight, binding_ids)
    if not needing:
        return ()
    covered: set[str] = set()
    for coverage in variant.verification_coverage:
        if not _verification_coverage_refs_are_valid(coverage, binding_ids):
            continue
        if coverage.kind not in _RECOGNIZED_VERIFICATION_KINDS:
            continue
        if not _is_structured_verification_token(coverage.mechanism):
            continue
        if not _verification_coverage_is_grounded(coverage, variant):
            continue
        if coverage.mechanism == _PACKAGE_PRESENCE_MECHANISM:
            # CLAUDE-ADC-S23-STRICT-IDENTITY-ENVIRONMENT-BINDING-FIX-004:
            # a pip_show entry's `requirement_refs` may list several ids
            # behind one shared `evidence` string -- each is proven
            # independently against ITS OWN claiming item/Requirement
            # (see _pip_show_coverage_credited_refs()), never credited
            # in bulk from a single evidence-resolved item's verdict.
            covered.update(_pip_show_coverage_credited_refs(
                coverage, variant, preflight, project_root,
            ))
            continue
        if not _verification_coverage_is_compatible(
            coverage, variant, trusted_groups, governed_manual_verification_ids, preflight, project_root,
        ):
            continue
        covered.update(coverage.requirement_refs)
    return tuple(sorted(set(needing) - covered))


def validate_variants(
    variants: tuple[CouncilVariant, ...],
    preflight: PreflightResult | None = None,
    platform: str | None = None,
    trusted_verification_groups: tuple = (),
    governed_manual_verification_ids: frozenset[str] = frozenset(),
    project_root: str | None = None,
) -> tuple[CandidateValidation, ...]:
    """S2.3 Engineering Admissibility -- THE single technical admissibility
    authority inside S2 (CLAUDE-ARCH-S2-012A). Deterministically classifies
    every given CouncilVariant as admissible or inadmissible with exact,
    safe, structured reasons. This is the ONLY decision the deterministic
    layer makes on its own; it never picks among several admissible
    candidates (see resolve_human_engineering_selection()/
    select_engineering_variant()), never merges candidates, and never
    changes a candidate's content.

    Takes `variants` directly (not a full CouncilResult) so this S2.3
    authority has no dependency on the S2.2-owned CouncilResult type --
    any producer of a tuple of CouncilVariant can call it directly (see
    app.engineering_council's own early rework check, which calls this
    exact function rather than re-implementing admissibility).

    `trusted_verification_groups` (CLAUDE-ARCH-S2-013G): the independent,
    ADC-owned, pre-Council capability evidence Verification Feasibility's
    mechanism-compatibility check requires -- each entry is a set of
    interchangeable identity strings ADC itself has already,
    deterministically confirmed refer to the SAME real capability in this
    project (see the Generalized Verification module's own
    trusted_verification_identity_groups() helper, which derives this
    from Project Intelligence's own read-only detection plus that
    module's own runner maps -- deliberately computed OUTSIDE this
    module so S2.3 stays free of any import on S5 execution code; the
    caller passes the already-computed result in as plain data).
    Optional and additive: a caller that omits it gets the fully
    fail-closed default (no
    provides_verification claim can be corroborated), never a silent
    bypass of the new check. `governed_manual_verification_ids`: ids ADC
    has independently recognized as having an actual governed human-
    verification path for kind="manual_review" coverage; empty by
    default (no productive caller populates this yet -- see the module
    note at EngineeringReworkRequest).

    `project_root` (CLAUDE-ADC-S23-STRICT-IDENTITY-ENVIRONMENT-BINDING-
    FIX-004): optional and additive, forwarded unchanged into the
    pip_show verification-capability check
    (_python_package_verification_capability()) so S2.3 itself can know
    whether a "venv" candidate has an actual, resolvable target BEFORE
    admissibility is decided -- never a competing environment resolver,
    the SAME app.python_distribution.resolve_environment_python_target()
    materialize_decision() itself uses. Omitting it preserves the exact
    prior behavior for "host" candidates (project_root is irrelevant to
    host resolution) and fails a "venv" candidate's pip_show capability
    closed (an unresolvable target is never assumed resolvable)."""
    binding_ids = _binding_requirement_ids(preflight)
    trusted_groups = tuple(trusted_verification_groups)
    # CLAUDE-ARCH-S2-014C (F3), defense-in-depth: validate_variants()
    # deliberately has no dependency on app.engineering_council's own
    # structural duplicate-id rejection (see _parse_chairman_result())
    # -- ANY producer of a tuple of CouncilVariant can call this function
    # directly, so S2.3 must not silently TRUST that its caller already
    # guaranteed unique ids. A duplicated id makes the identity of every
    # variant sharing it ambiguous -- "which candidate is this?" no
    # longer has one answer -- so every one of them is inadmissible,
    # never merely the second/later occurrence.
    id_counts: dict[str, int] = {}
    for variant in variants:
        id_counts[variant.id] = id_counts.get(variant.id, 0) + 1
    duplicate_ids = frozenset(vid for vid, count in id_counts.items() if count > 1)
    results = []
    for variant in variants:
        reasons: list[str] = []
        # A5: a requirement satisfied only for a DIFFERENT target than
        # this exact variant's own environment would use is binding
        # candidate coverage for THIS variant specifically -- never a
        # single, environment-blind set shared by every variant.
        effective_binding_ids = binding_ids | _environment_scoped_binding_requirement_ids(
            preflight, variant, project_root,
        )
        if variant.id in duplicate_ids:
            reasons.append(
                f"ambiguous variant identity: id {variant.id!r} is shared by "
                f"{id_counts[variant.id]} candidates -- a duplicated id can "
                "never be safely selected"
            )
        unsatisfied_requirements = _semantically_unsatisfied_binding_requirements(
            variant, effective_binding_ids, preflight,
        )
        if unsatisfied_requirements:
            reasons.append(
                f"missing binding requirement coverage: {list(unsatisfied_requirements)}"
            )
        platform_conflict = _violates_platform_constraint(variant, platform)
        if platform_conflict:
            reasons.append(f"violates platform constraint for platform={platform!r}")
        unmaterializable = _unmaterializable_binding_requirements(variant, effective_binding_ids)
        if unmaterializable:
            detail = ", ".join(
                f"{req_id} (item name={name!r})"
                for req_id, name, _category in unmaterializable
            )
            reasons.append(
                "a controlled binding requirement cannot be materialized "
                "as an executable install step: "
                f"{detail}"
            )
        verification_gaps = _verification_feasibility_gaps(
            variant, preflight, effective_binding_ids, trusted_groups, governed_manual_verification_ids,
            project_root,
        )
        verification_gap_diagnostics: tuple[str, ...] = ()
        if verification_gaps:
            verification_gap_diagnostics = tuple(_verification_feasibility_gap_diagnostics(
                variant, verification_gaps, trusted_groups, governed_manual_verification_ids, effective_binding_ids,
                preflight, project_root,
            ))
            reasons.append(
                "missing required verification coverage for binding "
                f"Requirement(s): {sorted(verification_gaps)} (variant={variant.id!r}): "
                "no recognized, evidenced, capability-compatible, controllable "
                "verification mechanism (test_command/build_command/"
                "static_analysis/probe/smoke_test/config_validation/"
                "manual_review) covers this requirement"
                + ("; " + "; ".join(verification_gap_diagnostics) if verification_gap_diagnostics else "")
            )
        results.append(CandidateValidation(
            variant=variant,
            solution_class=classify_engineering_solution(variant),
            admissible=not reasons,
            reasons=tuple(reasons),
            unmaterializable_items=unmaterializable,
            duplicate_variant_identity=variant.id in duplicate_ids,
            missing_binding_requirement_ids=tuple(unsatisfied_requirements),
            platform_conflict=platform_conflict,
            verification_feasibility_gap_ids=tuple(sorted(verification_gaps)),
            verification_feasibility_gap_diagnostics=verification_gap_diagnostics,
        ))
    return tuple(results)


def validate_candidates(
    council_result: CouncilResult,
    preflight: PreflightResult | None = None,
    platform: str | None = None,
    trusted_verification_groups: tuple = (),
    governed_manual_verification_ids: frozenset[str] = frozenset(),
    project_root: str | None = None,
) -> tuple[CandidateValidation, ...]:
    """S2.3 Engineering Admissibility. Backward-compatible convenience
    wrapper around validate_variants() for callers that already hold a
    full CouncilResult.

    `project_root` (CLAUDE-ADC-S23-STRICT-IDENTITY-ENVIRONMENT-BINDING-
    FIX-004): forwarded, unmodified, to validate_variants() -- see its
    own docstring."""
    return validate_variants(
        council_result.variants, preflight, platform,
        trusted_verification_groups, governed_manual_verification_ids,
        project_root,
    )


def admissible_variants(validations: tuple[CandidateValidation, ...]) -> tuple[CouncilVariant, ...]:
    """S2.3 Engineering Admissibility."""
    return tuple(v.variant for v in validations if v.admissible)


def categorize_admissibility_reasons(reasons: tuple[str, ...]) -> str:
    """S2.3 Engineering Admissibility: maps a CandidateValidation's own
    deterministic reason strings to a coarse, stable, safe diagnostic
    category (CLAUDE-ARCH-S2-012A, Part 28) -- e.g. for a Diagnostic
    Trace fault-localization line such as "S2.3 NIO: platform_constraint".
    Never invents a new admissibility rule; purely classifies the exact
    reasons validate_variants() already produced."""
    if not reasons:
        return "admissible"
    joined = " ".join(reasons)
    if "ambiguous variant identity" in joined:
        return "duplicate_variant_identity"
    if "missing binding requirement coverage" in joined:
        return "completeness_validation"
    if "violates platform constraint" in joined:
        return "platform_constraint"
    if "cannot be materialized" in joined:
        return "materializability_conflict"
    if "missing required verification coverage" in joined:
        return "verification_coverage"
    return "admissibility_validation"


def _admissibility_reason_categories(validation: "CandidateValidation") -> tuple[str, ...]:
    """CLAUDE-ADC-ZIELBILD-DIFF-FIX-001 (D1): the exact set of
    S2.3-computed structured failure categories for one candidate --
    checked directly against validate_variants()'s own structured
    CandidateValidation fields, never derived by parsing `reasons`'
    human-readable text. Unlike categorize_admissibility_reasons()
    (a separate, unchanged, single first-match category kept for its
    own Diagnostic Trace fault-localization contract), several
    categories can legitimately apply to the same candidate at once --
    e.g. a candidate can simultaneously omit a binding requirement AND
    carry an unmaterializable item -- and the S2.3 -> S2.2 rework
    contract must see all of them, not just the first."""
    categories: list[str] = []
    if validation.duplicate_variant_identity:
        categories.append("duplicate_variant_identity")
    if validation.missing_binding_requirement_ids:
        categories.append("completeness_validation")
    if validation.platform_conflict:
        categories.append("platform_constraint")
    if validation.unmaterializable_items:
        categories.append("materializability_conflict")
    if validation.verification_feasibility_gap_ids:
        categories.append("verification_coverage")
    return tuple(categories) if categories else ("admissible",)


def resolve_human_engineering_selection(
    validations: tuple[CandidateValidation, ...],
    *,
    chairman_recommendation: str | None = None,
    human_selected_variant_id: str | None = None,
) -> tuple[CandidateValidation, str]:
    """S2.4 Human Engineering Authority (CLAUDE-ARCH-S2-012A). Consumes
    ONLY an already-computed S2.3 CandidateValidation set -- never
    re-evaluates technical admissibility itself -- and decides WHICH
    admissible candidate is chosen and by WHOM, WITHOUT the deterministic
    layer choosing which admissible candidate is "preferred". Multiple
    technically valid solutions may coexist (Host, venv, Docker, VM,
    ...); this function only ever:

      - rejects a recommendation/selection that is technically
        inadmissible (raising ChairmanRecommendationInadmissibleError,
        never silently substituting another candidate for it) --
        Human authority may override the Chairman's recommendation, but
        may NEVER override technical admissibility,
      - honors an explicit human_selected_variant_id over the Chairman's
        own chairman_recommendation when both are given (a deliberate
        human override of the recommendation),
      - honors chairman_recommendation as-is whenever it is admissible,
      - auto-selects the sole admissible candidate when exactly one
        exists and no recommendation/selection was given (there is no
        choice being forced in that case -- there is only one option),
      - otherwise raises EngineeringSelectionRequiredError: with more
        than one admissible candidate and no recommendation or human
        selection, the deterministic layer must not decide on its own.

    Raises NoEligibleEngineeringCandidateError when no candidate in
    `validations` is admissible at all -- there is nothing for the
    Chairman or a human to choose from.

    Returns (matched CandidateValidation, selection_authority) -- S2.5's
    build_engineering_decision() turns this into the final
    EngineeringDecision artifact.
    """
    admissible = admissible_variants(validations)
    if not admissible:
        raise NoEligibleEngineeringCandidateError(
            "No proposed engineering candidate satisfies every binding "
            "Requirement/Constraint with a valid controlled-or-explicitly-"
            "manual execution model for this project.",
            validations=validations,
        )

    if human_selected_variant_id is not None:
        chosen_id, authority = human_selected_variant_id, "human"
    elif chairman_recommendation is not None:
        chosen_id, authority = chairman_recommendation, "chairman"
    elif len(admissible) == 1:
        return validations_by_id(validations, admissible[0].id), "sole_admissible"
    else:
        raise EngineeringSelectionRequiredError(
            "Multiple engineering candidates are admissible; an explicit "
            "Chairman recommendation or human selection is required -- "
            "the deterministic layer does not choose between them."
        )

    match = next((v for v in validations if v.variant.id == chosen_id), None)
    if match is None:
        raise EngineeringVariantNotFoundError(
            f"Selected variant id was not proposed by the Council: {chosen_id}"
        )
    if not match.admissible:
        raise ChairmanRecommendationInadmissibleError(
            f"Selected variant {chosen_id!r} is not technically admissible: "
            f"{'; '.join(match.reasons)}",
            recommendation_id=chosen_id,
            admissible=admissible,
            rejected=tuple(v for v in validations if not v.admissible),
        )
    return match, authority


def build_engineering_decision(match: CandidateValidation, selection_authority: str) -> EngineeringDecision:
    """S2.5 Engineering Decision & S3 Handoff (CLAUDE-ARCH-S2-012A).
    Constructs the final, immutable EngineeringDecision artifact from an
    already-resolved S2.4 selection -- the only artifact that may
    normally cross the S2 -> S3 boundary. Performs no validation or
    authority resolution of its own; those are exclusively S2.3's and
    S2.4's jobs, already done by the time this is called."""
    return EngineeringDecision(
        variant=match.variant, solution_class=match.solution_class,
        selection_authority=selection_authority,
    )


def select_engineering_variant(
    council_result: CouncilResult,
    preflight: PreflightResult | None = None,
    platform: str | None = None,
    *,
    chairman_recommendation: str | None = None,
    human_selected_variant_id: str | None = None,
    trusted_verification_groups: tuple = (),
    governed_manual_verification_ids: frozenset[str] = frozenset(),
    project_root: str | None = None,
) -> EngineeringDecision:
    """The S2.3 -> S2.4 -> S2.5 pipeline entry point (CLAUDE-ARCH-S2-012A):
    validate_variants() (S2.3) -> resolve_human_engineering_selection()
    (S2.4) -> build_engineering_decision() (S2.5). Kept as a single call
    for the overwhelming majority of callers (e.g.
    ToolchainMaterializer.materialize(), the S2/S3 compatibility path)
    that just want "the decision" -- this function itself decides and
    validates nothing; see the three composed functions for the actual
    per-Subsubsystem contracts and exceptions raised.

    `trusted_verification_groups`/`governed_manual_verification_ids`
    (CLAUDE-ARCH-S2-013G): forwarded, unmodified, to validate_candidates()
    -- see its own docstring.

    `project_root` (CLAUDE-ADC-S23-STRICT-IDENTITY-ENVIRONMENT-BINDING-
    FIX-004): forwarded, unmodified, to validate_candidates() so S2.3's
    pip_show verification-capability check can determine whether the
    selected candidate's own environment has an actual, resolvable
    target -- see _python_package_structural_capability()'s own
    docstring.
    """
    validations = validate_candidates(
        council_result, preflight, platform,
        trusted_verification_groups, governed_manual_verification_ids,
        project_root,
    )
    match, authority = resolve_human_engineering_selection(
        validations,
        chairman_recommendation=chairman_recommendation,
        human_selected_variant_id=human_selected_variant_id,
    )
    return build_engineering_decision(match, authority)


def validations_by_id(validations: tuple[CandidateValidation, ...], variant_id: str) -> CandidateValidation:
    return next(v for v in validations if v.variant.id == variant_id)


def describe_engineering_variant_selection(
    council_result: CouncilResult,
    preflight: PreflightResult | None = None,
    platform: str | None = None,
    *,
    chairman_recommendation: str | None = None,
    human_selected_variant_id: str | None = None,
    trusted_verification_groups: tuple = (),
    governed_manual_verification_ids: frozenset[str] = frozenset(),
    project_root: str | None = None,
) -> EngineeringVariantSelection:
    """Non-raising counterpart to select_engineering_variant(), meant to be
    presented to a human (CLAUDE-PRE-E2E-009C, Part 5): the Chairman's
    recommendation, every candidate's admissible-or-rejected-with-reasons
    validation, and whichever variant id is currently selected -- or None,
    with selection_authority="none", when nothing could yet be resolved
    (no eligible candidate, an inadmissible recommendation, or several
    admissible candidates awaiting an explicit choice).

    `project_root` (CLAUDE-ADC-S23-STRICT-IDENTITY-ENVIRONMENT-BINDING-
    FIX-004): forwarded, unmodified, to validate_candidates() -- see
    select_engineering_variant()'s own docstring."""
    validations = validate_candidates(
        council_result, preflight, platform,
        trusted_verification_groups, governed_manual_verification_ids,
        project_root,
    )
    try:
        match, authority = resolve_human_engineering_selection(
            validations,
            chairman_recommendation=chairman_recommendation,
            human_selected_variant_id=human_selected_variant_id,
        )
    except (
        NoEligibleEngineeringCandidateError,
        ChairmanRecommendationInadmissibleError,
        EngineeringSelectionRequiredError,
        EngineeringVariantNotFoundError,
    ) as error:
        # D2: preserve the non-raising presentation contract (still
        # selected_variant_id=None, selection_authority="none" -- an
        # existing, relied-upon contract, unchanged) while additionally
        # exposing a bounded, machine-readable reason distinguishing
        # WHY selection is unresolved, never the raw exception string.
        unresolved_reason = {
            NoEligibleEngineeringCandidateError: "no_eligible_candidate",
            ChairmanRecommendationInadmissibleError: "recommendation_inadmissible",
            EngineeringSelectionRequiredError: "selection_required",
            EngineeringVariantNotFoundError: "selected_variant_not_found",
        }[type(error)]
        return EngineeringVariantSelection(
            council_result=council_result,
            chairman_recommendation=chairman_recommendation,
            validations=validations,
            selected_variant_id=None,
            selection_authority="none",
            unresolved_reason=unresolved_reason,
        )
    return EngineeringVariantSelection(
        council_result=council_result,
        chairman_recommendation=chairman_recommendation,
        validations=validations,
        selected_variant_id=match.variant.id,
        selection_authority=authority,
    )
