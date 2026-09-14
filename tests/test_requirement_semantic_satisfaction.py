"""CLAUDE-ARCH-S2-014C (F4): closes the "requirement_ref alone proves
satisfaction" gap independently reproduced in CDX-REVIEW-S2-014A.

Root cause: `_covers_binding_requirements()` only checked that SOME
ToolchainItem shared a binding Requirement's `requirement_ref` --
`binding_ids <= {item.requirement_ref for item in variant.toolchain}`.
`requirement_ref` is a REFERENCE (a foreign-key-style pointer a
candidate declares), not proof that the referenced item is actually the
thing the Requirement demands. A candidate could satisfy a required
Python package purely by attaching an UNRELATED executable to the SAME
requirement_ref string, and S2.3 would count it as covered.

Fix: `_semantically_unsatisfied_binding_requirements()` additionally
requires, for every binding id, that AT LEAST ONE of its referencing
ToolchainItem(s) semantically matches the Requirement's own structured
fields (`_toolchain_item_matches_requirement_semantics()`): (a) type
must match `requirement.type`, (b) technical identity must correspond to
`requirement.name` -- reusing app.python_distribution.
distribution_names_match() for PYTHON_PACKAGE (the SAME PEP-503
normalization ADC's README already documents), case-insensitive exact
comparison for every other type, (c) an exact-string version mismatch
when BOTH sides declare one (no invented range/operator semantics --
none exist anywhere in ADC's Requirement.required_version contract
today). PYTHON_PACKAGE items with no `technical_identity` are treated as
INDETERMINATE for identity (never a fabricated verdict) -- reusing
CLAUDE-ARCH-S2-012D's own precedent that a missing technical_identity is
a MATERIALIZABILITY defect, not a semantic-mismatch one.

RED-before-fix evidence: cases 1-5 below passed unmodified pre-014C code
-- i.e. FAILED to reject -- because `_covers_binding_requirements()`
never looked at anything beyond `requirement_ref` (confirmed before
implementing `_toolchain_item_matches_requirement_semantics()`/
`_semantically_unsatisfied_binding_requirements()`; see the completion
report, R10).

TARGET AMBIGUITY: ADC has no structured version-CONSTRAINT semantics
(ranges, operators such as ">=") anywhere -- `Requirement.required_version`
is a plain optional string, read but never parsed/compared anywhere else
in the codebase. This module therefore enforces ONLY exact-string
in/equality when both sides declare a version, and does not invent
range/operator parsing -- seeTestCase3VersionConstraint's own docstring.
"""
import pytest

from app.council_models import CouncilResult, CouncilVariant, ToolchainItem
from app.engineering_decision import validate_candidates
from app.requirement_model import Requirement, RequirementType

from tests.test_engineering_decision import _binding_preflight, _multi_requirement_preflight


def _req(req_id, name="esphome", req_type=RequirementType.PYTHON_PACKAGE, **kwargs):
    return Requirement(
        id=req_id, name=name, type=req_type, purpose="test", required=True,
        confidence=0.9, **kwargs,
    )


def _item(req_id, name, item_type, technical_identity=None, version=None):
    return ToolchainItem(
        requirement_ref=req_id, name=name, type=item_type,
        technical_identity=technical_identity, version=version,
    )


class TestCase1UnrelatedExecutableSameRefFails:
    """1: required Python package + unrelated executable + same
    requirement_ref -- FAIL. Generalized across several unrelated
    identities, not one exact string."""

    @pytest.mark.parametrize("unrelated_name", ["curl", "docker", "make", "totally-unrelated-tool"])
    def test_unrelated_executable_with_matching_ref_fails(self, unrelated_name):
        req = _req("req-esphome")
        preflight = _binding_preflight(req)
        item = _item(req.id, unrelated_name, "executable", technical_identity=unrelated_name)
        variant = CouncilVariant(id="v1", name="v1", toolchain=(item,))
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is False, unrelated_name
        assert "req-esphome" in validations[0].reasons[0]


