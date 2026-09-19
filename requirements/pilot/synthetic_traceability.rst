Synthetic Traceability Pilot
============================

.. note::

   This page is a **non-normative technical pilot** for the ADC Sphinx-Needs setup.
   All Needs on this page carry the ``pilot`` tag and are excluded from the real ADC dashboards.

.. ziel:: Synthetic ADC goal
   :id: ZIEL_TEST_001
   :tags: pilot
   :status: approved

   ADC shall provide a traceable engineering process.

.. sysreq:: Synthetic system requirement
   :id: SYS_REQ_TEST_001
   :tags: pilot
   :status: approved
   :realizes: ZIEL_TEST_001

   Relevant engineering outcomes shall be traceable to their originating goals.

.. arch:: Synthetic architecture decision
   :id: ARC_TEST_001
   :tags: pilot
   :status: approved
   :satisfies: SYS_REQ_TEST_001

   The selected architecture provides explicit trace relationships.

.. arcreq:: Synthetic architecture-derived requirement
   :id: ARC_REQ_TEST_001
   :tags: pilot
   :status: approved
   :derived_from: ARC_TEST_001

   The selected architecture shall expose a traceable derived requirement.

.. subreq:: Synthetic subsystem requirement
   :id: SUB_REQ_TEST_001
   :tags: pilot
   :status: approved
   :derived_from: ARC_REQ_TEST_001

   The responsible functional area shall preserve the required trace relationship.

.. ifreq:: Synthetic interface requirement
   :id: IF_REQ_TEST_001
   :tags: pilot
   :status: approved
   :derived_from: SUB_REQ_TEST_001

   The interface shall preserve the trace relationship across its boundary.

.. impl:: Synthetic implementation
   :id: IMPL_TEST_001
   :tags: pilot
   :status: approved
   :implements: IF_REQ_TEST_001

   Synthetic implementation placeholder.

.. test:: Synthetic verification
   :id: TEST_TEST_001
   :tags: pilot
   :status: approved
   :verification_result: IO
   :verifies: IF_REQ_TEST_001

   Synthetic verification placeholder.

.. evidence:: Synthetic evidence
   :id: EVID_TEST_001
   :tags: pilot
   :status: approved
   :evidences: TEST_TEST_001

   Synthetic PASS evidence.

Traceability graph
------------------

.. needflow:: ADC synthetic end-to-end trace
   :root_id: ZIEL_TEST_001
   :root_direction: incoming
   :link_types: realizes,satisfies,derived_from,refines,implements,verifies,evidences
   :show_link_names: outgoing
   :engine: graphviz
   :direction: right

Forward traceability matrix
---------------------------

.. needtable::
   :filter: "pilot" in tags
   :columns: id;type;title;realizes;satisfies;derived_from;refines;implements;verifies;evidences
   :style: table

Reverse coverage matrix
-----------------------

.. needtable::
   :filter: "pilot" in tags
   :columns: id;type;title;realizes_back;satisfies_back;derived_from_back;refines_back;implements_back;verifies_back;evidences_back
   :style: table
