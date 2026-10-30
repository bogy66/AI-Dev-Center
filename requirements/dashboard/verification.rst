ADC Verification Overview
=========================

Tests
-----

.. needtable::
   :filter: type == "test" and "pilot" not in tags
   :columns: id;title;status;verifies;evidences_back
   :style: table

Evidence
--------

.. needtable::
   :filter: type == "evidence" and "pilot" not in tags
   :columns: id;title;status;evidences
   :style: table

Verified requirements
---------------------

.. needtable::
   :filter: type in ["sysreq", "arcreq", "subreq", "ifreq"] and "pilot" not in tags
   :columns: id;type;title;status;verifies_back
   :style: table
