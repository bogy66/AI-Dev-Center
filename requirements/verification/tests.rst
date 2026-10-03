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

   CLAUDE-ADC-RSE033-INSTALLER-RECOVERY-CLOSURE-FIX-002: activation and
   installation state stay distinct at functional-unit depth -- an active
   binding missing requirement becomes an actionable install step or an
   explicit manual_review blocker that prevents development, while an
   inactive needs_install requirement remains legitimately DEFERRED.

   tests/test_installer_recovery_identity.py::test_active_binding_missing_controllable_requirement_yields_install_step,
   ::test_active_binding_unresolvable_requirement_is_explicit_and_blocks_development,
   ::test_inactive_requirement_remains_legitimately_deferred

   CLAUDE-ADC-RSE033-RESIDUAL-DISTRIBUTION-PTY-CLOSURE-FIX-003
   (DEF-RSE033-ESPHOME-COMPILE-TIMEOUT, NO_VERDICT_AS_ABSENCE_CLASSIFICATION):
   setup planning is fed only honest current-state evidence. Through real
   target-Python query processes and the real central execution boundary,
   present, absent, unavailable target, runtime crash, timeout and
   malformed answers stay distinct; a query without a valid presence
   verdict fails Preflight closed -- inside the real DevelopmentWorkflow it
   yields no missing requirement, no SetupStep, no Council and no
   materialization -- while a genuine ABSENT verdict still becomes a
   missing requirement and an install step.

   tests/test_distribution_no_verdict_preflight.py

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
   :verifies: ARC_REQ_009, SUB_REQ_010, SUB_REQ_026, SUB_REQ_029, IF_REQ_015

   KIB-ADC-CAPABILITY-AUTH-TERMINAL-BOUNDARY-TC-FIX-001: extended with
   the four previously-unmapped cwd-confinement/environment-allowlist/
   exactly-once/target-authorization regressions this Requirement's own
   declared "capability/approval/identity" scope already covers --
   tests/test_execution_consolidation.py and
   tests/test_execution_target_authorization_negative.py existed before
   this task but were referenced by no TEST object anywhere in this
   file or in requirements/evidence/selector_map.py, making their
   failures invisible to Requirements/Evidence-driven verification.
   Repaired to observe the FINAL CHILD process a controlled installation
   actually spawns (tests/terminal_final_child_probe.py) rather than a
   now-stale app.execution.subprocess.run spy, since every classified
   installation routes through InteractiveTerminalLauncher (see
   TEST_032) -- this does not narrow or weaken SUB_REQ_010/SUB_REQ_029's
   cwd/environment/identity/count guarantees, it proves them at the
   correct current observation point instead of an obsolete one.
   The integrated terminal-boundary fix now confines the final child to
   the controlled allowlisted environment while still giving the
   emulator only the desktop/session values it needs.

   CLAUDE-ADC-TEST-ENVIRONMENT-FIDELITY-UPGRADE-001: extended with a
   reusable, mechanically-enumerable equivalence-class/pairwise/3-way/
   state-machine/property/fault-injection test architecture
   (tests/env_scenarios.py's 94-class catalog across PROCESS,
   FILESYSTEM, ENVIRONMENT, TERMINAL, ARGV, TOOLCHAIN, AUTHORITY,
   LIFECYCLE and INTERFACE dimensions; tests/env_pairwise.py's own
   deterministic covering-array generator, since no pairwise/property
   -based library exists in this environment) proving this same
   Requirement's "capability/approval/identity" scope holds across
   realistic environment variation, not just the single representative
   case each pre-existing selector covered. Also safely corrected and
   included the four previously GATE-1-deferred CLAUDE-E2E-003I
   regressions (approved-content immutability, content immutability +
   legacy upgrade safety, real cross-process execution-claim races,
   setup-generation semantics), which shared the exact same "real,
   unmocked terminal boundary reachable via a bare PythonPackageExecutor()"
   safety gap as the four selectors above and are now routed through
   the same inert terminal boundary and deterministic verifier seam.
   tests/test_env_state_machine.py::TestMissingToolchainRecoveryStateMachine
   additionally strengthens TEST_014/SUB_REQ_012's own bounded-recovery
   claim through the same real S3.5 producer chain.

   tests/test_execution_boundary.py::TestExecuteControlled,
   ::TestExecuteStepControlled, ::TestNoInstall, ::TestNoShell,
   ::TestNoHardware,
   tests/test_execution_consolidation.py::test_install_with_project_root_routes_through_execute_controlled_and_confines_cwd,
   ::test_install_environment_is_allowlisted_not_fully_inherited,
   ::test_mcp_execute_setup_plan_routes_through_execute_controlled_with_correct_cwd,
   tests/test_execution_target_authorization_negative.py::TestExecutionCountGuarantees::test_approved_target_executes_exactly_once,
   tests/test_env_pairwise_helper.py, tests/test_env_equivalence_classes.py,
   tests/test_terminal_provider_surrogates.py, tests/test_env_fault_matrix.py,
   tests/test_env_pairwise_coverage.py, tests/test_env_property_invariants.py,
   tests/test_env_threeway_coverage.py, tests/test_env_state_machine.py,
   tests/test_execution_target_authorization_approved_content_immutability.py,
   tests/test_execution_target_authorization_content_immutability_and_legacy.py,
   tests/test_execution_target_authorization_cross_process.py,
   tests/test_execution_target_authorization_generation.py

   CLAUDE-ADC-RSE033-RESIDUAL-DISTRIBUTION-PTY-CLOSURE-FIX-003
   (DEF-RSE033-ESPHOME-COMPILE-TIMEOUT, FINAL_CHILD_STATUS_FIDELITY): the
   visible PTY launcher's result is the final command's own real exit
   status and output. Typed startup/completion records replace a fixed
   startup pause, so shell startup is never command completion; shell or
   launcher lifecycle status and later kill/reap never overwrite a
   recorded completion; a run without completion is fail-closed with no
   fabricated status.

   tests/test_execution_presenter.py::test_pty_launcher_captures_nonzero_exit,
   ::test_pty_launcher_preserves_command_env,
   ::test_pty_launcher_result_json_from_exit_code_file,
   ::test_exit_code_from_fifo_e2e, ::test_one_shot_fifo_e2e,
   tests/test_pty_final_child_fidelity.py,
   tests/test_pty_component_contracts.py,
   tests/test_terminal_result_authority.py

