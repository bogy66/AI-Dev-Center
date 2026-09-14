"""CLAUDE-ARCH-S2-013F: closes the residual mechanical gap left by
CLAUDE-ARCH-S2-013E's independent review.

013E proved verification coverage was structured, linked to binding
requirements, and grounded in candidate-local toolchain evidence -- but
it did NOT prove that the declared mechanism was actually COMPATIBLE
with the referenced toolchain identity, nor that ADC could control/
observe the result. A structurally valid but ecosystem-mismatched pair
such as (mechanism="pytest", evidence=<a real npm ToolchainItem's
identity>) was previously accepted; it must not be.

RED-before-fix evidence: every test in TestCrossToolchainMismatchFails
below failed against the pre-013F code (mechanical compatibility was not
checked at all -- any structured mechanism token plus any candidate-
local toolchain identity was accepted), confirmed before implementing
ToolchainItem.provides_verification / VerificationCoverage.human_governed
(see the completion report, R4).
"""
import pytest

from app.council_models import CouncilResult, CouncilVariant, ToolchainItem, VerificationCoverage
from app.engineering_decision import (
    EngineeringReworkRequest,
    categorize_admissibility_reasons,
    validate_candidates,
    validate_variants,
)

from tests.test_engineering_decision import (
    _binding_preflight,
    _multi_requirement_preflight,
    _requirement_needing_verification,
    _trusted_groups,
)


def _py_item(req_id, name="pytest", technical_identity="pytest",
             provides=("pytest",), state="needs_install"):
    return ToolchainItem(
        requirement_ref=req_id, name=name, type="python_package",
        technical_identity=technical_identity, install_method="pip",
        state=state, provides_verification=provides,
    )


def _npm_item(req_id, name="npm", technical_identity="npm_test",
              provides=("npm_test",), state="needs_install"):
    # CLAUDE-ARCH-S2-013G: technical_identity is the identity Project
    # Intelligence would need to have independently detected for this
    # item's claimed mechanism to be trusted (see _trusted_groups()) --
    # `name` stays the human-facing "npm" label the coverage.evidence
    # fields below still resolve against.
    return ToolchainItem(
        requirement_ref=req_id, name=name, type="executable",
        technical_identity=technical_identity, provides_verification=provides,
        state=state,
    )


def _cargo_item(req_id, provides=("cargo_test",), state="needs_install"):
    return ToolchainItem(
        requirement_ref=req_id, name="cargo", type="executable",
        technical_identity="cargo", provides_verification=provides, state=state,
    )


def _esphome_item(req_id, provides=("esphome_check",), state="needs_install"):
    return ToolchainItem(
        requirement_ref=req_id, name="esphome", type="executable",
        technical_identity="esphome_check", provides_verification=provides, state=state,
    )


def _cmake_item(req_id, provides=("cmake",), state="needs_install"):
    return ToolchainItem(
        requirement_ref=req_id, name="cmake", type="executable",
        technical_identity="cmake", provides_verification=provides, state=state,
    )


def _covering_item(req_id):
    """CLAUDE-ARCH-S2-014C (F4): a DEDICATED item that semantically
    satisfies the binding Requirement itself (type=python_package,
    technical_identity="esphome", matching _requirement_needing_
    verification()'s own fixed name="esphome") -- separate from
    whichever item below provides VERIFICATION evidence. Before F4, one
    item (_py_item/_npm_item/etc.) was overloaded to both cover the
    binding requirement (via requirement_ref alone) AND provide
    verification evidence; F4 now correctly rejects that overload
    whenever the verification tool's own identity (pytest, npm, cargo,
    cmake, ...) is not ALSO a semantically valid distribution for the
    "esphome" requirement -- exactly the phantom-coverage-by-convenience
    shape F4 closes."""
    return ToolchainItem(
        requirement_ref=req_id, name="esphome-package", type="python_package",
        technical_identity="esphome",
    )


