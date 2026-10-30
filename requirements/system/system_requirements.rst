ADC System Requirements
=======================

Derived exclusively from the accepted ADC Zielbild.
Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt and zielbild/zielbild.rst

.. sysreq:: Integrated engineering platform
   :id: SYS_REQ_001
   :status: draft
   :realizes: ZIEL_001

   ADC shall operate as an integrated engineering platform supporting software,
   firmware, and hardware engineering.

   Source: ZIEL_001 (§1 Purpose/Mission)

.. sysreq:: Complete controlled engineering process
   :id: SYS_REQ_002
   :status: draft
   :realizes: ZIEL_002

   ADC shall provide a complete, traceable, and controlled engineering process
   covering: understanding project and requirements, making technically founded
   decisions, controlled materialization of the chosen solution, controlled
   change implementation, real mechanical verification, controlled delivery, and
   durable learning from collected evidence.

   Source: ZIEL_002 (§1 Purpose/Mission)

.. sysreq:: Project support with Existing Project First
   :id: SYS_REQ_003
   :status: draft
   :realizes: ZIEL_003, ZIEL_025, ZIEL_026

   ADC shall support both existing and greenfield projects, with priority for
   existing project structure, conventions, and toolchains. ADC shall adapt to
   the project rather than imposing its own structures. Changing toolchain or
   environment shall require a documented technical reason; "ADC prefers
   technology X" alone is not sufficient.

   Source: ZIEL_003, ZIEL_025, ZIEL_026 (§2, §6)

.. sysreq:: Heterogeneous multi-toolchain project understanding
   :id: SYS_REQ_004
   :status: draft
   :realizes: ZIEL_004

   ADC shall understand heterogeneous and multi-toolchain projects without
   artificially unifying them. Projects containing multiple independent
   technical areas (e.g., backend, frontend, firmware, hardware configuration
   with distinct languages, build systems, and test systems) shall be understood
   separately while being brought together in a common engineering context.

   Source: ZIEL_004 (§2 Scope)

.. sysreq:: E/E engineering platform evolution with hardware/firmware governance
   :id: SYS_REQ_005
   :status: draft
   :realizes: ZIEL_005, ZIEL_057

   ADC shall evolve toward an integrated electrical/electronic engineering
   platform. ADC governance principles — engineering decision before mutation,
   controlled tool/device capabilities, human approval for physical actions,
   real verification, traceable evidence, FMEA, and traceable delivery — shall
   apply equally to firmware, electronics, hardware, and physical-system
   engineering artifacts.

   Source: ZIEL_005, ZIEL_057 (§2 Scope)

.. sysreq:: Read-only project inspection and requirement identification
   :id: SYS_REQ_006
   :status: draft
   :realizes: ZIEL_006, ZIEL_041

   ADC shall understand a user request and inspect an existing project
   read-only. ADC shall identify and structure requirements, distinguish
   mandatory from optional requirements, and connect requirements with
   evidence. ADC shall distinguish observed project reality from deliberately
   established project decisions and bring them together without silently
   overwriting contradictory sources.

   Source: ZIEL_006, ZIEL_041 (§3, §12)

.. sysreq:: Solution variant generation and evaluation
   :id: SYS_REQ_007
   :status: draft
   :realizes: ZIEL_007, ZIEL_029

   ADC shall generate multiple technically sound engineering solution variants
   rather than enforcing a single predetermined solution. Variants shall be
   evaluated against real engineering criteria including: requirement
   fulfillment, project fit, necessary changes, reuse of existing capabilities,
   risks, reproducibility, materializability, controlled executability, real
   verifiability, cost/complexity, and introduced dependencies.

   Source: ZIEL_007, ZIEL_029 (§3, §8)

.. sysreq:: Traceable recommendation with structured alternative presentation
   :id: SYS_REQ_008
   :status: draft
   :realizes: ZIEL_008, ZIEL_044

   ADC shall produce a technically justified recommendation and present it to
   the user in a structured, traceable manner together with alternatives. The
   presentation shall include: variant name, technical justification, fulfilled
   requirements, required environment, required changes, risks, verification
   strategy, expected setup steps, human approval points, and for each
   alternative: admissibility, advantages/disadvantages, additional effort,
   additional risks, and verification implications.

   Source: ZIEL_008, ZIEL_044 (§3, §5, §12)

