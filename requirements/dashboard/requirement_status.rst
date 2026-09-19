Erfüllungsstatus der Anforderungen
==================================

.. role:: red
.. role:: yellow
.. role:: green

:red:`ROT` — Nicht implementiert
  Die Anforderung ist nicht vollständig implementiert.

:yellow:`GELB` — Implementiert, Verifikation nicht bestanden
  Die Anforderung ist aus Sicht der Implementierungsabdeckung umgesetzt,
  aber die erfolgreiche Verifikation ist noch nicht nachgewiesen.

:green:`GRÜN` — Implementiert und verifiziert
  Die Anforderung ist vollständig implementiert und die erfolgreiche
  Verifikation ist nachgewiesen.

.. note::

   Der Status wird automatisch aus dem Nachverfolgbarkeitsgraphen abgeleitet.
   Er wird niemals manuell in Anforderungsdirektiven eingetragen.

---

Rot — Nicht implementiert
-------------------------

.. container:: adc-status-red

   .. needtable::
      :filter: type in ["sysreq", "arcreq", "subreq", "ifreq"] and "pilot" not in tags and implementation_state == "NOT_IMPLEMENTED"
      :columns: id;type;title;status
      :style: table

Gelb — Implementiert / Verifikation NIO
---------------------------------------

.. container:: adc-status-yellow

   .. needtable::
      :filter: type in ["sysreq", "arcreq", "subreq", "ifreq"] and "pilot" not in tags and implementation_state == "IMPLEMENTED_TEST_NIO"
      :columns: id;type;title;status
      :style: table

Grün — Implementiert / Verifikation IO
--------------------------------------

.. container:: adc-status-green

   .. needtable::
      :filter: type in ["sysreq", "arcreq", "subreq", "ifreq"] and "pilot" not in tags and implementation_state == "IMPLEMENTED_TEST_IO"
      :columns: id;type;title;status
      :style: table