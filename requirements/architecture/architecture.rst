ADC Architecture Decisions
============================

Selected architecture for the ADC system.
Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt

.. arch:: Six-subsystem decomposition
   :id: ARC_001
   :status: draft
   :satisfies: SYS_REQ_001, SYS_REQ_002, SYS_REQ_005

   ADC is decomposed into six subsystems: S1 Requirement Intelligence,
   S2 Engineering Decision, S3 Environment & Setup, S4 Development & Change,
   S5 Quality & Verification, S6 Delivery & Outcome. This sequences the
   end-to-end capability (Understand → Decide → Prepare → Change → Verify →
   Deliver → Learn).

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §1

.. arch:: S1 Requirement Intelligence
   :id: ARC_002
   :status: draft
   :satisfies: SYS_REQ_003, SYS_REQ_004, SYS_REQ_006, SYS_REQ_015

   A dedicated subsystem is responsible for understanding what the project and
   user actually need. S1 analyzes user requests, inspects the project
   read-only, identifies and structures requirements, distinguishes mandatory
   from optional requirements, recognizes conflicts and uncertainties, connects
   requirements with evidence, and formulates requirements testably for later
   verification. S1 produces no technical solution and executes no setup action.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §1/S1

.. arch:: S2 Engineering Decision
   :id: ARC_003
   :status: draft
   :satisfies: SYS_REQ_007, SYS_REQ_014, SYS_REQ_015

   A dedicated subsystem decides WHAT shall be technically built and WITH WHICH
   engineering solution. S2 generates multiple solution variants, evaluates
   technical feasibility, compares risks and toolchain options, considers
   verification concepts, and produces a justified recommendation while keeping
   alternatives transparent. S2 executes no installation and mutates no
   environment; it produces Engineering Decisions, not setup execution.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §1/S2

.. arch:: S2.1 Engineering Alternatives
   :id: ARC_004
   :status: draft
   :satisfies: SYS_REQ_007, SYS_REQ_014

   S2 is internally decomposed into five sub-areas. S2.1 generates
   independent, technically sound engineering alternatives and collects
   cross-review evidence. Authority: generate alternatives and cross-review.
   Forbidden: selecting a recommendation, deciding admissibility, human
   selection, producing EngineeringDecision.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3A/S2.1

.. arch:: S2.2 Engineering Synthesis & Recommendation
   :id: ARC_005
   :status: draft
   :satisfies: SYS_REQ_008

   S2.2 synthesizes the cross-reviewed proposals and produces a recommendation
   to the user, including one bounded targeted repair attempt on structurally
   rejected synthesis. Forbidden: exercising technical admissibility policy
   independently of S2.3, or deterministically replacing the recommendation
   with another variant.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3A/S2.2

.. arch:: S2.3 Engineering Admissibility
   :id: ARC_006
   :status: draft
   :satisfies: SYS_REQ_014, SYS_REQ_015, SYS_REQ_018

   S2.3 is the sole technical admissibility authority within S2. It classifies
   admissible/inadmissible with exact deterministic reasons and preserves
   multiple admissible alternatives. Forbidden: selecting a preferred solution,
   modifying/merging/repairing any candidate.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3A/S2.3

.. arch:: S2.4 Human Engineering Authority
   :id: ARC_007
   :status: draft
   :satisfies: SYS_REQ_016

   S2.4 represents the final human decision authority. The human may accept the
   recommendation, select another admissible alternative, reject, defer, or
   request rework. Forbidden: overriding technical inadmissibility or silently
   substituting the desired candidate.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3A/S2.4

.. arch:: S2.5 Engineering Decision & S3 Handoff
   :id: ARC_008
   :status: draft
   :satisfies: SYS_REQ_015

   S2.5 produces the final S2 decision artifact and owns the S2→S3 boundary.
   The EngineeringDecision is the single artifact crossing the boundary in the
   normal case. S2.5 preserves exact candidate identity, selection authority,
   and validation provenance. Forbidden: inventing a selection, choosing a
   winner, repairing a candidate.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3A/S2.5

.. arch:: S3 Environment & Setup
   :id: ARC_009
   :status: draft
   :satisfies: SYS_REQ_009, SYS_REQ_015

   S3 transfers the chosen engineering solution into a real, usable development
   and test environment in a controlled manner. S3 derives the target state from
   the Engineering Decision, observes the current state, compares them, avoids
   unnecessary changes, produces a SetupPlan, classifies setup steps, verifies
   that each executable step has a matching controlled executor, obtains human
   approval, performs controlled execution, re-verifies the result, and updates
   EnvironmentState.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §1/S3

