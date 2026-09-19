ADC Traceability
================

Echter ADC-Trace-Graph
----------------------

Dieser Graph zeigt nur echte ADC-Engineering-Objekte. Der synthetische Pilot ist ausgeschlossen.

.. needflow:: ADC Ende-zu-Ende Trace
   :filter: "pilot" not in tags
   :link_types: realizes,satisfies,derived_from,refines,implements,verifies,evidences
   :show_link_names: outgoing
   :engine: graphviz
   :direction: right

Legende (nur Anforderungsknoten)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

🔴 **ROT** — Nicht implementiert

🟡 **GELB** — Implementiert, Verifikation nicht bestanden

🟢 **GRÜN** — Implementiert und Verifikation bestanden

Nicht-Anforderungsknoten (ZIEL, ARC, IMPL, TEST, EVID) tragen keinen Status-Punkt.

Zielbild → Systemanforderungen
------------------------------

.. needtable::
   :filter: type in ["ziel", "sysreq"] and "pilot" not in tags
   :columns: id;type;title;realizes;realizes_back
   :style: table

Systemanforderungen → Architektur
---------------------------------

.. needtable::
   :filter: type in ["sysreq", "arch"] and "pilot" not in tags
   :columns: id;type;title;satisfies;satisfies_back
   :style: table

Architektur → Abgeleitete Anforderungen
---------------------------------------

.. needtable::
   :filter: type in ["arch", "arcreq", "subreq", "ifreq"] and "pilot" not in tags
   :columns: id;type;title;derived_from;derived_from_back;refines;refines_back
   :style: table

Anforderungen → Implementierung / Tests
---------------------------------------

.. needtable::
   :filter: type in ["arcreq", "subreq", "ifreq", "impl", "test"] and "pilot" not in tags
   :columns: id;type;title;implements;implements_back;verifies;verifies_back
   :style: table

Tests → Evidenz
---------------

.. needtable::
   :filter: type in ["test", "evidence"] and "pilot" not in tags
   :columns: id;type;title;evidences;evidences_back
   :style: table