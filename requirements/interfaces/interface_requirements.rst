ADC Interface Requirements
==========================

Normative interface contracts from the ADC Interface Requirements Catalog.
Source: ADC_IF_Anforderungskatalog.txt

External Entry Interfaces
-------------------------

.. ifreq:: Request identity and correlation
   :id: IF_REQ_001
   :status: draft
   :derived_from: SUB_REQ_001

   Every incoming request shall possess a structured identity and
   correlation enabling unique assignment across the entire ADC run.
   The user intent shall be preserved unchanged. The adapter shall not
   reinterpret, restrict, or silently reformulate the user request.

   Source: ADC_IF_Anforderungskatalog.txt IF-000A

.. ifreq:: Adapter shall not select solutions or mutate
   :id: IF_REQ_002
   :status: draft
   :derived_from: SUB_REQ_001

   The external entry adapter shall not select a technical solution,
   toolchain, environment, build method, or engineering strategy.
   The adapter is a pure input interface without project, target,
   or environment mutation authority.

   Source: ADC_IF_Anforderungskatalog.txt IF-000A

.. ifreq:: Project inspector read-only boundary
   :id: IF_REQ_003
   :status: draft
   :derived_from: SUB_REQ_001

   The project inspector shall inspect the project exclusively
   read-only. Every inspection shall be evidence-based and shall
   deliver observable facts, not assumptions or preferences.
   The inspector shall not mutate the project, target, or environment.

   Source: ADC_IF_Anforderungskatalog.txt IF-000B

.. ifreq:: Existing Project First in inspection
   :id: IF_REQ_004
   :status: draft
   :derived_from: SUB_REQ_001

   Observed project conventions, toolchains, build systems, and test
   systems shall be respected and documented. ADC shall not silently
   replace them with ADC defaults. Observation "project uses toolchain
   X" shall not become the silent decision "ADC shall use toolchain X."

   Source: ADC_IF_Anforderungskatalog.txt IF-000B

S1 → S2
-------

.. ifreq:: Requirement identity and activation provenance
   :id: IF_REQ_005
   :status: draft
   :derived_from: SUB_REQ_002

   Every binding requirement shall have a stable technical identity.
   Requirement ID, type, technical identity, required-status, and
   relevant activation shall remain uniquely correlatable through
   S2 evaluation. Activation provenance shall structurally distinguish
   origins: user input, central default, fallback due to missing input,
   fallback due to invalid input, and controlled transformation.

   Source: ADC_IF_Anforderungskatalog.txt IF-001

.. ifreq:: S1 shall not select engineering solutions
   :id: IF_REQ_006
   :status: draft
   :derived_from: SUB_REQ_002

   The S1→S2 boundary shall not carry a technical engineering solution
   selection or setup execution authority from S1. ID loss,
   contradictory binding activations, or unresolvable requirement
   conflicts shall not silently enter a normal council handoff.

   Source: ADC_IF_Anforderungskatalog.txt IF-001

S2 Internal Boundaries
----------------------

.. ifreq:: Alternatives handoff to synthesis
   :id: IF_REQ_007
   :status: draft
   :derived_from: SUB_REQ_003, SUB_REQ_004

   The S2.1→S2.2 handoff shall transfer all relevant proposal/candidate
   IDs with complete cross-review evidence and agent/contributor
   origin. Degraded contributors shall be identifiable. S2.1 shall not
   determine a final winner; S2.2 shall not treat missing candidates
   as present.

   Source: ADC_IF_Anforderungskatalog.txt IF-002

.. ifreq:: Synthesis-to-admissibility transformation lineage
   :id: IF_REQ_008
   :status: draft
   :derived_from: SUB_REQ_004, SUB_REQ_005

   The S2.2→S2.3 handoff shall structurally make the transformation
   chain traceable: source proposal/candidate identity → controlled
   synthesis/merge relationship → final candidate identity. Relevant
   requirement references, toolchain items, and verification-relevant
   fields shall be retained through the transformation. Synthesis
   completion shall not be interpreted as technical admissibility.

   Source: ADC_IF_Anforderungskatalog.txt IF-003

.. ifreq:: Structured rejection for admissibility evaluation
   :id: IF_REQ_009
   :status: draft
   :derived_from: SUB_REQ_005

   S2.3 shall structurally distinguish pre-execution verification
   contract gaps (missing reference, type/technical-identity/semantic/
   version mismatch, verification contract gap) from execution/
   materialization adequacy gaps (materializability conflict, platform
   constraint). Verification contract gap addresses the verification
   strategy, distinct from missing runtime verification evidence.

   Source: ADC_IF_Anforderungskatalog.txt IF-003