.. arch:: S3.1 Setup Planning
   :id: ARC_010
   :status: draft
   :satisfies: SYS_REQ_009

   S3.1 determines WHICH setup actions are required and controllably
   materializes the Engineering Decision into a structured SetupPlan with
   classified SetupSteps. Forbidden: executing actions, granting human approval,
   or reopening the S2 candidate selection.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3B/S3.1

.. arch:: S3.2 Setup Approval
   :id: ARC_011
   :status: draft
   :satisfies: SYS_REQ_016, SYS_REQ_024

   S3.2 is the sole human approval authority over planned mutating setup actions,
   separated from planning (S3.1) and execution (S3.3). Forbidden: planning,
   executing, or replacing human authority with system or deterministic policy.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3B/S3.2

.. arch:: S3.3 Controlled Execution
   :id: ARC_012
   :status: draft
   :satisfies: SYS_REQ_019, SYS_REQ_024

   S3.3 performs approved setup mutations controllably and deterministically,
   requiring an approved SetupPlan and executable SetupStep, enforcing the
   setup execution boundary, integrating replay/idempotency protection from
   S3.4, and delegating concrete setup mutation to the responsible registered
   executor.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3B/S3.3

.. arch:: S3.4 Execution State & Idempotency
   :id: ARC_013
   :status: draft
   :satisfies: SYS_REQ_028, SYS_REQ_031

   S3.4 manages persisted execution identity and state per setup step, with
   claim/check protection, cross-process safety, content-fingerprint binding,
   known-success reuse, fail-closed on unknown/recovery state, and
   forced new generation/approval on changed content. S3.4 concerns only
   setup-step execution identity, not broader workflow-stage synchronization.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3B/S3.4

.. arch:: S3.5 Missing-Toolchain Recovery
   :id: ARC_014
   :status: draft
   :satisfies: SYS_REQ_028

   S3.5 converts generic TOOL_UNAVAILABLE evidence into bounded,
   approval-bound recovery using the authorities of S3.1/S3.2/S3.3 again,
   with exactly bounded recovery and re-execution of the previously planned
   verification. Forbidden: unapproved installation, unbounded loops,
   reopening S2 engineering selection, or stack-specific central policy.

   S3.5 recovery pauses at the existing S3.2 human approval boundary; one TOOL_UNAVAILABLE outcome yields at most one recovery, and its setup execution and verification retry each run at most once. The recovery resolves the unavailable tool identity to its provisioning requirement and its installer identity only through explicit correlation (IF_REQ_037) and fails closed otherwise.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3B/S3.5

.. arch:: S4 Development & Change
   :id: ARC_015
   :status: draft
   :satisfies: SYS_REQ_010, SYS_REQ_019

   S4 performs the actual technical change on the project in a controlled
   manner. S4 converts requirements into structured development work, respects
   project conventions, produces structured Engineering Changes, applies them
   via controlled ChangeApplication within authorized TargetScope, maintains
   Change Provenance, and protects pre-existing target state.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §1/S4

.. arch:: S4.1 Development Change Generation
   :id: ARC_016
   :status: draft
   :satisfies: SYS_REQ_010, SYS_REQ_032

   S4.1 generates structured developer changes without performing
   ChangeTarget mutation. Critical invariant: an empty development change set
   must fail — S4.1 has no no-op authority.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3C/S4.1

.. arcreq:: Source generation uses established target-environment compatibility context
   :id: ARC_REQ_027
   :status: draft
   :derived_from: ARC_016

   Before generation, relevant target-environment properties affecting source
   compatibility shall be established and supplied to the generator. Source
   compatibility shall not be assumed when evidence is unavailable.

   Source: ARC_016 (S4.1), ZIEL_003, ZIEL_010

.. arcreq:: Verification executes generated source in its intended target environment
   :id: ARC_REQ_028
   :status: draft
   :derived_from: ARC_039

   S5 shall execute the applicable project verification for generated source
   in the same intended target environment established before generation. If
   that environment cannot be selected or used reliably, verification shall
   not confirm compatibility.

   Source: ARC_039, SYS_REQ_032

