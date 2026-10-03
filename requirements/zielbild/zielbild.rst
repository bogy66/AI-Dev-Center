ADC Zielbild – Traceability Objects
===================================

Real Zielbild goals derived from the normative Zielbild text.
Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt

.. ziel:: ADC as integrated engineering platform
   :id: ZIEL_001
   :status: draft

   ADC shall develop into an integrated engineering platform for software,
   firmware, and hardware.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §1 Purpose/Mission

.. ziel:: Complete controlled engineering process
   :id: ZIEL_002
   :status: draft

   ADC shall support a complete, traceable, and controlled engineering
   process: understand project and requirements, make technically
   founded decisions, controlled materialization of chosen solution,
   controlled change implementation, real mechanical verification,
   controlled delivery, and durable learning from collected evidence.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §1 Purpose/Mission

.. ziel:: Support existing and new projects
   :id: ZIEL_003
   :status: draft

   ADC shall support both existing and greenfield projects, with
   priority for existing project structure, conventions, and
   toolchains (Existing Project First).

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §2 Scope, §6 Existing Project First

.. ziel:: Heterogeneous multi-toolchain project understanding
   :id: ZIEL_004
   :status: draft

   ADC shall understand heterogeneous and multi-toolchain projects
   without artificially unifying them. A project may contain multiple
   independent technical areas simultaneously, each with its own
   languages, build systems, and test systems. ADC shall understand
   these areas separately while bringing them together in a common
   engineering context.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §2 Scope

.. ziel:: Long-term E/E engineering platform evolution
   :id: ZIEL_005
   :status: draft

   ADC shall evolve from a software development platform toward an
   integrated electrical/electronic engineering platform, covering the
   full path from requirement through system concept, schematic,
   simulation, component selection, PCB layout, compliance checks,
   manufacturing data, prototype, bring-up, firmware, validation, to
   documentation.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §2 Scope

.. ziel:: Read-only inspection and requirement identification
   :id: ZIEL_006
   :status: draft

   ADC shall be capable of understanding a user request, inspecting
   an existing project read-only, identifying and structuring
   requirements, distinguishing mandatory from optional requirements,
   and connecting requirements with evidence.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §3 Core Capabilities

.. ziel:: Multiple solution variants with criteria evaluation
   :id: ZIEL_007
   :status: draft

   ADC shall generate multiple technically sound engineering solution
   variants and evaluate them against real engineering criteria,
   including requirement fulfillment, project fit, necessary changes,
   reuse of existing capabilities, risks, reproducibility,
   materializability, controlled executability, real verifiability,
   cost/complexity, and introduced dependencies.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §3 Core Capabilities, §8 Engineering Quality

.. ziel:: Traceable recommendation with alternatives
   :id: ZIEL_008
   :status: draft

   ADC shall produce a technically justified recommendation and
   present it to the user in a traceable manner together with the
   alternatives, including the rationale for each alternative,
   advantages and disadvantages, additional effort, additional risks,
   and verification implications.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §3 Core Capabilities, §5 Human Authority

.. ziel:: Controlled environment preparation
   :id: ZIEL_009
   :status: draft

   ADC shall transfer the chosen engineering solution into a real,
   usable environment in a controlled manner without reopening the
   already-made engineering selection.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §3 Core Capabilities, §4 System Guarantees

.. ziel:: Controlled technical change execution
   :id: ZIEL_010
   :status: draft

   ADC shall carry out the actual technical change on the project in a
   controlled manner, within authorized scope, with full change
   provenance and protection of pre-existing target state.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §3 Core Capabilities, §9 Controlled Change

.. ziel:: Real mechanical verification with evidence separation
   :id: ZIEL_011
   :status: draft

   ADC shall mechanically and actually verify whether the technical
   solution and changes truly function, using project-specific build
   and test systems, with clear separation of unit, component, system,
   and real-system evidence. Real test results are authoritative
   evidence. Toolchain availability shall be detected and verification
   dependencies mapped.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §3 Core Capabilities, §10 Verification

.. ziel:: Controlled delivery of verified outcome
   :id: ZIEL_012
   :status: draft

   ADC shall deliver a verified and approved result in a controlled
   manner. Delivery shall not represent unverified or unapproved work
   as an accepted final result.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §3 Core Capabilities, §13 Delivery

