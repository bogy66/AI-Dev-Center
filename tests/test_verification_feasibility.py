"""CLAUDE-ARCH-S2-013E: S2.3 Verification Feasibility.

Closes the LOW-MEDIUM finding from CLAUDE-ARCH-S2-013A: S2.3's prior
verification-coverage check (CLAUDE-ARCH-S2-012B, Gate E) was satisfied by
ANY non-empty CouncilVariant.verification free text (e.g. "run tests"),
without any structured evidence that ADC actually has a meaningful,
recognizable, controllable verification mechanism for the candidate.

RED-before-fix evidence for this exact weakness is captured in
test_case_a_vague_free_text_alone_is_not_sufficient below, and was
confirmed failing against the pre-013E code (see completion report R4).

S2.3 answers ONLY "can this be verified in a controlled, meaningful way?"
-- it never executes verification itself; S5 (Quality & Verification)
remains solely responsible for actually running/assessing it.
"""
import pytest

from app.council_models import CouncilResult, CouncilVariant, ToolchainItem, VerificationCoverage
from app.engineering_decision import (
    EngineeringReworkRequest,
    NoEligibleEngineeringCandidateError,
    categorize_admissibility_reasons,
    select_engineering_variant,
    validate_candidates,
    validate_variants,
)

from tests.test_engineering_decision import (
    _binding_preflight,
    _multi_requirement_preflight,
    _pip_item,
    _requirement,
    _requirement_needing_verification,
    _trusted_groups,
)


def _covered_item(req_id, name="pytest", technical_identity="pytest"):
    return _pip_item(req_id)  # already-admissible toolchain item for req_id


def _pytest_evidence_item(req_id):
    """CLAUDE-ARCH-S2-014C (F4): a DEDICATED toolchain item for pytest
    verification evidence -- never the SAME item _pip_item() returns for
    covering the binding requirement itself. _pip_item()'s own identity
    must semantically match the Requirement it covers (F4); overloading
    that same item's technical_identity to "pytest" would satisfy 013G's
    mechanism-compatibility check while failing F4's, since one identity
    cannot simultaneously mean two different real packages."""
    return ToolchainItem(
        requirement_ref=req_id, name="pytest", type="executable",
        technical_identity="pytest", provides_verification=("pytest",),
    )


