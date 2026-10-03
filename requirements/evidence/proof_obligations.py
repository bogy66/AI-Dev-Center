"""Gate-1 (and Gate-3, for the single Real-System exception) proof
obligation model (KIA-ADC-TEST-ASSURANCE-MODEL-FIX-001 section 3).

Reuses the EXISTING TEST_* Requirement-Test objects
(requirements/verification/tests.rst) and the existing selector_map.py
/ ingest.py Evidence machinery -- no new TEST_*/SYS_REQ/ARC_REQ/etc IDs
are created, and no competing coverage/evidence system is built. This
module only adds a distinct PROOF axis, orthogonal to the existing
FUNCTIONAL axis (`:verification_result:` == IO/NIO/NOT_RUN, computed by
ingest.py from real historical pytest runs).

FUNCTIONAL asks: "did the mapped test(s) pass, the last time they were
actually run?" PROOF asks the stricter question this task exists to
answer honestly: "is that FUNCTIONAL result still mechanically
trustworthy right now?" -- required_tests must still resolve to real,
collectible pytest items (a renamed/deleted test must not let a stale
IO silently keep counting), and, where a TEST_* id's required_tests
include the environment-equivalence-class test modules, the current
(session-live) PASS-VERIFIED high-risk coverage gate
(tests/env_scenarios.py) must also hold. A TEST_* can therefore be
GATE1_FUNCTIONAL=IO while GATE1_PROOF=PARTIAL: functionally green last
time it ran, but not currently backed by everything its own proof
obligation requires.

STATUS is always DERIVED from these inputs -- never hand-set or
hard-coded per TEST_* id.
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass

from .ingest import DEFAULT_STORE_ROOT, REPO_ROOT, TESTS_RST_PATH, ingest_all_runs
from .product_runtime import product_env, product_pytest_command
from .ingest import _ID_RE, _TEST_BLOCK_RE, _VRESULT_RE  # reuse, not reimplementation
from .selector_map import SELECTOR_MAP

_VERIFIES_RE = re.compile(r":verifies:\s*([^\n]+)")
_TITLE_RE = re.compile(r"\.\. test::\s*([^\n]+)")

# TEST_* ids whose required_tests exercise tests/env_scenarios.py's
# equivalence-class catalog -- their proof also depends on that
# catalog's live, session-scoped PASS-VERIFIED high-risk coverage gate
# (see tests/test_env_equivalence_classes.py::test_high_risk_classes_are_all_covered).
_EQUIVALENCE_CLASS_LINKED_OBLIGATIONS = frozenset({"TEST_012"})

# The single established REAL_SYSTEM_ONLY TEST object (selector_map.py's
# own documented, tested convention -- not introduced here).
_REAL_SYSTEM_ONLY_OBLIGATIONS = frozenset({"TEST_033"})


@dataclass(frozen=True)
class ProofObligation:
    obligation_id: str
    gate: str                       # "GATE1" | "GATE3"
    requirement_ids: tuple[str, ...]
    contract: str
    required_strategy: str
    required_tests: tuple[str, ...]
    functional_result: str          # IO | NIO | NOT_RUN (existing axis)
    all_selectors_collectible: bool | None  # None if collectibility was not checked
    status: str                     # PROVEN | PARTIAL | UNPROVEN (derived)


def read_current_verification_results(tests_rst_path: str | None = None) -> dict[str, str]:
    """Read the CURRENT `:verification_result:` value already persisted
    in tests.rst for every TEST_* id, using ingest.py's own block/id/
    result regexes (reuse, not a second parser) -- purely a read, never
    writes anything."""
    path = tests_rst_path or TESTS_RST_PATH
    with open(path, encoding="utf-8") as f:
        text = f.read()
    results: dict[str, str] = {}
    for block in _TEST_BLOCK_RE.findall(text):
        id_match = _ID_RE.search(block)
        vres_match = _VRESULT_RE.search(block)
        if id_match and vres_match:
            results[id_match.group(1)] = vres_match.group(2)
    return results


def read_requirement_ids_and_titles(tests_rst_path: str | None = None) -> dict[str, tuple[tuple[str, ...], str]]:
    """Read each TEST_*'s :verifies: link field and its `.. test::`
    title, from the same tests.rst blocks."""
    path = tests_rst_path or TESTS_RST_PATH
    with open(path, encoding="utf-8") as f:
        text = f.read()
    out: dict[str, tuple[tuple[str, ...], str]] = {}
    for block in _TEST_BLOCK_RE.findall(text):
        id_match = _ID_RE.search(block)
        if not id_match:
            continue
        verifies_match = _VERIFIES_RE.search(block)
        requirement_ids = tuple(
            r.strip() for r in verifies_match.group(1).split(",")
        ) if verifies_match else ()
        title_match = _TITLE_RE.search(block)
        title = title_match.group(1).strip() if title_match else ""
        out[id_match.group(1)] = (requirement_ids, title)
    return out


def check_selectors_collectible(selectors: tuple[str, ...], repo_root: str | None = None) -> bool:
    """Fast, execution-free traceability check: every selector must
    resolve to at least one item pytest can actually COLLECT today
    (--collect-only never runs a test body). A selector that no longer
    resolves to anything (a renamed/deleted test) means the mapping is
    stale, regardless of what a past run's Evidence says."""
    repo_root = repo_root or REPO_ROOT
    file_parts = sorted({s.split("::", 1)[0] for s in selectors})
    # Product tests are collected by the product runtime, never by the
    # interpreter this governance code happens to run in (e.g. the
    # canonical .requirements-venv) -- see product_runtime.py. A missing
    # product runtime raises ProductRuntimeUnavailable (fail closed).
    result = subprocess.run(
        product_pytest_command("--collect-only", "-q", *file_parts, repo_root=repo_root),
        cwd=repo_root, env=product_env(repo_root), capture_output=True, text=True, timeout=120,
    )
    if result.returncode not in (0, 1):  # 1 == collected fine but 0 items matched some filter; still inspect output
        return False
    collected_nodeids = {
        line.strip() for line in result.stdout.splitlines()
        if "::" in line and not line.startswith(" ")
    }
    for selector in selectors:
        if "::" not in selector:
            if not any(nid.startswith(selector + "::") for nid in collected_nodeids):
                return False
            continue
        if not any(
            nid == selector or nid.startswith(selector + "::") or nid.startswith(selector + "[")
            for nid in collected_nodeids
        ):
            return False
    return True