.. ifreq:: Inadmissibility evidence to rework
   :id: IF_REQ_010
   :status: draft
   :derived_from: SUB_REQ_005

   S2.3→S2.2 rework feedback shall include only deterministically
   determined technical deficits referencing the specific candidate
   and requirement/constraint. Repairable and non-repairable causes
   shall remain distinguishable. S2.3 shall not repair candidates or
   select alternative winners.

   Source: ADC_IF_Anforderungskatalog.txt IF-004

.. ifreq:: Admissibility results to human authority
   :id: IF_REQ_011
   :status: draft
   :derived_from: SUB_REQ_005, SUB_REQ_006

   The S2.3→S2.4 handoff shall transfer technically evaluated
   candidates with admissible status and structured reasons. Multiple
   admissible alternatives may remain. S2.4 shall never make an
   inadmissible candidate technically admissible. Zero eligible
   candidates means no valid human selection is possible.

   Source: ADC_IF_Anforderungskatalog.txt IF-005

.. ifreq:: Human selection to final decision artifact
   :id: IF_REQ_012
   :status: draft
   :derived_from: SUB_REQ_006, SUB_REQ_007

   The S2.4→S2.5 handoff shall reference an existing admissible
   candidate, retain selection authority, and produce no hidden
   EngineeringDecision on reject/defer/rework. No default winner
   shall be produced on unresolved selection.

   Source: ADC_IF_Anforderungskatalog.txt IF-006

S2 → S3
-------

.. ifreq:: EngineeringDecision handoff to setup
   :id: IF_REQ_013
   :status: draft
   :derived_from: SUB_REQ_007, SUB_REQ_008

   The S2.5→S3.1 handoff shall transfer the EngineeringDecision with
   exact candidate identity, solution class, selection authority, and
   correlatable validation/selection provenance. S3 shall not reselect
   a candidate, exercise S2.3 authority, or reinterpret the
   recommendation.

   Source: ADC_IF_Anforderungskatalog.txt IF-007

S3 Internal Boundaries
----------------------

.. ifreq:: Setup plan to approval with executability mapping
   :id: IF_REQ_014
   :status: draft
   :derived_from: SUB_REQ_008, SUB_REQ_009

   The S3.1→S3.2 handoff shall transfer a SetupPlan with semantically
   classified mutating steps. Automatic executability shall be mappable
   to a compatible controlled executor/capability contract before
   approval. States shall honestly distinguish unsupported, manual,
   already satisfied, and executable. A genuinely non-mutating
   already-satisfied step with deterministic current-state evidence
   does not require human approval.

   Source: ADC_IF_Anforderungskatalog.txt IF-008

.. ifreq:: Approved plan to controlled execution
   :id: IF_REQ_015
   :status: draft
   :derived_from: SUB_REQ_009, SUB_REQ_010

   The S3.2→S3.3 handoff shall transfer the approved, persisted
   SetupPlan with approval provenance bound to exact plan content.
   Exactly the approved plan content shall be executed. Changed content
   shall require new approval. Execution shall not proceed without
   central approval and authorization.

   Source: ADC_IF_Anforderungskatalog.txt IF-009

.. ifreq:: Execution state identity and idempotency contract
   :id: IF_REQ_016
   :status: draft
   :derived_from: SUB_REQ_010, SUB_REQ_011

   The S3.3↔S3.4 bidirectional contract shall manage setup-step
   execution identity, content fingerprint, claim/check state, and
   result/known-success state. Identical known-success content may be
   reused only under explicit contract. Changed content requires new
   execution identity and approval. Unknown or recovery state shall
   fail closed. Concurrent and restart semantics shall be deterministic.

   Source: ADC_IF_Anforderungskatalog.txt IF-010

S3 → S4
-------

.. ifreq:: Setup completion precondition for development
   :id: IF_REQ_017
   :status: draft
   :derived_from: SUB_REQ_013

   Development entry requires: all required setup approved, all
   required executable setup steps completed successfully, no
   unresolved setup blocker, and execution/recovery state safe to
   continue. Development shall not start after failed required setup.

   Source: ADC_IF_Anforderungskatalog.txt IF-011

S4 Internal Boundaries
----------------------

.. ifreq:: Structured development changes to change application
   :id: IF_REQ_018
   :status: draft
   :derived_from: SUB_REQ_013, SUB_REQ_015

   The S4.1→S4.3 handoff shall transfer structured changes with safe
   target-scope-relative semantics and an explicit action/content
   contract. An empty development change set shall fail.

   Source: ADC_IF_Anforderungskatalog.txt IF-012

