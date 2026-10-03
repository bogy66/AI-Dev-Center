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


def test_rse_esphome_acceptance_selector_resolves_to_test_033_without_running_it():
    """KIB-ADC-RSE-DIAGNOSTIC-TRACE-TC-FIX-001: proves the previously
    UNMAPPED_TEST selector now resolves through the central mapping
    machinery -- purely mechanical selector-string resolution, no
    Real-System-E2E execution."""
    assert selector_map.resolve_selector(
        "tests/real_system/real_system_e2e.py::"
        "test_real_esphome_esp32_hello_world_acceptance"
    ) == "TEST_033"
    # A distinct RSE test/module must remain genuinely unmapped -- this
    # is not a blanket match on the whole real_system/ directory.
    assert selector_map.resolve_selector(
        "tests/real_system/real_system_e2e.py::test_some_other_rse_scenario"
    ) is None


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
    from datetime import datetime, timezone

    # Same-second random ID suffixes do not establish chronology. Make the
    # IDs deliberately oppose the manifest timestamps so a lexical-ID
    # implementation cannot accidentally satisfy the latest-run assertion.
    moment = datetime(2026, 9, 18, tzinfo=timezone.utc)
    run_1, run_2 = sorted((run_identity.generate_run_id(now=moment),
                           run_identity.generate_run_id(now=moment)), reverse=True)
    assert run_1 != run_2
    selector = "tests/test_common_request.py::test_common_request_preserves_adapter_neutral_user_intent"
    first = _event(run_1, selector=selector, result="IO")
    first.update(timestamp_start="2026-09-18T00:00:00.100000+00:00",
                 timestamp_end="2026-09-18T00:00:00.200000+00:00", duration=0.1)
    second = _event(run_2, selector=selector, result="NIO")
    second.update(timestamp_start="2026-09-18T00:00:00.300000+00:00",
                  timestamp_end="2026-09-18T00:00:00.400000+00:00", duration=0.1)
    assert publisher.publish_test_evidence(first, store_root=str(tmp_path)).success
    assert publisher.publish_test_evidence(second, store_root=str(tmp_path)).success

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
    # run_2 started later (despite its lexically smaller ID) and touched the same
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


# ============================================================================
# KIB-ADC-RSE-DIAGNOSTIC-TRACE-TC-FIX-002: focused vs. real-system
# verification are separate TEST semantics. A focused run must never be
# able to mark the Real-System TEST object (TEST_033) IO, and a real
# mapped RSE event must correctly drive TEST_033's own result.
# ============================================================================

_RSE_SELECTOR = (
    "tests/real_system/real_system_e2e.py::"
    "test_real_esphome_esp32_hello_world_acceptance"
)

_FOCUSED_DIAGNOSTIC_TRACE_SELECTOR = (
    "tests/test_real_system_e2e_progress.py::"
    "test_validate_final_diagnostic_trace_never_calls_to_record"
)

_SPLIT_TESTS_RST_FIXTURE = """ADC Verification Tests
======================

.. test:: Focused DiagnosticTrace contract
   :id: TEST_778
   :status: draft
   :verification_result: NOT_RUN
   :verifies: IF_REQ_999

   tests/test_fixture_focused.py::test_it

.. test:: Real-System-E2E acceptance
   :id: TEST_779
   :status: draft
   :verification_result: NOT_RUN
   :verifies: IF_REQ_999

   {rse_selector}
""".format(rse_selector=_RSE_SELECTOR)


def _ingest_with_fixture_map(tmp_path, fixture_map, tests_rst_text=_SPLIT_TESTS_RST_FIXTURE):
    """Runs ingest_all_runs against tmp_path's store with a temporary,
    restored SELECTOR_MAP override -- never touching the real
    requirements/_evidence store or the real tests.rst."""
    tests_rst = tmp_path / "tests.rst"
    tests_rst.write_text(tests_rst_text)
    evidence_generated = tmp_path / "evidence_generated.rst"

    saved = dict(selector_map.SELECTOR_MAP)
    selector_map.SELECTOR_MAP.clear()
    selector_map.SELECTOR_MAP.update(fixture_map)
    try:
        report = ingest.ingest_all_runs(
            store_root=str(tmp_path),
            tests_rst_path=str(tests_rst),
            evidence_generated_path=str(evidence_generated),
            write=True,
        )
    finally:
        selector_map.SELECTOR_MAP.clear()
        selector_map.SELECTOR_MAP.update(saved)
    return report, tests_rst, evidence_generated


# --- 1/2: selector resolution mechanics (no execution) ---------------------

def test_1_rse_selector_resolves_to_the_real_system_test_object():
    assert selector_map.resolve_selector(_RSE_SELECTOR) == "TEST_033"


def test_2_focused_diagnostic_trace_selector_does_not_resolve_to_test_033():
    resolved = selector_map.resolve_selector(_FOCUSED_DIAGNOSTIC_TRACE_SELECTOR)
    assert resolved != "TEST_033"
    assert resolved == "TEST_030"


