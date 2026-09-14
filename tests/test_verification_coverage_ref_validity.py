"""CLAUDE-ARCH-S2-014C (F1): closes the phantom/foreign requirement_ref
gap independently reproduced in CDX-REVIEW-S2-014A.

Root cause: `_verification_coverage_is_grounded()`'s self-evidenced
branch (kind in {"manual_review", "probe", "config_validation"}) treated
`evidence in coverage.requirement_refs` as sufficient grounding -- a
TAUTOLOGY the SAME LLM call fully controls (it declares both
`requirement_refs` and `evidence` on the identical VerificationCoverage
object). Nothing checked that the referenced id was even a real,
relevant, currently-binding requirement -- an entry could smuggle a
totally invented ("phantom") id, a foreign id copied from another
context, or bundle a phantom id alongside a genuine one to ride along
and still register as "coverage".

Fix: `_verification_coverage_refs_are_valid()` requires every id in
`coverage.requirement_refs` to be a member of `binding_ids` (computed by
S1/Preflight, never by the Council/Chairman) BEFORE grounding/
compatibility are even considered -- applied identically to every
verification kind, not only the self-evidenced ones. An entry with even
ONE phantom/foreign/non-binding ref is rejected IN FULL.

RED-before-fix evidence: every FAIL test below (cases 1-3 and the
generalized phantom-ref class) passed unmodified pre-014C code --
i.e. FAILED to reject -- because probe/config_validation/manual_review
grounding accepted a bare self-reference with no independent check that
the referenced id was real (confirmed before implementing
_verification_coverage_refs_are_valid(); see the completion report, R4).
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
    _pip_item,
    _requirement_needing_verification,
    _trusted_groups,
)


class TestCase1PhantomRefWithInventedMechanismFails:
    """1: real binding requirement R + phantom coverage ref P + invented
    mechanism + self-declared provides_verification + no trusted ADC
    evidence -- FAIL, across every self-evidenced kind."""

    @pytest.mark.parametrize("kind", ["probe", "config_validation", "manual_review"])
    def test_phantom_ref_self_referenced_with_invented_mechanism_fails(self, kind):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        phantom = "phantom-req-does-not-exist"
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(_pip_item(req.id),),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(phantom,), kind=kind,
                mechanism="totally_invented_mechanism", evidence=phantom,
                human_governed=True,
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is False
        # req itself is STILL uncovered (the phantom entry never touches it).
        assert "req-esphome" in validations[0].reasons[0]


class TestCase2MixedRealAndPhantomRefsFails:
    """2: coverage containing BOTH the real requirement R and a phantom
    P in the SAME entry -- the entire entry is rejected, R does not
    receive a free ride alongside P."""

    @pytest.mark.parametrize("kind", ["probe", "config_validation"])
    def test_real_ref_does_not_ride_along_with_phantom_ref(self, kind):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        phantom = "phantom-req-xyz"
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(_pip_item(req.id),),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id, phantom), kind=kind,
                mechanism="config_check", evidence=phantom,
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is False
        assert "req-esphome" in validations[0].reasons[0]

    def test_real_ref_does_not_ride_along_when_self_referencing_the_real_one(self):
        """Even when evidence self-references the REAL id (not the
        phantom), the phantom's mere PRESENCE in requirement_refs still
        invalidates the whole entry -- an attacker cannot launder a
        phantom by attaching it to a legitimately-evidenced real ref."""
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        phantom = "phantom-req-xyz"
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(_pip_item(req.id),),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id, phantom), kind="config_validation",
                mechanism="config_check", evidence=req.id,
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is False


class TestCase3ForeignRequirementIdFails:
    """3: a requirement id that IS structurally valid-looking and even
    real in ANOTHER context/candidate, but not part of THIS candidate's
    binding set -- foreign, not phantom, but equally rejected."""

    def test_foreign_id_from_a_different_multi_requirement_context_fails(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        # "req-from-another-project" is exactly the SHAPE of a real
        # requirement id elsewhere in ADC -- just not one binding HERE.
        foreign_id = "req-from-another-project"
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(_pip_item(req.id),),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(foreign_id,), kind="probe",
                mechanism="health_check", evidence=foreign_id,
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is False

    def test_foreign_id_that_is_a_real_but_non_binding_requirement_fails(self):
        """A ref naming a requirement that genuinely exists in THIS
        preflight but is NOT binding (not required/not blocking) is
        equally a "foreign" ref for S2.3 Verification Feasibility
        purposes -- it must not establish coverage for the ACTUAL
        binding requirement."""
        req = _requirement_needing_verification("req-binding")
        non_binding = _requirement_needing_verification("req-not-binding")
        preflight = _multi_requirement_preflight(req, non_binding=(non_binding,))
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(_pip_item(req.id), _pip_item(non_binding.id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(non_binding.id,), kind="config_validation",
                mechanism="config_check", evidence=non_binding.id,
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is False
        assert "req-binding" in validations[0].reasons[0]


class TestCase4LegitimateRefsWithIndependentEvidencePass:
    """4: legitimate requirement refs + legitimate independent evidence
    -- PASS, proving the fix does not overreach into genuinely valid
    coverage.

    Uses kind="manual_review" (governed) rather than probe/
    config_validation for the self-evidenced shape: once F1 requires a
    self-referenced evidence value to be a REAL binding id, and F4
    requires every binding id to already have a real covering
    ToolchainItem, `_resolve_toolchain_item_for_evidence()` will always
    find that SAME covering item for a probe/config_validation entry
    (it matches by requirement_ref) -- so those two kinds now
    necessarily also go through the toolchain-compatibility path, not
    the self-evidenced fallback (see
    tests/test_verification_feasibility_compatibility.py for that
    combined path). manual_review is checked BEFORE toolchain
    resolution (app.engineering_decision._verification_coverage_is_
    compatible()) and is the one kind that genuinely stays on the
    self-evidenced path -- proven here to still pass once its ref is
    real and its governance is real (CLAUDE-ARCH-S2-013G)."""

    def test_self_evidenced_manual_review_with_real_binding_ref_passes(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(_pip_item(req.id),),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="manual_review",
                mechanism="manual_review", evidence=req.id, human_governed=True,
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(
            result, preflight=preflight, governed_manual_verification_ids=frozenset({req.id}),
        )
        assert validations[0].admissible is True

    def test_multiple_real_refs_in_one_entry_pass(self):
        req_a = _requirement_needing_verification("req-a")
        req_b = _requirement_needing_verification("req-b")
        preflight = _multi_requirement_preflight(req_a, req_b)
        # Dedicated pytest-evidence item, separate from the two covering
        # items -- an item's OWN identity ("esphome") must semantically
        # match the Requirement it covers (F4), which is orthogonal to
        # which identity actually provides the "pytest" mechanism (013F/G).
        pytest_item = ToolchainItem(
            requirement_ref=req_a.id, name="pytest", type="executable",
            technical_identity="pytest", provides_verification=("pytest",),
        )
        variant = CouncilVariant(
            id="v1", name="v1",
            toolchain=(_pip_item(req_a.id), _pip_item(req_b.id), pytest_item),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req_a.id, req_b.id), kind="test_command",
                mechanism="pytest", evidence="pytest",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(
            result, preflight=preflight,
            trusted_verification_groups=_trusted_groups(test_systems=["pytest"]),
        )
        assert validations[0].admissible is True


class TestGeneralizedPhantomRefClass:
    """Generalized (LLM->S2 regression principle): a CLASS of phantom/
    foreign ref shapes across every self-evidenced kind, not one exact
    string."""

    @pytest.mark.parametrize("kind, phantom", [
        ("probe", "made-up-id-1"),
        ("probe", ""),
        ("config_validation", "req-does-not-exist"),
        ("manual_review", "sneaky-foreign-ref"),
        ("manual_review", "req-esphome-typo"),
    ])
    def test_phantom_or_malformed_refs_never_establish_coverage(self, kind, phantom):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        coverage_kwargs = {"human_governed": True} if kind == "manual_review" else {}
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(_pip_item(req.id),),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(phantom,) if phantom else (), kind=kind,
                mechanism="some_mechanism", evidence=phantom, **coverage_kwargs,
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is False, (kind, phantom)

    def test_categorize_admissibility_reasons_still_maps_to_verification_coverage(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(_pip_item(req.id),),
            verification_coverage=(VerificationCoverage(
                requirement_refs=("phantom",), kind="probe",
                mechanism="health_check", evidence="phantom",
            ),),
        )
        validation = validate_variants((variant,), preflight=preflight)[0]
        assert categorize_admissibility_reasons(validation.reasons) == "verification_coverage"


class TestRepairEvidenceNamesThePhantomRef:
    def test_repair_evidence_identifies_the_exact_phantom_ref(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        phantom = "phantom-ref-abc"
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(_pip_item(req.id),),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(phantom,), kind="probe",
                mechanism="health_check", evidence=phantom,
            ),),
        )
        validation = validate_variants((variant,), preflight=preflight)[0]
        assert validation.admissible is False
        rework = EngineeringReworkRequest.from_validation(validation)
        assert rework.reason_codes == ("verification_coverage",)
        # The phantom entry does not reference "req-esphome" at all (its
        # OWN requirement_refs is purely the phantom id) -- so req-esphome
        # is correctly reported as having NO entry referencing it, exactly
        # as if nothing had been declared for it.
        assert "req-esphome" in " ".join(rework.verification_feasibility_gap_ids)
        assert any(
            "no verification_coverage entry references this requirement" in detail
            for detail in rework.verification_feasibility_conflict_detail
        )

    def test_repair_with_a_genuinely_valid_ref_becomes_admissible(self):
        """The SAME S2.3 function, re-evaluated with the phantom ref
        replaced by the real one, becomes admissible -- proving repair
        corrects data rather than S2.3 being weakened."""
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        broken = CouncilVariant(
            id="v1", name="v1", toolchain=(_pip_item(req.id),),
            verification_coverage=(VerificationCoverage(
                requirement_refs=("phantom-ref",), kind="probe",
                mechanism="health_check", evidence="phantom-ref",
            ),),
        )
        assert validate_variants((broken,), preflight=preflight)[0].admissible is False

        # kind="manual_review" (governed), not probe/config_validation:
        # once the ref is real, F4 guarantees a real covering ToolchainItem
        # exists for it, so a probe/config_validation entry would now
        # resolve THAT item via requirement_ref and go through the
        # toolchain-compatibility path instead of self-evidenced grounding
        # (see TestCase4LegitimateRefsWithIndependentEvidencePass's own
        # docstring) -- manual_review is the kind that genuinely stays
        # self-evidenced.
        repaired = CouncilVariant(
            id="v1", name="v1", toolchain=(_pip_item(req.id),),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="manual_review",
                mechanism="manual_review", evidence=req.id, human_governed=True,
            ),),
        )
        assert validate_variants(
            (repaired,), preflight=preflight,
            governed_manual_verification_ids=frozenset({req.id}),
        )[0].admissible is True


class TestS2_3StillExecutesNothing:
    def test_ref_validity_check_is_a_pure_function(self):
        import inspect
        import app.engineering_decision as ed_module
        source = inspect.getsource(ed_module)
        assert "subprocess" not in source
        assert "app.verification" not in source
        assert "app.testing_stage" not in source