def derive_status(
    *, required_tests: tuple[str, ...], functional_result: str,
    all_selectors_collectible: bool | None, extra_proof_gate_ok: bool | None,
    current_run_backed: bool | None = None,
) -> str:
    """Mechanical STATUS derivation -- the only place a PROOF status is
    decided. Never hard-coded per obligation id.

    `current_run_backed` (KIA-ADC-GATE1-HARNESS-PROOF-FIX-001 section 7):
    None (the default) means "not checked" -- exactly like
    `all_selectors_collectible=None` -- and never blocks PROVEN by
    itself, preserving every existing caller's behavior unchanged.
    False means at least one of this obligation's required_tests was
    deselected/skipped/failed/xfailed/never-collected in the CURRENT
    pytest session (see current_run_completion.py); that is a structural
    completeness gap, exactly like broken selector-collectibility, so it
    forces UNPROVEN rather than merely PARTIAL -- a stale historical PASS
    must never stand in for a selector the current run never actually
    proved."""
    if not required_tests:
        return "UNPROVEN"
    if all_selectors_collectible is False:
        return "UNPROVEN"
    if current_run_backed is False:
        return "UNPROVEN"
    if functional_result in ("NIO", "NOT_RUN"):
        return "UNPROVEN"
    # functional_result == "IO" and (traceability unknown-or-ok) from here.
    if extra_proof_gate_ok is False:
        return "PARTIAL"
    return "PROVEN"


