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

   S3.3 shall enforce the execution-surface contract of ARC_REQ_009 at the final child-process boundary. A terminal emulator may additionally receive narrowly necessary desktop/session variables to open and function. The wrapped installation command shall receive exactly the controlled child environment supplied by Controlled Execution for the approved ExecutionRequest. Ambient ADC or terminal-server variables excluded by that policy shall not reappear in the command environment. Environment separation shall preserve the authorized target and cwd, argv fidelity, exactly one command launch per authorized invocation, real exit status, and the prohibition on hidden installation fallback.

   Source: ARC_012 (S3.3), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3B/S3.3

.. subreq:: S3.3 shall route every classified software installation through a visible interactive terminal
   :id: SUB_REQ_032
   :status: draft
   :derived_from: ARC_REQ_025, SUB_REQ_010

   S3.3 shall classify which controlled operations are a software
   installation using one central, deterministic, structured criterion
   (never inferred from command text/argv), and shall route every
   operation so classified through a dedicated visible, interactive
   terminal execution surface, ecosystem-neutral by construction (not
   specific to any one package manager or toolchain) and never scattered
   across individual installer adapters. Non-installation controlled
   operations (verification, test, build, compile, configure) shall
   remain unaffected and continue to execute exactly as before. If no
   supported visible interactive terminal provider can be opened, S3.3
   shall fail closed with a structured cause
   (``INTERACTIVE_TERMINAL_UNAVAILABLE``) rather than falling back to a
   hidden subprocess; there shall be no such fallback for any classified
   installation. S3.3 shall wait for the terminal-hosted command to
   actually complete before continuing the setup lifecycle, and shall
   propagate its real exit result: a non-zero exit remains a failure, and
   a cancelled or closed terminal shall never be reported as success.
   S3.3 shall never receive, store, pipe, cache, log, serialize, or
   persist a sudo password in any form; interactive authentication
   belongs exclusively to the terminal/sudo interaction.

   The visible-terminal path shall apply SUB_REQ_010 at the wrapped command boundary, including separation of desktop/session environment from the controlled child environment.

   Source: ARC_REQ_025, CLAUDE-ADC-VISIBLE-TERMINAL-FOR-SOFTWARE-INSTALLATION-001

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
   conventions and the user's chosen technology. An empty development change
   set shall fail. S4.1 has no no-op authority.

   Source: ARC_016 (S4.1), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3C/S4.1

.. subreq:: S4.1 shall bind generated source to the intended target environment
   :id: SUB_REQ_041
   :status: draft
   :derived_from: ARC_REQ_027

   Before generating source, S4.1 shall establish relevant properties of the
   intended target environment, including installed tool versions or available
   capabilities where they affect compatibility, and provide them as generator
   context. Generated source shall be compatible with that environment. If
   compatibility cannot be reliably established, it shall remain explicitly
   unknown and shall not be represented as confirmed. Project conventions and
   the user's technology choice take precedence; ADC shall not change
   technology solely from its own preference. This obligation shall not prefer
   a language, toolchain, platform, or implementation.

   Source: ARC_REQ_027, ZIEL_003, ZIEL_010

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
   requirements and the present toolchain. Toolchain-specific logic shall
   reside exclusively in toolchain adapters.

   Source: ARC_021 (S5.1), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3D/S5.1

.. subreq:: S5 shall verify generated source in its intended target environment
   :id: SUB_REQ_042
   :status: draft
   :derived_from: ARC_REQ_028

   S5 shall bind verification execution for generated source to the same
   intended target environment established before generation. A host or
   default environment that differs from the intended target shall not be used
   as evidence of target compatibility. If the intended target cannot be
   reliably identified or used, compatibility shall remain unconfirmed.

   Source: ARC_REQ_028, SYS_REQ_032

.. subreq:: S5.2 shall execute verification through registered runners
   :id: SUB_REQ_018
   :status: draft
   :derived_from: ARC_REQ_016

   S5.2 shall execute registered controlled verification runners
   deterministically, preserving per-step result, status, return code,
   timeout, diagnostics, and runner identity.

   Source: ARC_022 (S5.2), ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3D/S5.2

.. subreq:: S5.2 shall preserve target-workspace integrity during verification
   :id: SUB_REQ_031
   :status: draft
   :derived_from: ARC_REQ_024

   S5.2 shall preserve target-workspace integrity while executing a
   controlled verification runner. Filesystem side effects produced
   merely as verification side effects (build/tool caches, generated
   configuration, metadata, and similar incidental artifacts) shall not
   appear as new, modified, or removed paths in the target project. A
   runner reporting a successful outcome while the target project was
   nonetheless left with an unaccounted mutation shall not be reported
   as a clean verification result; S5.2 shall fail closed and attribute
   the violation at its own boundary rather than deferring detection to
   a later subsystem. Pre-existing target state unrelated to the
   current run shall never be treated as a violation, deleted, or
   otherwise altered by this check.

   Source: ARC_REQ_024, ADC_Architektur_Ausfuehrliche_Beschreibung.txt §3D/S5.2

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