.. arch:: S4.2 Test Change Generation
   :id: ARC_017
   :status: draft
   :satisfies: SYS_REQ_010

   S4.2 generates structured test changes with an explicit no-op contract.
   A valid no-op requires explicit declaration; an empty changes array alone is
   not a no-op.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3C/S4.2

.. arch:: S4.3 Change Application
   :id: ARC_018
   :status: draft
   :satisfies: SYS_REQ_010, SYS_REQ_019

   S4.3 applies a structured Engineering Change via the controlled
   ChangeApplication mechanism onto its authorized ChangeTarget/TargetScope,
   writing generated content exclusively within the authorized scope, classifying
   actual apply attempts, and going fail-closed on partial or skipped
   application.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3C/S4.3

.. arch:: S4.4 Change Provenance & Attribution
   :id: ARC_019
   :status: draft
   :satisfies: SYS_REQ_025

   S4.4 provides traceable change origin with baseline-before, event-after
   attribution, run/phase attribution, and controlled change evidence.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3C/S4.4

.. arch:: S5 Quality & Verification
   :id: ARC_020
   :status: draft
   :satisfies: SYS_REQ_011, SYS_REQ_013, SYS_REQ_020

   S5 mechanically and really verifies whether the technical solution and
   changes actually function. S5 produces a VerificationPlan, uses
   project-specific build and test systems, separates unit/subcomponent/system/
   real-system evidence, does not replace results with AI self-assertions,
   detects toolchain availability, maps verification dependencies, treats real
   test results as authoritative evidence, and connects failure modes with test
   coverage.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §1/S5

.. arch:: S5.1 Verification Planning
   :id: ARC_021
   :status: draft
   :satisfies: SYS_REQ_011

   S5.1 derives a structured VerificationPlan from project requirements and the
   present toolchain.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3D/S5.1

.. arch:: S5.2 Controlled Verification Execution
   :id: ARC_022
   :status: draft
   :satisfies: SYS_REQ_011

   S5.2 executes registered controlled verification runners deterministically.
   Toolchain-specific logic belongs exclusively in runners/adapters, never in
   central orchestration.

   The execution time budget of every external verification or build operation is part of the VerificationStep execution policy selected by S5.1 before execution; S5.2 runners consume that budget and are never its authoritative source, and no different technology-specific budget is substituted at execution time. A step without a valid budget fails closed before any process starts. When the budget expires, S5.2 terminates the entire controlled process tree and reports TIMEOUT with the partial evidence captured so far; the timeout return code is a synthetic marker, never a real process exit status.

   EXECUTION_ERROR is a controlled-verification execution-infrastructure failure after the controlled process was successfully started, where no valid project verification verdict was produced (for example a failure communicating with the started process, a controlled-process transport or runtime failure, or a failure of the controlled execution boundary itself). S5.2 decides the launch boundary structurally, never from message text: only an executable or capability that cannot be started is reported as TOOL_UNAVAILABLE; a controlled-execution failure after a successful start is reported as EXECUTION_ERROR with its error category, only after the owned process tree has been contained, and never as TOOL_UNAVAILABLE, TIMEOUT, PASS or FAIL. A launch failure that is not an unavailable executable or capability (for example exhausted process resources) cannot be remedied by provisioning and is likewise reported as EXECUTION_ERROR, never as TOOL_UNAVAILABLE.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3D/S5.2

.. arch:: S5 verifies generated source in its intended target environment
   :id: ARC_039
   :status: draft
   :satisfies: SYS_REQ_011, SYS_REQ_032

   S5 verification of generated source executes in the same intended target
   environment established for that source. Verification run in a different
   host or default environment does not establish compatibility with the
   intended target.

   Source: SYS_REQ_032; ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3D/S5

.. arch:: S5.3 Verification Evidence Aggregation
   :id: ARC_023
   :status: draft
   :satisfies: SYS_REQ_011

   S5.3 aggregates verification results per step and preserves failure evidence
   in a structured manner.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3D/S5.3

.. arch:: S5.4 Diagnostic Evidence Formatting
   :id: ARC_024
   :status: draft
   :satisfies: SYS_REQ_021

   S5.4 performs deterministic formatting of already-produced verification
   evidence. S5.4 has no diagnostic authority.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3D/S5.4

.. arch:: S5.5 Diagnosis Interpretation
   :id: ARC_025
   :status: draft
   :satisfies: SYS_REQ_020, SYS_REQ_021

   S5.5 interprets diagnostic evidence. Forbidden: reinterpreting a real
   deterministic test failure as success.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3D/S5.5

