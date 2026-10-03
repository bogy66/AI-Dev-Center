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
        "--adc-evidence-run-id", action="store", default=None,
        help="Use a caller-assigned run id (validated against the Evidence Contract).",
    )
    group.addoption(
        "--adc-evidence-producer", action="store", default="ADC",
        help="Producer identity recorded on every published event (default: ADC).",
    )
    group.addoption(
        "--adc-evidence-store", action="store", default=None,
        help=(
            "Override the Evidence store root (default: requirements/_evidence). "
            "PRODUCTION FORMAL RUN vs. ISOLATED/CUSTOM EVIDENCE RUN: leaving this "
            "unset (the real default store) is what makes a --adc-evidence run a "
            "genuine formal Requirements-updating run -- publish, finalize, ingest, "
            "TEST_*/EVID_* update, strict Sphinx build, and Requirement status/"
            "dashboard/trace-graph refresh all happen automatically. Passing a "
            "custom path here makes this an ISOLATED/diagnostic Evidence run "
            "instead: Evidence is still published/finalized into that custom "
            "store, but the automatic Requirements-refresh pipeline is never "
            "attempted (it always targets the real store together with the real "
            "requirements/ tree) and is reported as "
            "'formal_finalization: NOT_APPLICABLE' in the terminal summary, never "
            "as a completed or failed production formal run."
        ),
    )


def pytest_configure(config):
    if not config.getoption("--adc-evidence"):
        return
    requested_run_id = config.getoption("--adc-evidence-run-id")
    if requested_run_id:
        from .run_identity import is_valid_run_id

        if not is_valid_run_id(requested_run_id):
            raise pytest.UsageError("--adc-evidence-run-id is not a valid ADC Evidence run id")
    config._adc_evidence_run_id = requested_run_id or generate_run_id()
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
    config._adc_formal_finalization = None
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
    from .formal_finalization import FormalFinalizationResult, finalize_formal_test_run, is_default_store

    if not result.success:
        config._adc_evidence_publish_failures.append(("<run finalize>", result.errors))
        # No real, finalized run exists for this run_id -- the mandatory
        # post-test pipeline (ingest/Sphinx refresh) must never run
        # against an unfinalized run, and a formal invocation whose own
        # Evidence run could not even be finalized is never a fully
        # successful formal run (CLAUDE-ADC-FORMAL-TEST-AUTO-
        # REQUIREMENTS-UPDATE-002). Still reported in the terminal
        # summary below (run_finalize_ok=False), never silently skipped.
        config._adc_formal_finalization = FormalFinalizationResult(
            run_id=config._adc_evidence_run_id, run_finalize_ok=False,
        )
        _fail_closed(session)
        return

    if not is_default_store(config._adc_evidence_store):
        # An explicit, non-default --adc-evidence-store was requested --
        # a scoped/diagnostic Evidence run, never a genuine formal
        # Requirements-updating run against the real project state. The
        # automatic ingest/Sphinx-refresh pipeline always targets the
        # real default store together with the real requirements/ source
        # tree; running it here would mix a scratch store with the real
        # generated output (see formal_finalization.py and
        # ingest_all_runs's own docstring). Never attempted, never
        # treated as a pipeline failure -- reported as the explicit
        # NOT_APPLICABLE state in the terminal summary, never as OK.
        config._adc_formal_finalization = FormalFinalizationResult(
            run_id=config._adc_evidence_run_id, run_finalize_ok=True,
            skipped_custom_store=True,
        )
        return

    # Central formal-run finalization: exactly once per session, always
    # AFTER the Evidence run itself was successfully finalized above.
    # Orchestrates (never duplicates) the existing central ingest and
    # Requirements/Sphinx build -- see formal_finalization.py.
    formal_result = finalize_formal_test_run(config._adc_evidence_run_id)
    config._adc_formal_finalization = formal_result
    if not formal_result.success:
        # pytest's own test assertions may all have passed -- that must
        # never be reported as a fully successful FORMAL run when the
        # mandatory Requirements finalization pipeline itself failed.
        _fail_closed(session)


