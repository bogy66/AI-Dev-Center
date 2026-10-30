ADC Subsystem Requirements
==========================

Requirements allocated to ADC subsystems and sub-sub-system areas.
Source: ADC_Architektur_Ausfuehrliche_Beschreibung.txt

S1 Requirement Intelligence
---------------------------

.. subreq:: S1 shall identify and structure requirements
   :id: SUB_REQ_001
   :status: draft
   :derived_from: ARC_002

   S1 shall analyze user requests read-only, inspect the project,
   identify requirements, structure them into mandatory and optional,
   recognize conflicts and uncertainties, and connect requirements with
   evidence. S1 shall not select technical solutions or execute setup.

   Source: ARC_002 (S1), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §1/S1

.. subreq:: S1 shall formulate requirements testably
   :id: SUB_REQ_002
   :status: draft
   :derived_from: ARC_002

   S1 shall formulate requirements so they are testable for later
   verification stages, with stable identities, activation provenance,
   and evidence linkage.

   Source: ARC_002 (S1), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §1/S1

S2 Engineering Decision
-----------------------

.. subreq:: S2.1 shall generate independent alternatives
   :id: SUB_REQ_003
   :status: draft
   :derived_from: ARC_REQ_003

   S2.1 shall generate multiple independent, technically sound
   engineering alternatives and collect cross-review evidence.
   S2.1 shall not select a recommendation or decide admissibility.

   Source: ARC_004 (S2.1), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3A/S2.1

.. subreq:: S2.2 shall synthesize and recommend
   :id: SUB_REQ_004
   :status: draft
   :derived_from: ARC_REQ_003

   S2.2 shall synthesize cross-reviewed proposals and produce a
   technically justified recommendation including one bounded
   targeted repair attempt on structurally rejected synthesis.
   S2.2 shall not exercise independent admissibility policy.

   Source: ARC_005 (S2.2), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3A/S2.2

.. subreq:: S2.3 shall classify technical admissibility
   :id: SUB_REQ_005
   :status: draft
   :derived_from: ARC_REQ_004

   S2.3 shall be the sole technical admissibility authority within S2.
   It shall classify variants as admissible or inadmissible with exact
   deterministic reasons and preserve multiple admissible alternatives.
   S2.3 shall not select a preferred solution or modify candidates.

   Source: ARC_006 (S2.3), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3A/S2.3

.. subreq:: S2.4 shall represent human decision authority
   :id: SUB_REQ_006
   :status: draft
   :derived_from: ARC_007

   S2.4 shall present technically evaluated candidates to the human and
   allow accepting a recommendation, selecting another admissible
   alternative, rejecting, deferring, or requesting rework. S2.4 shall
   not make an inadmissible candidate admissible and shall not silently
   substitute the desired candidate.

   Source: ARC_007 (S2.4), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3A/S2.4

.. subreq:: S2.5 shall produce final S2 decision and own S2→S3 boundary
   :id: SUB_REQ_007
   :status: draft
   :derived_from: ARC_REQ_006

   S2.5 shall produce the final EngineeringDecision artifact preserving
   exact candidate identity, selection authority, and validation
   provenance. S2.5 shall own the S2→S3 boundary. S2.5 shall not invent
   a selection, choose a winner, or repair a candidate.

   Source: ARC_008 (S2.5), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3A/S2.5

S3 Environment & Setup
----------------------

.. subreq:: S3.1 shall plan setup actions from EngineeringDecision
   :id: SUB_REQ_008
   :status: draft
   :derived_from: ARC_REQ_007

   S3.1 shall materialize the EngineeringDecision into a structured
   SetupPlan with classified SetupSteps. S3.1 shall not execute
   actions, grant approvals, or reopen the S2 selection.

   Source: ARC_010 (S3.1), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3B/S3.1

.. subreq:: S3.2 shall provide sole human setup approval authority
   :id: SUB_REQ_009
   :status: draft
   :derived_from: ARC_REQ_008

   S3.2 shall be the sole human approval boundary for mutating setup
   actions, structurally separated from planning and execution.
   S3.2 shall bind approval to exact plan content and shall not plan
   or execute actions.

   Source: ARC_011 (S3.2), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3B/S3.2

