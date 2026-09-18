"""Central ADC Evidence ingest.

Reads every published Evidence event from the store, resolves each
event's `test_selector` to a TEST_* id via selector_map.py, determines
each TEST_*'s currently-applicable verification result, and updates the
Sphinx-Needs-facing representation:

  - requirements/verification/tests.rst   -- `:verification_result:`
    field updated IN PLACE for TEST_* ids this ingest has data for.
    TEST_* ids this ingest has no data for are left completely untouched
    (their existing, previously-established value is preserved -- see
    module docstring rationale in ingest_all_runs()).

  - requirements/verification/evidence_generated.rst -- fully
    regenerated from the complete run history in the store (never
    touching the separate, hand-authored requirements/verification/
    evidence.rst, which stays the historical record of the pre-
    infrastructure mapping task's own manually-run pytest batches).

Sphinx itself never executes tests and never talks to the Evidence
store directly -- it only ever renders whatever these two .rst files
already say (CLAUDE-ADC-TESTBED-EVIDENCE-INFRASTRUCTURE-001, section Q).
"""
import glob
import json
import os
import re
from dataclasses import dataclass, field

from .contract import validate_event
from .selector_map import resolve_selector

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_STORE_ROOT = os.path.join(REPO_ROOT, "requirements", "_evidence")
TESTS_RST_PATH = os.path.join(REPO_ROOT, "requirements", "verification", "tests.rst")
EVIDENCE_GENERATED_RST_PATH = os.path.join(
    REPO_ROOT, "requirements", "verification", "evidence_generated.rst",
)

_RESULT_PRIORITY = {"IO": 0, "NOT_RUN": 1, "NIO": 2}  # higher = worse, wins aggregation


@dataclass
class IngestReport:
    runs_processed: list = field(default_factory=list)
    events_processed: int = 0
    malformed_events_skipped: list = field(default_factory=list)
    unmapped_selectors: list = field(default_factory=list)
    test_ids_updated: dict = field(default_factory=dict)  # test_id -> new result
    evidence_objects_generated: list = field(default_factory=list)


def _run_started_at(store_root, run_id):
    """Read the run's own recorded started_at for chronological ordering.

    Lexical sort of run_id strings is NOT a safe proxy for this: two runs
    created within the same wall-clock second share an identical
    second-resolution timestamp prefix, so their relative order would
    otherwise be decided by their random uniqueness suffix -- which can
    silently pick the WRONG run as "most recent" for aggregation. Missing
    or unreadable run.json sorts last (defensive; an unreadable manifest
    should not be trusted to precede real, readable runs)."""
    run_json_path = os.path.join(store_root, "runs", run_id, "run.json")
    try:
        with open(run_json_path, encoding="utf-8") as f:
            manifest = json.load(f)
        return manifest["started_at"]
    except (OSError, json.JSONDecodeError, KeyError):
        return "9999"  # sorts after any real ISO-8601 timestamp


def _discover_runs(store_root):
    runs_dir = os.path.join(store_root, "runs")
    if not os.path.isdir(runs_dir):
        return []
    run_ids = [d for d in os.listdir(runs_dir) if os.path.isdir(os.path.join(runs_dir, d))]
    return sorted(run_ids, key=lambda rid: (_run_started_at(store_root, rid), rid))