.. ifreq:: Test changes with disposition contract
   :id: IF_REQ_019
   :status: draft
   :derived_from: SUB_REQ_014, SUB_REQ_015

   The S4.2→S4.3 handoff shall transfer test changes with an explicit
   TestChangeDisposition: either "changes" with actual test changes, or
   "no_changes_required" with empty changes and a non-empty reason. An
   empty changes array alone is not a no-op declaration.

   Source: ADC_IF_Anforderungskatalog.txt IF-013

.. ifreq:: Change application provenance contract
   :id: IF_REQ_020
   :status: draft
   :derived_from: SUB_REQ_015, SUB_REQ_016

   The S4.3↔S4.4 contract shall enforce: baseline-before provenance,
   controlled apply, and event/result attribution. Changed targets
   shall be attributable to run and phase. Target safety shall be
   enforced via central policy. Unauthorized targets shall never mutate
   outside the target scope. Skipped or partial application shall not
   appear successful. Interrupted mutation states shall be detected by
   later runs, correlated with provenance, and go fail-closed.

   Source: ADC_IF_Anforderungskatalog.txt IF-014

S4 → S5
-------

.. ifreq:: Development completion precondition for verification
   :id: IF_REQ_021
   :status: draft
   :derived_from: SUB_REQ_013, SUB_REQ_017

   Verification entry requires: all required S4 mutations succeeded,
   development mutation succeeded, and test mutation succeeded when
   disposition is changes. Partial or skipped required application
   shall not enter normal successful verification flow.

   Source: ADC_IF_Anforderungskatalog.txt IF-015

S5 Internal Boundaries
----------------------

.. ifreq:: Verification plan to execution with step identity
   :id: IF_REQ_022
   :status: draft
   :derived_from: SUB_REQ_017, SUB_REQ_018

   The S5.1→S5.2 handoff shall transfer a VerificationPlan with step
   identity, working area, verification kind, runner/capability type,
   and execution policy structurally defined. Central S5 orchestration
   shall not special-case specific ecosystems.

   Source: ADC_IF_Anforderungskatalog.txt IF-016

.. ifreq:: Verification result to evidence with step fidelity
   :id: IF_REQ_023
   :status: draft
   :derived_from: SUB_REQ_018, SUB_REQ_019

   The S5.2→S5.3 handoff shall transfer VerificationResults with
   preserved status, return code, timeout, diagnostics, runner
   identity, and per-step failure evidence. Every VerificationStepResult
   shall maintain explicit fidelity to the exact VerificationStep that
   produced it. UNSUPPORTED or TOOL_UNAVAILABLE shall not be treated
   as PASS. Multiple failures shall not be collapsed into misleading
   generic success.

   Source: ADC_IF_Anforderungskatalog.txt IF-017

.. ifreq:: Evidence aggregation to diagnostic formatting
   :id: IF_REQ_024
   :status: draft
   :derived_from: SUB_REQ_019, SUB_REQ_020

   The S5.3→S5.4 handoff shall transfer aggregated test results and
   step failure evidence. Formatting shall preserve deterministic
   evidence semantics and shall not decide acceptance/rework or
   rewrite failed evidence into passed evidence.

   Source: ADC_IF_Anforderungskatalog.txt IF-018

.. ifreq:: Diagnostic evidence to interpretation
   :id: IF_REQ_025
   :status: draft
   :derived_from: SUB_REQ_020, SUB_REQ_021

   The S5.4→S5.5 handoff shall transfer bounded, redacted deterministic
   diagnostic evidence. The interpretation shall consume authoritative
   deterministic evidence and shall clearly be non-authoritative over
   real test facts. Hidden provider reasoning shall not become system
   evidence.

   Source: ADC_IF_Anforderungskatalog.txt IF-019

.. ifreq:: Interpretation and test result to outcome policy
   :id: IF_REQ_026
   :status: draft
   :derived_from: SUB_REQ_021, SUB_REQ_022

   The S5.5→S5.6 handoff shall transfer the review result alongside
   the authoritative test result. Deterministic real failure shall
   dominate the reviewer interpretation: test FAIL + reviewer ACCEPTED
   yields rework required; timeout + reviewer ACCEPTED yields rework
   required; review infrastructure failure is not silently accepted.

   Source: ADC_IF_Anforderungskatalog.txt IF-020

.. ifreq:: Outcome policy to controlled rework
   :id: IF_REQ_027
   :status: draft
   :derived_from: SUB_REQ_022, SUB_REQ_023

   The S5.6→S5.7 handoff shall transfer a rework request only for
   defined rework states, with bounded failure evidence retained and
   exactly one bounded controlled rework cycle. Unlimited self-healing
   loops are forbidden.

   Source: ADC_IF_Anforderungskatalog.txt IF-021

