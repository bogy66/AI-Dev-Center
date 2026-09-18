"""Central test-selector -> TEST_* mapping, reusing the TEST_* catalog
established by CLAUDE-ADC-SPHINX-IMPLEMENTATION-TEST-EVIDENCE-MAPPING-001
(requirements/verification/tests.rst). This is the ONLY place a raw
pytest selector is translated into a Requirement-Test id -- an ordinary
ADC test never has to know its own TEST_* id (CLAUDE-ADC-TESTBED-
EVIDENCE-INFRASTRUCTURE-001, section H/I).

Each entry lists the selectors that TEST_ID's `.. test::` body in
tests.rst cites. A selector is one of:
  - "path::Class"    matches nodeid == "path::Class" or "path::Class::..."
  - "path::function" matches nodeid == "path::function" or a
                      parametrized "path::function[...]"
  - "path"            matches any nodeid whose file part is exactly `path`
                       (whole-file-level Requirement coverage, used where
                       tests.rst cites a whole file with no narrower
                       selector)

If tests.rst's TEST_* catalog changes, this table must be kept in sync
by hand -- it is not auto-parsed from the RST prose, several entries in
tests.rst describe their scope in prose rather than exact node ids (see
CLAUDE-ADC-TESTBED-EVIDENCE-INFRASTRUCTURE-001's final report for the
six entries -- test_engineering_decision.py x4 and test_testing_stage.py
x2 -- resolved to exact classes/functions by reading the underlying
test code, since tests.rst's own prose was not literal enough to parse
mechanically without risking an incorrect or over-broad mapping).
"""