.. subreq:: S3.3 shall execute approved setup controllably
   :id: SUB_REQ_010
   :status: draft
   :derived_from: ARC_REQ_009

   S3.3 shall execute approved setup mutations through a controlled
   execution boundary requiring an approved plan, executable step,
   matching registered executor, and replay/idempotency protection.
   Execution shall not proceed on non-approved or changed content.

   Source: ARC_012 (S3.3), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3B/S3.3

.. subreq:: S3.4 shall manage execution identity and idempotency
   :id: SUB_REQ_011
   :status: draft
   :derived_from: ARC_013

   S3.4 shall persist execution identity and state per setup step with
   content-fingerprint binding. Known-success shall enable reuse;
   unknown or recovery state shall fail closed; changed content shall
   force new generation and approval. S3.4 concerns only setup-step
   execution identity.

   Source: ARC_013 (S3.4), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3B/S3.4

.. subreq:: S3.5 shall provide bounded missing-toolchain recovery
   :id: SUB_REQ_012
   :status: draft
   :derived_from: ARC_014

   S3.5 shall convert TOOL_UNAVAILABLE evidence into a bounded,
   approval-bound recovery reusing S3.1/S3.2/S3.3 authorities.
   Recovery shall be exactly bounded, shall not reopen engineering
   selection, and shall re-execute previously planned verification
   after completion.

   Source: ARC_014 (S3.5), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3B/S3.5

S4 Development & Change
-----------------------

.. subreq:: S4.1 shall generate structured development changes
   :id: SUB_REQ_013
   :status: draft
   :derived_from: ARC_REQ_012

   S4.1 shall generate structured developer changes respecting project
   conventions. An empty development change set shall fail. S4.1 has
   no no-op authority.

   Source: ARC_016 (S4.1), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3C/S4.1

.. subreq:: S4.2 shall generate test changes with explicit no-op contract
   :id: SUB_REQ_014
   :status: draft
   :derived_from: ARC_017

   S4.2 shall generate structured test changes with an explicit no-op
   contract. A valid no-op requires an explicit declaration; an empty
   changes array alone is not a no-op.

   Source: ARC_017 (S4.2), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3C/S4.2

.. subreq:: S4.3 shall apply changes within authorized scope
   :id: SUB_REQ_015
   :status: draft
   :derived_from: ARC_018

   S4.3 shall apply structured engineering changes via a controlled
   mechanism onto authorized targets within defined scope, classifying
   actual apply attempts. S4.3 shall fail closed on partial or
   skipped application and prevent mutation outside the project scope.

   Source: ARC_018 (S4.3), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3C/S4.3

.. subreq:: S4.4 shall capture change provenance
   :id: SUB_REQ_016
   :status: draft
   :derived_from: ARC_REQ_014

   S4.4 shall capture baseline-before and event-after change provenance
   with run and phase attribution, providing traceable change evidence.

   Source: ARC_019 (S4.4), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3C/S4.4

S5 Quality & Verification
-------------------------

.. subreq:: S5.1 shall derive verification plan from project requirements
   :id: SUB_REQ_017
   :status: draft
   :derived_from: ARC_021

   S5.1 shall derive a structured verification plan from project
   requirements and the present toolchain. Toolchain-specific logic
   shall reside exclusively in toolchain adapters.

   Source: ARC_021 (S5.1), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3D/S5.1

.. subreq:: S5.2 shall execute verification through registered runners
   :id: SUB_REQ_018
   :status: draft
   :derived_from: ARC_REQ_016

   S5.2 shall execute registered controlled verification runners
   deterministically, preserving per-step result, status, return code,
   timeout, diagnostics, and runner identity.

   Source: ARC_022 (S5.2), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3D/S5.2

.. subreq:: S5.3 shall aggregate verification evidence per step
   :id: SUB_REQ_019
   :status: draft
   :derived_from: ARC_023

   S5.3 shall aggregate verification results per step with failure
   evidence structurally preserved. Multiple failures shall not be
   collapsed into misleading generic success.

   Source: ARC_023 (S5.3), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3D/S5.3

.. subreq:: S5.4 shall format diagnostic evidence deterministically
   :id: SUB_REQ_020
   :status: draft
   :derived_from: ARC_024

   S5.4 shall format already-produced verification evidence
   deterministically. S5.4 shall have no diagnostic authority and
   shall not decide acceptance/rework or rewrite failed evidence.

   Source: ARC_024 (S5.4), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3D/S5.4

