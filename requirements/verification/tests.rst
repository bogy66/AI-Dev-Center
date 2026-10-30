ADC Verification Tests
======================

Real tests that behaviorally verify Requirement obligations — not import
success, not mere reachability, not mocked-everything. Each links to the
specific Requirement(s) whose obligation its assertions actually prove.

``verification_result`` is set from the actually-observed pytest outcome at
the time evidence was captured (see verification/evidence.rst) — never
inferred from a test merely existing.

.. test:: External entry request preserves intent, no shared mutable defaults
   :id: TEST_001
   :status: draft
   :verification_result: IO
   :verifies: IF_REQ_002

   tests/test_common_request.py::test_common_request_preserves_adapter_neutral_user_intent,
   ::test_common_requests_do_not_share_project_info_defaults

.. test:: Requirement ID lineage survives loss/drift/duplication into S2.3
   :id: TEST_002
   :status: draft
   :verification_result: IO
   :verifies: IF_REQ_006

   tests/test_requirement_lineage.py::TestRequirementLineageThroughS23
   (5 cases: preserved ID accepted; lost, drifted, semantic-duplicate, and
   incompatibly-duplicated IDs each independently caught as missing
   binding coverage)

.. test:: Council Phase 1/2 produce independent, cross-reviewed proposals
   :id: TEST_003
   :status: draft
   :verification_result: IO
   :verifies: ARC_REQ_003, SUB_REQ_003, IF_REQ_007

   tests/test_engineering_council.py::TestPhase1DataIsolation,
   ::TestPhase1Parallelism, ::TestPhase2DataIsolation (and related
   Phase-1/Phase-2 classes in the same file)

.. test:: Chairman synthesizes a recommendation with one bounded repair
   :id: TEST_004
   :status: draft
   :verification_result: IO
   :verifies: SUB_REQ_004

   tests/test_engineering_council.py::TestBoundedChairmanRepair

.. test:: S2.3 admissibility classifies candidates independent of recommendation
   :id: TEST_005
   :status: draft
   :verification_result: IO
   :verifies: ARC_REQ_004, SUB_REQ_005

   tests/test_engineering_decision.py (validate_variants / validate_candidates
   core admissibility test classes)

.. test:: Structured rework feedback distinguishes repairable causes
   :id: TEST_006
   :status: draft
   :verification_result: IO
   :verifies: IF_REQ_010

   tests/test_engineering_decision.py (EngineeringReworkRequest.from_validation
   test classes)

.. test:: Human authority never overrides inadmissibility; zero-eligible fails closed
   :id: TEST_007
   :status: draft
   :verification_result: IO
   :verifies: SUB_REQ_006, IF_REQ_011

   tests/test_engineering_decision.py (resolve_human_engineering_selection
   test classes)

.. test:: Selection resolves only an existing admissible candidate
   :id: TEST_008
   :status: draft
   :verification_result: IO
   :verifies: IF_REQ_012

   tests/test_engineering_decision.py (select_engineering_variant test
   classes)

.. test:: S2.5 to S3 handoff carries exactly one EngineeringDecision artifact
   :id: TEST_009
   :status: draft
   :verification_result: IO
   :verifies: ARC_REQ_006, SUB_REQ_007, IF_REQ_013

   tests/test_s2_subsubsystem_architecture.py::TestBoundaryS2ToS3

.. test:: Setup planning classifies steps and never executes
   :id: TEST_010
   :status: draft
   :verification_result: IO
   :verifies: ARC_REQ_007, SUB_REQ_008, IF_REQ_014

   tests/test_toolchain_materializer.py (materialize_decision and
   _classify_item_baseline test classes)

.. test:: Setup approval binds to exact content, excludes manual_review
   :id: TEST_011
   :status: draft
   :verification_result: IO
   :verifies: ARC_REQ_008, SUB_REQ_009

   tests/test_setup_approval.py

.. test:: Controlled execution boundary enforces capability/approval/identity
   :id: TEST_012
   :status: draft
   :verification_result: IO
   :verifies: ARC_REQ_009, SUB_REQ_010, SUB_REQ_026, SUB_REQ_029

   tests/test_execution_boundary.py::TestExecuteControlled,
   ::TestExecuteStepControlled, ::TestNoInstall, ::TestNoShell,
   ::TestNoHardware

.. test:: Execution state fails closed on unknown state, reuses known success
   :id: TEST_013
   :status: draft
   :verification_result: IO
   :verifies: SUB_REQ_011, IF_REQ_016

   tests/test_setup_execution_state.py::TestValidTransitions,
   ::TestIllegalTransitions, ::TestCorruptStateFailsClosed,
   ::TestProjectPlanStepBinding

.. test:: Missing-toolchain recovery is bounded, approval-bound, non-repeating
   :id: TEST_014
   :status: draft
   :verification_result: IO
   :verifies: SUB_REQ_012, IF_REQ_029, IF_REQ_030, ARC_REQ_023, SUB_REQ_025

   tests/test_missing_toolchain_setup.py::test_tool_unavailable_does_not_install_automatically,
   ::test_setup_cannot_execute_before_approval,
   ::test_approved_structured_setup_executes_once,
   ::test_already_available_toolchain_is_not_reinstalled,
   ::test_restart_does_not_repeat_completed_installation,
   ::test_missing_toolchain_recovery_preserves_human_selected_engineering_decision,
   ::test_retry_uses_persisted_existing_verification_plan