class TestCrossToolchainMismatchFails:
    """A-D: a structured mechanism token plus SOME candidate-local
    toolchain identity is not enough -- the identity must actually
    declare it can run that exact mechanism."""

    def test_case_a_pytest_with_only_npm_capability_fails(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(_npm_item(req.id), _covering_item(req.id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism="pytest", evidence="npm",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is False
        assert "missing required verification coverage" in validations[0].reasons[0]

    def test_case_b_npm_test_with_only_python_capability_fails(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(_py_item(req.id), _covering_item(req.id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism="npm_test", evidence="pytest",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is False

    def test_case_c_cargo_test_with_unrelated_toolchain_fails(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(_py_item(req.id), _covering_item(req.id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism="cargo_test", evidence="pytest",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is False

    def test_case_d_invented_mechanism_token_with_valid_unrelated_evidence_fails(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(_py_item(req.id), _covering_item(req.id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism="totally_fake_test_runner", evidence="pytest",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is False


class TestMatchingToolchainPasses:
    """E-H: a mechanism that the referenced toolchain identity actually
    declares it can run is accepted, across ecosystems."""

    def test_case_e_pytest_matches_python_capability(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(_py_item(req.id), _covering_item(req.id)),
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

    def test_case_f_python_unittest_matches_unittest_capability(self):
        """F: a DIFFERENT real, registered controlled runner
        (python_unittest -- see app.verification.PythonUnittestRunner)
        than pytest, proving the check is not pytest-special-cased.
        npm_test/Node has NO registered controlled runner at all today
        (RUNNER_MAP marks jest/vitest/mocha "deferred") -- see
        TestControlledCapabilityRequired for that exact RED evidence,
        CLAUDE-ARCH-S2-014C (F2)."""
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        unittest_item = ToolchainItem(
            requirement_ref=req.id, name="unittest", type="executable",
            technical_identity="unittest", provides_verification=("python_unittest",),
        )
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(unittest_item, _covering_item(req.id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism="python_unittest", evidence="unittest",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        assert validate_candidates(
            result, preflight=preflight, trusted_verification_groups=_trusted_groups(test_systems=["unittest"]),
        )[0].admissible is True

    def test_case_g_esphome_validate_matches_esphome_capability(self):
        req = _requirement_needing_verification("req-esphome-fw")
        preflight = _binding_preflight(req)
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(_esphome_item(req.id), _covering_item(req.id)),
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

    def test_case_h_ctest_matches_cmake_build_capability(self):
        """H: cmake -- ctest itself is "deferred" (no registered runner
        yet), but cmake's OWN build_command route IS controlled
        (CMakeRunner is registered) -- CLAUDE-ARCH-S2-014C (F2)."""
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(_cmake_item(req.id), _covering_item(req.id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="build_command",
                mechanism="cmake", evidence="cmake",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        assert validate_candidates(
            result, preflight=preflight, trusted_verification_groups=_trusted_groups(build_systems=["cmake"]),
        )[0].admissible is True


class TestControllabilityObservability:
    def test_case_i_unavailable_backing_tool_cannot_be_controlled_or_observed(self):
        """I: mechanism/evidence structurally compatible, but the backing
        ToolchainItem is state="unavailable" -- ADC cannot obtain it, so
        it cannot control/observe the result."""
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(_py_item(req.id, state="unavailable"), _covering_item(req.id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism="pytest", evidence="pytest",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        assert validate_candidates(result, preflight=preflight)[0].admissible is False

    def test_case_j_manual_review_without_governance_evidence_fails(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        manual_item = ToolchainItem(
            requirement_ref=req.id, name="manual-checklist-step",
            type="capability", state="already_installed",
        )
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(manual_item, _covering_item(req.id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="manual_review",
                mechanism="manual_review", evidence=req.id, human_governed=False,
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        assert validate_candidates(result, preflight=preflight)[0].admissible is False

    def test_case_k_manual_review_with_explicit_governance_passes(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        manual_item = ToolchainItem(
            requirement_ref=req.id, name="manual-checklist-step",
            type="capability", state="already_installed",
        )
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(manual_item, _covering_item(req.id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="manual_review",
                mechanism="manual_review", evidence=req.id, human_governed=True,
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        assert validate_candidates(
            result, preflight=preflight, governed_manual_verification_ids=frozenset({req.id}),
        )[0].admissible is True


class TestMultiToolchainBinding:
    @staticmethod
    def _unittest_item(req_id):
        return ToolchainItem(
            requirement_ref=req_id, name="unittest", type="executable",
            technical_identity="unittest", provides_verification=("python_unittest",),
        )

    def test_case_l_each_mechanism_must_bind_the_correct_capability(self):
        """L: a mixed candidate declares BOTH a pytest and a unittest
        capability; pytest must bind to the pytest item and
        python_unittest to the unittest item -- cross-wiring must fail
        even though both identities exist somewhere on the candidate."""
        req_py = _requirement_needing_verification("req-py")
        req_ut = _requirement_needing_verification("req-ut")
        preflight = _multi_requirement_preflight(req_py, req_ut)
        variant = CouncilVariant(
            id="v1", name="v1",
            toolchain=(_py_item(req_py.id), self._unittest_item(req_ut.id)),
            verification_coverage=(
                VerificationCoverage(
                    requirement_refs=(req_py.id,), kind="test_command",
                    mechanism="pytest", evidence="unittest",  # WRONG binding
                ),
                VerificationCoverage(
                    requirement_refs=(req_ut.id,), kind="test_command",
                    mechanism="python_unittest", evidence="pytest",  # WRONG binding
                ),
            ),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is False

    def test_case_l_correct_binding_passes(self):
        req_py = _requirement_needing_verification("req-py")
        req_ut = _requirement_needing_verification("req-ut")
        preflight = _multi_requirement_preflight(req_py, req_ut)
        variant = CouncilVariant(
            id="v1", name="v1",
            toolchain=(
                _py_item(req_py.id), self._unittest_item(req_ut.id),
                _covering_item(req_py.id), _covering_item(req_ut.id),
            ),
            verification_coverage=(
                VerificationCoverage(
                    requirement_refs=(req_py.id,), kind="test_command",
                    mechanism="pytest", evidence="pytest",
                ),
                VerificationCoverage(
                    requirement_refs=(req_ut.id,), kind="test_command",
                    mechanism="python_unittest", evidence="unittest",
                ),
            ),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        assert validate_candidates(
            result, preflight=preflight,
            trusted_verification_groups=_trusted_groups(test_systems=["pytest", "unittest"]),
        )[0].admissible is True

    def test_case_m_one_requirement_without_compatible_route_stays_inadmissible(self):
        req_py = _requirement_needing_verification("req-py")
        req_ut = _requirement_needing_verification("req-ut")
        preflight = _multi_requirement_preflight(req_py, req_ut)
        variant = CouncilVariant(
            id="v1", name="v1",
            toolchain=(
                _py_item(req_py.id), self._unittest_item(req_ut.id),
                _covering_item(req_py.id), _covering_item(req_ut.id),
            ),
            verification_coverage=(
                VerificationCoverage(
                    requirement_refs=(req_py.id,), kind="test_command",
                    mechanism="pytest", evidence="pytest",
                ),
                # req_ut is left without ANY coverage.
            ),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(
            result, preflight=preflight, trusted_verification_groups=_trusted_groups(test_systems=["pytest"]),
        )
        assert validations[0].admissible is False
        assert "req-ut" in validations[0].reasons[0]
        assert "req-py" not in validations[0].reasons[0]


class TestRepairEvidenceAndS5Boundary:
    def test_case_n_repair_evidence_identifies_compatibility_reason(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(
            id="merged-host-venv", name="v1", toolchain=(_npm_item(req.id), _covering_item(req.id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism="pytest", evidence="npm",
            ),),
        )
        validation = validate_variants((variant,), preflight=preflight)[0]
        assert validation.admissible is False
        rework = EngineeringReworkRequest.from_validation(validation)
        assert rework.reason_codes == ("verification_coverage",)
        assert req.id in " ".join(rework.verification_feasibility_gap_ids)

    def test_case_n_repair_with_corrected_compatible_evidence_becomes_admissible(self):
        """The SAME S2.3 function, called again with corrected,
        compatible evidence, becomes admissible -- proving a repair
        corrects data rather than S2.3 being weakened."""
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        broken = CouncilVariant(
            id="v1", name="v1", toolchain=(_cmake_item(req.id), _covering_item(req.id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="build_command",
                mechanism="pytest", evidence="cmake",
            ),),
        )
        assert validate_variants((broken,), preflight=preflight)[0].admissible is False

        repaired = CouncilVariant(
            id="v1", name="v1", toolchain=(_cmake_item(req.id), _covering_item(req.id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="build_command",
                mechanism="cmake", evidence="cmake",
            ),),
        )
        assert validate_variants(
            (repaired,), preflight=preflight,
            trusted_verification_groups=_trusted_groups(build_systems=["cmake"]),
        )[0].admissible is True

    def test_case_o_s2_3_still_executes_nothing(self):
        import inspect
        import app.engineering_decision as ed_module
        source = inspect.getsource(ed_module)
        assert "subprocess" not in source
        assert "app.verification" not in source
        assert "app.testing_stage" not in source


class TestGeneralizedMalformedVerificationClaims:
    """LLM->S2 regression principle: cover a CLASS of malformed claims,
    not only one exact technology string."""

    @pytest.mark.parametrize("mechanism, wrong_evidence_identity", [
        ("pytest", "npm"),
        ("npm_test", "cargo"),
        ("cargo_test", "cmake"),
        ("go_test", "pytest"),
        ("ctest", "esphome"),
        ("esphome_validate", "go"),
        ("made_up_runner_xyz", "pytest"),
        ("", "pytest"),
    ])
    def test_mismatched_or_malformed_claims_never_pass(self, mechanism, wrong_evidence_identity):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        item = ToolchainItem(
            requirement_ref=req.id, name=wrong_evidence_identity, type="executable",
            technical_identity=wrong_evidence_identity,
            provides_verification=(wrong_evidence_identity + "_own_mechanism",),
        )
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(item,),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism=mechanism, evidence=wrong_evidence_identity,
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        assert validate_candidates(result, preflight=preflight)[0].admissible is False

    def test_categorize_admissibility_reasons_still_maps_to_verification_coverage(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(_npm_item(req.id), _covering_item(req.id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism="pytest", evidence="npm",
            ),),
        )
        validation = validate_variants((variant,), preflight=preflight)[0]
        assert categorize_admissibility_reasons(validation.reasons) == "verification_coverage"
