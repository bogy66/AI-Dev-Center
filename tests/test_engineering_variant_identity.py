"""CLAUDE-ARCH-S2-014C (F3): closes the duplicate-variant-identity gap
independently reproduced in CDX-REVIEW-S2-014A.

Root cause: `EngineeringCouncil._parse_chairman_result()` computed
`variant_ids = {variant.id for variant in variants}` -- a SET
comprehension that silently COLLAPSES two CouncilVariant objects sharing
one id into a single entry, while `variants` itself (the LIST that
becomes `CouncilResult.variants`) still carries BOTH. Nothing checked
`len(variants) == len(variant_ids)`. Downstream, code that resolves "the
variant with id X" by `next(v for v in ... if v.id == X)` (first match --
app.engineering_decision.resolve_human_engineering_selection(),
validations_by_id()) and code that instead builds a `{id: v}` dict (LAST
match wins -- app.web_api._engineering_decision_payload() before this
fix) would silently resolve to TWO DIFFERENT objects for the SAME id:
exactly "human sees variant A, submits its id, selector resolves variant
B".

Fix: `_parse_chairman_result()` now rejects (raises
CouncilChairmanError, category="duplicate_variant_id") whenever
`len(variants) != len(variant_ids)` -- BEFORE any admissibility check,
BEFORE S2.4 ever sees a selectable candidate. `app.engineering_decision.
validate_variants()` ALSO independently rejects (marks every variant
sharing a duplicated id inadmissible) as defense-in-depth, since it
explicitly accepts a tuple of CouncilVariant from ANY producer, not only
the Chairman parser. `app.web_api._engineering_decision_payload()` no
longer builds a last-wins `{id: v}` dict at all -- it resolves by first
match, the SAME order every other S2 consumer uses.

RED-before-fix evidence: case 1 and case 2 below passed unmodified
pre-014C code -- i.e. FAILED to reject -- because neither
`_parse_chairman_result()` nor `validate_variants()` checked identity
uniqueness at all (confirmed before implementing the duplicate-id
checks; see the completion report, R8).
"""
import json

import pytest

from app.council_error import CouncilChairmanError
from app.council_models import CouncilInput, CouncilResult, CouncilVariant
from app.engineering_council import EngineeringCouncil
from app.engineering_decision import (
    admissible_variants,
    categorize_admissibility_reasons,
    validate_variants,
)
from app.requirement_model import (
    PreflightRequirementResult,
    PreflightResult,
    RequirementActivation,
)
from app.secret_resolver import SimpleSecretResolver

from tests.test_engineering_council import _make_council_config
from tests.test_engineering_decision import _pip_item, _requirement


def _minimal_council():
    return EngineeringCouncil(
        council_config=_make_council_config(),
        secret_resolver=SimpleSecretResolver({"openrouter-api": "test"}),
    )


def _minimal_council_input():
    req = _requirement("req-1")
    return CouncilInput(
        requirements=(req,),
        preflight=PreflightResult(
            id="pre-1", project_id="proj", overall_ready=False,
            results=(PreflightRequirementResult(
                requirement_id=req.id, present=False, satisfied=False,
            ),),
            missing_requirements=(req,),
            activations=(RequirementActivation(req.id, True, True),),
        ),
        detected_stack="python", project_id="proj",
        project_files=("proj.py",), platform="linux",
    )


def _dict_variant(variant_id, req_id="req-1"):
    return {
        "id": variant_id, "name": variant_id, "description": "",
        "origin_agents": ["A1"], "merged_from": [variant_id],
        "rank": 1, "total_score": 5.0, "consensus_level": "strong_consensus",
        "minority_opinions": [], "environment": "host",
        "hardware_target": None, "connection": None,
        "capabilities": [],
        "toolchain": [{
            "requirement_ref": req_id, "name": "esphome",
            "technical_identity": "esphome", "type": "python_package",
            "install_method": "pip", "version": None, "purpose": "",
            "depends_on": [], "state": "needs_install",
            "environment_constraint": None, "provided_by": None,
            "provides_verification": [],
        }],
        "advantages": [], "disadvantages": [], "risks": [],
        "confidence": 0.9, "feasibility": "high", "verification": "",
    }


class TestCase1DuplicateIdRejectedBeforeHumanSelection:
    """1: two candidates with the same id -- fail closed BEFORE human
    selection is offered (proven both at the Chairman-parse structural
    boundary AND, defense-in-depth, at S2.3's own validate_variants())."""

    def test_duplicate_id_rejected_at_chairman_parse_boundary(self):
        council = _minimal_council()
        council_input = _minimal_council_input()
        parsed = {
            "variants": [_dict_variant("v1"), _dict_variant("v1")],
            "recommendation": "v1",
        }
        with pytest.raises(CouncilChairmanError) as excinfo:
            council._parse_chairman_result(parsed, council_input)
        assert excinfo.value.category == "duplicate_variant_id"

    def test_duplicate_id_marks_both_candidates_inadmissible_in_validate_variants(self):
        """Defense-in-depth: even a producer OTHER than the Chairman
        parser (validate_variants() accepts a bare tuple of
        CouncilVariant from anyone) must not let an ambiguous id reach
        S2.4."""
        req = _requirement("req-1")
        variant_a = CouncilVariant(id="v1", name="Variant A", toolchain=(_pip_item(req.id),))
        variant_b = CouncilVariant(id="v1", name="Variant B", toolchain=(_pip_item(req.id),))
        validations = validate_variants((variant_a, variant_b))
        assert all(not v.admissible for v in validations)
        assert all("ambiguous variant identity" in v.reasons[0] for v in validations)
        assert all(
            categorize_admissibility_reasons(v.reasons) == "duplicate_variant_identity"
            for v in validations
        )
        # Nothing is selectable -- S2.4 correctly sees zero admissible
        # candidates, not an arbitrary pick.
        assert admissible_variants(validations) == ()