.. sysreq:: Controlled environment preparation
   :id: SYS_REQ_009
   :status: draft
   :realizes: ZIEL_009

   ADC shall transfer the chosen engineering solution into a real, usable
   environment in a controlled manner without reopening the already-made
   engineering selection.

   Source: ZIEL_009 (§3, §4)

.. sysreq:: Controlled technical change execution
   :id: SYS_REQ_010
   :status: draft
   :realizes: ZIEL_010

   ADC shall carry out the actual technical change on the project in a
   controlled manner, within authorized scope, with full change provenance and
   protection of pre-existing target state.

   Source: ZIEL_010 (§3, §9)

.. sysreq:: Real verification with evidence separation
   :id: SYS_REQ_011
   :status: draft
   :realizes: ZIEL_011, ZIEL_037, ZIEL_038

   ADC shall mechanically and actually verify whether the technical solution and
   changes function, using project-specific build and test systems. ADC shall
   provide multiple clearly separated verification levels from local
   function/contract checks through component-level checks to real-world
   integration verification. Real test results shall be authoritative evidence.
   Toolchain availability shall be detected and verification dependencies
   mapped. Failure modes shall be connected with test coverage.

   Source: ZIEL_011, ZIEL_037, ZIEL_038 (§3, §10)

.. sysreq:: Controlled delivery of verified outcome
   :id: SYS_REQ_012
   :status: draft
   :realizes: ZIEL_012, ZIEL_045, ZIEL_046, ZIEL_047, ZIEL_048

   ADC shall deliver a verified and approved result in a controlled manner.
   Delivery shall not represent unverified or unapproved work as accepted final
   result. ADC shall not appropriate foreign target state changes not belonging
   to the current run. Only targets with fully proven provenance shall be
   transferred to final state. ADC shall not automatically discard, overwrite,
   undo, or silently absorb pre-existing target state. Where publish applies, it
   shall be a separate explicit action with its own approval boundary. Version
   control shall be optional and project-specific.

   Source: ZIEL_012, ZIEL_045, ZIEL_046, ZIEL_047, ZIEL_048 (§3, §13)

.. sysreq:: Durable evidence-based learning
   :id: SYS_REQ_013
   :status: draft
   :realizes: ZIEL_013, ZIEL_051, ZIEL_054

   ADC shall durably learn from accepted evidence, including from failed
   outcomes. Learning shall not be artificially coupled to successful delivery.
   Every locally reproducible, actually observed defect shall be durably
   transferred into deterministic test coverage — not only the concrete failure
   case but the generalized failure pattern it represents. A learning shall only
   be accepted durably after: Observation → Analysis → Test → Evidence →
   Acceptance → Learning accepted.

   Source: ZIEL_013, ZIEL_051, ZIEL_054 (§3, §15)

.. sysreq:: Solution variability and quality gates
   :id: SYS_REQ_014
   :status: draft
   :realizes: ZIEL_014, ZIEL_015, ZIEL_030, ZIEL_031

   ADC shall not enforce the same solution class for identical input.
   Different project-specific engineering solutions may all be correct.
   ADC shall not be a deterministic solver — different technically valid
   recommendations for the same starting situation are permitted. ADC shall
   enable solution diversity but block technical invalidity early. Every chosen
   solution shall fulfill binding requirements, violate no constraints, be
   technically materializable, possess appropriate controlled execution
   capability, have a defined verification strategy, be secured by deterministic
   tests, and be presentable to the human before mutating execution.

   Source: ZIEL_014, ZIEL_015, ZIEL_030, ZIEL_031 (§3, §8)

.. sysreq:: Authority separation guarantees
   :id: SYS_REQ_015
   :status: draft
   :realizes: ZIEL_016, ZIEL_017, ZIEL_018, ZIEL_019

   ADC shall guarantee the following authority separations: understanding
   requirements shall not select a technical solution nor execute setup actions;
   making an engineering decision shall not execute installations nor mutate
   environments; preparing the environment shall not reopen the already-made
   engineering selection; a technical recommendation is not an automatic
   execution authorization; human selection or approval shall never make a
   technically inadmissible solution admissible.

   Source: ZIEL_016, ZIEL_017, ZIEL_018, ZIEL_019 (§4, §5)

