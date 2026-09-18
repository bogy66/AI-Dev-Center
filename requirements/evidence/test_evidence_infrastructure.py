"""Regression tests for the ADC Evidence infrastructure itself
(CLAUDE-ADC-TESTBED-EVIDENCE-INFRASTRUCTURE-001, section T).

These test the infrastructure (contract, publisher, ingest, selector map)
in isolation, against scratch stores under tmp_path -- never against the
real requirements/_evidence store, and never by running ADC's own product
tests through the plugin (that demonstration is done separately, once,
against a handful of already-mapped real tests).
"""
import json
import os
import subprocess

import pytest

from requirements.evidence import ingest, provenance, publisher, run_identity, selector_map
from requirements.evidence.adapters.rse_adapter import RSEEvidenceRun


def _event(run_id, selector="tests/test_x.py::test_y", result="IO", commit="abc123", dirty=False):
    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "producer": "ADC",
        "test_selector": selector,
        "mapped_test_id": None,
        "result": result,
        "timestamp_start": "2026-09-18T00:00:00+00:00",
        "timestamp_end": "2026-09-18T00:00:01+00:00",
        "duration": 1.0,
        "command_or_procedure": "pytest " + selector,
        "exit_code": None,
        "repository_identity": {"commit": commit, "dirty": dirty},
        "artifact_identity": None,
        "environment": {"os": "Linux", "platform": "Linux-x", "testbed": "pytest", "profile": None},
        "tool_versions": {"python": "3.12.3"},
        "evidence_payload": {},
        "raw_output_reference": None,
    }


# 1. successful IO publication -----------------------------------------------

def test_successful_io_publication(tmp_path):
    run_id = run_identity.generate_run_id()
    result = publisher.publish_test_evidence(_event(run_id, result="IO"), store_root=str(tmp_path))
    assert result.success
    with open(result.event_path) as f:
        stored = json.load(f)
    assert stored["result"] == "IO"


# 2. NIO publication -----------------------------------------------------------

def test_nio_publication(tmp_path):
    run_id = run_identity.generate_run_id()
    result = publisher.publish_test_evidence(_event(run_id, result="NIO"), store_root=str(tmp_path))
    assert result.success
    with open(result.event_path) as f:
        stored = json.load(f)
    assert stored["result"] == "NIO"


# 3. unique run IDs -------------------------------------------------------------

def test_run_ids_are_unique_even_within_the_same_second():
    from datetime import datetime, timezone
    same_instant = datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)
    ids = {run_identity.generate_run_id(now=same_instant) for _ in range(50)}
    assert len(ids) == 50
    assert all(run_identity.is_valid_run_id(rid) for rid in ids)


# 4. multiple test events in one run --------------------------------------------

def test_multiple_events_share_one_run_and_are_individually_recorded(tmp_path):
    run_id = run_identity.generate_run_id()
    r1 = publisher.publish_test_evidence(
        _event(run_id, selector="tests/test_x.py::test_a", result="IO"), store_root=str(tmp_path),
    )
    r2 = publisher.publish_test_evidence(
        _event(run_id, selector="tests/test_x.py::test_b", result="NIO"), store_root=str(tmp_path),
    )
    assert r1.success and r2.success
    assert r1.event_id != r2.event_id
    with open(os.path.join(tmp_path, "runs", run_id, "run.json")) as f:
        manifest = json.load(f)
    assert manifest["event_count"] == 2
    assert set(manifest["event_ids"]) == {r1.event_id, r2.event_id}


# 5. malformed Evidence rejected -------------------------------------------------

def test_unknown_result_value_is_rejected_not_coerced_to_io(tmp_path):
    run_id = run_identity.generate_run_id()
    bad = _event(run_id, result="MAYBE")
    result = publisher.publish_test_evidence(bad, store_root=str(tmp_path))
    assert not result.success
    assert not os.path.isdir(os.path.join(tmp_path, "runs", run_id, "events")) or not os.listdir(
        os.path.join(tmp_path, "runs", run_id, "events")
    )


def test_missing_required_field_is_rejected(tmp_path):
    run_id = run_identity.generate_run_id()
    bad = _event(run_id)
    del bad["repository_identity"]
    result = publisher.publish_test_evidence(bad, store_root=str(tmp_path))
    assert not result.success
    assert result.errors


# 6. unknown test selector remains unmapped --------------------------------------

def test_unknown_selector_resolves_to_none_never_guessed():
    assert selector_map.resolve_selector("tests/test_totally_unrelated_file.py::test_nothing") is None


def test_known_selector_resolves_to_exactly_one_test_id():
    assert selector_map.resolve_selector(
        "tests/test_common_request.py::test_common_request_preserves_adapter_neutral_user_intent"
    ) == "TEST_001"