class TestCase2DuplicateFromChairmanSynthesisRejectedStructurally:
    """2: duplicate ID from Chairman synthesis -- the parser/structural
    boundary rejects it (not S2.3, not S2.4 -- the earliest possible
    point)."""

    def test_three_variants_two_sharing_an_id_rejected(self):
        council = _minimal_council()
        council_input = _minimal_council_input()
        parsed = {
            "variants": [
                _dict_variant("v1"), _dict_variant("v2"), _dict_variant("v1"),
            ],
            "recommendation": "v1",
        }
        with pytest.raises(CouncilChairmanError) as excinfo:
            council._parse_chairman_result(parsed, council_input)
        assert excinfo.value.category == "duplicate_variant_id"
        assert "v1" in str(excinfo.value)

    def test_unique_ids_are_not_rejected(self):
        """Sanity: the check is specific to actual duplicates, not an
        overreaching rejection of every multi-variant result."""
        council = _minimal_council()
        council_input = _minimal_council_input()
        parsed = {
            "variants": [_dict_variant("v1"), _dict_variant("v2")],
            "recommendation": "v1",
        }
        result = council._parse_chairman_result(parsed, council_input)
        assert {v.id for v in result.variants} == {"v1", "v2"}


class TestCase3DuplicateAfterRepairFailsClosed:
    """3: a duplicate id introduced by the REPAIRED Chairman response
    (not just the first attempt) fails closed -- proven by calling the
    SAME structural parser _parse_chairman_result() invokes on a repair
    response, since it is the ONE parser both the original and repaired
    synthesis pass through (app.engineering_council._phase3_chairman_
    synthesis calls it for both)."""

    def test_repair_response_with_duplicate_id_still_rejected(self):
        council = _minimal_council()
        council_input = _minimal_council_input()
        repaired_parsed = {
            "variants": [_dict_variant("v1"), _dict_variant("v1")],
            "recommendation": "v1",
        }
        with pytest.raises(CouncilChairmanError) as excinfo:
            council._parse_chairman_result(repaired_parsed, council_input)
        assert excinfo.value.category == "duplicate_variant_id"


class TestCase4And5DisplayedChoiceReachesS3ExactObject:
    """4: the displayed candidate ID/object is the EXACT SAME candidate
    that reaches EngineeringDecision.
    5: a unique alternate human selection reaches S3 as the EXACT
    selected object -- proven via object identity (`is`), not merely
    equal ids, across describe -> accept -> EngineeringDecision."""

    @staticmethod
    def _two_variant_setup():
        req = _requirement("req-1")
        preflight = PreflightResult(
            id="pre-1", project_id="proj", overall_ready=False,
            results=(PreflightRequirementResult(
                requirement_id=req.id, present=False, satisfied=False,
            ),),
            missing_requirements=(req,),
            activations=(RequirementActivation(req.id, True, True),),
        )
        variant_recommended = CouncilVariant(
            id="v1", name="Recommended", toolchain=(_pip_item(req.id),),
        )
        variant_alt = CouncilVariant(
            id="v2", name="Alternative", toolchain=(_pip_item(req.id),),
        )
        result = CouncilResult(
            id="c1", project_id="proj", variants=(variant_recommended, variant_alt),
            recommendation="v1", council_complete=True,
        )
        return preflight, result, variant_recommended, variant_alt

    def test_displayed_recommendation_is_the_exact_object_in_the_engineering_decision(self):
        from app.engineering_decision import describe_engineering_variant_selection, select_engineering_variant

        preflight, result, variant_recommended, _ = self._two_variant_setup()
        selection = describe_engineering_variant_selection(
            result, preflight, "linux", chairman_recommendation="v1",
        )
        displayed = next(
            v.variant for v in selection.validations if v.variant.id == selection.selected_variant_id
        )
        decision = select_engineering_variant(
            result, preflight, "linux",
            chairman_recommendation="v1", human_selected_variant_id="v1",
        )
        assert displayed is variant_recommended
        assert decision.variant is displayed

    def test_unique_alternate_human_selection_is_the_exact_object_selected(self):
        from app.engineering_decision import select_engineering_variant

        preflight, result, variant_recommended, variant_alt = self._two_variant_setup()
        decision = select_engineering_variant(
            result, preflight, "linux",
            chairman_recommendation="v1", human_selected_variant_id="v2",
        )
        assert decision.variant is variant_alt
        assert decision.variant is not variant_recommended
        assert decision.selection_authority == "human"


class TestNoSilentRenameOrFirstLastPick:
    """Do not silently rename duplicate IDs. Do not pick first/last
    duplicate. Ambiguous identity must fail closed -- proven the parser
    NEVER returns a CouncilResult at all for a duplicate-id input (no
    renamed variant, no silently-dropped one)."""

    def test_parser_never_returns_a_result_for_duplicate_ids(self):
        council = _minimal_council()
        council_input = _minimal_council_input()
        parsed = {
            "variants": [_dict_variant("v1"), _dict_variant("v1")],
            "recommendation": "v1",
        }
        with pytest.raises(CouncilChairmanError):
            council._parse_chairman_result(parsed, council_input)
        # No CouncilResult with either 1 (silently deduped) or a renamed
        # variant is ever produced -- the exception IS the only outcome.
