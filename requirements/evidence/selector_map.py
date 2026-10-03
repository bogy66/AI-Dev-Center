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
        # FIX019: permanent lifecycle/slot safety probes. A start claim
        # must not silently satisfy the stronger no-late-entry assertion.
        "tests/test_fix016_independent_regressions.py::test_provider_start_claim_does_not_prove_actual_handover",
        "tests/test_fix016_independent_regressions.py::test_coordinator_callback_cannot_block_deadline",
        "tests/test_fix016_independent_regressions.py::test_blocked_thinking_callback_does_not_leave_terminal_diagnosis_pending",
        "tests/test_fix016_independent_regressions.py::test_healthy_same_slot_waiters_succeed_and_release_capacity",
        "tests/test_fix016_independent_regressions.py::test_waiter_timeout_does_not_quarantine_healthy_holder",
        "tests/test_fix016_independent_regressions.py::test_result_callback_cannot_block_public_evaluate",
        "tests/test_fix019_architecture_regressions.py::test_slot_admission_survives_thread_bootstrap_observation",
        # FIX014 independent regressions of this existing boundary.
        "tests/test_council_trace_independent_regressions.py::test_processwide_capacity_admission_and_release_across_instances",
        "tests/test_council_trace_independent_regressions.py::test_same_slot_concurrent_timeouts_leave_at_most_one_abandoned_worker",
        "tests/test_council_trace_independent_regressions.py::test_no_retry_can_start_after_concurrent_timeout",
        "tests/test_council_trace_independent_regressions.py::test_completed_before_deadline_never_gets_second_timeout_terminal",
        "tests/test_fix014_remaining_regressions.py::test_finalization_remains_bounded_after_terminal_activity",
        "tests/test_fix014_remaining_regressions.py::test_provider_cannot_start_after_gate_check_races_finalization",
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
        "tests/test_installer_recovery_identity.py::test_active_binding_missing_controllable_requirement_yields_install_step",
        "tests/test_installer_recovery_identity.py::test_active_binding_unresolvable_requirement_is_explicit_and_blocks_development",
        "tests/test_installer_recovery_identity.py::test_inactive_requirement_remains_legitimately_deferred",
        # CLAUDE-ADC-RSE033-RESIDUAL-DISTRIBUTION-PTY-CLOSURE-FIX-003: a
        # no-verdict distribution query never becomes a missing requirement
        # or a SetupStep; a valid ABSENT verdict still does.
        "tests/test_distribution_no_verdict_preflight.py",
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
        "tests/test_execution_consolidation.py::test_install_with_project_root_routes_through_execute_controlled_and_confines_cwd",
        "tests/test_execution_consolidation.py::test_install_environment_is_allowlisted_not_fully_inherited",
        "tests/test_execution_consolidation.py::test_mcp_execute_setup_plan_routes_through_execute_controlled_with_correct_cwd",
        "tests/test_execution_target_authorization_negative.py::TestExecutionCountGuarantees::test_approved_target_executes_exactly_once",
        "tests/test_env_pairwise_helper.py",
        "tests/test_env_equivalence_classes.py",
        "tests/test_terminal_provider_surrogates.py",
        "tests/test_env_fault_matrix.py",
        "tests/test_env_pairwise_coverage.py",
        "tests/test_env_property_invariants.py",
        "tests/test_env_threeway_coverage.py",
        "tests/test_env_state_machine.py",
        "tests/test_execution_target_authorization_approved_content_immutability.py",
        "tests/test_execution_target_authorization_content_immutability_and_legacy.py",
        "tests/test_execution_target_authorization_cross_process.py",
        "tests/test_execution_target_authorization_generation.py",
        # CLAUDE-ADC-RSE033-RESIDUAL-DISTRIBUTION-PTY-CLOSURE-FIX-003: the
        # visible PTY launcher's final-child status/output fidelity
        # (ARC_REQ_009's execution-surface contract: real exit-status
        # propagation through every controlled execution surface), which
        # was outside every Gate-1 obligation.
        "tests/test_execution_presenter.py::test_pty_launcher_captures_nonzero_exit",
        "tests/test_execution_presenter.py::test_pty_launcher_preserves_command_env",
        "tests/test_execution_presenter.py::test_pty_launcher_result_json_from_exit_code_file",
        "tests/test_execution_presenter.py::test_exit_code_from_fifo_e2e",
        "tests/test_execution_presenter.py::test_one_shot_fifo_e2e",
        "tests/test_pty_final_child_fidelity.py",
        # Independent final-child authority regressions (autonomy pilot 001).
        "tests/test_pty_component_contracts.py",
        "tests/test_terminal_result_authority.py",
        "tests/test_terminal_status_adversarial.py",
        "tests/test_terminal_status_v3_contract.py",
    ],
    "TEST_013": [
        "tests/test_setup_execution_state.py::TestValidTransitions",
        "tests/test_setup_execution_state.py::TestIllegalTransitions",
        "tests/test_setup_execution_state.py::TestCorruptStateFailsClosed",
        "tests/test_setup_execution_state.py::TestProjectPlanStepBinding",
        "tests/test_execution_target_authorization_retry_system.py::test_web_http_boundary_retry_launches_zero_additional_processes",
        "tests/test_execution_target_authorization_retry_system.py::test_mcp_boundary_retry_launches_zero_additional_processes",
    ],
    "TEST_014": [
        "tests/test_missing_toolchain_setup.py::test_tool_unavailable_does_not_install_automatically",
        "tests/test_missing_toolchain_setup.py::test_setup_cannot_execute_before_approval",
        "tests/test_missing_toolchain_setup.py::test_approved_structured_setup_executes_once",
        "tests/test_missing_toolchain_setup.py::test_already_available_toolchain_is_not_reinstalled",
        "tests/test_missing_toolchain_setup.py::test_restart_does_not_repeat_completed_installation",
        "tests/test_missing_toolchain_setup.py::test_missing_toolchain_recovery_preserves_human_selected_engineering_decision",
        "tests/test_missing_toolchain_setup.py::test_retry_uses_persisted_existing_verification_plan",
        "tests/test_s3_missing_toolchain_capability_authorization.py::test_recovery_generated_install_reaches_real_capability_authorization_and_completes",
        "tests/test_s3_missing_toolchain_capability_authorization.py::test_pending_recovery_approval_yields_zero_authorization_and_zero_execution",
        "tests/test_s3_missing_toolchain_capability_authorization.py::test_rejected_recovery_approval_yields_zero_authorization_and_zero_execution",
        "tests/test_s3_missing_toolchain_capability_authorization.py::test_wrong_project_for_verification_plan_fails_closed",
        "tests/test_s3_missing_toolchain_capability_authorization.py::test_recovery_remains_bounded_and_non_repeating",
        "tests/test_s3_missing_toolchain_capability_authorization.py::test_failed_pre_execution_authorization_does_not_strand_recovery_as_executing",
        # IF_REQ_037 (CLAUDE-ADC-RSE033-INSTALLER-RECOVERY-CLOSURE-FIX-002):
        # central installer-identity resolution, explicit distinct-identity
        # correlation and fail-closed reverification at unit depth. The
        # cross-subsystem S5 -> S3.5 composition is Gate 2
        # (gate2_selector_map.GATE2_S5_S3_BOUNDED_RECOVERY), never here.
        "tests/test_installer_recovery_identity.py::test_supported_forms_resolve_through_materializer_to_one_registered_installer",
        "tests/test_installer_recovery_identity.py::test_unsupported_forms_never_become_install_steps_or_resolve",
        "tests/test_installer_recovery_identity.py::test_package_identity_is_never_used_as_installer_identity",
        "tests/test_installer_recovery_identity.py::test_uncontrolled_effect_resolves_to_no_installer",
        "tests/test_installer_recovery_identity.py::test_executable_correlates_to_provider_through_declared_provided_by",
        "tests/test_installer_recovery_identity.py::test_package_identity_alone_never_correlates_to_an_executable",
        "tests/test_installer_recovery_identity.py::test_ambiguous_or_broken_correlation_fails_closed",
        "tests/test_installer_recovery_identity.py::test_distinct_identities_correlate_only_through_explicit_relations",
        "tests/test_missing_toolchain_setup.py::test_passing_reverification_completes_recovery_once",
        "tests/test_missing_toolchain_setup.py::test_failed_reverification_never_reports_recovery_completed",
        "tests/test_missing_toolchain_setup.py::test_reverification_without_a_structured_result_fails_closed",
        # IF_REQ_029: an execution error of a started tool never takes the
        # S5 -> S3.5 route; a genuinely unavailable tool still does.
        "tests/test_verification_execution_error.py::TestExecutionErrorToolchainRecoveryBoundary",
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
        # FIX014 independent regressions of this existing boundary.
        "tests/test_cross_subsystem_independent_regressions.py::test_git_metadata_is_not_an_allowed_generated_change_target",
        "tests/test_cross_subsystem_independent_regressions.py::test_git_metadata_rejected_through_direct_and_symlink_targets",
        "tests/test_s43_s44_path_safety.py",
        "tests/test_change_application.py",
    ],
    "TEST_019": [
        "tests/test_change_provenance.py",
        "tests/test_s4_subsubsystem_architecture.py::TestS4_4_ChangeProvenanceAttribution",
    ],
    "TEST_020": [
        "tests/test_development_testing_stage.py::test_development_mutation_failure_never_reaches_verification",
        "tests/test_development_testing_stage.py::test_required_test_mutation_apply_failure_never_reaches_verification",
        "tests/test_development_testing_stage.py::test_explicit_no_op_test_mutation_is_not_required_and_verification_still_starts",
        "tests/test_development_testing_stage.py::test_verification_all_steps_passing_yields_a_passed_test_result",
    ],
    "TEST_021": [
        "tests/test_s5_subsubsystem_architecture.py::TestS5_1_VerificationPlanning",
        # IF_REQ_022: the execution budget is part of the step's execution
        # policy, written by the plan producer (DEF-RSE033-ESPHOME-COMPILE-TIMEOUT).
        "tests/test_verification_timeout_policy.py::TestVerificationBudgetPolicy",
    ],
    "TEST_022": [
        # FIX014 independent regressions of this existing boundary.
        "tests/test_cross_subsystem_independent_regressions.py::test_cmake_build_receives_configure_state_in_protected_workspace",
        "tests/test_fix014_remaining_regressions.py::test_branch_workspaces_do_not_consume_sibling_configuration",
        "tests/test_fix014_remaining_regressions.py::test_branched_productive_cmake_runners_keep_separate_caches",
        "tests/test_s5_subsubsystem_architecture.py::TestS5_2_ControlledVerificationExecution",
        "tests/test_verification.py",
        # Runners consume the step budget; the real process boundary
        # contains the timed-out process tree with str partial output.
        "tests/test_verification_timeout_policy.py::TestBudgetConsumptionAndProcessBoundary",
        # ARC_022 / IF_REQ_023: the launch boundary separates TOOL_UNAVAILABLE
        # (cannot start) from EXECUTION_ERROR (started, then failed).
        "tests/test_verification_execution_error.py::TestExecutionErrorClassification",
    ],
    "TEST_023": [
        # FIX014 independent regressions of this existing boundary.
        "tests/test_cross_subsystem_independent_regressions.py::test_mixed_verification_outcomes_keep_authoritative_failure",
        "tests/test_cross_subsystem_independent_regressions.py::test_mixed_failure_preserves_both_step_records_through_real_diagnosis",
        # Whole-file selector deliberately narrowed to exclude the four
        # functions TEST_020 now claims (added by
        # CLAUDE-ADC-TEST-ASSURANCE-AB-INTEGRATE-CORRECT-002's TEST_020
        # correction) -- a shared whole-file wildcard would otherwise
        # make those four selectors ambiguously match both TEST_020 and
        # TEST_023, which test_selector_map_has_no_ambiguous_overlaps
        # correctly rejects.
        "tests/test_development_testing_stage.py::test_runs_canonical_stages_once_in_order_and_preserves_real_results",
        "tests/test_development_testing_stage.py::test_uses_the_same_project_root_for_test_changes_and_test_execution",
        "tests/test_development_testing_stage.py::test_rework_result_is_returned_without_retrying_any_stage",
        "tests/test_development_testing_stage.py::test_review_failed_is_returned_without_accepted_fallback_or_retry",
        "tests/test_development_testing_stage.py::test_upstream_failure_stops_without_synthesizing_results",
        "tests/test_development_testing_stage.py::test_verification_failure_preserves_real_step_stdout_stderr_return_code",
        "tests/test_development_testing_stage.py::test_verification_multiple_failures_remain_individually_attributable",
        "tests/test_development_testing_stage.py::test_verification_no_executable_steps_never_falls_back_to_project_test_runner",
        "tests/test_development_testing_stage.py::test_verification_all_unsupported_steps_never_falls_back_to_project_test_runner",
        "tests/test_development_testing_stage.py::test_project_intelligence_exception_never_falls_back_to_project_test_runner",
        "tests/test_development_testing_stage.py::test_normal_generalized_pytest_verification_still_works",
        "tests/test_development_testing_stage.py::test_normal_generalized_cmake_firmware_verification_remains_unchanged",
        "tests/test_development_testing_stage.py::test_tool_unavailable_does_not_enter_developer_rework",
        "tests/test_development_testing_stage.py::test_tool_unavailable_carries_verification_plan_for_s3_5_recovery",
        "tests/test_development_testing_stage.py::test_actual_build_failure_still_reaches_rework",
        "tests/test_development_testing_stage.py::test_unsupported_verification_does_not_trigger_installation",
    ],
    "TEST_024": [
        "tests/test_diagnostic_evidence.py",
    ],
    "TEST_025": [
        # FIX014 independent regressions of this existing boundary.
        "tests/test_cross_subsystem_independent_regressions.py::test_reviewer_input_excludes_secret_values",
        "tests/test_fix014_remaining_regressions.py::test_reviewer_obeys_bounded_diagnostic_evidence_contract",
        "tests/test_fix014_remaining_regressions.py::test_reviewer_redacts_split_credential_argv",
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
        "tests/test_testing_stage.py::test_timed_out_test_without_diagnosis_fails_closed_when_diagnosis_reviewer_raises",
        "tests/test_testing_stage.py::test_controlled_rework_stage_executes_rework_when_reviewer_raises_on_real_failure",
        # IF_REQ_026 (clarified): TIMEOUT is fail-closed but only a
        # diagnosed source-correctable cause may use the bounded rework.
        "tests/test_verification_timeout_policy.py::TestTimeoutReworkClassification",
        # IF_REQ_026 (clarified): EXECUTION_ERROR is a fail-closed terminal
        # outcome that no diagnosis can turn into rework.
        "tests/test_verification_execution_error.py::TestExecutionErrorOutcomePolicy",
    ],
    "TEST_027": [
        # FIX014 independent regressions of this existing boundary.
        "tests/test_fix014_remaining_regressions.py::test_rework_redacts_split_credential_argv",
        "tests/test_cross_subsystem_independent_regressions.py::test_mixed_failure_then_source_rework_preserves_missing_tool_recovery_plan",
        "tests/test_controlled_rework_stage.py",
        "tests/test_rework_diagnostic_fidelity.py",
        # IF_REQ_027: EXECUTION_ERROR never consumes the bounded rework.
        "tests/test_verification_execution_error.py::TestExecutionErrorReworkBudget",
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
        # FIX014 independent regressions of this existing boundary.
        "tests/test_council_trace_independent_regressions.py::test_boundary_forms_persistence_and_levels",
        "tests/test_council_trace_independent_regressions.py::test_documented_serialized_character_budget_includes_overhead",
        "tests/test_central_diagnostic_trace.py::test_secret_redaction_and_detail_allowlist_protect_persisted_jsonl",
        "tests/test_central_diagnostic_trace.py::test_trace_content_cannot_approve_or_release_publish_gate",
        # KIB-ADC-RSE-DIAGNOSTIC-TRACE-TC-FIX-002: the extracted,
        # deterministic final-DiagnosticTrace-validation contract
        # (_validate_final_diagnostic_trace) tests the SAME
        # non-authority/redaction/structural-lineage obligation
        # (SUB_REQ_028, IF_REQ_033) TEST_030 already verifies -- via
        # real DiagnosticTraceEvent instances, never via
        # tests/real_system/real_system_e2e.py's own RSE selector
        # (that selector is reserved exclusively for TEST_033; a
        # focused run must never be able to mark the Real-System TEST
        # object IO).
        "tests/test_real_system_e2e_progress.py::test_validate_final_diagnostic_trace_accepts_a_realistic_real_shaped_trace",
        "tests/test_real_system_e2e_progress.py::test_validate_final_diagnostic_trace_never_calls_to_record",
        "tests/test_real_system_e2e_progress.py::test_validate_final_diagnostic_trace_checks_x_f_y_semantics",
        "tests/test_real_system_e2e_progress.py::test_validate_final_diagnostic_trace_checks_execution_identity_semantics",
        "tests/test_real_system_e2e_progress.py::test_validate_final_diagnostic_trace_checks_actor_phase_semantics",
        "tests/test_real_system_e2e_progress.py::test_validate_final_diagnostic_trace_rejects_forbidden_data",
        "tests/test_real_system_e2e_progress.py::test_diagnostic_detail_level_none_does_not_erase_persisted_audit_evidence",
        "tests/test_real_system_e2e_progress.py::test_validate_final_diagnostic_trace_fails_clearly_on_missing_task_description",
        "tests/test_real_system_e2e_progress.py::test_validate_final_diagnostic_trace_fails_clearly_on_empty_trace",
    ],
    "TEST_031": [
        "tests/test_verification_workspace_integrity.py",
    ],
    "TEST_032": [
        "tests/test_execution_boundary.py::TestSoftwareInstallationRoutesThroughVisibleTerminal",
        "tests/test_interactive_terminal.py",
    ],
    # KIB-ADC-RSE-DIAGNOSTIC-TRACE-TC-FIX-002: TEST_033 is exclusively
    # the Real-System-E2E acceptance selector. No focused/synthetic test
    # selector may ever be added here -- that is precisely the defect
    # this correction fixes (a focused run must never be able to mark
    # the Real-System TEST object IO). The failure-stage-diagnostic
    # regressions (_emit_failure_diagnostics/_phase_later_recovered) and
    # the selector-resolution regression are deliberately left UNMAPPED
    # to any TEST_* id: they verify TC/harness code quality, not a
    # product Requirement obligation, matching this file's own
    # already-established convention that not every pytest function
    # needs a Requirement-verifying mapping.
    "TEST_033": [
        "tests/real_system/real_system_e2e.py::test_real_esphome_esp32_hello_world_acceptance",
    ],
    # CLAUDE-ADC-YELLOW-VERIFICATION-CLOSURE-IMPLEMENT-001: IF_REQ_001's
    # identity/intent clauses are asserted by TEST_001's own selectors
    # (never remapped -- no-ambiguous-overlaps invariant); TEST_034 owns
    # the dedicated deterministic request-identity + run-scoped
    # correlation selectors that prove the COMPLETE IF_REQ_001 contract.
    "TEST_034": [
        "tests/test_request_identity_correlation.py::test_common_request_structured_identity_preserves_user_request_unchanged",
        "tests/test_request_identity_correlation.py::test_run_scoped_correlation_assigns_and_isolates_two_runs",
    ],
    "TEST_040": [
        "tests/test_target_environment_generation_contract.py::test_s3_s4_generation_and_production_s5_runner_use_the_same_target",
        "tests/test_target_environment_generation_contract.py::test_unavailable_target_environment_cannot_be_confirmed_by_host_verification",
        "tests/test_target_environment_generation_contract.py::test_plan_selected_target_that_cannot_be_observed_is_never_replaced",
        "tests/test_target_environment_generation_contract.py::test_plan_selected_target_is_the_verification_target_when_observed",
        "tests/test_target_environment_generation_contract.py::test_several_different_observed_targets_are_ambiguous_not_a_choice",
        "tests/test_missing_toolchain_setup.py::test_retry_without_established_target_is_blocked_and_never_runs_on_the_host",
        "tests/test_missing_toolchain_setup.py::test_retry_verifies_through_exactly_the_persisted_s5_target",
        "tests/test_target_bound_cli_boundary.py::test_detection_uses_only_the_selected_target_never_the_host_path",
        "tests/test_target_bound_cli_boundary.py::test_unknown_or_unusable_target_is_never_available",
        "tests/test_target_bound_cli_boundary.py::test_target_lookup_never_resolves_a_path_like_or_different_name",
        "tests/test_target_bound_cli_boundary.py::test_target_bound_request_requires_an_approved_target",
        "tests/test_target_bound_cli_boundary.py::test_approval_of_one_target_never_covers_another",
        "tests/test_target_bound_cli_boundary.py::test_host_resolved_or_bare_command_is_rejected_for_a_target_bound_request",
        "tests/test_target_bound_cli_boundary.py::test_target_bound_request_requires_a_capability_named_tool_that_exists",
        "tests/test_target_bound_cli_boundary.py::test_unusable_target_stays_fail_closed",
        "tests/test_target_bound_cli_boundary.py::test_target_approval_needs_complete_provenance_for_this_project",
        "tests/test_target_bound_cli_boundary.py::test_plan_selected_environment_is_approved_even_without_steps",
        "tests/test_target_bound_cli_boundary.py::test_execution_runs_exactly_the_target_tool_even_if_the_host_path_changes",
        "tests/test_target_bound_cli_boundary.py::test_runner_never_falls_back_to_a_host_tool_when_the_target_lacks_it",
        "tests/test_target_bound_cli_boundary.py::test_runner_executes_the_selected_target_tool_and_repeats_identically",
        "tests/test_target_bound_cli_boundary.py::test_target_environment_prose_lists_exactly_the_selector_map",
        "tests/test_development_testing_stage.py::test_legacy_s5_branch_without_established_target_never_runs_on_the_host",
        "tests/test_development_testing_stage.py::test_legacy_s5_branch_with_unusable_target_context_is_unconfirmed",
        "tests/test_development_testing_stage.py::test_legacy_s5_branch_runs_through_exactly_the_established_target",
        "tests/test_missing_toolchain_setup.py::test_retry_after_restart_re_establishes_the_target_approval",
        "tests/test_missing_toolchain_setup.py::test_retry_with_a_target_the_recovery_plan_did_not_select_is_blocked",
    ],
}


