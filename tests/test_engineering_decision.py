"""S2 Engineering candidate validation and variant selection contracts
(CLAUDE-PRE-E2E-009B, corrected by CLAUDE-PRE-E2E-009C).

ADC's documented governance (ADC_Zielbild_Ausfuehrliche_Beschreibung.txt,
Abschnitt 2): the Council proposes alternatives, the deterministic layer
only ever marks each one technically admissible or inadmissible, the
Chairman synthesizes and selects a recommendation among the admissible
ones, and the human may accept it or choose another admissible
alternative. Multiple technically valid Engineering solutions (Host,
venv, Docker, VM, ...) may legitimately coexist -- the deterministic
layer must reject an INADMISSIBLE candidate, but it must never decide
WHICH admissible candidate the Chairman or the human is forced to use.

CLAUDE-PRE-E2E-009B's own tests encoded the opposite assumption for
several scenarios (a mutation-free candidate always beats a valid
mutating one, a stable hash tie-break silently overrides an admissible
Chairman recommendation when no recommendation was even given). Those
scenarios are corrected below; the genuine technical-admissibility
invariants 009B introduced (binding Requirement coverage, Constraint
compliance, materializability) are unchanged and still covered.
"""
import pytest

from app.council_models import (
    CouncilResult, CouncilVariant, ToolchainItem, VerificationCoverage,
)
from app.engineering_decision import (
    ChairmanRecommendationInadmissibleError,
    EngineeringReworkRequest,
    EngineeringSelectionRequiredError,
    EngineeringVariantNotFoundError,
    NoEligibleEngineeringCandidateError,
    admissible_variants,
    binding_materializer_diagnostics,
    categorize_admissibility_reasons,
    select_engineering_variant,
    validate_candidates,
    validate_variants,
)
from app.requirement_model import (
    PreflightRequirementResult,
    PreflightResult,
    Requirement,
    RequirementActivation,
    RequirementType,
)


def _requirement(req_id="req-esphome", required=True):
    return Requirement(
        technical_identity="esphome",
        id=req_id, name="esphome", type=RequirementType.PYTHON_PACKAGE,
        purpose="firmware build", required=required, confidence=0.9,
    )


def _requirement_needing_verification(req_id="req-esphome", verification_method="pytest tests/"):
    return Requirement(
        technical_identity="esphome",
        id=req_id, name="esphome", type=RequirementType.PYTHON_PACKAGE,
        purpose="firmware build", required=True, confidence=0.9,
        verification_method=verification_method,
    )


def _binding_preflight(requirement):
    return PreflightResult(
        id="pre-1", project_id="proj", overall_ready=False,
        results=(
            PreflightRequirementResult(
                requirement_id=requirement.id, present=False, satisfied=False,
                active=True, blocks_current_operation=True,
            ),
        ),
        missing_requirements=(requirement,),
        activations=(RequirementActivation(requirement.id, True, True),),
    )


def _pip_item(requirement_ref, install_method="pip", state="needs_install",
              environment_constraint=None, provided_by=None,
              provides_verification=("pytest",), technical_identity="esphome"):
    return ToolchainItem(
        requirement_ref=requirement_ref, name="esphome",
        type=RequirementType.PYTHON_PACKAGE, technical_identity=technical_identity,
        install_method=install_method, state=state,
        environment_constraint=environment_constraint, provided_by=provided_by,
        provides_verification=provides_verification,
    )


def _trusted_intelligence(test_systems=(), build_systems=(), firmware_indicators=()):
    """CLAUDE-ARCH-S2-013G: the dict-shaped independent, ADC-owned
    Project Intelligence evidence app.verification.trusted_verification_
    identity_groups() (and, through it, S2.3's mechanism-compatibility
    check) consumes -- the exact shape CouncilInput.project_intelligence
    already carries in production. Never itself a verification source of
    truth: it only lists identities a real Project Intelligence pass
    would have independently, deterministically detected."""
    return {
        "test_systems": list(test_systems),
        "build_systems": list(build_systems),
        "firmware_indicators": list(firmware_indicators),
    }


def _trusted_groups(test_systems=(), build_systems=(), firmware_indicators=()):
    """Convenience wrapper: builds the same trusted evidence directly as
    the `trusted_verification_groups` tuple validate_variants()/
    validate_candidates() accept, via the SAME production helper
    (app.verification.trusted_verification_identity_groups) most tests
    below call through -- kept here so tests do not hand-roll their own
    grouping logic."""
    from app.verification import trusted_verification_identity_groups
    return trusted_verification_identity_groups(
        _trusted_intelligence(test_systems, build_systems, firmware_indicators)
    )


def _multi_requirement_preflight(*requirements, non_binding=()):
    """Real-System-E2E #5 shape (CLAUDE-E2E-NIO-010A): more than one
    binding Requirement, plus an optional set of NON-binding ones
    (missing but either not required or not blocking) that must never
    affect admissibility (Part 9.D)."""
    results = tuple(
        PreflightRequirementResult(
            requirement_id=r.id, present=False, satisfied=False,
            active=True, blocks_current_operation=True,
        )
        for r in requirements
    ) + tuple(
        PreflightRequirementResult(
            requirement_id=r.id, present=False, satisfied=False,
            active=True, blocks_current_operation=False,
        )
        for r in non_binding
    )
    return PreflightResult(
        id="pre-1", project_id="proj", overall_ready=False,
        results=results,
        missing_requirements=tuple(requirements) + tuple(non_binding),
        activations=tuple(
            RequirementActivation(r.id, True, True) for r in requirements
        ) + tuple(
            RequirementActivation(r.id, True, False) for r in non_binding
        ),
    )


class TestBindingRequirementCoverage:
    """Part 9.A/9.B -- still-valid technical validation invariant from 009B."""

    def test_candidate_missing_a_binding_requirement_is_inadmissible(self):
        requirement = _requirement()
        preflight = _binding_preflight(requirement)
        variant_missing = CouncilVariant(id="v1", name="v1", toolchain=())
        result = CouncilResult(
            id="c1", project_id="proj", variants=(variant_missing,),
            recommendation="v1", council_complete=True,
        )

        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is False
        assert "missing binding requirement coverage" in validations[0].reasons[0]

        with pytest.raises(NoEligibleEngineeringCandidateError):
            select_engineering_variant(
                result, preflight=preflight, chairman_recommendation="v1",
            )

    def test_candidate_covering_all_binding_requirements_is_admissible(self):
        requirement = _requirement()
        preflight = _binding_preflight(requirement)
        variant = CouncilVariant(id="v1", name="v1", toolchain=(_pip_item(requirement.id),))
        result = CouncilResult(
            id="c1", project_id="proj", variants=(variant,),
            recommendation="v1", council_complete=True,
        )

        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is True

        decision = select_engineering_variant(
            result, preflight=preflight, chairman_recommendation="v1",
        )
        assert decision.variant.id == "v1"
        assert decision.selection_authority == "chairman"


class TestConstraintEnforcement:
    """Part 9.B -- still-valid technical validation invariant from 009B."""

    def test_candidate_violating_a_binding_constraint_is_inadmissible(self):
        requirement = _requirement()
        preflight = _binding_preflight(requirement)
        violating = CouncilVariant(
            id="v1", name="v1",
            toolchain=(_pip_item(requirement.id, environment_constraint="windows"),),
        )
        compliant = CouncilVariant(
            id="v2", name="v2",
            toolchain=(_pip_item(requirement.id, environment_constraint="linux"),),
        )
        result = CouncilResult(
            id="c1", project_id="proj", variants=(violating, compliant),
            recommendation="v1", council_complete=True,
        )

        validations = validate_candidates(result, preflight=preflight, platform="linux")
        by_id = {v.variant.id: v for v in validations}
        assert by_id["v1"].admissible is False
        assert by_id["v2"].admissible is True

        # The Chairman recommended the inadmissible one -- ADC must reject
        # it, not silently switch to "v2" and call that the recommendation.
        with pytest.raises(ChairmanRecommendationInadmissibleError) as excinfo:
            select_engineering_variant(
                result, preflight=preflight, platform="linux",
                chairman_recommendation="v1",
            )
        assert excinfo.value.recommendation_id == "v1"
        assert [v.id for v in excinfo.value.admissible] == ["v2"]

    def test_all_candidates_violating_the_constraint_raises(self):
        requirement = _requirement()
        preflight = _binding_preflight(requirement)
        violating = CouncilVariant(
            id="v1", name="v1",
            toolchain=(_pip_item(requirement.id, environment_constraint="windows"),),
        )
        result = CouncilResult(
            id="c1", project_id="proj", variants=(violating,),
            recommendation="v1", council_complete=True,
        )

        with pytest.raises(NoEligibleEngineeringCandidateError):
            select_engineering_variant(
                result, preflight=preflight, platform="linux",
                chairman_recommendation="v1",
            )


class TestMaterializabilityEligibility:
    """Part 9.C/9.D -- CLAUDE-E2E-NIO-008A's specific failure class,
    still enforced as a technical-admissibility condition. Part 9.I/9.J
    corrects HOW an inadmissible recommendation is handled: it must be
    rejected, never silently swapped for an admissible alternative."""

    def test_controlled_candidate_that_cannot_materialize_is_inadmissible(self):
        requirement = _requirement()
        preflight = _binding_preflight(requirement)
        broken = CouncilVariant(
            id="v1", name="v1",
            toolchain=(_pip_item(
                requirement.id,
                install_method="python3 -m venv .venv && source .venv/bin/activate && pip install esphome",
            ),),
        )
        working = CouncilVariant(id="v2", name="v2", toolchain=(_pip_item(requirement.id),))
        result = CouncilResult(
            id="c1", project_id="proj", variants=(broken, working),
            recommendation="v1", council_complete=True,
        )

        validations = validate_candidates(result, preflight=preflight)
        by_id = {v.variant.id: v for v in validations}
        assert by_id["v1"].admissible is False
        assert by_id["v2"].admissible is True

    def test_inadmissible_chairman_recommendation_cannot_proceed_to_s3(self):
        """Part 9.I/9.J: an inadmissible Chairman recommendation must be
        rejected outright -- it must not be silently replaced by another
        admissible candidate while still being presented as though it
        were the Chairman's own choice."""
        requirement = _requirement()
        preflight = _binding_preflight(requirement)
        broken = CouncilVariant(
            id="v1", name="v1",
            toolchain=(_pip_item(
                requirement.id,
                install_method="python3 -m venv .venv && source .venv/bin/activate && pip install esphome",
            ),),
        )
        working = CouncilVariant(id="v2", name="v2", toolchain=(_pip_item(requirement.id),))
        result = CouncilResult(
            id="c1", project_id="proj", variants=(broken, working),
            recommendation="v1", council_complete=True,
        )

        with pytest.raises(ChairmanRecommendationInadmissibleError) as excinfo:
            select_engineering_variant(
                result, preflight=preflight, chairman_recommendation="v1",
            )
        # The exception must name the ORIGINAL (inadmissible) id, never a
        # substituted one -- proving no silent substitution took place.
        assert excinfo.value.recommendation_id == "v1"
        assert [v.id for v in excinfo.value.admissible] == ["v2"]

        from app.toolchain_materializer import ToolchainMaterializer
        with pytest.raises(ChairmanRecommendationInadmissibleError):
            ToolchainMaterializer().materialize(result, "proj", preflight=preflight)

    def test_unmaterializable_only_candidate_raises_rather_than_binding(self):
        requirement = _requirement()
        preflight = _binding_preflight(requirement)
        broken = CouncilVariant(
            id="v1", name="v1",
            toolchain=(_pip_item(
                requirement.id,
                install_method="python3 -m venv .venv && source .venv/bin/activate && pip install esphome",
            ),),
        )
        result = CouncilResult(
            id="c1", project_id="proj", variants=(broken,),
            recommendation="v1", council_complete=True,
        )

        with pytest.raises(NoEligibleEngineeringCandidateError):
            select_engineering_variant(
                result, preflight=preflight, chairman_recommendation="v1",
            )

    def test_legitimately_manual_requirement_type_is_admissible(self):
        """Part 9.D: a binding requirement of a type with no controlled
        executor at all (e.g. SDK) is SUPPOSED to become manual_review --
        explicitly-manual execution is a valid, admissible model, not a
        defect."""
        sdk_requirement = Requirement(
            id="req-sdk", name="ESP-IDF", type=RequirementType.SDK,
            purpose="firmware SDK", required=True, confidence=0.9,
        )
        preflight = _binding_preflight(sdk_requirement)
        variant = CouncilVariant(
            id="v1", name="v1",
            toolchain=(ToolchainItem(
                requirement_ref=sdk_requirement.id, name="ESP-IDF",
                type=RequirementType.SDK, install_method="manual",
            ),),
        )
        result = CouncilResult(
            id="c1", project_id="proj", variants=(variant,),
            recommendation="v1", council_complete=True,
        )

        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is True

        decision = select_engineering_variant(
            result, preflight=preflight, chairman_recommendation="v1",
        )
        assert decision.variant.id == "v1"


