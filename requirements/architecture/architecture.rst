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
   :satisfies: SYS_REQ_010

   S4.1 generates structured developer changes without performing
   ChangeTarget mutation. Critical invariant: an empty development change set
   must fail — S4.1 has no no-op authority.

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3C/S4.1

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

   Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3D/S5.2

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
