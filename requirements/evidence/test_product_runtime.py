"""Cross-environment governance meta-test (CLAUDE-ADC-RSE033-INSTALLER-
RECOVERY-CLOSURE-FIX-002 section 22).

Runs from whichever interpreter executes the governance suite -- in
particular the canonical `.requirements-venv`, which has no product
runtime dependencies (FastAPI, ...) -- and proves the current Gate-1 and
Gate-2 product-test selectors are validated through the product runtime
without import failures. Every negative case fails closed; nothing skips.
"""
from __future__ import annotations

import os

import pytest

from requirements.evidence import product_runtime
from requirements.evidence.gate2_selector_map import GATE2_SELECTOR_MAP
from requirements.evidence.product_runtime import (
    PRODUCT_PYTHON_ENV, ProductRuntimeUnavailable, ProductSelectorCollectionError,
    StaleProductSelector, collect_product_nodeids, product_python, resolve_product_selectors,
)
from requirements.evidence.proof_obligations import check_selectors_collectible
from requirements.evidence.selector_map import SELECTOR_MAP


def test_current_gate1_and_gate2_selectors_resolve_through_the_product_runtime():
    selectors = sorted({s for sels in SELECTOR_MAP.values() for s in sels}
                       | {s for sels in GATE2_SELECTOR_MAP.values() for s in sels})
    resolved = resolve_product_selectors(selectors)
    assert set(resolved) == set(selectors)
    assert all(resolved.values())
    # The web-facing product tests import FastAPI; they still collect.
    assert resolved["tests/test_installer_recovery_productive_path.py"]


def test_product_runtime_is_the_repository_product_interpreter():
    python = product_python()
    assert python.endswith(os.path.join("venv", "bin", "python"))
    assert ".requirements-venv" not in python


def test_missing_product_runtime_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv(PRODUCT_PYTHON_ENV, str(tmp_path / "no-such-python"))
    with pytest.raises(ProductRuntimeUnavailable):
        product_python()
    with pytest.raises(ProductRuntimeUnavailable):
        collect_product_nodeids(["tests/test_missing_toolchain_setup.py"])
    with pytest.raises(ProductRuntimeUnavailable):
        check_selectors_collectible(("tests/test_missing_toolchain_setup.py",))


def test_stale_selector_fails_closed():
    with pytest.raises(StaleProductSelector, match="test_renamed_away"):
        resolve_product_selectors((
            "tests/test_missing_toolchain_setup.py::test_setup_cannot_execute_before_approval",
            "tests/test_missing_toolchain_setup.py::test_renamed_away",
        ))


def test_collection_failure_fails_closed(tmp_path):
    broken = tmp_path / "test_import_failure.py"
    broken.write_text("import adc_module_that_does_not_exist\n\ndef test_x():\n    pass\n", encoding="utf-8")
    with pytest.raises(ProductSelectorCollectionError, match="collection failed"):
        collect_product_nodeids([str(broken)])


def test_zero_collected_nodes_fail_closed(tmp_path):
    empty = tmp_path / "test_nothing_here.py"
    empty.write_text("VALUE = 1\n", encoding="utf-8")
    with pytest.raises(ProductSelectorCollectionError):
        collect_product_nodeids([str(empty)])
    with pytest.raises(ProductSelectorCollectionError):
        collect_product_nodeids([])


def test_governance_never_launches_product_pytest_with_its_own_interpreter():
    """The runtime split is structural: Gate-1 collectibility, the Gate-2
    runner and the Gate-1 scoping probe build their pytest command only
    through product_runtime."""
    import inspect

    from requirements.evidence import gate2_proof, proof_obligations
    for module in (gate2_proof, proof_obligations):
        source = inspect.getsource(module)
        assert "sys.executable" not in source, module.__name__
        assert "product_pytest_command" in source, module.__name__
    assert product_runtime.product_pytest_command("-q")[0] == product_python()