.. test:: Software installation is routed through a visible interactive terminal, fails closed when unavailable
   :id: TEST_032
   :status: draft
   :verification_result: IO
   :verifies: ARC_REQ_025, SUB_REQ_032

   KIB-ADC-CAPABILITY-AUTH-TERMINAL-BOUNDARY-TC-FIX-001: the final-child
   class proves cwd, controlled environment, argv, exactly-once execution,
   exit propagation, and the visible-terminal no-fallback boundary through
   the real wrapper-script/status-file mechanism.

   tests/test_execution_boundary.py::TestSoftwareInstallationRoutesThroughVisibleTerminal,
   tests/test_interactive_terminal.py

.. test:: Execution state fails closed on unknown state, reuses known success
   :id: TEST_013
   :status: draft
   :verification_result: IO
   :verifies: SUB_REQ_011, IF_REQ_016

   CLAUDE-ADC-TEST-GATE1-SAFETY-CORRECTION-001 (DEF-014): extended with
   tests/test_execution_target_authorization_retry_system.py's two
   SYSTEM-level regressions, entering through the real Web HTTP boundary
   and the real MCP JSON-RPC tool boundary respectively, proving SUB_REQ_011's
   own "known-success shall enable reuse" clause holds end to end when
   an already-succeeded approved setup step is retried through either
   adapter -- exactly zero additional real installation launches, with
   no adapter-specific retry-prevention logic duplicated in web_api.py
   or mcp_server.py, both instead inheriting the SAME central
   app.setup_execution_state / DevelopmentWorkflow._execute_with_state_guard
   guard the pre-existing selectors below already verify at the
   lower, state-machine-only level. Was previously unmapped to any
   TEST object and unsafe to execute (constructed a real, unmocked
   PythonPackageExecutor with no terminal-boundary substitution, risking
   a real GUI terminal launch); the external terminal boundary is now
   INERT (tests/terminal_final_child_probe.py::inert_counting_provider),
   recording each genuine reach of execute_controlled()'s install branch
   without ever executing pip or installing anything, while every other
   collaborator in the chain remains real and unmocked.

   tests/test_setup_execution_state.py::TestValidTransitions,
   ::TestIllegalTransitions, ::TestCorruptStateFailsClosed,
   ::TestProjectPlanStepBinding,
   tests/test_execution_target_authorization_retry_system.py::test_web_http_boundary_retry_launches_zero_additional_processes,
   ::test_mcp_boundary_retry_launches_zero_additional_processes

