ADC Implementation Mapping
===========================

Real implementation artifacts that materially satisfy accepted Requirements.

Each object below was verified by reading the actual source referenced, not
inferred from filenames. Where a Requirement's full obligation is only
partially realized by existing code, no IMPL object is created for it here —
that Requirement remains an honest gap (see the coverage dashboard).

.. impl:: External entry request identity
   :id: IMPL_001
   :status: draft
   :implements: IF_REQ_002

   ``CommonRequest`` (a frozen dataclass with no mutation methods) is the
   adapter-neutral external-entry artifact. It structurally cannot select a
   technical solution, toolchain, or execute setup, and preserves the
   user's request unchanged.

   Location: app/common_request.py, class CommonRequest

.. impl:: S1 requirement pipeline (discovery, validation, preflight)
   :id: IMPL_002
   :status: draft
   :implements: IF_REQ_006

   ``AIRequirementDiscovery`` → ``RequirementValidator`` →
   ``RequirementPreflight`` produce Requirement objects with stable,
   generated IDs and carry no technical-solution-selection or
   setup-execution capability; downstream S2.3 admissibility rejects any
   candidate whose requirement_ref does not match a real, preserved ID
   from this pipeline (ID loss/drift/duplication never silently enters
   the Council handoff).

   Location: app/ai_requirement_discovery.py class AIRequirementDiscovery;
   app/requirement_validator.py class RequirementValidator;
   app/requirement_preflight.py class RequirementPreflight

.. impl:: Engineering Council alternatives generation and cross-review
   :id: IMPL_003
   :status: draft
   :implements: ARC_REQ_003, SUB_REQ_003, IF_REQ_007

   Phase 1 (``_phase1_independent_proposals``) generates independent
   per-agent proposals; Phase 2 (``_phase2_cross_review``) collects
   cross-review evidence for each before any recommendation is produced.
   Neither phase selects a final recommendation or decides admissibility.

   Location: app/engineering_council.py, functions
   _phase1_independent_proposals, _phase2_cross_review

.. impl:: Chairman synthesis and bounded repair
   :id: IMPL_004
   :status: draft
   :implements: SUB_REQ_004

   ``_phase3_chairman_synthesis`` synthesizes cross-reviewed proposals into
   a recommendation, including exactly one bounded targeted repair attempt
   on a structurally rejected synthesis; it exercises no independent
   admissibility policy of its own.

   Note: this same code also produces the final Chairman-candidate
   artifact IF_REQ_008 is about, but no existing test genuinely exercises
   a multi-source Chairman merge with correctly-derived
   ``merged_from``/``origin_agents`` feeding ``validate_candidates()`` —
   IF_REQ_008 is therefore intentionally left without an IMPL link here
   (reported as IMPLEMENTATION_GAP for the merge-lineage-fidelity clause
   specifically, not a blanket claim that Chairman synthesis is
   unimplemented).

   Location: app/engineering_council.py, function
   _phase3_chairman_synthesis

.. impl:: S2.3 Engineering Admissibility (technical evaluation authority)
   :id: IMPL_005
   :status: draft
   :implements: ARC_REQ_004, SUB_REQ_005

   ``validate_variants``/``validate_candidates`` is the sole technical
   admissibility authority, producing ``CandidateValidation`` with
   admissible/reasons per candidate; it is invoked independently of, and
   never infers admissibility from, the Chairman recommendation.

   Note: the Requirement's full "structured rejection category"
   obligation (IF_REQ_009: distinct missing-reference / type /
   technical-identity / semantic / version-mismatch / verification-
   contract-gap categories) is only partially exposed by the current
   ``CandidateValidation`` fields (4 coarse dimensions:
   missing_binding_requirement_ids, platform_conflict,
   unmaterializable_items, verification_feasibility_gap_ids) — IF_REQ_009
   is intentionally left unmapped (IMPLEMENTATION_GAP), not claimed as
   fully satisfied by this partial implementation.

   Location: app/engineering_decision.py, functions validate_variants,
   validate_candidates; class CandidateValidation