# Adoption 026: retain legacy declarations but separate their effective scope.
from .council_lifecycle_scope import separate_council_lifecycle

SELECTOR_MAP, LEGACY_COUNCIL_REPRODUCTIONS = separate_council_lifecycle(SELECTOR_MAP)

# ---------------------------------------------------------------------
# Selector-level gate scoping (KIA-ADC-GATE1-CONTAINMENT-GATE-SCOPING
# -FIX-001 sections 6-8). A handful of TEST_* ids (currently only
# TEST_032) legitimately verify BOTH a Gate-1 deterministic obligation
# AND a Gate-3 Real-System smoke test in the SAME `.. test::` object --
# unlike TEST_033, which is entirely, exclusively Gate-3. Rather than
# giving TEST_032 its own new TEST_* id (forbidden -- section 1) or a
# second, competing selector table, this ONE small, centralized,
# mechanically-inspectable set names the specific selectors, among
# SELECTOR_MAP's own entries, that are explicitly Gate-3-only:
# retained in SELECTOR_MAP unchanged (so resolve_selector/
# resolve_selector_all keep mapping their nodeids to their TEST_* id --
# Requirement-Test traceability is never deleted), but excluded from
# mandatory Gate-1 current-run/functional completion by
# current_run_completion.py and ingest.py, both of which import
# is_gate3_only_nodeid() from here rather than re-deciding gate scope
# independently. A whole-file selector (e.g. TEST_032's
# "tests/test_interactive_terminal.py") must never make an explicitly
# Gate-3-only nested item (its own real_system-marked smoke test) a
# mandatory Gate-1 selector merely because it happens to live in the
# same file as genuinely deterministic Gate-1 tests.
# ---------------------------------------------------------------------
GATE3_ONLY_SELECTORS = frozenset({
    "tests/test_interactive_terminal.py::TestRealTerminalSmoke",
})


def is_gate3_only_nodeid(nodeid: str) -> bool:
    """True when `nodeid` falls under an explicitly Gate-3-only
    selector -- i.e. it remains part of its TEST_*'s Requirement
    traceability (SELECTOR_MAP itself is never narrowed) but must never
    be treated as a mandatory Gate-1 obligation by current_run_completion.py
    or ingest.py's GATE1 functional-result aggregation."""
    return any(_selector_matches(sel, nodeid) for sel in GATE3_ONLY_SELECTORS)


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
