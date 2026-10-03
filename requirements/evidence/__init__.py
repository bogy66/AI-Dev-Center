"""ADC Evidence infrastructure: one Evidence Contract, one publisher, one
central ingest, shared by every ADC testbed/bench.

A testbed only ever needs to know: which test ran, which run it belongs
to, what was tested, what result was observed, and what command produced
it. It never needs to know about SYS_REQ/ARC_REQ/SUB_REQ/IF_REQ or
Sphinx-Needs — central ingest (see `ingest.py`) does that mapping.
"""
