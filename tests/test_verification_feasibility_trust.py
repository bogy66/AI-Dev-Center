"""CLAUDE-ARCH-S2-013G: closes the trust/provenance gap CLAUDE-ARCH-S2-
013F's own independent review found in S2.3 Verification Feasibility.

013F made compatibility explicit via
`coverage.mechanism in ToolchainItem.provides_verification` -- but
`provides_verification` is declared by the SAME Agent/Chairman that
produces the candidate, so an LLM could still self-certify an invented
or incompatible verification capability (declaring both mechanism=
"pytest" AND provides_verification=("pytest",) on a candidate that has
nothing to do with pytest, or claiming a real mechanism via an item that
has nothing to do with it). This closes that hole:

    LLM claim
    -> structured candidate declaration (provides_verification)
    -> independent/trusted ADC capability evidence (Project
       Intelligence's own, pre-Council, deterministic detection --
       app.verification.trusted_verification_identity_groups())
    -> compatibility (both trace back to the SAME independently-
       detected capability)
    -> controllability/observability (ToolchainItem.state, unchanged
       since 013F)

A producer-declared provides_verification value ALONE must never
establish verification feasibility. RED-before-fix evidence: every FAIL
test below (mandatory cases 1, 2, 5, 6, 7 and the generalized malformed-
claims class) passed unmodified 013F code -- i.e. FAILED to reject --
before this task's `trusted_verification_groups`/
`governed_manual_verification_ids` parameters were wired into
app.engineering_decision._verification_coverage_is_compatible()
(confirmed before implementing the fix; see the completion report, R4).
"""
import pytest

from app.council_models import CouncilResult, CouncilVariant, ToolchainItem, VerificationCoverage
from app.engineering_decision import (
    EngineeringReworkRequest,
    categorize_admissibility_reasons,
    validate_candidates,
    validate_variants,
)
from app.verification import trusted_verification_identity_groups

from tests.test_engineering_decision import (
    _binding_preflight,
    _multi_requirement_preflight,
    _pip_item,
    _requirement_needing_verification,
    _trusted_groups,
)


def _fake_item(req_id, technical_identity, mechanism, state="needs_install"):
    """A candidate-local ToolchainItem that SELF-DECLARES it supports
    `mechanism` -- exactly the shape a self-certifying LLM would
    produce. Only trusted_verification_groups (never this declaration
    alone) can make that claim mechanically meaningful."""
    return ToolchainItem(
        requirement_ref=req_id, name=technical_identity, type="executable",
        technical_identity=technical_identity, provides_verification=(mechanism,),
        state=state,
    )