SELECTOR_MAP = {
    "TEST_001": [
        "tests/test_common_request.py::test_common_request_preserves_adapter_neutral_user_intent",
        "tests/test_common_request.py::test_common_requests_do_not_share_project_info_defaults",
    ],
    "TEST_002": [
        "tests/test_requirement_lineage.py::TestRequirementLineageThroughS23",
    ],
    "TEST_003": [
        "tests/test_engineering_council.py::TestPhase1DataIsolation",
        "tests/test_engineering_council.py::TestPhase1Parallelism",
        "tests/test_engineering_council.py::TestPhase2DataIsolation",
    ],
    "TEST_004": [
        "tests/test_engineering_council.py::TestBoundedChairmanRepair",
    ],
    "TEST_005": [
        # validate_variants / validate_candidates core admissibility.
        "tests/test_engineering_decision.py::TestBindingRequirementCoverage",
        "tests/test_engineering_decision.py::TestConstraintEnforcement",
        "tests/test_engineering_decision.py::TestMaterializabilityEligibility",
        "tests/test_engineering_decision.py::TestMultipleAdmissibleSolutionsCoexist",
        # NOTE: TestProposalOrderAndProseIndependence deliberately excluded
        # during review -- it calls select_engineering_variant and asserts
        # SELECTION determinism regardless of proposal order, not
        # validate_variants/validate_candidates admissibility itself. Left
        # genuinely unmapped rather than force-fit here or into TEST_007/008.
        "tests/test_engineering_decision.py::TestAdmissibleVariantsHelper",
        "tests/test_engineering_decision.py::TestMultipleBindingRequirementsCoverage",
        "tests/test_engineering_decision.py::TestNonBindingRequirementsDoNotAffectAdmissibility",
        "tests/test_engineering_decision.py::TestProvidedByWithinAVariantSatisfiesCoverage",
        "tests/test_engineering_decision.py::TestManualReviewSemanticsAreNotStale",
        "tests/test_engineering_decision.py::TestPerCandidateFailureEvidence",
        "tests/test_engineering_decision.py::TestVerificationCoverageAdmissibility",
        "tests/test_engineering_decision.py::TestRealE2E8MaterializabilityDiagnostics",
        "tests/test_engineering_decision.py::TestMaterializerBindingDiagnostics",
        "tests/test_engineering_decision.py::TestEnvironmentScopedBindingRequirements",
        "tests/test_engineering_decision.py::TestProductiveCouncilCandidatePipeline",
        "tests/test_engineering_decision.py::TestStructuredFailureDiagnosticsOnZeroAdmissibleCandidates",
    ],
    "TEST_006": [
        # EngineeringReworkRequest.from_validation.
        "tests/test_engineering_decision.py::TestStructuredReworkEvidenceSurvivesHostileIds",
    ],
    "TEST_007": [
        # resolve_human_engineering_selection.
        "tests/test_engineering_decision.py::TestChairmanRecommendationIsNotOverridden",
        "tests/test_engineering_decision.py::TestNoForcedTieBreakWithoutARecommendation",
        "tests/test_engineering_decision.py::TestHumanVariantSelection",
    ],
    "TEST_008": [
        # select_engineering_variant (the composed S2.3->S2.4->S2.5 entrypoint).
        # NOTE: TestSelectedVariantReachesS3Unchanged was deliberately excluded
        # here during review -- it calls ToolchainMaterializer().materialize()
        # directly, never select_engineering_variant, so including it would
        # have over-mapped TEST_008 to a class that does not actually exercise
        # the function TEST_008 claims to verify.
        "tests/test_engineering_decision.py::TestSolutionClassDistinguishability",
    ],
    "TEST_009": [
        "tests/test_s2_subsubsystem_architecture.py::TestBoundaryS2ToS3",
    ],
    "TEST_010": [
        "tests/test_toolchain_materializer.py",
    ],
    "TEST_011": [
        "tests/test_setup_approval.py",
    ],
    "TEST_012": [
        "tests/test_execution_boundary.py::TestExecuteControlled",
        "tests/test_execution_boundary.py::TestExecuteStepControlled",
        "tests/test_execution_boundary.py::TestNoInstall",
        "tests/test_execution_boundary.py::TestNoShell",
        "tests/test_execution_boundary.py::TestNoHardware",
    ],
    "TEST_013": [
        "tests/test_setup_execution_state.py::TestValidTransitions",
        "tests/test_setup_execution_state.py::TestIllegalTransitions",
        "tests/test_setup_execution_state.py::TestCorruptStateFailsClosed",
        "tests/test_setup_execution_state.py::TestProjectPlanStepBinding",
    ],
    "TEST_014": [
        "tests/test_missing_toolchain_setup.py::test_tool_unavailable_does_not_install_automatically",
        "tests/test_missing_toolchain_setup.py::test_setup_cannot_execute_before_approval",
        "tests/test_missing_toolchain_setup.py::test_approved_structured_setup_executes_once",
        "tests/test_missing_toolchain_setup.py::test_already_available_toolchain_is_not_reinstalled",
        "tests/test_missing_toolchain_setup.py::test_restart_does_not_repeat_completed_installation",
        "tests/test_missing_toolchain_setup.py::test_missing_toolchain_recovery_preserves_human_selected_engineering_decision",
        "tests/test_missing_toolchain_setup.py::test_retry_uses_persisted_existing_verification_plan",
    ],
    "TEST_015": [
        "tests/test_development_testing_integration.py::test_unapproved_setup_never_starts_development_testing",
        "tests/test_development_testing_integration.py::test_failed_setup_never_starts_development_testing",
    ],
    "TEST_016": [
        "tests/test_s4_subsubsystem_architecture.py::TestS4_1_DevelopmentChangeGeneration",
    ],
    "TEST_017": [
        "tests/test_s42_test_change_noop_contract.py",
    ],
    "TEST_018": [
        "tests/test_s43_s44_path_safety.py",
        "tests/test_change_application.py",
    ],
    "TEST_019": [
        "tests/test_change_provenance.py",
        "tests/test_s4_subsubsystem_architecture.py::TestS4_4_ChangeProvenanceAttribution",
    ],
    "TEST_020": [
        "tests/test_development_testing_integration.py::test_development_mutation_through_a_symlink_escape_blocks_s5",
        "tests/test_development_testing_integration.py::test_valid_explicit_no_op_test_mutation_is_not_required_and_s5_still_starts",
        "tests/test_development_testing_integration.py::test_development_mutation_is_always_required_even_for_a_no_op_test_cycle",
        "tests/test_development_testing_integration.py::test_successful_required_mutations_permit_s5",
    ],
    "TEST_021": [
        "tests/test_s5_subsubsystem_architecture.py::TestS5_1_VerificationPlanning",
    ],
    "TEST_022": [
        "tests/test_s5_subsubsystem_architecture.py::TestS5_2_ControlledVerificationExecution",
        "tests/test_verification.py",
    ],
    "TEST_023": [
        "tests/test_development_testing_stage.py",
    ],
    "TEST_024": [
        "tests/test_diagnostic_evidence.py",
    ],
    "TEST_025": [
        # DiagnosisReviewer: the JSON review-contract parsing/validation surface.
        "tests/test_testing_stage.py::test_valid_accepted_json",
        "tests/test_testing_stage.py::test_valid_rework_required_json",
        "tests/test_testing_stage.py::test_summary_preserved",
        "tests/test_testing_stage.py::test_invalid_json_rejected",
        "tests/test_testing_stage.py::test_prose_rejected",
        "tests/test_testing_stage.py::test_legacy_exact_string_rejected",
        "tests/test_testing_stage.py::test_legacy_rework_string_rejected",
        "tests/test_testing_stage.py::test_unsupported_decision_rejected",
        "tests/test_testing_stage.py::test_missing_decision_rejected",
        "tests/test_testing_stage.py::test_missing_summary_rejected",
        "tests/test_testing_stage.py::test_empty_summary_rejected",
        "tests/test_testing_stage.py::test_whitespace_only_summary_rejected",
        "tests/test_testing_stage.py::test_non_dict_root_rejected",
        "tests/test_testing_stage.py::test_decision_not_string_rejected",
        "tests/test_testing_stage.py::test_summary_with_leading_whitespace_trimmed",
        "tests/test_testing_stage.py::test_reviewer_prompt_has_no_legacy_exact_string_output",
        "tests/test_testing_stage.py::test_reviewer_contract_precedes_test_result",
    ],
    "TEST_026": [
        # TestingStage.run: fail-safe orchestration of the reviewer's verdict.
        "tests/test_testing_stage.py::test_fail_safe_testing_policy",
        "tests/test_testing_stage.py::test_reviewer_failure_is_review_failed_without_retry",
        "tests/test_testing_stage.py::test_failed_test_not_accepted_by_reviewer",
        "tests/test_testing_stage.py::test_timed_out_test_not_accepted_by_reviewer",
        "tests/test_testing_stage.py::test_invalid_reviewer_returns_review_failed",
        "tests/test_testing_stage.py::test_real_test_failure_still_requires_rework_when_diagnosis_reviewer_raises",
        "tests/test_testing_stage.py::test_timed_out_test_still_requires_rework_when_diagnosis_reviewer_raises",
        "tests/test_testing_stage.py::test_controlled_rework_stage_executes_rework_when_reviewer_raises_on_real_failure",
    ],
    "TEST_027": [
        "tests/test_controlled_rework_stage.py",
        "tests/test_rework_diagnostic_fidelity.py",
    ],
    "TEST_028": [
        "tests/test_controlled_git_stage.py::test_preexisting_foreign_untracked_file_does_not_block_the_approved_commit",
        "tests/test_controlled_git_stage.py::test_new_foreign_untracked_file_introduced_during_the_run_blocks_commit",
        "tests/test_controlled_git_stage.py::test_mixed_preexisting_and_new_foreign_changes_only_the_new_one_blocks",
        "tests/test_controlled_git_stage.py::test_controlled_stage_uses_fixed_argv_and_forbidden_git_actions_are_absent",
        "tests/test_final_approval.py::test_rejection_is_terminal_and_isolated_to_its_run",
        "tests/test_final_approval.py::test_final_approval_requires_a_persisted_accepted_run",
    ],
    "TEST_029": [
        "tests/test_controlled_publish_stage.py::test_committed_run_creates_separate_pending_publish_approval",
        "tests/test_controlled_publish_stage.py::test_missing_commit_basis_never_pushes",
        "tests/test_controlled_publish_stage.py::test_unsuccessful_git_commit_result_never_becomes_ready",
        "tests/test_controlled_publish_stage.py::test_additional_foreign_local_commit_blocks_without_push",
    ],
    "TEST_030": [
        "tests/test_central_diagnostic_trace.py::test_secret_redaction_and_detail_allowlist_protect_persisted_jsonl",
        "tests/test_central_diagnostic_trace.py::test_trace_content_cannot_approve_or_release_publish_gate",
    ],
}


