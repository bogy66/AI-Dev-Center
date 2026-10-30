ADC Traceability
================

Real ADC trace graph
--------------------

This graph shows only real ADC engineering objects. The synthetic pilot is excluded.

.. needflow:: ADC end-to-end trace
   :filter: "pilot" not in tags
   :link_types: realizes,satisfies,derived_from,refines,implements,verifies,evidences
   :show_link_names: outgoing
   :engine: graphviz
   :direction: right

Red background = Not implemented · Yellow background = Implemented, verification not IO · Green background = Implemented and verification IO
(traffic-light backgrounds apply to Requirement nodes only — SYS_REQ / ARC_REQ / SUB_REQ / IF_REQ)

Zielbild → System Requirements
------------------------------

.. needtable::
   :filter: type in ["ziel", "sysreq"] and "pilot" not in tags
   :columns: id;type;title;realizes;realizes_back
   :style: table

System Requirements → Architecture
----------------------------------

.. needtable::
   :filter: type in ["sysreq", "arch"] and "pilot" not in tags
   :columns: id;type;title;satisfies;satisfies_back
   :style: table

Architecture → Derived Requirements
-----------------------------------

.. needtable::
   :filter: type in ["arch", "arcreq", "subreq", "ifreq"] and "pilot" not in tags
   :columns: id;type;title;derived_from;derived_from_back;refines;refines_back
   :style: table

Requirements → Implementation / Tests
-------------------------------------

.. needtable::
   :filter: type in ["arcreq", "subreq", "ifreq", "impl", "test"] and "pilot" not in tags
   :columns: id;type;title;implements;implements_back;verifies;verifies_back
   :style: table

Tests → Evidence
----------------

.. needtable::
   :filter: type in ["test", "evidence"] and "pilot" not in tags
   :columns: id;type;title;evidences;evidences_back
   :style: table
