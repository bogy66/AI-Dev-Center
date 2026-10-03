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

.. impl:: Council lifecycle execution and critical diagnosis
   :id: IMPL_035
   :status: draft
   :implements: ARC_033, SUB_REQ_033, SUB_REQ_034, SUB_REQ_035, SUB_REQ_036, SUB_REQ_037, SUB_REQ_038, SUB_REQ_039, SUB_REQ_040

   Observed implementation at product commit 1ec0f33a: counted run threads,
   transport handover gates, diagnosis reservations, persistence writer and
   serial notification lanes. The development workflow records the critical
   lifecycle projection for public retrieval. This association identifies
   code responsibility and does not claim contract acceptance.

   Native verification 030 reproduces uncharged retained protocols and Web
   results, leaked reservations on run-thread start failure, and non-atomic
   same-instance admission. HTTP/TLS/proxy evidence remains blocked by socket
   permissions. Operating and shutdown profiles remain provisional.

   Product fix 031 assigns every retained object an owner: a run's
   diagnosis envelope stays charged after retention while its call
   records or a fail-closed result are still held; handed-out results
   are charged for their lifetime; queued and in-flight notifications
   are charged for their payload; a failed run-thread start returns all
   admission reservations; same-instance admission is atomic and refuses
   overlap without a service-wide limit. Independent verification is
   pending.

   Product fix 036 bounds the project identity to 255 UTF-8 bytes with
   one rule for Web start and the public Council call: a longer identity
   is refused visibly (HTTP 400 before any session; a fail-closed Council
   result without identity and before provider handover), never
   shortened. An admitted input is charged while any service-side owner
   holds it (public call, run body, a propagated exception and its
   traceback); an input the pool cannot take is recorded as not
   chargeable and dropped from the service's finished traceback frames.
   Independent verification is pending.

   Product fix 037 replaces that continuation: no Council work runs with
   unbooked data. A run ledger books the admitted input, every invocation
   prompt and every provider response before they are used, and is owned
   by the public call, the run body, every invocation (a quarantined worker
   included) and every propagated exception; it is released only when the
   last owner is actually gone. An input the pool cannot take refuses
   admission with a bounded resource error before any provider handover;
   an unbookable prompt starts no invocation; an unbookable response is
   dropped and fails its invocation visibly. A pending persistence payload
   stays charged until the writer has dropped it. Independent verification
   is pending.

   Location: app/engineering_council.py, app/council_lifecycle.py,
   app/council_models.py, app/web_api.py, app/dev_workflow.py,
   app/diagnostic_trace.py.

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

   The controlled boundary supplies validated argv, resolved cwd and the controlled child environment to the execution surface. IMPL_032 preserves this contract across the additional terminal process boundary for installations.

   Location: app/execution.py, functions execute_controlled,
   validate_request; class CapabilityRegistry