def _fail_closed(session):
    """Force a non-success process exit status without masking a worse
    pre-existing one (e.g. real test failures already produced exit code
    1; an internal/usage error already produced 3/4)."""
    import pytest as _pytest

    if session.exitstatus in (0,):
        session.exitstatus = _pytest.ExitCode.TESTS_FAILED


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

    formal_result = getattr(config, "_adc_formal_finalization", None)
    if formal_result is None:
        return
    terminalreporter.write_sep("-", "ADC Formal Requirements Finalization")
    terminalreporter.write_line(f"run_id: {formal_result.run_id}")
    terminalreporter.write_line(f"evidence: {'OK' if config._adc_evidence_published else 'FAIL'}")
    # Never print a false OK for a stage that never ran because an
    # earlier one already failed (CLAUDE-ADC-FORMAL-TEST-AUTO-
    # REQUIREMENTS-UPDATE-002: "Do not print false OK states when a
    # stage was not executed due to an earlier failure").
    terminalreporter.write_line(f"run_finalize: {'OK' if formal_result.run_finalize_ok else 'FAIL'}")
    if formal_result.skipped_custom_store:
        from .formal_finalization import CUSTOM_STORE_SKIP_REASON, NOT_APPLICABLE

        terminalreporter.write_line(f"ingest: {NOT_APPLICABLE}")
        terminalreporter.write_line(f"requirements_build: {NOT_APPLICABLE}")
        terminalreporter.write_line(f"requirements_status_refresh: {NOT_APPLICABLE}")
        terminalreporter.write_line(f"trace_graph_refresh: {NOT_APPLICABLE}")
        # Never "OK" here: Requirements finalization was intentionally
        # never attempted for a custom-store run, and reporting "OK"
        # would misrepresent an isolated/diagnostic Evidence run as a
        # completed production formal run (CLAUDE-ADC-FORMAL-TEST-AUTO-
        # REQUIREMENTS-UPDATE-003). Never "FAIL" either -- this is not
        # an error condition.
        terminalreporter.write_line(f"formal_finalization: {NOT_APPLICABLE}")
        terminalreporter.write_line(f"reason: {CUSTOM_STORE_SKIP_REASON}")
        return
    ingest_state = "OK" if formal_result.ingest_ok else ("FAIL" if formal_result.run_finalize_ok else "SKIPPED")
    terminalreporter.write_line(f"ingest: {ingest_state}")
    terminalreporter.write_line(f"tests_updated: {len(formal_result.test_ids_updated)}")
    terminalreporter.write_line(f"evidence_objects: {len(formal_result.evidence_objects_generated)}")
    terminalreporter.write_line(f"unmapped_selectors: {len(formal_result.unmapped_selectors)}")
    build_state = "OK" if formal_result.build_ok else ("FAIL" if formal_result.ingest_ok else "SKIPPED")
    terminalreporter.write_line(f"requirements_build: {build_state}")
    status_state = "OK" if formal_result.status_output_ok else ("FAIL" if formal_result.build_ok else "SKIPPED")
    terminalreporter.write_line(f"requirements_status_refresh: {status_state}")
    trace_state = "OK" if formal_result.trace_graph_ok else ("FAIL" if formal_result.build_ok else "SKIPPED")
    terminalreporter.write_line(f"trace_graph_refresh: {trace_state}")
    terminalreporter.write_line(f"formal_finalization: {'OK' if formal_result.success else 'FAIL'}")
    if formal_result.ingest_error:
        terminalreporter.write_line(f"  ingest_error: {formal_result.ingest_error}")
    if formal_result.build_error:
        terminalreporter.write_line(f"  build_error: {formal_result.build_error}")
    if formal_result.missing_outputs:
        terminalreporter.write_line(f"  missing_outputs: {formal_result.missing_outputs}")
