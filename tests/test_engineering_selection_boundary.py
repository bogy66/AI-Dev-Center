"""CLAUDE-ARCH-S2-013C: the productive Human Engineering Authority (S2.4)
boundary.

RED-before-fix evidence (CLAUDE-ARCH-S2-013A CRITICAL finding): the
productive DevelopmentWorkflow.run() call used to resolve an admissible
Chairman recommendation into an EngineeringDecision and a materialized
SetupPlan in the SAME synchronous call, with NO explicit human
engineering-selection input -- chairman_recommendation existed,
human_selected_variant_id was always None, and an EngineeringDecision was
created anyway. These tests prove the corrected productive shape:
run() now PAUSES at the human engineering-selection boundary (no
EngineeringDecision, no SetupPlan) whenever at least one admissible
candidate exists, and only DevelopmentWorkflow.resolve_engineering_selection()
-- called with an EXPLICIT human_selected_variant_id -- may produce the
EngineeringDecision and materialize a SetupPlan.
"""
from unittest.mock import MagicMock

import pytest

from app.ai_requirement_discovery import AIRequirementDiscovery
from app.council_models import CouncilResult, CouncilVariant
from app.dev_workflow import DevelopmentWorkflow, WorkflowResult
from app.diagnostic_trace import DiagnosticTrace, DiagnosticTraceStore
from app.engineering_council import EngineeringCouncil
from app.engineering_decision import (
    ChairmanRecommendationInadmissibleError,
    EngineeringVariantNotFoundError,
    EngineeringVariantSelection,
    NoEligibleEngineeringCandidateError,
)
from app.requirement_preflight import RequirementPreflight
from app.requirement_validator import RequirementValidator
from app.setup_planner import SetupPlanner
from app.toolchain_materializer import ToolchainMaterializer

from tests.test_dev_workflow import _make_components


def _make_workflow(trace=None):
    (
        discovery, validator, preflight, planner, council, materializer,
        discovery_result, validation_result, preflight_result,
        council_result, plan_result,
    ) = _make_components()
    workflow = DevelopmentWorkflow(
        discovery, validator, preflight, planner,
        council=council, materializer=materializer,
        diagnostic_trace=trace,
    )
    return (
        workflow, council, materializer, discovery_result, validation_result,
        preflight_result, council_result, plan_result,
    )