.. impl:: S3.3 visible interactive terminal for controlled installation
   :id: IMPL_032
   :status: draft
   :implements: ARC_REQ_025, SUB_REQ_032, ARC_REQ_009, SUB_REQ_010

   ``execute_controlled`` classifies a request as a software installation
   centrally and deterministically via
   ``is_software_installation_request`` (``ExecutionRequest.operation_type
   == "install"``, the same structured field
   ``_MUTATING_OPERATION_TYPES`` already treats as mutating; never
   inferred from command text) and, only for that classification, routes
   execution through ``InteractiveTerminalLauncher`` instead of the
   direct ``subprocess.run`` call used for every other operation type.
   ``InteractiveTerminalLauncher`` depends only on a ``TerminalProvider``
   abstraction, never one hard-coded desktop terminal program;
   ``DesktopTerminalProvider`` is the production provider, trying an
   ordered, extensible list of common Linux terminal emulators and using
   whichever is first found on ``PATH``. The wrapped installation command
   runs with its stdin/stdout/stderr owned entirely by the terminal
   emulator's own PTY -- this Python process never reads or forwards
   them, which is what structurally guarantees ADC can never receive a
   sudo password as application data. The real exit code is obtained via
   a private, per-run status file a small wrapper script writes only
   after the wrapped command (invoked via ``"$@"``, never re-quoted
   through a shell string) actually returns; its absence -- terminal
   unavailable, launch failure, or the window closing/timing out first
   -- always raises ``InteractiveTerminalError`` with a structured cause
   (``INTERACTIVE_TERMINAL_UNAVAILABLE`` /
   ``INTERACTIVE_TERMINAL_LAUNCH_FAILED`` /
   ``INTERACTIVE_TERMINAL_CANCELLED``), never a synthesized success.

   DesktopTerminalProvider adds only explicitly listed desktop/session connectivity variables to the emulator environment. The wrapper invokes /usr/bin/env with -i and separate assignment/argv elements to replace any inherited terminal-server environment with exactly the supplied controlled child environment before executing the command. No shell-string concatenation or additional installation launch is introduced; cwd, terminal-owned stdio and the existing exit-status protocol are preserved.

   Location: app/interactive_terminal.py, classes
   InteractiveTerminalLauncher, DesktopTerminalProvider,
   InteractiveTerminalError; app/execution.py, function
   is_software_installation_request and the routing branch inside
   execute_controlled

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
   :implements: SUB_REQ_012, IF_REQ_029, IF_REQ_030, ARC_REQ_023, SUB_REQ_025, IF_REQ_037

   ``ProjectSetupApplicationService``'s prepare/decide/execute
   missing-toolchain methods plus ``retry_missing_toolchain_verification``
   convert generic TOOL_UNAVAILABLE evidence into a bounded,
   approval-bound recovery reusing S3.1/S3.2/S3.3 authorities, never
   reopening the already-selected EngineeringDecision, and re-executing
   only the persisted VerificationPlan afterward — this is also the
   concrete realization of the cross-subsystem "S5→S3 boundary allows only
   bounded missing-toolchain recovery" sequencing constraint.

   ``route_tool_unavailable_to_recovery`` is the production S5→S3.5 seam: it consumes the real S5 TOOL_UNAVAILABLE result and the planning result's EngineeringDecision, correlates the runner-reported ``unavailable_tool`` to its provisioning requirement through ``correlate_provisioning_requirement``, and stops at pending human approval. ``StructuredInstallerRegistry.resolve`` selects the installer through the central ``resolve_structured_installer_identity`` contract, which reuses the controlled executor's own install-method parser.

   Location: app/project_setup_application.py, class
   ProjectSetupApplicationService, methods
   prepare_missing_toolchain_setup, decide_missing_toolchain_setup,
   execute_missing_toolchain_setup, retry_missing_toolchain_verification,
   route_tool_unavailable_to_recovery;
   app/missing_toolchain_setup.py, classes MissingToolchainSetupRequest,
   MissingToolchainSetupResult, StructuredInstallerRegistry,
   function correlate_provisioning_requirement; app/execution.py, function
   resolve_structured_installer_identity; app/python_package_executor.py,
   function resolve_python_package_installer_identity

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

.. impl:: S5.2 target-workspace integrity during verification execution
   :id: IMPL_031
   :status: draft
   :implements: ARC_REQ_024, SUB_REQ_031

   ``_execute_verification_isolated`` executes every controlled
   verification runner against a disposable shadow copy of the real
   target workspace, never the real one, so a runner's own incidental
   filesystem side effects land only in the shadow copy and are
   discarded with it; the real target workspace is additionally
   snapshotted before and after as deterministic, attributable proof,
   identified per path by ``_entry_fingerprint`` -- a cryptographic
   content hash for a regular file, or a symlink's own raw target
   string, never a followed/dereferenced read, and never size or mtime
   alone (a same-size or mtime-preserving content rewrite is still
   detected). Any new, modified, or removed path in the real target
   workspace forces the step's status to ``WORKSPACE_INTEGRITY_VIOLATION``
   regardless of the runner's own reported exit code, and no
   pre-existing or newly observed path is ever deleted, reverted, or
   silently absorbed. Wired transparently into
   ``ControlledRunnerRegistry.execute_step`` so no individual runner
   (ESPHome, CMake, PlatformIO, pytest, unittest, or any future
   registered runner) needs its own workspace-isolation logic.

   Location: app/verification.py, function
   _execute_verification_isolated, class ControlledRunnerRegistry,
   method execute_step

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
   real failure, regardless of the reviewer's interpretation; a timeout
   without a real failure uses the one bounded rework only when the
   reviewer identifies a source-correctable cause and otherwise ends as
   verification_timeout; an execution error without a real failure ends as
   verification_execution_error without rework; a reviewer-infrastructure
   exception is never silently accepted as success.

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

.. impl:: Persisted approved-plan approval and controlled-execution lifecycle
   :id: IMPL_033
   :status: draft
   :implements: IF_REQ_015

   An approved SetupPlan is persisted via ``persist_setup_plan()``
   (plan plus Council provenance), human-approved via
   ``approve_setup_plan()`` through the central S3.2 approval authority,
   and executed later via ``execute_approved_plan_from_store()`` — the
   same central lifecycle Web and MCP adapters use. The stored approved
   plan, its project-root association, and the
   ``authorize_setup_plan_targets()`` → ``register_setup_step_targets()``
   capability/approval-provenance chain are resolved from the persisted
   store at execution time, never from ad-hoc caller state.

   Location: app/project_setup_application.py, functions persist_setup_plan,
   approve_setup_plan, execute_approved_plan_from_store;
   app/workflow_plan_store.py, class WorkflowPlanStore;
   app/execution.py, functions authorize_setup_plan_targets,
   register_setup_step_targets