class TestCase2CorrectTypeWrongIdentityFails:
    """2: correct type but wrong technical identity -- FAIL."""

    def test_correct_type_wrong_python_distribution_fails(self):
        req = _req("req-esphome", name="esphome")
        preflight = _binding_preflight(req)
        item = _item(req.id, "requests", "python_package", technical_identity="requests")
        variant = CouncilVariant(id="v1", name="v1", toolchain=(item,))
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is False

    def test_correct_type_wrong_identity_for_non_python_type_fails(self):
        req = _req("req-cmake", name="cmake", req_type=RequirementType.EXECUTABLE)
        preflight = _binding_preflight(req)
        item = _item(req.id, "make", "executable", technical_identity="make")
        variant = CouncilVariant(id="v1", name="v1", toolchain=(item,))
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is False

    def test_pep503_equivalent_names_are_still_recognized_as_the_same_distribution(self):
        """Sanity: the check reuses distribution_names_match(), so
        case/hyphen/underscore/dot equivalents are NOT false positives."""
        req = _req("req-beautifulsoup", name="Beautiful-Soup")
        preflight = _binding_preflight(req)
        item = _item(req.id, "beautifulsoup4", "python_package", technical_identity="beautiful_soup")
        variant = CouncilVariant(id="v1", name="v1", toolchain=(item,))
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is True


class TestCase3VersionConstraint:
    """3: incompatible version constraint, where structured version
    semantics exist -- FAIL. ADC's ONLY structured version semantics
    today are exact-string presence/equality (required_version is a
    plain optional string, never parsed as a range/operator constraint
    anywhere in the codebase) -- this is intentionally NOT a semver
    range check; inventing one would be a second, undocumented
    requirements model. See the module docstring's TARGET AMBIGUITY
    note."""

    def test_exact_version_mismatch_fails(self):
        req = _req("req-esphome", required_version="2.0.0")
        preflight = _binding_preflight(req)
        item = _item(req.id, "esphome", "python_package", technical_identity="esphome", version="1.0.0")
        variant = CouncilVariant(id="v1", name="v1", toolchain=(item,))
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is False

    def test_exact_version_match_passes(self):
        req = _req("req-esphome", required_version="2.0.0")
        preflight = _binding_preflight(req)
        item = _item(req.id, "esphome", "python_package", technical_identity="esphome", version="2.0.0")
        variant = CouncilVariant(id="v1", name="v1", toolchain=(item,))
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is True

    def test_unspecified_item_version_is_not_proven_incompatible(self):
        """An item that simply does not commit to a version is
        INDETERMINATE for version, not proven wrong -- required_version
        alone never fabricates a mismatch."""
        req = _req("req-esphome", required_version="2.0.0")
        preflight = _binding_preflight(req)
        item = _item(req.id, "esphome", "python_package", technical_identity="esphome", version=None)
        variant = CouncilVariant(id="v1", name="v1", toolchain=(item,))
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is True


class TestCase4EnvironmentPlatformConstraintViolationFails:
    """4: violated environment/platform constraint -- FAIL. Reuses the
    EXISTING _violates_platform_constraint() check unchanged (never
    duplicated here); this proves F4's new semantic-identity check
    correctly COEXISTS with it rather than masking it."""

    def test_semantically_correct_item_still_fails_on_platform_violation(self):
        req = _req("req-esphome")
        preflight = _binding_preflight(req)
        item = ToolchainItem(
            requirement_ref=req.id, name="esphome", type="python_package",
            technical_identity="esphome", environment_constraint="windows",
        )
        variant = CouncilVariant(id="v1", name="v1", toolchain=(item,))
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(result, preflight=preflight, platform="linux")
        assert validations[0].admissible is False
        assert "violates platform constraint" in validations[0].reasons[0]
        # The identity dimension is NOT what failed here -- proving the
        # two checks are independent, not duplicated.
        assert "missing binding requirement coverage" not in validations[0].reasons[0]