.. subreq:: S5.5 shall interpret diagnostic evidence without overriding
   :id: SUB_REQ_021
   :status: draft
   :derived_from: ARC_025

   S5.5 shall interpret diagnostic evidence. S5.5 shall never
   reinterpret a real deterministic test failure as success.

   Source: ARC_025 (S5.5), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3D/S5.5

.. subreq:: S5.6 shall enforce deterministic failure policy
   :id: SUB_REQ_022
   :status: draft
   :derived_from: ARC_026

   S5.6 shall enforce the deterministic policy that a real
   verification or test failure forces rework regardless of any
   diagnosis interpretation.

   Source: ARC_026 (S5.6), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3D/S5.6

.. subreq:: S5.7 shall orchestrate exactly one bounded rework cycle
   :id: SUB_REQ_023
   :status: draft
   :derived_from: ARC_REQ_021

   S5.7 shall orchestrate exactly one bounded controlled rework cycle
   triggered by the S5 verification verdict. No unbounded rework loops
   shall occur.

   Source: ARC_027 (S5.7), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3D/S5.7

S6 Delivery & Outcome
---------------------

.. subreq:: S6 shall deliver only verified and approved outcomes
   :id: SUB_REQ_024
   :status: draft
   :derived_from: ARC_028

   S6 shall transfer only technically verified and human-approved
   results into final state. S6 shall protect pre-existing target
   state, prevent silent destructive repair, and treat publish as a
   separate explicit action with its own approval boundary.

   Source: ARC_028 (S6), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §1/S6

Cross-cutting
-------------

.. subreq:: Subsystem boundaries shall enforce sequencing
   :id: SUB_REQ_025
   :status: draft
   :derived_from: ARC_REQ_023

   Cross-subsystem boundaries shall enforce that each subsystem starts
   only after required upstream responsibilities are fulfilled. A
   single bounded rework cycle and bounded missing-toolchain recovery
   are the only allowed backward transitions.

   Source: ARC_029, ADC_Architektur_Ausfuehrliche_Beschreibung.txt §4

.. subreq:: Architecture interfaces shall use technology-neutral vocabulary
   :id: SUB_REQ_026
   :status: draft
   :derived_from: ARC_030

   Central orchestration shall use only technology-neutral terms.
   Stack-specific logic shall reside in adapters and providers.

   Source: ARC_030, ADC_Architektur_Ausfuehrliche_Beschreibung.txt §2, §5

.. subreq:: Architecture transitions shall expose Producer-Artifact-Consumer
   :id: SUB_REQ_027
   :status: draft
   :derived_from: ARC_031

   Every important architectural transition shall have an explicit
   Producer→Artifact→Consumer chain with answerable identity,
   authority, provenance, and contract version per artifact.

   Source: ARC_031, ADC_Architektur_Ausfuehrliche_Beschreibung.txt §8

.. subreq:: Diagnostic trace shall not hold decision authority
   :id: SUB_REQ_028
   :status: draft
   :derived_from: ARC_032

   The diagnostic trace across all subsystems shall not substitute
   for any formal decision authority. It shall not replace
   admissibility evaluation, human selection, approval, or
   verification verdicts.

   Source: ARC_032, ADC_Architektur_Ausfuehrliche_Beschreibung.txt §9

.. subreq:: Executability proof shall precede every mutation
   :id: SUB_REQ_029
   :status: draft
   :derived_from: ARC_034

   Before any mutating execution, the executing subsystem shall
   establish proof of: defined setup effect, registered executor,
   matching input schema, correct target scope, required approval, and
   verifiability. Readiness shall be modeled in distinct states and the
   system shall fail closed on unproven executability.

   Source: ARC_034, ADC_Architektur_Ausfuehrliche_Beschreibung.txt §7

.. subreq:: Engineering alternatives process shall be structured
   :id: SUB_REQ_030
   :status: draft
   :derived_from: ARC_033

   The alternative generation and evaluation process shall use a
   structured multi-perspective mechanism producing cross-reviewed
   alternatives with traced, technically justified recommendations.

   Source: ARC_033, ADC_Architektur_Ausfuehrliche_Beschreibung.txt §6