.. subreq:: Timeout scopes and actual request handover
   :id: SUB_REQ_033
   :status: approved
   :derived_from: ARC_033, SYS_REQ_023, SYS_REQ_025, SYS_REQ_026, SYS_REQ_027

   Each timeout shall identify attempt, contributor invocation, phase, or Council scope. Only a nonterminal attempt timeout may permit retry within remaining budgets. After terminal closure, no new actual request handover shall occur in the closed scope. Handover begins when request-specific data first leave retractable local preparation for a provider-directed transport whose onward transmission ADC can no longer reliably prevent; this includes SDK, transport, and operating-system buffers. Each supported integration shall document and expose this observable boundary. Admission, start claims, complete() entry, connection setup, or a check before a later send alone shall not establish compliance. Automatic SDK or transport retries and new transfers after connection failure shall count as separate handovers, obey closure, and consume the request budget. Continuing the transfer of an already handed-over request is not a new handover.

   Acceptance: Delay work on both sides of the documented boundary and race closure with handover. No handover shall begin after closure, including buffered and automatic retries. A timeout in one scope shall not close unrelated open scopes.

   Source: ADC_Council_Lifecycle_Anforderungskatalog.txt CL-F01; explicit user adoption CODEX-ADC-COUNCIL-REQUIREMENTS-ADOPTION-026.

.. subreq:: Immutable Council completion and late diagnostic additions
   :id: SUB_REQ_034
   :status: approved
   :derived_from: ARC_033, SYS_REQ_023, SYS_REQ_025, SYS_REQ_026, SYS_REQ_027

   The final snapshot shall preserve result identity, accepted contributions, variants, recommendation, complete/degraded status, and decision-relevant errors. Late success or failure shall not rewrite it or trigger further work in the closed scope. New late facts may be appended as identified diagnostic additions with invocation reference, event time, and receipt time, without overwriting the original completion cause. Handover and confirmed provider acceptance shall be distinct. Unknown acceptance or remote termination shall remain explicitly unknown. Local completion shall not imply termination of remote processing, transfer, or costs.

   Acceptance: Inject late success and failure after timeout and compare final snapshots. No accepted contribution, verdict, original error, or follow-up request shall change. Identified diagnostic additions remain permitted; an unconfirmed remote state shall never be reported as confirmed.

   Source: ADC_Council_Lifecycle_Anforderungskatalog.txt CL-F02; explicit user adoption CODEX-ADC-COUNCIL-REQUIREMENTS-ADOPTION-026.

.. subreq:: Independent critical diagnosis and monotone current state
   :id: SUB_REQ_035
   :status: approved
   :derived_from: ARC_033, SYS_REQ_023, SYS_REQ_025, SYS_REQ_026, SYS_REQ_027

   Critical diagnosis shall identify run, invocation and contributor, completion cause, degradation, handover status, and resource and storage failures. Retrieval shall be independent of callbacks. A terminal current state shall never become active again because of late, duplicated, or overtaking messages. Redundant late progress may be coalesced and counted; genuinely new information may remain in marked history. The last historical entry need not be terminal. Diagnosis shall retain the existing secret-redaction and non-authority constraints.

   Acceptance: Use the real diagnostic receiver and public state query with delayed, duplicated, and overtaking progress. The terminal current state and retrievable critical causes shall remain correct throughout the promised retrieval period.

   Source: ADC_Council_Lifecycle_Anforderungskatalog.txt CL-F03; explicit user adoption CODEX-ADC-COUNCIL-REQUIREMENTS-ADOPTION-026.

.. subreq:: Bounded storage reservation and distinct completion states
   :id: SUB_REQ_036
   :status: approved
   :derived_from: ARC_033, SYS_REQ_023, SYS_REQ_025, SYS_REQ_026, SYS_REQ_027

   Functional completion, durable-storage state, and notification state shall be separately observable. Durability shall require confirmed persistence, not merely a local write buffer. Before admission, ADC shall reserve capacity for structurally bounded critical mandatory data, including a bounded failure record. Reservation shall not assume exact prediction of later diagnostic size. Unexpected overflow shall use a visible size/resource failure path retaining available mandatory facts and identifying what could not be retained; critical information shall not be silently truncated and complete auditability shall not be falsely claimed. No further provider handover shall begin once mandatory recording capacity cannot be maintained. Blocked or failed storage shall not extend the public deadline: ADC shall return the functional result with explicitly unconfirmed durability and guarantee bounded volatile retrieval while the service remains alive. Late confirmed persistence may update durability, not the functional snapshot. Restart retrieval shall be promised only for confirmed persistence. Exhausted storage, retention, or volatile retrieval capacity shall reject new admissions before provider handover; existing retrieval or retention promises shall not be silently shortened. Service-held snapshots, references, copies, pending writes, and failure records shall all count against storage limits.

   Acceptance: Block writes, inject storage errors, exhaust reservations, and exceed the expected diagnostic size. Completion shall remain bounded with truthful separate states, a visible overflow record, no silent loss claim, and bounded memory. Protected prior data shall remain available; unconfirmed data shall carry no restart guarantee.

   Source: ADC_Council_Lifecycle_Anforderungskatalog.txt CL-F04; explicit user adoption CODEX-ADC-COUNCIL-REQUIREMENTS-ADOPTION-026.