def build_proof_obligations(
    *, check_collectibility: bool = True,
    live_equivalence_class_report: dict | None = None,
    require_current_run_completion: bool = False,
    tests_rst_path: str | None = None, store_root: str | None = None,
    obligation_ids: frozenset[str] | None = None,
) -> tuple[ProofObligation, ...]:
    """Build the full Gate-1(+Gate-3) proof-obligation catalog, one
    obligation per EXISTING TEST_* id in selector_map.SELECTOR_MAP
    (section 9: no new Requirement-Test ids are created).

    `live_equivalence_class_report` should be tests.env_scenarios's own
    coverage_report() dict, passed in by a pytest-session-scoped caller
    (e.g. the Gate-1 proof meta-gate test) that ran AFTER the
    environment-equivalence-class tests actually executed. Left None,
    the equivalence-class-linked extra proof gate is simply not
    evaluated (never fabricated as passing) and those obligations can
    reach at most PROVEN-if-otherwise-eligible only when there is
    nothing to check against -- see `extra_proof_gate_ok` below.

    `require_current_run_completion` (section 7): when True, a GATE1
    obligation whose required_tests were not ALL current-run PASS-backed
    THIS session (current_run_completion.mandatory_current_run_gaps())
    is forced to UNPROVEN regardless of any historical persisted IO --
    closing the masking gap where a deselected/skipped/not-executed
    selector could otherwise silently inherit an old run's PASS. Left
    False (the default, preserving every existing caller's behavior),
    this check is simply not evaluated.

    `obligation_ids`, when given, restricts the catalog to those TEST_*
    ids (same derivation, fewer collectibility runs) -- used by the
    Gate-3 defect-register check, which needs only the owning obligations.
    """
    functional = dict(read_current_verification_results(tests_rst_path))
    fresh = ingest_all_runs(store_root=store_root, tests_rst_path=tests_rst_path, write=False)
    functional.update(fresh.test_ids_updated)

    req_ids_titles = read_requirement_ids_and_titles(tests_rst_path)

    current_run_gaps: frozenset[str] = frozenset()
    if require_current_run_completion:
        from .current_run_completion import mandatory_current_run_gaps
        current_run_gaps = frozenset(mandatory_current_run_gaps())

    high_risk_uncovered: set[str] | None = None
    if live_equivalence_class_report is not None:
        from tests.env_scenarios import all_classes
        high_risk_ids = {c.class_id for c in all_classes() if c.risk_category == "high"}
        high_risk_uncovered = high_risk_ids & set(live_equivalence_class_report.get("uncovered", ()))

    obligations = []
    for obligation_id in sorted(SELECTOR_MAP, key=lambda x: int(x.split("_")[1])):
        if obligation_ids is not None and obligation_id not in obligation_ids:
            continue
        required_tests = tuple(SELECTOR_MAP[obligation_id])
        gate = "GATE3" if obligation_id in _REAL_SYSTEM_ONLY_OBLIGATIONS else "GATE1"
        requirement_ids, title = req_ids_titles.get(obligation_id, ((), ""))
        required_strategy = (
            "REAL_SYSTEM_ACCEPTANCE_TEST" if gate == "GATE3" else "PASS_BACKED_BEHAVIORAL_TEST"
        )

        all_collectible = None
        if check_collectibility:
            all_collectible = check_selectors_collectible(required_tests)

        extra_gate_ok = None
        if obligation_id in _EQUIVALENCE_CLASS_LINKED_OBLIGATIONS and high_risk_uncovered is not None:
            extra_gate_ok = not high_risk_uncovered

        current_run_backed = None
        if require_current_run_completion and gate == "GATE1":
            current_run_backed = obligation_id not in current_run_gaps

        status = derive_status(
            required_tests=required_tests,
            functional_result=functional.get(obligation_id, "NOT_RUN"),
            all_selectors_collectible=all_collectible,
            extra_proof_gate_ok=extra_gate_ok,
            current_run_backed=current_run_backed,
        )

        obligations.append(ProofObligation(
            obligation_id=obligation_id,
            gate=gate,
            requirement_ids=requirement_ids,
            contract=title,
            required_strategy=required_strategy,
            required_tests=required_tests,
            functional_result=functional.get(obligation_id, "NOT_RUN"),
            all_selectors_collectible=all_collectible,
            status=status,
        ))
    return tuple(obligations)


def gate1_proof_summary(obligations: tuple[ProofObligation, ...]) -> dict[str, object]:
    """The single, authoritative Gate-1 proof summary representation
    (KIA-ADC-GATE1-HARNESS-PROOF-FIX-001 section 6): TOTAL/PROVEN/
    PARTIAL/UNPROVEN are always derived together, from the SAME
    Gate-1-filtered obligation list -- never TOTAL from one (possibly
    unfiltered) source and the breakdown from another. Any future report
    script must call this function rather than recomputing any of these
    four numbers independently."""
    gate1 = [o for o in obligations if o.gate == "GATE1"]
    return {
        "total": len(gate1),
        "proven": sorted(o.obligation_id for o in gate1 if o.status == "PROVEN"),
        "partial": sorted(o.obligation_id for o in gate1 if o.status == "PARTIAL"),
        "unproven": sorted(o.obligation_id for o in gate1 if o.status == "UNPROVEN"),
    }