.. impl:: S2.3-to-S2.2 structured rework feedback
   :id: IMPL_006
   :status: draft
   :implements: IF_REQ_010

   ``EngineeringReworkRequest.from_validation()`` builds rework feedback
   directly from a ``CandidateValidation``, distinguishing repairable
   (identity_conflict/install_method_conflict) from non-repairable
   (materializability_conflict) causes; never repairs a candidate or picks
   an alternative winner itself.

   Location: app/engineering_decision.py, class EngineeringReworkRequest,
   method from_validation

.. impl:: S2.4 Human Engineering Authority
   :id: IMPL_007
   :status: draft
   :implements: SUB_REQ_006, IF_REQ_011

   ``resolve_human_engineering_selection`` consumes only already-
   technically-evaluated ``CandidateValidationSet`` results; zero eligible
   candidates raises ``NoEligibleEngineeringCandidateError`` rather than
   silently proceeding.

   Location: app/engineering_decision.py, function
   resolve_human_engineering_selection; class EngineeringVariantSelection

.. impl:: S2.4-to-S2.5 final candidate resolution
   :id: IMPL_008
   :status: draft
   :implements: IF_REQ_012

   ``select_engineering_variant`` resolves the human's choice against an
   existing admissible candidate; produces no hidden EngineeringDecision on
   reject/defer/rework and no default winner on unresolved selection.

   Location: app/engineering_decision.py, function
   select_engineering_variant

.. impl:: S2.5 Engineering Decision and S3 handoff artifact
   :id: IMPL_009
   :status: draft
   :implements: ARC_REQ_006, SUB_REQ_007, IF_REQ_013

   ``build_engineering_decision`` produces the single ``EngineeringDecision``
   artifact preserving exact candidate identity, selection authority, and
   validation provenance across the S2→S3 boundary.

   Location: app/engineering_decision.py, function
   build_engineering_decision; class EngineeringDecision

.. impl:: S3.1 Setup Planning (materialization without execution)
   :id: IMPL_010
   :status: draft
   :implements: ARC_REQ_007, SUB_REQ_008, IF_REQ_014

   ``ToolchainMaterializer.materialize_decision()`` materializes the
   already-chosen EngineeringDecision into a classified SetupPlan
   (already_satisfied / materializable / manual_review / deferred /
   provided via ``_classify_item_baseline``) without executing, approving,
   or reopening the S2 selection.

   Location: app/toolchain_materializer.py, class ToolchainMaterializer,
   methods materialize_decision, _classify_item_baseline

.. impl:: S3.2 sole human setup-approval authority
   :id: IMPL_011
   :status: draft
   :implements: ARC_REQ_008, SUB_REQ_009

   ``SetupApproval`` is a narrow state-transition class with no planning or
   execution capability; binds approval to exact plan content and
   excludes manual_review steps from being marked approved.

   Location: app/setup_approval.py, class SetupApproval, methods approve,
   reject

.. impl:: S3.3 controlled execution boundary
   :id: IMPL_012
   :status: draft
   :implements: ARC_REQ_009, SUB_REQ_010, SUB_REQ_026, SUB_REQ_029

   ``execute_controlled``/``validate_request`` require an active
   registered ``CapabilityRegistration``, an allowed operation type,
   complete approval provenance for mutating operations, matching
   executable identity, and reject dangerous argument patterns before any
   mutation proceeds. Toolchain-specific behavior is delegated entirely to
   registered capabilities/adapters, never embedded in this central
   boundary — the same generic mechanism realizes the technology-neutral
   vocabulary requirement and the "executability proof precedes mutation"
   requirement.

   Location: app/execution.py, functions execute_controlled,
   validate_request; class CapabilityRegistry

.. impl:: S3.4 execution state and idempotency
   :id: IMPL_013
   :status: draft
   :implements: SUB_REQ_011, IF_REQ_016

   ``SetupExecutionStateStore`` persists execution identity/state per
   setup step bound to a content fingerprint
   (``setup_step_content_snapshot``); known-success content may be reused,
   changed content forces new generation, unknown/recovery state fails
   closed; cross-process safe via file locking.

   Location: app/setup_execution_state.py, class SetupExecutionStateStore,
   function setup_step_content_snapshot

