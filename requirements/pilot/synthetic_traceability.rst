Synthetischer Nachverfolgbarkeitspilot
======================================

.. note::

   Diese Seite ist ein **nicht-normativer technischer Pilot** für das ADC Sphinx-Needs-Setup.
   Alle Needs auf dieser Seite tragen den ``pilot``-Tag und sind von den echten ADC-Dashboards ausgeschlossen.

.. ziel:: Synthetisches ADC-Ziel
   :id: ZIEL_TEST_001
   :tags: pilot
   :status: approved

   ADC soll einen nachverfolgbaren Engineering-Prozess bereitstellen.

.. sysreq:: Synthetische Systemanforderung
   :id: SYS_REQ_TEST_001
   :tags: pilot
   :status: approved
   :realizes: ZIEL_TEST_001

   Relevante Engineering-Ergebnisse sollen auf ihre ursprünglichen Ziele zurückverfolgbar sein.

.. arch:: Synthetische Architekturentscheidung
   :id: ARC_TEST_001
   :tags: pilot
   :status: approved
   :satisfies: SYS_REQ_TEST_001

   Die gewählte Architektur stellt explizite Nachverfolgbarkeitsbeziehungen bereit.

.. arcreq:: Synthetische architekturabgeleitete Anforderung
   :id: ARC_REQ_TEST_001
   :tags: pilot
   :status: approved
   :derived_from: ARC_TEST_001

   Die gewählte Architektur soll eine nachverfolgbare abgeleitete Anforderung bereitstellen.

.. subreq:: Synthetische Subsystemanforderung
   :id: SUB_REQ_TEST_001
   :tags: pilot
   :status: approved
   :derived_from: ARC_REQ_TEST_001

   Der zuständige Funktionsbereich soll die geforderte Nachverfolgbarkeitsbeziehung bewahren.

.. ifreq:: Synthetische Schnittstellenanforderung
   :id: IF_REQ_TEST_001
   :tags: pilot
   :status: approved
   :derived_from: SUB_REQ_TEST_001

   Die Schnittstelle soll die Nachverfolgbarkeitsbeziehung über ihre Grenze hinweg bewahren.

.. impl:: Synthetische Implementierung
   :id: IMPL_TEST_001
   :tags: pilot
   :status: approved
   :implements: IF_REQ_TEST_001

   Synthetischer Implementierungs-Platzhalter.

.. test:: Synthetische Verifikation
   :id: TEST_TEST_001
   :tags: pilot
   :status: approved
   :verification_result: IO
   :verifies: IF_REQ_TEST_001

   Synthetischer Verifikations-Platzhalter.

.. evidence:: Synthetische Evidenz
   :id: EVID_TEST_001
   :tags: pilot
   :status: approved
   :evidences: TEST_TEST_001

   Synthetische PASS-Evidenz.

Nachverfolgbarkeitsgraph
-------------------------

.. needflow:: ADC synthetischer Ende-zu-Ende-Trace
   :root_id: ZIEL_TEST_001
   :root_direction: incoming
   :link_types: realizes,satisfies,derived_from,refines,implements,verifies,evidences
   :show_link_names: outgoing
   :engine: graphviz
   :direction: right

Vorwärts-Nachverfolgbarkeitsmatrix
-----------------------------------

.. needtable::
   :filter: "pilot" in tags
   :columns: id;type;title;realizes;satisfies;derived_from;refines;implements;verifies;evidences
   :style: table

Rückwärts-Nachverfolgbarkeitsmatrix
------------------------------------

.. needtable::
   :filter: "pilot" in tags
   :columns: id;type;title;realizes_back;satisfies_back;derived_from_back;refines_back;implements_back;verifies_back;evidences_back
   :style: table