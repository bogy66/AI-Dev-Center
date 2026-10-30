Requirement Implementation Status
==================================

.. role:: red
.. role:: yellow
.. role:: green

:red:`RED` — Not implemented
  The Requirement is not fully implemented.

:yellow:`YELLOW` — Implemented, verification not proven
  The Requirement is implemented from an implementation-coverage
  perspective, but successful verification is not yet proven.

:green:`GREEN` — Implemented and verified
  The Requirement is fully implemented and successful verification
  is proven.

.. note::

   Status is derived automatically from the traceability graph.
   It is never manually entered on Requirement directives.

---

Red — Not implemented
---------------------

.. container:: adc-status-red

   .. needtable::
      :filter: type in ["sysreq","arcreq","subreq","ifreq"] and "pilot" not in tags
      :filter-func: status_model.filter_red
      :columns: id;type;title;status
      :style: table

Yellow — Implemented / Verification NIO
---------------------------------------

.. container:: adc-status-yellow

   .. needtable::
      :filter: type in ["sysreq","arcreq","subreq","ifreq"] and "pilot" not in tags
      :filter-func: status_model.filter_yellow
      :columns: id;type;title;status
      :style: table

Green — Implemented / Verification IO
-------------------------------------

.. container:: adc-status-green

   .. needtable::
      :filter: type in ["sysreq","arcreq","subreq","ifreq"] and "pilot" not in tags
      :filter-func: status_model.filter_green
      :columns: id;type;title;status
      :style: table