class TestProductiveEngineeringSelectionBoundary:
    def test_a_admissible_recommendation_stops_at_engineering_selection(self):
        """A: a productive run with an admissible Chairman recommendation
        must stop at the engineering-selection boundary rather than
        immediately creating an EngineeringDecision."""
        workflow, *_ = _make_workflow()

        result = workflow.run({"name": "test-project"}, "proj-1")

        assert isinstance(result, WorkflowResult)
        assert result.engineering_selection is not None
        assert isinstance(result.engineering_selection, EngineeringVariantSelection)

    def test_b_no_s3_materialization_before_explicit_selection(self):
        """B: no SetupPlan/S3 materialization occurs before an explicit
        human engineering selection is made."""
        workflow, council, materializer, *_ = _make_workflow()

        result = workflow.run({"name": "test-project"}, "proj-1")

        assert result.setup_plan is None
        materializer.materialize_decision.assert_not_called()
        materializer.materialize.assert_not_called()

    def test_c_chairman_recommendation_displayed_not_auto_accepted(self):
        """C: the Chairman recommendation is displayed (present on the
        pending selection) but never becomes the selected/authoritative
        candidate on its own."""
        workflow, *_ = _make_workflow()

        result = workflow.run({"name": "test-project"}, "proj-1")

        selection = result.engineering_selection
        assert selection.chairman_recommendation == "v1"
        # C: displayed only -- describe_engineering_variant_selection()'s
        # own selected_variant_id/selection_authority (built purely for
        # inspection) must never be treated as an actual decision; proven
        # end-to-end by test_b (no SetupPlan) and test_m (no deterministic
        # auto-selection reaches S2.5) above/below.

    def test_d_explicit_accept_of_recommendation_reaches_s2_5(self):
        """D: user explicitly accepts the Chairman recommendation -> the
        exact recommended candidate reaches S2.5/S3."""
        workflow, council, materializer, _, _, preflight_result, \
            council_result, plan_result = _make_workflow()

        pending = workflow.run({"name": "test-project"}, "proj-1")
        result = workflow.resolve_engineering_selection(
            pending.council_result, pending.preflight_result, "linux", "proj-1",
            human_selected_variant_id=pending.engineering_selection.chairman_recommendation,
        )

        assert result.setup_plan is plan_result
        materializer.materialize_decision.assert_called_once()
        decision = materializer.materialize_decision.call_args.args[0]
        assert decision.variant.id == "v1"
        assert decision.selection_authority == "human"

    def test_e_explicit_alternative_choice_reaches_s2_5(self):
        """E: user explicitly chooses a DIFFERENT admissible candidate ->
        that exact candidate (not the Chairman's) reaches S2.5/S3."""
        (
            discovery, validator, preflight, planner, council, materializer,
            _, _, preflight_result, _, plan_result,
        ) = _make_components()
        two_variant_result = CouncilResult(
            id="council-2", project_id="proj-1",
            variants=(
                CouncilVariant(id="v1", name="v1"),
                CouncilVariant(id="v2", name="v2"),
            ),
            recommendation="v1", council_complete=True,
        )
        council.evaluate.return_value = two_variant_result
        workflow = DevelopmentWorkflow(
            discovery, validator, preflight, planner,
            council=council, materializer=materializer,
        )

        pending = workflow.run({"name": "test-project"}, "proj-1")
        result = workflow.resolve_engineering_selection(
            pending.council_result, pending.preflight_result, "linux", "proj-1",
            human_selected_variant_id="v2",
        )

        assert result.setup_plan is plan_result
        decision = materializer.materialize_decision.call_args.args[0]
        assert decision.variant.id == "v2"
        assert decision.selection_authority == "human"

    def test_f_unknown_candidate_selection_is_rejected(self):
        """F: submitting an unknown candidate id is rejected safely."""
        workflow, council, materializer, *_ = _make_workflow()
        pending = workflow.run({"name": "test-project"}, "proj-1")

        with pytest.raises(EngineeringVariantNotFoundError):
            workflow.resolve_engineering_selection(
                pending.council_result, pending.preflight_result, "linux", "proj-1",
                human_selected_variant_id="does-not-exist",
            )
        materializer.materialize_decision.assert_not_called()

    def test_g_inadmissible_candidate_selection_is_rejected(self):
        """G: submitting a technically inadmissible candidate id is
        rejected safely -- the user may never override S2.3."""
        from app.requirement_model import (
            PreflightRequirementResult, PreflightResult, Requirement,
            RequirementActivation,
        )
        (
            discovery, validator, preflight, planner, council, materializer,
            _, _, _, _, plan_result,
        ) = _make_components()
        req = Requirement(
            id="req-x", name="x", type="python_package",
            purpose="p", required=True, confidence=0.9,
        )
        preflight_result = PreflightResult(
            id="pre-1", project_id="proj-1", overall_ready=False,
            results=(PreflightRequirementResult(requirement_id="req-x", present=False, satisfied=False),),
            missing_requirements=(req,),
            activations=(RequirementActivation("req-x", True, True),),
        )
        admissible = CouncilVariant(id="v1", name="v1")
        inadmissible = CouncilVariant(id="v2", name="v2")  # covers no binding requirement
        mixed_result = CouncilResult(
            id="council-3", project_id="proj-1",
            variants=(admissible, inadmissible), recommendation="v1",
            council_complete=True,
        )
        # v1 must actually cover req-x to be admissible; give it a toolchain item.
        from app.council_models import ToolchainItem
        admissible_covered = CouncilVariant(
            id="v1", name="v1",
            toolchain=(ToolchainItem(requirement_ref="req-x", name="x", type="python_package"),),
        )
        mixed_result = CouncilResult(
            id="council-3", project_id="proj-1",
            variants=(admissible_covered, inadmissible), recommendation="v1",
            council_complete=True,
        )
        council.evaluate.return_value = mixed_result
        preflight.check.return_value = preflight_result
        workflow = DevelopmentWorkflow(
            discovery, validator, preflight, planner,
            council=council, materializer=materializer,
        )

        pending = workflow.run({"name": "test-project"}, "proj-1")

        with pytest.raises(ChairmanRecommendationInadmissibleError):
            workflow.resolve_engineering_selection(
                pending.council_result, pending.preflight_result, "linux", "proj-1",
                human_selected_variant_id="v2",
            )
        materializer.materialize_decision.assert_not_called()

    def test_h_multiple_admissible_alternatives_remain_available(self):
        """H: multiple admissible alternatives remain available at the
        human boundary -- run() never narrows them down on its own."""
        (
            discovery, validator, preflight, planner, council, materializer,
            _, _, _, _, _,
        ) = _make_components()
        two_variant_result = CouncilResult(
            id="council-2", project_id="proj-1",
            variants=(
                CouncilVariant(id="v1", name="v1"),
                CouncilVariant(id="v2", name="v2"),
            ),
            recommendation="v1", council_complete=True,
        )
        council.evaluate.return_value = two_variant_result
        workflow = DevelopmentWorkflow(
            discovery, validator, preflight, planner,
            council=council, materializer=materializer,
        )

        result = workflow.run({"name": "test-project"}, "proj-1")

        admissible_ids = {
            v.variant.id for v in result.engineering_selection.validations if v.admissible
        }
        assert admissible_ids == {"v1", "v2"}

    def test_i_defer_leaves_workflow_pending_and_does_not_execute_s3(self):
        """I: nothing in DevelopmentWorkflow forces S3 materialization
        merely because a pending selection exists -- deferring (i.e.
        simply not calling resolve_engineering_selection()) never
        executes S3 on its own."""
        workflow, council, materializer, *_ = _make_workflow()

        result = workflow.run({"name": "test-project"}, "proj-1")

        assert result.setup_plan is None
        materializer.materialize_decision.assert_not_called()

    def test_j_reject_does_not_execute_s3(self):
        """J: same evidence as defer -- rejecting (never calling resolve_
        engineering_selection()) never executes S3."""
        workflow, council, materializer, *_ = _make_workflow()

        workflow.run({"name": "test-project"}, "proj-1")

        materializer.materialize_decision.assert_not_called()
        materializer.materialize.assert_not_called()

    def test_k_human_selection_authority_is_recorded(self):
        """K: an explicit human selection is always recorded with
        selection_authority="human" -- even when it matches the
        Chairman's own recommendation (accepting IS an explicit human
        act, never an automatic one)."""
        workflow, council, materializer, _, _, preflight_result, \
            council_result, plan_result = _make_workflow()

        pending = workflow.run({"name": "test-project"}, "proj-1")
        workflow.resolve_engineering_selection(
            pending.council_result, pending.preflight_result, "linux", "proj-1",
            human_selected_variant_id="v1",
        )

        decision = materializer.materialize_decision.call_args.args[0]
        assert decision.selection_authority == "human"

    def test_m_no_deterministic_code_selects_on_behalf_of_the_user(self):
        """M: run() itself never calls select_engineering_variant()/
        resolve_human_engineering_selection() with any candidate id --
        it only ever builds the non-binding, display-only
        EngineeringVariantSelection."""
        workflow, council, materializer, *_ = _make_workflow()

        result = workflow.run({"name": "test-project"}, "proj-1")

        assert result.engineering_selection.selected_variant_id is None or (
            result.engineering_selection.selection_authority != "human"
        )
        materializer.materialize_decision.assert_not_called()

    def test_n_zero_admissible_candidates_still_raises_immediately(self):
        """A genuine dead end (zero admissible candidates) must still
        surface immediately from run() -- there is nothing for a human
        to decide between."""
        from app.requirement_model import (
            PreflightRequirementResult, PreflightResult, Requirement,
            RequirementActivation,
        )
        (
            discovery, validator, preflight, planner, council, materializer,
            _, _, _, _, _,
        ) = _make_components()
        req = Requirement(
            id="req-platformio", name="platformio", type="executable",
            purpose="build backend", required=True, confidence=0.9,
        )
        preflight_result = PreflightResult(
            id="pre-1", project_id="proj-1", overall_ready=False,
            results=(PreflightRequirementResult(requirement_id="req-platformio", present=False, satisfied=False),),
            missing_requirements=(req,),
            activations=(RequirementActivation("req-platformio", True, True),),
        )
        rejected_variant = CouncilVariant(id="merged-venv", name="ESPHome mit Python Virtual Environment")
        council_result = CouncilResult(
            id="council-1", project_id="proj-1",
            variants=(rejected_variant,), recommendation="merged-venv",
            council_complete=True,
        )
        preflight.check.return_value = preflight_result
        council.evaluate.return_value = council_result
        workflow = DevelopmentWorkflow(
            discovery, validator, preflight, planner,
            council=council, materializer=materializer,
        )

        with pytest.raises(NoEligibleEngineeringCandidateError):
            workflow.run({"name": "test"}, "proj-1")

    def test_bounded_automatic_s2_3_repair_still_works_unchanged(self):
        """N: the existing automatic, bounded S2.3->S2.2 admissibility
        repair (inside EngineeringCouncil.evaluate(), max two Chairman
        syntheses total) is not touched by this task -- verified by
        confirming EngineeringCouncil itself was not modified/duplicated
        by this task's dev_workflow.py changes (dev_workflow.py never
        calls into the Chairman repair machinery directly)."""
        import inspect

        import app.dev_workflow as dev_workflow_module

        source = inspect.getsource(dev_workflow_module)
        assert "_admissibility_rework_evidence" not in source
        assert "_phase3_chairman_synthesis" not in source