.. sysreq:: Human decision authority
   :id: SYS_REQ_016
   :status: draft
   :realizes: ZIEL_023, ZIEL_024

   The human shall remain the decisive authority at mutating and safety-relevant
   boundaries. The system shall clearly separate a technical recommendation
   from execution approval. The user may accept a recommendation, select another
   admissible variant, request a change, reject planning, or request a new
   decision round.

   Source: ZIEL_023, ZIEL_024 (§5)

.. sysreq:: Technology neutrality
   :id: SYS_REQ_017
   :status: draft
   :realizes: ZIEL_027, ZIEL_028

   ADC shall remain technology-open. No concrete implementation technology shall
   dominate the central ADC system or become the hidden default. Concrete
   technologies exist exclusively as replaceable current implementation,
   project-specific choice, or non-normative example. New technical stacks shall
   be integrable without fundamentally rebuilding ADC. Various functional areas
   of ADC may be realized in arbitrary implementation technologies.

   Source: ZIEL_027, ZIEL_028 (§7)

.. sysreq:: Requirements as binding contract
   :id: SYS_REQ_018
   :status: draft
   :realizes: ZIEL_032

   Requirements shall form the technical contract against which solutions are
   evaluated. A solution shall only be admissible if it fulfills the binding
   requirements for the concrete operation. Requirements shall possess evidence
   and be linkable with tests, forming: Requirement → Contract → Verification →
   Evidence.

   Source: ZIEL_032 (§8)

.. sysreq:: Structured controlled mutation
   :id: SYS_REQ_019
   :status: draft
   :realizes: ZIEL_033, ZIEL_034, ZIEL_035

   ADC shall not model changes as a collection of unstructured operation
   representations. No freely formulated or unstructured analysis result shall
   automatically become a mutating action. Every environment-altering or
   project-altering action shall semantically describe WHAT is to be changed and
   be implemented via structured, controlled mechanisms. Every mutating
   execution shall run through controlled boundaries checking: capability,
   executing instance, operation type, authorized scope, approval, argument
   structure, and operational limits. Creative analysis and synthesis shall
   contribute exclusively to decision preparation and justification, not to
   direct uncontrolled mutation. There shall be no general path through which a
   reasoning system can directly bring unstructured operations to execution.

   Source: ZIEL_033, ZIEL_034, ZIEL_035 (§9)

.. sysreq:: Real verification dominance over interpretation
   :id: SYS_REQ_020
   :status: draft
   :realizes: ZIEL_020, ZIEL_038

   A real verification result shall not be overridden by any interpretation.
   A real deterministic test failure shall always force rework, independent of
   any interpretation. Failure modes shall be connected with test coverage.

   Source: ZIEL_020, ZIEL_038 (§4, §10)

.. sysreq:: Diagnostic evidence authority limits
   :id: SYS_REQ_021
   :status: draft
   :realizes: ZIEL_021

   Diagnostic Evidence is Evidence, not Authority. It shall never replace,
   override, bypass, or synthesize formal decision-authority — including
   technical admissibility, human selection, approval, verification result,
   final approval, or publish approval.

   Source: ZIEL_021 (§4)

.. sysreq:: Delivery separation from development
   :id: SYS_REQ_022
   :status: draft
   :realizes: ZIEL_022

   Delivery shall be its own engineering step and not a side effect of
   development.

   Source: ZIEL_022 (§4)

.. sysreq:: Bounded engineering behavior
   :id: SYS_REQ_023
   :status: draft
   :realizes: ZIEL_036

   ADC shall contain no unbounded engineering loops. Budgets shall exist for
   controlled operations including operation, phase, and run time limits,
   maximum attempts, maximum rework cycles, maximum state revisits, and provider
   budgets. A workflow shall not pend endlessly between the same states.

   Source: ZIEL_036 (§9)

.. sysreq:: Proven executability (fail-closed)
   :id: SYS_REQ_024
   :status: draft
   :realizes: ZIEL_039

   Before any mutating execution, ADC shall be able to prove that execution is
   actually possible — including a responsible controlled execution capability, a
   matching structured input, a registered capability, a correct target scope,
   operation permissibility, required approval, and the ability to verify the
   result afterward. The system shall operate fail-closed: unproven executability
   is non-executability.

   Source: ZIEL_039 (§11)