.. ifreq:: Rework to development entry with bounded scope
   :id: IF_REQ_028
   :status: draft
   :derived_from: SUB_REQ_023, SUB_REQ_013

   The S5.7→S4 rework entry shall transfer a bounded rework development
   request with original failure evidence remaining attributable.
   Rework scope shall remain bounded. S4 shall not silently erase the
   verification cause.

   Source: ADC_IF_Anforderungskatalog.txt IF-022

S5 → S3 Recovery
----------------

.. ifreq:: Tool unavailable to missing-toolchain recovery
   :id: IF_REQ_029
   :status: draft
   :derived_from: SUB_REQ_012

   The S5→S3.5 recovery path shall trigger only on generic
   TOOL_UNAVAILABLE or defined capability absence. The recovery
   request shall be structured, with persisted verification plan and
   failure evidence. Human approval shall be reused through S3
   approval authority. Recovery shall be bounded and shall not convert
   normal functional test failures into toolchain recovery.

   Source: ADC_IF_Anforderungskatalog.txt IF-023

.. ifreq:: Recovery to verification retry
   :id: IF_REQ_030
   :status: draft
   :derived_from: SUB_REQ_012

   The S3.5→S5 verification retry shall be based on the persisted
   verification intent and plan, with no new S2 candidate selection,
   no infinite retry, and recovered capability verified before normal
   continuation.

   Source: ADC_IF_Anforderungskatalog.txt IF-024

S5 → S6
-------

.. ifreq:: Terminal outcome to delivery
   :id: IF_REQ_031
   :status: draft
   :derived_from: SUB_REQ_024

   The S5→S6 handoff shall transfer only terminal accepted deterministic
   outcome and evidence. Final approval shall remain distinct from
   verification. Local controlled delivery state shall remain distinct
   from publish. Run-owned changes and provenance define delivery
   scope. Failed verification shall not be delivered as success.
   Foreign pre-existing target state changes shall not be silently
   included. Destructive repair of delivery state is forbidden.
   Uncontrolled publish is forbidden. Publish requires its own governed
   approval where the architecture defines it.

   Source: ADC_IF_Anforderungskatalog.txt IF-025

.. ifreq:: Local delivery state to publish
   :id: IF_REQ_032
   :status: draft
   :derived_from: SUB_REQ_024

   The local controlled delivery state shall form the boundary to
   publish approval. Completed controlled local delivery state
   identity shall be known. Publish scope shall be known where publish
   exists. Publish approval shall be distinct from local delivery
   authority. No unrelated pre-existing target state changes shall be
   included.

   Source: ADC_IF_Anforderungskatalog.txt IF-026

Cross-cutting Interfaces
------------------------

.. ifreq:: Diagnostic trace contract
   :id: IF_REQ_033
   :status: draft
   :derived_from: SUB_REQ_028

   The diagnostic trace shall apply to all relevant interfaces,
   preserving structured input/output lineage, recording the
   responsible unit/contract, recording status and failure category,
   correlating to the run, and retaining enough evidence to distinguish
   producer omission, transition corruption, semantic mismatch, and
   valid consumer rejection. The trace shall not store chain-of-thought,
   secrets, tokens, or credentials. Truncated raw prompts shall not be
   the only evidence for structured contracts.

   Source: ADC_IF_Anforderungskatalog.txt IF-027

.. ifreq:: Interface verification governance
   :id: IF_REQ_034
   :status: draft
   :derived_from: SUB_REQ_018

   Each relevant interface shall identify artifact fidelity tests,
   fail-closed negative tests, authority leak tests, diagnostic
   evidence tests, persistence/restart tests where applicable, and
   real-system acceptance evidence where external/live behavior
   matters. A deterministic test with simulated providers shall not
   be described as proof of live-provider correctness. A real-system
   failure before a boundary shall not be described as evidence that
   the later boundary failed.

   Source: ADC_IF_Anforderungskatalog.txt IF-028

S6 → External
-------------

.. ifreq:: Delivery outcome to user, project status, and learning
   :id: IF_REQ_035
   :status: draft
   :derived_from: SUB_REQ_024

   Delivery evidence shall correspond to the actual delivery outcome
   and remain uniquely attributable. Project status shall reflect the
   actual delivery state. Learning memory and FMEA shall only be
   updated based on accepted evidence. Diagnostic or system-generated
   claims alone shall not create accepted learning. ADC shall be able
   to learn from accepted evidence of all outcome classes, including
   failed outcomes. The S6→user interface shall be technology-neutral.

   Source: ADC_IF_Anforderungskatalog.txt IF-029