.. impl:: Run-scoped request identity and correlation
   :id: IMPL_034
   :status: draft
   :implements: IF_REQ_001

   Every incoming request carries a structured identity
   (``CommonRequest`` with project_id/intent/source_interface) and is
   assigned a run correlation id (``run_id``, defaulting to the
   project id when no explicit run id is supplied). All run-scoped
   records — DiagnosticTrace events, final-approval and publish-approval
   records, change-provenance baselines and events — are stored and
   retrieved keyed by this run id, enabling unique assignment across the
   entire ADC run without the adapter reinterpreting the request.

   Location: app/common_request.py, class CommonRequest;
   app/project_setup_application.py (run_id resolution at plan entry);
   app/diagnostic_trace.py, get_trace(run_id) filtering;
   app/workflow_manager.py, per-run-id record stores

.. impl:: Target-environment context for S4.1 source generation
   :id: IMPL_036
   :status: draft
   :implements: SYS_REQ_032, ARC_REQ_027, SUB_REQ_041, IF_REQ_038

   After approved setup has realized the environment and before any source
   is generated, the S3→S4 handoff in
   ``DevelopmentWorkflow.execute_approved_and_run_development`` establishes
   the intended target environment (``establish_target_environment``):
   observed version of each plan step's execution target and of each
   planned component, probed only through the central controlled execution
   boundary and dispatched by the step's own ``setup_effect`` through a
   registry, plus the detected project conventions from Project
   Intelligence. The result (``TargetEnvironmentContext``) travels on the
   existing ``DevelopmentRequest`` (also through ``ReworkDevelopmentRequest``)
   and ``DeveloperAgent`` appends it to the generator task together with the
   instruction to preserve the user's technology choice and project
   conventions. A property that cannot be observed — failed or timed-out
   probe, unavailable target, or a setup effect without a registered probe —
   stays explicitly ``unknown``; the context's overall state is
   ``established``/``partial``/``unknown`` and its ``compatibility`` is
   always ``unknown`` because no generated source has been checked at that
   point. The state is recorded as redacted S4.1 generation evidence
   (``target_environment_state``). A request without a context is passed on
   unchanged and claims nothing. No language, toolchain or platform is
   preferred. This association identifies code responsibility and does not
   claim contract acceptance.

   Location: app/target_environment.py, functions
   establish_target_environment, class TargetEnvironmentContext;
   app/development_stage.py, classes DevelopmentRequest, DeveloperAgent,
   DevelopmentStage; app/controlled_rework_stage.py, class
   ReworkDevelopmentRequest; app/dev_workflow.py, method
   _with_target_environment

.. impl:: S5 verification bound to the established target environment
   :id: IMPL_037
   :status: draft
   :implements: ARC_REQ_028, SUB_REQ_042, IF_REQ_039

   S5 verifies in the target environment established before generation.
   ``DevelopmentTestingStage`` takes the verification target from the
   request's ``TargetEnvironmentContext.verification_target``: the
   environment target selected by the approved plan
   (``SetupPlan.environment_target_executable``, resolved once by
   ``ToolchainMaterializer`` through the central environment resolver and
   persisted by ``WorkflowPlanStore``) when it was observed, otherwise the
   single observed target. A plan-selected target that could not be observed
   is never replaced by another one, and several different observed targets
   are treated as ambiguous. Without a usable target no verification runs:
   the cycle ends as ``target_unconfirmed`` (never rework, no fabricated test
   result). With a target, ``verification_target()`` scopes the
   ``ControlledRunnerRegistry`` so Python runners execute through the target
   executable and tool-resolving runners look only in the target's own tool
   directory; a runner that does not execute through the target is reported
   TOOL_UNAVAILABLE instead of running on a substitute environment. This
   association identifies code responsibility and does not claim contract
   acceptance.

   Location: app/verification.py, function verification_target and class
   ControlledRunnerRegistry; app/development_testing_stage.py, class
   DevelopmentTestingStage; app/target_environment.py, property
   TargetEnvironmentContext.verification_target; app/requirement_model.py,
   field SetupPlan.environment_target_executable;
   app/toolchain_materializer.py; app/workflow_plan_store.py;
   app/dev_workflow.py, diagnosis projection of target_unconfirmed