.. arch:: S5.6 Deterministic Test Outcome Policy
   :id: ARC_026
   :status: draft
   :satisfies: SYS_REQ_020

   S5.6 enforces the deterministic test outcome policy: a real
   verification/test failure forces rework regardless of the interpretation
   from S5.5.

   TOOL_UNAVAILABLE is not a real verification or test failure. S5.6 routes it across the S5→S3 boundary into bounded S3.5 Missing-Toolchain Recovery instead of S5.7 developer rework; S3.5 then owns the recovery request.

   TIMEOUT is a fail-closed, non-PASS verification outcome, but a timeout alone is not proof of a source-code defect. S5.6 hands a timeout to the single bounded S5.7 developer rework only when the S5.5 diagnosis identifies a source-correctable cause; otherwise the timeout remains a structured terminal verification outcome and is routed neither to S5.7 rework nor to S3.5 recovery. A real verification or test failure alongside the timeout still forces rework.

   EXECUTION_ERROR is not a real verification or test failure and not proof of a source-code defect: no valid project verdict exists. S5.6 routes it to the fail-closed terminal verification_execution_error outcome, meaning that verification did not establish PASS or FAIL of the project because the ADC execution infrastructure failed. It is never accepted, never handed to S5.7 developer rework (an S5.5 diagnosis may describe it but cannot authorize rework), and never routed to S3.5 recovery. A real verification or test failure alongside it still forces rework.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3D/S5.6

.. arch:: S5.7 Controlled Rework Orchestration
   :id: ARC_027
   :status: draft
   :satisfies: SYS_REQ_023

   S5.7 orchestrates exactly one bounded controlled rework cycle. Rework is
   triggered by the S5 verification verdict; ownership therefore lies correctly
   with S5, not S4.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3D/S5.7

.. arch:: S6 Delivery & Outcome
   :id: ARC_028
   :status: draft
   :satisfies: SYS_REQ_012, SYS_REQ_022

   S6 transfers only technically verified and human-approved results into a
   final state in a controlled manner. S6 provides Final Approval, controlled
   Delivery Operation, respects Delivery Target, performs controlled Publish
   where applicable, maintains Delivery Evidence, preserves Change Provenance,
   does not absorb foreign target state changes not belonging to the current
   run, prevents silent destructive repair of the Delivery state, and prevents
   automatic publication outside defined boundaries. Delivery is a separate
   engineering step. Version control is optional and project-specific.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §1/S6

.. arch:: S2-S3-S4-S5-S6 boundaries
   :id: ARC_029
   :status: draft
   :satisfies: SYS_REQ_015, SYS_REQ_031

   Explicit boundaries connect S2→S3→S4→S5→S6. S3 must consume the already
   selected Engineering Decision without reopening selection authority. S4 may
   start only after required S3 responsibilities are fulfilled. S5 may start
   only after required S4 mutations succeeded. S5→S4 has exactly one bounded
   rework cycle. S5→S3 provides bounded Missing-Toolchain recovery. S5→S6
   delivers terminal verification evidence only after the deterministic policy
   is satisfied.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §4

.. arch:: Technology-neutral architecture vocabulary
   :id: ARC_030
   :status: draft
   :satisfies: SYS_REQ_017

   The architecture uses a defined set of technology-neutral terms (Requirement,
   EngineeringDecision, SetupEffect, SetupPlan, Capability, Executor,
   VerificationPlan, VerificationResult, EnvironmentState, Change, ChangeTarget,
   ChangeApplication, ExecutionContext, TargetScope, DeliveryOperation,
   DeliveryTarget, DeliveryState, DeliveryEvidence) to implement
   technology-neutrality structurally. Stack-specific logic belongs in adapters,
   inspectors, executors, runners, change-appliers, and providers, never in
   central orchestration.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §2, §5

