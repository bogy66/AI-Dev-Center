Council lifecycle adoption and unapproved profile candidates
============================================================

Authority: explicit user adoption CODEX-ADC-COUNCIL-REQUIREMENTS-ADOPTION-026 of E1, E2, E3 and CL-F01 through CL-F08 from finalization 025. The German source catalog and English SUB_REQ_033 through SUB_REQ_040 describe the same approved semantic contract. Only these new obligations are approved. Their allocation through ARC_033 identifies the existing Council responsibility, not a new architecture mechanism. Direct system links retain budget and diagnosis provenance.

Source: ADC_Council_Lifecycle_Anforderungskatalog.txt; targeted IF-030 addition in ADC_IF_Anforderungskatalog.txt. Original Zielbild and unrelated draft statuses are unchanged. No implementation object is assigned: all eight obligations remain NOT_IMPLEMENTED; TEST_036 through TEST_039 remain NOT_RUN without evidence.

TEST_003 retains alternatives and cross-review only. Legacy lifecycle reproductions are preserved but excluded from its effective selector scope; they are not automatically assigned to the new acceptance obligations. TEST_030 retains its existing evidence scope; TEST_037 adds storage and retrieval obligations without inheriting its IO result.

No numeric value below is approved, a default requirement, or an implementation instruction. Existing values are observations only; proposed values require usage/capacity validation and separate approval. A finite declared operating profile is mandatory, but adoption does not choose its numbers.

Existing orientation: contributor timeout 60 s, chairman timeout 90 s, at most two attempts, local provider capacity 16, and notification capacity 64. Proposed true attempt-total deadlines and the derived maximum of 16 request handovers remain profile candidates, including automatic retries. These bounds do not guarantee a monetary cost ceiling.

Derived time candidates for the existing workflow: phases 120/120/360 s, preparation 5 s, finalization including storage confirmation 5 s, public total 610 s from entry, and measurement tolerance 1 s. The 5 s and 1 s values are unmeasured proposals; all require validation. Quarantine has no individual termination deadline. Owner-process shutdown candidate: 5 s, not proof that all remote or separate local work ended.

Storage/retrieval candidates, not empirically validated: service reservation pool 64 MiB, critical diagnosis envelope 1 MiB per Council, volatile retrieval 1 hour while the service runs, and confirmed-persistence retention 30 days. Validate against actual mandatory data and invocation rates. Reservation covers a structurally bounded mandatory record and overflow path, not an exact forecast of all future diagnosis. Large functional artifacts need separate resource accounting.

Delivery-buffer candidate: retain only the latest waiting progress per subscription and bounded completion references in the independent retrieval source. Queue-byte limits, subscription count, and storage capacity must be validated; deriving capacity from the number of callback types is not justified. No single-Council limit is adopted.

Task 021 remains deferred. TEST_033, TEST_035, real-system E2E, and live providers remain blocked. Historical compile timeout and DEF-010 remain OPEN_UNCHANGED. CMake/CTest evidence remains a separate open tool/evidence obligation, not fulfilled by Council documentation builds.

.. needtable::
   :filter: id in ["SUB_REQ_033", "SUB_REQ_034", "SUB_REQ_035", "SUB_REQ_036", "SUB_REQ_037", "SUB_REQ_038", "SUB_REQ_039", "SUB_REQ_040", "TEST_036", "TEST_037", "TEST_038", "TEST_039"]
   :columns: id; title_display; status; implementation_state; verification_result
