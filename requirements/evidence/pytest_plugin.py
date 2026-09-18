"""Pytest plugin that publishes ADC Evidence events as part of a formal
test invocation -- opt-in only, via the `--adc-evidence` flag.

Registered explicitly on the command line:

    pytest -p requirements.evidence.pytest_plugin --adc-evidence tests/...

Without `--adc-evidence`, every hook below returns immediately and does
nothing -- an ordinary developer `pytest tests/...` run is completely
unaffected: no Evidence Contract import cost beyond hook registration, no
filesystem writes, no dependency on Sphinx (CLAUDE-ADC-TESTBED-EVIDENCE-
INFRASTRUCTURE-001, section M).

Publish failures are recorded but deliberately never raised into the test
run itself -- a testbed's own test results must never be lost merely
because Evidence publication failed (section L); the terminal summary at
session end reports any publish failures explicitly instead.
"""
import os
import sys
from datetime import datetime, timezone

import pytest

from .provenance import python_tool_versions, repository_identity, runtime_environment
from .publisher import finalize_run, publish_test_evidence
from .run_identity import generate_run_id

_RESULT_MAP = {
    "passed": "IO",
    "failed": "NIO",
    "error": "NIO",
}

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def pytest_addoption(parser):
    group = parser.getgroup("adc-evidence")
    group.addoption(
        "--adc-evidence", action="store_true", default=False,
        help="Publish ADC Evidence events for this run via the central Evidence Contract.",
    )
    group.addoption(
        "--adc-evidence-producer", action="store", default="ADC",
        help="Producer identity recorded on every published event (default: ADC).",
    )
    group.addoption(
        "--adc-evidence-store", action="store", default=None,
        help="Override the Evidence store root (default: requirements/_evidence).",
    )


def pytest_configure(config):
    if not config.getoption("--adc-evidence"):
        return
    config._adc_evidence_run_id = generate_run_id()
    config._adc_evidence_producer = config.getoption("--adc-evidence-producer")
    config._adc_evidence_store = config.getoption("--adc-evidence-store")
    config._adc_evidence_repo = repository_identity(_REPO_ROOT)
    config._adc_evidence_items = {}
    config._adc_evidence_publish_failures = []
    config._adc_evidence_published = 0
    config._adc_evidence_unmapped = []

    config._adc_evidence_environment = runtime_environment("pytest")
    config._adc_evidence_tool_versions = python_tool_versions({"pytest": pytest.__version__})
    config._adc_evidence_command = " ".join(["pytest"] + sys.argv[1:])


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Hookwrapper: let pytest build its own TestReport first (so
    passed/failed/skipped/xfail classification, including markers and
    exception handling, is exactly pytest's own -- never hand-reclassified
    here), then read that finished report back to accumulate per-test
    Evidence."""
    outcome = yield
    if not item.config.getoption("--adc-evidence"):
        return
    report = outcome.get_result()
    config = item.config
    nodeid = item.nodeid
    bucket = config._adc_evidence_items.setdefault(
        nodeid, {"start": None, "duration": 0.0, "outcome": None, "longrepr": None},
    )
    if bucket["start"] is None:
        bucket["start"] = datetime.now(timezone.utc)
    bucket["duration"] += getattr(report, "duration", 0.0) or 0.0

    if report.when == "call":
        if report.passed:
            bucket["outcome"] = "passed"
        elif report.failed:
            bucket["outcome"] = "failed"
            bucket["longrepr"] = str(report.longrepr)[:500]
        elif report.skipped:
            bucket["outcome"] = "skipped"
    elif report.when == "setup":
        if report.failed:
            bucket["outcome"] = "error"
            bucket["longrepr"] = str(report.longrepr)[:500]
        elif report.skipped:
            bucket["outcome"] = "skipped"
    elif report.when == "teardown":
        if report.failed and bucket["outcome"] in (None, "passed"):
            bucket["outcome"] = "failed"
            bucket["longrepr"] = str(report.longrepr)[:500]
        bucket["end"] = datetime.now(timezone.utc)
        _publish_item(config, nodeid, bucket)


def _publish_item(config, nodeid, bucket):
    from .selector_map import resolve_selector

    outcome = bucket["outcome"]
    if outcome is None:
        outcome = "skipped"
    result = _RESULT_MAP.get(outcome, "NOT_RUN")

    start = bucket["start"] or datetime.now(timezone.utc)
    end = bucket.get("end") or datetime.now(timezone.utc)

    mapped_test_id = resolve_selector(nodeid)
    if mapped_test_id is None:
        config._adc_evidence_unmapped.append(nodeid)

    event = {
        "schema_version": "1.0",
        "run_id": config._adc_evidence_run_id,
        "producer": config._adc_evidence_producer,
        "test_selector": nodeid,
        "mapped_test_id": None,  # resolved centrally at ingest, never by the producer
        "result": result,
        "timestamp_start": start.isoformat(),
        "timestamp_end": end.isoformat(),
        "duration": round(bucket["duration"], 6),
        "command_or_procedure": config._adc_evidence_command,
        "exit_code": None,
        "repository_identity": config._adc_evidence_repo,
        "artifact_identity": None,
        "environment": config._adc_evidence_environment,
        "tool_versions": config._adc_evidence_tool_versions,
        "evidence_payload": {
            "outcome": outcome,
            "longrepr": bucket.get("longrepr"),
        },
        "raw_output_reference": None,
    }

    publish_result = publish_test_evidence(event, store_root=config._adc_evidence_store)
    if publish_result.success:
        config._adc_evidence_published += 1
    else:
        config._adc_evidence_publish_failures.append((nodeid, publish_result.errors))


def pytest_sessionfinish(session, exitstatus):
    config = session.config
    if not config.getoption("--adc-evidence"):
        return
    if config._adc_evidence_published == 0:
        # No event was ever durably published (e.g. every item's own
        # publish call failed, or zero items reached teardown) -- there
        # is no real run.json to finalize; finalize_run() would only
        # report a confusing "no run.json" failure for a run that never
        # meaningfully started.
        return
    # pytest exit codes: 0 all passed, 1 tests failed, 5 no tests
    # collected -- the session still ran to a genuine, reportable
    # conclusion. 2 interrupted, 3 internal error, 4 usage error -- the
    # run did not complete as intended.
    run_status = "completed" if exitstatus in (0, 1, 5) else "aborted"
    result = finalize_run(
        config._adc_evidence_run_id,
        store_root=config._adc_evidence_store,
        run_status=run_status,
    )
    if not result.success:
        config._adc_evidence_publish_failures.append(("<run finalize>", result.errors))


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    if not config.getoption("--adc-evidence"):
        return
    terminalreporter.write_sep("-", "ADC Evidence")
    terminalreporter.write_line(f"run_id: {config._adc_evidence_run_id}")
    terminalreporter.write_line(f"events published: {config._adc_evidence_published}")
    if config._adc_evidence_unmapped:
        terminalreporter.write_line(
            f"UNMAPPED_TEST selectors ({len(config._adc_evidence_unmapped)}): "
            + ", ".join(config._adc_evidence_unmapped[:10])
            + (" ..." if len(config._adc_evidence_unmapped) > 10 else "")
        )
    if config._adc_evidence_publish_failures:
        terminalreporter.write_line(
            f"PUBLISH FAILURES ({len(config._adc_evidence_publish_failures)}) -- "
            "these test results were NOT recorded as Evidence:"
        )
        for nodeid, errors in config._adc_evidence_publish_failures:
            terminalreporter.write_line(f"  {nodeid}: {errors}")