def test_selector_map_has_no_ambiguous_overlaps():
    """Every concrete selector string in the table must resolve to exactly
    one TEST_* id -- if two entries both matched the same real node id,
    ingest's aggregation would silently pick whichever happened to be
    dict-iteration-first, corrupting traceability."""
    seen = {}
    for test_id, selectors in selector_map.SELECTOR_MAP.items():
        for sel in selectors:
            probe = sel if "::" in sel else sel + "::__probe__"
            matches = selector_map.resolve_selector_all(probe)
            assert len(matches) <= 1, (
                f"selector {sel!r} (probed as {probe!r}) matches multiple TEST_* "
                f"ids: {matches}"
            )
            if sel in seen:
                assert seen[sel] == test_id, f"selector {sel!r} listed under both {seen[sel]} and {test_id}"
            seen[sel] = test_id


# 7. publisher failure cannot produce GREEN --------------------------------------

def test_publish_failure_leaves_no_trace_for_ingest_to_pick_up(tmp_path):
    run_id = run_identity.generate_run_id()
    bad = _event(run_id, selector="tests/test_common_request.py::test_common_request_preserves_adapter_neutral_user_intent", result="NOT_A_REAL_RESULT")
    result = publisher.publish_test_evidence(bad, store_root=str(tmp_path))
    assert not result.success

    report = ingest.ingest_all_runs(
        store_root=str(tmp_path),
        tests_rst_path=str(tmp_path / "unused_tests.rst"),
        evidence_generated_path=str(tmp_path / "unused_evidence.rst"),
        write=False,
    )
    assert report.test_ids_updated == {}
    assert report.events_processed == 0


# 8. dirty worktree provenance recorded ------------------------------------------

def test_dirty_worktree_is_recorded_as_dirty_not_pretended_clean(tmp_path):
    repo = tmp_path / "scratch_repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "a.txt").write_text("one")
    subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repo, check=True)

    identity_clean = provenance.repository_identity(str(repo))
    assert identity_clean["dirty"] is False

    (repo / "a.txt").write_text("two, uncommitted")
    identity_dirty = provenance.repository_identity(str(repo))
    assert identity_dirty["dirty"] is True
    assert identity_dirty["commit"] == identity_clean["commit"]


# 9. repeated runs preserved independently ---------------------------------------

def test_repeated_runs_are_preserved_independently_not_overwritten(tmp_path):
    run_1 = run_identity.generate_run_id()
    run_2 = run_identity.generate_run_id()
    assert run_1 != run_2

    publisher.publish_test_evidence(
        _event(run_1, selector="tests/test_common_request.py::test_common_request_preserves_adapter_neutral_user_intent", result="IO"),
        store_root=str(tmp_path),
    )
    publisher.publish_test_evidence(
        _event(run_2, selector="tests/test_common_request.py::test_common_request_preserves_adapter_neutral_user_intent", result="NIO"),
        store_root=str(tmp_path),
    )

    runs_dir = os.path.join(tmp_path, "runs")
    assert set(os.listdir(runs_dir)) == {run_1, run_2}
    with open(os.path.join(runs_dir, run_1, "run.json")) as f:
        assert json.load(f)["run_id"] == run_1
    with open(os.path.join(runs_dir, run_2, "run.json")) as f:
        assert json.load(f)["run_id"] == run_2

    report = ingest.ingest_all_runs(
        store_root=str(tmp_path),
        tests_rst_path=str(tmp_path / "unused_tests.rst"),
        evidence_generated_path=str(tmp_path / "unused_evidence.rst"),
        write=False,
    )
    # run_2 started later (lexically greater run_id) and touched the same
    # test_id with a different result -- it must win as "currently
    # applicable", proving history is not merged/averaged across runs.
    assert report.test_ids_updated["TEST_001"] == "NIO"


# 10. Evidence ingest updates the central Sphinx-facing status source correctly --

_TESTS_RST_FIXTURE = """ADC Verification Tests
======================

.. test:: Something
   :id: TEST_777
   :status: draft
   :verification_result: NOT_RUN
   :verifies: IF_REQ_999

   tests/test_fixture_target.py::test_it
"""


def test_ingest_updates_verification_result_in_place_for_mapped_tests(tmp_path, monkeypatch):
    run_id = run_identity.generate_run_id()
    publisher.publish_test_evidence(
        _event(run_id, selector="tests/test_fixture_target.py::test_it", result="IO"),
        store_root=str(tmp_path),
    )

    tests_rst = tmp_path / "tests.rst"
    tests_rst.write_text(_TESTS_RST_FIXTURE)
    evidence_generated = tmp_path / "evidence_generated.rst"

    monkeypatch.setitem(selector_map.SELECTOR_MAP, "TEST_777", ["tests/test_fixture_target.py::test_it"])
    try:
        report = ingest.ingest_all_runs(
            store_root=str(tmp_path),
            tests_rst_path=str(tests_rst),
            evidence_generated_path=str(evidence_generated),
            write=True,
        )
    finally:
        del selector_map.SELECTOR_MAP["TEST_777"]

    assert report.test_ids_updated == {"TEST_777": "IO"}
    updated_text = tests_rst.read_text()
    assert ":verification_result: IO" in updated_text
    assert ":id: TEST_777" in updated_text  # untouched elsewhere
    assert evidence_generated.exists()
    generated_text = evidence_generated.read_text()
    assert "TEST_777" in generated_text
    assert "Never hand-edited" in generated_text


