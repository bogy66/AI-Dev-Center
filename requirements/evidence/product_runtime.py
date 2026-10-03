"""The one place Requirements governance reaches product tests from
(CLAUDE-ADC-RSE033-INSTALLER-RECOVERY-CLOSURE-FIX-002 section 21).

`.requirements-venv` is the canonical Requirements/Sphinx environment and
deliberately does not carry ADC's product runtime dependencies (FastAPI,
...). Product tests are collected and executed by the product interpreter
(`venv/`) only. Governance code -- Gate-1 selector collectibility, the
Gate-2 runner, the Gate-3 defect register -- therefore never launches a
product-test pytest session with its own `sys.executable`; it goes
through product_python() here, from whichever interpreter it runs in.

Fail closed: a missing product interpreter, a collection error (e.g. an
import failure), a stale selector or a selector resolving to zero nodes
raises -- never a silent skip or an empty "nothing to check".
"""
from __future__ import annotations

import os
import subprocess

from .current_run_completion import _selector_matches  # the Gate-1/Gate-2 selector semantics
from .ingest import REPO_ROOT

# Explicit override (e.g. a container image with the product interpreter
# elsewhere). Never a fallback: when unset, only <repo>/venv/bin/python.
PRODUCT_PYTHON_ENV = "ADC_PRODUCT_PYTHON"


class ProductRuntimeError(RuntimeError):
    """Base class: the product runtime cannot answer a selector question."""


class ProductRuntimeUnavailable(ProductRuntimeError):
    """The product interpreter does not exist or is not executable."""


class ProductSelectorCollectionError(ProductRuntimeError):
    """Collecting product tests failed or collected nothing."""


class StaleProductSelector(ProductRuntimeError):
    """A selector resolves to no collected product-test node."""


def product_python(repo_root: str | None = None) -> str:
    candidate = os.environ.get(PRODUCT_PYTHON_ENV) or os.path.join(
        repo_root or REPO_ROOT, "venv", "bin", "python",
    )
    if not (os.path.isfile(candidate) and os.access(candidate, os.X_OK)):
        raise ProductRuntimeUnavailable(
            f"product runtime interpreter is unavailable: {candidate!r}"
        )
    return candidate


def product_pytest_command(*args: str, repo_root: str | None = None) -> list[str]:
    return [product_python(repo_root), "-m", "pytest", *args]


def product_env(repo_root: str | None = None) -> dict[str, str]:
    env = dict(os.environ)
    root = repo_root or REPO_ROOT
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [root, env.get("PYTHONPATH")]))
    return env


def collect_product_nodeids(paths, repo_root: str | None = None) -> tuple[str, ...]:
    """Every nodeid the product runtime collects for `paths`
    (execution-free). Raises on any collection error or zero nodes."""
    repo_root = repo_root or REPO_ROOT
    paths = sorted(set(paths))
    if not paths:
        raise ProductSelectorCollectionError("no product-test paths to collect")
    completed = subprocess.run(
        product_pytest_command("--collect-only", "-q", "-p", "no:cacheprovider", *paths,
                               repo_root=repo_root),
        cwd=repo_root, env=product_env(repo_root), capture_output=True, text=True, timeout=300,
    )
    if completed.returncode != 0:
        raise ProductSelectorCollectionError(
            f"product-test collection failed (exit {completed.returncode}):\n"
            f"{completed.stdout[-4000:]}\n{completed.stderr[-4000:]}"
        )
    nodeids = tuple(
        line.strip() for line in completed.stdout.splitlines()
        if "::" in line and not line.startswith(" ")
    )
    if not nodeids:
        raise ProductSelectorCollectionError(f"product-test collection found zero nodes in {paths}")
    return nodeids


def resolve_product_selectors(selectors, repo_root: str | None = None) -> dict[str, tuple[str, ...]]:
    """selector -> the product-test nodeids it names today. Raises
    StaleProductSelector for any selector that names nothing."""
    selectors = tuple(selectors)
    collected = collect_product_nodeids((s.split("::", 1)[0] for s in selectors), repo_root)
    resolved = {s: tuple(n for n in collected if _selector_matches(n, s)) for s in selectors}
    stale = sorted(s for s, nodes in resolved.items() if not nodes)
    if stale:
        raise StaleProductSelector(f"selectors resolve to no product-test node: {stale}")
    return resolved
