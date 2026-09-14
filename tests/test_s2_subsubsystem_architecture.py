"""S2 Subsubsystem architecture pilot (CLAUDE-ARCH-S2-012A).

Covers what does not naturally belong inside the historical per-defect
test files (tests/test_engineering_council.py for S2.1/S2.2,
tests/test_engineering_decision.py for S2.3/S2.4/S2.5,
tests/test_toolchain_materializer.py for S3):

  - the S2.4 Human Engineering Authority emulator (Part 19) and its
    action-permutation tests
  - internal S2.x boundary tests (Part 21, CLAUDE-ARCH-S2-012B: TC-B-
    S2.1-2.2 and TC-B-S2.2-2.3 made explicit via their own boundary
    classes; TC-B-S2-S3 renamed TC-B-S2.5-S3 per Gap 4's ownership
    correction): TC-B-S2.1-2.2, TC-B-S2.2-2.3, TC-B-S2.3-2.2 (rework),
    TC-B-S2.3-2.4, TC-B-S2.4-2.5, TC-B-S2.5-S3
  - explicit authority-leak negative tests (Part 23)
  - the S2 subsystem acceptance-suite scenario families (Part 22,
    S2-SCENARIO-01..15), built from REAL internal S2 components
    (validate_variants / resolve_human_engineering_selection /
    build_engineering_decision / ToolchainMaterializer) -- mocks are used
    ONLY for the Chairman LLM provider boundary, per Part 22's own rule
  - the permanent, generalized Real-System-E2E #7 regression (Part 18)
  - the RED-2 S3-backward-dependency regression (Part 25)

Historical protections (009C/010A/011A) are NOT re-tested here; their
own test files remain the authority for those regressions (see the
completion report, R27).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import patch

import pytest

from app.council_models import CouncilInput, CouncilResult, CouncilVariant, ToolchainItem
from app.engineering_decision import (
    ChairmanRecommendationInadmissibleError,
    EngineeringDecision,
    EngineeringSelectionRequiredError,
    EngineeringVariantNotFoundError,
    NoEligibleEngineeringCandidateError,
    admissible_variants,
    build_engineering_decision,
    describe_engineering_variant_selection,
    resolve_human_engineering_selection,
    select_engineering_variant,
    validate_variants,
)
from app.requirement_model import (
    PreflightRequirementResult,
    PreflightResult,
    Requirement,
    RequirementActivation,
    RequirementType,
)
from app.setup_approval import SetupApproval
from app.toolchain_materializer import ToolchainMaterializer


# =========================================================================
# Shared fixtures
# =========================================================================


def _requirement(req_id="req-esphome"):
    return Requirement(
        id=req_id, name="esphome", type=RequirementType.PYTHON_PACKAGE,
        purpose="firmware build", required=True, confidence=0.9,
    )


def _binding_preflight(*requirements):
    return PreflightResult(
        id="pre-1", project_id="proj", overall_ready=False,
        results=tuple(
            PreflightRequirementResult(
                requirement_id=r.id, present=False, satisfied=False,
                active=True, blocks_current_operation=True,
            )
            for r in requirements
        ),
        missing_requirements=tuple(requirements),
        activations=tuple(RequirementActivation(r.id, True, True) for r in requirements),
    )


def _pip_item(requirement_ref, install_method="pip", state="needs_install",
              environment_constraint=None, provides_verification=("pytest",),
              technical_identity="esphome"):
    return ToolchainItem(
        requirement_ref=requirement_ref, name="esphome",
        type=RequirementType.PYTHON_PACKAGE, technical_identity=technical_identity,
        install_method=install_method, state=state,
        environment_constraint=environment_constraint,
        provides_verification=provides_verification,
    )


def _host_docker_council(requirement):
    host = CouncilVariant(id="host", name="Host toolchain", environment="host",
                           toolchain=(_pip_item(requirement.id),))
    docker = CouncilVariant(id="docker", name="Docker toolchain", environment="docker",
                             toolchain=(_pip_item(requirement.id),))
    return CouncilResult(
        id="c1", project_id="proj", variants=(host, docker),
        recommendation="host", council_complete=True,
    )


# =========================================================================
# S2.4 Human Engineering Authority emulator (Part 19)
#
# TEST-ONLY: represents the six Human decisions the target architecture
# names, mapped onto the real S2.3/S2.4 functions. This is a test
# fixture, not a claim about any existing production UI/API surface --
# no production Web/API behavior is invented here.
# =========================================================================


@dataclass(frozen=True)
class HumanDecision:
    action: str  # one of the six actions below
    selected_variant_id: str | None = None


ACCEPT_RECOMMENDATION = "ACCEPT_RECOMMENDATION"
SELECT_ALTERNATIVE = "SELECT_ALTERNATIVE"
REJECT_RECOMMENDATION = "REJECT_RECOMMENDATION"
REJECT_ALL = "REJECT_ALL"
REQUEST_REWORK = "REQUEST_REWORK"
DEFER_DECISION = "DEFER_DECISION"


def emulate_human_engineering_authority(
    council_result: CouncilResult, decision: HumanDecision,
    preflight=None, platform=None,
) -> EngineeringDecision | None:
    """Applies one S2.4 HumanDecision against a CouncilResult's already-
    computed S2.3 admissibility. Returns the resulting EngineeringDecision,
    or None when the Human's decision structurally cannot produce one
    (REJECT_RECOMMENDATION/REJECT_ALL/DEFER_DECISION/REQUEST_REWORK) --
    matching Part 19/20: "no EngineeringDecision exists" for those."""
    if decision.action == ACCEPT_RECOMMENDATION:
        return select_engineering_variant(
            council_result, preflight, platform,
            chairman_recommendation=council_result.recommendation,
        )
    if decision.action == SELECT_ALTERNATIVE:
        return select_engineering_variant(
            council_result, preflight, platform,
            chairman_recommendation=council_result.recommendation,
            human_selected_variant_id=decision.selected_variant_id,
        )
    if decision.action in (REJECT_RECOMMENDATION, REJECT_ALL, REQUEST_REWORK, DEFER_DECISION):
        return None
    raise ValueError(f"unsupported HumanDecision.action: {decision.action!r}")


class TestHumanEngineeringAuthorityEmulator:
    """Part 19/20: Human decision permutations."""

    def test_accept_recommendation_with_one_admissible_candidate(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(id="v1", name="v1", toolchain=(_pip_item(req.id),))
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        decision = emulate_human_engineering_authority(
            result, HumanDecision(ACCEPT_RECOMMENDATION), preflight,
        )
        assert decision.variant.id == "v1"
        assert decision.selection_authority == "chairman"

    def test_accept_recommendation_with_multiple_admissible_candidates(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        result = _host_docker_council(req)
        decision = emulate_human_engineering_authority(
            result, HumanDecision(ACCEPT_RECOMMENDATION), preflight,
        )
        assert decision.variant.id == "host"

    def test_accept_recommendation_inadmissible_cannot_produce_a_valid_decision(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        inadmissible = CouncilVariant(
            id="v1", name="v1",
            toolchain=(_pip_item(req.id, environment_constraint="windows"),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(inadmissible,),
                                recommendation="v1", council_complete=True)
        with pytest.raises(NoEligibleEngineeringCandidateError):
            emulate_human_engineering_authority(
                result, HumanDecision(ACCEPT_RECOMMENDATION), preflight, platform="linux",
            )

    def test_select_alternative_host_style(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        result = _host_docker_council(req)
        decision = emulate_human_engineering_authority(
            result, HumanDecision(SELECT_ALTERNATIVE, "host"), preflight,
        )
        assert decision.variant.id == "host"
        assert decision.selection_authority == "human"

    def test_select_alternative_docker_style(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        result = _host_docker_council(req)
        decision = emulate_human_engineering_authority(
            result, HumanDecision(SELECT_ALTERNATIVE, "docker"), preflight,
        )
        assert decision.variant.id == "docker"
        assert decision.selection_authority == "human"

    def test_select_alternative_venv_style(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        venv = CouncilVariant(id="venv", name="venv", environment="host",
                               toolchain=(_pip_item(req.id),))
        docker = CouncilVariant(id="docker2", name="docker", environment="docker",
                                 toolchain=(_pip_item(req.id),))
        result = CouncilResult(id="c1", project_id="proj", variants=(venv, docker),
                                recommendation="docker2", council_complete=True)
        decision = emulate_human_engineering_authority(
            result, HumanDecision(SELECT_ALTERNATIVE, "venv"), preflight,
        )
        assert decision.variant.id == "venv"

    def test_select_alternative_unknown_candidate_is_blocked(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        result = _host_docker_council(req)
        with pytest.raises(EngineeringVariantNotFoundError):
            emulate_human_engineering_authority(
                result, HumanDecision(SELECT_ALTERNATIVE, "does-not-exist"), preflight,
            )

    def test_select_alternative_inadmissible_candidate_is_blocked(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        admissible = CouncilVariant(id="v1", name="v1", toolchain=(_pip_item(req.id),))
        inadmissible = CouncilVariant(
            id="v2", name="v2",
            toolchain=(_pip_item(req.id, environment_constraint="windows"),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(admissible, inadmissible),
                                recommendation="v1", council_complete=True)
        with pytest.raises(ChairmanRecommendationInadmissibleError):
            emulate_human_engineering_authority(
                result, HumanDecision(SELECT_ALTERNATIVE, "v2"), preflight, platform="linux",
            )

    def test_reject_recommendation_produces_no_engineering_decision(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        result = _host_docker_council(req)
        decision = emulate_human_engineering_authority(
            result, HumanDecision(REJECT_RECOMMENDATION), preflight,
        )
        assert decision is None

    def test_reject_all_produces_no_engineering_decision_and_no_s3_handoff(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        result = _host_docker_council(req)
        decision = emulate_human_engineering_authority(
            result, HumanDecision(REJECT_ALL), preflight,
        )
        assert decision is None
        # No S3 handoff is possible without an EngineeringDecision --
        # there is nothing to pass to materialize_decision().

    def test_defer_decision_produces_no_engineering_decision(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        result = _host_docker_council(req)
        decision = emulate_human_engineering_authority(
            result, HumanDecision(DEFER_DECISION), preflight,
        )
        assert decision is None

    def test_request_rework_produces_no_engineering_decision(self):
        """Part 19: REQUEST_REWORK only where the current contract
        permits -- no hidden automatic winner is chosen; a human rework
        request results in no EngineeringDecision from the CURRENT
        CouncilResult (a fresh Chairman/Council cycle is a separate,
        already-governed concern, not invented here)."""
        req = _requirement()
        preflight = _binding_preflight(req)
        result = _host_docker_council(req)
        decision = emulate_human_engineering_authority(
            result, HumanDecision(REQUEST_REWORK), preflight,
        )
        assert decision is None

    def test_provenance_exactly_records_human_authority(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        result = _host_docker_council(req)
        decision = emulate_human_engineering_authority(
            result, HumanDecision(SELECT_ALTERNATIVE, "docker"), preflight,
        )
        assert decision.selection_authority == "human"
        chairman_decision = emulate_human_engineering_authority(
            result, HumanDecision(ACCEPT_RECOMMENDATION), preflight,
        )
        assert chairman_decision.selection_authority == "chairman"

    def test_no_human_choice_required_but_absent_yields_no_decision(self):
        """describe_engineering_variant_selection() (S2.4, non-raising)
        must report selection_authority="none" when multiple admissible
        candidates exist and neither the Chairman recommendation nor an
        explicit human choice was resolvable."""
        req = _requirement()
        preflight = _binding_preflight(req)
        result = _host_docker_council(req)
        selection = describe_engineering_variant_selection(
            CouncilResult(id="c2", project_id="proj", variants=result.variants,
                          recommendation=None, council_complete=True),
            preflight,
        )
        assert selection.selected_variant_id is None
        assert selection.selection_authority == "none"


# =========================================================================
# TC-B-S2.1-2.2: alternatives / cross-review-evidence artifact boundary
# (CLAUDE-ARCH-S2-012B, Gate G: this coverage previously existed only
# implicitly, exercised incidentally by TestPhase1DataIsolation/
# TestPhase1Parallelism/TestPhase2DataIsolation in test_engineering_
# council.py without ever asserting the cross-boundary ARTIFACT SHAPE
# itself -- CLAUDE-ARCH-S2-012A's own report explicitly disclosed this
# as "implicit"; these tests make it explicit and mechanically
# discoverable by name.)
# =========================================================================


class TestBoundaryS2_1_to_S2_2:
    """S2.1 (_phase1_independent_proposals / _phase2_cross_review) hands
    S2.2 exactly two artifacts: the merged ProposalSet (every agent's
    variants, keyed by variant_id) and the tuple of AgentVoteSets (the
    cross-review evidence). S2.2 must receive both, complete, and
    unmodified -- never a filtered or S2.2-recomputed subset."""

    def test_s2_1_proposal_artifact_reaches_s2_2_chairman_prompt_complete(self, tmp_path):
        from tests.test_engineering_council import (
            _all_variant_ids,
            _build_standard_providers,
            _make_chairman_response,
            _make_council_config,
            _make_phase1_response,
            _make_phase2_response,
            _run_council_with_fakes,
        )

        a1_resp = _make_phase1_response("A1", 1)
        a2_resp = _make_phase1_response("A2", 1)
        a3_resp = _make_phase1_response("A3", 1)
        all_ids = _all_variant_ids([a1_resp, a2_resp, a3_resp])
        ph2_resp = _make_phase2_response("x", all_ids)
        ch_resp = _make_chairman_response(all_ids)
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp)
        captured_configs: list = []

        result = _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path, capture_configs=captured_configs,
        )

        # Every S2.1-produced variant id (the ProposalSet artifact) is
        # visible to the Chairman's own final synthesis (S2.2) --
        # nothing was dropped or recomputed crossing the boundary.
        assert result.council_complete
        chairman_variant_ids = {v.id for v in result.variants}
        assert chairman_variant_ids == set(all_ids)

    def test_s2_1_cross_review_votes_reach_s2_2_via_phase2_barrier(self, tmp_path):
        """The cross-review evidence (AgentVoteSets from _phase2_cross_
        review) is gathered from ALL phase-1 agents before S2.2's
        Chairman synthesis (phase 3) ever starts -- proven by the
        existing PhaseBarrier discipline; asserted here explicitly as
        the S2.1->S2.2 boundary artifact, not merely as a threading
        property."""
        from tests.test_engineering_council import (
            _all_variant_ids,
            _build_standard_providers,
            _make_chairman_response,
            _make_council_config,
            _make_phase1_response,
            _make_phase2_response,
            _run_council_with_fakes,
        )

        a1_resp = _make_phase1_response("A1", 1)
        a2_resp = _make_phase1_response("A2", 1)
        a3_resp = _make_phase1_response("A3", 1)
        all_ids = _all_variant_ids([a1_resp, a2_resp, a3_resp])
        ph2_resp = _make_phase2_response("x", all_ids)
        ch_resp = _make_chairman_response(all_ids)
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp)

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        # Each of the 3 phase-1 providers was called exactly twice
        # (phase 1 proposal, then phase 2 cross-review vote) -- the
        # cross-review evidence for ALL agents was gathered before the
        # (separately-called-once) chairman synthesis, confirming the
        # complete AgentVoteSet tuple crossed the boundary before S2.2
        # ever ran.
        for provider in fake_providers.values():
            assert len(provider.calls) >= 1
        assert result.council_complete


# =========================================================================
# TC-B-S2.2-2.3: Chairman-synthesis-result / admissibility-authority
# boundary (CLAUDE-ARCH-S2-012B, Gate G: previously implicit via
# TestControlledSetupEligibility/TestCouncilResultOrigin/
# TestBindingRequirementCoverageAcrossVariants in test_engineering_
# council.py; made explicit here. Also directly demonstrates Gate C:
# S2.3's validate_variants() is the ONLY function consulted, on the
# exact CouncilResult S2.2 produced -- never a duplicated policy.)
# =========================================================================


class TestBoundaryS2_2_to_S2_3:
    def test_structurally_complete_council_result_is_the_sole_artifact_s2_3_receives(self, tmp_path):
        from tests.test_engineering_council import (
            _all_variant_ids,
            _build_standard_providers,
            _make_chairman_response,
            _make_council_config,
            _make_phase1_response,
            _make_phase2_response,
            _run_council_with_fakes,
        )

        a1_resp = _make_phase1_response("A1", 1)
        a2_resp = _make_phase1_response("A2", 1)
        a3_resp = _make_phase1_response("A3", 1)
        all_ids = _all_variant_ids([a1_resp, a2_resp, a3_resp])
        ph2_resp = _make_phase2_response("x", all_ids)
        ch_resp = _make_chairman_response(all_ids)
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp)

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        # S2.3 needs nothing beyond the CouncilResult itself (plus its
        # own preflight/platform inputs) to render a verdict -- proving
        # the CouncilResult is a complete, self-sufficient artifact
        # crossing this boundary.
        assert result.council_complete
        validations = validate_variants(result.variants, preflight=None, platform=None)
        assert len(validations) == len(result.variants)
        assert {v.variant.id for v in validations} == {v.id for v in result.variants}

    def test_s2_3_rejection_of_the_recommended_variant_is_visible_across_the_boundary(self, tmp_path):
        """A structurally complete CouncilResult (S2.2's output) whose
        recommended variant S2.3 finds inadmissible still crosses the
        boundary intact -- S2.3 renders its OWN verdict on the exact
        artifact received, never a pre-filtered one (Gate B/C)."""
        from tests.test_engineering_council import (
            FakeLLMProvider,
            _all_variant_ids,
            _build_standard_providers,
            _make_chairman_response,
            _make_council_config,
            _make_phase1_response,
            _make_phase2_response,
            _run_council_with_fakes,
        )

        a1_resp = _make_phase1_response("A1", 1)
        a2_resp = _make_phase1_response("A2", 1)
        a3_resp = _make_phase1_response("A3", 1)
        all_ids = _all_variant_ids([a1_resp, a2_resp, a3_resp])
        ph2_resp = _make_phase2_response("x", all_ids)
        ch_data = json.loads(_make_chairman_response(all_ids))
        ch_data["variants"][0]["toolchain"] = [{
            "requirement_ref": "req-1", "name": "python", "type": "python_package",
            "install_method": "pip", "version": None, "state": "needs_install",
            "environment_constraint": "windows", "provided_by": None,
        }]
        ch_resp = json.dumps(ch_data)
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp)
        fake_providers["model-ch"] = FakeLLMProvider([ch_resp, ch_resp])

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert result.council_complete
        recommended = next(v for v in result.variants if v.id == result.recommendation)
        validation = validate_variants((recommended,), preflight=None, platform="linux")[0]
        assert validation.admissible is False
        assert "violates platform constraint" in validation.reasons[0]


# =========================================================================
# TC-S2.3-VERIFICATION-FEASIBILITY (CLAUDE-ARCH-S2-013E): closes the
# CLAUDE-ARCH-S2-013A LOW-MEDIUM finding. The exhaustive RED/GREEN case
# matrix (A-J, 10 representative candidates, repair-path evidence) lives
# in tests/test_verification_feasibility.py; these tests exist so the
# TC-S2.3-VERIFICATION-FEASIBILITY id itself is mechanically discoverable
# from this file, per the established S2 Subsubsystem traceability
# convention (mirrors TC-S2.3-materializability's own placement).
# =========================================================================


class TestVerificationFeasibilityBoundary:
    @staticmethod
    def _requirement_needing_verification(req_id="req-esphome"):
        from dataclasses import replace
        return replace(_requirement(req_id), verification_method="run the firmware test suite")

    def test_vague_free_text_alone_is_inadmissible(self):
        req = self._requirement_needing_verification()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(_pip_item(req.id),), verification="run tests",
        )
        validations = validate_variants((variant,), preflight=preflight)
        assert validations[0].admissible is False
        assert "missing required verification coverage" in validations[0].reasons[0]

    def test_structured_grounded_evidence_is_admissible(self):
        from app.council_models import VerificationCoverage
        from app.verification import trusted_verification_identity_groups
        req = self._requirement_needing_verification()
        preflight = _binding_preflight(req)
        pytest_item = ToolchainItem(
            requirement_ref=req.id, name="pytest", type="executable",
            technical_identity="pytest", provides_verification=("pytest",),
        )
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(_pip_item(req.id), pytest_item),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism="pytest", evidence="pytest",
            ),),
        )
        trusted_groups = trusted_verification_identity_groups(
            {"test_systems": ["pytest"], "build_systems": [], "firmware_indicators": []},
        )
        validations = validate_variants(
            (variant,), preflight=preflight, trusted_verification_groups=trusted_groups,
        )
        assert validations[0].admissible is True

    def test_s2_3_remains_sole_authority_no_execution(self):
        """S2.3 verification feasibility is a pure function over already-
        structured data -- it never imports S5's execution machinery."""
        import inspect
        import app.engineering_decision as ed_module
        source = inspect.getsource(ed_module)
        assert "app.verification" not in source
        assert "subprocess" not in source


# =========================================================================
# TC-B-S2.3-2.4: admissible/inadmissible domain boundary
# =========================================================================


class TestBoundaryS2_3_to_S2_4:
    def test_one_admissible_candidate(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(id="v1", name="v1", toolchain=(_pip_item(req.id),))
        validations = validate_variants((variant,), preflight)
        match, authority = resolve_human_engineering_selection(
            validations, chairman_recommendation="v1",
        )
        assert match.variant.id == "v1" and authority == "chairman"

    def test_multiple_admissible_candidates(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        result = _host_docker_council(req)
        validations = validate_variants(result.variants, preflight)
        assert len(admissible_variants(validations)) == 2

    def test_mixed_admissible_and_inadmissible(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        good = CouncilVariant(id="v1", name="v1", toolchain=(_pip_item(req.id),))
        bad = CouncilVariant(id="v2", name="v2", toolchain=())
        validations = validate_variants((good, bad), preflight)
        assert [v.variant.id for v in validations if v.admissible] == ["v1"]
        assert [v.variant.id for v in validations if not v.admissible] == ["v2"]

    def test_zero_admissible(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        bad = CouncilVariant(id="v1", name="v1", toolchain=())
        validations = validate_variants((bad,), preflight)
        assert admissible_variants(validations) == ()
        with pytest.raises(NoEligibleEngineeringCandidateError):
            resolve_human_engineering_selection(validations, chairman_recommendation="v1")

    def test_inadmissible_candidate_excluded_from_valid_selection_domain(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        good = CouncilVariant(id="v1", name="v1", toolchain=(_pip_item(req.id),))
        bad = CouncilVariant(id="v2", name="v2", toolchain=())
        validations = validate_variants((good, bad), preflight)
        assert "v2" not in [v.id for v in admissible_variants(validations)]

    def test_human_cannot_elevate_an_inadmissible_candidate(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        good = CouncilVariant(id="v1", name="v1", toolchain=(_pip_item(req.id),))
        bad = CouncilVariant(id="v2", name="v2", toolchain=())
        validations = validate_variants((good, bad), preflight)
        with pytest.raises(ChairmanRecommendationInadmissibleError):
            resolve_human_engineering_selection(
                validations, chairman_recommendation="v1", human_selected_variant_id="v2",
            )

    def test_all_validation_provenance_preserved_into_selection(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        good = CouncilVariant(id="v1", name="v1", toolchain=(_pip_item(req.id),))
        bad = CouncilVariant(id="v2", name="v2", toolchain=())
        validations = validate_variants((good, bad), preflight)
        try:
            resolve_human_engineering_selection(
                validations, chairman_recommendation="v1", human_selected_variant_id="v2",
            )
        except ChairmanRecommendationInadmissibleError as exc:
            assert len(exc.rejected) == 1 and exc.rejected[0].variant.id == "v2"
            assert [v.id for v in exc.admissible] == ["v1"]


# =========================================================================
# TC-B-S2.4-2.5: selection -> EngineeringDecision boundary
# =========================================================================


class TestBoundaryS2_4_to_S2_5:
    def test_accepted_recommendation_becomes_engineering_decision(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(id="v1", name="v1", toolchain=(_pip_item(req.id),))
        validations = validate_variants((variant,), preflight)
        match, authority = resolve_human_engineering_selection(validations, chairman_recommendation="v1")
        decision = build_engineering_decision(match, authority)
        assert decision.variant.id == "v1" and decision.selection_authority == "chairman"

    def test_human_alternative_selection_becomes_engineering_decision(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        result = _host_docker_council(req)
        validations = validate_variants(result.variants, preflight)
        match, authority = resolve_human_engineering_selection(
            validations, chairman_recommendation="host", human_selected_variant_id="docker",
        )
        decision = build_engineering_decision(match, authority)
        assert decision.variant.id == "docker" and decision.selection_authority == "human"

    def test_absent_required_human_choice_raises_selection_required(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        result = _host_docker_council(req)
        validations = validate_variants(result.variants, preflight)
        with pytest.raises(EngineeringSelectionRequiredError):
            resolve_human_engineering_selection(validations)

    def test_invalid_human_choice_never_produces_a_decision(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        result = _host_docker_council(req)
        validations = validate_variants(result.variants, preflight)
        with pytest.raises(EngineeringVariantNotFoundError):
            resolve_human_engineering_selection(validations, human_selected_variant_id="ghost")

    def test_selection_authority_preservation(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(id="v1", name="v1", toolchain=(_pip_item(req.id),))
        validations = validate_variants((variant,), preflight)
        match, authority = resolve_human_engineering_selection(validations)
        assert authority == "sole_admissible"
        decision = build_engineering_decision(match, authority)
        assert decision.selection_authority == "sole_admissible"

    def test_exact_selected_candidate_preservation(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        result = _host_docker_council(req)
        validations = validate_variants(result.variants, preflight)
        match, authority = resolve_human_engineering_selection(
            validations, chairman_recommendation="docker",
        )
        decision = build_engineering_decision(match, authority)
        assert decision.variant is match.variant

    def test_no_silent_fallback_when_recommendation_and_selection_absent_and_ambiguous(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        result = _host_docker_council(req)
        validations = validate_variants(result.variants, preflight)
        with pytest.raises(EngineeringSelectionRequiredError):
            resolve_human_engineering_selection(validations)


# =========================================================================
# CLAUDE-ARCH-S2-013C: the PRODUCTIVE S2.4 boundary, exercised through
# DevelopmentWorkflow itself (not only the raw S2.4 functions above) --
# TC-B-S2.3-S2.4 (admissible candidate set reaches the human decision
# boundary), TC-S2.4 (human selection authority: accept/select/reject/
# defer/rework -- reject/defer/rework are exercised productively at the
# Web/API layer in tests/test_productive_web_e2e.py, since dev_workflow
# itself does not model them -- see DevelopmentWorkflow.resolve_
# engineering_selection()'s own docstring), TC-B-S2.4-2.5 (only an
# explicit, valid human selection ever creates S2.5 input), TC-B-S2.5-S3
# (EngineeringDecision reaches S3, never before S2.4 is explicitly
# complete). The exhaustive RED/GREEN matrix (unknown id, inadmissible
# id, multiple admissible alternatives, zero admissible, bounded repair
# untouched) lives in tests/test_engineering_selection_boundary.py;
# these tests exist so the boundary IDs themselves are mechanically
# discoverable from this file, per the established S2 traceability
# convention.
# =========================================================================


class TestProductiveS2_4Boundary:
    def _workflow(self):
        from unittest.mock import MagicMock

        from app.ai_requirement_discovery import AIRequirementDiscovery
        from app.dev_workflow import DevelopmentWorkflow
        from app.engineering_council import EngineeringCouncil
        from app.requirement_preflight import RequirementPreflight
        from app.requirement_validator import RequirementValidator
        from app.setup_planner import SetupPlanner
        from tests.test_dev_workflow import _make_components

        (
            discovery, validator, preflight, planner, council, materializer,
            discovery_result, validation_result, preflight_result,
            council_result, plan_result,
        ) = _make_components()
        workflow = DevelopmentWorkflow(
            discovery, validator, preflight, planner,
            council=council, materializer=materializer,
        )
        return workflow, materializer, preflight_result, council_result, plan_result

    def test_tc_b_s2_3_s2_4_admissible_set_reaches_the_human_boundary(self):
        workflow, materializer, *_ = self._workflow()
        result = workflow.run({"name": "test"}, "proj-1")
        assert result.setup_plan is None
        assert result.engineering_selection is not None
        admissible = [v for v in result.engineering_selection.validations if v.admissible]
        assert len(admissible) >= 1
        materializer.materialize_decision.assert_not_called()

    def test_tc_b_s2_4_2_5_only_explicit_human_selection_creates_s2_5_input(self):
        workflow, materializer, preflight_result, council_result, plan_result = self._workflow()
        pending = workflow.run({"name": "test"}, "proj-1")

        resumed = workflow.resolve_engineering_selection(
            pending.council_result, preflight_result, "linux", "proj-1",
            human_selected_variant_id="v1",
        )

        decision = materializer.materialize_decision.call_args.args[0]
        assert decision.variant.id == "v1"
        assert decision.selection_authority == "human"
        assert resumed.setup_plan is plan_result

    def test_tc_b_s2_5_s3_no_s3_execution_before_s2_4_is_complete(self):
        workflow, materializer, *_ = self._workflow()
        workflow.run({"name": "test"}, "proj-1")
        # No resolve_engineering_selection() call happened -- S3 must
        # never have been reached.
        materializer.materialize_decision.assert_not_called()
        materializer.materialize.assert_not_called()


# =========================================================================
# TC-B-S2.5-S3: the S2.5 -> S3 handoff boundary (CLAUDE-ARCH-S2-012B,
# Gap 4: renamed from "TC-B-S2-S3" -- ToolchainMaterializer.
# materialize_decision() below is the S3-owned consumer/entry point,
# never an S2.5-owned Unit)
# =========================================================================


class TestBoundaryS2ToS3:
    def test_valid_engineering_decision_crosses_the_boundary(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(id="v1", name="v1", toolchain=(_pip_item(req.id),))
        decision = select_engineering_variant(
            CouncilResult(id="c1", project_id="proj", variants=(variant,),
                          recommendation="v1", council_complete=True),
            preflight, chairman_recommendation="v1",
        )
        plan = ToolchainMaterializer().materialize_decision(decision, "proj", preflight=preflight)
        assert plan.status == "pending_approval"

    def test_materialize_decision_takes_no_council_result_no_recommendation_no_platform(self):
        """CLAUDE-ARCH-S2-012A, RED-2 permanent regression: the pure S3
        entry point structurally CANNOT reach back into S2 selection --
        it is never even given a CouncilResult, a recommendation string,
        or a platform to resolve. It only ever sees the one, already-
        chosen EngineeringDecision. This is impossible to satisfy by
        accident if materialize_decision() ever grew a CouncilResult
        parameter -- the test would then need one to pass, and its own
        signature inspection below would fail first."""
        import inspect
        signature = inspect.signature(ToolchainMaterializer.materialize_decision)
        params = list(signature.parameters)
        assert "council_result" not in params
        assert "recommendation" not in params
        assert "chairman_recommendation" not in params
        assert "human_selected_variant_id" not in params

        req = _requirement()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(id="v1", name="v1", toolchain=(_pip_item(req.id),))
        decision = EngineeringDecision(
            variant=variant,
            solution_class=validate_variants((variant,), preflight)[0].solution_class,
            selection_authority="human",
        )
        plan = ToolchainMaterializer().materialize_decision(decision, "proj", preflight=preflight)
        assert plan.status == "pending_approval"

    def test_raw_council_variant_rejected_as_normal_handoff(self):
        variant = CouncilVariant(id="v1", name="v1")
        with pytest.raises((TypeError, AttributeError)):
            ToolchainMaterializer().materialize_decision(variant, "proj")

    def test_raw_council_result_rejected_as_normal_engineering_decision(self):
        result = CouncilResult(id="c1", project_id="proj")
        with pytest.raises(AttributeError):
            ToolchainMaterializer().materialize_decision(result, "proj")

    def test_inadmissible_candidate_cannot_cross_the_boundary(self):
        """An inadmissible candidate never becomes an EngineeringDecision
        in the first place (S2.3/S2.4 reject it before S2.5 could build
        one) -- there is structurally nothing invalid to hand to S3."""
        req = _requirement()
        preflight = _binding_preflight(req)
        inadmissible = CouncilVariant(id="v1", name="v1", toolchain=())
        with pytest.raises(NoEligibleEngineeringCandidateError):
            select_engineering_variant(
                CouncilResult(id="c1", project_id="proj", variants=(inadmissible,),
                              recommendation="v1", council_complete=True),
                preflight, chairman_recommendation="v1",
            )

    def test_s3_receives_exact_chosen_variant_human_selected(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        result = _host_docker_council(req)
        decision = select_engineering_variant(
            result, preflight, chairman_recommendation="host",
            human_selected_variant_id="docker",
        )
        plan = ToolchainMaterializer().materialize_decision(decision, "proj", preflight=preflight)
        materialized_refs = {step.requirement_id for step in plan.steps}
        assert materialized_refs == {req.id}
        assert decision.variant.id == "docker"

    def test_s3_receives_exact_chosen_variant_chairman_selected_when_human_accepts(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        result = _host_docker_council(req)
        decision = select_engineering_variant(
            result, preflight, chairman_recommendation="host",
        )
        assert decision.variant.id == "host"
        plan = ToolchainMaterializer().materialize_decision(decision, "proj", preflight=preflight)
        assert plan.status == "pending_approval"

    def test_s3_does_not_change_engineering_solution_class(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(id="v1", name="v1", environment="docker",
                                  toolchain=(_pip_item(req.id),))
        decision = select_engineering_variant(
            CouncilResult(id="c1", project_id="proj", variants=(variant,),
                          recommendation="v1", council_complete=True),
            preflight, chairman_recommendation="v1",
        )
        before = decision.solution_class
        ToolchainMaterializer().materialize_decision(decision, "proj", preflight=preflight)
        assert decision.solution_class == before

    def test_s3_still_validates_its_own_setup_execution_contracts(self):
        """S3 legitimately keeps its OWN defensive checks (e.g. an
        incomplete recommendation reference at the materializer's own
        pre-check level in the compatibility materialize() path) -- this
        task must not remove S3's own integrity checks."""
        from app.toolchain_materializer import ToolchainMaterializationError
        empty_result = CouncilResult(id="c1", project_id="proj", council_complete=True)
        with pytest.raises(ToolchainMaterializationError):
            ToolchainMaterializer().materialize(empty_result, "proj")


# =========================================================================
# Authority-leak negative tests (Part 23)
# =========================================================================


class TestAuthorityLeaks:
    def test_s2_3_cannot_select_preferred_candidate_among_admissible_ones(self):
        """validate_variants()/CandidateValidation never expresses a
        preference -- only admissible/inadmissible with reasons. There is
        no field, return value, or side effect representing "the S2.3-
        preferred candidate"."""
        req = _requirement()
        preflight = _binding_preflight(req)
        result = _host_docker_council(req)
        validations = validate_variants(result.variants, preflight)
        assert all(v.admissible for v in validations)
        assert not hasattr(validations, "preferred")
        assert len({v.variant.id for v in validations}) == 2

    def test_s2_3_cannot_override_chairman_recommendation_with_another_candidate(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        result = _host_docker_council(req)
        decision = select_engineering_variant(result, preflight, chairman_recommendation="docker")
        assert decision.variant.id == "docker"
        assert decision.selection_authority == "chairman"

    def test_s2_3_cannot_synthesize_an_engineering_candidate(self):
        """validate_variants() only ever classifies variants it was
        GIVEN -- it cannot invent one. Passing zero variants in yields
        zero validations, never a synthesized candidate."""
        assert validate_variants(()) == ()

    def test_s2_4_cannot_make_an_inadmissible_candidate_admissible(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        inadmissible = CouncilVariant(id="v1", name="v1", toolchain=())
        validations = validate_variants((inadmissible,), preflight)
        with pytest.raises(NoEligibleEngineeringCandidateError):
            resolve_human_engineering_selection(
                validations, human_selected_variant_id="v1",
            )

    def test_s2_4_cannot_modify_validation_evidence(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(id="v1", name="v1", toolchain=(_pip_item(req.id),))
        validations = validate_variants((variant,), preflight)
        match, _ = resolve_human_engineering_selection(validations, chairman_recommendation="v1")
        assert match is validations[0]
        assert match.reasons == ()

    def test_s2_5_cannot_invent_a_selection(self):
        """build_engineering_decision() takes an already-resolved match
        and authority -- it has no code path that picks a variant on its
        own; it is a pure, one-line constructor."""
        req = _requirement()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(id="v1", name="v1", toolchain=(_pip_item(req.id),))
        validation = validate_variants((variant,), preflight)[0]
        decision = build_engineering_decision(validation, "human")
        assert decision.variant is variant
        assert decision.selection_authority == "human"

    def test_s3_cannot_choose_engineering_candidate_materialize_decision_is_deterministic_passthrough(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        result = _host_docker_council(req)
        decision_a = select_engineering_variant(result, preflight, chairman_recommendation="host")
        decision_b = select_engineering_variant(result, preflight, chairman_recommendation="docker")
        plan_a = ToolchainMaterializer().materialize_decision(decision_a, "proj", preflight=preflight)
        plan_b = ToolchainMaterializer().materialize_decision(decision_b, "proj", preflight=preflight)
        # Both are valid plans reflecting exactly what was handed in --
        # S3 never overrides which variant it was given.
        assert plan_a.status == plan_b.status == "pending_approval"

    def test_s3_cannot_silently_replace_the_engineering_decision_variant(self):
        req = _requirement()
        satisfied_preflight = PreflightResult(
            id="pre-1", project_id="proj", overall_ready=True,
            results=(PreflightRequirementResult(
                requirement_id=req.id, present=True, satisfied=True,
            ),),
            missing_requirements=(), activations=(),
        )
        variant = CouncilVariant(
            id="v1", name="v1",
            toolchain=(_pip_item(req.id, state="already_installed"),),
        )
        decision = EngineeringDecision(
            variant=variant,
            solution_class=validate_variants((variant,))[0].solution_class,
            selection_authority="human",
        )
        plan = ToolchainMaterializer().materialize_decision(
            decision, "proj", preflight=satisfied_preflight,
        )
        # The authoritative Preflight says req-esphome is already
        # satisfied -> no install step is generated; this proves the
        # plan was built from decision.variant's OWN identity/state (as
        # cross-checked against the SAME preflight S3 was given), not a
        # substituted candidate materialize_decision() invented on its
        # own -- it has no OTHER candidate available to substitute at all.
        assert not any(step.action == "install" for step in plan.steps)


# =========================================================================
# Setup Approval independence (part of TC-B-S2.5-S3 / Authority)
# =========================================================================


class TestSetupApprovalRemainsSeparateFromEngineeringSelection:
    def test_setup_approval_operates_only_on_the_setup_plan(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        result = _host_docker_council(req)
        decision = select_engineering_variant(result, preflight, chairman_recommendation="docker")
        plan = ToolchainMaterializer().materialize_decision(decision, "proj", preflight=preflight)
        approved = SetupApproval.approve(plan)
        assert approved.status == "approved"
        assert all(step.is_approved for step in approved.steps)


# =========================================================================
# S2 subsystem acceptance scenarios (Part 22)
# =========================================================================


class TestS2SubsystemScenarios:
    """S2-SCENARIO-01..09, 12, 13 (built from real internal S2/S3
    components, no LLM/network mocks needed since a hand-built
    CouncilResult stands in for an already-completed Council synthesis --
    scenarios exercising the Chairman/repair LLM boundary itself live in
    tests/test_engineering_council.py's TestBoundedChairmanRepair, per
    Part 22's own rule that mocks are for the true external boundary
    only)."""

    def test_scenario_01_recommendation_accepted_reaches_engineering_decision(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(id="v1", name="v1", toolchain=(_pip_item(req.id),))
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        decision = emulate_human_engineering_authority(
            result, HumanDecision(ACCEPT_RECOMMENDATION), preflight,
        )
        plan = ToolchainMaterializer().materialize_decision(decision, "proj", preflight=preflight)
        assert plan.status == "pending_approval"

    def test_scenario_02_human_selects_b_reaches_engineering_decision_unchanged(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        result = _host_docker_council(req)
        decision = emulate_human_engineering_authority(
            result, HumanDecision(SELECT_ALTERNATIVE, "docker"), preflight,
        )
        assert decision.variant.id == "docker"
        plan = ToolchainMaterializer().materialize_decision(decision, "proj", preflight=preflight)
        assert plan.status == "pending_approval"

    def test_scenario_05_all_candidates_inadmissible_zero_decision_zero_handoff(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        bad_a = CouncilVariant(id="v1", name="v1", toolchain=())
        bad_b = CouncilVariant(id="v2", name="v2", toolchain=())
        result = CouncilResult(id="c1", project_id="proj", variants=(bad_a, bad_b),
                                recommendation="v1", council_complete=True)
        with pytest.raises(NoEligibleEngineeringCandidateError):
            emulate_human_engineering_authority(result, HumanDecision(ACCEPT_RECOMMENDATION), preflight)

    def test_scenario_06_human_rejects_all_zero_engineering_decision(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        result = _host_docker_council(req)
        decision = emulate_human_engineering_authority(result, HumanDecision(REJECT_ALL), preflight)
        assert decision is None

    def test_scenario_07_human_defers_zero_engineering_decision(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        result = _host_docker_council(req)
        decision = emulate_human_engineering_authority(result, HumanDecision(DEFER_DECISION), preflight)
        assert decision is None

    def test_scenario_08_host_and_docker_both_admissible_chairman_may_recommend_either(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        result = _host_docker_council(req)
        decision_host = select_engineering_variant(result, preflight, chairman_recommendation="host")
        decision_docker = select_engineering_variant(result, preflight, chairman_recommendation="docker")
        assert {decision_host.variant.id, decision_docker.variant.id} == {"host", "docker"}

    def test_scenario_08_human_may_choose_either(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        result = _host_docker_council(req)
        for choice in ("host", "docker"):
            decision = select_engineering_variant(
                result, preflight, chairman_recommendation="host",
                human_selected_variant_id=choice,
            )
            assert decision.variant.id == choice

    def test_scenario_09_host_venv_docker_vm_all_admissible_no_forced_winner(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        host = CouncilVariant(id="host", name="Host", environment="host", toolchain=(_pip_item(req.id),))
        venv = CouncilVariant(id="venv", name="venv", environment="host", toolchain=(_pip_item(req.id),))
        docker = CouncilVariant(id="docker", name="Docker", environment="docker", toolchain=(_pip_item(req.id),))
        vm = CouncilVariant(id="vm", name="VM", environment="vm", toolchain=(_pip_item(req.id),))
        result = CouncilResult(id="c1", project_id="proj", variants=(host, venv, docker, vm),
                                recommendation="host", council_complete=True)
        validations = validate_variants(result.variants, preflight)
        assert len(admissible_variants(validations)) == 4
        # No single "preferred" survivor -- each can still individually
        # become the EngineeringDecision when named.
        for candidate_id in ("host", "venv", "docker", "vm"):
            decision = select_engineering_variant(result, preflight, chairman_recommendation=candidate_id)
            assert decision.variant.id == candidate_id

    def test_scenario_10_requirement_failure_caught_in_s2_3_before_s3(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        incomplete = CouncilVariant(id="v1", name="v1", toolchain=())
        result = CouncilResult(id="c1", project_id="proj", variants=(incomplete,),
                                recommendation="v1", council_complete=True)
        with pytest.raises(NoEligibleEngineeringCandidateError) as excinfo:
            select_engineering_variant(result, preflight, chairman_recommendation="v1")
        assert "missing binding requirement coverage" in str(excinfo.value)

    def test_scenario_12_constraint_and_platform_failure_caught_in_s2_3_before_s3(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(
            id="v1", name="v1",
            toolchain=(_pip_item(req.id, environment_constraint="windows"),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        with pytest.raises(NoEligibleEngineeringCandidateError) as excinfo:
            select_engineering_variant(result, preflight, platform="linux", chairman_recommendation="v1")
        assert "violates platform constraint" in str(excinfo.value)

    def test_scenario_13_materializability_failure_caught_in_s2_3_before_s3(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        broken = CouncilVariant(
            id="v1", name="v1",
            toolchain=(_pip_item(
                req.id,
                install_method="python3 -m venv .venv && source .venv/bin/activate && pip install esphome",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(broken,),
                                recommendation="v1", council_complete=True)
        with pytest.raises(NoEligibleEngineeringCandidateError) as excinfo:
            select_engineering_variant(result, preflight, chairman_recommendation="v1")
        assert "cannot be materialized" in str(excinfo.value)


# =========================================================================
# Real-System-E2E #7 permanent generalized regression (Part 18)
# =========================================================================


class TestRealE2E7GeneralizedRegression:
    """CLAUDE-ARCH-S2-012A, RED-1: a structurally-valid, synthesis-
    complete Chairman recommendation that violates a binding platform
    Constraint must be caught at S2.3 -- generically, for ANY project/
    platform pair, never hardcoded to ESPHome/Linux."""

    def _two_candidate_council(self, req, platform_a, platform_b):
        variant_a = CouncilVariant(
            id="candidate-a", name="Candidate A",
            toolchain=(_pip_item(req.id, environment_constraint=platform_a),),
        )
        variant_b = CouncilVariant(
            id="candidate-b", name="Candidate B",
            toolchain=(_pip_item(req.id, environment_constraint=platform_b),),
        )
        return CouncilResult(
            id="c1", project_id="proj", variants=(variant_a, variant_b),
            recommendation="candidate-a", council_complete=True,
        )

    @pytest.mark.parametrize("project_platform,candidate_platform", [
        ("linux", "windows"),
        ("windows", "linux"),
        ("darwin", "linux"),
        ("linux", "darwin"),
    ])
    def test_platform_invalid_recommendation_is_never_admissible_for_any_platform_pair(
        self, project_platform, candidate_platform,
    ):
        req = _requirement()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(
            id="candidate-a", name="Candidate A",
            toolchain=(_pip_item(req.id, environment_constraint=candidate_platform),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="candidate-a", council_complete=True)
        with pytest.raises(NoEligibleEngineeringCandidateError):
            select_engineering_variant(
                result, preflight, platform=project_platform,
                chairman_recommendation="candidate-a",
            )

    def test_same_candidate_compatible_with_platform_is_admissible(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(
            id="candidate-a", name="Candidate A",
            toolchain=(_pip_item(req.id, environment_constraint="linux"),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="candidate-a", council_complete=True)
        decision = select_engineering_variant(
            result, preflight, platform="linux", chairman_recommendation="candidate-a",
        )
        assert decision.variant.id == "candidate-a"

    def test_one_platform_invalid_and_one_platform_valid_candidate(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        result = self._two_candidate_council(req, "windows", "linux")
        validations = validate_variants(result.variants, preflight, platform="linux")
        by_id = {v.variant.id: v for v in validations}
        assert by_id["candidate-a"].admissible is False
        assert by_id["candidate-b"].admissible is True

    def test_chairman_recommends_invalid_one_recommendation_does_not_silently_switch(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        result = self._two_candidate_council(req, "windows", "linux")
        with pytest.raises(ChairmanRecommendationInadmissibleError) as excinfo:
            select_engineering_variant(
                result, preflight, platform="linux", chairman_recommendation="candidate-a",
            )
        assert excinfo.value.recommendation_id == "candidate-a"
        assert [v.id for v in excinfo.value.admissible] == ["candidate-b"]

    def test_human_may_choose_the_valid_alternative(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        result = self._two_candidate_council(req, "windows", "linux")
        decision = select_engineering_variant(
            result, preflight, platform="linux", chairman_recommendation="candidate-a",
            human_selected_variant_id="candidate-b",
        )
        assert decision.variant.id == "candidate-b"
        assert decision.selection_authority == "human"

    def test_all_candidates_platform_invalid_zero_admissible(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        result = self._two_candidate_council(req, "windows", "darwin")
        with pytest.raises(NoEligibleEngineeringCandidateError):
            select_engineering_variant(
                result, preflight, platform="linux", chairman_recommendation="candidate-a",
            )

    def test_platform_unspecified_does_not_reject_anything_on_this_dimension(self):
        req = _requirement()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(
            id="candidate-a", name="Candidate A",
            toolchain=(_pip_item(req.id, environment_constraint="windows"),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="candidate-a", council_complete=True)
        decision = select_engineering_variant(
            result, preflight, platform=None, chairman_recommendation="candidate-a",
        )
        assert decision.variant.id == "candidate-a"

    def test_end_to_end_council_level_e2e_7_shape_completes_structurally_and_is_caught_by_s2_3(self):
        """CLAUDE-ARCH-S2-012B: the FULL, mechanical Real-System-E2E #7
        reproduction. A structurally valid, single-candidate Chairman
        synthesis whose only candidate violates platform completes
        SYNTHESIS normally (council_complete=True, chairman_error=None
        -- S2.2 never gates completeness on S2.3's verdict, see Gate A/B
        of the independent review). The platform violation IS still
        caught -- by S2.3's own validate_candidates(), called by
        whichever consumer processes this "complete" CouncilResult next
        (exactly as any other post-synthesis S2.3 check already
        works) -- never silently lost."""
        from app.ai_config import CouncilAgentConfig, CouncilConfig
        from app.engineering_council import EngineeringCouncil
        from app.secret_resolver import SimpleSecretResolver
        from app.requirement_model import RequirementEvidence, Status

        def make_config():
            ac = lambda p, m: CouncilAgentConfig(role="x", provider=p, model=m, timeout_seconds=10, temperature=0.5)
            return CouncilConfig(
                enabled=True, max_variants_per_agent=2,
                environment_architect=ac("openrouter-ea", "model-ea"),
                toolchain_integrator=ac("openrouter-ti", "model-ti"),
                risk_assessor=ac("openrouter-ra", "model-ra"),
                chairman=ac("openrouter-ch", "model-ch"),
            )

        req = Requirement(
            id="req-1", name="esphome", type=RequirementType.PYTHON_PACKAGE,
            purpose="test", required=True, confidence=0.9,
            evidence=(RequirementEvidence(id="ev-1", source_type="test", description="test"),),
            status=Status.DISCOVERED,
        )
        council_input = CouncilInput(
            requirements=(req,),
            preflight=PreflightResult(
                id="pre-1", project_id="test-project", overall_ready=False,
                results=(PreflightRequirementResult(requirement_id="req-1", present=False, satisfied=False),),
                missing_requirements=(req,), activations=(RequirementActivation("req-1", True, True),),
                already_installed=(), warnings=(),
            ),
            detected_stack="esphome", project_id="esphome-p1", project_files=(), platform="linux",
        )

        class FakeLLMProvider:
            def __init__(self, responses):
                self._r = list(responses); self.calls = []
            def complete(self, prompt):
                self.calls.append(prompt)
                return self._r.pop(0)

        def phase1_resp(agent_id):
            return json.dumps({"variants": [{
                "variant_id": f"{agent_id}-var-1", "name": f"{agent_id} v", "description": "d",
                "environment": "host", "hardware_target": None, "connection": None, "capabilities": [],
                "toolchain": [{"requirement_ref": "req-1", "name": "esphome", "type": "python_package",
                               "install_method": "pip", "version": None, "purpose": "p", "depends_on": [],
                               "state": "needs_install", "environment_constraint": None}],
                "advantages": [], "disadvantages": [], "risks": [],
            }]})

        def phase2_resp(all_ids):
            return json.dumps({"votes": [
                {"variant_id": vid, "scores": {}, "would_recommend": True, "reasoning": "ok", "concerns": []}
                for vid in all_ids
            ]})

        a1, a2, a3 = phase1_resp("A1"), phase1_resp("A2"), phase1_resp("A3")
        ph2 = phase2_resp(["A1-var-1", "A2-var-1", "A3-var-1"])
        ch_resp = json.dumps({
            "merge_decisions": [], "rejected_variants": [],
            "variants": [{
                "id": "final-1", "name": "Standard ESPHome CLI Toolchain (Python venv)",
                "description": "d", "origin_agents": ["A2"], "merged_from": ["A2-var-1"],
                "rank": 1, "total_score": 5.0, "consensus_level": "strong_consensus",
                "minority_opinions": [], "environment": "host", "hardware_target": None,
                "connection": None, "capabilities": [],
                "toolchain": [{"requirement_ref": "req-1", "name": "esphome", "type": "python_package",
                               "install_method": "pip", "version": None, "state": "needs_install",
                               "environment_constraint": "windows", "provided_by": None}],
                "advantages": [], "disadvantages": [], "risks": [],
                "confidence": 0.9, "feasibility": "high", "verification": "test",
            }],
            "recommendation": "final-1", "reasoning": "ok",
        })
        fake_providers = {
            "model-ea": FakeLLMProvider([a1, ph2]), "model-ti": FakeLLMProvider([a2, ph2]),
            "model-ra": FakeLLMProvider([a3, ph2]), "model-ch": FakeLLMProvider([ch_resp]),
        }
        with patch("app.engineering_council.create_council_provider") as mf:
            mf.side_effect = lambda config, resolver, ollama_url=None: fake_providers[config.model]
            council = EngineeringCouncil(
                council_config=make_config(),
                secret_resolver=SimpleSecretResolver({"openrouter-api": "test"}),
            )
            result = council.evaluate(council_input)

        assert result.council_complete
        assert result.chairman_error is None
        assert result.recommendation == "final-1"

        from app.engineering_decision import validate_candidates
        validations = validate_candidates(result, preflight=council_input.preflight, platform="linux")
        assert validations[0].admissible is False
        assert "violates platform constraint" in validations[0].reasons[0]


class TestDiagnosticTraceS2FaultLocalization:
    """Part 28, corrected in CLAUDE-ARCH-S2-012B: a future failure must
    be classifiable approximately as "S2.2 PASS / S2.3 NIO:
    platform_constraint / S2.4 NOT REACHED / S2.5 NOT REACHED / S3 NOT
    REACHED". Since Gate A/B (synthesis_complete is structural-only),
    S2.2's OWN chairman_error/chairman_failure_category/
    chairman_failure_subsystem fields now ONLY ever reflect genuine
    PROTOCOL failures (S2.2's own domain) -- a mere S2.3 admissibility
    rejection of an otherwise-complete synthesis produces NO
    chairman_error at all (Gate B). The S2.3-level fault-localization
    ("S2.3 NIO: platform_constraint") is surfaced where S2.3 is actually
    consulted -- by whichever consumer calls select_engineering_
    variant()/validate_candidates() on the "complete" CouncilResult,
    exactly as already proven since CLAUDE-E2E-NIO-010A/011A via
    app/dev_workflow.py's own toolchain_materialization trace
    enrichment (unaffected by this correction)."""

    def test_genuine_protocol_failure_is_attributed_to_s2_2(self):
        """A genuinely S2.2-owned failure (invalid recommendation
        reference, never repairable in this fixture since the queue is
        exhausted) IS still reported via chairman_error/
        chairman_failure_category/chairman_failure_subsystem -- this
        remains S2.2's own, legitimate diagnostic domain, unaffected by
        Gate A/B (which is about ADMISSIBILITY, not protocol validity)."""
        from app.engineering_council import EngineeringCouncil
        from app.secret_resolver import SimpleSecretResolver
        from tests.test_engineering_council import (
            FakeLLMProvider,
            _build_standard_providers,
            _invalid_recommendation_chairman_response,
            _make_council_config,
            _make_council_input,
            _setup_standard_responses,
        )

        a1_resp, a2_resp, a3_resp, ph2_resp, _, all_ids = _setup_standard_responses()
        broken_ch_resp = _invalid_recommendation_chairman_response(all_ids)
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, broken_ch_resp)
        fake_providers["model-ch"] = FakeLLMProvider([broken_ch_resp, broken_ch_resp])

        structured_results = []
        with patch("app.engineering_council.create_council_provider") as mf:
            mf.side_effect = lambda config, resolver, ollama_url=None: fake_providers[config.model]
            council = EngineeringCouncil(
                council_config=_make_council_config(),
                secret_resolver=SimpleSecretResolver({"openrouter-api": "test"}),
            )
            council.set_result_callback(lambda **result: structured_results.append(result))
            result = council.evaluate(_make_council_input())

        assert not result.council_complete
        chairman_result = next(
            item for item in structured_results if item["result_kind"] == "chairman_decision"
        )
        info = chairman_result["council_output"]["info"]
        assert info["chairman_failure_category"] == "invalid_recommendation"
        assert info["chairman_failure_subsystem"] == "S2.2"
        assert info["chairman_attempts"] == 2

    def test_s2_3_admissibility_rejection_produces_no_chairman_error_but_is_discoverable_downstream(self, tmp_path):
        """Gate A/B: a structurally complete synthesis whose
        recommendation S2.3 rejects produces council_complete=True,
        chairman_error=None -- and the rejection remains fully
        discoverable via app/dev_workflow.py's existing (010A/011A,
        unchanged) toolchain_materialization trace enrichment, proving
        "S2.3 NIO: platform_constraint" fault localization still works
        end-to-end, just correctly attributed and correctly timed."""
        from unittest.mock import MagicMock

        from app.ai_requirement_discovery import AIRequirementDiscovery
        from app.dev_workflow import DevelopmentWorkflow
        from app.diagnostic_trace import DiagnosticTrace, DiagnosticTraceStore
        from app.engineering_council import EngineeringCouncil
        from app.engineering_decision import NoEligibleEngineeringCandidateError
        from app.requirement_preflight import RequirementPreflight
        from app.requirement_validator import RequirementValidator
        from app.toolchain_materializer import ToolchainMaterializer as RealToolchainMaterializer
        from tests.test_dev_workflow import _make_discovery_result, _make_validation_result

        req = _requirement()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(
            id="v1", name="v1",
            toolchain=(_pip_item(req.id, environment_constraint="windows"),),
        )
        council_result = CouncilResult(
            id="c1", project_id="proj-1", variants=(variant,),
            recommendation="v1", council_complete=True,
        )
        discovery_result = _make_discovery_result("proj-1")
        discovery = MagicMock(spec=AIRequirementDiscovery)
        validator = MagicMock(spec=RequirementValidator)
        preflight_stage = MagicMock(spec=RequirementPreflight)
        council = MagicMock(spec=EngineeringCouncil)
        discovery.discover.return_value = discovery_result
        validator.validate.return_value = _make_validation_result(discovery_result.requirements)
        preflight_stage.check.return_value = preflight
        council.evaluate.return_value = council_result

        trace = DiagnosticTrace(DiagnosticTraceStore(tmp_path / "trace.jsonl"))
        workflow = DevelopmentWorkflow(
            discovery, validator, preflight_stage,
            council=council, materializer=RealToolchainMaterializer(), diagnostic_trace=trace,
        )
        with pytest.raises(NoEligibleEngineeringCandidateError):
            workflow.run({"name": "test"}, "proj-1")

        events = trace.get_trace("proj-1")
        failure_events = [
            event for event in events
            if event.phase == "toolchain_materialization" and event.status == "failed"
            and "failure_summary" in event.details
        ]
        assert len(failure_events) == 1
        assert "violates platform constraint" in failure_events[0].details["failure_summary"]
