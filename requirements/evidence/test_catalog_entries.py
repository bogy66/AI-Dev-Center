"""Tests for the authoritative equivalence-class catalog entries
(KIA-ADC-TEST-ASSURANCE-MODEL-FIX-001 section 2).
"""
from __future__ import annotations

import pytest

from requirements.evidence.catalog_entries import (
    ALLOWED_COVERAGE_STRATEGIES, build_catalog_entry, validate_catalog_entry,
)
from tests.env_scenarios import all_classes


def test_unknown_class_id_raises():
    with pytest.raises(KeyError):
        build_catalog_entry("NOT_A_REAL_CLASS_ID", live_report={"sources": {}})


def test_entry_with_no_sources_has_no_selectors_no_strategy_and_fails_validation():
    entry = build_catalog_entry("ARGV_ORDINARY", live_report={"sources": {}})
    assert entry.test_selectors == ()
    assert entry.coverage_strategy is None
    assert entry.requirement_ids == ()
    # PRODUCT_BOUNDARY_OR_BRANCH is a static, per-class mapping (see
    # PRODUCT_BOUNDARY_OR_BRANCH_BY_CLASS) independent of live coverage,
    # so it is populated even with an empty synthetic report.
    assert entry.product_boundary_or_branch is not None
    is_valid, reasons = validate_catalog_entry(entry)
    assert is_valid is False
    assert any("PASS-VERIFIED" in r for r in reasons)
    assert not any("product_boundary_or_branch" in r for r in reasons)


def test_entry_with_a_pairwise_source_is_classified_pairwise():
    synthetic = {"sources": {
        "PROC_SPAWN_SUCCESS": ["tests.test_env_pairwise_coverage::test_pairwise_process_outcome_x_provider_state"],
    }}
    entry = build_catalog_entry("PROC_SPAWN_SUCCESS", live_report=synthetic)
    assert entry.coverage_strategy == "PAIRWISE"


def test_the_reclassified_pairwise_b_function_is_equivalence_partition_not_pairwise():
    synthetic = {"sources": {
        "FS_VALID_ROOT": ["tests.test_env_pairwise_coverage::test_pairwise_cwd_class_x_interface"],
    }}
    entry = build_catalog_entry("FS_VALID_ROOT", live_report=synthetic)
    assert entry.coverage_strategy == "EQUIVALENCE_PARTITION"


def test_the_reclassified_threeway_c_function_is_equivalence_partition_not_threeway():
    synthetic = {"sources": {
        "PROC_MISSING_STATUS": ["tests.test_env_threeway_coverage::test_threeway_child_status_outcome_x_lifecycle_x_interface"],
    }}
    entry = build_catalog_entry("PROC_MISSING_STATUS", live_report=synthetic)
    assert entry.coverage_strategy == "EQUIVALENCE_PARTITION"


def test_gate_is_always_gate1_for_this_catalog():
    entry = build_catalog_entry("ARGV_ORDINARY", live_report={"sources": {}})
    assert entry.gate == "GATE1"


def test_validate_catalog_entry_accepts_all_allowed_strategies_and_rejects_others():
    from requirements.evidence.catalog_entries import CatalogEntry
    for strategy in ALLOWED_COVERAGE_STRATEGIES:
        entry = CatalogEntry(
            class_id="X", dimension="D", gate="GATE1", requirement_ids=("IF_REQ_001",),
            product_boundary_or_branch="app.x.y", coverage_strategy=strategy,
            test_selectors=("tests/test_x.py::test_y",),
        )
        is_valid, reasons = validate_catalog_entry(entry)
        assert is_valid is True, reasons

    from dataclasses import replace
    invalid = replace(entry, coverage_strategy="NOT_A_REAL_STRATEGY")
    is_valid, reasons = validate_catalog_entry(invalid)
    assert is_valid is False


def test_every_real_equivalence_class_can_build_an_entry_without_crashing():
    """Structural smoke test across the whole real 94-class catalog,
    with an empty synthetic report (no live pytest session here) --
    every entry must build without error. Each entry still reports as
    incomplete under a report with no sources (no PASS-VERIFIED
    selectors, so no traceable requirement_ids either), but
    product_boundary_or_branch -- a static per-class mapping, not
    derived from live coverage -- is always populated."""
    for equivalence_class in all_classes():
        entry = build_catalog_entry(equivalence_class.class_id, live_report={"sources": {}})
        assert entry.product_boundary_or_branch is not None
        is_valid, reasons = validate_catalog_entry(entry)
        assert is_valid is False
        assert "product_boundary_or_branch not yet assigned" not in reasons
        assert "no PASS-VERIFIED test_selectors" in reasons
