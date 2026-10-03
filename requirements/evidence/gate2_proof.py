"""Authoritative mechanical Gate-2 proof
(CLAUDE-ADC-RSE033-GATE2-MECHANICAL-PROOF-GOVERNANCE-FIX-002).

    python -m requirements.evidence.gate2_proof verify

1. loads the 19-obligation catalog (gate2_obligations.py) and the
   central selector map (gate2_selector_map.py) and validates both;
2. collects the selectors' files (--collect-only) to resolve every
   selector to real nodeids -- a selector resolving to nothing is stale;
3. executes exactly the resolved mandatory nodes in one pytest run;
4. reads that CURRENT run's per-node outcomes (gate2_pytest_report.py);
5. derives each obligation's state and prints the accounting;
6. evaluates the Gate-2-owned Gate-3 defect regressions
   (gate3_defect_register.py) against this same run;
7. exits 0 only when every obligation is PROVEN and every Gate-2-owned
   defect regression is CLOSED (1 otherwise, 2 on a malformed map/catalog
   or a run that produced no report).

States are derived, never set:
  PROVEN   -- no stale selector, >=1 mandatory node, every mandatory node
              PASSED in this run;
  PARTIAL  -- no stale selector and no failure, some nodes PASSED, but
              others are missing / skipped / xfailed / deselected;
  UNPROVEN -- anything else (stale selector, zero nodes, any FAILED node,
              or no PASSED node at all).
The catalog's own status stays NOT_YET_EXECUTED (gate2_obligations.
assert_none_marked_proven); a proof exists only as the result of a run.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass

from .current_run_completion import _selector_matches  # reuse Gate-1 selector semantics
from .gate2_obligations import GATE2_OBLIGATIONS, assert_none_marked_proven
from .gate2_selector_map import GATE2_SELECTOR_MAP
from .gate3_defect_register import CLOSED, GATE2, evaluate_register, register_lines
from .gate2_pytest_report import REPORT_SCHEMA
from .ingest import REPO_ROOT
from .product_runtime import product_env, product_pytest_command

PROVEN, PARTIAL, UNPROVEN = "PROVEN", "PARTIAL", "UNPROVEN"
PASSED = "PASSED"
MISSING = "MISSING"


class MalformedGate2SelectorMap(ValueError):
    """The central map does not describe exactly the current catalog."""


@dataclass(frozen=True)
class Gate2ObligationProof:
    obligation_id: str
    status: str
    selectors: tuple[str, ...]
    stale_selectors: tuple[str, ...]
    node_outcomes: tuple[tuple[str, str], ...]  # (nodeid, PASSED|FAILED|SKIPPED|XFAIL|DESELECTED|MISSING)

    @property
    def gaps(self) -> tuple[tuple[str, str], ...]:
        return tuple(item for item in self.node_outcomes if item[1] != PASSED)


def validate_gate2_selector_map(selector_map=None, obligations=GATE2_OBLIGATIONS) -> None:
    selector_map = GATE2_SELECTOR_MAP if selector_map is None else selector_map
    catalog_ids = [o.obligation_id for o in obligations]
    if len(catalog_ids) != len(set(catalog_ids)):
        raise MalformedGate2SelectorMap(f"duplicate obligation ids in catalog: {catalog_ids}")
    unknown = sorted(set(selector_map) - set(catalog_ids))
    unmapped = sorted(set(catalog_ids) - set(selector_map))
    if unknown or unmapped:
        raise MalformedGate2SelectorMap(f"unknown obligations {unknown}; unmapped obligations {unmapped}")
    for obligation_id, selectors in selector_map.items():
        if not isinstance(selectors, tuple) or not selectors:
            raise MalformedGate2SelectorMap(f"{obligation_id}: mandatory selector scope must be a non-empty tuple")
        if len(set(selectors)) != len(selectors):
            raise MalformedGate2SelectorMap(f"{obligation_id}: duplicate selector")
        for selector in selectors:
            path = selector.split("::", 1)[0] if isinstance(selector, str) else ""
            if (not path.endswith(".py") or not path.startswith(("tests/", "requirements/"))
                    or any(ch.isspace() for ch in selector)):
                raise MalformedGate2SelectorMap(f"{obligation_id}: malformed selector {selector!r}")


def expand_selector(selector: str, collected) -> tuple[str, ...]:
    return tuple(sorted(n for n in collected if _selector_matches(n, selector)))


def evaluate_obligation(obligation_id, selectors, collected, outcomes) -> Gate2ObligationProof:
    stale, nodes = [], set()
    for selector in selectors:
        matched = expand_selector(selector, collected)
        if not matched:
            stale.append(selector)
        nodes.update(matched)
    node_outcomes = tuple((n, outcomes.get(n, MISSING)) for n in sorted(nodes))
    values = {outcome for _, outcome in node_outcomes}
    if stale or not node_outcomes or "FAILED" in values or PASSED not in values:
        status = UNPROVEN
    elif values == {PASSED}:
        status = PROVEN
    else:
        status = PARTIAL
    return Gate2ObligationProof(obligation_id, status, tuple(selectors), tuple(stale), node_outcomes)


def evaluate_gate2(collected, outcomes, selector_map=None, obligations=GATE2_OBLIGATIONS):
    """Pure evaluation of one current run: `collected` is every nodeid
    the selector files collect; `outcomes` the run's nodeid -> outcome."""
    selector_map = GATE2_SELECTOR_MAP if selector_map is None else selector_map
    validate_gate2_selector_map(selector_map, obligations)
    assert_none_marked_proven(obligations)
    collected = frozenset(collected)
    return tuple(
        evaluate_obligation(o.obligation_id, selector_map[o.obligation_id], collected, outcomes)
        for o in obligations
    )