def test_ingest_leaves_tests_rst_untouched_for_test_ids_with_no_new_data(tmp_path):
    tests_rst = tmp_path / "tests.rst"
    tests_rst.write_text(_TESTS_RST_FIXTURE)
    original = tests_rst.read_text()
    evidence_generated = tmp_path / "evidence_generated.rst"

    report = ingest.ingest_all_runs(
        store_root=str(tmp_path),
        tests_rst_path=str(tests_rst),
        evidence_generated_path=str(evidence_generated),
        write=True,
    )
    assert report.runs_processed == []
    assert tests_rst.read_text() == original


def test_run_manifest_conforms_to_run_schema_and_finalizes_exactly_once(tmp_path):
    run_id = run_identity.generate_run_id()
    publisher.publish_test_evidence(_event(run_id), store_root=str(tmp_path))

    first = publisher.finalize_run(run_id, store_root=str(tmp_path))
    assert first.success
    with open(os.path.join(tmp_path, "runs", run_id, "run.json")) as f:
        manifest_after_first = json.load(f)
    assert manifest_after_first["run_status"] == "completed"
    assert manifest_after_first["completed_at"] is not None

    second = publisher.finalize_run(run_id, store_root=str(tmp_path), run_status="aborted")
    assert second.success
    with open(os.path.join(tmp_path, "runs", run_id, "run.json")) as f:
        manifest_after_second = json.load(f)
    # Already completed -- a later finalize call must not regress it.
    assert manifest_after_second["run_status"] == "completed"
    assert manifest_after_second["completed_at"] == manifest_after_first["completed_at"]


def test_finalize_run_without_any_published_event_fails_closed(tmp_path):
    run_id = run_identity.generate_run_id()
    result = publisher.finalize_run(run_id, store_root=str(tmp_path))
    assert not result.success


# RSE adapter -- standalone, never exercised by actually running RSE ------------

def test_rse_adapter_disabled_mode_never_touches_the_filesystem(tmp_path):
    before = list(tmp_path.iterdir())
    with RSEEvidenceRun(enabled=False, store_root=str(tmp_path)) as run:
        result = run.record_phase("phase_x", "IO", timestamp_start="a", timestamp_end="b")
    assert result is None
    assert list(tmp_path.iterdir()) == before


def test_rse_adapter_enabled_mode_publishes_phases_and_finalizes(tmp_path):
    with RSEEvidenceRun(enabled=True, store_root=str(tmp_path)) as run:
        run.record_phase(
            "council", "IO",
            timestamp_start="2026-09-18T00:00:00+00:00",
            timestamp_end="2026-09-18T00:01:00+00:00",
        )
        run.record_phase(
            "esphome_build", "NIO",
            timestamp_start="2026-09-18T00:01:00+00:00",
            timestamp_end="2026-09-18T00:02:00+00:00",
            failure_type="build_timeout",
        )
    assert run.publish_failures == []
    with open(os.path.join(tmp_path, "runs", run.run_id, "run.json")) as f:
        manifest = json.load(f)
    assert manifest["event_count"] == 2
    assert manifest["run_status"] == "completed"


def test_rse_adapter_marks_run_aborted_when_the_context_exits_via_exception(tmp_path):
    with pytest.raises(RuntimeError):
        with RSEEvidenceRun(enabled=True, store_root=str(tmp_path)) as run:
            run.record_phase(
                "council", "IO",
                timestamp_start="2026-09-18T00:00:00+00:00",
                timestamp_end="2026-09-18T00:01:00+00:00",
            )
            raise RuntimeError("simulated RSE failure")
    with open(os.path.join(tmp_path, "runs", run.run_id, "run.json")) as f:
        manifest = json.load(f)
    assert manifest["run_status"] == "aborted"


def test_rse_adapter_never_raises_on_a_bad_result_value(tmp_path):
    with RSEEvidenceRun(enabled=True, store_root=str(tmp_path)) as run:
        result = run.record_phase(
            "council", "NOT_A_REAL_RESULT",
            timestamp_start="2026-09-18T00:00:00+00:00",
            timestamp_end="2026-09-18T00:01:00+00:00",
        )
    assert not result.success
    assert run.publish_failures
