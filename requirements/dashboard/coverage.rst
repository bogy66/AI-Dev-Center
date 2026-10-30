ADC Coverage
============

Coverage gaps
-------------

The following tables are intended as engineering review views.
Empty tables mean no matching gap currently exists in the loaded real ADC Needs.

Zielbild without System Requirement coverage
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. needtable::
   :filter: type == "ziel" and "pilot" not in tags and len(realizes_back) == 0
   :columns: id;title;status
   :style: table

System Requirements without Architecture coverage
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. needtable::
   :filter: type == "sysreq" and "pilot" not in tags and len(satisfies_back) == 0
   :columns: id;title;status;realizes
   :style: table

Derived requirements without origin
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. needtable::
   :filter: type in ["arcreq", "subreq", "ifreq"] and "pilot" not in tags and len(derived_from) == 0
   :columns: id;type;title;status
   :style: table

Requirements without implementation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Architecture-, Subsystem-, and Interface-level Requirements only. By design,
System Requirements never carry a direct implementation link — they aggregate
their status through the Architecture they are satisfied by, so listing them
here would flag every System Requirement unconditionally rather than a real
gap.

.. needtable::
   :filter: type in ["arcreq", "subreq", "ifreq"] and "pilot" not in tags and len(implements_back) == 0
   :columns: id;type;title;status;derived_from
   :style: table

Requirements without verification
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Architecture-, Subsystem-, and Interface-level Requirements only, for the
same aggregation reason as above.

.. needtable::
   :filter: type in ["arcreq", "subreq", "ifreq"] and "pilot" not in tags and len(verifies_back) == 0
   :columns: id;type;title;status;derived_from
   :style: table

Implemented but not verified (implementation gap into test)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Requirements that have an Implementation object but no Test verifying them —
the YELLOW-producing case.

.. needtable::
   :filter: type in ["arcreq", "subreq", "ifreq"] and "pilot" not in tags and len(implements_back) > 0 and len(verifies_back) == 0
   :columns: id;type;title;status;implements_back
   :style: table

Tests without Evidence
~~~~~~~~~~~~~~~~~~~~~~

.. needtable::
   :filter: type == "test" and "pilot" not in tags and len(evidences_back) == 0
   :columns: id;title;status;verifies
   :style: table

Tests with failed or unproven verification (NIO)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. needtable::
   :filter: type == "test" and "pilot" not in tags and verification_result not in ["IO", ""]
   :columns: id;title;status;verification_result;verifies
   :style: table