def gate2_summary(proofs) -> dict[str, object]:
    summary = {
        "total": len(proofs),
        "proven": sorted(p.obligation_id for p in proofs if p.status == PROVEN),
        "partial": sorted(p.obligation_id for p in proofs if p.status == PARTIAL),
        "unproven": sorted(p.obligation_id for p in proofs if p.status == UNPROVEN),
    }
    summary["result"] = "IO" if proofs and len(summary["proven"]) == len(proofs) else "NIO"
    return summary


def mandatory_nodes(collected, selector_map=None) -> tuple[str, ...]:
    selector_map = GATE2_SELECTOR_MAP if selector_map is None else selector_map
    nodes = set()
    for selectors in selector_map.values():
        for selector in selectors:
            nodes.update(expand_selector(selector, collected))
    return tuple(sorted(nodes))


def _run_pytest(args, report_path, repo_root):
    # Always the product runtime (product_runtime.py), whichever
    # interpreter runs this governance code.
    env = product_env(repo_root)
    command = product_pytest_command(
        *args, "-p", "no:cacheprovider", "-p", "requirements.evidence.gate2_pytest_report",
        f"--adc-gate2-report={report_path}", repo_root=repo_root,
    )
    completed = subprocess.run(command, cwd=repo_root, env=env, capture_output=True, text=True)
    if not os.path.exists(report_path):
        raise RuntimeError(f"pytest produced no Gate-2 report (exit {completed.returncode}):\n{completed.stdout[-4000:]}\n{completed.stderr[-4000:]}")
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)
    if report.get("schema") != REPORT_SCHEMA:
        raise RuntimeError(f"unexpected Gate-2 report schema: {report.get('schema')!r}")
    return report, completed


