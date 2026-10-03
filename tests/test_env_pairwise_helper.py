"""Tests for the deterministic covering-array helper itself
(tests/env_pairwise.py) -- CLAUDE-ADC-TEST-ENVIRONMENT-FIDELITY-UPGRADE-001
section 3: "The helper itself must be tested."
"""
from __future__ import annotations

from itertools import combinations, product

import pytest

from tests.env_pairwise import case_id, generate_covering_array


def _assert_full_t_way_coverage(cases, param_values, strength):
    names = tuple(param_values.keys())
    for name_combo in combinations(names, strength):
        value_lists = [param_values[n] for n in name_combo]
        for value_combo in product(*value_lists):
            obligation = tuple(zip(name_combo, value_combo))
            assert any(
                all(case[name] == value for name, value in obligation)
                for case in cases
            ), f"uncovered {strength}-way obligation: {obligation}"


def test_pairwise_covers_every_pair_for_a_small_domain():
    params = {"a": (1, 2, 3), "b": ("x", "y"), "c": (True, False)}
    cases = generate_covering_array(params, strength=2)
    assert len(cases) > 0
    _assert_full_t_way_coverage(cases, params, strength=2)


def test_pairwise_is_smaller_than_full_cartesian_product_for_a_nontrivial_domain():
    params = {"a": (1, 2, 3, 4), "b": ("x", "y", "z"), "c": (True, False), "d": ("p", "q")}
    full_product_size = 4 * 3 * 2 * 2
    cases = generate_covering_array(params, strength=2)
    assert len(cases) < full_product_size


def test_pairwise_generation_is_deterministic_across_repeated_calls():
    params = {"a": (1, 2, 3), "b": ("x", "y"), "c": (True, False), "d": ("p", "q", "r")}
    first = generate_covering_array(params, strength=2)
    second = generate_covering_array(params, strength=2)
    assert first == second


def test_threeway_covers_every_triple_for_a_small_domain():
    params = {"a": (1, 2), "b": ("x", "y"), "c": (True, False), "d": ("p", "q")}
    cases = generate_covering_array(params, strength=3)
    assert len(cases) > 0
    _assert_full_t_way_coverage(cases, params, strength=3)


def test_single_parameter_domain_at_pairwise_strength_is_rejected_as_degenerate():
    """KIA-ADC-TEST-ASSURANCE-MODEL-FIX-001 section 4: a PAIRWISE claim
    requires >= 2 genuinely varying dimensions. A single parameter can
    never satisfy that, and must be rejected -- not silently downgraded
    to a 1-way sweep while still being labelled pairwise (the previous
    behavior of this exact call)."""
    params = {"only": (1, 2, 3)}
    with pytest.raises(ValueError, match="degenerate PAIRWISE claim"):
        generate_covering_array(params, strength=2)


def test_single_parameter_domain_at_strength_one_is_a_legitimate_equivalence_partition():
    params = {"only": (1, 2, 3)}
    cases = generate_covering_array(params, strength=1)
    assert {c["only"] for c in cases} == {1, 2, 3}


def test_pairwise_with_one_constant_dimension_is_rejected_as_degenerate():
    """A dimension pinned to a single value contributes nothing to a
    pairwise claim -- reproduces the exact shape this task's audit
    found in tests/test_env_pairwise_coverage.py's original Domain B."""
    params = {"cwd_class": ("valid_root", "nested", "outside_root", "missing"), "interface": ("internal",)}
    with pytest.raises(ValueError, match="degenerate PAIRWISE claim"):
        generate_covering_array(params, strength=2)


def test_threeway_with_two_constant_dimensions_is_rejected_as_degenerate():
    """Reproduces the exact shape this task's audit found in
    tests/test_env_threeway_coverage.py's original Domain C: one
    varying dimension plus two constant labels must not count as
    Three-Way."""
    params = {
        "status_outcome": ("success", "nonzero", "missing_status"),
        "lifecycle_state": ("first_execution",),
        "interface": ("internal",),
    }
    with pytest.raises(ValueError, match="degenerate THREE_WAY claim"):
        generate_covering_array(params, strength=3)


def test_empty_domain_returns_empty_tuple():
    assert generate_covering_array({}, strength=2) == ()


def test_case_id_is_stable_and_readable():
    assignment = {"a": 1, "b": "x"}
    assert case_id(assignment) == "a=1-b=x"