class TestVerificationFeasibilityCases:
    """A-J: the exact required RED/GREEN case matrix."""

    def test_case_a_vague_free_text_alone_is_not_sufficient(self):
        """A: a binding requirement expects verification, but the
        candidate only contains vague non-empty free text -- must NOT be
        considered sufficiently covered, even though the old (012B)
        contract would have accepted it."""
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(_pip_item(req.id),),
            verification="run tests",  # free text only, no structured coverage
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is False
        assert "missing required verification coverage" in validations[0].reasons[0]
        assert "req-esphome" in validations[0].reasons[0]

    def test_case_b_unsupported_mechanism_claim_fails(self):
        """B: verification_coverage exists but its evidence references
        something that is NOT actually present on the candidate's own
        toolchain/project evidence -- must fail feasibility."""
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(_pip_item(req.id),),
            verification_coverage=(
                VerificationCoverage(
                    requirement_refs=(req.id,), kind="test_command",
                    mechanism="cargo_test", evidence="cargo",  # "cargo" not on toolchain
                ),
            ),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is False
        assert "missing required verification coverage" in validations[0].reasons[0]

    def test_case_c_supported_mechanism_with_grounded_evidence_passes(self):
        """C: verification_coverage references a controlled mechanism
        whose evidence names a real, already-present toolchain identity
        -- may pass."""
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(_pip_item(req.id), _pytest_evidence_item(req.id)),
            verification_coverage=(
                VerificationCoverage(
                    requirement_refs=(req.id,), kind="test_command",
                    mechanism="pytest", evidence="pytest",
                ),
            ),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(
            result, preflight=preflight, trusted_verification_groups=_trusted_groups(test_systems=["pytest"]),
        )
        assert validations[0].admissible is True

    def test_case_d_already_satisfied_requirement_creates_no_obligation(self):
        """D: a requirement already satisfied by preflight (not binding)
        must not create a new verification obligation."""
        req = _requirement_needing_verification()
        # No _binding_preflight() -- nothing missing, nothing binding.
        from app.requirement_model import (
            PreflightRequirementResult, PreflightResult, RequirementActivation,
        )
        preflight = PreflightResult(
            id="pre-1", project_id="proj", overall_ready=True,
            results=(PreflightRequirementResult(
                requirement_id=req.id, present=True, satisfied=True,
            ),),
            missing_requirements=(), already_installed=(req,),
            activations=(RequirementActivation(req.id, True, True),),
        )
        variant = CouncilVariant(id="v1", name="v1", toolchain=())
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is True
        assert validations[0].reasons == ()

    def test_case_e_one_mechanism_covers_multiple_requirements(self):
        """E: one verification mechanism may cover multiple binding
        requirements when coverage is explicitly evidenced."""
        req_a = _requirement_needing_verification("req-a")
        req_b = _requirement_needing_verification("req-b")
        preflight = _multi_requirement_preflight(req_a, req_b)
        variant = CouncilVariant(
            id="v1", name="v1",
            toolchain=(_pip_item(req_a.id), _pip_item(req_b.id), _pytest_evidence_item(req_a.id)),
            verification_coverage=(
                VerificationCoverage(
                    requirement_refs=(req_a.id, req_b.id), kind="test_command",
                    mechanism="pytest", evidence="pytest",
                ),
            ),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(
            result, preflight=preflight, trusted_verification_groups=_trusted_groups(test_systems=["pytest"]),
        )
        assert validations[0].admissible is True

    def test_case_f_multiple_mechanisms_jointly_cover_one_candidate(self):
        """F: multiple verification mechanisms may jointly cover one
        candidate's several binding requirements."""
        from app.council_models import ToolchainItem
        req_a = _requirement_needing_verification("req-a")
        req_b = _requirement_needing_verification("req-b")
        preflight = _multi_requirement_preflight(req_a, req_b)
        cmake_item = ToolchainItem(
            requirement_ref=req_b.id, name="cmake", type="executable",
            technical_identity="cmake", provides_verification=("cmake",),
        )
        variant = CouncilVariant(
            id="v1", name="v1",
            toolchain=(
                _pip_item(req_a.id), _pytest_evidence_item(req_a.id),
                _pip_item(req_b.id), cmake_item,
            ),
            verification_coverage=(
                VerificationCoverage(
                    requirement_refs=(req_a.id,), kind="test_command",
                    mechanism="pytest", evidence="pytest",
                ),
                VerificationCoverage(
                    requirement_refs=(req_b.id,), kind="build_command",
                    mechanism="cmake", evidence="cmake",
                ),
            ),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(
            result, preflight=preflight,
            trusted_verification_groups=_trusted_groups(test_systems=["pytest"], build_systems=["cmake"]),
        )
        assert validations[0].admissible is True

    def test_case_g_missing_coverage_for_one_requirement_is_not_hidden(self):
        """G: unrelated verification text/coverage for ONE requirement
        must not hide missing coverage for ANOTHER binding requirement."""
        req_a = _requirement_needing_verification("req-a")
        req_b = _requirement_needing_verification("req-b")
        preflight = _multi_requirement_preflight(req_a, req_b)
        variant = CouncilVariant(
            id="v1", name="v1",
            toolchain=(_pip_item(req_a.id), _pytest_evidence_item(req_a.id), _pip_item(req_b.id)),
            verification_coverage=(
                VerificationCoverage(
                    requirement_refs=(req_a.id,), kind="test_command",
                    mechanism="pytest", evidence="pytest",
                ),
                # req_b is left uncovered.
            ),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(
            result, preflight=preflight, trusted_verification_groups=_trusted_groups(test_systems=["pytest"]),
        )
        assert validations[0].admissible is False
        assert "req-b" in validations[0].reasons[0]
        assert "req-a" not in validations[0].reasons[0]

    def test_case_h_free_form_explanatory_text_alone_never_creates_coverage(self):
        """H: a verification_coverage entry with an unrecognized kind or
        an evidence value that is just prose (not a structured identity)
        must not mechanically create coverage."""
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(_pip_item(req.id),),
            verification_coverage=(
                VerificationCoverage(
                    requirement_refs=(req.id,), kind="test_command",
                    mechanism="pytest",
                    evidence="we will run the test suite manually before release",
                ),
            ),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is False

    def test_case_i_technology_neutral_across_ecosystems(self):
        """I: the rule is technology-neutral -- non-Python mechanisms
        with grounded evidence pass exactly like pytest does, as long as
        Project Intelligence has independently detected the SAME
        capability AND that capability has an actual controlled,
        registered execution route (CLAUDE-ARCH-S2-013G/014C -- see
        app.verification.trusted_verification_identity_groups()'s own
        policy=="controlled_execution" gate). Uses ecosystems that are
        BOTH detectable AND controlled today: CMake/cmake (build,
        CMakeRunner registered) and ESPHome (firmware, ESPHomeCheckRunner
        registered). jest/ctest/vitest/mocha/make are all deliberately
        "deferred" in RUNNER_MAP/BUILD_RUNNER_MAP (no registered runner
        exists for them yet), so they correctly NEVER pass this check --
        see TestControlledCapabilityRequired below for that exact RED
        evidence. cargo_test/go_test remain valid, technology-neutral
        mechanism tokens in the vocabulary, but Project Intelligence does
        not yet detect Rust/Go projects at all, so those two currently
        have no independent trusted evidence to corroborate against -- an
        explicit, honest, fail-closed limitation (see
        tests/test_verification_feasibility_trust.py::
        TestNoRustGoDetectionYet), not a defect of this check."""
        from app.council_models import ToolchainItem
        for mechanism, technical_identity, trust_kwargs in (
            ("cmake", "cmake", {"build_systems": ["cmake"]}),
            ("esphome_check", "esphome", {"firmware_indicators": ["esphome"]}),
        ):
            req = _requirement_needing_verification()
            preflight = _binding_preflight(req)
            item = ToolchainItem(
                requirement_ref=req.id, name=technical_identity,
                type="executable", technical_identity=technical_identity,
                provides_verification=(mechanism,),
            )
            variant = CouncilVariant(
                id="v1", name="v1", toolchain=(item, _pip_item(req.id)),
                verification_coverage=(
                    VerificationCoverage(
                        requirement_refs=(req.id,), kind="build_command",
                        mechanism=mechanism, evidence=technical_identity,
                    ),
                ),
            )
            result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                    recommendation="v1", council_complete=True)
            validations = validate_candidates(
                result, preflight=preflight, trusted_verification_groups=_trusted_groups(**trust_kwargs),
            )
            assert validations[0].admissible is True, mechanism

    def test_case_j_s2_3_never_executes_anything(self):
        """J: validate_variants()/validate_candidates() are pure
        functions over already-structured data -- no subprocess, no I/O,
        no S5 call. Verified by inspecting the module source for the
        absence of any execution primitive in the verification-
        feasibility code path."""
        import inspect

        import app.engineering_decision as ed_module

        source = inspect.getsource(ed_module)
        assert "subprocess" not in source
        assert "app.verification" not in source
        assert "app.testing_stage" not in source


class TestVerificationFeasibilityRepresentativeCandidates:
    """The 10 required representative regression candidates."""

    def test_1_python_pytest_project(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(
            id="v1", name="python-pytest", toolchain=(_pip_item(req.id), _pytest_evidence_item(req.id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism="pytest", evidence="pytest",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        assert validate_candidates(
            result, preflight=preflight, trusted_verification_groups=_trusted_groups(test_systems=["pytest"]),
        )[0].admissible is True

    def test_2_javascript_node_project(self):
        """CLAUDE-ARCH-S2-014C (F2): jest is independently DETECTABLE
        (Project Intelligence recognizes it) but has NO registered
        controlled runner anywhere in app.verification's
        build_default_registry() -- RUNNER_MAP marks it "deferred", never
        "controlled_execution". Recognition/name-mapping alone is not
        capability proof, so this candidate correctly stays inadmissible
        until a real, controlled Node test runner is registered; this is
        F2's own mandatory RED case 2, not a defect of this test."""
        from app.council_models import ToolchainItem
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        item = ToolchainItem(
            requirement_ref=req.id, name="npm", type="executable",
            technical_identity="jest", provides_verification=("jest",),
        )
        variant = CouncilVariant(
            id="v1", name="node-npm-test", toolchain=(_pip_item(req.id), item),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism="jest", evidence="jest",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        assert validate_candidates(
            result, preflight=preflight, trusted_verification_groups=_trusted_groups(test_systems=["jest"]),
        )[0].admissible is False

    def test_3_compiled_embedded_toolchain_candidate(self):
        from app.council_models import ToolchainItem
        req = _requirement_needing_verification("req-esphome-fw")
        preflight = _binding_preflight(req)
        item = ToolchainItem(
            requirement_ref=req.id, name="esphome", type="executable",
            technical_identity="esphome",
            provides_verification=("esphome_check",),
        )
        variant = CouncilVariant(
            id="v1", name="esphome-firmware", toolchain=(item, _pip_item(req.id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="build_command",
                mechanism="esphome_check", evidence="esphome",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        assert validate_candidates(
            result, preflight=preflight,
            trusted_verification_groups=_trusted_groups(firmware_indicators=["esphome"]),
        )[0].admissible is True

    def test_4_unsupported_verification_claim(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(_pip_item(req.id),),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism="cargo_test", evidence="cargo",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        assert validate_candidates(result, preflight=preflight)[0].admissible is False

    def test_5_vague_free_text_only(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(_pip_item(req.id),),
            verification="we will verify this later",
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        assert validate_candidates(result, preflight=preflight)[0].admissible is False

    def test_6_mixed_multi_toolchain_project(self):
        """Mixed-ecosystem candidate: Python/pytest (test_command) AND
        CMake/cmake (build_command) -- both have an actual registered
        controlled runner today, unlike Node/jest (see test_2)."""
        from app.council_models import ToolchainItem
        req_py = _requirement_needing_verification("req-py")
        req_cmake = _requirement_needing_verification("req-cmake")
        preflight = _multi_requirement_preflight(req_py, req_cmake)
        cmake_item = ToolchainItem(
            requirement_ref=req_cmake.id, name="cmake", type="executable",
            technical_identity="cmake", provides_verification=("cmake",),
        )
        variant = CouncilVariant(
            id="v1", name="mixed",
            toolchain=(
                _pip_item(req_py.id), _pytest_evidence_item(req_py.id),
                _pip_item(req_cmake.id), cmake_item,
            ),
            verification_coverage=(
                VerificationCoverage(
                    requirement_refs=(req_py.id,), kind="test_command",
                    mechanism="pytest", evidence="pytest",
                ),
                VerificationCoverage(
                    requirement_refs=(req_cmake.id,), kind="build_command",
                    mechanism="cmake", evidence="cmake",
                ),
            ),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        assert validate_candidates(
            result, preflight=preflight,
            trusted_verification_groups=_trusted_groups(test_systems=["pytest"], build_systems=["cmake"]),
        )[0].admissible is True

    def test_7_already_satisfied_requirement_evidence(self):
        self.test_case = TestVerificationFeasibilityCases()
        self.test_case.test_case_d_already_satisfied_requirement_creates_no_obligation()

    def test_8_partial_requirement_coverage(self):
        self.test_case = TestVerificationFeasibilityCases()
        self.test_case.test_case_g_missing_coverage_for_one_requirement_is_not_hidden()

    def test_9_complete_requirement_coverage(self):
        self.test_case = TestVerificationFeasibilityCases()
        self.test_case.test_case_f_multiple_mechanisms_jointly_cover_one_candidate()

    def test_10_no_verification_required_by_binding_requirement(self):
        """A binding requirement with no verification_method at all never
        demands verification coverage."""
        req = _requirement()  # no verification_method
        preflight = _binding_preflight(req)
        variant = CouncilVariant(id="v1", name="v1", toolchain=(_pip_item(req.id),))
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is True
        assert validations[0].reasons == ()


class TestS2_2VerificationCoverageParsing:
    """S2.2 producer-side wiring: a real Chairman/agent JSON response's
    verification_coverage array is parsed into structured
    VerificationCoverage objects, never invented, never dropped."""

    def test_parse_verification_coverage_from_raw_json_data(self):
        from app.engineering_council import _parse_verification_coverage

        parsed = _parse_verification_coverage([
            {"requirement_refs": ["req-1", "req-2"], "kind": "test_command",
             "mechanism": "pytest", "evidence": "req-1"},
        ])
        assert parsed == (VerificationCoverage(
            requirement_refs=("req-1", "req-2"), kind="test_command",
            mechanism="pytest", evidence="req-1",
        ),)

    def test_parse_verification_coverage_defaults_to_empty_tuple(self):
        from app.engineering_council import _parse_verification_coverage

        assert _parse_verification_coverage([]) == ()
        assert _parse_verification_coverage(None) == ()


class TestVerificationFeasibilityRepairPath:
    def test_rejection_evidence_identifies_exact_verification_gap(self):
        """Rejection evidence names the affected requirement AND the
        candidate identity, suitable for the bounded S2 repair path."""
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(
            id="merged-host-venv", name="v1", toolchain=(_pip_item(req.id),),
            verification="run tests",
        )
        validation = validate_variants((variant,), preflight=preflight)[0]
        rework = EngineeringReworkRequest.from_validation(validation)
        assert rework.reason_codes == ("verification_coverage",)
        assert req.id in " ".join(rework.verification_feasibility_gap_ids)

    def test_repair_with_corrected_verification_evidence_becomes_admissible(self):
        """A repaired candidate that adds real, grounded verification
        coverage becomes admissible -- without S2.3's truth values being
        artificially altered (the SAME function, called again, simply
        evaluates NEW, now-sufficient evidence)."""
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        broken = CouncilVariant(
            id="v1", name="v1", toolchain=(_pip_item(req.id),),
            verification="run tests",
        )
        assert validate_variants((broken,), preflight=preflight)[0].admissible is False

        repaired = CouncilVariant(
            id="v1", name="v1", toolchain=(_pip_item(req.id), _pytest_evidence_item(req.id)),
            verification="run tests",
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism="pytest", evidence="pytest",
            ),),
        )
        assert validate_variants(
            (repaired,), preflight=preflight,
            trusted_verification_groups=_trusted_groups(test_systems=["pytest"]),
        )[0].admissible is True

    def test_categorize_admissibility_reasons_still_maps_to_verification_coverage(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(id="v1", name="v1", toolchain=(_pip_item(req.id),))
        validation = validate_variants((variant,), preflight=preflight)[0]
        assert categorize_admissibility_reasons(validation.reasons) == "verification_coverage"