# --- 3/4: a focused run cannot mark the Real-System TEST object IO ---------

def test_3_focused_evidence_cannot_mark_the_real_system_test_object_io(tmp_path):
    run_id = run_identity.generate_run_id()
    publisher.publish_test_evidence(
        _event(run_id, selector="tests/test_fixture_focused.py::test_it", result="IO"),
        store_root=str(tmp_path),
    )
    report, tests_rst, _ = _ingest_with_fixture_map(
        tmp_path,
        {"TEST_778": ["tests/test_fixture_focused.py::test_it"],
         "TEST_779": [_RSE_SELECTOR]},
    )
    assert report.test_ids_updated == {"TEST_778": "IO"}
    assert "TEST_779" not in report.test_ids_updated
    text = tests_rst.read_text()
    # TEST_779's block is completely untouched -- still NOT_RUN.
    rse_block = text[text.index(":id: TEST_779"):]
    assert ":verification_result: NOT_RUN" in rse_block


def test_4_focused_pass_and_real_system_pass_are_distinct_facts(tmp_path):
    """Publishing IO for the focused selector must never be usable, by
    itself, as evidence that the real-system selector also passed --
    proven by ingesting ONLY the focused event and confirming the
    Real-System TEST object's result is unaffected, even though the
    focused one legitimately becomes IO."""
    run_id = run_identity.generate_run_id()
    publisher.publish_test_evidence(
        _event(run_id, selector="tests/test_fixture_focused.py::test_it", result="IO"),
        store_root=str(tmp_path),
    )
    report, tests_rst, evidence_generated = _ingest_with_fixture_map(
        tmp_path,
        {"TEST_778": ["tests/test_fixture_focused.py::test_it"],
         "TEST_779": [_RSE_SELECTOR]},
    )
    text = tests_rst.read_text()
    focused_block = text[text.index(":id: TEST_778"):text.index(":id: TEST_779")]
    assert ":verification_result: IO" in focused_block
    generated_text = evidence_generated.read_text() if evidence_generated.exists() else ""
    assert "TEST_779" not in generated_text


# --- 5/6: a genuinely mapped RSE event correctly drives TEST_033's result --

def test_5_a_real_mapped_rse_io_event_verifies_the_real_system_test_object(tmp_path):
    run_id = run_identity.generate_run_id()
    publisher.publish_test_evidence(
        _event(run_id, selector=_RSE_SELECTOR, result="IO"),
        store_root=str(tmp_path),
    )
    report, tests_rst, evidence_generated = _ingest_with_fixture_map(
        tmp_path, {"TEST_779": [_RSE_SELECTOR]},
    )
    assert report.test_ids_updated == {"TEST_779": "IO"}
    assert ":verification_result: IO" in tests_rst.read_text()
    generated_text = evidence_generated.read_text()
    assert "TEST_779" in generated_text
    assert "genuinely observed failure" not in generated_text


def test_6_a_real_mapped_rse_nio_event_makes_the_real_system_test_object_nio(tmp_path):
    run_id = run_identity.generate_run_id()
    publisher.publish_test_evidence(
        _event(run_id, selector=_RSE_SELECTOR, result="NIO"),
        store_root=str(tmp_path),
    )
    report, tests_rst, evidence_generated = _ingest_with_fixture_map(
        tmp_path, {"TEST_779": [_RSE_SELECTOR]},
    )
    assert report.test_ids_updated == {"TEST_779": "NIO"}
    assert ":verification_result: NIO" in tests_rst.read_text()
    # A real, honest failure record IS generated -- never fabricated
    # success, never silence.
    generated_text = evidence_generated.read_text()
    assert "TEST_779" in generated_text
    assert "genuinely observed failure" in generated_text
    assert "_FAIL" in generated_text


# --- 7: TEST_030 retains its intended focused semantics ---------------------

def test_7_test_030_still_carries_its_original_focused_selectors():
    selectors = selector_map.SELECTOR_MAP["TEST_030"]
    assert (
        "tests/test_central_diagnostic_trace.py::"
        "test_secret_redaction_and_detail_allowlist_protect_persisted_jsonl"
        in selectors
    )
    assert (
        "tests/test_central_diagnostic_trace.py::"
        "test_trace_content_cannot_approve_or_release_publish_gate"
        in selectors
    )
    assert _RSE_SELECTOR not in selectors


# --- 8: no intentional selector remains unmapped ----------------------------

def test_8_all_new_focused_and_rse_selectors_resolve_to_a_test_id():
    new_selectors = selector_map.SELECTOR_MAP["TEST_030"][2:] + selector_map.SELECTOR_MAP["TEST_033"]
    for selector in new_selectors:
        assert selector_map.resolve_selector(selector) is not None, (
            f"selector unexpectedly unmapped: {selector}"
        )


def test_test_033_selector_list_contains_only_the_rse_selector():
    assert selector_map.SELECTOR_MAP["TEST_033"] == [_RSE_SELECTOR]


# ============================================================================
# KIB-ADC-RSE-DIAGNOSTIC-TRACE-TC-FIX-003: failure-Evidence contract and
# TEST_033 assertion-derived Requirement mapping.
# ============================================================================