class TestMultipleAdmissibleSolutionsCoexist:
    """Part 9.E/9.F/9.O: materially different candidates may ALL be
    admissible at once; the Chairman may recommend either; the
    deterministic layer never collapses them to a single forced winner."""

    def _two_admissible_environments(self, requirement):
        host = CouncilVariant(
            id="host", name="Host toolchain", environment="host",
            toolchain=(_pip_item(requirement.id),),
        )
        docker = CouncilVariant(
            id="docker", name="Docker toolchain", environment="docker",
            toolchain=(_pip_item(requirement.id),),
        )
        return host, docker

    def test_two_materially_different_candidates_may_both_be_admissible(self):
        requirement = _requirement()
        preflight = _binding_preflight(requirement)
        host, docker = self._two_admissible_environments(requirement)
        result = CouncilResult(
            id="c1", project_id="proj", variants=(host, docker),
            recommendation="host", council_complete=True,
        )

        validations = validate_candidates(result, preflight=preflight)
        assert all(v.admissible for v in validations)
        assert {v.variant.id for v in validations} == {"host", "docker"}
        # Materially different EngineeringSolutionClasses, never forced
        # to collapse into one (Part 9.O).
        host_class = next(v.solution_class for v in validations if v.variant.id == "host")
        docker_class = next(v.solution_class for v in validations if v.variant.id == "docker")
        assert host_class != docker_class

    def test_chairman_may_recommend_either_admissible_candidate(self):
        requirement = _requirement()
        preflight = _binding_preflight(requirement)
        host, docker = self._two_admissible_environments(requirement)
        result = CouncilResult(
            id="c1", project_id="proj", variants=(host, docker),
            recommendation="host", council_complete=True,
        )

        decision_host = select_engineering_variant(
            result, preflight=preflight, chairman_recommendation="host",
        )
        assert decision_host.variant.id == "host"

        decision_docker = select_engineering_variant(
            result, preflight=preflight, chairman_recommendation="docker",
        )
        assert decision_docker.variant.id == "docker"


class TestChairmanRecommendationIsNotOverridden:
    """Part 9.G/9.H: the corrected replacement for 009B's
    TestExistingCapabilityMutationPreference. 009B's own test asserted
    that a mutation-free candidate silently REPLACES an admissible,
    explicitly-recommended mutating candidate -- exactly the governance
    defect this task closes. The deterministic layer may still classify
    and expose mutation information (EngineeringSolutionClass,
    requires_environment_mutation) as Engineering decision evidence, but
    it must never use it to override an admissible recommendation."""

    def test_admissible_mutating_recommendation_is_not_replaced_by_a_mutation_free_alternative(self):
        requirement = _requirement()
        preflight = _binding_preflight(requirement)
        no_mutation = CouncilVariant(
            id="v1", name="v1",
            toolchain=(_pip_item(requirement.id, state="already_installed"),),
        )
        mutation = CouncilVariant(
            id="v2", name="v2",
            toolchain=(_pip_item(requirement.id, state="needs_install"),),
        )
        result = CouncilResult(
            id="c1", project_id="proj", variants=(no_mutation, mutation),
            recommendation="v2", council_complete=True,
        )

        validations = validate_candidates(result, preflight=preflight)
        assert all(v.admissible for v in validations)

        decision = select_engineering_variant(
            result, preflight=preflight, chairman_recommendation="v2",
        )
        assert decision.variant.id == "v2"
        assert decision.selection_authority == "chairman"
        # Mutation information remains available as evidence, it just no
        # longer drives the selection.
        assert decision.solution_class.requires_environment_mutation is True

    def test_mutation_only_candidate_is_selected_when_it_is_the_sole_admissible_option(self):
        requirement = _requirement()
        preflight = _binding_preflight(requirement)
        mutation_only = CouncilVariant(
            id="v1", name="v1",
            toolchain=(_pip_item(requirement.id, state="needs_install"),),
        )
        result = CouncilResult(
            id="c1", project_id="proj", variants=(mutation_only,),
            recommendation="v1", council_complete=True,
        )

        decision = select_engineering_variant(
            result, preflight=preflight, chairman_recommendation="v1",
        )
        assert decision.variant.id == "v1"


class TestProposalOrderAndProseIndependence:
    """Part 9 (validation invariants): order/prose must not change
    VALIDATION outcomes or classification -- unlike 009B, this is no
    longer about forcing the same final SELECTED variant regardless of
    which candidate was recommended."""

    def test_proposal_order_does_not_change_which_candidate_a_given_recommendation_selects(self):
        requirement = _requirement()
        preflight = _binding_preflight(requirement)
        no_mutation = CouncilVariant(
            id="v1", name="v1",
            toolchain=(_pip_item(requirement.id, state="already_installed"),),
        )
        mutation = CouncilVariant(
            id="v2", name="v2",
            toolchain=(_pip_item(requirement.id, state="needs_install"),),
        )

        forward = CouncilResult(
            id="c1", project_id="proj", variants=(no_mutation, mutation),
            recommendation="v1", council_complete=True,
        )
        reversed_ = CouncilResult(
            id="c2", project_id="proj", variants=(mutation, no_mutation),
            recommendation="v1", council_complete=True,
        )

        decision_forward = select_engineering_variant(
            forward, preflight=preflight, chairman_recommendation="v1",
        )
        decision_reversed = select_engineering_variant(
            reversed_, preflight=preflight, chairman_recommendation="v1",
        )
        assert decision_forward.variant.id == decision_reversed.variant.id == "v1"

    def test_prose_name_and_id_differences_do_not_change_the_solution_class(self):
        requirement = _requirement()
        preflight = _binding_preflight(requirement)
        variant_a = CouncilVariant(
            id="proposal-alpha", name="The Simple Approach",
            description="A clean, well-understood setup.",
            advantages=("fast", "reliable"),
            toolchain=(_pip_item(requirement.id),),
        )
        variant_b = CouncilVariant(
            id="totally-different-id-42", name="An Entirely Different Name",
            description="Completely different reasoning and wording.",
            advantages=("team familiarity", "low maintenance", "documented"),
            toolchain=(_pip_item(requirement.id),),
        )
        result_a = CouncilResult(
            id="c1", project_id="proj", variants=(variant_a,),
            recommendation="proposal-alpha", council_complete=True,
        )
        result_b = CouncilResult(
            id="c2", project_id="proj", variants=(variant_b,),
            recommendation="totally-different-id-42", council_complete=True,
        )

        decision_a = select_engineering_variant(
            result_a, preflight=preflight, chairman_recommendation="proposal-alpha",
        )
        decision_b = select_engineering_variant(
            result_b, preflight=preflight, chairman_recommendation="totally-different-id-42",
        )
        assert decision_a.solution_class == decision_b.solution_class


class TestSolutionClassDistinguishability:
    """Part 9.O -- the deterministic contracts above must not collapse
    genuinely different classes into false equivalence."""

    def test_materially_different_solution_classes_remain_distinguishable(self):
        requirement = _requirement()
        preflight = _binding_preflight(requirement)
        host_variant = CouncilVariant(
            id="v1", name="v1", environment="host",
            toolchain=(_pip_item(requirement.id),),
        )
        docker_variant = CouncilVariant(
            id="v2", name="v2", environment="docker",
            toolchain=(_pip_item(requirement.id),),
        )

        host_decision = select_engineering_variant(
            CouncilResult(id="c1", project_id="proj", variants=(host_variant,),
                          recommendation="v1", council_complete=True),
            preflight=preflight, chairman_recommendation="v1",
        )
        docker_decision = select_engineering_variant(
            CouncilResult(id="c2", project_id="proj", variants=(docker_variant,),
                          recommendation="v2", council_complete=True),
            preflight=preflight, chairman_recommendation="v2",
        )
        assert host_decision.solution_class != docker_decision.solution_class


class TestNoForcedTieBreakWithoutARecommendation:
    """Part 9 / Part 11 ('No False Determinism'): the corrected
    replacement for 009B's TestStableTieBreak. 009B's own test proved a
    deterministic hash silently picked a winner among two admissible,
    equally-valid candidates even though NEITHER was recommended -- this
    is precisely the governance defect ('only one valid solution may
    exist') this task rejects. The deterministic layer must now require
    an explicit recommendation or human selection instead of guessing."""

    def test_two_admissible_candidates_without_a_recommendation_requires_an_explicit_choice(self):
        requirement = _requirement()
        preflight = _binding_preflight(requirement)
        variant_a = CouncilVariant(id="v1", name="v1", toolchain=(_pip_item(requirement.id),))
        variant_b = CouncilVariant(id="v2", name="v2", toolchain=(_pip_item(requirement.id),))
        result = CouncilResult(
            id="c1", project_id="proj", variants=(variant_a, variant_b),
            recommendation=None, council_complete=True,
        )

        with pytest.raises(EngineeringSelectionRequiredError):
            select_engineering_variant(result, preflight=preflight)

        # Proposal order must not matter for this outcome either.
        result_reversed = CouncilResult(
            id="c2", project_id="proj", variants=(variant_b, variant_a),
            recommendation=None, council_complete=True,
        )
        with pytest.raises(EngineeringSelectionRequiredError):
            select_engineering_variant(result_reversed, preflight=preflight)

    def test_sole_admissible_candidate_is_selected_without_forcing_a_choice(self):
        """No forced choice occurs when there IS only one option -- this
        is not a governance violation, since nothing was chosen FOR
        anyone among several valid alternatives."""
        requirement = _requirement()
        preflight = _binding_preflight(requirement)
        variant = CouncilVariant(id="v1", name="v1", toolchain=(_pip_item(requirement.id),))
        result = CouncilResult(
            id="c1", project_id="proj", variants=(variant,),
            recommendation=None, council_complete=True,
        )

        decision = select_engineering_variant(result, preflight=preflight)
        assert decision.variant.id == "v1"
        assert decision.selection_authority == "sole_admissible"


class TestHumanVariantSelection:
    """Part 9.K/9.L/9.N -- the human may override the Chairman's
    recommendation with another admissible alternative, but never with
    an inadmissible one; Setup Approval remains a wholly separate,
    later authority from this Engineering variant selection."""

    def test_human_may_choose_another_admissible_variant_instead_of_the_chairman_recommendation(self):
        requirement = _requirement()
        preflight = _binding_preflight(requirement)
        recommended = CouncilVariant(id="v1", name="v1", toolchain=(_pip_item(requirement.id),))
        alternative = CouncilVariant(id="v2", name="v2", toolchain=(_pip_item(requirement.id),))
        result = CouncilResult(
            id="c1", project_id="proj", variants=(recommended, alternative),
            recommendation="v1", council_complete=True,
        )

        decision = select_engineering_variant(
            result, preflight=preflight,
            chairman_recommendation="v1", human_selected_variant_id="v2",
        )
        assert decision.variant.id == "v2"
        assert decision.selection_authority == "human"

    def test_human_may_not_choose_an_inadmissible_variant_for_s3_execution(self):
        requirement = _requirement()
        preflight = _binding_preflight(requirement)
        recommended = CouncilVariant(id="v1", name="v1", toolchain=(_pip_item(requirement.id),))
        inadmissible = CouncilVariant(
            id="v2", name="v2",
            toolchain=(_pip_item(requirement.id, environment_constraint="windows"),),
        )
        result = CouncilResult(
            id="c1", project_id="proj", variants=(recommended, inadmissible),
            recommendation="v1", council_complete=True,
        )

        with pytest.raises(ChairmanRecommendationInadmissibleError) as excinfo:
            select_engineering_variant(
                result, preflight=preflight, platform="linux",
                chairman_recommendation="v1", human_selected_variant_id="v2",
            )
        assert excinfo.value.recommendation_id == "v2"

    def test_selecting_an_unproposed_variant_id_is_rejected_distinctly(self):
        requirement = _requirement()
        preflight = _binding_preflight(requirement)
        variant = CouncilVariant(id="v1", name="v1", toolchain=(_pip_item(requirement.id),))
        result = CouncilResult(
            id="c1", project_id="proj", variants=(variant,),
            recommendation="v1", council_complete=True,
        )

        with pytest.raises(EngineeringVariantNotFoundError):
            select_engineering_variant(
                result, preflight=preflight,
                chairman_recommendation="v1", human_selected_variant_id="does-not-exist",
            )

    def test_setup_approval_is_a_separate_authority_from_variant_selection(self):
        """Part 9.N: once S3 has materialized the SELECTED variant into a
        SetupPlan, SetupApproval operates purely on that SetupPlan -- it
        has no dependency on, or awareness of, which Engineering variant
        or which selection authority (chairman/human) produced it."""
        from app.setup_approval import SetupApproval
        from app.toolchain_materializer import ToolchainMaterializer

        requirement = _requirement()
        preflight = _binding_preflight(requirement)
        recommended = CouncilVariant(id="v1", name="v1", toolchain=(_pip_item(requirement.id),))
        alternative = CouncilVariant(id="v2", name="v2", toolchain=(_pip_item(requirement.id),))
        result = CouncilResult(
            id="c1", project_id="proj", variants=(recommended, alternative),
            recommendation="v1", council_complete=True,
        )

        plan = ToolchainMaterializer().materialize(result, "proj", preflight=preflight)
        assert plan.status == "pending_approval"

        approved = SetupApproval.approve(plan)
        assert approved.status == "approved"
        assert all(step.is_approved for step in approved.steps)