.. ziel:: Durable learning from accepted evidence
   :id: ZIEL_013
   :status: draft

   ADC shall durably learn from accepted evidence, including from
   failed outcomes. Learning shall not be artificially coupled to
   successful delivery.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §3 Core Capabilities, §15 Learning/FMEA

.. ziel:: Solution variability without artificial uniformity
   :id: ZIEL_014
   :status: draft

   ADC shall not attempt to enforce the same solution class for
   identical input. Different project-specific engineering solutions
   may all be correct. Variability is permitted.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §3 Core Capabilities, §8 Engineering Quality

.. ziel:: Solution quality gates
   :id: ZIEL_015
   :status: draft

   Every chosen solution shall fulfill binding requirements, violate
   no constraints, be technically materializable, possess an
   appropriate controlled execution capability, have a defined
   verification strategy, be secured by deterministic tests, and be
   presentable to the human in a traceable manner before mutating
   execution.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §3 Core Capabilities

.. ziel:: Authority separation — understanding vs solution selection
   :id: ZIEL_016
   :status: draft

   Understanding requirements shall itself neither select a technical
   solution nor execute any setup action.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §4 System Guarantees

.. ziel:: Authority separation — decision vs mutation
   :id: ZIEL_017
   :status: draft

   Making an engineering decision shall itself neither execute an
   installation nor mutate any environment.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §4 System Guarantees

.. ziel:: Authority separation — preparation vs reopening selection
   :id: ZIEL_018
   :status: draft

   Preparing the environment shall not reopen the already-made
   engineering selection.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §4 System Guarantees

.. ziel:: Authority separation — recommendation vs execution authorization
   :id: ZIEL_019
   :status: draft

   A technical recommendation is not an automatic execution
   authorization. Human selection or approval shall NEVER make a
   technically inadmissible solution admissible.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §4 System Guarantees, §5 Human Authority

.. ziel:: Real verification dominates AI interpretation
   :id: ZIEL_020
   :status: draft

   A real verification result shall not be overridden by any AI
   interpretation. An AI shall not claim that something works when
   real verification shows the opposite. A real deterministic test
   failure shall always force rework, independent of any
   interpretation.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §4 System Guarantees, §10 Verification

.. ziel:: Diagnostic Evidence is not Authority
   :id: ZIEL_021
   :status: draft

   Diagnostic Evidence is Evidence, not Authority. It shall never
   replace, override, bypass, or synthesize formal
   decision-authority — including technical admissibility, human
   selection, approval, verification result, final approval, or
   publish approval.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §4 System Guarantees

.. ziel:: Delivery as separate step from development
   :id: ZIEL_022
   :status: draft

   Delivery shall be its own engineering step and not a side effect of
   development.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §4 System Guarantees

.. ziel:: Human as decisive authority at safety-critical boundaries
   :id: ZIEL_023
   :status: draft

   The human shall remain the decisive authority at mutating and
   safety-relevant boundaries. The user may accept a recommendation,
   select another presented admissible variant, request a change,
   reject planning, or request a new decision round.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §5 Human Authority