def collect_selector_scope(repo_root=None, selector_map=None) -> tuple[str, ...]:
    """Every nodeid the mapped files collect today (execution-free)."""
    repo_root = repo_root or REPO_ROOT
    selector_map = GATE2_SELECTOR_MAP if selector_map is None else selector_map
    files = sorted({s.split("::", 1)[0] for sels in selector_map.values() for s in sels})
    with tempfile.TemporaryDirectory(prefix="adc-gate2-") as tmp:
        report, _ = _run_pytest(["--collect-only", "-q", *files], os.path.join(tmp, "collect.json"), repo_root)
    return tuple(report["collected"])


def verify(repo_root=None, out=sys.stdout) -> int:
    repo_root = repo_root or REPO_ROOT
    try:
        validate_gate2_selector_map()
        assert_none_marked_proven()
        collected = collect_selector_scope(repo_root)
        nodes = mandatory_nodes(collected)
        if not nodes:
            raise RuntimeError("Gate-2 mandatory scope resolved to zero nodes")
        with tempfile.TemporaryDirectory(prefix="adc-gate2-") as tmp:
            report, completed = _run_pytest(["-q", "-rs", *nodes], os.path.join(tmp, "run.json"), repo_root)
    except (MalformedGate2SelectorMap, AssertionError, RuntimeError) as error:
        print(f"GATE2_RESULT=NIO\nGATE2_ERROR={error}", file=out)
        return 2
    outcomes = report["outcomes"]
    proofs = evaluate_gate2(collected, outcomes)
    summary = gate2_summary(proofs)
    ran = {n: outcomes.get(n, MISSING) for n in nodes}
    counts = {k: sum(1 for v in ran.values() if v == k) for k in ("PASSED", "FAILED", "SKIPPED", "XFAIL", "DESELECTED", MISSING)}
    tail = [line for line in completed.stdout.strip().splitlines() if line.strip()][-1:]
    print(f"GATE2_PYTEST_EXIT={completed.returncode} {' '.join(tail)}", file=out)
    print(f"GATE2_SCOPE_COLLECTED={len(collected)}", file=out)
    print(f"GATE2_MANDATORY_NODES={len(nodes)}", file=out)
    print(f"GATE2_NOT_MANDATORY_IN_SCOPE={len(set(collected) - set(nodes))}", file=out)
    for key, value in counts.items():
        print(f"GATE2_MANDATORY_{key}={value}", file=out)
    for proof in proofs:
        passed = sum(1 for _, o in proof.node_outcomes if o == PASSED)
        print(f"{proof.obligation_id}={proof.status} nodes={len(proof.node_outcomes)} passed={passed}", file=out)
        for selector in proof.stale_selectors:
            print(f"  STALE {selector}", file=out)
        for nodeid, outcome in proof.gaps:
            print(f"  {outcome} {nodeid}", file=out)
    print(f"GATE2_TOTAL={summary['total']}", file=out)
    print(f"GATE2_PROVEN={len(summary['proven'])}", file=out)
    print(f"GATE2_PARTIAL={len(summary['partial'])}", file=out)
    print(f"GATE2_UNPROVEN={len(summary['unproven'])}", file=out)
    print(f"GATE2_RESULT={summary['result']}", file=out)
    # Gate-3 defects this gate owns must be contained by THIS run
    # (gate3_defect_register.py): registered nodes mandatory here, passed
    # here, and their owning obligation proven here.
    register = evaluate_register(
        GATE2, collected, outcomes, {p.obligation_id: p.status for p in proofs},
    )
    for line in register_lines(register):
        print(line, file=out)
    register_closed = bool(register) and all(r.state == CLOSED for r in register)
    print(f"GATE2_OWNED_GATE3_DEFECTS={'CLOSED' if register_closed else 'OPEN'}", file=out)
    return 0 if summary["result"] == "IO" and completed.returncode == 0 and register_closed else 1


def main(argv=None):
    parser = argparse.ArgumentParser(prog="adc-gate2-proof")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("verify", help="Run and mechanically evaluate the authoritative Gate-2 scope")
    parser.parse_args(argv)
    return verify()


if __name__ == "__main__":
    sys.exit(main())
