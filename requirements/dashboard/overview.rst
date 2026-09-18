ADC Engineering Dashboard
=========================

.. role:: red
.. role:: yellow
.. role:: green

Requirement Implementation Status
---------------------------------

:red:`RED` — Not implemented  |  :yellow:`YELLOW` — Implemented, verification NIO  |  :green:`GREEN` — Implemented and verified

See :doc:`requirement_status` for the full breakdown.

Requirement implementation summary
-----------------------------------

Derived counts across real (non-pilot) System, Architecture-derived, Subsystem,
and Interface Requirements — computed by the same central status model used on
every Requirement card and on the :doc:`requirement_status` page.

.. raw:: html

   <div class="adc-status-summary-block">ADC_STATUS_SUMMARY_PLACEHOLDER</div>

Engineering chain
-----------------

**Zielbild → System Requirements → Architecture → Derived Requirements → Implementation → Tests → Evidence**

The Zielbild TXT remains the normative human-readable source.
The pages below provide traceability views over the Sphinx-Needs representation.

Real ADC content
----------------

Zielbild objects
~~~~~~~~~~~~~~~~

.. needtable::
   :filter: type == "ziel" and "pilot" not in tags
   :columns: id;title;status
   :style: table

System Requirements
~~~~~~~~~~~~~~~~~~~

.. needtable::
   :filter: type == "sysreq" and "pilot" not in tags
   :columns: id;title;status;realizes
   :style: table

Architecture Decisions
~~~~~~~~~~~~~~~~~~~~~~

.. needtable::
   :filter: type == "arch" and "pilot" not in tags
   :columns: id;title;status;satisfies
   :style: table

Derived Requirements
~~~~~~~~~~~~~~~~~~~~

.. needtable::
   :filter: type in ["arcreq", "subreq", "ifreq"] and "pilot" not in tags
   :columns: id;type;title;status;derived_from
   :style: table

Implementation / Verification
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. needtable::
   :filter: type in ["impl", "test", "evidence"] and "pilot" not in tags
   :columns: id;type;title;status;implements;verifies;evidences
   :style: table