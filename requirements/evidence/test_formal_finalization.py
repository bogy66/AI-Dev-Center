"""Regression tests for the central formal-run finalization pipeline
(CLAUDE-ADC-FORMAL-TEST-AUTO-REQUIREMENTS-UPDATE-002).

Three layers, cheapest first:

  1. Unit tests against `finalize_formal_test_run()` directly, with
     scratch stores/paths and injected `build_argv` -- proves the
     orchestration's own fail-closed logic without needing a real
     Sphinx build for every case.
  2. Unit tests against `pytest_plugin.pytest_sessionfinish` directly
     (a stub session/config, monkeypatched `finalize_run`/
     `finalize_formal_test_run`) -- proves the exact wiring/ordering/
     exit-status contract without spawning a subprocess pytest.
  3. A handful of real, end-to-end tests via the `pytester` fixture,
     running the REAL plugin and (for the full-pipeline cases) a REAL
     `.requirements-venv/bin/sphinx-build` against a disposable COPY of
     the `requirements/` source tree -- never the real, committed one.
     Default-store tests relocate writable defaults to that private tree,
     without a CLI custom-store override or mocked finalization. Synthetic
     Evidence never enters the operator-owned store.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from requirements.evidence import run_identity
from requirements.evidence.formal_finalization import (
    FormalFinalizationResult, finalize_formal_test_run,
)
from requirements.evidence.publisher import finalize_run, publish_test_evidence

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
REQUIREMENTS_SRC = os.path.join(REPO_ROOT, "requirements")
SPHINX_BUILD = os.path.join(REPO_ROOT, ".requirements-venv", "bin", "sphinx-build")


def _event(run_id, selector="tests/test_x.py::test_y", result="IO"):
    # Real (not fixed/artificial) timestamps: ingest's "most recent run
    # wins" policy (requirements/evidence/ingest.py) sorts runs by their
    # own recorded started_at, so a synthetic event competing against
    # SEEDED real run history (see test_full_real_pipeline_mapped_test_
    # io_then_nio) must genuinely be the most recent to correctly win.
    now = datetime.now(timezone.utc)
    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "producer": "ADC",
        "test_selector": selector,
        "mapped_test_id": None,
        "result": result,
        "timestamp_start": now.isoformat(),
        "timestamp_end": now.isoformat(),
        "duration": 1.0,
        "command_or_procedure": "pytest " + selector,
        "exit_code": None,
        "repository_identity": {"commit": "abc123", "dirty": False},
        "artifact_identity": None,
        "environment": {"os": "Linux", "platform": "Linux-x", "testbed": "pytest", "profile": None},
        "tool_versions": {"python": "3.12.3"},
        "evidence_payload": {},
        "raw_output_reference": None,
    }


def _publish_and_finalize(store_root, run_id, selector, result):
    assert publish_test_evidence(_event(run_id, selector, result), store_root=str(store_root)).success
    assert finalize_run(run_id, store_root=str(store_root)).success


def _write_dummy_outputs(html_root, languages=("en",)):
    for lang in languages:
        base = os.path.join(html_root, lang)
        os.makedirs(os.path.join(base, "dashboard"), exist_ok=True)
        os.makedirs(os.path.join(base, "_images"), exist_ok=True)
        for rel in ("needs.json", "requirement_status.json",
                    os.path.join("dashboard", "overview.html"),
                    os.path.join("dashboard", "requirement_status.html"),
                    os.path.join("dashboard", "traceability.html")):
            with open(os.path.join(base, rel), "w", encoding="utf-8") as f:
                f.write("{}")
        with open(os.path.join(base, "_images", "needflow-1.svg"), "w", encoding="utf-8") as f:
            f.write("<svg></svg>")


# ============================================================================
# 1. Unit tests: finalize_formal_test_run() fail-closed behavior
# ============================================================================

def test_ingest_exception_fails_closed(tmp_path):
    run_id = run_identity.generate_run_id()
    _publish_and_finalize(tmp_path, run_id, "tests/unmapped.py::test_z", "IO")
    unwritable_target = tmp_path / "evidence_generated_is_actually_a_directory"
    unwritable_target.mkdir()
    result = finalize_formal_test_run(
        run_id, store_root=str(tmp_path),
        tests_rst_path=str(tmp_path / "tests.rst"),
        evidence_generated_path=str(unwritable_target),
        build_argv=["true"],
    )
    assert result.run_finalize_ok is True  # only ever called after a real finalize_run() succeeded
    assert result.ingest_ok is False
    assert result.ingest_error is not None
    assert result.build_ok is False  # never reached
    assert result.success is False


def test_malformed_evidence_fails_closed(tmp_path):
    run_id = run_identity.generate_run_id()
    events_dir = tmp_path / "runs" / run_id / "events"
    events_dir.mkdir(parents=True)
    (events_dir / "EVT-0001.json").write_text("{not valid json")
    (tmp_path / "runs" / run_id / "run.json").write_text(json.dumps({
        "schema_version": "1.0", "run_id": run_id, "producer": "ADC",
        "started_at": "2026-09-20T00:00:00+00:00",
        "repository_identity": {"commit": "abc", "dirty": False},
        "environment": {"os": "Linux", "platform": "Linux-x", "testbed": "pytest", "profile": None},
        "tool_versions": {}, "command_or_procedure": "pytest", "run_status": "completed",
        "completed_at": "2026-09-20T00:00:02+00:00", "event_ids": ["EVT-0001"], "event_count": 1,
    }))
    result = finalize_formal_test_run(
        run_id, store_root=str(tmp_path),
        tests_rst_path=str(tmp_path / "tests.rst"),
        evidence_generated_path=str(tmp_path / "evidence_generated.rst"),
        build_argv=["true"],
    )
    assert result.ingest_ok is False
    assert "malformed" in result.ingest_error.lower()
    assert result.success is False


def test_build_failure_fails_closed(tmp_path):
    run_id = run_identity.generate_run_id()
    _publish_and_finalize(tmp_path, run_id, "tests/unmapped.py::test_z", "IO")
    result = finalize_formal_test_run(
        run_id, store_root=str(tmp_path),
        tests_rst_path=str(tmp_path / "tests.rst"),
        evidence_generated_path=str(tmp_path / "evidence_generated.rst"),
        build_argv=[sys.executable, "-c", "import sys; sys.exit(1)"],
        html_root=str(tmp_path / "html"), languages=("en",),
    )
    assert result.ingest_ok is True
    assert result.build_ok is False
    assert result.build_error is not None
    assert result.success is False


def test_build_invocation_error_fails_closed(tmp_path):
    run_id = run_identity.generate_run_id()
    _publish_and_finalize(tmp_path, run_id, "tests/unmapped.py::test_z", "IO")
    result = finalize_formal_test_run(
        run_id, store_root=str(tmp_path),
        tests_rst_path=str(tmp_path / "tests.rst"),
        evidence_generated_path=str(tmp_path / "evidence_generated.rst"),
        build_argv=[str(tmp_path / "does-not-exist-binary")],
        html_root=str(tmp_path / "html"), languages=("en",),
    )
    assert result.ingest_ok is True
    assert result.build_ok is False
    assert "could not invoke" in result.build_error
    assert result.success is False


def test_missing_generated_outputs_fails_closed(tmp_path):
    run_id = run_identity.generate_run_id()
    _publish_and_finalize(tmp_path, run_id, "tests/unmapped.py::test_z", "IO")
    result = finalize_formal_test_run(
        run_id, store_root=str(tmp_path),
        tests_rst_path=str(tmp_path / "tests.rst"),
        evidence_generated_path=str(tmp_path / "evidence_generated.rst"),
        build_argv=["true"],  # "succeeds" but writes nothing
        html_root=str(tmp_path / "html"), languages=("en",),
    )
    assert result.build_ok is True
    assert result.status_output_ok is False
    assert result.trace_graph_ok is False
    assert result.missing_outputs
    assert result.success is False


def test_successful_stub_pipeline_reports_success(tmp_path):
    run_id = run_identity.generate_run_id()
    _publish_and_finalize(tmp_path, run_id, "tests/unmapped.py::test_z", "IO")
    html_root = str(tmp_path / "html")
    _write_dummy_outputs(html_root)
    result = finalize_formal_test_run(
        run_id, store_root=str(tmp_path),
        tests_rst_path=str(tmp_path / "tests.rst"),
        evidence_generated_path=str(tmp_path / "evidence_generated.rst"),
        build_argv=["true"], html_root=html_root, languages=("en",),
    )
    assert result.success is True
    assert result.unmapped_selectors == ["tests/unmapped.py::test_z"]
    assert result.test_ids_updated == {}  # unmapped -- never invented


def test_deterministic_rerun_does_not_duplicate_or_corrupt(tmp_path):
    run_id = run_identity.generate_run_id()
    _publish_and_finalize(tmp_path, run_id, "tests/unmapped.py::test_z", "IO")
    html_root = str(tmp_path / "html")
    _write_dummy_outputs(html_root)
    kwargs = dict(
        store_root=str(tmp_path),
        tests_rst_path=str(tmp_path / "tests.rst"),
        evidence_generated_path=str(tmp_path / "evidence_generated.rst"),
        build_argv=["true"], html_root=html_root, languages=("en",),
    )
    first = finalize_formal_test_run(run_id, **kwargs)
    second = finalize_formal_test_run(run_id, **kwargs)
    assert first.success and second.success
    assert first.evidence_objects_generated == second.evidence_objects_generated
    assert first.test_ids_updated == second.test_ids_updated


def test_manual_cli_ingest_still_works(tmp_path, capsys, monkeypatch):
    """The manual `adc-evidence ingest --store <path>` command only ever
    exposes `--store` (never rst-path overrides) -- exactly the
    real-target-defaulting behavior the automatic formal pipeline
    deliberately never exercises with anything but the real store (see
    ingest_all_runs's own docstring). Proven here against monkeypatched
    scratch default rst paths so this regression test itself never
    writes into the real, committed requirements/verification/*.rst."""
    from requirements.evidence import cli, ingest as ingest_module

    monkeypatch.setattr(ingest_module, "TESTS_RST_PATH", str(tmp_path / "tests.rst"))
    monkeypatch.setattr(ingest_module, "EVIDENCE_GENERATED_RST_PATH", str(tmp_path / "evidence_generated.rst"))

    run_id = run_identity.generate_run_id()
    _publish_and_finalize(tmp_path, run_id, "tests/unmapped.py::test_z", "IO")
    rc = cli.main(["ingest", "--store", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "runs_processed=1" in out


# ============================================================================
# 2. Unit tests: pytest_plugin.pytest_sessionfinish wiring
# ============================================================================

def _fake_config(published=1, store=None, evidence_run_id="ADC-RUN-x"):
    return SimpleNamespace(
        _adc_evidence_run_id=evidence_run_id,
        _adc_evidence_store=store,
        _adc_evidence_published=published,
        _adc_evidence_publish_failures=[],
        getoption=lambda name: True if name == "--adc-evidence" else None,
    )


def _fake_session(exitstatus=0, config=None):
    session = SimpleNamespace(exitstatus=exitstatus, config=config or _fake_config())
    return session


def test_zero_published_events_never_triggers_finalization(monkeypatch):
    from requirements.evidence import pytest_plugin

    calls = []
    monkeypatch.setattr(pytest_plugin, "finalize_run", lambda *a, **k: calls.append("finalize_run"))
    session = _fake_session(config=_fake_config(published=0))
    pytest_plugin.pytest_sessionfinish(session, 0)
    assert calls == []
    assert session.config._adc_formal_finalization is None
    assert session.exitstatus == 0


def test_run_finalize_failure_fails_closed_and_skips_formal_pipeline(monkeypatch):
    from requirements.evidence import pytest_plugin, formal_finalization

    monkeypatch.setattr(
        pytest_plugin, "finalize_run",
        lambda *a, **k: SimpleNamespace(success=False, errors=["boom"]),
    )
    formal_calls = []
    monkeypatch.setattr(
        formal_finalization, "finalize_formal_test_run",
        lambda *a, **k: formal_calls.append((a, k)),
    )
    session = _fake_session(exitstatus=0)
    pytest_plugin.pytest_sessionfinish(session, 0)

    assert formal_calls == []  # never reached -- run itself was never finalized
    assert session.config._adc_formal_finalization.run_finalize_ok is False
    assert session.config._adc_formal_finalization.success is False
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED


def test_custom_evidence_store_skips_automatic_pipeline_without_failing(monkeypatch):
    """A non-default --adc-evidence-store must never reach
    finalize_formal_test_run() at all -- see ingest_all_runs's own
    docstring for why mixing a scratch store with the real rst targets
    is dangerous. This is a scoped/diagnostic run, not a pipeline
    failure: exitstatus must stay untouched."""
    from requirements.evidence import pytest_plugin, formal_finalization

    monkeypatch.setattr(pytest_plugin, "finalize_run", lambda *a, **k: SimpleNamespace(success=True))
    calls = []
    monkeypatch.setattr(
        formal_finalization, "finalize_formal_test_run",
        lambda *a, **k: calls.append((a, k)),
    )
    session = _fake_session(exitstatus=0, config=_fake_config(store="/some/custom/store"))
    pytest_plugin.pytest_sessionfinish(session, 0)

    assert calls == []  # never invoked for a custom store
    result = session.config._adc_formal_finalization
    assert result.skipped_custom_store is True
    assert result.success is True
    assert session.exitstatus == 0


def test_formal_pipeline_failure_fails_closed(monkeypatch):
    from requirements.evidence import pytest_plugin

    monkeypatch.setattr(pytest_plugin, "finalize_run", lambda *a, **k: SimpleNamespace(success=True))
    failing_result = FormalFinalizationResult(run_id="r", run_finalize_ok=True, ingest_ok=True, build_ok=False)
    monkeypatch.setattr(
        "requirements.evidence.formal_finalization.finalize_formal_test_run",
        lambda *a, **k: failing_result,
    )
    session = _fake_session(exitstatus=0)
    pytest_plugin.pytest_sessionfinish(session, 0)

    assert session.config._adc_formal_finalization is failing_result
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED


def test_successful_formal_pipeline_leaves_exitstatus_untouched(monkeypatch):
    from requirements.evidence import pytest_plugin

    monkeypatch.setattr(pytest_plugin, "finalize_run", lambda *a, **k: SimpleNamespace(success=True))
    ok_result = FormalFinalizationResult(
        run_id="r", run_finalize_ok=True, ingest_ok=True, build_ok=True,
        status_output_ok=True, trace_graph_ok=True,
    )
    monkeypatch.setattr(
        "requirements.evidence.formal_finalization.finalize_formal_test_run",
        lambda *a, **k: ok_result,
    )
    session = _fake_session(exitstatus=0)
    pytest_plugin.pytest_sessionfinish(session, 0)

    assert session.config._adc_formal_finalization.success is True
    assert session.exitstatus == 0


def test_preexisting_test_failure_exitstatus_is_never_downgraded(monkeypatch):
    """A real test failure (exitstatus already 1) must remain 1 -- the
    formal pipeline succeeding must never reset it back toward success,
    and a formal-pipeline failure must not need to invent a WORSE code
    than the real failure already produced."""
    from requirements.evidence import pytest_plugin

    monkeypatch.setattr(pytest_plugin, "finalize_run", lambda *a, **k: SimpleNamespace(success=True))
    ok_result = FormalFinalizationResult(
        run_id="r", run_finalize_ok=True, ingest_ok=True, build_ok=True,
        status_output_ok=True, trace_graph_ok=True,
    )
    monkeypatch.setattr(
        "requirements.evidence.formal_finalization.finalize_formal_test_run",
        lambda *a, **k: ok_result,
    )
    session = _fake_session(exitstatus=1)
    pytest_plugin.pytest_sessionfinish(session, 1)
    assert session.exitstatus == 1


# ============================================================================
# 3. Real end-to-end tests (pytester): the actual plugin, a real Sphinx
#    build, never against the real committed requirements/ tree.
# ============================================================================

@pytest.fixture
def scratch_requirements(tmp_path):
    """A disposable copy of requirements/ (never _build/_evidence/__pycache__)
    that a real sphinx-build can run against without touching the real,
    committed source tree."""
    dest = tmp_path / "requirements"
    shutil.copytree(
        REQUIREMENTS_SRC, dest,
        ignore=shutil.ignore_patterns("_build", "_evidence", "__pycache__"),
    )
    return dest


def _build_argv(outdir, doctree_dir, src):
    return [SPHINX_BUILD, "-E", "-a", "-W", "-b", "html", "-d", str(doctree_dir), str(src), str(outdir)]


def test_full_real_pipeline_mapped_test_io_then_nio(scratch_requirements, tmp_path):
    """Real ingest + real Sphinx build against a scratch copy of the
    Requirements tree, driving an EXISTING real TEST_*/Requirement chain
    (TEST_001 -> IF_REQ_002) through both IO and NIO -- proves the full
    chain: Evidence -> ingest -> TEST_* result -> generated Evidence ->
    strict Sphinx build -> Requirement-status recomputation, entirely
    isolated from the real, committed requirements/ tree.

    The scratch evidence store is SEEDED from a copy of the real run
    history (never the real store itself -- a copy) before this test's
    own synthetic runs are added to it: `evidence_generated.rst` is
    always a full regeneration from a store's complete history (existing,
    unchanged ingest.py behavior), so a store containing only this test's
    own two synthetic runs would silently regenerate evidence for TEST_001
    alone and drop every other real TEST_*'s evidence -- which the
    schema-validated scratch copy of tests.rst still requires (each
    already-IO TEST_* has a `test-has-evidence` schema rule demanding at
    least one incoming `evidences` link). Seeding preserves that
    completeness without ever touching the real store.
    """
    store = tmp_path / "_evidence"
    shutil.copytree(os.path.join(REQUIREMENTS_SRC, "_evidence"), store)
    tests_rst = scratch_requirements / "verification" / "tests.rst"
    evidence_generated = scratch_requirements / "verification" / "evidence_generated.rst"
    html_root = tmp_path / "html"
    doctree_dir = tmp_path / "doctrees"
    outdir_en = html_root / "en"

    selector = "tests/test_common_request.py::test_common_request_preserves_adapter_neutral_user_intent"

    def _run(result_value):
        run_id = run_identity.generate_run_id()
        _publish_and_finalize(store, run_id, selector, result_value)
        return finalize_formal_test_run(
            run_id, store_root=str(store),
            tests_rst_path=str(tests_rst), evidence_generated_path=str(evidence_generated),
            build_argv=_build_argv(outdir_en, doctree_dir, scratch_requirements),
            html_root=str(html_root), languages=("en",),
        )

    nio_result = _run("NIO")
    assert nio_result.success is True, nio_result
    assert nio_result.test_ids_updated["TEST_001"] == "NIO"
    with open(outdir_en / "requirement_status.json") as f:
        status_after_nio = json.load(f)
    assert status_after_nio["IF_REQ_002"]["implementation_state"] == "IMPLEMENTED_TEST_NIO"

    io_result = _run("IO")
    assert io_result.success is True, io_result
    assert io_result.test_ids_updated["TEST_001"] == "IO"
    with open(outdir_en / "requirement_status.json") as f:
        status_after_io = json.load(f)
    assert status_after_io["IF_REQ_002"]["implementation_state"] == "IMPLEMENTED_TEST_IO"


def test_default_store_formal_run_pass_completes_pipeline_exactly_once(pytester, isolated_formal_defaults):
    """No CLI store override: exercise the genuine default-store branch.

    The fixture relocates every writable default to a disposable source
    copy, preserving the real plugin, ingest and bilingual build. Repository
    provenance still identifies the actual code under test. Neither synthetic
    Evidence nor generated catalogs may touch operator-owned source/store.
    """
    pytester.makeconftest("pytest_plugins = ['requirements.evidence.pytest_plugin']")
    pytester.makepyfile("def test_default_store_pass_case():\n    assert True\n")

    result = pytester.runpytest("-p", "requirements.evidence.pytest_plugin", "--adc-evidence")

    result.assert_outcomes(passed=1)
    assert result.ret == 0
    result.stdout.fnmatch_lines([
        "*run_finalize: OK*",
        "*ingest: OK*",
        "*requirements_build: OK*",
        "*requirements_status_refresh: OK*",
        "*trace_graph_refresh: OK*",
        "*formal_finalization: OK*",
    ])
    assert "\n".join(result.outlines).count("ADC Formal Requirements Finalization") == 1


def test_default_store_formal_run_fail_ingests_nio_and_preserves_test_failure(pytester, isolated_formal_defaults):
    """The same production/default-store contract on a FAILING test:
    the real test failure must never be masked, and the failing
    Evidence (result=NIO) must still be durably published and ingested
    -- the pipeline itself (ingest/build) can still complete cleanly
    even though the mapped-if-it-were-mapped test result is NIO, exactly
    as required for "a failed mapped test... must produce... TEST_* =
    NIO... and pytest must still exit as failed" (this selector is
    unmapped, so no real TEST_* is touched, but the NIO event itself is
    genuinely published/ingested, proving the failure path is not
    special-cased away)."""
    pytester.makeconftest("pytest_plugins = ['requirements.evidence.pytest_plugin']")
    pytester.makepyfile("def test_default_store_fail_case():\n    assert False\n")

    result = pytester.runpytest("-p", "requirements.evidence.pytest_plugin", "--adc-evidence")

    result.assert_outcomes(failed=1)
    assert result.ret == 1  # the real test failure is never masked
    result.stdout.fnmatch_lines([
        "*run_finalize: OK*", "*ingest: OK*", "*requirements_build: OK*",
        "*requirements_status_refresh: OK*", "*trace_graph_refresh: OK*",
        "*formal_finalization: OK*",
    ])


def test_ordinary_pytest_without_adc_evidence_is_side_effect_free(pytester):
    pytester.makeconftest("pytest_plugins = ['requirements.evidence.pytest_plugin']")
    pytester.makepyfile("def test_ok():\n    assert True\n")
    scratch_store = pytester.path / "would-be-evidence-store"

    result = pytester.runpytest()
    result.assert_outcomes(passed=1)
    assert result.ret == 0
    assert not scratch_store.exists()
    result.stdout.no_fnmatch_line("*ADC Evidence*")
    result.stdout.no_fnmatch_line("*ADC Formal Requirements Finalization*")


def test_formal_run_with_custom_store_skips_pipeline_without_touching_real_tree(pytester, tmp_path):
    """A --adc-evidence-store override is a scoped/diagnostic Evidence
    run, not a formal Requirements-updating run: the automatic ingest/
    Sphinx-refresh pipeline must be skipped rather than mixing a scratch
    store with the real requirements/ tree (the exact combination that,
    before this guard, silently wiped real generated Evidence -- see
    ingest_all_runs's own docstring). Publication/finalization of the
    Evidence run itself still happens normally."""
    pytester.makeconftest("pytest_plugins = ['requirements.evidence.pytest_plugin']")
    pytester.makepyfile(
        "def test_one():\n    assert True\n"
        "def test_two():\n    assert True\n"
        "def test_three():\n    assert True\n"
    )
    store = tmp_path / "_evidence"
    real_evidence_generated = os.path.join(REQUIREMENTS_SRC, "verification", "evidence_generated.rst")
    with open(real_evidence_generated, encoding="utf-8") as f:
        before = f.read()

    result = pytester.runpytest(
        "-p", "requirements.evidence.pytest_plugin",
        "--adc-evidence", f"--adc-evidence-store={store}",
    )
    result.assert_outcomes(passed=3)
    assert result.ret == 0  # a scoped run is never a pipeline failure
    result.stdout.fnmatch_lines([
        "*run_finalize: OK*",
        "*ingest: NOT_APPLICABLE*",
        "*requirements_build: NOT_APPLICABLE*",
        "*requirements_status_refresh: NOT_APPLICABLE*",
        "*trace_graph_refresh: NOT_APPLICABLE*",
        "*formal_finalization: NOT_APPLICABLE*",
        "*reason: custom Evidence store*",
    ])
    # Never a bare "OK"/"FAIL" for the intentionally-skipped stages --
    # only the explicit NOT_APPLICABLE state (CLAUDE-ADC-FORMAL-TEST-
    # AUTO-REQUIREMENTS-UPDATE-003: never confusable with a completed or
    # failed production formal run).
    result.stdout.no_fnmatch_line("*formal_finalization: OK*")
    result.stdout.no_fnmatch_line("*formal_finalization: FAIL*")
    # exactly one finalization section, despite three test functions
    assert "\n".join(result.outlines).count("ADC Formal Requirements Finalization") == 1
    assert list(store.glob("runs/*"))  # the scoped run's own Evidence was still durably published

    with open(real_evidence_generated, encoding="utf-8") as f:
        after = f.read()
    assert after == before  # the real, committed tree was never touched


def test_formal_run_failing_test_with_custom_store_preserves_failure(pytester, tmp_path):
    pytester.makeconftest("pytest_plugins = ['requirements.evidence.pytest_plugin']")
    pytester.makepyfile(
        "def test_fails():\n    assert False\n"
    )
    store = tmp_path / "_evidence"

    result = pytester.runpytest(
        "-p", "requirements.evidence.pytest_plugin",
        "--adc-evidence", f"--adc-evidence-store={store}",
    )
    result.assert_outcomes(failed=1)
    assert result.ret == 1  # the real test failure is never masked
    result.stdout.fnmatch_lines(["*ADC Formal Requirements Finalization*"])
    result.stdout.fnmatch_lines(["*run_finalize: OK*"])


@pytest.fixture
def isolated_formal_defaults(scratch_requirements, monkeypatch):
    """Exercise the default-store branch with a real build in a private tree.

    No CLI custom-store override: production's default-path decision and
    finalization still execute. Only their filesystem roots are relocated.
    Synthetic Evidence must never enter the operator's real Evidence store.
    """
    from requirements.evidence import publisher, ingest, formal_finalization

    root = scratch_requirements.parent
    (root / ".requirements-venv").symlink_to(os.path.join(REPO_ROOT, ".requirements-venv"),
                                            target_is_directory=True)
    store = str(scratch_requirements / "_evidence")
    # The copied Requirements model references its full prior Evidence graph.
    # Seed a private copy as fixture state, exactly as the mapped IO/NIO test
    # above does; the new synthetic event is still freshly published/ingested.
    shutil.copytree(os.path.join(REQUIREMENTS_SRC, "_evidence"), store)
    for module in (publisher, ingest, formal_finalization):
        monkeypatch.setattr(module, "DEFAULT_STORE_ROOT", store)
    monkeypatch.setattr(ingest, "TESTS_RST_PATH", str(scratch_requirements / "verification/tests.rst"))
    monkeypatch.setattr(ingest, "EVIDENCE_GENERATED_RST_PATH", str(scratch_requirements / "verification/evidence_generated.rst"))
    monkeypatch.setattr(formal_finalization, "REPO_ROOT", str(root))
    monkeypatch.setattr(formal_finalization, "REQUIREMENTS_SRC", str(scratch_requirements))
    monkeypatch.setattr(formal_finalization, "BUILD_SH", str(scratch_requirements / "build.sh"))
    monkeypatch.setattr(formal_finalization, "DEFAULT_HTML_ROOT", str(scratch_requirements / "_build/html"))
    monkeypatch.delenv("ADC_REQUIREMENTS_BUILD_ROOT", raising=False)
    return scratch_requirements