.. ziel:: Separation of recommendation and execution approval
   :id: ZIEL_024
   :status: draft

   A system recommendation ("I consider this the best technical
   variant") and human approval ("this concrete mutating action may be
   executed") shall be clearly separated. This separation is a core
   principle.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §5 Human Authority

.. ziel:: Existing Project First
   :id: ZIEL_025
   :status: draft

   Existing projects shall take priority over ADC preferences. ADC
   shall adapt to the project, not the reverse. When an existing
   project already has a build system, toolchain, tests, CI, project
   structure, or conventions, ADC shall recognize and use these first.
   ADC shall not impose its own directory, build, or test structure
   on foreign repositories.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §6 Existing Project First

.. ziel:: Technical reason required for toolchain changes
   :id: ZIEL_026
   :status: draft

   Changing to a different toolchain or environment shall require a
   technical reason. Permissible reasons include a requirement, a
   constraint, a missing capability, a security boundary,
   reproducible isolation, platform incompatibility, a user decision,
   or a demonstrated engineering advantage. "ADC fundamentally prefers
   technology X" alone is not permissible.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §6 Existing Project First

.. ziel:: Technology neutrality
   :id: ZIEL_027
   :status: draft

   ADC shall remain technology-open. Any concrete implementation
   technology may occur, but NONE shall dominate the central ADC
   system or become the hidden default for all projects. ADC shall not
   be centered implicitly or explicitly around a specific
   implementation technology. Concrete technologies exist exclusively
   as replaceable current implementation, project-specific choice, or
   explicitly non-normative example.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §7 Technology Neutrality

.. ziel:: Stack integrability without system rebuild
   :id: ZIEL_028
   :status: draft

   New technical stacks shall be integrable without fundamentally
   rebuilding ADC as a system. Various functional areas of ADC may be
   realized in arbitrary implementation technologies.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §7 Technology Neutrality

.. ziel:: Multiple solution variants without enforced single solution
   :id: ZIEL_029
   :status: draft

   ADC shall deliberately generate and evaluate multiple technically
   sound engineering solutions rather than enforcing a single
   predetermined solution.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §8 Engineering Quality

.. ziel:: No deterministic solver
   :id: ZIEL_030
   :status: draft

   ADC shall not be a deterministic solver that must always deliver
   the same solution for identical input. Different technically valid
   recommendations for the same starting situation are fundamentally
   permitted.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §8 Engineering Quality

.. ziel:: Solution diversity with early invalidity blocking
   :id: ZIEL_031
   :status: draft

   ADC shall enable solution diversity but block technical invalidity
   early. A variant becomes problematic only when it violates
   requirements, ignores constraints, is not materializable, lacks a
   controlled execution capability, lacks verification, bypasses
   security boundaries, creates unnecessary or unreasonable risks, or
   is presented as "executable" when ADC cannot actually execute it
   in a controlled manner.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §8 Engineering Quality

.. ziel:: Requirements as technical contract
   :id: ZIEL_032
   :status: draft

   Requirements shall not be mere system-generated text. They shall form the
   technical contract against which solutions are evaluated. A
   solution shall only be admissible if it fulfills the binding
   requirements for the concrete operation. Requirements shall possess
   evidence and be linkable with tests: Requirement → Contract →
   Verification → Evidence.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §8 Engineering Quality

.. ziel:: No unstructured or automatic system-generated mutations
   :id: ZIEL_033
   :status: draft

ADC shall not model changes and setup as a collection of
    unstructured, freely formulated operation representations. No
    freely formulated or unstructured reasoning or analysis result
    shall automatically become a mutating action. Every
    environment-altering or project-altering action shall semantically
    describe WHAT is to be changed and be implemented via a structured,
    controlled mechanism with an appropriate controlled execution
    capability.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §9 Controlled Change

.. ziel:: Controlled execution boundaries for all mutations
   :id: ZIEL_034
   :status: draft

   Every mutating execution shall run through controlled boundaries
   that check: which capability is claimed, which executing instance
   is responsible, which type of operation is present, in which
   authorized execution/target scope it is permitted, whether valid
   approval exists, whether the argument structure is permitted, and
   which operational limits apply. There shall be no general path
   through which a reasoning system can directly bring unstructured
   operations to execution.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §9 Controlled Change

.. ziel:: Creative analysis vs controlled mutation separation
   :id: ZIEL_035
   :status: draft

   Creative analysis and synthesis shall contribute exclusively to the
   preparation and justification of decisions, not to direct
   uncontrolled mutation. Actual changes to projects or environments
   shall only occur through controlled, checked, and approved
   channels.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §9 Controlled Change

.. ziel:: No unbounded engineering loops
   :id: ZIEL_036
   :status: draft

   ADC shall contain no unbounded engineering loops. Budgets shall
   exist for controlled operations, including operation, phase, and
   run time limits, maximum attempts, maximum rework cycles, maximum
   state revisits, and provider budgets. A workflow shall not pend
   endlessly between the same states.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §9 Controlled Change

.. ziel:: Multiple clearly separated verification levels
   :id: ZIEL_037
   :status: draft

   ADC shall have multiple clearly separated verification levels: from
   local, narrow checks of individual functions/contracts through
   checks of individual components against their technical invariants
   and checks of transitions between components to real-world
   integration verification with real toolchains, relevant external
   systems, and real components as necessary. Real integration
   verification is acceptance evidence, not the primary debugging tool.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §10 Verification

.. ziel:: Real verification as authoritative evidence
   :id: ZIEL_038
   :status: draft

   ADC shall treat real verification results as authoritative
   evidence. Failure modes shall be connected with test coverage. An
   AI interpretation of diagnostic evidence shall NEVER reinterpret a
   real deterministic test failure as success. A real failure shall
   always force rework, independent of interpretation.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §10 Verification

.. ziel:: Proven executability before mutating execution (fail-closed)
   :id: ZIEL_039
   :status: draft

   Before any mutating execution, ADC shall be able to prove that
   execution is actually possible — including a responsible controlled
   execution capability, a matching structured input, a registered
   capability, a correct project/target scope, the permissibility of
   the operation, the required approval, and the ability to verify the
   result afterward. The system shall operate fail-closed: unproven
   executability is non-executability.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §11 Safety/Fail-Closed

.. ziel:: Artifact identity and provenance
   :id: ZIEL_040
   :status: draft

   For every important artifact, the following questions shall be
   answerable: Who creates it? Who may modify it? Where is it
   persisted? Who consumes it? Which authority applies? Which evidence
   proves its state? Which contract version applies?

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §12 Traceability/Evidence

.. ziel:: Read-only project understanding with observation/decision separation
   :id: ZIEL_041
   :status: draft

   ADC shall understand existing projects deterministically and
   read-only, and shall distinguish observed reality (languages,
   frameworks, build/test systems, conventions, project areas) from
   deliberately established project decisions. Deliberate project
   decisions shall not be raw chat history and shall not themselves
   create approval authority. They shall be versionable (active,
   superseded, revoked). Observed reality, explicit decisions, and
   technical configuration shall be brought together without silently
   overwriting contradictory sources.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §12 Traceability/Evidence

.. ziel:: Diagnostic trace without internal thoughts or secrets
   :id: ZIEL_042
   :status: draft

   ADC shall maintain a technical timeline of its run (Diagnostic
   Trace): which phase was started, which structured inputs were
   present, which system part processed them, which provider/model
   was used (where known), which structured result was produced,
   which approval boundary was reached, which error occurred, which
   evidence is present, and where the workflow ended or was blocked.
   This trace shall not be a chain-of-thought store: it shall contain
   no internal model thoughts, no secrets, no tokens, no credential
   dumps, and no uncontrolled executable commands.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §12 Traceability/Evidence

.. ziel:: Decisions and transformations traceable for audit and diagnosis
   :id: ZIEL_043
   :status: draft

   ADC shall make relevant decisions and transformations traceable.
   It shall be possible to determine the triggering input or
   underlying evidence for a relevant result. It shall be possible to
   identify the responsible processing step or decision context
   sufficiently for audit and diagnosis. Failure-relevant information
   shall not silently disappear across processing boundaries.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §12 Traceability/Evidence

.. ziel:: Structured user presentation of recommendation and alternatives
   :id: ZIEL_044
   :status: draft

   The user shall not see only an opaque recommendation. ADC shall
   provide a structured presentation of the recommendation (variant
   name, short technical justification, fulfilled requirements,
   required environment, required changes, risks, verification
   strategy, expected setup steps, human approval points) as well as
   the alternatives (why they are also admissible, advantages and
   disadvantages, additional effort, additional risks, verification
   implications), so that the user can decide consciously.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §12 Traceability/Evidence

.. ziel:: Provenance-based delivery — no foreign state appropriation
   :id: ZIEL_045
   :status: draft

   ADC shall not appropriate foreign target state changes that do not
   belong to the current run. It shall prove per run: initial state,
   targets changed by ADC, belonging to the run. Only targets whose
   provenance is fully proven shall be transferred to final state.
   Pre-existing changes in the delivery target may remain as long as
   ADC does not modify them; if ADC additionally modifies an already
   modified target, this shall be detected.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §13 Delivery

.. ziel:: No destructive repair of pre-existing target state
   :id: ZIEL_046
   :status: draft

   ADC shall NOT automatically discard, overwrite, undo, or silently
   absorb pre-existing target state — this includes in particular any
   form of destructive state repair.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §13 Delivery

.. ziel:: Separate publish with own approval boundary
   :id: ZIEL_047
   :status: draft

   Where the delivery solution provides for a publish, publish shall
   be a separate explicit action after a local controlled delivery
   state and its own approval boundary.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §13 Delivery

.. ziel:: Version control optional and project-specific
   :id: ZIEL_048
   :status: draft

   Version control shall be optional and project-specific. ADC shall
   remain validly functional without a version control system or with
   a different delivery mechanism.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §13 Delivery

.. ziel:: Interruption detection and fail-closed on partial state
   :id: ZIEL_049
   :status: draft

   If a run is interrupted during or after a mutation, a later run
   shall detect the unsafe or partial state, correlate the current
   target state with captured provenance, NOT silently reapply the
   same change, NOT silently treat the change as successful, and
   either go fail-closed or enter a controlled reconciliation path.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §14 Recovery/Restart

.. ziel:: Known-success reuse and bounded recovery
   :id: ZIEL_050
   :status: draft

   Successfully completed steps may be reused on known success (no
   unnecessary repetition); on unknown or recovery state, the system
   shall go fail-closed. Changed content shall force new
   generation/approval instead of silent reuse. If a needed
   capability or tool is missing at runtime, ADC shall be able to
   transfer this into a bounded, approval-bound recovery without
   reopening the already-made engineering decision and without an
   unbounded repetition loop. After such recovery, the previously
   planned verification shall be re-executed.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §14 Recovery/Restart

.. ziel:: Defect-to-test-coverage learning loop
   :id: ZIEL_051
   :status: draft

   Every locally reproducible, actually observed defect shall be
   durably transferred into deterministic test coverage — not only
   the concrete failure case but the generalized failure pattern it
   represents. The question shall always be asked: which obvious
   errors of the same class would otherwise be discovered again only
   expensively?

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §15 Learning/FMEA

.. ziel:: Living project-level engineering FMEA
   :id: ZIEL_052
   :status: draft

   ADC shall maintain a living engineering FMEA for each project,
   derived from requirements, architecture, technologies, toolchains,
   hardware, operating environment, past errors, tests, and
   real-system evidence — supplemented by a central, reusable failure
   mode library. Each relevant failure mode shall be connected with
   cause, effect, criticality, detection, prevention,
   control/mitigation, owner, verification evidence, test case,
   timing/recovery aspects, and residual risk. FMEA is not a static
   document but part of the engineering learning system.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §15 Learning/FMEA

.. ziel:: Separation of knowledge types
   :id: ZIEL_053
   :status: draft

ADC shall keep different knowledge types separate: Knowledge
    (current valid project/system contract), Evidence (facts from the
    current run), Learning Memory (accepted insights from past errors
    and improvements), Analytic Reasoning (flexible analysis,
    synthesis, and proposal formation), and Deterministic Contracts
    (hard, non-negotiable rules).

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §15 Learning/FMEA

.. ziel:: Learning acceptance process
   :id: ZIEL_054
   :status: draft

   A learning shall only be accepted durably after: Observation →
   Analysis → Test → Evidence → Acceptance → Learning accepted. As
   long as ADC changes substantially, the current truth lies in
   structured data, contracts, and evidence — not in model weights.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §15 Learning/FMEA

.. ziel:: Cross-cutting supervisory capability
   :id: ZIEL_055
   :status: draft

   ADC shall possess a cross-cutting supervision/quality capability
   that observes the entire run (timing, loop/retry behavior, evidence
   quality, project-related FMEA) — starting read-only, initially
   recognizing rather than automatically repairing, later with
   limited capability to warn, block, or stop. This capability shall
   never autonomously execute destructive actions or alternative
   fixes.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §15 Learning/FMEA

.. ziel:: Outcome dependencies — understand before decide, verify before deliver
   :id: ZIEL_056
   :status: draft

   Starting from a clear goal, ADC shall understand the project
   before making significant technical decisions. Technical decisions
   shall be sufficiently justified before a mutation occurs that
   depends on that decision. Mutating actions requiring approval
   shall not occur without that approval. Results shall be
   technically verified before being presented as successfully
   completed. Delivery shall not present unverified or unapproved
   work as an accepted final result.

    Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §16 Success Criteria

.. ziel:: Governance principles apply to firmware and hardware
   :id: ZIEL_057
   :status: draft

   ADC governance principles — engineering decision before mutation,
   controlled tool/device capabilities, human approval for physical
   actions, real verification, traceable evidence, FMEA, and
   traceable delivery — shall apply equally to firmware,
   electronics, hardware, and physical-system engineering artifacts.

   Source: ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §2 Scope