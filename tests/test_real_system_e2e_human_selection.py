"""Tests for CLAUDE-ADC-E2E-HUMAN-SELECTION-EMULATION-001: the Real-System
E2E harness's TEST-ONLY human-selection emulation for the productive S2.4
Human Engineering Authority boundary.

These exercise the plain helper function in
tests/real_system/real_system_e2e.py directly and carry no
@pytest.mark.real_system marker, so they run under a normal
``pytest -q`` invocation without --real-system-e2e and without touching
any real toolchain, network, or paid provider.

The module under test is loaded by explicit file path (rather than a
package import) because tests/real_system/ has no __init__.py, and any
test physically placed inside that directory is treated by
tests/conftest.py's keyword-based skip logic as a real-system test
regardless of markers.
"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.council_models import CouncilResult, CouncilVariant
from app.dev_workflow import DevelopmentWorkflow
from app.engineering_decision import describe_engineering_variant_selection
from app.toolchain_materializer import ToolchainMaterializer

from tests.test_engineering_decision import _binding_preflight, _pip_item, _requirement

_MODULE_PATH = (
    Path(__file__).parent / "real_system" / "real_system_e2e.py"
)
_spec = importlib.util.spec_from_file_location(
    "real_system_e2e_human_selection_under_test", _MODULE_PATH,
)
real_system_e2e = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(real_system_e2e)

_choose_human_selected_variant_id = real_system_e2e._choose_human_selected_variant_id


def _two_candidate_selection(recommendation: str):
    """One binding requirement, one variant that genuinely covers it
    (admissible) and one that does not (inadmissible) -- exactly the
    "Chairman recommendation may or may not be admissible" shape the
    task requires covering both sides of."""
    req = _requirement()
    preflight = _binding_preflight(req)
    admissible_variant = CouncilVariant(
        id="admissible-candidate", name="Covers the binding requirement",
        toolchain=(_pip_item(req.id),),
    )
    inadmissible_variant = CouncilVariant(
        id="inadmissible-candidate", name="Does not cover the binding requirement",
    )
    council_result = CouncilResult(
        id="c1", project_id="proj",
        variants=(admissible_variant, inadmissible_variant),
        recommendation=recommendation, council_complete=True,
    )
    return describe_engineering_variant_selection(
        council_result, preflight=preflight, chairman_recommendation=recommendation,
    )


def test_accepts_the_chairman_recommendation_when_it_is_admissible():
    selection = _two_candidate_selection(recommendation="admissible-candidate")

    chosen = _choose_human_selected_variant_id(selection)

    assert chosen == "admissible-candidate"


def test_never_selects_an_inadmissible_chairman_recommendation():
    """CLAUDE-ADC-E2E-HUMAN-SELECTION-EMULATION-001 core requirement: the
    harness must never choose a candidate merely because the Chairman
    recommended it -- an inadmissible recommendation must fall through
    to a genuinely admissible alternative instead."""
    selection = _two_candidate_selection(recommendation="inadmissible-candidate")
    assert selection.chairman_recommendation == "inadmissible-candidate"
    assert "inadmissible-candidate" not in {
        v.id for v in selection.admissible_variants
    }

    chosen = _choose_human_selected_variant_id(selection)

    assert chosen == "admissible-candidate"
    assert chosen != selection.chairman_recommendation


def test_is_deterministic_among_multiple_admissible_alternatives():
    """When the recommendation is inadmissible (or unset) and MULTIPLE
    candidates are admissible, the choice must be a fixed, reproducible
    function of the candidate ids -- never dependent on proposal order
    or randomness."""
    req = _requirement()
    preflight = _binding_preflight(req)
    variant_b = CouncilVariant(id="b-candidate", name="b", toolchain=(_pip_item(req.id),))
    variant_a = CouncilVariant(id="a-candidate", name="a", toolchain=(_pip_item(req.id),))
    council_result = CouncilResult(
        id="c1", project_id="proj",
        variants=(variant_b, variant_a),
        recommendation="no-such-variant", council_complete=True,
    )
    selection = describe_engineering_variant_selection(
        council_result, preflight=preflight, chairman_recommendation="no-such-variant",
    )

    chosen_first = _choose_human_selected_variant_id(selection)
    chosen_second = _choose_human_selected_variant_id(selection)

    assert chosen_first == chosen_second == "a-candidate"


def test_raises_when_no_candidate_is_admissible():
    req = _requirement()
    preflight = _binding_preflight(req)
    inadmissible_variant = CouncilVariant(id="v1", name="v1")
    council_result = CouncilResult(
        id="c1", project_id="proj", variants=(inadmissible_variant,),
        recommendation="v1", council_complete=True,
    )
    selection = describe_engineering_variant_selection(
        council_result, preflight=preflight, chairman_recommendation="v1",
    )
    assert not selection.admissible_variants

    with pytest.raises(AssertionError):
        _choose_human_selected_variant_id(selection)


def test_planning_contract_mapping_reports_the_human_selected_variant_not_the_inadmissible_recommendation(capsys):
    """CDX-ADC-E2E-HUMAN-SELECTION-REVIEW-001 finding F1: when the
    Chairman recommendation is inadmissible and the emulated human
    explicitly selects a different, admissible variant, execution
    already follows that human choice -- DevelopmentWorkflow.
    resolve_engineering_selection() materializes the human-selected
    variant's SetupPlan -- but the harness's own planning-contract
    mapping evidence was still deriving `selected_variant` and its
    toolchain from `council.recommendation`, falsely labeling the
    REJECTED Chairman recommendation as selected. This reproduces that
    exact scenario end-to-end through the real
    DevelopmentWorkflow.resolve_engineering_selection() call (equivalent
    to CDX-ADC-E2E-HUMAN-SELECTION-REVIEW-001's own /tmp reproducer, now
    recreated as durable, repository-resident coverage) and proves the
    mapping reports the actual human-selected id, with the Chairman
    recommendation kept only as separate diagnostic metadata -- never
    conflated with the selection."""
    selection = _two_candidate_selection(recommendation="inadmissible-candidate")
    req = _requirement()
    preflight = _binding_preflight(req)
    council = CouncilResult(
        id="c1", project_id="proj",
        variants=tuple(v.variant for v in selection.validations),
        recommendation="inadmissible-candidate", council_complete=True,
    )
    human_selected_variant_id = _choose_human_selected_variant_id(selection)
    assert human_selected_variant_id == "admissible-candidate"
    assert human_selected_variant_id != council.recommendation

    workflow = DevelopmentWorkflow(None, None, None, None, materializer=ToolchainMaterializer())
    result = workflow.resolve_engineering_selection(
        council, preflight, None, "proj",
        human_selected_variant_id=human_selected_variant_id,
    )
    assert result.setup_plan.status == "pending_approval"

    real_system_e2e._emit_planning_contract_mapping(
        SimpleNamespace(
            validation_result=SimpleNamespace(normalized_requirements=(req,)),
            preflight_result=preflight, council_result=council,
            setup_plan=result.setup_plan,
        ),
        human_selected_variant_id,
    )

    out = capsys.readouterr().out
    assert f"selected_variant: id={human_selected_variant_id} " in out
    assert f"recommendation={council.recommendation}" in out
    assert f"id={council.recommendation} " not in out