.. test:: Development never starts after unapproved or failed setup
   :id: TEST_015
   :status: draft
   :verification_result: IO
   :verifies: IF_REQ_017

   tests/test_development_testing_integration.py::test_unapproved_setup_never_starts_development_testing,
   ::test_failed_setup_never_starts_development_testing

.. test:: Empty development change set fails; S4.1 has no no-op authority
   :id: TEST_016
   :status: draft
   :verification_result: IO
   :verifies: ARC_REQ_012, SUB_REQ_013

   tests/test_s4_subsubsystem_architecture.py::TestS4_1_DevelopmentChangeGeneration

.. test:: Test-change no-op requires explicit disposition and reason
   :id: TEST_017
   :status: draft
   :verification_result: IO
   :verifies: SUB_REQ_014, IF_REQ_019

   tests/test_s42_test_change_noop_contract.py

.. test:: Change application is the sole path to disk; unsafe paths fail closed
   :id: TEST_018
   :status: draft
   :verification_result: IO
   :verifies: SUB_REQ_015, IF_REQ_018

   tests/test_s43_s44_path_safety.py, tests/test_change_application.py

.. test:: Change provenance captures baseline-before/event-after with attribution
   :id: TEST_019
   :status: draft
   :verification_result: IO
   :verifies: ARC_REQ_014, SUB_REQ_016, IF_REQ_020

   tests/test_change_provenance.py,
   tests/test_s4_subsubsystem_architecture.py::TestS4_4_ChangeProvenanceAttribution

.. test:: Verification never begins after partial/skipped required S4 mutation
   :id: TEST_020
   :status: draft
   :verification_result: IO
   :verifies: IF_REQ_021

   tests/test_development_testing_integration.py::test_development_mutation_through_a_symlink_escape_blocks_s5,
   ::test_valid_explicit_no_op_test_mutation_is_not_required_and_s5_still_starts,
   ::test_development_mutation_is_always_required_even_for_a_no_op_test_cycle,
   ::test_successful_required_mutations_permit_s5

.. test:: Verification plan derivation stays central and ecosystem-neutral
   :id: TEST_021
   :status: draft
   :verification_result: IO
   :verifies: SUB_REQ_017, IF_REQ_022

   tests/test_s5_subsubsystem_architecture.py::TestS5_1_VerificationPlanning

.. test:: Controlled runners preserve full per-step result fidelity
   :id: TEST_022
   :status: draft
   :verification_result: IO
   :verifies: ARC_REQ_016, SUB_REQ_018, IF_REQ_023

   tests/test_s5_subsubsystem_architecture.py::TestS5_2_ControlledVerificationExecution,
   tests/test_verification.py

.. test:: Evidence aggregation preserves each failing step individually
   :id: TEST_023
   :status: draft
   :verification_result: IO
   :verifies: SUB_REQ_019

   tests/test_development_testing_stage.py (test_result_from_verification /
   step_failure_evidence test classes)

.. test:: Diagnostic formatting is deterministic and has no authority
   :id: TEST_024
   :status: draft
   :verification_result: IO
   :verifies: SUB_REQ_020, IF_REQ_024

   tests/test_diagnostic_evidence.py

.. test:: Diagnosis interpretation fails closed, cannot accept real failure
   :id: TEST_025
   :status: draft
   :verification_result: IO
   :verifies: SUB_REQ_021, IF_REQ_025

   tests/test_testing_stage.py (DiagnosisReviewer test classes)

.. test:: Real failure/timeout forces rework regardless of interpretation
   :id: TEST_026
   :status: draft
   :verification_result: IO
   :verifies: SUB_REQ_022, IF_REQ_026

   tests/test_testing_stage.py (TestingStage.run test classes)

.. test:: Rework is bounded to exactly one cycle with attributable evidence
   :id: TEST_027
   :status: draft
   :verification_result: IO
   :verifies: ARC_REQ_021, SUB_REQ_023, IF_REQ_027, IF_REQ_028

   tests/test_controlled_rework_stage.py,
   tests/test_rework_diagnostic_fidelity.py

.. test:: Controlled Git commit blocks on foreign/unaccounted changes
   :id: TEST_028
   :status: draft
   :verification_result: IO
   :verifies: SUB_REQ_024, IF_REQ_031

   tests/test_controlled_git_stage.py::test_preexisting_foreign_untracked_file_does_not_block_the_approved_commit,
   ::test_new_foreign_untracked_file_introduced_during_the_run_blocks_commit,
   ::test_mixed_preexisting_and_new_foreign_changes_only_the_new_one_blocks,
   ::test_controlled_stage_uses_fixed_argv_and_forbidden_git_actions_are_absent,
   tests/test_final_approval.py::test_rejection_is_terminal_and_isolated_to_its_run,
   ::test_final_approval_requires_a_persisted_accepted_run

.. test:: Publish requires a committed basis and its own distinct approval
   :id: TEST_029
   :status: draft
   :verification_result: IO
   :verifies: IF_REQ_032

   tests/test_controlled_publish_stage.py::test_committed_run_creates_separate_pending_publish_approval,
   ::test_missing_commit_basis_never_pushes,
   ::test_unsuccessful_git_commit_result_never_becomes_ready,
   ::test_additional_foreign_local_commit_blocks_without_push

.. test:: Diagnostic trace redacts secrets and cannot grant delivery authority
   :id: TEST_030
   :status: draft
   :verification_result: IO
   :verifies: SUB_REQ_028, IF_REQ_033

   tests/test_central_diagnostic_trace.py::test_secret_redaction_and_detail_allowlist_protect_persisted_jsonl,
   ::test_trace_content_cannot_approve_or_release_publish_gate