.. test:: Missing-toolchain recovery is bounded, approval-bound, non-repeating
   :id: TEST_014
   :status: draft
   :verification_result: IO
   :verifies: SUB_REQ_012, IF_REQ_029, IF_REQ_030, ARC_REQ_023, SUB_REQ_025, IF_REQ_037

   KIB-ADC-CAPABILITY-AUTH-TERMINAL-BOUNDARY-TC-FIX-001: extended with a
   real-producer-chain regression (ToolchainMaterializer to
   DevelopmentWorkflow to ProjectSetupApplicationService's
   prepare/decide/execute/retry missing-toolchain-setup lifecycle to
   StructuredInstallerRegistry to a real PythonPackageExecutor to real
   execute_controlled) that never manually injects the capability
   registration under test -- unlike an earlier, unrelated workaround
   this exact manual-injection pattern is explicitly required to avoid
   (DEF-012). KIB-ADC-CAPABILITY-AUTH-TERMINAL-BOUNDARY-TC-CORRECTION-001:
   the external terminal boundary is INERT (records the exact argv it
   would otherwise have run, e.g. ``<python> -m pip install <package>``,
   without ever executing it), and post-install detection/verification
   uses deterministic doubles at PythonPackageExecutor's own `verifier`
   parameter and StructuredInstallerRegistration's own
   `availability_checker` parameter -- no venv is created and no pip
   invocation, real or hermetic, occurs anywhere in this regression, on
   any code path, whether its tests are RED or GREEN. The integrated
   recovery authorization fix routes the approved recovery artifact through
   the shared capability gate before execution and leaves authorization
   failures in an explicit bounded failure state.

   tests/test_missing_toolchain_setup.py::test_tool_unavailable_does_not_install_automatically,
   ::test_setup_cannot_execute_before_approval,
   ::test_approved_structured_setup_executes_once,
   ::test_already_available_toolchain_is_not_reinstalled,
   ::test_restart_does_not_repeat_completed_installation,
   ::test_missing_toolchain_recovery_preserves_human_selected_engineering_decision,
   ::test_retry_uses_persisted_existing_verification_plan,
   tests/test_s3_missing_toolchain_capability_authorization.py::test_recovery_generated_install_reaches_real_capability_authorization_and_completes,
   ::test_pending_recovery_approval_yields_zero_authorization_and_zero_execution,
   ::test_rejected_recovery_approval_yields_zero_authorization_and_zero_execution,
   ::test_wrong_project_for_verification_plan_fails_closed,
   ::test_recovery_remains_bounded_and_non_repeating,
   ::test_failed_pre_execution_authorization_does_not_strand_recovery_as_executing

   DEF-RSE033-ESPHOME-COMPILE-TIMEOUT (EXECUTION_ERROR, IF_REQ_029):
   through the real inspector, plan producer, registry, runner and S5.6
   policy, an execution error of a verification process that had started
   never takes the S5 -> S3 missing-toolchain route, while a genuinely
   unavailable tool still does and carries its verification plan for the
   recovery request.

   tests/test_verification_execution_error.py::TestExecutionErrorToolchainRecoveryBoundary

   CLAUDE-ADC-RSE033-INSTALLER-RECOVERY-CLOSURE-FIX-002 (IF_REQ_037): the
   one central installer-identity resolution (every accepted installation
   representation reaches its structured installer, a rejected one none,
   a package identity never selects an installer), the explicit
   executable -> provisioning-requirement correlation with pairwise
   distinct requirement, distribution, executable, representation,
   installer and capability identities (ambiguous or missing relations
   fail closed), and fail-closed reverification: recovery completes only
   when its single retry of the persisted VerificationPlan passes.

   tests/test_installer_recovery_identity.py::test_supported_forms_resolve_through_materializer_to_one_registered_installer,
   ::test_unsupported_forms_never_become_install_steps_or_resolve,
   ::test_package_identity_is_never_used_as_installer_identity,
   ::test_uncontrolled_effect_resolves_to_no_installer,
   ::test_executable_correlates_to_provider_through_declared_provided_by,
   ::test_package_identity_alone_never_correlates_to_an_executable,
   ::test_ambiguous_or_broken_correlation_fails_closed,
   ::test_distinct_identities_correlate_only_through_explicit_relations,
   tests/test_missing_toolchain_setup.py::test_passing_reverification_completes_recovery_once,
   ::test_failed_reverification_never_reports_recovery_completed,
   ::test_reverification_without_a_structured_result_fails_closed

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

   tests/test_development_testing_stage.py::test_development_mutation_failure_never_reaches_verification,
   ::test_required_test_mutation_apply_failure_never_reaches_verification,
   ::test_explicit_no_op_test_mutation_is_not_required_and_verification_still_starts,
   ::test_verification_all_steps_passing_yields_a_passed_test_result