class TestCase5OneSatisfiedMustNotHideAnotherUnsatisfied:
    """5: one requirement correctly satisfied must not hide another
    semantically unsatisfied requirement -- FAIL (naming the specific
    unsatisfied one, not the satisfied one)."""

    def test_second_requirement_semantic_mismatch_is_not_hidden(self):
        req_a = _req("req-a", name="esphome")
        req_b = _req("req-b", name="platformio", req_type=RequirementType.EXECUTABLE)
        preflight = _multi_requirement_preflight(req_a, req_b)
        item_a = _item(req_a.id, "esphome", "python_package", technical_identity="esphome")
        item_b = _item(req_b.id, "totally-unrelated", "executable", technical_identity="totally-unrelated")
        variant = CouncilVariant(id="v1", name="v1", toolchain=(item_a, item_b))
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is False
        assert "req-b" in validations[0].reasons[0]
        assert "req-a" not in validations[0].reasons[0]


class TestCase6LegitimateStructuredMatchPasses:
    """6: legitimate structured match -- PASS."""

    def test_matching_type_identity_and_version_passes(self):
        req = _req("req-esphome", required_version="2.0.0")
        preflight = _binding_preflight(req)
        item = _item(req.id, "esphome", "python_package", technical_identity="esphome", version="2.0.0")
        variant = CouncilVariant(id="v1", name="v1", toolchain=(item,))
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is True

    def test_multiple_requirements_all_matching_pass(self):
        req_a = _req("req-a", name="esphome")
        req_b = _req("req-b", name="cmake", req_type=RequirementType.EXECUTABLE)
        preflight = _multi_requirement_preflight(req_a, req_b)
        item_a = _item(req_a.id, "esphome", "python_package", technical_identity="esphome")
        item_b = _item(req_b.id, "cmake", "executable", technical_identity="cmake")
        variant = CouncilVariant(id="v1", name="v1", toolchain=(item_a, item_b))
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is True


class TestRealE2E8PrecedentPreserved:
    """A PYTHON_PACKAGE item with NO technical_identity at all (the
    EXACT CLAUDE-ARCH-S2-012D / Real-System-E2E #8 shape -- a display
    name like "ESPHome CLI" that is not itself a valid distribution
    identifier) is treated as INDETERMINATE for identity, not a fake
    semantic mismatch -- the ALREADY-EXISTING materializability check
    (_unmaterializable_binding_requirements()) remains the correct,
    precise diagnostic for this exact defect; F4 must never shadow it
    with a different, invented verdict."""

    def test_missing_technical_identity_defers_to_materializability_diagnostic(self):
        req = _req("req-esphome", name="esphome")
        preflight = _binding_preflight(req)
        item = ToolchainItem(
            requirement_ref=req.id, name="ESPHome CLI", type="python_package",
            technical_identity=None, install_method="pip",
        )
        variant = CouncilVariant(id="v1", name="v1", toolchain=(item,))
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is False
        assert "cannot be materialized" in validations[0].reasons[0]
        assert "missing binding requirement coverage" not in validations[0].reasons[0]


class TestGeneralizedSemanticMismatchClass:
    """LLM->S2 regression principle: a CLASS of semantic-mismatch
    shapes, not one exact technology string."""

    @pytest.mark.parametrize("req_name, req_type, item_identity, item_type", [
        ("esphome", RequirementType.PYTHON_PACKAGE, "flask", "python_package"),
        ("esphome", RequirementType.PYTHON_PACKAGE, "esphome", "executable"),
        ("cmake", RequirementType.EXECUTABLE, "make", "executable"),
        ("platformio", RequirementType.EXECUTABLE, "platformio", "python_package"),
        ("esp-idf", RequirementType.SDK, "arduino-sdk", "sdk"),
    ])
    def test_mismatched_identity_or_type_never_passes(self, req_name, req_type, item_identity, item_type):
        req = _req("req-x", name=req_name, req_type=req_type)
        preflight = _binding_preflight(req)
        item = _item(req.id, item_identity, item_type, technical_identity=item_identity)
        variant = CouncilVariant(id="v1", name="v1", toolchain=(item,))
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is False, (req_name, req_type, item_identity, item_type)


class TestS2_3StillDoesNotExecute:
    def test_semantic_check_is_a_pure_function(self):
        import inspect
        import app.engineering_decision as ed_module
        source = inspect.getsource(ed_module)
        assert "subprocess" not in source
        assert "app.verification" not in source
        assert "app.testing_stage" not in source