class TestSelectedVariantReachesS3Unchanged:
    """Part 9.M: the exact admissible variant that was selected is the
    one ToolchainMaterializer actually builds the SetupPlan from -- not
    a different, validator-preferred candidate."""

    def test_selected_admissible_variant_is_exactly_the_variant_materialized_by_s3(self):
        from app.toolchain_materializer import ToolchainMaterializer

        requirement_a = _requirement("req-a")
        preflight = PreflightResult(
            id="pre-1", project_id="proj", overall_ready=False,
            results=(
                PreflightRequirementResult(
                    requirement_id=requirement_a.id, present=False, satisfied=False,
                    active=True, blocks_current_operation=True,
                ),
            ),
            missing_requirements=(requirement_a,),
            activations=(RequirementActivation(requirement_a.id, True, True),),
        )
        # Two admissible candidates covering the SAME binding requirement
        # with genuinely different toolchains -- proves the materialized
        # plan reflects the recommended one, not some other admissible
        # candidate the validator might otherwise have preferred.
        recommended = CouncilVariant(
            id="v1", name="v1",
            toolchain=(ToolchainItem(
                requirement_ref=requirement_a.id, name="esphome-recommended",
                type=RequirementType.PYTHON_PACKAGE, technical_identity="esphome",
                install_method="pip", state="needs_install",
            ),),
        )
        other_admissible = CouncilVariant(
            id="v2", name="v2",
            toolchain=(ToolchainItem(
                requirement_ref=requirement_a.id, name="esphome-alternative",
                type=RequirementType.PYTHON_PACKAGE, technical_identity="esphome",
                install_method="pip", state="already_installed",
            ),),
        )
        result = CouncilResult(
            id="c1", project_id="proj", variants=(recommended, other_admissible),
            recommendation="v1", council_complete=True,
        )

        plan = ToolchainMaterializer().materialize(result, "proj", preflight=preflight)
        materialized_refs = {step.requirement_id for step in plan.steps}
        assert materialized_refs == {requirement_a.id}
        # The chosen candidate ("v1") needs installing; if the validator
        # had silently preferred "v2" (already_installed, mutation-free)
        # instead, no step would appear at all.
        assert any(step.action == "install" for step in plan.steps)


class TestDownstreamS3SafetyUnchanged:
    """Part 9.K (S2->S3 boundary) -- the pre-existing S3 safety net
    (ToolchainMaterializer demoting an unsupported step to manual_review)
    remains intact and unweakened by this governance correction."""

    def test_manual_review_remains_the_outcome_for_a_genuinely_uncontrolled_effect(self):
        from app.toolchain_materializer import ToolchainMaterializer

        sdk_requirement = Requirement(
            id="req-sdk", name="ESP-IDF", type=RequirementType.SDK,
            purpose="firmware SDK", required=True, confidence=0.9,
        )
        preflight = _binding_preflight(sdk_requirement)
        variant = CouncilVariant(
            id="v1", name="v1",
            toolchain=(ToolchainItem(
                requirement_ref=sdk_requirement.id, name="ESP-IDF",
                type=RequirementType.SDK, install_method="manual",
            ),),
        )
        result = CouncilResult(
            id="c1", project_id="proj", variants=(variant,),
            recommendation="v1", council_complete=True,
        )

        plan = ToolchainMaterializer().materialize(result, "proj", preflight=preflight)
        assert plan.steps[0].action == "manual_review"


class TestAdmissibleVariantsHelper:
    def test_admissible_variants_returns_only_the_admissible_ones(self):
        requirement = _requirement()
        preflight = _binding_preflight(requirement)
        good = CouncilVariant(id="v1", name="v1", toolchain=(_pip_item(requirement.id),))
        bad = CouncilVariant(id="v2", name="v2", toolchain=())
        result = CouncilResult(
            id="c1", project_id="proj", variants=(good, bad),
            recommendation="v1", council_complete=True,
        )

        validations = validate_candidates(result, preflight=preflight)
        assert [v.id for v in admissible_variants(validations)] == ["v1"]


class TestMultipleBindingRequirementsCoverage:
    """CLAUDE-E2E-NIO-010A, Part 9.B: a candidate covering MULTIPLE
    binding Requirements (not just one) remains admissible -- the exact
    positive counterpart to Real-System-E2E #5's fragmented-coverage
    failure."""

    def test_candidate_covering_two_binding_requirements_is_admissible(self):
        req_a = _requirement("req-esphome")
        req_b = _requirement("req-platformio")
        preflight = _multi_requirement_preflight(req_a, req_b)
        complete = CouncilVariant(
            id="v1", name="v1",
            toolchain=(_pip_item(req_a.id), _pip_item(req_b.id)),
        )
        result = CouncilResult(
            id="c1", project_id="proj", variants=(complete,),
            recommendation="v1", council_complete=True,
        )

        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is True

        decision = select_engineering_variant(
            result, preflight=preflight, chairman_recommendation="v1",
        )
        assert decision.variant.id == "v1"

    def test_fragmented_candidates_each_covering_only_one_requirement_are_all_inadmissible(self):
        """Mechanical reproduction of the Real-E2E #5 shape at the S2
        layer itself: two candidates, each legitimately covering ONE of
        two binding Requirements, cover the full set only when their
        toolchains are UNIONED -- but S2 correctly never does that
        unioning itself (that would be exactly the kind of forced
        synthesis CLAUDE-PRE-E2E-009C forbids); each remains inadmissible
        on its own."""
        req_a = _requirement("req-esphome")
        req_b = _requirement("req-platformio")
        preflight = _multi_requirement_preflight(req_a, req_b)
        esphome_only = CouncilVariant(id="v1", name="v1", toolchain=(_pip_item(req_a.id),))
        platformio_only = CouncilVariant(id="v2", name="v2", toolchain=(_pip_item(req_b.id),))
        result = CouncilResult(
            id="c1", project_id="proj", variants=(esphome_only, platformio_only),
            recommendation="v1", council_complete=True,
        )

        validations = validate_candidates(result, preflight=preflight)
        assert all(not v.admissible for v in validations)
        assert admissible_variants(validations) == ()

        with pytest.raises(NoEligibleEngineeringCandidateError):
            select_engineering_variant(
                result, preflight=preflight, chairman_recommendation="v1",
            )


class TestNonBindingRequirementsDoNotAffectAdmissibility:
    """Part 9.D: a Requirement that is missing but NOT blocking the
    current operation must never cause a false rejection -- only
    required+missing+blocking Requirements are binding."""

    def test_missing_non_blocking_requirement_does_not_reject_an_otherwise_complete_candidate(self):
        binding = _requirement("req-esphome")
        optional = _requirement("req-optional-linter", required=True)
        preflight = _multi_requirement_preflight(binding, non_binding=(optional,))
        variant = CouncilVariant(id="v1", name="v1", toolchain=(_pip_item(binding.id),))
        result = CouncilResult(
            id="c1", project_id="proj", variants=(variant,),
            recommendation="v1", council_complete=True,
        )

        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is True, validations[0].reasons

        decision = select_engineering_variant(
            result, preflight=preflight, chairman_recommendation="v1",
        )
        assert decision.variant.id == "v1"


class TestProvidedByWithinAVariantSatisfiesCoverage:
    """Part 9.E: ADC's EXISTING structured relation for 'this Requirement
    is satisfied transitively by installing another one' is ToolchainItem.
    provided_by (reused, not reinvented -- CLAUDE-E2E-NIO-010A, Part 4:
    ADC already has this contract, so no prose-based heuristic was
    introduced). An item marked provided_by another item IN THE SAME
    variant still satisfies coverage for its OWN requirement_ref -- e.g.
    a PlatformIO-like Requirement that a project's real package manager
    would install transitively as part of installing ESPHome."""

    def test_provided_by_item_still_counts_as_covering_its_own_requirement(self):
        req_esphome = _requirement("req-esphome")
        req_platformio = _requirement("req-platformio")
        preflight = _multi_requirement_preflight(req_esphome, req_platformio)
        variant = CouncilVariant(
            id="v1", name="v1",
            toolchain=(
                _pip_item(req_esphome.id),
                _pip_item(req_platformio.id, provided_by=req_esphome.id, state="already_installed"),
            ),
        )
        result = CouncilResult(
            id="c1", project_id="proj", variants=(variant,),
            recommendation="v1", council_complete=True,
        )

        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is True, validations[0].reasons


class TestManualReviewSemanticsAreNotStale:
    """Part 6: distinguish "ADC has no controlled executor but the plan
    is explicitly manual" (admissible) from "ADC claims the step is
    controlled/automatable but cannot execute it" (inadmissible) -- and
    confirm the exception wording no longer implies that only
    "genuinely automatable" candidates can ever be admissible, which
    would misdescribe this exact, correct, still-supported exception."""

    def test_legitimately_manual_candidate_remains_admissible_not_merely_by_accident(self):
        sdk_requirement = Requirement(
            id="req-sdk", name="ESP-IDF", type=RequirementType.SDK,
            purpose="firmware SDK", required=True, confidence=0.9,
        )
        preflight = _binding_preflight(sdk_requirement)
        variant = CouncilVariant(
            id="v1", name="v1",
            toolchain=(ToolchainItem(
                requirement_ref=sdk_requirement.id, name="ESP-IDF",
                type=RequirementType.SDK, install_method="manual",
            ),),
        )
        result = CouncilResult(
            id="c1", project_id="proj", variants=(variant,),
            recommendation="v1", council_complete=True,
        )
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is True
        assert validations[0].reasons == ()

    def test_no_eligible_candidate_message_no_longer_implies_only_automatable_is_admissible(self):
        variant = CouncilVariant(id="v1", name="v1", toolchain=())
        result = CouncilResult(
            id="c1", project_id="proj", variants=(variant,),
            recommendation="v1", council_complete=True,
        )
        preflight = _binding_preflight(_requirement())
        with pytest.raises(NoEligibleEngineeringCandidateError) as excinfo:
            select_engineering_variant(
                result, preflight=preflight, chairman_recommendation="v1",
            )
        message = str(excinfo.value)
        assert "genuinely automatable" not in message
        assert "controlled-or-explicitly-manual" in message