class TestCase1MadeUpRunnerSelfCertifiedFails:
    """1: made_up_runner_xyz declared both as mechanism and
    provides_verification by the same candidate/LLM, but unsupported by
    trusted ADC evidence -- FAIL, even with NO trusted evidence at all
    and even with UNRELATED trusted evidence present."""

    def test_fails_with_no_trusted_evidence_at_all(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        item = _fake_item(req.id, "made_up_toolchain", "made_up_runner_xyz")
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(item,),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism="made_up_runner_xyz", evidence="made_up_toolchain",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is False

    def test_fails_even_with_unrelated_trusted_evidence_present(self):
        """A real, independently-detected pytest project does not
        license an unrelated invented mechanism token."""
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        item = _fake_item(req.id, "made_up_toolchain", "made_up_runner_xyz")
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(item,),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism="made_up_runner_xyz", evidence="made_up_toolchain",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(
            result, preflight=preflight, trusted_verification_groups=_trusted_groups(test_systems=["pytest"]),
        )
        assert validations[0].admissible is False


class TestCase2PytestSelfDeclaredOnNpmOnlyCapabilityFails:
    """2: pytest self-declared on an npm-only capability -- the item's
    OWN identity ("jest", a real, independently-detected Node test
    system) is trusted, but that trust does not transfer to a
    completely different, self-declared mechanism ("pytest") the SAME
    item merely CLAIMS to also support."""

    def test_fails_even_though_the_items_own_identity_is_trusted(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        item = _fake_item(req.id, "jest", "pytest")  # jest item self-declaring pytest
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(item,),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism="pytest", evidence="jest",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(
            result, preflight=preflight, trusted_verification_groups=_trusted_groups(test_systems=["jest"]),
        )
        assert validations[0].admissible is False


class TestCase3LegitimatePytestClaimPasses:
    """3: a legitimate pytest claim with independent, compatible ADC
    capability evidence (Project Intelligence genuinely detected a
    pytest project) passes."""

    def test_passes_with_independent_compatible_evidence(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        item = _fake_item(req.id, "pytest", "pytest")
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(item, _pip_item(req.id)),
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


class TestCase4NonPythonExamplesPass:
    """4: legitimate build/ESPHome/non-pytest examples pass exactly like
    pytest does, once independently corroborated AND actually controlled
    (CLAUDE-ARCH-S2-014C, F2). jest/ctest are independently DETECTABLE
    but have NO registered controlled runner (RUNNER_MAP marks them
    "deferred") -- see TestControlledCapabilityRequired for that exact
    RED evidence; using them here as PASS examples was itself a
    false-confidence gap this task closes (see the CDX-REVIEW-S2-014A
    "FALSE-CONFIDENCE TEST REVIEW" list)."""

    def test_python_unittest_passes(self):
        """A DIFFERENT real, registered controlled runner than pytest
        (python_unittest -- app.verification.PythonUnittestRunner)."""
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        item = _fake_item(req.id, "unittest", "python_unittest")
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(item, _pip_item(req.id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism="python_unittest", evidence="unittest",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(
            result, preflight=preflight, trusted_verification_groups=_trusted_groups(test_systems=["unittest"]),
        )
        assert validations[0].admissible is True

    def test_cmake_build_passes(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        item = _fake_item(req.id, "cmake", "cmake")
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(item, _pip_item(req.id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="build_command",
                mechanism="cmake", evidence="cmake",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(
            result, preflight=preflight, trusted_verification_groups=_trusted_groups(build_systems=["cmake"]),
        )
        assert validations[0].admissible is True

    def test_esphome_check_passes(self):
        req = _requirement_needing_verification("req-esphome-fw")
        preflight = _binding_preflight(req)
        item = _fake_item(req.id, "esphome", "esphome_check")
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(item, _pip_item(req.id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="build_command",
                mechanism="esphome_check", evidence="esphome",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(
            result, preflight=preflight,
            trusted_verification_groups=_trusted_groups(firmware_indicators=["esphome"]),
        )
        assert validations[0].admissible is True

    def test_esphome_validate_passes(self):
        """CLAUDE-ADC-E2E-VERIFICATION-EVIDENCE-FIX-001: the ACTUAL
        mechanism vocabulary app.council_prompts/app.council_models
        instruct Council candidates to declare for ESPHome's "validate"
        step is "esphome_validate" (see both modules' own docstrings and
        app.engineering_decision._is_structured_verification_token's),
        not "esphome_check" (S5's own internal VerificationStep.
        runner_type). Before CLAUDE-ARCH-S2-014E this was rejected as
        uncorroborated self-certification even with a real, independently
        detected ESPHome project -- the exact Real-System-E2E failure
        (binding requirement inadmissible: 'no independent Project
        Intelligence evidence linking both to the same real capability').
        A genuinely-detected ESPHome capability using the documented
        mechanism token must be admissible."""
        req = _requirement_needing_verification("req-esphome-fw")
        preflight = _binding_preflight(req)
        item = _fake_item(req.id, "esphome", "esphome_validate")
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(item, _pip_item(req.id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="build_command",
                mechanism="esphome_validate", evidence="esphome",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(
            result, preflight=preflight,
            trusted_verification_groups=_trusted_groups(firmware_indicators=["esphome"]),
        )
        assert validations[0].admissible is True

    def test_esphome_validate_self_certified_without_independent_evidence_still_fails(self):
        """The positive esphome_validate case above must NOT be a
        blanket trust of the "esphome_validate" token itself -- with NO
        independent Project Intelligence evidence of an ESPHome project
        at all (trusted_verification_groups empty, exactly as when
        inspect_project() genuinely found no firmware indicator), the
        SAME self-declared mechanism/evidence pair must still be
        rejected as uncorroborated self-certification. Proves
        CLAUDE-ARCH-S2-014E only ADDS a missing, genuinely documented
        identity alias -- it never lets provides_verification alone
        establish feasibility."""
        req = _requirement_needing_verification("req-esphome-fw")
        preflight = _binding_preflight(req)
        item = _fake_item(req.id, "esphome", "esphome_validate")
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(item, _pip_item(req.id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="build_command",
                mechanism="esphome_validate", evidence="esphome",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is False
        assert any("self-certified" in reason for reason in validations[0].reasons)


class TestCase5NoControlledObservableRouteFails:
    """5: a capability declared by the LLM but for which ADC has no
    controlled/observable route -- FAIL, both when the identity itself
    is untrusted and when it is trusted but state="unavailable"."""

    def test_fails_when_declared_capability_has_no_trusted_evidence(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        item = _fake_item(req.id, "cargo", "cargo_test")
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(item,),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism="cargo_test", evidence="cargo",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        # No Project Intelligence at all: no independent evidence exists.
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is False

    def test_fails_when_trusted_but_unavailable(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        item = _fake_item(req.id, "pytest", "pytest", state="unavailable")
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(item,),
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


class TestCase6StateAloneNeverProvesControllability:
    """6: state merely not equal to "unavailable", without POSITIVE
    (independently trusted) capability evidence, must NOT automatically
    prove controllability -- a needs_install item with an untrusted
    identity still fails."""

    def test_needs_install_without_trusted_evidence_still_fails(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        item = _fake_item(req.id, "totally_untrusted_tool", "pytest", state="needs_install")
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(item,),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism="pytest", evidence="totally_untrusted_tool",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        # Even with SOME unrelated trusted evidence present, this
        # specific identity/mechanism pair is never corroborated.
        validations = validate_candidates(
            result, preflight=preflight, trusted_verification_groups=_trusted_groups(test_systems=["jest"]),
        )
        assert validations[0].admissible is False


class TestCase7And8ManualReviewGovernance:
    """7: manual_review with human_governed=True but no actual governed
    ADC human-verification path -- FAIL (human_governed is itself a
    candidate self-declaration, not independent evidence).
    8: manual_review bound to an actual existing governed human path --
    PASS."""

    @staticmethod
    def _manual_variant(req_id):
        manual_item = ToolchainItem(
            requirement_ref=req_id, name="manual-checklist-step",
            type="capability", state="already_installed",
        )
        return CouncilVariant(
            id="v1", name="v1", toolchain=(manual_item, _pip_item(req_id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req_id,), kind="manual_review",
                mechanism="manual_review", evidence=req_id, human_governed=True,
            ),),
        )

    def test_case_7_human_governed_flag_alone_is_not_enough(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        variant = self._manual_variant(req.id)
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        # No governed_manual_verification_ids supplied at all -- the
        # honest, fail-closed production default (see the module note in
        # app.engineering_decision.validate_variants()).
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is False

    def test_case_7_human_governed_flag_for_a_different_requirement_is_not_enough(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        variant = self._manual_variant(req.id)
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(
            result, preflight=preflight,
            governed_manual_verification_ids=frozenset({"some-other-requirement"}),
        )
        assert validations[0].admissible is False

    def test_case_8_bound_to_an_actual_governed_path_passes(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        variant = self._manual_variant(req.id)
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(
            result, preflight=preflight,
            governed_manual_verification_ids=frozenset({req.id}),
        )
        assert validations[0].admissible is True


class TestGeneralizedBadLLMSelfCertificationClass:
    """9: LLM->S2 regression principle -- a CLASS of self-certification
    attempts (not just one exact technology string) must always fail
    closed, across ecosystems and shapes."""

    @pytest.mark.parametrize("technical_identity, mechanism", [
        ("jest", "pytest"),        # real Node identity, false Python claim
        ("pytest", "jest"),        # real Python identity, false Node claim
        ("ctest", "esphome_check"),  # real CMake identity, false firmware claim
        ("esphome", "ctest"),      # real firmware identity, false CMake claim
        ("made_up_thing", "made_up_thing"),  # nothing real at all
        ("pytest", ""),            # blank mechanism
    ])
    def test_self_certified_mismatches_never_pass(self, technical_identity, mechanism):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        item = _fake_item(req.id, technical_identity, mechanism or "placeholder")
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(item,),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism=mechanism, evidence=technical_identity,
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        # Every real, independently-detectable identity used above is
        # granted trust for ITSELF -- proving the failure is specifically
        # the cross-wiring/self-certification, not merely absent evidence.
        validations = validate_candidates(
            result, preflight=preflight,
            trusted_verification_groups=_trusted_groups(
                test_systems=["jest", "pytest", "ctest"], firmware_indicators=["esphome"],
            ),
        )
        assert validations[0].admissible is False, (technical_identity, mechanism)

    def test_categorize_admissibility_reasons_still_maps_to_verification_coverage(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        item = _fake_item(req.id, "jest", "pytest")
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(item, _pip_item(req.id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism="pytest", evidence="jest",
            ),),
        )
        validation = validate_variants((variant,), preflight=preflight)[0]
        assert categorize_admissibility_reasons(validation.reasons) == "verification_coverage"


class TestNoRustGoDetectionYet:
    """Honest, documented boundary (CLAUDE-ARCH-S2-013G): Project
    Intelligence does not yet detect Rust/Go projects, so cargo_test/
    go_test -- still valid, technology-neutral mechanism tokens in the
    S2 vocabulary -- currently have NO independent trusted evidence to
    corroborate against. Fail-closed is the CORRECT behavior here, not a
    defect: absence of independent evidence is never treated as
    permission. A future task extending Project Intelligence's detection
    to Rust/Go closes this without any change to app.engineering_decision."""

    @pytest.mark.parametrize("mechanism, technical_identity", [
        ("cargo_test", "cargo"), ("go_test", "go"),
    ])
    def test_rust_go_mechanisms_currently_always_fail_closed(self, mechanism, technical_identity):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        item = _fake_item(req.id, technical_identity, mechanism)
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(item,),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism=mechanism, evidence=technical_identity,
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        # Even generously granting every OTHER ecosystem's trust, Rust/Go
        # still has nothing to point to.
        validations = validate_candidates(
            result, preflight=preflight,
            trusted_verification_groups=_trusted_groups(
                test_systems=["pytest", "jest", "ctest"], firmware_indicators=["esphome"],
            ),
        )
        assert validations[0].admissible is False


class TestCase10ProductiveBoundaryProven:
    """10: the productive S2.2 -> S2.3 -> S2.4 boundary genuinely
    threads independent Project Intelligence evidence end-to-end through
    app.dev_workflow.DevelopmentWorkflow.run() -- not just through direct
    unit calls to validate_variants()/validate_candidates()."""

    @staticmethod
    def _workflow_with(council_result, preflight_result):
        from unittest.mock import MagicMock

        from app.ai_requirement_discovery import AIRequirementDiscovery
        from app.dev_workflow import DevelopmentWorkflow
        from app.engineering_council import EngineeringCouncil
        from app.requirement_model import DiscoveryResult, ValidationResult
        from app.requirement_preflight import RequirementPreflight
        from app.requirement_validator import RequirementValidator
        from app.toolchain_materializer import ToolchainMaterializer

        req = preflight_result.missing_requirements[0]
        discovery = MagicMock(spec=AIRequirementDiscovery)
        discovery.discover.return_value = DiscoveryResult(
            id="disc-1", source="test", project_id="proj-1",
            requirements=(req,), activations=(), warnings=(),
        )
        validator = MagicMock(spec=RequirementValidator)
        validator.validate.return_value = ValidationResult(
            id="val-1", valid=True, requirements=(req,), errors=(), warnings=(),
            normalized_requirements=(req,), activations=(),
        )
        preflight = MagicMock(spec=RequirementPreflight)
        preflight.check.return_value = preflight_result
        council = MagicMock(spec=EngineeringCouncil)
        council.evaluate.return_value = council_result
        materializer = MagicMock(spec=ToolchainMaterializer)

        return DevelopmentWorkflow(
            discovery, validator, preflight, None,
            council=council, materializer=materializer,
        )

    def test_run_becomes_admissible_only_when_matching_project_intelligence_flows_through(self):
        from app.project_intelligence import (
            DetectedTestSystem, ProjectIntelligence,
        )

        req = _requirement_needing_verification()
        preflight_result = _binding_preflight(req)
        item = _fake_item(req.id, "pytest", "pytest")
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(item, _pip_item(req.id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism="pytest", evidence="pytest",
            ),),
        )
        council_result = CouncilResult(
            id="c1", project_id="proj-1", variants=(variant,),
            recommendation="v1", council_complete=True,
        )

        # Without project_intelligence: fails closed even though this is
        # otherwise a perfectly legitimate pytest candidate -- the sole
        # candidate becomes inadmissible, so run() raises exactly as it
        # would for any other zero-admissible-candidate outcome.
        from app.engineering_decision import NoEligibleEngineeringCandidateError

        workflow_without = self._workflow_with(council_result, preflight_result)
        with pytest.raises(NoEligibleEngineeringCandidateError):
            workflow_without.run({"name": "proj"}, "proj-1")

        # With a REAL ProjectIntelligence independently confirming pytest:
        # becomes admissible and selectable, through the SAME productive
        # run() call, with no direct call to validate_variants() at all.
        intelligence = ProjectIntelligence(
            project_root="/tmp/proj", project_kind="existing", areas=(),
            languages=(), frameworks=(), package_systems=(),
            build_systems=(), test_systems=(DetectedTestSystem("pytest", ()),),
            firmware_indicators=(), ci_indicators=(), doc_indicators=(),
            git_repository_present=True, sensitive_configuration_present=False,
            warnings=(), truncated=False, total_files_traversed=1,
            total_files_excluded=0, inspection_limit_exceeded=False,
        )
        workflow_with = self._workflow_with(council_result, preflight_result)
        result_with = workflow_with.run(
            {"name": "proj"}, "proj-1", project_intelligence=intelligence,
        )
        assert result_with.engineering_selection is not None
        assert result_with.engineering_selection.selected_variant_id == "v1"

    def test_resolve_engineering_selection_reuses_the_persisted_project_intelligence(self):
        """The resume path (web_api.py's own /engineering-decision
        endpoint calls DevelopmentWorkflow.resolve_engineering_selection())
        must recompute S2.3 admissibility with the SAME independent
        evidence the initial run() call had -- proven directly here at
        the DevelopmentWorkflow level, without needing a live web server."""
        from app.project_intelligence import DetectedTestSystem, ProjectIntelligence

        req = _requirement_needing_verification()
        preflight_result = _binding_preflight(req)
        item = _fake_item(req.id, "pytest", "pytest")
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(item, _pip_item(req.id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism="pytest", evidence="pytest",
            ),),
        )
        council_result = CouncilResult(
            id="c1", project_id="proj-1", variants=(variant,),
            recommendation="v1", council_complete=True,
        )
        intelligence = ProjectIntelligence(
            project_root="/tmp/proj", project_kind="existing", areas=(),
            languages=(), frameworks=(), package_systems=(),
            build_systems=(), test_systems=(DetectedTestSystem("pytest", ()),),
            firmware_indicators=(), ci_indicators=(), doc_indicators=(),
            git_repository_present=True, sensitive_configuration_present=False,
            warnings=(), truncated=False, total_files_traversed=1,
            total_files_excluded=0, inspection_limit_exceeded=False,
        )
        workflow = self._workflow_with(council_result, preflight_result)
        initial = workflow.run(
            {"name": "proj"}, "proj-1", project_intelligence=intelligence,
        )
        resumed = workflow.resolve_engineering_selection(
            council_result, preflight_result, "linux", "proj-1",
            human_selected_variant_id="v1",
            project_intelligence=initial.project_intelligence,
        )
        assert resumed.setup_plan is not None
