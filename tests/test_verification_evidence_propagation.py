"""S2.3 pre-flight test hardening (CLAUDE-ADC-S23-RSE-PREFLIGHT-TEST-
HARDENING-001), Part E: verification-evidence propagation.

Real-System-E2E task ADC-REAL-SYSTEM-E2E-RETRY-001 reported, for two of
the three rejected candidates, "ESPHome verification missing" and, for
all three, "configuration-file verification missing" alongside the
missing platform-requirement coverage. These tests focus narrowly on
that verification-evidence propagation path, independent of binding
coverage:

    verification requirements (Requirement.verification_method)
    -> Project Intelligence (dict-shaped project_intelligence summary)
    -> app.verification.trusted_verification_identity_groups()
       (trusted_verification_groups)
    -> Council candidate verification evidence (VerificationCoverage)
    -> CandidateValidation.verification_feasibility_gap_ids

All four required cases call the real
app.engineering_decision.validate_variants()/validate_candidates() --
never a re-implementation of the compatibility/grounding rules -- and
never weaken identity matching (no case here corroborates a claim by
loosening `_verification_coverage_is_compatible()`/
`_verification_coverage_is_grounded()`'s own equality/membership checks).
"""
from __future__ import annotations

from app.council_models import CouncilResult, CouncilVariant, ToolchainItem, VerificationCoverage
from app.engineering_decision import validate_candidates, validate_variants
from app.requirement_model import RequirementType
from app.verification import trusted_verification_identity_groups

from tests.test_engineering_decision import (
    _binding_preflight,
    _pip_item,
    _requirement_needing_verification,
)


def _firmware_project_intelligence(firmware_indicators=("esphome",)):
    """The dict-shaped Project Intelligence summary
    (CouncilInput.project_intelligence) trusted_verification_identity_
    groups() consumes in production -- built here from scratch (never
    reusing app.verification's own runner maps) so this test remains
    independent evidence, not a tautology."""
    return {
        "test_systems": [],
        "build_systems": [],
        "firmware_indicators": list(firmware_indicators),
    }


def _esphome_toolchain_item(req_id, name="esphome", technical_identity="esphome"):
    return ToolchainItem(
        requirement_ref=req_id, name=name, type=RequirementType.PYTHON_PACKAGE,
        technical_identity=technical_identity, install_method="pip install esphome",
        state="needs_install", provides_verification=("esphome_validate",),
    )


class TestValidVerificationEvidencePropagates:
    def test_esphome_verification_evidence_corroborated_by_trusted_groups_produces_no_gap(self):
        req = _requirement_needing_verification(
            req_id="req-esphome", verification_method="esphome validate",
        )
        preflight = _binding_preflight(req)
        item = _esphome_toolchain_item(req.id)
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(item,),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="build_command",
                mechanism="esphome_validate", evidence="esphome",
            ),),
        )
        result = CouncilResult(
            id="c1", project_id="proj", variants=(variant,),
            recommendation="v1", council_complete=True,
        )

        trusted_groups = trusted_verification_identity_groups(_firmware_project_intelligence())
        validations = validate_candidates(
            result, preflight=preflight, trusted_verification_groups=trusted_groups,
        )
        assert validations[0].verification_feasibility_gap_ids == ()
        assert validations[0].admissible is True, validations[0].reasons