.. sysreq:: Artifact provenance and identity
   :id: SYS_REQ_025
   :status: draft
   :realizes: ZIEL_040

   For every important artifact, the following shall be answerable: Who creates
   it? Who may modify it? Where is it persisted? Who consumes it? Which
   authority applies? Which evidence proves its state? Which contract version
   applies?

   Source: ZIEL_040 (§12)

.. sysreq:: Diagnostic trace
   :id: SYS_REQ_026
   :status: draft
   :realizes: ZIEL_042

   ADC shall maintain a technical timeline of its run (Diagnostic Trace):
   which processing phase was started, which structured inputs were present,
   which system part processed them, which provider or model was used where
   known, which structured result was produced, which approval boundary was
   reached, which error occurred, which evidence is present, and where the
   workflow ended or was blocked. This trace shall not be a chain-of-thought
   store and shall contain no internal model thoughts, secrets, tokens,
   credential dumps, or uncontrolled executable commands.

   Source: ZIEL_042 (§12)

.. sysreq:: Audit and diagnosis traceability
   :id: SYS_REQ_027
   :status: draft
   :realizes: ZIEL_043

   ADC shall make relevant decisions and transformations traceable. It shall be
   possible to determine the triggering input or underlying evidence for a
   relevant result. It shall be possible to identify the responsible processing
   step or decision context sufficiently for audit and diagnosis.
   Failure-relevant information shall not silently disappear across processing
   boundaries.

   Source: ZIEL_043 (§12)

.. sysreq:: Interruption recovery (fail-closed)
   :id: SYS_REQ_028
   :status: draft
   :realizes: ZIEL_049, ZIEL_050

   If a run is interrupted during or after a mutation, a later run shall detect
   the unsafe or partial state, correlate the current target state with
   captured provenance, not silently reapply the same change, not silently treat
   the change as successful, and either go fail-closed or enter a controlled
   reconciliation path. Successfully completed steps may be reused on known
   success. Changed content shall force new generation/approval instead of
   silent reuse. Missing capabilities or tools at runtime shall be transferable
   into a bounded, approval-bound recovery without reopening the engineering
   decision and without unbounded repetition. After recovery, previously planned
   verification shall be re-executed.

   Source: ZIEL_049, ZIEL_050 (§14)

.. sysreq:: Knowledge separation and FMEA
   :id: SYS_REQ_029
   :status: draft
   :realizes: ZIEL_052, ZIEL_053

   ADC shall maintain a living engineering FMEA for each project, derived from
   requirements, architecture, technologies, toolchains, hardware, operating
   environment, past errors, tests, and real-system evidence, supplemented by a
   central reusable failure mode library. ADC shall keep different knowledge
   types separate: Knowledge (current valid project/system contract), Evidence
   (facts from the current run), Learning Memory (accepted insights from past
   errors and improvements), Analytic Reasoning (flexible analysis, synthesis,
   and proposal formation), and Deterministic Contracts (hard, non-negotiable
   rules). FMEA is part of the engineering learning system, not a static
   document.

   Source: ZIEL_052, ZIEL_053 (§15)

.. sysreq:: Cross-cutting supervisory capability
   :id: SYS_REQ_030
   :status: draft
   :realizes: ZIEL_055

   ADC shall possess a cross-cutting supervision and quality capability
   observing the entire run — timing, loop/retry behavior, evidence quality,
   project-related FMEA — starting read-only, initially recognizing rather than
   automatically repairing, later with limited capability to warn, block, or
   stop. This capability shall never autonomously execute destructive actions
   or alternative fixes.

   Source: ZIEL_055 (§15)

.. sysreq:: Outcome dependencies
   :id: SYS_REQ_031
   :status: draft
   :realizes: ZIEL_056

   ADC shall satisfy the following outcome dependencies: understand the project
   before making significant technical decisions; sufficiently justify technical
   decisions before mutations depending on them; obtain required approval before
   executing mutating actions requiring approval; technically verify results
   before presenting them as successfully completed; not present unverified or
   unapproved work as accepted final result.

   Source: ZIEL_056 (§16)