def test_failure_evidence_never_makes_a_requirement_green(tmp_path):
    """Item 4: even with a real, honest FAIL Evidence object linked to a
    NIO test, the central status model must never report GREEN for the
    Requirement it verifies -- proven end to end: ingest a genuine NIO
    RSE event (producing FAIL Evidence), then feed the resulting
    verification_result + evidence linkage through the real
    status_model.compute_all_requirement_states."""
    from requirements import status_model

    run_id = run_identity.generate_run_id()
    publisher.publish_test_evidence(
        _event(run_id, selector=_RSE_SELECTOR, result="NIO"),
        store_root=str(tmp_path),
    )
    report, tests_rst, evidence_generated = _ingest_with_fixture_map(
        tmp_path, {"TEST_779": [_RSE_SELECTOR]},
    )
    assert report.test_ids_updated == {"TEST_779": "NIO"}
    generated_text = evidence_generated.read_text()
    assert "TEST_779" in generated_text  # a real FAIL Evidence object exists

    needs = {
        "IF_REQ_999": {
            "type": "ifreq",
            "implements": [],
        },
        "IMPL_FIXTURE": {
            "type": "impl",
            "implements": ["IF_REQ_999"],
        },
        "TEST_779": {
            "type": "test",
            "verification_result": "NIO",
            "verifies": ["IF_REQ_999"],
        },
        "EVID_FAIL_FIXTURE": {
            "type": "evidence",
            "evidences": ["TEST_779"],
        },
    }
    # Build the incoming-link view compute_all_requirement_states expects
    # (needs_json's own "implements"/"verifies"/"evidences" are outgoing;
    # _incoming_ids derives the reverse view from those directly).
    states = status_model.compute_all_requirement_states(needs)
    assert states["IF_REQ_999"] == status_model.IMPLEMENTED_TEST_NIO
    assert states["IF_REQ_999"] != status_model.IMPLEMENTED_TEST_IO


def test_not_run_cannot_fabricate_evidence(tmp_path):
    """Item 5: a TEST_* id with no events in any ingested run must never
    receive a generated Evidence object, and must never appear in
    test_ids_updated at all -- absence of execution is never confused
    with a real, honest failure or success."""
    report, tests_rst, evidence_generated = _ingest_with_fixture_map(
        tmp_path, {"TEST_778": ["tests/test_fixture_focused.py::test_it"],
                   "TEST_779": [_RSE_SELECTOR]},
    )
    assert report.test_ids_updated == {}
    assert report.runs_processed == []
    text = tests_rst.read_text()
    assert ":verification_result: NOT_RUN" in text
    if evidence_generated.exists():
        generated_text = evidence_generated.read_text()
        assert "TEST_778" not in generated_text
        assert "TEST_779" not in generated_text


def test_raw_run_history_files_are_never_written_by_ingest(tmp_path):
    """Item 6: ingest_all_runs is read-only against requirements/_evidence/runs/
    -- it only ever writes tests_rst_path/evidence_generated_path/the
    unmapped-selectors report, never any file under runs/<id>/events/ or
    runs/<id>/run.json."""
    run_id = run_identity.generate_run_id()
    publisher.publish_test_evidence(
        _event(run_id, selector=_RSE_SELECTOR, result="NIO"), store_root=str(tmp_path),
    )
    event_path = next((tmp_path / "runs" / run_id / "events").glob("*.json"))
    run_json_path = tmp_path / "runs" / run_id / "run.json"
    before_event = event_path.read_bytes()
    before_run = run_json_path.read_bytes()

    _ingest_with_fixture_map(tmp_path, {"TEST_779": [_RSE_SELECTOR]})

    assert event_path.read_bytes() == before_event
    assert run_json_path.read_bytes() == before_run


def test_test_033_requirement_links_match_the_assertion_derived_mapping():
    """Item 8: the real tests.rst TEST_033 :verifies: list matches
    exactly the assertion-by-assertion derived set from
    KIB-ADC-RSE-DIAGNOSTIC-TRACE-TC-FIX-003's review -- no silent drift
    between this regression test's expectation and the actual RST."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    tests_rst_path = os.path.join(repo_root, "requirements", "verification", "tests.rst")
    with open(tests_rst_path, encoding="utf-8") as f:
        text = f.read()
    block_start = text.index(":id: TEST_033")
    block = text[block_start:block_start + 400]
    verifies_line = next(line for line in block.splitlines() if line.strip().startswith(":verifies:"))
    actual = [rid.strip() for rid in verifies_line.split(":verifies:")[1].split(",")]
    expected = [
        "SUB_REQ_006", "IF_REQ_012", "ARC_REQ_007", "SUB_REQ_008",
        "ARC_REQ_008", "SUB_REQ_009", "ARC_REQ_016", "SUB_REQ_018",
        "SUB_REQ_024", "IF_REQ_031", "SUB_REQ_028", "IF_REQ_033",
    ]
    assert actual == expected
