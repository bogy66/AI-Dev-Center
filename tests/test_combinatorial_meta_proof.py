"""Combinatorial coverage meta-proof (KIA-ADC-TEST-ASSURANCE-MODEL-FIX-001
section 5): for every claimed Pairwise/Three-Way domain, mechanically
derive REQUIRED_INTERACTIONS, GENERATED_INTERACTIONS, COVERED_INTERACTIONS
and MISSING_INTERACTIONS using tests/combinatorial_meta_proof.py's
independent (recursion-based, not itertools-based) verifier -- never
tests/env_pairwise.py's own internal obligation bookkeeping.

Also proves (section 4) that every domain currently claiming PAIRWISE or
THREE_WAY here really does have >= 2 / >= 3 genuinely varying dimensions
(the two domains that previously did not -- the original Domain B in
test_env_pairwise_coverage.py and Domain C in test_env_threeway_coverage.py
-- were reclassified as EQUIVALENCE_PARTITION and are checked at
strength=1 instead).
"""
from __future__ import annotations

from tests.combinatorial_meta_proof import verify_combinatorial_coverage
from tests.test_env_pairwise_coverage import (
    _DOMAIN_A as PAIRWISE_A, _DOMAIN_B as PAIRWISE_B, _DOMAIN_C as PAIRWISE_C,
    _DOMAIN_D as PAIRWISE_D, _DOMAIN_E as PAIRWISE_E,
    _PARAMS_A as PAIRWISE_PARAMS_A, _PARAMS_B as PAIRWISE_PARAMS_B,
    _PARAMS_C as PAIRWISE_PARAMS_C, _PARAMS_D as PAIRWISE_PARAMS_D,
    _PARAMS_E as PAIRWISE_PARAMS_E,
)
from tests.test_env_threeway_coverage import (
    _DOMAIN_A as THREEWAY_A, _DOMAIN_B as THREEWAY_B, _DOMAIN_C as THREEWAY_C,
    _DOMAIN_D as THREEWAY_D,
    _PARAMS_A as THREEWAY_PARAMS_A, _PARAMS_B as THREEWAY_PARAMS_B,
    _PARAMS_C as THREEWAY_PARAMS_C, _PARAMS_D as THREEWAY_PARAMS_D,
)

# (label, param_values, strength, generated_cases)
_CLAIMED_DOMAINS = [
    ("pairwise:A", PAIRWISE_PARAMS_A, 2, PAIRWISE_A),
    ("pairwise:B(reclassified equivalence-partition)", PAIRWISE_PARAMS_B, 1, PAIRWISE_B),
    ("pairwise:C", PAIRWISE_PARAMS_C, 2, PAIRWISE_C),
    ("pairwise:D", PAIRWISE_PARAMS_D, 2, PAIRWISE_D),
    ("pairwise:E", PAIRWISE_PARAMS_E, 2, PAIRWISE_E),
    ("threeway:A", THREEWAY_PARAMS_A, 3, THREEWAY_A),
    ("threeway:B", THREEWAY_PARAMS_B, 3, THREEWAY_B),
    ("threeway:C(reclassified equivalence-partition)", THREEWAY_PARAMS_C, 1, THREEWAY_C),
    ("threeway:D", THREEWAY_PARAMS_D, 3, THREEWAY_D),
]


def test_no_claimed_pairwise_or_threeway_domain_has_missing_interactions():
    failures = {}
    for label, param_values, strength, cases in _CLAIMED_DOMAINS:
        report = verify_combinatorial_coverage(param_values, strength, cases)
        if report["missing_count"]:
            failures[label] = sorted(report["missing_interactions"])
    assert not failures, f"domains with MISSING_INTERACTIONS: {failures}"


def test_every_pairwise_domain_has_at_least_two_genuinely_varying_dimensions():
    for label, param_values, strength, _cases in _CLAIMED_DOMAINS:
        if strength != 2:
            continue
        varying = [n for n, values in param_values.items() if len(values) >= 2]
        assert len(varying) >= 2, f"{label}: degenerate PAIRWISE claim, only {varying} vary"


def test_every_threeway_domain_has_at_least_three_genuinely_varying_dimensions():
    for label, param_values, strength, _cases in _CLAIMED_DOMAINS:
        if strength != 3:
            continue
        varying = [n for n, values in param_values.items() if len(values) >= 2]
        assert len(varying) >= 3, f"{label}: degenerate THREE_WAY claim, only {varying} vary"


# ----------------------------------------------------------------------
# Self-consistency of the independent verifier itself, against a small
# hand-countable domain (2 x 3 pairwise => 6 required pairs; 2 x 2 x 2
# threeway => 8 required triples).
# ----------------------------------------------------------------------

def test_verifier_computes_correct_required_count_for_a_known_pairwise_domain():
    params = {"a": (1, 2), "b": ("x", "y", "z")}
    full_cartesian = tuple({"a": a, "b": b} for a in params["a"] for b in params["b"])
    report = verify_combinatorial_coverage(params, strength=2, cases=full_cartesian)
    assert report["required_count"] == 2 * 3
    assert report["missing_count"] == 0
    assert report["covered_count"] == report["required_count"]


def test_verifier_computes_correct_required_count_for_a_known_threeway_domain():
    params = {"a": (1, 2), "b": (True, False), "c": ("p", "q")}
    full_cartesian = tuple(
        {"a": a, "b": b, "c": c} for a in params["a"] for b in params["b"] for c in params["c"]
    )
    report = verify_combinatorial_coverage(params, strength=3, cases=full_cartesian)
    assert report["required_count"] == 2 * 2 * 2
    assert report["missing_count"] == 0


def test_verifier_detects_a_genuinely_missing_interaction():
    params = {"a": (1, 2), "b": ("x", "y")}
    incomplete_cases = ({"a": 1, "b": "x"}, {"a": 2, "b": "y"})  # misses (1,y) and (2,x)
    report = verify_combinatorial_coverage(params, strength=2, cases=incomplete_cases)
    assert report["missing_count"] == 2
    assert (("a", 1), ("b", "y")) in report["missing_interactions"]
    assert (("a", 2), ("b", "x")) in report["missing_interactions"]