.. impl:: S3.5 missing-toolchain recovery
   :id: IMPL_014
   :status: draft
   :implements: SUB_REQ_012, IF_REQ_029, IF_REQ_030, ARC_REQ_023, SUB_REQ_025

   ``ProjectSetupApplicationService``'s prepare/decide/execute
   missing-toolchain methods plus ``retry_missing_toolchain_verification``
   convert generic TOOL_UNAVAILABLE evidence into a bounded,
   approval-bound recovery reusing S3.1/S3.2/S3.3 authorities, never
   reopening the already-selected EngineeringDecision, and re-executing
   only the persisted VerificationPlan afterward — this is also the
   concrete realization of the cross-subsystem "S5→S3 boundary allows only
   bounded missing-toolchain recovery" sequencing constraint.

   Location: app/project_setup_application.py, class
   ProjectSetupApplicationService, methods
   prepare_missing_toolchain_setup, decide_missing_toolchain_setup,
   execute_missing_toolchain_setup, retry_missing_toolchain_verification;
   app/missing_toolchain_setup.py, classes MissingToolchainSetupRequest,
   MissingToolchainSetupResult, StructuredInstallerRegistry

.. impl:: S3-to-S4 development entry gate
   :id: IMPL_015
   :status: draft
   :implements: IF_REQ_017

   ``execute_approved_and_run_development`` requires setup execution to
   have fully succeeded before development/testing is ever started;
   unapproved or failed setup raises before the development stage runs
   (verified: the mocked development-testing stage's ``run`` is never
   called in either failure case).

   Location: app/dev_workflow.py, method
   execute_approved_and_run_development

.. impl:: S4.1 structured development change generation
   :id: IMPL_016
   :status: draft
   :implements: ARC_REQ_012, SUB_REQ_013

   ``DeveloperAgent`` generates structured developer changes; an empty
   development change set fails at the application boundary rather than
   being silently accepted as a no-op (S4.1 has no no-op authority of its
   own).

   Location: app/development_stage.py, class DeveloperAgent;
   app/structured_change_generation.py

.. impl:: S4.2 test change generation with explicit no-op contract
   :id: IMPL_017
   :status: draft
   :implements: SUB_REQ_014, IF_REQ_019

   ``TestChangeGenerator`` requires an explicit
   ``disposition="no_changes_required"`` with a non-empty reason for a
   valid no-op; a bare empty changes array alone is rejected as not a
   no-op.

   Location: app/test_change_generator.py, class TestChangeGenerator

.. impl:: S4.3 controlled change application within authorized scope
   :id: IMPL_018
   :status: draft
   :implements: SUB_REQ_015, IF_REQ_018

   ``ChangeApplicationService`` is the single path from generated content
   to disk, delegating path resolution to ``resolve_safe_path()`` (the one
   authoritative scope-safety policy); traversal/absolute-path/symlink-
   escape attempts fail closed as unsafe_path, and partial/skipped
   application is classified apply_failed rather than appearing
   successful.

   Location: app/change_application.py, class ChangeApplicationService;
   app/developer_file_applier.py; app/safe_project_path.py, function
   resolve_safe_path

.. impl:: S4.4 change provenance and attribution
   :id: IMPL_019
   :status: draft
   :implements: ARC_REQ_014, SUB_REQ_016, IF_REQ_020

   ``RunChangeProvenance`` captures baseline-before and event-after
   provenance with run/phase attribution, consuming (never competing
   with) S4.3's own path-safety policy.

   Location: app/change_provenance.py, class RunChangeProvenance

.. impl:: S4-to-S5 verification entry gate
   :id: IMPL_020
   :status: draft
   :implements: IF_REQ_021

   ``DevelopmentTestingStage.run`` requires the development mutation to
   have succeeded, and the test mutation to have succeeded whenever
   disposition is "changes" (never required for a valid explicit no-op),
   before verification is allowed to begin.

   Location: app/development_testing_stage.py, class
   DevelopmentTestingStage, method run

.. impl:: S5.1 verification plan derivation
   :id: IMPL_021
   :status: draft
   :implements: SUB_REQ_017, IF_REQ_022

   ``build_verification_plan`` derives a structured VerificationPlan from
   project requirements and the detected toolchain; planning itself never
   executes verification, and central orchestration contains no
   ecosystem-specific special-casing.

   Location: app/verification.py, function build_verification_plan