class TestWrongIdentityEvidenceIsRejected:
    def test_evidence_naming_an_unrelated_items_identity_is_rejected(self):
        """The evidence structurally resolves to a REAL toolchain item on
        the SAME candidate (CLAUDE-ARCH-S2-013E grounding is satisfied),
        but that item has nothing to do with the esphome_validate
        mechanism the coverage entry claims -- ADC must never treat
        "some item exists" as proof that THIS mechanism applies to it."""
        req = _requirement_needing_verification(
            req_id="req-esphome", verification_method="esphome validate",
        )
        preflight = _binding_preflight(req)
        esphome_item = _esphome_toolchain_item(req.id)
        unrelated_item = ToolchainItem(
            requirement_ref=req.id, name="unrelated-tool",
            type=RequirementType.EXECUTABLE, technical_identity="unrelated-tool",
            provides_verification=(),
        )
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(esphome_item, unrelated_item),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="build_command",
                mechanism="esphome_validate", evidence="unrelated-tool",
            ),),
        )
        result = CouncilResult(
            id="c1", project_id="proj", variants=(variant,),
            recommendation="v1", council_complete=True,
        )

        trusted_groups = trusted_verification_identity_groups(_firmware_project_intelligence())
        validations = validate_candidates(
            result, preflight=preflight, trusted_verification_groups=trusted_groups,
        )
        assert validations[0].verification_feasibility_gap_ids == (req.id,)
        assert validations[0].admissible is False

    def test_trusted_group_for_a_different_capability_does_not_corroborate(self):
        """Independent Project Intelligence evidence exists (pytest), but
        NOT for the capability this candidate actually claims
        (esphome_validate) -- a trusted group for one real capability
        must never corroborate an unrelated one."""
        req = _requirement_needing_verification(
            req_id="req-esphome", verification_method="esphome validate",
        )
        preflight = _binding_preflight(req)
        item = _esphome_toolchain_item(req.id)
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(item,),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="build_command",
                mechanism="esphome_validate", evidence="esphome",
            ),),
        )
        result = CouncilResult(
            id="c1", project_id="proj", variants=(variant,),
            recommendation="v1", council_complete=True,
        )

        # Only a pytest test-system group exists -- no firmware evidence.
        trusted_groups = trusted_verification_identity_groups({
            "test_systems": ["pytest"], "build_systems": [], "firmware_indicators": [],
        })
        validations = validate_candidates(
            result, preflight=preflight, trusted_verification_groups=trusted_groups,
        )
        assert validations[0].verification_feasibility_gap_ids == (req.id,)
        assert validations[0].admissible is False


class TestMissingVerificationEvidenceProducesExpectedGapId:
    def test_no_verification_coverage_entry_produces_the_exact_gap_id(self):
        req = _requirement_needing_verification(
            req_id="req-esphome", verification_method="esphome validate",
        )
        preflight = _binding_preflight(req)
        item = _esphome_toolchain_item(req.id)
        variant = CouncilVariant(id="v1", name="v1", toolchain=(item,), verification_coverage=())
        result = CouncilResult(
            id="c1", project_id="proj", variants=(variant,),
            recommendation="v1", council_complete=True,
        )

        trusted_groups = trusted_verification_identity_groups(_firmware_project_intelligence())
        validations = validate_candidates(
            result, preflight=preflight, trusted_verification_groups=trusted_groups,
        )
        assert validations[0].verification_feasibility_gap_ids == (req.id,)
        assert validations[0].admissible is False


class TestConfigurationFileVerificationIsTreatedDistinctly:
    """CLAUDE-ARCH-S2-013E: `config_validation` is one of the
    `_SELF_EVIDENCED_VERIFICATION_KINDS` -- its evidence may name one of
    the requirement ids the mechanism itself claims to cover (there is
    nothing installable, e.g. no ToolchainItem, to point evidence at for
    a project configuration file), unlike a tool-backed kind
    (test_command/build_command/static_analysis), which requires a real,
    corroborated ToolchainItem. This is the exact distinction the RSE's
    separately-reported "configuration-file verification missing" gap
    (as opposed to "ESPHome verification missing") depends on."""

    def test_self_evidenced_config_validation_needs_no_toolchain_item_or_trusted_groups(self):
        req = _requirement_needing_verification(
            req_id="req-esphome-yaml", verification_method="validate esphome.yaml schema",
        )
        preflight = _binding_preflight(req)
        # No ToolchainItem at all references this requirement's identity
        # -- config_validation evidence self-references the requirement
        # id instead.
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="config_validation",
                mechanism="yaml_schema_check", evidence=req.id,
            ),),
        )
        result = CouncilResult(
            id="c1", project_id="proj", variants=(variant,),
            recommendation="v1", council_complete=True,
        )

        # Deliberately no binding-coverage toolchain item and no trusted
        # groups at all -- config_validation must still be feasible.
        validations = validate_variants((variant,), preflight=preflight)
        assert validations[0].verification_feasibility_gap_ids == ()

    def test_same_shape_build_command_evidence_without_grounding_or_trust_still_gaps(self):
        """The contrast case: swapping ONLY the kind from
        "config_validation" to "build_command" (still self-referencing
        evidence, still no toolchain item, still no trusted groups) must
        NOT also become self-evidenced -- proving config_validation's
        leniency is a specific, intentional exception, not a general
        weakening of the grounding/compatibility rules."""
        req = _requirement_needing_verification(
            req_id="req-esphome-yaml", verification_method="validate esphome.yaml schema",
        )
        preflight = _binding_preflight(req)
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="build_command",
                mechanism="yaml_schema_check", evidence=req.id,
            ),),
        )
        validations = validate_variants((variant,), preflight=preflight)
        assert validations[0].verification_feasibility_gap_ids == (req.id,)
        assert validations[0].admissible is False