.. subreq:: Bounded best-effort notification
   :id: SUB_REQ_037
   :status: approved
   :derived_from: ARC_033, SYS_REQ_023, SYS_REQ_025, SYS_REQ_026, SYS_REQ_027

   Callbacks shall be best effort and shall neither determine provider success nor extend public completion. Callback execution shall not overlap within one subscription. Progress may be coalesced; critical completion data shall remain independently retrievable. Omitted, failed, and still-unconfirmed deliveries shall be separately counted. Queue admission shall not be reported as delivery. Blocked prior deliveries shall continue to consume delivery capacity.

   Acceptance: Permanently block each notification type and saturate delivery capacity. Functional completion and its deadline shall remain unchanged, critical diagnosis retrievable, delivery bounds respected, and delivery counters truthful.

   Source: ADC_Council_Lifecycle_Anforderungskatalog.txt CL-F05; explicit user adoption CODEX-ADC-COUNCIL-REQUIREMENTS-ADOPTION-026.

.. subreq:: Concurrent Council isolation and overload
   :id: SUB_REQ_038
   :status: approved
   :derived_from: ARC_033, SYS_REQ_023, SYS_REQ_025, SYS_REQ_026, SYS_REQ_027

   Service-wide capacity shall be configurable independently of contributor count. Supported concurrent invocations shall isolate identity, results, and invocation budgets. Active, waiting, and quarantined work, notifications, and retained completion data shall count against finite resource limits. Overload shall produce a distinguishable resource failure. A missing contribution may be classified as degradation only when functional continuation is admissible. An overload rejection shall start no provider work and shall not itself permanently block healthy later invocations. Reducing previously supported parallelism requires a separate product decision; this adoption imposes no single-Council limit.

   Acceptance: Run concurrent and repeated invocations under permanent blockage. No identities, results, or budgets shall mix and no resource limit shall be exceeded. An admission rejection shall cause zero provider handovers. A healthy new invocation shall work after actual resource release.

   Source: ADC_Council_Lifecycle_Anforderungskatalog.txt CL-F06; explicit user adoption CODEX-ADC-COUNCIL-REQUIREMENTS-ADOPTION-026.

.. subreq:: End-to-end Council deadline accounting
   :id: SUB_REQ_039
   :status: approved
   :derived_from: ARC_033, SYS_REQ_023, SYS_REQ_025, SYS_REQ_026, SYS_REQ_027

   A finite public deadline shall begin at entry to the public Council operation before validation and admission and include preparation, all phases, retries, repair, and finalization. Retries shall not reset subordinate deadlines. Supported operations shall declare their finite time and resource profile before admission; concrete values require separate profile approval. No work may treat measurement tolerance as additional execution budget.

   Acceptance: Include pre-provider and persistence delays in elapsed time. An outcome completed after its applicable deadline shall not be accepted because the coordinator runs late. A timely outcome shall not fail solely because notification is late. Hanging providers and receivers shall not cause an unbounded public return.

   Source: ADC_Council_Lifecycle_Anforderungskatalog.txt CL-F07; explicit user adoption CODEX-ADC-COUNCIL-REQUIREMENTS-ADOPTION-026.

.. subreq:: Counted quarantine and bounded process exit
   :id: SUB_REQ_040
   :status: approved
   :derived_from: ARC_033, SYS_REQ_023, SYS_REQ_025, SYS_REQ_026, SYS_REQ_027

   Capacity-bounded quarantine is permitted without a guaranteed individual termination deadline. Actually terminated work shall be distinguished from still-running isolated work. Quarantined work shall fully consume its resource limits until termination is confirmed; deletion from bookkeeping shall not release capacity. Council work shall not indefinitely prevent public completion, service shutdown, or exit of the owning process. These outcomes shall not imply termination of remote processing or separately continuing local work. Uncertain remote requests shall not be automatically resubmitted after restart.

   Acceptance: Keep a provider or receiver permanently blocked: it shall remain counted and may exhaust capacity. An isolated owner process shall exit within its separately approved shutdown bound. Still-running work shall never be recorded as terminated, and restart shall cause no automatic resubmission.

   Source: ADC_Council_Lifecycle_Anforderungskatalog.txt CL-F08; explicit user adoption CODEX-ADC-COUNCIL-REQUIREMENTS-ADOPTION-026.