def _selector_matches(selector, nodeid):
    file_part = nodeid.split("::", 1)[0]
    if "::" not in selector:
        # Whole-file selector.
        return file_part == selector
    return nodeid == selector or nodeid.startswith(selector + "::") or nodeid.startswith(selector + "[")


def resolve_selector(nodeid):
    """Return the TEST_* id whose selectors match `nodeid`, or None if
    unmapped. `nodeid` is a pytest node id, e.g.
    'tests/test_x.py::TestY::test_z' or 'tests/test_x.py::test_z'.

    Section H requires: an unmapped selector must be classified as
    UNMAPPED_TEST, never guessed at or defaulted to some TEST_* id.
    """
    matches = []
    for test_id, selectors in SELECTOR_MAP.items():
        for selector in selectors:
            if _selector_matches(selector, nodeid):
                matches.append(test_id)
                break
    # De-duplicate while preserving order; a nodeid should map to exactly
    # one TEST_* id under this table's design (checked by the regression
    # test test_selector_map_has_no_ambiguous_overlaps).
    seen = []
    for m in matches:
        if m not in seen:
            seen.append(m)
    if not seen:
        return None
    return seen[0]


def resolve_selector_all(nodeid):
    """Same as resolve_selector but returns every matching TEST_* id
    (used by the overlap-detection regression test)."""
    result = []
    for test_id, selectors in SELECTOR_MAP.items():
        for selector in selectors:
            if _selector_matches(selector, nodeid):
                result.append(test_id)
                break
    return result