class TestPerCandidateFailureEvidence:
    """Part 7/9.J: when zero candidates are admissible, the diagnostic
    evidence must show WHY each one failed -- not only a generic
    sentence. This is exactly the observability gap Real-System-E2E #5
    exposed (a bare "No proposed engineering candidate satisfies..."
    with no way to mechanically determine the actual rejection cause)."""

    def test_no_eligible_candidate_error_carries_and_renders_full_per_candidate_evidence(self):
        req_a = _requirement("req-esphome")
        req_b = _requirement("req-platformio")
        preflight = _multi_requirement_preflight(req_a, req_b)
        esphome_only = CouncilVariant(
            id="merged-venv", name="ESPHome mit Python Virtual Environment",
            toolchain=(_pip_item(req_a.id),),
        )
        platformio_only = CouncilVariant(
            id="A3-var-3", name="Virtuelle Umgebung",
            toolchain=(_pip_item(req_b.id),),
        )
        result = CouncilResult(
            id="c1", project_id="proj", variants=(esphome_only, platformio_only),
            recommendation="merged-venv", council_complete=True,
        )

        with pytest.raises(NoEligibleEngineeringCandidateError) as excinfo:
            select_engineering_variant(
                result, preflight=preflight, chairman_recommendation="merged-venv",
            )

        error = excinfo.value
        # Programmatically inspectable (Part 7: candidate id, name if
        # safe, EngineeringSolutionClass, admissible=False, reasons).
        assert len(error.validations) == 2
        by_id = {v.variant.id: v for v in error.validations}
        assert by_id["merged-venv"].admissible is False
        assert "req-platformio" in by_id["merged-venv"].reasons[0]
        assert by_id["A3-var-3"].admissible is False
        assert "req-esphome" in by_id["A3-var-3"].reasons[0]
        # Directly visible in the exception message itself -- no secrets,
        # no LLM prose beyond the short capped candidate name, no
        # Chain-of-Thought.
        message = str(error)
        assert "merged-venv" in message
        assert "req-platformio" in message
        assert "A3-var-3" in message
        assert "req-esphome" in message
        for forbidden in ("chain_of_thought", "api_key", "password", "begin private key"):
            assert forbidden not in message.lower()

    def test_chairman_recommendation_inadmissible_error_also_carries_full_evidence(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        recommended_inadmissible = CouncilVariant(
            id="v1", name="v1",
            toolchain=(_pip_item(req.id, environment_constraint="windows"),),
        )
        other_admissible = CouncilVariant(id="v2", name="v2", toolchain=(_pip_item(req.id),))
        result = CouncilResult(
            id="c1", project_id="proj", variants=(recommended_inadmissible, other_admissible),
            recommendation="v1", council_complete=True,
        )

        from app.engineering_decision import ChairmanRecommendationInadmissibleError
        with pytest.raises(ChairmanRecommendationInadmissibleError) as excinfo:
            select_engineering_variant(
                result, preflight=preflight, platform="linux", chairman_recommendation="v1",
            )
        message = str(excinfo.value)
        assert "v1" in message
        assert "windows" in message.lower() or "platform" in message.lower()


class TestVerificationCoverageAdmissibility:
    """CLAUDE-ARCH-S2-012B, Gate E: S2.3's Verification-Coverage
    admissibility dimension. Reuses the EXISTING, already-structured
    Requirement.verification_method contract (app/requirement_model.py,
    validated non-empty-when-present by RequirementValidator, already
    surfaced to the Chairman prompt) -- never invents a new one, and is
    implemented ONLY in S2.3 (app/engineering_decision.py), never
    duplicated in S2.2/S2.4/S2.5/S3."""

    def test_sufficient_verification_coverage_is_admissible(self):
        """CLAUDE-ARCH-S2-013E: sufficiency now requires structured
        verification_coverage (mechanism + grounded evidence), not just
        non-empty free text -- see tests/test_verification_feasibility.py
        for the full RED/GREEN matrix this task added."""
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        pytest_item = ToolchainItem(
            requirement_ref=req.id, name="pytest", type="executable",
            technical_identity="pytest", provides_verification=("pytest",),
        )
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(_pip_item(req.id), pytest_item),
            verification="pytest tests/test_firmware.py -k esphome",
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism="pytest", evidence="pytest",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(
            result, preflight=preflight, trusted_verification_groups=_trusted_groups(test_systems=["pytest"]),
        )
        assert validations[0].admissible is True

    def test_missing_required_verification_coverage_is_inadmissible(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(id="v1", name="v1", toolchain=(_pip_item(req.id),), verification="")
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is False
        assert "missing required verification coverage" in validations[0].reasons[0]
        assert "req-esphome" in validations[0].reasons[0]
        assert categorize_admissibility_reasons(validations[0].reasons) == "verification_coverage"

        with pytest.raises(NoEligibleEngineeringCandidateError):
            select_engineering_variant(result, preflight=preflight, chairman_recommendation="v1")

    def test_irrelevant_non_binding_verification_information_does_not_cause_false_rejection(self):
        """A Requirement with NO verification_method at all must never
        be treated as demanding verification coverage -- an empty
        CouncilVariant.verification field is then simply irrelevant."""
        req = _requirement()  # no verification_method set
        preflight = _binding_preflight(req)
        variant = CouncilVariant(id="v1", name="v1", toolchain=(_pip_item(req.id),), verification="")
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is True
        assert validations[0].reasons == ()

    def test_verification_coverage_interacts_correctly_with_requirement_dimension(self):
        """A candidate missing BOTH binding-requirement coverage AND
        verification coverage is reported with both reasons -- neither
        dimension hides the other."""
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        incomplete = CouncilVariant(id="v1", name="v1", toolchain=(), verification="")
        result = CouncilResult(id="c1", project_id="proj", variants=(incomplete,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is False
        joined = "; ".join(validations[0].reasons)
        assert "missing binding requirement coverage" in joined
        assert "missing required verification coverage" in joined

    def test_verification_coverage_interacts_correctly_with_platform_dimension(self):
        """A candidate that satisfies verification coverage but violates
        the platform Constraint remains inadmissible for the platform
        reason -- verification coverage does not mask a platform
        violation, and is itself independently satisfied."""
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        pytest_item = ToolchainItem(
            requirement_ref=req.id, name="pytest", type="executable",
            technical_identity="pytest", provides_verification=("pytest",),
        )
        variant = CouncilVariant(
            id="v1", name="v1",
            toolchain=(_pip_item(req.id, environment_constraint="windows"), pytest_item),
            verification="pytest tests/",
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism="pytest", evidence="pytest",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(
            result, preflight=preflight, platform="linux",
            trusted_verification_groups=_trusted_groups(test_systems=["pytest"]),
        )
        assert validations[0].admissible is False
        assert "violates platform constraint" in validations[0].reasons[0]
        assert not any("verification" in reason for reason in validations[0].reasons)

    def test_verification_coverage_interacts_correctly_with_materializability_dimension(self):
        """A candidate with sufficient verification coverage but an
        incompatible controlled install_method remains inadmissible for
        materializability -- verification coverage does not mask it."""
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        pytest_item = ToolchainItem(
            requirement_ref=req.id, name="pytest", type="executable",
            technical_identity="pytest", provides_verification=("pytest",),
        )
        variant = CouncilVariant(
            id="v1", name="v1",
            toolchain=(_pip_item(
                req.id,
                install_method="python3 -m venv .venv && source .venv/bin/activate && pip install esphome",
            ), pytest_item),
            verification="pytest tests/",
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism="pytest", evidence="pytest",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(
            result, preflight=preflight, trusted_verification_groups=_trusted_groups(test_systems=["pytest"]),
        )
        assert validations[0].admissible is False
        assert "cannot be materialized" in validations[0].reasons[0]
        assert not any("verification" in reason for reason in validations[0].reasons)

    def test_multiple_admissible_candidates_one_with_and_one_needing_verification(self):
        """Two candidates for the SAME verification-demanding
        requirement: one articulates verification coverage (admissible),
        one does not (inadmissible) -- both dimensions resolve
        independently and correctly per candidate."""
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        pytest_item = ToolchainItem(
            requirement_ref=req.id, name="pytest", type="executable",
            technical_identity="pytest", provides_verification=("pytest",),
        )
        covered = CouncilVariant(
            id="v1", name="v1", toolchain=(_pip_item(req.id), pytest_item),
            verification="pytest tests/",
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism="pytest", evidence="pytest",
            ),),
        )
        uncovered = CouncilVariant(id="v2", name="v2", toolchain=(_pip_item(req.id),), verification="")
        result = CouncilResult(id="c1", project_id="proj", variants=(covered, uncovered),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(
            result, preflight=preflight, trusted_verification_groups=_trusted_groups(test_systems=["pytest"]),
        )
        by_id = {v.variant.id: v for v in validations}
        assert by_id["v1"].admissible is True
        assert by_id["v2"].admissible is False


# =========================================================================
# Real-System-E2E #8 (CLAUDE-ARCH-S2-012D): the Chairman synthesized a
# python_package toolchain item whose human-readable display `name`
# ("ESPHome CLI") is not itself a valid distribution identifier and whose
# `technical_identity` was left unset -- S2.3 correctly rejected it, but
# the bounded repair's own evidence (a bare `materializability_conflict=
# True` boolean) never named the offending requirement/item, so the one
# allowed Chairman repair attempt could not target the actual defect.
# Root cause: insufficient diagnostic information, not a validator or
# producer-contract defect (the technical_identity contract was already
# fully documented end-to-end in app.council_prompts). Fix: S2.3 now
# names the exact offending (requirement_ref, item name) pair in both its
# reason text and the EngineeringReworkRequest it hands to S2.2 for
# repair; the repair prompt surfaces this as an actionable, technology-
# neutral hint. S2.3's own admissible/inadmissible verdicts are BYTE-
# IDENTICAL in truth value to before this fix -- only the diagnostic
# detail changed.
# =========================================================================


def _esphome_binding_setup():
    req = Requirement(
        technical_identity="esphome",
        id="req-esphome", name="esphome", type=RequirementType.PYTHON_PACKAGE,
        purpose="firmware build", required=True, confidence=0.9,
    )
    return req, _binding_preflight(req)


def _esphome_item(
    name="esphome", technical_identity="esphome",
    install_method="pip install esphome", environment_constraint=None,
    provides_verification=(),
):
    return ToolchainItem(
        requirement_ref="req-esphome", name=name, type=RequirementType.PYTHON_PACKAGE,
        technical_identity=technical_identity, install_method=install_method,
        environment_constraint=environment_constraint,
        provides_verification=provides_verification,
    )


class TestRealE2E8MaterializabilityDiagnostics:
    """TC-S2.3-e2e8: deterministic regressions reproducing the exact
    Real-System-E2E #8 semantic shape (RED-before-fix evidence recorded
    in the CLAUDE-ARCH-S2-012D completion report)."""

    def test_case_a_host_venv_esphome_with_controlled_executable_install_path_is_admissible(self):
        """A: host + Python venv + ESPHome binding requirement + a
        genuinely controlled, automatable executable install path (a
        display name that differs from the display label, corrected via
        technical_identity) is admissible."""
        req, preflight = _esphome_binding_setup()
        variant = CouncilVariant(
            id="merged-host-venv", name="ESPHome CLI mit Python Virtual Environment",
            environment="host",
            toolchain=(_esphome_item(name="ESPHome CLI", technical_identity="esphome"),),
        )
        validations = validate_variants((variant,), preflight=preflight, platform="linux")
        assert validations[0].admissible is True

    def test_case_b_same_solution_via_materially_different_valid_llm_output_shape(self):
        """B: the SAME semantic solution (host + venv + esphome) expressed
        through a materially different, still-valid LLM output shape --
        here the display `name` IS ALREADY a valid distribution
        identifier, so technical_identity is legitimately left unset --
        must resolve to the identical admissible outcome as case A."""
        req, preflight = _esphome_binding_setup()
        variant = CouncilVariant(
            id="merged-host-venv-alt", name="ESPHome via venv",
            environment="host",
            toolchain=(_esphome_item(name="esphome", technical_identity=None),),
        )
        validations = validate_variants((variant,), preflight=preflight, platform="linux")
        assert validations[0].admissible is True

    def test_case_c_genuinely_missing_controlled_install_information_stays_inadmissible(self):
        """C: EXACT Real-System-E2E #8 reproduction -- display name is not
        a valid distribution identifier AND technical_identity is
        genuinely missing. Must remain inadmissible: the fix must never
        weaken S2.3 to let this through."""
        req, preflight = _esphome_binding_setup()
        variant = CouncilVariant(
            id="merged-host-venv", name="ESPHome CLI mit Python Virtual Environment",
            environment="host",
            toolchain=(_esphome_item(name="ESPHome CLI", technical_identity=None),),
        )
        validations = validate_variants((variant,), preflight=preflight, platform="linux")
        assert validations[0].admissible is False
        assert "cannot be materialized" in validations[0].reasons[0]
        assert "req-esphome" in validations[0].reasons[0]
        assert "ESPHome CLI" in validations[0].reasons[0]

    def test_case_c_blank_technical_identity_is_treated_as_genuinely_missing(self):
        """C (permutation): a blank/whitespace-only technical_identity
        must be treated exactly like an absent one -- never accepted as
        if it were a valid identifier."""
        req, preflight = _esphome_binding_setup()
        variant = CouncilVariant(
            id="merged-host-venv", name="ESPHome CLI mit Python Virtual Environment",
            environment="host",
            toolchain=(_esphome_item(name="ESPHome CLI", technical_identity="   "),),
        )
        validations = validate_variants((variant,), preflight=preflight, platform="linux")
        assert validations[0].admissible is False

    def test_case_d_unsupported_install_representation_stays_inadmissible(self):
        """D: technical_identity IS valid, but install_method is an
        unsupported, compound shell command the controlled pip executor
        cannot safely run -- must remain inadmissible even though the
        package identity itself is perfectly well-formed."""
        req, preflight = _esphome_binding_setup()
        variant = CouncilVariant(
            id="merged-host-venv", name="ESPHome CLI mit Python Virtual Environment",
            environment="host",
            toolchain=(_esphome_item(
                name="ESPHome CLI", technical_identity="esphome",
                install_method="python3 -m venv .venv && "
                                ".venv/bin/pip install esphome",
            ),),
        )
        validations = validate_variants((variant,), preflight=preflight, platform="linux")
        assert validations[0].admissible is False
        assert "cannot be materialized" in validations[0].reasons[0]

    def test_case_e_repair_evidence_names_the_exact_offending_item(self):
        """E (S2.3-level half of the full repair loop -- the S2.2-level
        half, proving the targeted repair actually succeeds end-to-end,
        is covered in tests/test_engineering_council.py): the
        EngineeringReworkRequest built from the case-C rejection must name
        the exact offending requirement id and item name -- never a bare
        boolean -- so a second Chairman synthesis has an actionable
        target."""
        req, preflight = _esphome_binding_setup()
        broken = CouncilVariant(
            id="merged-host-venv", name="ESPHome CLI mit Python Virtual Environment",
            environment="host",
            toolchain=(_esphome_item(name="ESPHome CLI", technical_identity=None),),
        )
        validation = validate_variants((broken,), preflight=preflight, platform="linux")[0]
        rework = EngineeringReworkRequest.from_validation(validation, platform="linux")
        assert rework.materializability_conflict is True
        assert any(
            "req-esphome" in detail and "ESPHome CLI" in detail
            for detail in rework.materializability_conflict_detail
        )

    def test_case_e2_identity_defect_sets_identity_conflict_not_install_method_conflict(self):
        """C (CLAUDE-ADC-S23-INSTALL-METHOD-PRODUCER-REPAIR-FIX-001): the
        exact case-C/case-E identity defect (missing technical_identity)
        must set the new `identity_conflict`/`identity_conflict_detail`
        fields -- and must NOT set `install_method_conflict` -- so the
        Chairman repair prompt builder emits the technical_identity hint
        and never the install_method hint for a defect that has nothing
        to do with install_method."""
        req, preflight = _esphome_binding_setup()
        broken = CouncilVariant(
            id="merged-host-venv", name="ESPHome CLI mit Python Virtual Environment",
            environment="host",
            toolchain=(_esphome_item(name="ESPHome CLI", technical_identity=None),),
        )
        validation = validate_variants((broken,), preflight=preflight, platform="linux")[0]
        rework = EngineeringReworkRequest.from_validation(validation, platform="linux")

        assert rework.identity_conflict is True
        assert any(
            "req-esphome" in detail and "ESPHome CLI" in detail
            for detail in rework.identity_conflict_detail
        )
        assert rework.install_method_conflict is False
        assert rework.install_method_conflict_detail == ()

    def test_case_e3_install_method_defect_sets_install_method_conflict_not_identity_conflict(self):
        """B (CLAUDE-ADC-S23-INSTALL-METHOD-PRODUCER-REPAIR-FIX-001): the
        exact case-D shape (technical_identity valid, install_method an
        incompatible compound shell command) must set the new
        `install_method_conflict`/`install_method_conflict_detail`
        fields -- and must NOT set `identity_conflict` -- proving the
        rework artifact now distinguishes the two categories using the
        already-central classification (_binding_item_rejection_
        category()) rather than a bare, undifferentiated
        materializability_conflict boolean."""
        req, preflight = _esphome_binding_setup()
        broken = CouncilVariant(
            id="merged-2", name="ESPHome Docker Container Setup",
            environment="container",
            toolchain=(_esphome_item(
                name="ESPHome Python Package (in container)",
                technical_identity="esphome",
                install_method=(
                    "python3 -m venv .venv && source .venv/bin/activate "
                    "&& pip install esphome"
                ),
            ),),
        )
        validation = validate_variants((broken,), preflight=preflight, platform="linux")[0]
        rework = EngineeringReworkRequest.from_validation(validation, platform="linux")

        assert rework.install_method_conflict is True
        assert any(
            "req-esphome" in detail
            and "ESPHome Python Package (in container)" in detail
            for detail in rework.install_method_conflict_detail
        )
        assert rework.identity_conflict is False
        assert rework.identity_conflict_detail == ()
        # Unchanged, backward-compatible generic flag: still fires for
        # EITHER category, exactly as before this fix.
        assert rework.materializability_conflict is True

    def test_case_g_container_alternative_incompatible_with_binding_platform_constraint(self):
        """G: EXACT Real-System-E2E #8 'merged-container' shape -- a
        technically well-formed candidate (valid technical_identity, valid
        install_method) that nonetheless violates the binding platform
        constraint must remain inadmissible for that reason, independent
        of and unrelated to the materializability dimension."""
        req, preflight = _esphome_binding_setup()
        variant = CouncilVariant(
            id="merged-container", name="ESPHome CLI in Docker/Podman Container",
            environment="container",
            toolchain=(_esphome_item(
                name="ESPHome CLI", technical_identity="esphome",
                environment_constraint="container",
            ),),
        )
        validations = validate_variants((variant,), preflight=preflight, platform="linux")
        assert validations[0].admissible is False
        assert "violates platform constraint" in validations[0].reasons[0]

    def test_case_h_mixed_candidate_set_only_admissible_candidate_is_selectable(self):
        """H: EXACT Real-System-E2E #8 two-candidate set -- one
        inadmissible (materializability), one inadmissible (platform) in
        the original failure, here paired with a THIRD, genuinely
        admissible host+venv candidate (the corrected shape from case A)
        -- only the admissible candidate may be selectable at all."""
        req, preflight = _esphome_binding_setup()
        broken_host = CouncilVariant(
            id="merged-host-venv", name="ESPHome CLI mit Python Virtual Environment",
            environment="host",
            toolchain=(_esphome_item(name="ESPHome CLI", technical_identity=None),),
        )
        broken_container = CouncilVariant(
            id="merged-container", name="ESPHome CLI in Docker/Podman Container",
            environment="container",
            toolchain=(_esphome_item(
                name="ESPHome CLI", technical_identity="esphome",
                environment_constraint="container",
            ),),
        )
        fixed_host = CouncilVariant(
            id="merged-host-venv-fixed", name="ESPHome CLI mit Python Virtual Environment (korrigiert)",
            environment="host",
            toolchain=(_esphome_item(name="ESPHome CLI", technical_identity="esphome"),),
        )
        result = CouncilResult(
            id="c1", project_id="proj",
            variants=(broken_host, broken_container, fixed_host),
            recommendation="merged-host-venv-fixed", council_complete=True,
        )
        validations = validate_candidates(result, preflight=preflight, platform="linux")
        admissible = admissible_variants(validations)
        assert [v.id for v in admissible] == ["merged-host-venv-fixed"]
        decision = select_engineering_variant(
            result, preflight=preflight, platform="linux",
            chairman_recommendation="merged-host-venv-fixed",
        )
        assert decision.variant.id == "merged-host-venv-fixed"

    def test_case_i_esphome_greenfield_recovers_admissibility_via_esphome_validate(self):
        """CLAUDE-ADC-E2E-VERIFICATION-EVIDENCE-FIX-001: reproduces the
        verified Real-System-E2E ESPHome greenfield failure shape at the
        full validate_candidates/select_engineering_variant level --
        'merged-container' and 'merged-host-pip' (real E2E variant ids),
        an ESPHome project Project Intelligence genuinely detected
        (firmware_indicators=["esphome"]), and a binding req-esphome
        requirement. Before CLAUDE-ARCH-S2-014E, BOTH candidates were
        inadmissible: the container candidate for its genuine platform
        constraint (unrelated, expected -- see case G/H above) AND the
        host candidate for verification feasibility, because the
        documented "esphome_validate" mechanism token was never in the
        trusted identity group -- collapsing to NoEligibleEngineering-
        CandidateError exactly like the real run. With the fix, the host
        candidate's genuinely independently-corroborated esphome_validate
        coverage makes it admissible and selectable; the container
        candidate legitimately remains inadmissible on platform grounds
        alone, unrelated to and unweakened by this fix."""
        req, preflight = _esphome_binding_setup()
        trusted = _trusted_groups(firmware_indicators=["esphome"])

        merged_container = CouncilVariant(
            id="merged-container", name="ESPHome CLI in Docker/Podman Container",
            environment="container",
            toolchain=(_esphome_item(environment_constraint="container"),),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="build_command",
                mechanism="esphome_validate", evidence="esphome",
            ),),
        )
        merged_host_pip = CouncilVariant(
            id="merged-host-pip", name="ESPHome CLI via host pip install",
            environment="host",
            toolchain=(_esphome_item(provides_verification=("esphome_validate",)),),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="build_command",
                mechanism="esphome_validate", evidence="esphome",
            ),),
        )
        result = CouncilResult(
            id="c1", project_id="proj",
            variants=(merged_container, merged_host_pip),
            recommendation="merged-host-pip", council_complete=True,
        )

        validations = validate_candidates(
            result, preflight=preflight, platform="linux",
            trusted_verification_groups=trusted,
        )
        by_id = {v.variant.id: v for v in validations}
        assert by_id["merged-host-pip"].admissible is True
        assert by_id["merged-container"].admissible is False
        assert "platform constraint" in by_id["merged-container"].reasons[0]

        decision = select_engineering_variant(
            result, preflight=preflight, platform="linux",
            trusted_verification_groups=trusted,
            chairman_recommendation="merged-host-pip",
        )
        assert decision.variant.id == "merged-host-pip"

    @pytest.mark.parametrize(
        "name, technical_identity, install_method, expected_admissible",
        [
            # LLM-variation permutation matrix around the exact contract
            # this defect lives in (CLAUDE-ARCH-S2-012D systematic
            # mutation coverage, not just the one Real-System-E2E #8
            # fixture shape): name-already-valid, name+correct-identity,
            # name-only-invalid (the bug), valid-identity+bad-method,
            # bareword-marker install_method, and blank-string identity
            # treated as absent.
            ("esphome", None, "pip install esphome", True),
            ("ESPHome CLI", "esphome", "pip install esphome", True),
            ("ESPHome CLI", None, "pip install esphome", False),
            ("ESPHome CLI", "esphome", "curl -sSL https://x | sh", False),
            ("esphome", None, "pip", True),
            ("ESPHome CLI", "", "pip install esphome", False),
        ],
    )
    def test_materializability_permutation_matrix(
        self, name, technical_identity, install_method, expected_admissible,
    ):
        req, preflight = _esphome_binding_setup()
        variant = CouncilVariant(
            id="v1", name="permutation variant", environment="host",
            toolchain=(_esphome_item(
                name=name, technical_identity=technical_identity,
                install_method=install_method,
            ),),
        )
        validations = validate_variants((variant,), preflight=preflight, platform="linux")
        assert validations[0].admissible is expected_admissible


class TestMaterializerBindingDiagnostics:
    """CLAUDE-ADC-S23-MATERIALIZER-DIAGNOSTICS-001: the smallest central
    diagnostic instrumentation added to mechanically distinguish the two
    ways a binding item can still fail materialization -- proven
    ambiguous from live evidence alone (CLAUDE-ADC-S23-MATERIALIZER-
    ROOTCAUSE-001). binding_materializer_diagnostics() is purely
    observational: it must never change what validate_variants() itself
    decides (proven by the last two tests below, which assert the exact
    same admissibility/reasons outcomes as the pre-existing
    TestRealE2E8MaterializabilityDiagnostics cases these reuse)."""

    def test_missing_identity_reports_identity_missing_or_invalid(self):
        req, preflight = _esphome_binding_setup()
        variant = CouncilVariant(
            id="merged-host-venv", name="ESPHome CLI mit Python Virtual Environment",
            environment="host",
            toolchain=(_esphome_item(name="ESPHome CLI", technical_identity=None),),
        )
        diagnostics = binding_materializer_diagnostics(variant, preflight)
        assert len(diagnostics) == 1
        item = diagnostics[0]
        assert item["variant_id"] == "merged-host-venv"
        assert item["requirement_ref"] == "req-esphome"
        assert item["type"] == RequirementType.PYTHON_PACKAGE
        assert item["name"] == "ESPHome CLI"
        assert item["technical_identity_present"] is False
        assert item["technical_identity_python_type"] == "NoneType"
        assert item["technical_identity_check_applicable"] is True
        assert item["technical_identity_valid"] is False
        assert item["name_valid_as_identifier"] is False
        # Never leaks a raw, invalid identifier -- absent, not "ESPHome CLI".
        assert item["safe_identifier"] is None
        assert item["materializer_action"] == "manual_review"
        assert item["materializer_rejection_category"] == "identity_missing_or_invalid"
        # install_method compatibility was never even reached (identity
        # resolution failed first, exactly like _materialize_item()).
        assert item["install_method_compatible"] is None

    def test_blank_technical_identity_is_also_reported_as_missing_or_invalid(self):
        """Permutation of the missing-identity case: whitespace-only
        technical_identity must classify identically to an absent one,
        never as if it were present-but-something-else."""
        req, preflight = _esphome_binding_setup()
        variant = CouncilVariant(
            id="merged-host-venv", name="ESPHome CLI mit Python Virtual Environment",
            environment="host",
            toolchain=(_esphome_item(name="ESPHome CLI", technical_identity="   "),),
        )
        item = binding_materializer_diagnostics(variant, preflight)[0]
        assert item["technical_identity_present"] is True
        assert item["technical_identity_python_type"] == "str"
        assert item["technical_identity_valid"] is False
        assert item["safe_identifier"] is None
        assert item["materializer_rejection_category"] == "identity_missing_or_invalid"

    def test_valid_identity_with_incompatible_install_method_reports_that_category(self):
        req, preflight = _esphome_binding_setup()
        variant = CouncilVariant(
            id="merged-host-venv", name="ESPHome CLI mit Python Virtual Environment",
            environment="host",
            toolchain=(_esphome_item(
                name="ESPHome CLI", technical_identity="esphome",
                install_method="python3 -m venv .venv && "
                                ".venv/bin/pip install esphome",
            ),),
        )
        item = binding_materializer_diagnostics(variant, preflight)[0]
        assert item["technical_identity_present"] is True
        assert item["technical_identity_valid"] is True
        # The identity itself resolved cleanly and IS exposed -- only an
        # invalid one is ever suppressed.
        assert item["safe_identifier"] == "esphome"
        assert item["install_method_compatible"] is False
        # The compound shell command's own text is never present anywhere
        # in the diagnostic -- only a bounded shape label.
        assert item["install_method_classification"] == "unrecognized_shape"
        # The one field that could ever leak install_method's own raw text
        # (install_method_classification) is a fixed label, never it.
        assert "&&" not in item["install_method_classification"]
        assert item["install_method_classification"] in {
            "empty_or_none", "no_validator_registered", "bareword_marker",
            "recognized_command_pattern_package_match",
            "recognized_command_pattern_package_mismatch", "unrecognized_shape",
        }
        assert item["materializer_action"] == "manual_review"
        assert item["materializer_rejection_category"] == "install_method_incompatible"

    def test_valid_identity_with_supported_install_method_is_not_rejected(self):
        req, preflight = _esphome_binding_setup()
        variant = CouncilVariant(
            id="merged-host-venv", name="ESPHome CLI mit Python Virtual Environment",
            environment="host",
            toolchain=(_esphome_item(name="ESPHome CLI", technical_identity="esphome"),),
        )
        item = binding_materializer_diagnostics(variant, preflight)[0]
        assert item["technical_identity_valid"] is True
        assert item["safe_identifier"] == "esphome"
        assert item["install_method_compatible"] is True
        assert item["install_method_classification"] == "recognized_command_pattern_package_match"
        assert item["materializer_action"] == "install"
        assert item["materializer_rejection_category"] is None

    def test_bareword_install_method_marker_is_recognized(self):
        req, preflight = _esphome_binding_setup()
        variant = CouncilVariant(
            id="v1", name="ESPHome via bareword pip",
            toolchain=(_esphome_item(
                name="esphome", technical_identity=None, install_method="pip",
            ),),
        )
        item = binding_materializer_diagnostics(variant, preflight)[0]
        assert item["install_method_classification"] == "bareword_marker"
        assert item["materializer_action"] == "install"

    def test_name_already_valid_identifier_needs_no_technical_identity(self):
        """The SAME semantic solution as the missing-identity case, but
        expressed via an already-valid display name -- the diagnostic must
        show name_valid_as_identifier True and no rejection, distinguishing
        this from the genuinely-broken shape above."""
        req, preflight = _esphome_binding_setup()
        variant = CouncilVariant(
            id="v1", name="ESPHome via valid name",
            toolchain=(_esphome_item(name="esphome", technical_identity=None),),
        )
        item = binding_materializer_diagnostics(variant, preflight)[0]
        assert item["technical_identity_present"] is False
        assert item["name_valid_as_identifier"] is True
        assert item["safe_identifier"] == "esphome"
        assert item["materializer_action"] == "install"
        assert item["materializer_rejection_category"] is None

    def test_non_binding_item_is_excluded(self):
        """Only binding (required + missing + blocking) requirements are
        diagnosed -- exactly the same population
        _unmaterializable_binding_requirements() itself iterates."""
        req, preflight = _esphome_binding_setup()
        variant = CouncilVariant(
            id="v1", name="test",
            toolchain=(ToolchainItem(
                requirement_ref="req-not-binding", name="Something Else",
                type=RequirementType.PYTHON_PACKAGE, technical_identity=None,
            ),),
        )
        assert binding_materializer_diagnostics(variant, preflight) == ()

    def test_never_changes_admissibility_outcome_missing_identity(self):
        """The diagnostic is purely observational: validate_variants()'s
        own admissibility outcome for this exact fixture must be
        unaffected by binding_materializer_diagnostics() ever having been
        called (and, independently, calling it must not itself raise or
        mutate anything validate_variants() also reads)."""
        req, preflight = _esphome_binding_setup()
        variant = CouncilVariant(
            id="merged-host-venv", name="ESPHome CLI mit Python Virtual Environment",
            environment="host",
            toolchain=(_esphome_item(name="ESPHome CLI", technical_identity=None),),
        )
        binding_materializer_diagnostics(variant, preflight)
        validations = validate_variants((variant,), preflight=preflight, platform="linux")
        assert validations[0].admissible is False
        assert "cannot be materialized" in validations[0].reasons[0]

    def test_never_changes_admissibility_outcome_supported_install(self):
        req, preflight = _esphome_binding_setup()
        variant = CouncilVariant(
            id="merged-host-venv", name="ESPHome CLI mit Python Virtual Environment",
            environment="host",
            toolchain=(_esphome_item(name="ESPHome CLI", technical_identity="esphome"),),
        )
        binding_materializer_diagnostics(variant, preflight)
        validations = validate_variants((variant,), preflight=preflight, platform="linux")
        assert validations[0].admissible is True

    def test_bytes_install_method_with_missing_identity_never_crashes(self):
        """CLAUDE-ADC-S23-MATERIALIZER-DIAGNOSTICS-FIX-001 (CDX-ADC-S23-
        MATERIALIZER-DIAGNOSTICS-REVIEW-001): a binding item with missing/
        invalid identity AND a non-string install_method (b"pip") must
        never raise -- the diagnostic install-method shape classifier is
        total for any Python value. The real, unmodified S2.3/materializer
        outcome (identity resolution fails first; install_method is never
        even inspected for compatibility) must be reported exactly as it
        already is, unaffected by install_method's own type."""
        req, preflight = _esphome_binding_setup()
        variant = CouncilVariant(
            id="merged-host-venv", name="ESPHome CLI mit Python Virtual Environment",
            environment="host",
            toolchain=(_esphome_item(
                name="ESPHome CLI", technical_identity=None, install_method=b"pip",
            ),),
        )
        item = binding_materializer_diagnostics(variant, preflight)[0]
        assert item["install_method_python_type"] == "bytes"
        # A dedicated, bounded label -- never the raw bytes value itself,
        # and never one of the string-shape labels (which would imply
        # install_method was actually inspected as a string).
        assert item["install_method_classification"] == "non_string_type"
        assert item["materializer_action"] == "manual_review"
        assert item["materializer_rejection_category"] == "identity_missing_or_invalid"
        # install_method compatibility was never reached at all -- identity
        # resolution failed first, exactly like the real materializer.
        assert item["install_method_compatible"] is None

    def test_bytes_install_method_does_not_change_the_real_admissibility_outcome(self):
        """The real validate_variants() outcome for this exact fixture --
        proven, independently of the diagnostic helper, to already be
        correct and non-crashing before this fix -- must remain identical
        after binding_materializer_diagnostics() is also called on it."""
        req, preflight = _esphome_binding_setup()
        variant = CouncilVariant(
            id="merged-host-venv", name="ESPHome CLI mit Python Virtual Environment",
            environment="host",
            toolchain=(_esphome_item(
                name="ESPHome CLI", technical_identity=None, install_method=b"pip",
            ),),
        )
        binding_materializer_diagnostics(variant, preflight)
        validations = validate_variants((variant,), preflight=preflight, platform="linux")
        assert validations[0].admissible is False
        assert "cannot be materialized" in validations[0].reasons[0]
        assert "req-esphome" in validations[0].reasons[0]

    def test_ordinary_string_install_method_classification_is_unchanged(self):
        """Guards against a regression in the fix itself: a normal,
        already-supported string install_method must still classify
        exactly as it did before this fix."""
        req, preflight = _esphome_binding_setup()
        variant = CouncilVariant(
            id="v1", name="ESPHome via pip",
            toolchain=(_esphome_item(name="ESPHome CLI", technical_identity="esphome"),),
        )
        item = binding_materializer_diagnostics(variant, preflight)[0]
        assert item["install_method_classification"] == "recognized_command_pattern_package_match"
        assert item["materializer_action"] == "install"

    def test_none_install_method_is_classified_by_identity_not_truthiness(self):
        """CLAUDE-ADC-S23-MATERIALIZER-DIAGNOSTICS-FIX-002 (CDX-ADC-S23-
        MATERIALIZER-DIAGNOSTICS-FIX-REVIEW-001): None must be recognized
        via `is None`, never via `bool(None)` -- proven by construction
        here (the classifier's own first check is an identity check), and
        exercised through the exact same public boundary as every other
        case in this class."""
        from app.engineering_decision import _classify_install_method_for_diagnostics
        from app.requirement_model import SetupEffect

        assert _classify_install_method_for_diagnostics(
            SetupEffect.PYTHON_PACKAGE_INSTALL, None, "esphome",
        ) == "empty_or_none"

    def test_empty_string_install_method_is_still_classified_as_empty_or_none(self):
        """The empty string is a genuine string (unlike None or a non-string
        object) -- it must still resolve to "empty_or_none" AFTER the
        non-string guard, not "non_string_type"."""
        from app.engineering_decision import _classify_install_method_for_diagnostics
        from app.requirement_model import SetupEffect

        assert _classify_install_method_for_diagnostics(
            SetupEffect.PYTHON_PACKAGE_INSTALL, "", "esphome",
        ) == "empty_or_none"

    def test_object_whose_bool_raises_is_non_string_type_without_invoking_truthiness(self):
        """CLAUDE-ADC-S23-MATERIALIZER-DIAGNOSTICS-FIX-002 (CDX-ADC-S23-
        MATERIALIZER-DIAGNOSTICS-FIX-REVIEW-001): the remaining
        observational-isolation defect FIX-001 left behind -- its own
        `if not install_method:` first check called bool() on every
        non-string value too (including bytes, which happens not to raise
        for `not b"pip"`, masking the issue), so a value whose __bool__
        itself raises would still crash the diagnostic. This object's
        __bool__/__eq__/__hash__ all raise if ever invoked; only a strict
        `isinstance(..., str)` check performed BEFORE any truthiness,
        membership, or regex use can classify it safely."""
        from app.engineering_decision import _classify_install_method_for_diagnostics
        from app.requirement_model import SetupEffect

        class ExplodingTruthiness:
            def __bool__(self):
                raise AssertionError("truthiness must never be evaluated")

            def __eq__(self, other):
                raise AssertionError("equality/membership must never be evaluated")

            def __hash__(self):
                raise AssertionError("hashing must never be evaluated")

        result = _classify_install_method_for_diagnostics(
            SetupEffect.PYTHON_PACKAGE_INSTALL, ExplodingTruthiness(), "esphome",
        )
        assert result == "non_string_type"

    def test_bytes_regression_still_classified_as_non_string_type(self):
        """The FIX-001 regression (bytes install_method) must remain fixed
        after FIX-002's reordering -- kept as its own explicit case per
        this task's own instruction."""
        from app.engineering_decision import _classify_install_method_for_diagnostics
        from app.requirement_model import SetupEffect

        assert _classify_install_method_for_diagnostics(
            SetupEffect.PYTHON_PACKAGE_INSTALL, b"pip", "esphome",
        ) == "non_string_type"


# ---------------------------------------------------------------------------
# CLAUDE-ADC-S23-STRICT-IDENTITY-ENVIRONMENT-BINDING-FIX-004 (#3):
# _requirement_by_id() must fail closed on a duplicated/ambiguous id --
# zero matches is unresolved (unchanged), exactly one is usable
# (unchanged), and MORE than one sharing the same id must never be
# silently resolved to whichever one happens to appear first or last.
# ---------------------------------------------------------------------------

class TestRequirementByIdAmbiguity:
    def _preflight_with(self, missing=(), already_installed=()):
        return PreflightResult(
            id="pre-ambiguous", project_id="proj", overall_ready=False,
            results=(), missing_requirements=tuple(missing),
            already_installed=tuple(already_installed),
        )

    def test_zero_matching_requirements_is_unresolved(self):
        from app.engineering_decision import _requirement_by_id
        preflight = self._preflight_with(missing=(_requirement("req-other"),))
        assert _requirement_by_id(preflight, "req-nowhere") is None

    def test_exactly_one_matching_requirement_is_usable(self):
        from app.engineering_decision import _requirement_by_id
        requirement = _requirement("req-a")
        preflight = self._preflight_with(missing=(requirement,))
        assert _requirement_by_id(preflight, "req-a") is requirement

    def test_duplicate_id_within_missing_requirements_is_ambiguous_first_ordering(self):
        """Two conflicting Requirement objects sharing the same id, in
        one ordering -- must resolve to neither, never silently to the
        FIRST one."""
        from app.engineering_decision import _requirement_by_id
        first = Requirement(
            technical_identity="acme-widgets",
            id="req-dup", name="acme-widgets", type=RequirementType.PYTHON_PACKAGE,
            purpose="first claim", required=True, confidence=0.9,
        )
        second = Requirement(
            technical_identity="totally-different-package",
            id="req-dup", name="totally-different-package", type=RequirementType.PYTHON_PACKAGE,
            purpose="second claim", required=True, confidence=0.9,
        )
        preflight = self._preflight_with(missing=(first, second))
        result = _requirement_by_id(preflight, "req-dup")
        assert result is None
        assert result is not first
        assert result is not second

    def test_duplicate_id_within_missing_requirements_is_ambiguous_reversed_ordering(self):
        """The exact same conflicting pair, in the OPPOSITE ordering --
        still resolves to neither, never silently to the LAST one. Proves
        the rule is order-independent, not merely 'never picks first'."""
        from app.engineering_decision import _requirement_by_id
        first = Requirement(
            technical_identity="acme-widgets",
            id="req-dup", name="acme-widgets", type=RequirementType.PYTHON_PACKAGE,
            purpose="first claim", required=True, confidence=0.9,
        )
        second = Requirement(
            technical_identity="totally-different-package",
            id="req-dup", name="totally-different-package", type=RequirementType.PYTHON_PACKAGE,
            purpose="second claim", required=True, confidence=0.9,
        )
        preflight = self._preflight_with(missing=(second, first))
        result = _requirement_by_id(preflight, "req-dup")
        assert result is None
        assert result is not first
        assert result is not second

    def test_duplicate_id_split_across_missing_and_already_installed_is_ambiguous(self):
        """The SAME id appearing once in `missing_requirements` and once
        in `already_installed` is exactly as ambiguous as two duplicates
        living in the same collection -- both are searched, together."""
        from app.engineering_decision import _requirement_by_id
        missing_one = Requirement(
            technical_identity="acme-widgets",
            id="req-dup", name="acme-widgets", type=RequirementType.PYTHON_PACKAGE,
            purpose="missing claim", required=True, confidence=0.9,
        )
        installed_one = Requirement(
            technical_identity="acme-widgets",
            id="req-dup", name="acme-widgets", type=RequirementType.PYTHON_PACKAGE,
            purpose="already-installed claim", required=True, confidence=0.9,
        )
        preflight = self._preflight_with(
            missing=(missing_one,), already_installed=(installed_one,),
        )
        assert _requirement_by_id(preflight, "req-dup") is None

    def test_none_preflight_is_unresolved(self):
        from app.engineering_decision import _requirement_by_id
        assert _requirement_by_id(None, "req-a") is None


# ---------------------------------------------------------------------------
# CLAUDE-ADC-ZIELBILD-DIFF-FIX-001 (A5): a requirement Preflight found
# already satisfied is only evidence for the exact environment/target
# that check ran against -- never proof that a candidate targeting a
# DIFFERENT environment (e.g. "venv", when Preflight checked the host
# interpreter) is also satisfied.
# ---------------------------------------------------------------------------

class TestEnvironmentScopedBindingRequirements:
    def _preflight_host_satisfied(self, requirement, host_target="/usr/bin/python3"):
        return PreflightResult(
            id="pre-a5", project_id="proj", overall_ready=True,
            results=(
                PreflightRequirementResult(
                    requirement_id=requirement.id, present=True, satisfied=True,
                    active=True, blocks_current_operation=True,
                    target_executable=host_target,
                ),
            ),
            missing_requirements=(),
            already_installed=(requirement,),
            activations=(RequirementActivation(requirement.id, True, True),),
        )

    def test_venv_candidate_cannot_drop_required_package_only_satisfied_on_host(self, tmp_path):
        """Concrete acceptance case: a required Python distribution
        exists in the host interpreter (Preflight reports it satisfied);
        a candidate selects environment="venv" and its own toolchain
        omits the item entirely, relying on that host-side satisfaction.
        The isolated venv this candidate would materialize into has no
        such package -- S2.3 must reject the omission, never silently
        trust host-satisfaction evidence for a different target."""
        requirement = _requirement("req-esphome")
        preflight = self._preflight_host_satisfied(requirement)
        # No .venv exists under tmp_path -- exactly the "this venv does
        # not even have the package (or the venv itself) yet" case the
        # omission would otherwise silently paper over.
        venv_variant = CouncilVariant(
            id="venv-v", name="venv-v", environment="venv", toolchain=(),
        )

        validations = validate_variants(
            (venv_variant,), preflight, project_root=str(tmp_path),
        )

        assert validations[0].admissible is False
        assert requirement.id in validations[0].missing_binding_requirement_ids
        assert "missing binding requirement coverage" in " ".join(validations[0].reasons)

    def test_host_candidate_does_not_unnecessarily_reinstall_host_satisfied_requirement(self):
        """The mirror case: a "host" candidate that likewise omits the
        item from its own toolchain must NOT be forced to carry a
        genuinely host-satisfied requirement -- Preflight's own
        satisfaction evidence IS valid for a host candidate (no
        project_root supplied -- host resolution needs none), exactly
        the prior, unchanged behavior this fix must not disturb."""
        requirement = _requirement("req-esphome")
        preflight = self._preflight_host_satisfied(requirement)
        host_variant = CouncilVariant(
            id="host-v", name="host-v", environment="host", toolchain=(),
        )

        validations = validate_variants((host_variant,), preflight)

        assert validations[0].admissible is True
        assert validations[0].missing_binding_requirement_ids == ()


class TestStructuredReworkEvidenceSurvivesHostileIds:
    """CLAUDE-ADC-ZIELBILD-DIFF-FIX-001 (D1): EngineeringReworkRequest
    .from_validation() must build every field from validate_variants()'s
    own structured CandidateValidation fields, never by reverse-parsing
    `reasons`' human-readable text -- proven here with ids/names
    deliberately shaped to defeat the OLD split/bracket/regex-based
    extraction (embedded ", ", brackets, quotes) while the structured
    contract remains exact. Admissibility itself is unchanged."""

    def test_hostile_requirement_id_survives_missing_binding_extraction(self):
        hostile_id = "req, ['weird'], id"
        requirement = Requirement(
            technical_identity="esphome",
            id=hostile_id, name="esphome", type=RequirementType.PYTHON_PACKAGE,
            purpose="firmware build", required=True, confidence=0.9,
        )
        preflight = _binding_preflight(requirement)
        # Omits the item entirely -> "missing binding requirement
        # coverage" is the ONLY failure category, isolating this case.
        variant = CouncilVariant(
            id="v1", name="v1", environment="host", toolchain=(),
        )
        validation = validate_variants((variant,), preflight=preflight)[0]
        assert validation.admissible is False
        assert validation.missing_binding_requirement_ids == (hostile_id,)

        rework = EngineeringReworkRequest.from_validation(validation)
        assert rework.missing_requirement_ids == (hostile_id,)
        assert rework.reason_codes == ("completeness_validation",)

    def test_hostile_item_name_survives_materializability_detail_extraction(self):
        hostile_name = "ESPHome CLI (item name='broken'); [nested]"
        requirement = Requirement(
            technical_identity="esphome",
            id="req-esphome", name="esphome", type=RequirementType.PYTHON_PACKAGE,
            purpose="firmware build", required=True, confidence=0.9,
        )
        preflight = _binding_preflight(requirement)
        broken = CouncilVariant(
            id="v1", name="v1", environment="host",
            toolchain=(ToolchainItem(
                requirement_ref="req-esphome", name=hostile_name,
                type=RequirementType.PYTHON_PACKAGE, technical_identity=None,
                install_method="pip install esphome",
            ),),
        )
        validation = validate_variants((broken,), preflight=preflight)[0]
        assert validation.admissible is False

        rework = EngineeringReworkRequest.from_validation(validation)
        assert rework.materializability_conflict is True
        assert any(
            "req-esphome" in detail and hostile_name in detail
            for detail in rework.materializability_conflict_detail
        )
        assert rework.identity_conflict is True
        assert any(
            "req-esphome" in detail and hostile_name in detail
            for detail in rework.identity_conflict_detail
        )


# ---------------------------------------------------------------------------
# CLAUDE-ADC-S23-RSE-PREFLIGHT-TEST-HARDENING-001, Part C: a productive
# Council-candidate -> S2.3 test.
#
# Real-System-E2E task ADC-REAL-SYSTEM-E2E-RETRY-001 failed because every
# proposed candidate lacked binding coverage for a platform requirement
# (req-c2efb7b8, "ESP32 Platform") and two of the three also lacked
# ESPHome/configuration-file verification evidence. The scenario below is
# analogous (a generic HARDWARE_COMPONENT "platform" requirement plus a
# PYTHON_PACKAGE toolchain requirement needing pip_show verification) but
# is not itself ESPHome/ESP32-special-cased anywhere in the assertions or
# in app.engineering_decision -- it exercises the exact same generic S2.3
# rules every other candidate in this module goes through.
#
# The positive case calls validate_candidates() (never a hand-rolled
# admissibility check) and shows every one of the documented dimensions
# passing AT ONCE on one realistic multi-requirement candidate. Each
# negative case then isolates exactly ONE of those dimensions and proves
# validate_candidates() rejects for that reason alone, with the other
# structured fields staying clean -- i.e. the four rejection paths are
# independent of one another, not one over-broad check.
# ---------------------------------------------------------------------------


def _platform_requirement(req_id="req-platform", name="ESP32 Platform"):
    return Requirement(
        id=req_id, name=name, type=RequirementType.HARDWARE_COMPONENT,
        purpose="target hardware platform for the firmware build",
        required=True, confidence=0.9,
    )


def _toolchain_package_requirement(req_id="req-toolchain", name="esphome"):
    return Requirement(
        technical_identity=name,
        id=req_id, name=name, type=RequirementType.PYTHON_PACKAGE,
        purpose="firmware build toolchain", required=True, confidence=0.9,
        verification_method=f"pip show {name}",
    )


def _platform_item(req_id, name="ESP32 Platform", environment_constraint=None):
    return ToolchainItem(
        requirement_ref=req_id, name=name, type=RequirementType.HARDWARE_COMPONENT,
        state="already_installed", environment_constraint=environment_constraint,
    )


def _pip_show_package_item(req_id, name="esphome", technical_identity="esphome",
                            install_method="pip", state="needs_install"):
    from app.verification import PACKAGE_PRESENCE_MECHANISM
    return ToolchainItem(
        requirement_ref=req_id, name=name, type=RequirementType.PYTHON_PACKAGE,
        technical_identity=technical_identity, install_method=install_method,
        state=state, provides_verification=(PACKAGE_PRESENCE_MECHANISM,),
    )


def _pip_show_coverage(req_id, evidence="esphome"):
    from app.verification import PACKAGE_PRESENCE_MECHANISM
    return VerificationCoverage(
        requirement_refs=(req_id,), kind="smoke_test",
        mechanism=PACKAGE_PRESENCE_MECHANISM, evidence=evidence,
    )


class TestProductiveCouncilCandidatePipeline:
    """A realistic CouncilResult, fed through the actual S2.3 validation
    path (validate_candidates -> CandidateValidation -> admissible_variants),
    never a re-implementation of admissibility."""

    def test_fully_covered_candidate_is_admissible_on_every_dimension(self):
        platform_req = _platform_requirement()
        toolchain_req = _toolchain_package_requirement()
        preflight = _multi_requirement_preflight(platform_req, toolchain_req)

        candidate = CouncilVariant(
            id="esp32-host-1", name="Host ESPHome build", environment="host",
            toolchain=(
                _platform_item(platform_req.id),
                _pip_show_package_item(toolchain_req.id),
            ),
            verification_coverage=(_pip_show_coverage(toolchain_req.id),),
        )
        result = CouncilResult(
            id="c1", project_id="proj", variants=(candidate,),
            recommendation="esp32-host-1", council_complete=True,
        )

        validations = validate_candidates(result, preflight=preflight, platform="linux")
        assert len(validations) == 1
        [validation] = validations

        # Every binding requirement is covered, requirement_refs preserved.
        assert validation.missing_binding_requirement_ids == ()
        # Verification feasibility accepted.
        assert validation.verification_feasibility_gap_ids == ()
        # Materializability passes.
        assert validation.unmaterializable_items == ()
        # Platform constraints pass.
        assert validation.platform_conflict is False
        # Candidate becomes admissible.
        assert validation.admissible is True, validation.reasons
        assert admissible_variants(validations) == (candidate,)

    def test_missing_binding_requirement_coverage_is_rejected_independently(self):
        platform_req = _platform_requirement()
        toolchain_req = _toolchain_package_requirement()
        preflight = _multi_requirement_preflight(platform_req, toolchain_req)

        # The platform requirement's toolchain item is simply absent --
        # exactly the RSE #1 failure shape (no binding coverage for the
        # platform requirement at all).
        candidate = CouncilVariant(
            id="esp32-host-2", name="Host ESPHome build (no platform item)",
            environment="host",
            toolchain=(_pip_show_package_item(toolchain_req.id),),
            verification_coverage=(_pip_show_coverage(toolchain_req.id),),
        )
        result = CouncilResult(
            id="c1", project_id="proj", variants=(candidate,),
            recommendation="esp32-host-2", council_complete=True,
        )

        [validation] = validate_candidates(result, preflight=preflight, platform="linux")
        assert validation.missing_binding_requirement_ids == (platform_req.id,)
        assert validation.unmaterializable_items == ()
        assert validation.platform_conflict is False
        assert validation.admissible is False

    def test_missing_verification_evidence_is_rejected_independently(self):
        platform_req = _platform_requirement()
        toolchain_req = _toolchain_package_requirement()
        preflight = _multi_requirement_preflight(platform_req, toolchain_req)

        # Binding coverage for BOTH requirements is present, but no
        # verification_coverage entry exists for the toolchain
        # requirement's own verification_method at all -- exactly the
        # "ESPHome verification missing" gap from the RSE failure.
        candidate = CouncilVariant(
            id="esp32-host-3", name="Host ESPHome build (no verification)",
            environment="host",
            toolchain=(
                _platform_item(platform_req.id),
                _pip_show_package_item(toolchain_req.id),
            ),
            verification_coverage=(),
        )
        result = CouncilResult(
            id="c1", project_id="proj", variants=(candidate,),
            recommendation="esp32-host-3", council_complete=True,
        )

        [validation] = validate_candidates(result, preflight=preflight, platform="linux")
        assert validation.missing_binding_requirement_ids == ()
        assert validation.verification_feasibility_gap_ids == (toolchain_req.id,)
        assert validation.platform_conflict is False
        assert validation.admissible is False

    def test_unmaterializable_setup_item_is_rejected_independently(self):
        platform_req = _platform_requirement()
        # No verification_method here: isolates the materializability
        # dimension from verification feasibility.
        toolchain_req = Requirement(
            id="req-toolchain", name="esphome", type=RequirementType.PYTHON_PACKAGE,
            purpose="firmware build toolchain", required=True, confidence=0.9,
            technical_identity="esphome",
        )
        preflight = _multi_requirement_preflight(platform_req, toolchain_req)

        # CLAUDE-ARCH-S2-012D / Real-System-E2E #8 shape: a python_package
        # item whose display name is not itself a valid distribution
        # identifier and whose technical_identity was left unset. Binding
        # COVERAGE still holds (the Requirement's own technical_identity
        # is valid, and _toolchain_item_matches_requirement_semantics()
        # tolerates an item with no technical_identity of its own) -- this
        # isolates the materializability defect from a coverage defect.
        broken_item = ToolchainItem(
            requirement_ref=toolchain_req.id, name="ESPHome CLI",
            type=RequirementType.PYTHON_PACKAGE, technical_identity=None,
            install_method="pip install esphome", state="needs_install",
        )
        candidate = CouncilVariant(
            id="esp32-host-4", name="Host ESPHome build (broken identity)",
            environment="host",
            toolchain=(_platform_item(platform_req.id), broken_item),
        )
        result = CouncilResult(
            id="c1", project_id="proj", variants=(candidate,),
            recommendation="esp32-host-4", council_complete=True,
        )

        [validation] = validate_candidates(result, preflight=preflight, platform="linux")
        assert validation.missing_binding_requirement_ids == ()
        assert validation.verification_feasibility_gap_ids == ()
        assert validation.platform_conflict is False
        assert validation.unmaterializable_items != ()
        assert validation.unmaterializable_items[0][0] == toolchain_req.id
        assert validation.admissible is False

    def test_platform_conflict_is_rejected_independently(self):
        platform_req = _platform_requirement()
        # No verification_method here: isolates the platform-constraint
        # dimension from verification feasibility.
        toolchain_req = Requirement(
            id="req-toolchain", name="esphome", type=RequirementType.PYTHON_PACKAGE,
            purpose="firmware build toolchain", required=True, confidence=0.9,
            technical_identity="esphome",
        )
        preflight = _multi_requirement_preflight(platform_req, toolchain_req)

        candidate = CouncilVariant(
            id="esp32-host-5", name="Host ESPHome build (platform conflict)",
            environment="host",
            toolchain=(
                _platform_item(platform_req.id),
                _pip_show_package_item(
                    toolchain_req.id,
                ),
            ),
        )
        # Override the package item's environment_constraint to conflict
        # with the input platform ("linux").
        from dataclasses import replace
        conflicting_toolchain = tuple(
            replace(item, environment_constraint="windows") if item.type == RequirementType.PYTHON_PACKAGE
            else item
            for item in candidate.toolchain
        )
        candidate = replace(candidate, toolchain=conflicting_toolchain)
        result = CouncilResult(
            id="c1", project_id="proj", variants=(candidate,),
            recommendation="esp32-host-5", council_complete=True,
        )

        [validation] = validate_candidates(result, preflight=preflight, platform="linux")
        assert validation.missing_binding_requirement_ids == ()
        assert validation.unmaterializable_items == ()
        assert validation.platform_conflict is True
        assert validation.admissible is False


# ---------------------------------------------------------------------------
# CLAUDE-ADC-S23-RSE-PREFLIGHT-TEST-HARDENING-001, Part G: structured S2.3
# failure diagnostics. NoEligibleEngineeringCandidateError.validations
# already carries full CandidateValidation objects (see
# TestPerCandidateFailureEvidence above) -- these tests additionally
# assert directly on the STRUCTURED per-candidate fields the task
# requires (candidate_id via validation.variant.id,
# missing_binding_requirement_ids, verification_feasibility_gap_ids,
# unmaterializable_items, platform_conflict, admissible), never by
# parsing validation.reasons human-readable text.
# ---------------------------------------------------------------------------


class TestStructuredFailureDiagnosticsOnZeroAdmissibleCandidates:
    def test_each_structured_field_is_directly_inspectable_per_candidate(self):
        platform_req = _platform_requirement()
        toolchain_req = _toolchain_package_requirement()
        preflight = _multi_requirement_preflight(platform_req, toolchain_req)

        # Three independently-broken candidates, one per RSE-observed
        # failure shape, so structured evidence must distinguish them.
        missing_platform_coverage = CouncilVariant(
            id="merged-host-venv", name="merged-host-venv", environment="host",
            toolchain=(_pip_show_package_item(toolchain_req.id),),
            verification_coverage=(_pip_show_coverage(toolchain_req.id),),
        )
        missing_verification = CouncilVariant(
            id="merged-container", name="merged-container", environment="host",
            toolchain=(
                _platform_item(platform_req.id),
                _pip_show_package_item(toolchain_req.id),
            ),
            verification_coverage=(),
        )
        platform_conflicted = CouncilVariant(
            id="A3-var-1", name="A3-var-1", environment="host",
            toolchain=(
                _platform_item(platform_req.id, environment_constraint="windows"),
                _pip_show_package_item(toolchain_req.id),
            ),
            verification_coverage=(_pip_show_coverage(toolchain_req.id),),
        )
        result = CouncilResult(
            id="c1", project_id="proj",
            variants=(missing_platform_coverage, missing_verification, platform_conflicted),
            recommendation="merged-host-venv", council_complete=True, council_degraded=True,
        )

        with pytest.raises(NoEligibleEngineeringCandidateError) as excinfo:
            select_engineering_variant(
                result, preflight=preflight, platform="linux",
                chairman_recommendation="merged-host-venv",
            )

        by_id = {v.variant.id: v for v in excinfo.value.validations}
        assert set(by_id) == {"merged-host-venv", "merged-container", "A3-var-1"}

        assert by_id["merged-host-venv"].admissible is False
        assert by_id["merged-host-venv"].missing_binding_requirement_ids == (platform_req.id,)
        assert by_id["merged-host-venv"].verification_feasibility_gap_ids == ()
        assert by_id["merged-host-venv"].unmaterializable_items == ()
        assert by_id["merged-host-venv"].platform_conflict is False

        assert by_id["merged-container"].admissible is False
        assert by_id["merged-container"].missing_binding_requirement_ids == ()
        assert by_id["merged-container"].verification_feasibility_gap_ids == (toolchain_req.id,)
        assert by_id["merged-container"].unmaterializable_items == ()
        assert by_id["merged-container"].platform_conflict is False

        assert by_id["A3-var-1"].admissible is False
        assert by_id["A3-var-1"].missing_binding_requirement_ids == ()
        assert by_id["A3-var-1"].verification_feasibility_gap_ids == ()
        assert by_id["A3-var-1"].unmaterializable_items == ()
        assert by_id["A3-var-1"].platform_conflict is True