.. arch:: Producer-Artifact-Consumer handoff chain
   :id: ARC_031
   :status: draft
   :satisfies: SYS_REQ_025, SYS_REQ_027

   The architecture defines an explicit Producer→Artifact→Consumer chain for
   every important transition: User/Adapter→CommonRequest→S1,
   ProjectInspector→ProjectIntelligence→S1/S2, S1→RequirementSet→S2, S2→
   EngineeringDecision→S3, S3→SetupPlan→Approval/Execution, S3→
   EnvironmentState→S4/S5, S4→StructuredChanges/ChangeProvenance→S5, S5→
   VerificationResult→FinalApproval/S6, S6→DeliveryEvidence→User/ProjectStatus/
   Learning. For each important artifact the following shall be answerable: who
   creates it, who may modify it, where it is persisted, who consumes it, which
   authority applies, which evidence proves its state, which contract version
   applies.

   The recovery transition is part of this chain: S5→VerificationResult (TOOL_UNAVAILABLE, with the unavailable tool identity)→S3.5→missing-toolchain recovery request→S3.2 Approval→S3.3 Execution→S5 retry of the persisted VerificationPlan. The recovery request carries the unavailable tool identity, the correlated provisioning requirement, the selected EngineeringDecision's variant identity, and the persisted VerificationPlan and VerificationResult, so its provenance is answerable (IF_REQ_037).

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §8

.. arch:: Diagnostic Trace authority mapping
   :id: ARC_032
   :status: draft
   :satisfies: SYS_REQ_021, SYS_REQ_026

   The architecture maps the Zielbild requirement that Diagnostic Evidence must
   not replace formal decision-authority onto concrete Sx.y authorities.
   Diagnostic Trace/Evidence shall not substitute for: CandidateValidation
   (S2.3), Human Engineering Selection (S2.4), Setup Approval (S3.2), Approval
   Provenance, deterministic VerificationResult (S5), Final Approval (S5→S6),
   or Publish Approval (S6).

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §9

.. arch:: Engineering Council and Chairman realization
   :id: ARC_033
   :status: draft
   :satisfies: SYS_REQ_007, SYS_REQ_008

   The architecture realizes alternative generation and recommendation through
   a Council with Chairman role. The Council generates multiple technically
   sound alternatives and evaluates them in cross-review. The Chairman
   synthesizes proposals and cross-reviews and selects a technically justified
   recommendation. The Chairman is not a deterministic solver but an engineering
   recommendation selector.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §6

.. arch:: Materializability and setup contracts
   :id: ARC_034
   :status: draft
   :satisfies: SYS_REQ_009, SYS_REQ_024

   Before mutating execution, ADC must architecturally prove: which SetupEffect
   is required, which SetupStep is produced from it, which controlled Executor
   is responsible, which structured input schema the Executor expects, whether
   all required fields are present, whether the execution representation is
   supported, whether the Capability is registered, whether the project scope is
   correct, whether the operation is permissible, whether human approval is
   required and present, and whether the result can be verified afterward. The
   architecture models readiness states: already_satisfied, materializable,
   manual_review, unsupported, blocked, approval_required, executable,
   verification_required.

   Requirement activation and installation state are distinct. A ToolchainItem's installation state (needs_install, already_installed, unavailable) never overrides its requirement's activation. An inactive or non-blocking requirement may legitimately remain deferred without a SetupStep; a requirement satisfied through a declared provided_by relation is provided without its own SetupStep. An active, blocking requirement that is missing shall result in an actionable SetupStep or an explicitly non-executable state (manual_review, unsupported, blocked); it shall never silently cross the S3→S4 boundary.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §7

   The selected traceability chain links Zielbild→SystemRequirements→
   Architecture→ArchitectureDerivedRequirements→SubsystemRequirements→
   InterfaceRequirements with explicit parent/child relationships and network
   validation.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §12

.. arch:: Reference workflow through S1-S6
   :id: ARC_036
   :status: draft
   :satisfies: SYS_REQ_002, SYS_REQ_031

   The architecture defines a reference workflow through S1–S6: user formulates
   goal → ADC inspects project read-only → S1 produces structured requirements
   → requirements validated → current EnvironmentState observed → S2 Council
   generates multiple variants → Council agents review → Chairman synthesizes
   and selects recommendation → variants checked against requirements,
   constraints, materializability, execution/verification feasibility (S2.3) →
   user sees recommendation and alternatives → user decides (S2.4) → S3
   produces SetupPlan → non-executable or manual parts visibly marked → human
   approval for mutating setup steps (S3.2) → controlled setup execution (S3.3)
   → environment re-verification → S4 Development & Change → S5 real tests and
   verification → on failure: Diagnosis → missing contract/failure mode →
   regression test → fix → re-verification (S5.5–S5.7) → final approval → S6
   controlled delivery → separate publish approval where applicable →
   controlled publish where applicable → outcome and evidence persisted → FMEA/
   Learning Memory updated only after accepted evidence.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §10
   The architecture separates different knowledge types structurally: Knowledge
   (current valid project/system contract), Evidence (facts from the current
   run), Learning Memory (accepted insights), and Deterministic Contracts.
   Engineering FMEA is maintained as a living project instrument derived from
   requirements, architecture, technologies, toolchains, hardware, operating
   environment, past errors, tests, and real-system evidence.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §1/S5 (Verification→Learning)