.. test:: Verification plan derivation stays central and ecosystem-neutral
   :id: TEST_021
   :status: draft
   :verification_result: IO
   :verifies: SUB_REQ_017, IF_REQ_022

   tests/test_s5_subsubsystem_architecture.py::TestS5_1_VerificationPlanning

   DEF-RSE033-ESPHOME-COMPILE-TIMEOUT (IF_REQ_022): every planned step
   carries its execution time budget, selected before execution by the
   central technology-neutral policy from the step's generic operation
   class; the budget survives plan persistence, a legacy persisted step
   takes the central policy budget, and no runner has a constructor budget.

   tests/test_verification_timeout_policy.py::TestVerificationBudgetPolicy

.. test:: Controlled runners preserve full per-step result fidelity
   :id: TEST_022
   :status: draft
   :verification_result: IO
   :verifies: ARC_REQ_016, SUB_REQ_018, IF_REQ_023

   tests/test_s5_subsubsystem_architecture.py::TestS5_2_ControlledVerificationExecution,
   tests/test_verification.py

   DEF-RSE033-ESPHOME-COMPILE-TIMEOUT: runners consume exactly the step's
   policy budget as the real execution budget, an invalid budget fails
   closed before any process starts, and a real controlled-process timeout
   terminates the whole process tree and preserves the partial output as
   text with the synthetic timeout return code.

   DEF-RSE033-ESPHOME-COMPILE-TIMEOUT (FIX-002): partial output that is not
   valid UTF-8, or that cannot be drained, never interrupts the timeout's
   process-group cleanup (a SIGTERM-resistant descendant does not survive)
   and never turns the timeout into an unavailable tool; the valid
   surrounding output is preserved as text and the timeout stays a generic
   timeout that never reaches S5 -> S3 missing-toolchain recovery.

   tests/test_verification_timeout_policy.py::TestBudgetConsumptionAndProcessBoundary

   DEF-RSE033-ESPHOME-COMPILE-TIMEOUT (EXECUTION_ERROR, ARC_022): the real
   execution boundary and runners keep four outcomes distinct -- an
   executable that cannot be started is TOOL_UNAVAILABLE, a real controlled
   process that started and then failed at the execution boundary is
   EXECUTION_ERROR with its error category (after its whole process tree
   was contained, never TOOL_UNAVAILABLE), an exceeded budget is TIMEOUT,
   and a normal nonzero verdict is FAIL; a launch failure that provisioning
   cannot remedy is not TOOL_UNAVAILABLE either.

   tests/test_verification_execution_error.py::TestExecutionErrorClassification

.. test:: Verification-only runners preserve target-workspace integrity
   :id: TEST_031
   :status: draft
   :verification_result: IO
   :verifies: ARC_REQ_024, SUB_REQ_031

   tests/test_verification_workspace_integrity.py

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

.. test:: Real failure forces rework; timeout fails closed without automatic rework
   :id: TEST_026
   :status: draft
   :verification_result: IO
   :verifies: SUB_REQ_022, IF_REQ_026

   tests/test_testing_stage.py (TestingStage.run test classes)

   DEF-RSE033-ESPHOME-COMPILE-TIMEOUT (IF_REQ_026): a timeout is never
   accepted; without a diagnosed source-correctable cause it is a
   fail-closed outcome that does not consume the bounded rework, with such
   a diagnosis it uses at most the one bounded rework, and a real failure
   alongside it still forces rework.

   tests/test_verification_timeout_policy.py::TestTimeoutReworkClassification

   DEF-RSE033-ESPHOME-COMPILE-TIMEOUT (EXECUTION_ERROR, IF_REQ_026): an
   execution error without a real failure alongside it ends in the
   fail-closed verification_execution_error outcome whatever the diagnosis
   decides or whether the diagnosis is available at all; timeouts and
   blocked steps alongside it do not change that, and a real failure
   alongside it still forces rework.

   tests/test_verification_execution_error.py::TestExecutionErrorOutcomePolicy