# The single, authoritative expected Gate-1 obligation population,
# derived from the same SELECTOR_MAP / REAL_SYSTEM_ONLY convention
# gate1_proof_summary()/build_proof_obligations() already use. Never
# hand-maintained as a separate count.
GATE1_OBLIGATION_IDS: frozenset[str] = frozenset(SELECTOR_MAP) - _REAL_SYSTEM_ONLY_OBLIGATIONS


class MalformedGate1ProofSummary(ValueError):
    """Raised -- never silently downgraded to NIO/PARTIAL, and never
    allowed to reach IO -- when a summary dict handed to
    overall_gate1_proof_status() fails the fail-closed structural
    accounting invariant TOTAL == PROVEN + PARTIAL + UNPROVEN over a
    unique, disjoint obligation-id population.

    This is exactly the defensive gap KI-B's independent analysis found:
    an ad-hoc report script that computes `total` from the WHOLE
    unfiltered SELECTOR_MAP (33 entries, including the single Gate-3
    TEST_033) while sourcing proven/partial/unproven from this module's
    own Gate-1-filtered gate1_proof_summary() (32 entries) could
    previously slip a self-inconsistent 33/32/0/0 summary through to a
    GATE1_PROOF=IO verdict undetected. That is now structurally
    impossible: overall_gate1_proof_status() validates the invariant
    itself instead of trusting the caller, regardless of how the
    summary dict was produced."""


def _validate_gate1_summary_invariant(summary: dict[str, object]) -> None:
    for key in ("total", "proven", "partial", "unproven"):
        if key not in summary:
            raise MalformedGate1ProofSummary(f"summary is missing required key {key!r}: {summary!r}")
    proven, partial, unproven = summary["proven"], summary["partial"], summary["unproven"]
    for name, value in (("proven", proven), ("partial", partial), ("unproven", unproven)):
        if not isinstance(value, (list, tuple, set, frozenset)):
            raise MalformedGate1ProofSummary(
                f"summary[{name!r}] must be an explicit collection of obligation ids, "
                f"never a bare count or other value: {value!r}"
            )
    proven_ids, partial_ids, unproven_ids = set(proven), set(partial), set(unproven)
    population = proven_ids | partial_ids | unproven_ids
    if len(proven_ids) + len(partial_ids) + len(unproven_ids) != len(population):
        raise MalformedGate1ProofSummary(
            "proven/partial/unproven obligation-id sets are not disjoint: "
            f"proven={sorted(proven_ids)}, partial={sorted(partial_ids)}, unproven={sorted(unproven_ids)}"
        )
    if summary["total"] != len(population):
        raise MalformedGate1ProofSummary(
            f"declared total={summary['total']!r} does not equal the actual "
            f"proven+partial+unproven population ({len(population)}) -- this is "
            "exactly the historical defect shape (an unfiltered total combined "
            "with a Gate-1-filtered proven/partial/unproven breakdown)"
        )


def overall_gate1_proof_status(summary: dict[str, object]) -> str:
    """GATE1_PROOF, distinct from any single obligation's or Requirement's
    GATE1_FUNCTIONAL status (section 3/6): IO only when every mandatory
    Gate-1 proof obligation is PROVEN; NIO if even one is UNPROVEN
    (a functional gap always dominates); otherwise PARTIAL.

    Fail-closed accounting invariant (KIA-ADC-GATE1-HARNESS-PROOF-FIX-001
    section 5): this function VALIDATES, rather than trusts, *summary*
    before deriving anything from it. TOTAL must equal the disjoint
    PROVEN+PARTIAL+UNPROVEN population (else MalformedGate1ProofSummary
    -- never IO), and an IO verdict additionally requires that
    population to be EXACTLY GATE1_OBLIGATION_IDS -- not merely
    "whatever ids happened to be supplied". A malformed or incomplete
    summary can therefore never reach IO."""
    _validate_gate1_summary_invariant(summary)
    proven_ids = set(summary["proven"])
    partial_ids = set(summary["partial"])
    unproven_ids = set(summary["unproven"])
    if unproven_ids:
        return "NIO"
    if partial_ids:
        return "PARTIAL"
    if proven_ids != GATE1_OBLIGATION_IDS:
        raise MalformedGate1ProofSummary(
            f"summary claims a fully PROVEN Gate-1 population of {sorted(proven_ids)}, "
            f"which does not match the expected mandatory Gate-1 obligation set "
            f"{sorted(GATE1_OBLIGATION_IDS)}"
        )
    return "IO"