def _load_run_events(store_root, run_id):
    events_dir = os.path.join(store_root, "runs", run_id, "events")
    events = []
    for path in sorted(glob.glob(os.path.join(events_dir, "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                event = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            events.append(("MALFORMED", path, str(exc)))
            continue
        errors = validate_event(event)
        if errors:
            events.append(("MALFORMED", path, "; ".join(errors)))
            continue
        events.append(("OK", path, event))
    return events


def ingest_all_runs(store_root=None, tests_rst_path=None, evidence_generated_path=None,
                     write=True):
    """Process every run in the Evidence store and update the Sphinx-Needs
    representation. Returns an IngestReport.

    `write=False` computes the report without touching any file (used by
    tests that only want to check resolution/aggregation logic).

    Policy for "currently applicable" per TEST_*: the most recent run
    that exercised at least one of that TEST_*'s mapped selectors decides
    its result -- computed only from that run's own events (never merged
    across runs), and aggregated worst-of (NIO > NOT_RUN > IO) across
    every selector belonging to that TEST_* exercised in that run, since
    a TEST_* Requirement-verification object is only genuinely IO when
    ALL of the selectors tests.rst cites for it passed. A TEST_* id with
    no data in any ingested run is left exactly as tests.rst already has
    it -- ingest never invents or downgrades a result it has no evidence
    for (see ingest's own module docstring)."""
    store_root = store_root or DEFAULT_STORE_ROOT
    tests_rst_path = tests_rst_path or TESTS_RST_PATH
    evidence_generated_path = evidence_generated_path or EVIDENCE_GENERATED_RST_PATH

    report = IngestReport()
    run_ids = _discover_runs(store_root)

    # per test_id: (run_id, aggregated_result) from the most recent run
    # that had at least one event resolving to that test_id.
    latest_by_test = {}
    # per run_id: {test_id: aggregated_result} for evidence generation,
    # restricted to test_ids that reached IO in that run.
    run_io_test_ids = {}

    for run_id in run_ids:
        report.runs_processed.append(run_id)
        per_run_results = {}  # test_id -> worst result seen in this run
        for status, path, payload in _load_run_events(store_root, run_id):
            if status == "MALFORMED":
                report.malformed_events_skipped.append({"path": path, "error": payload})
                continue
            report.events_processed += 1
            event = payload
            test_id = resolve_selector(event["test_selector"])
            if test_id is None:
                report.unmapped_selectors.append(event["test_selector"])
                continue
            result = event["result"]
            current = per_run_results.get(test_id)
            if current is None or _RESULT_PRIORITY[result] > _RESULT_PRIORITY[current]:
                per_run_results[test_id] = result

        for test_id, result in per_run_results.items():
            latest_by_test[test_id] = (run_id, result)

        io_ids = sorted(tid for tid, res in per_run_results.items() if res == "IO")
        if io_ids:
            run_io_test_ids[run_id] = io_ids

    report.test_ids_updated = {tid: res for tid, (rid, res) in latest_by_test.items()}
    # de-duplicate unmapped selectors for a compact report, order-preserving
    seen = []
    for sel in report.unmapped_selectors:
        if sel not in seen:
            seen.append(sel)
    report.unmapped_selectors = seen

    if write:
        _update_tests_rst(tests_rst_path, report.test_ids_updated)
        generated_ids = _write_evidence_generated_rst(
            evidence_generated_path, run_io_test_ids, store_root,
        )
        report.evidence_objects_generated = generated_ids
        _write_unmapped_report(report.unmapped_selectors, store_root)

    return report


_TEST_BLOCK_RE = re.compile(
    r"(\.\. test::[^\n]*\n(?:[ \t]+:[^\n]*\n)+)", re.MULTILINE,
)
_ID_RE = re.compile(r":id:\s*(TEST_\d+)")
_VRESULT_RE = re.compile(r"(:verification_result:\s*)(\S+)")


def _update_tests_rst(path, test_ids_updated):
    if not test_ids_updated or not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        text = f.read()

    def _replace_block(match):
        block = match.group(1)
        id_match = _ID_RE.search(block)
        if not id_match:
            return block
        test_id = id_match.group(1)
        if test_id not in test_ids_updated:
            return block
        new_result = test_ids_updated[test_id]
        if _VRESULT_RE.search(block):
            return _VRESULT_RE.sub(rf"\g<1>{new_result}", block, count=1)
        return block.rstrip("\n") + f"\n   :verification_result: {new_result}\n"

    new_text = _TEST_BLOCK_RE.sub(_replace_block, text)
    if new_text != text:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_text)


def _sanitize_evid_id(run_id):
    token = run_id.replace("ADC-RUN-", "").replace("-", "_").upper()
    return f"EVID_GEN_{token}"


def _write_evidence_generated_rst(path, run_io_test_ids, store_root):
    generated_ids = []
    lines = [
        "ADC Generated Evidence",
        "=======================",
        "",
        "Machine-generated from requirements/_evidence/runs/ by "
        "requirements/evidence/ingest.py. Never hand-edited -- re-running "
        "ingest regenerates this file from the complete run history in "
        "the store. Historical, hand-authored Evidence from the "
        "preceding mapping task remains in verification/evidence.rst, "
        "untouched by this file.",
        "",
    ]
    for run_id, test_ids in run_io_test_ids.items():
        run_json_path = os.path.join(store_root, "runs", run_id, "run.json")
        repo_identity = {}
        producer = "ADC"
        if os.path.exists(run_json_path):
            with open(run_json_path, encoding="utf-8") as f:
                manifest = json.load(f)
            repo_identity = manifest.get("repository_identity", {})
            producer = manifest.get("producer", "ADC")
        evid_id = _sanitize_evid_id(run_id)
        generated_ids.append(evid_id)
        lines.append(f".. evidence:: Generated Evidence for {run_id}")
        lines.append(f"   :id: {evid_id}")
        lines.append("   :status: draft")
        lines.append(f"   :evidences: {', '.join(test_ids)}")
        lines.append("")
        lines.append(
            f"   Producer: {producer}. Repository: commit "
            f"{repo_identity.get('commit', 'unknown')}"
            f"{' (dirty worktree)' if repo_identity.get('dirty') else ' (clean worktree)'}"
            f". Ingested from ``requirements/_evidence/runs/{run_id}/``."
        )
        lines.append("")

    content = "\n".join(lines) + "\n"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return generated_ids


def _write_unmapped_report(unmapped_selectors, store_root):
    path = os.path.join(store_root, "unmapped_selectors.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"unmapped_selectors": unmapped_selectors}, f, indent=2, sort_keys=True)
        f.write("\n")