.. test:: Rework is bounded to exactly one cycle with attributable evidence
   :id: TEST_027
   :status: draft
   :verification_result: IO
   :verifies: ARC_REQ_021, SUB_REQ_023, IF_REQ_027, IF_REQ_028

   tests/test_controlled_rework_stage.py,
   tests/test_rework_diagnostic_fidelity.py

   DEF-RSE033-ESPHOME-COMPILE-TIMEOUT (EXECUTION_ERROR, IF_REQ_027): an
   execution error never starts the bounded rework cycle, even when the
   diagnosis asks for rework, and a rework cycle ending in an execution
   error never creates a further cycle.

   tests/test_verification_execution_error.py::TestExecutionErrorReworkBudget

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

.. test:: Diagnostic trace redacts secrets, cannot grant delivery authority, and preserves structured x/f/y and execution-identity lineage
   :id: TEST_030
   :status: draft
   :verification_result: IO
   :verifies: SUB_REQ_028, IF_REQ_033

   Focused/synthetic contract verification only -- never a substitute
   for, and never able to produce Evidence for, TEST_033 (the
   Real-System-E2E acceptance test). Covers secret redaction and
   delivery-authority non-substitution, plus (via
   ``_validate_final_diagnostic_trace``, the exact same deterministic
   final-validation logic the RSE itself calls) the structured x/f/y
   endpoint shape, execution-identity fields (entity, entity_version,
   implementation_version), actor/phase presence, forbidden-content
   rejection, and that ``DiagnosticDetailLevel.NONE`` suppresses
   presentation only, never the persisted audit evidence -- all against
   real ``DiagnosticTraceEvent`` instances, never against a live
   real-system run.

   tests/test_central_diagnostic_trace.py::test_secret_redaction_and_detail_allowlist_protect_persisted_jsonl,
   ::test_trace_content_cannot_approve_or_release_publish_gate,
   tests/test_real_system_e2e_progress.py::test_validate_final_diagnostic_trace_accepts_a_realistic_real_shaped_trace,
   ::test_validate_final_diagnostic_trace_never_calls_to_record,
   ::test_validate_final_diagnostic_trace_checks_x_f_y_semantics,
   ::test_validate_final_diagnostic_trace_checks_execution_identity_semantics,
   ::test_validate_final_diagnostic_trace_checks_actor_phase_semantics,
   ::test_validate_final_diagnostic_trace_rejects_forbidden_data,
   ::test_diagnostic_detail_level_none_does_not_erase_persisted_audit_evidence,
   ::test_validate_final_diagnostic_trace_fails_clearly_on_missing_task_description,
   ::test_validate_final_diagnostic_trace_fails_clearly_on_empty_trace