.. arch:: Engineering Supervisor (planned cross-cutting architecture)
   :id: ARC_038
   :status: draft
   :satisfies: SYS_REQ_030

   A cross-cutting Engineering Supervisor is planned as a quality layer
   observing S1 through S6. It is not a seventh subsystem. It shall start
   read-only, recognizing rather than automatically repairing. It shall never
   autonomously execute destructive actions or alternative fixes.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §11


Architecture-derived Requirements
=================================

Requirements that exist because of selected Architecture decisions.

.. arcreq:: Multiple independently reviewed alternatives required
   :id: ARC_REQ_003
   :status: draft
   :derived_from: ARC_004

   The selected architecture shall generate multiple independent
   engineering alternatives and collect cross-review evidence for each
   before a recommendation is made.

   Source: ARC_004 (S2.1), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3A/S2.1

.. arcreq:: Technical admissibility independent of recommendation authority
   :id: ARC_REQ_004
   :status: draft
   :derived_from: ARC_006

   Technical admissibility shall be determined by a dedicated authority
   structurally separate from the recommendation and synthesis functions,
   using exact deterministic reasons. Admissibility shall never be
   inferred from a recommendation.

   Source: ARC_006 (S2.3), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3A/S2.3

.. arcreq:: S2→S3 boundary uses single EngineeringDecision artifact
   :id: ARC_REQ_006
   :status: draft
   :derived_from: ARC_008

   The handoff from engineering decision to environment preparation shall
   use a single EngineeringDecision artifact preserving exact candidate
   identity, selection authority, and validation provenance. S3 shall
   consume the already-selected decision without reopening selection.

   Source: ARC_008 (S2.5), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3A/S2.5

.. arcreq:: Setup planning produces structured plan without execution
   :id: ARC_REQ_007
   :status: draft
   :derived_from: ARC_010

   Setup planning shall determine which setup actions are required and
   produce a structured SetupPlan with classified steps. Planning shall
   not execute actions, grant approvals, or reopen engineering selection.

   Source: ARC_010 (S3.1), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3B/S3.1

.. arcreq:: Human approval structurally before mutation
   :id: ARC_REQ_008
   :status: draft
   :derived_from: ARC_011

   Human approval for mutating setup actions shall be a dedicated
   architectural boundary structurally separated from planning and
   execution. No mutating setup action shall execute without an explicit
   human approval matching the exact planned content.

   Source: ARC_011 (S3.2), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3B/S3.2

.. arcreq:: Setup mutation only through controlled execution boundary
   :id: ARC_REQ_009
   :status: draft
   :derived_from: ARC_012

   Approved setup mutations shall execute only through a dedicated
   controlled execution boundary requiring an approved plan, executable
   steps, and a responsible registered executor. Every execution shall
   be deterministically recorded with replay/idempotency protection.

   Every controlled execution surface, including a visible interactive terminal, shall preserve the validated execution semantics through to the final command: the authorized executable and working-directory scope, controlled child environment, unchanged argv, exactly one command launch per authorized invocation, real exit-status propagation, and no hidden installation fallback.

   Source: ARC_012 (S3.3), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3B/S3.3

.. arcreq:: Development changes require structured generation
   :id: ARC_REQ_012
   :status: draft
   :derived_from: ARC_016

   Development changes shall be generated as structured change sets. An
   empty development change set shall fail — no silent no-op authority
   exists for development mutations.

   Source: ARC_016 (S4.1), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3C/S4.1

.. arcreq:: Change provenance must be recorded per run
   :id: ARC_REQ_014
   :status: draft
   :derived_from: ARC_019

   Every change shall have baseline-before and event-after provenance
   with run and phase attribution. Change evidence shall be captured
   and preserved for traceability.

   Source: ARC_019 (S4.4), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3C/S4.4