.. impl:: S5.2 controlled verification execution through registered runners
   :id: IMPL_022
   :status: draft
   :implements: ARC_REQ_016, SUB_REQ_018, IF_REQ_023

   ``ControlledRunnerRegistry`` dispatches verification steps to
   registered runners by structured capability contract; every
   ``VerificationStepResult`` preserves status, return code, timeout,
   diagnostics, and runner identity, and toolchain-specific logic stays
   runner-local rather than central.

   Location: app/verification.py, class ControlledRunnerRegistry, class
   VerificationStepResult

.. impl:: S5.3 verification evidence aggregation
   :id: IMPL_023
   :status: draft
   :implements: SUB_REQ_019

   ``_test_result_from_verification``/``_step_failure_evidence`` aggregate
   per-step results while preserving each failing step's own evidence
   individually rather than collapsing multiple failures into a single
   misleading generic result.

   Location: app/development_testing_stage.py, functions
   _test_result_from_verification, _step_failure_evidence

.. impl:: S5.4 deterministic diagnostic evidence formatting
   :id: IMPL_024
   :status: draft
   :implements: SUB_REQ_020, IF_REQ_024

   ``format_test_result_evidence`` deterministically formats
   already-produced verification evidence; it does not mutate the
   underlying TestResult, does not decide acceptance/rework, and makes no
   LLM call of its own.

   Location: app/diagnostic_evidence.py, function
   format_test_result_evidence

.. impl:: S5.5 diagnosis interpretation without override authority
   :id: IMPL_025
   :status: draft
   :implements: SUB_REQ_021, IF_REQ_025

   ``DiagnosisReviewer`` interprets diagnostic evidence into an accepted/
   rework-required decision; a malformed or infrastructure-failing review
   fails closed rather than being silently treated as acceptance, and
   reviewer interpretation alone can never accept a real deterministic
   failure.

   Location: app/testing_stage.py, class DiagnosisReviewer

.. impl:: S5.6 deterministic test outcome policy
   :id: IMPL_026
   :status: draft
   :implements: SUB_REQ_022, IF_REQ_026

   ``TestingStage.run`` forces rework whenever the real test result is a
   failure or timeout, regardless of the reviewer's interpretation, and
   never silently accepts a reviewer-infrastructure exception as success.

   Location: app/testing_stage.py, class TestingStage, method run

.. impl:: S5.7 controlled rework orchestration (bounded to one cycle)
   :id: IMPL_027
   :status: draft
   :implements: ARC_REQ_021, SUB_REQ_023, IF_REQ_027, IF_REQ_028

   ``ControlledReworkStage`` orchestrates exactly one bounded rework cycle
   triggered by the S5 verification verdict; original failure evidence
   remains attributable into the rework request, and a second failure
   never creates a third cycle.

   Location: app/controlled_rework_stage.py, class ControlledReworkStage

.. impl:: S6 controlled Git delivery stage
   :id: IMPL_028
   :status: draft
   :implements: SUB_REQ_024, IF_REQ_031

   ``ControlledGitStage`` commits only after development is accepted and
   final approval is granted; foreign/unaccounted working-tree changes
   (pre-existing or newly introduced during the run) block the commit via
   content-hash comparison against a captured baseline; no destructive
   Git operation (reset/stash/clean/rebase/force-push) exists anywhere in
   the module.

   Location: app/controlled_git_stage.py, class ControlledGitStage

.. impl:: S6 controlled publish stage and final/publish approval
   :id: IMPL_029
   :status: draft
   :implements: IF_REQ_032

   ``ControlledPublishStage`` requires a successful, committed Git result
   plus a separate, distinct publish approval before pushing the exact
   persisted branch-tip commit; a missing commit basis never pushes.
   ``FinalApprovalResult`` and publish approval are structurally distinct
   artifacts from the Git commit result, realizing "final approval
   remains distinct from verification" and "local delivery state remains
   distinct from publish."

   Location: app/controlled_publish_stage.py, class ControlledPublishStage;
   app/final_approval.py; app/publish_approval.py

.. impl:: Diagnostic trace (structured, non-authoritative, secret-redacted)
   :id: IMPL_030
   :status: draft
   :implements: SUB_REQ_028, IF_REQ_033

   ``DiagnosticTrace``/``DiagnosticTraceStore`` persist structured,
   correlated trace events; secret/token/credential redaction is applied
   to both structured fields and free text; trace content cannot approve
   or release any publish/approval gate.

   Location: app/diagnostic_trace.py, classes DiagnosticTrace,
   DiagnosticTraceStore