.. test:: Real-System-E2E: ESPHome Hello World acceptance run proves human selection authority, setup approval, Controlled Git, and the Central Diagnostic Trace contract on genuine real-system execution
   :id: TEST_033
   :status: draft
   :verifies: SUB_REQ_006, IF_REQ_012, ARC_REQ_007, SUB_REQ_008, ARC_REQ_008, SUB_REQ_009, ARC_REQ_016, SUB_REQ_018, SUB_REQ_024, IF_REQ_031, SUB_REQ_028, IF_REQ_033
   :verification_result: IO

   This is the Real-System-E2E acceptance test and nothing else --
   exclusively mapped from the actual RSE selector, never from any
   focused/synthetic test. It shall become IO only when a genuinely
   executed, real Real-System-E2E run produces passing Evidence for
   this exact selector; a passing focused regression (e.g. TEST_030,
   TEST_022, or any other synthetic test covering the same
   Requirements) can never mark this object IO. Focused verification
   and Real-System-E2E verification are distinct evidence layers that
   may legitimately verify the same Requirement; an already-green
   focused TEST is never, by itself, a reason to omit a Requirement
   the RSE itself meaningfully asserts.

   ``:verifies:`` is derived assertion-by-assertion from the RSE's own
   body, never from which subsystems the run merely passes through:
   (1) SUB_REQ_006/IF_REQ_012 -- S2.4 human selection authority: no
   SetupPlan exists before an explicit human selection artifact is
   returned, and ``engineering_decision.selection_authority == "human"``
   with the selected variant id matching the human's real choice; (2)
   ARC_REQ_007/SUB_REQ_008 -- S3.1 Setup Planning: the SetupPlan
   materializes only after selection resolves, with
   ``plan.status == "pending_approval"`` (planning neither executes nor
   auto-approves); (3) ARC_REQ_008/SUB_REQ_009 -- S3.2 Setup Approval
   executed through the real, unmocked central lifecycle helper
   (``approve_setup_plan``), the RSE's own continuation being
   contingent on it succeeding; (4) ARC_REQ_016/SUB_REQ_018 -- S5.2
   controlled verification execution: real ESPHome ``validate`` and
   ``compile`` steps are produced by a registered controlled runner and
   every one of them is asserted ``PASS`` -- this is the concrete real
   acceptance proof of ESPHome validate/compile the RSE was built to
   provide; (5) SUB_REQ_024/IF_REQ_031 -- S6 local delivery distinct
   from publish: Final Approval marks ``ready_for_git``, the real
   commit has a real commit hash, the working tree is clean after
   commit, and no remote is configured (never touching Controlled
   Publish); (6) SUB_REQ_028/IF_REQ_033 -- the Central Diagnostic Trace
   contract (task description present, all Council agents and the
   Chairman referenced, forbidden content absent, x/f/y and
   execution-identity structure present) against the actual persisted
   trace of this real run -- the exact final stage that previously
   failed with an ``AttributeError`` from a stale, nonexistent
   ``DiagnosticTraceEvent.to_record()`` assumption, now fixed via the
   shared ``_validate_final_diagnostic_trace`` helper also used by
   TEST_030's focused regression.

   Reviewed and deliberately NOT listed: Requirement/toolchain
   discovery, Preflight, Council deliberation itself, and
   MissingToolchainSetup recovery are exercised (the last only
   conditionally, when the real toolchain happens to be unavailable)
   but never meaningfully asserted by name in this RSE, so they are not
   claimed here. The generated ESPHome YAML's own semantic content
   (``esphome``/``esp32dev``/``logger``/the periodic "Hello World" text,
   checked by this file's own ``_assert_hello_world`` helper) was
   reviewed against the Requirements tree and found to have no
   sufficiently precise, dedicated Requirement ID describing generated-
   artifact semantic content matching the requested task; it is
   asserted by this RSE but intentionally not attached to an
   ill-fitting Requirement merely to claim coverage.

   tests/real_system/real_system_e2e.py::test_real_esphome_esp32_hello_world_acceptance

   tests/real_system/real_system_e2e.py::test_real_esphome_esp32_hello_world_acceptance,
   tests/test_real_system_e2e_progress.py::test_validate_final_diagnostic_trace_accepts_a_realistic_real_shaped_trace,
   ::test_validate_final_diagnostic_trace_never_calls_to_record,
   ::test_validate_final_diagnostic_trace_checks_x_f_y_semantics,
   ::test_validate_final_diagnostic_trace_checks_execution_identity_semantics,
   ::test_validate_final_diagnostic_trace_checks_actor_phase_semantics,
   ::test_validate_final_diagnostic_trace_rejects_forbidden_data,
   ::test_diagnostic_detail_level_none_does_not_erase_persisted_audit_evidence,
   ::test_validate_final_diagnostic_trace_fails_clearly_on_missing_task_description,
   ::test_validate_final_diagnostic_trace_fails_clearly_on_empty_trace,
   ::test_emit_failure_diagnostics_does_not_promote_a_recovered_testing_phase_retry,
   ::test_emit_failure_diagnostics_still_reports_a_genuinely_unrecovered_testing_failure,
   ::test_emit_failure_diagnostics_still_reports_a_later_genuine_failure_on_a_different_phase_after_testing_recovers,
   ::test_phase_later_recovered_true_only_for_a_genuinely_later_same_phase_success

.. test:: Request identity, intent preservation, and run-scoped correlation
   :id: TEST_034
   :status: draft
   :verification_result: IO
   :verifies: IF_REQ_001

   The real CommonRequest producer carries a structured identity
   (project_id, intent, source_interface) and preserves the user's
   request text unchanged, structurally refusing adapter
   reinterpretation; the real DiagnosticTrace and WorkflowManager
   consumers assign every artifact of one ADC run to exactly that run's
   run_id and fully isolate two runs sharing the same stores.

   tests/test_request_identity_correlation.py::test_common_request_structured_identity_preserves_user_request_unchanged,
   ::test_run_scoped_correlation_assigns_and_isolates_two_runs

.. test:: Request handover and immutable Council completion
   :id: TEST_036
   :status: approved
   :verification_result: IO
   :verifies: SUB_REQ_033, SUB_REQ_034

   Verify the documented transport boundary, buffered and automatic retries, closure races, all timeout scopes, remote uncertainty, immutable snapshots, and permitted late additions. Existing start-claim or complete()-entry probes are reproductions, not proof of actual handover.

   Implementation, executable acceptance selectors, and product evidence remain OPEN. No previous green test result establishes these new obligations. Gate 1 requires focused contract proof; Gate 2 requires the real Council-to-diagnosis-to-public-query composition where applicable. Native socket/ASGI evidence requires an environment permitting those operations. This adoption grants no Gate 3, TEST_033, TEST_035, real-system E2E, or live-provider execution.

.. test:: Critical diagnosis, storage failures, and retrieval
   :id: TEST_037
   :status: approved
   :verification_result: IO
   :verifies: SUB_REQ_035, SUB_REQ_036

   Verify public monotone state with real diagnosis and retrieval, confirmed-persistence reload, blocked storage, reservations, unexpected overflow, bounded volatile retrieval, and preservation of existing retention promises. Cover visible size failure without silent critical truncation.

   Implementation, executable acceptance selectors, and product evidence remain OPEN. No previous green test result establishes these new obligations. Gate 1 requires focused contract proof; Gate 2 requires the real Council-to-diagnosis-to-public-query composition where applicable. Native socket/ASGI evidence requires an environment permitting those operations. This adoption grants no Gate 3, TEST_033, TEST_035, real-system E2E, or live-provider execution.

.. test:: Notification saturation and concurrent Council resource isolation
   :id: TEST_038
   :status: approved
   :verification_result: IO
   :verifies: SUB_REQ_037, SUB_REQ_038

   Verify permanently blocked subscriptions, delivery counters and queue bounds, simultaneous Council isolation, resource saturation including retained snapshots, explicit overload, and recovery after actual capacity release. Contributor count is not a service-wide concurrency limit.

   Implementation, executable acceptance selectors, and product evidence remain OPEN. No previous green test result establishes these new obligations. Gate 1 requires focused contract proof; Gate 2 requires the real Council-to-diagnosis-to-public-query composition where applicable. Native socket/ASGI evidence requires an environment permitting those operations. This adoption grants no Gate 3, TEST_033, TEST_035, real-system E2E, or live-provider execution.

.. test:: Public deadline, counted quarantine, and owner-process exit
   :id: TEST_039
   :status: approved
   :verification_result: IO
   :verifies: SUB_REQ_039, SUB_REQ_040

   Verify all elapsed-time boundaries including preparation and finalization, timely versus late outcomes, counted permanent quarantine, isolated owner-process exit, and no restart resubmission. Use an explicitly validated and separately approved test profile; no numeric candidate is normative.

   Implementation, executable acceptance selectors, and product evidence remain OPEN. No previous green test result establishes these new obligations. Gate 1 requires focused contract proof; Gate 2 requires the real Council-to-diagnosis-to-public-query composition where applicable. Native socket/ASGI evidence requires an environment permitting those operations. This adoption grants no Gate 3, TEST_033, TEST_035, real-system E2E, or live-provider execution.

.. test:: Target-environment context and generated-source compatibility
   :id: TEST_040
   :status: approved
   :verification_result: IO
   :verifies: SYS_REQ_032, ARC_REQ_027, SUB_REQ_041, IF_REQ_038, ARC_REQ_028, SUB_REQ_042, IF_REQ_039

   Verify that the intended target environment is established before source
   generation, relevant properties reach the generator through the S3→S4
   handoff, and user-selected technology and project conventions are
   preserved. Also verify that S5 executes applicable generated-source checks
   in the same intended target environment. A different host or default
   environment must not count as target verification; if the intended target
   cannot be used, compatibility must remain unconfirmed. Verify that
   detection after an installation, capability approval and execution of a
   command-line tool all refer to the same selected and approved target
   environment, never to a host PATH hit for the same name. The executable
   selectors are:

   - ``tests/test_target_environment_generation_contract.py::test_s3_s4_generation_and_production_s5_runner_use_the_same_target``
   - ``tests/test_target_environment_generation_contract.py::test_unavailable_target_environment_cannot_be_confirmed_by_host_verification``
   - ``tests/test_target_environment_generation_contract.py::test_plan_selected_target_that_cannot_be_observed_is_never_replaced``
   - ``tests/test_target_environment_generation_contract.py::test_plan_selected_target_is_the_verification_target_when_observed``
   - ``tests/test_target_environment_generation_contract.py::test_several_different_observed_targets_are_ambiguous_not_a_choice``
   - ``tests/test_missing_toolchain_setup.py::test_retry_without_established_target_is_blocked_and_never_runs_on_the_host``
   - ``tests/test_missing_toolchain_setup.py::test_retry_verifies_through_exactly_the_persisted_s5_target``
   - ``tests/test_target_bound_cli_boundary.py::test_detection_uses_only_the_selected_target_never_the_host_path``
   - ``tests/test_target_bound_cli_boundary.py::test_unknown_or_unusable_target_is_never_available``
   - ``tests/test_target_bound_cli_boundary.py::test_target_lookup_never_resolves_a_path_like_or_different_name``
   - ``tests/test_target_bound_cli_boundary.py::test_target_bound_request_requires_an_approved_target``
   - ``tests/test_target_bound_cli_boundary.py::test_approval_of_one_target_never_covers_another``
   - ``tests/test_target_bound_cli_boundary.py::test_host_resolved_or_bare_command_is_rejected_for_a_target_bound_request``
   - ``tests/test_target_bound_cli_boundary.py::test_target_bound_request_requires_a_capability_named_tool_that_exists``
   - ``tests/test_target_bound_cli_boundary.py::test_unusable_target_stays_fail_closed``
   - ``tests/test_target_bound_cli_boundary.py::test_target_approval_needs_complete_provenance_for_this_project``
   - ``tests/test_target_bound_cli_boundary.py::test_plan_selected_environment_is_approved_even_without_steps``
   - ``tests/test_target_bound_cli_boundary.py::test_execution_runs_exactly_the_target_tool_even_if_the_host_path_changes``
   - ``tests/test_target_bound_cli_boundary.py::test_runner_never_falls_back_to_a_host_tool_when_the_target_lacks_it``
   - ``tests/test_target_bound_cli_boundary.py::test_runner_executes_the_selected_target_tool_and_repeats_identically``
   - ``tests/test_target_bound_cli_boundary.py::test_target_environment_prose_lists_exactly_the_selector_map``
   - ``tests/test_development_testing_stage.py::test_legacy_s5_branch_without_established_target_never_runs_on_the_host``
   - ``tests/test_development_testing_stage.py::test_legacy_s5_branch_with_unusable_target_context_is_unconfirmed``
   - ``tests/test_development_testing_stage.py::test_legacy_s5_branch_runs_through_exactly_the_established_target``
   - ``tests/test_missing_toolchain_setup.py::test_retry_after_restart_re_establishes_the_target_approval``
   - ``tests/test_missing_toolchain_setup.py::test_retry_with_a_target_the_recovery_plan_did_not_select_is_blocked``

   The integration selectors exercise target-context generation and the
   production S5 runner. They require the runner to use the established
   target executable and prevent a host run from confirming compatibility
   when the target is unavailable. Further unit selectors pin that a
   plan-selected target that cannot be observed is never replaced by another
   observed target and that several different observed targets remain
   ambiguous. The boundary selectors pin that an unknown, unapproved,
   ambiguous or unusable target stays fail-closed, also when the host PATH
   changes, after a restart and on every verification retry, and that the
   legacy S5 branch without a verification registry never verifies on a
   substitute environment. The verification result of TEST_040 is recorded
   only by formal Evidence ingest. The review status of this entry is
   unchanged by that result.