.. arcreq:: Controlled verification execution through registered runners
   :id: ARC_REQ_016
   :status: draft
   :derived_from: ARC_022

   Verification shall execute through registered controlled runners.
   Each verification step shall produce a result with status, return
   code, timeout, diagnostics, and runner identity preserved.

   Source: ARC_022 (S5.2), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3D/S5.2

.. arcreq:: Verification execution shall preserve target-workspace integrity
   :id: ARC_REQ_024
   :status: draft
   :derived_from: ARC_022

   Verification execution shall not introduce uncontrolled changes into
   the target project. A verification runner that invokes an external
   tool shall preserve target-workspace integrity: filesystem side
   effects produced merely as verification side effects shall either be
   isolated from the target workspace, or pass through an explicitly
   authorized controlled-mutation/provenance contract where such
   mutation is intentionally part of system behavior. Incidental
   cache/build/helper artifacts produced merely as verification side
   effects are not automatically approved engineering changes.
   Verification success shall never silently legitimize workspace
   mutation; unexpected target mutation during verification shall fail
   closed and shall never be absorbed into delivery merely because the
   verifier itself reported success.

   Source: ARC_022 (S5.2), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3D/S5.2

.. arcreq:: Rework is bounded to exactly one cycle
   :id: ARC_REQ_021
   :status: draft
   :derived_from: ARC_027

   Rework triggered by verification failure shall be limited to exactly
   one bounded controlled cycle. No unbounded rework loops shall occur.

   Source: ARC_027 (S5.7), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3D/S5.7

.. arcreq:: Subsystem boundaries enforce sequencing constraints
   :id: ARC_REQ_023
   :status: draft
   :derived_from: ARC_029

   Cross-subsystem boundaries shall enforce that each subsystem may
   start only after the required upstream responsibilities are
   fulfilled. The S5→S4 boundary shall allow exactly one rework cycle.
   The S5→S3 boundary shall allow only bounded missing-toolchain
   recovery.

   Source: ARC_029, ADC_Architektur_Ausfuehrliche_Beschreibung.txt §4

.. arcreq:: Software installation shall execute inside a visible interactive terminal
   :id: ARC_REQ_025
   :status: draft
   :derived_from: ARC_012, ARC_REQ_009

   Every ADC-controlled software installation (pip/venv package
   installation, apt/system package installation, toolchain/package-manager
   installation, and any other classified installation action) shall
   execute inside a visible, interactive terminal session that shows the
   real installation process/output and provides a real interactive TTY,
   so that a `sudo` prompt, when required, can be answered directly by
   the human in that terminal. This applies even when the specific
   installation would not itself require sudo: installation shall never
   execute silently as a hidden/background subprocess. Terminal
   availability is a precondition for starting such an installation: if
   no approved/supported interactive terminal can be opened, installation
   shall not proceed silently and shall fail closed with a structured
   cause. The terminal shall close automatically once the installation
   command has terminated; cancelling or closing the terminal before
   successful completion shall never be treated as installation success.
   ADC shall never request, receive, store, pipe, cache, log, serialize,
   or persist the sudo password itself, in any form -- sudo
   authentication, when needed, occurs entirely inside the terminal's own
   interactive TTY. The terminal is only the execution surface for an
   already-authorized installation; it shall never itself create
   installation authority.

   This terminal execution surface shall comply with the central execution-semantics contract in ARC_REQ_009; visibility and interactive authentication do not relax that contract.

   Source: ARC_012 (S3.3), CLAUDE-ADC-VISIBLE-TERMINAL-FOR-SOFTWARE-INSTALLATION-001

.. arcreq:: Delivery to authorized remote live runtime targets
   :id: ARC_REQ_026
   :status: draft
   :derived_from: ARC_028

   The delivery subsystem shall support controlled delivery of an approved
   and verified change to an explicitly authorized external live runtime
   target using the project's appropriate target-specific delivery
   mechanism. The runtime target's identity, address, and access details
   are project configuration and execution evidence — never hard-coded ADC
   product semantics. Delivery shall operate only on an approved verified
   delta. Unrelated pre-existing target state shall remain preserved. The
   chosen delivery mechanism may differ by target and project technology,
   consistent with version control being optional and project-specific.

   Source: ARC_028 (S6 Delivery & Outcome); authority transitively via
   ARC_028 satisfies SYS_REQ_012, SYS_REQ_022
   (CLAUDE-ADC-TEST035-REMOTE-DELIVERY-REQUIREMENTS-DELTA-IMPLEMENT-001)
