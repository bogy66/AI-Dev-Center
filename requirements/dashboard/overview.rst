ADC Engineering Dashboard
=========================

.. role:: red
.. role:: yellow
.. role:: green

Erfüllungsstatus der Anforderungen
----------------------------------

:red:`ROT` — Nicht implementiert  |  :yellow:`GELB` — Implementiert, Verifikation NIO  |  :green:`GRÜN` — Implementiert, Verifikation IO

Siehe :doc:`requirement_status` für die vollständige Aufschlüsselung.

Engineering-Kette
-----------------

**Zielbild → Systemanforderungen → Architektur → Abgeleitete Anforderungen → Implementierung → Tests → Evidenz**

Das Zielbild-TXT bleibt die normative, menschenlesbare Quelle.
Die folgenden Seiten bieten Nachverfolgbarkeitsansichten über die Sphinx-Needs-Repräsentation.

Echte ADC-Inhalte
-----------------

Zielbild-Objekte
~~~~~~~~~~~~~~~~

.. needtable::
   :filter: type == "ziel" and "pilot" not in tags
   :columns: id;title;status
   :style: table

Systemanforderungen
~~~~~~~~~~~~~~~~~~~

.. needtable::
   :filter: type == "sysreq" and "pilot" not in tags
   :columns: id;title;status;realizes
   :style: table

Architekturentscheidungen
~~~~~~~~~~~~~~~~~~~~~~~~~

.. needtable::
   :filter: type == "arch" and "pilot" not in tags
   :columns: id;title;status;satisfies
   :style: table

Abgeleitete Anforderungen
~~~~~~~~~~~~~~~~~~~~~~~~~

.. needtable::
   :filter: type in ["arcreq", "subreq", "ifreq"] and "pilot" not in tags
   :columns: id;type;title;status;derived_from
   :style: table

Implementierung / Verifikation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. needtable::
   :filter: type in ["impl", "test", "evidence"] and "pilot" not in tags
   :columns: id;type;title;status;implements;verifies;evidences
   :style: table