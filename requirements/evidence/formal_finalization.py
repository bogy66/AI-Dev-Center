"""Central formal-run finalization (CLAUDE-ADC-FORMAL-TEST-AUTO-
REQUIREMENTS-UPDATE-002), superseding the incomplete/unconfirmed
CLAUDE-ADC-FORMAL-TEST-AUTO-REQUIREMENTS-UPDATE-001.

A formal `pytest --adc-evidence` invocation must not leave the operator
to run `python -m requirements.evidence.cli ingest` (or a separate Sphinx
build) by hand. `finalize_formal_test_run()` is the ONE place that
orchestrates the mandatory post-test pipeline, called exactly once from
`pytest_plugin.py`'s `pytest_sessionfinish`, strictly AFTER
`publisher.finalize_run()` has already succeeded for that run:

    ingest_all_runs()            (requirements.evidence.ingest -- unchanged)
        -> TEST_*/EVID_* .rst representation updated in place
    Requirements/Sphinx build     (existing requirements/build.sh by
                                   default -- unchanged, never duplicated)
        -> requirement_status.json / dashboard / trace-graph SVG refreshed
           by the EXISTING build-finished hooks in requirements/conf.py
           and requirements/status_model.py
    generated-output presence check (never a second status computation --
        just confirms the existing build actually wrote what it always
        writes)

This module never re-implements ingest, never recomputes Requirement
status, never talks to the Evidence store directly, and never invokes a
second Sphinx/build mechanism -- it only sequences the three existing
ones and reports, per stage, whether the formal run may be considered
fully finalized. Fail-closed throughout: any stage failing means
`FormalFinalizationResult.success` is False, even though the earlier
stages (or the pytest session itself) may have succeeded.

CLAUDE-ADC-FORMAL-TEST-AUTO-REQUIREMENTS-UPDATE-003 -- the formal-run
contract, made explicit and unambiguous:

  PRODUCTION FORMAL RUN (`pytest --adc-evidence`, the DEFAULT Evidence
  store): publish -> finalize -> ingest -> TEST_*/EVID_* update ->
  Requirements/Sphinx build -> status/dashboard/trace-graph refresh, all
  automatic, exactly once. `FormalFinalizationResult.skipped_custom_store`
  is False; `.success` reflects every stage above.

  ISOLATED/CUSTOM EVIDENCE RUN (`pytest --adc-evidence
  --adc-evidence-store <custom path>`): publish/finalize happen into the
  CUSTOM store as requested, but the automatic ingest/Sphinx-refresh
  pipeline is DELIBERATELY NEVER attempted -- it always targets the real
  default store together with the real requirements/ source tree, and
  running it against a custom store would (and once did) silently
  regenerate the real generated Evidence from an incomplete history (see
  `ingest_all_runs`'s own docstring). This is reported as
  `FormalFinalizationResult.skipped_custom_store = True`, and the pytest
  terminal summary prints an explicit `formal_finalization: NOT_APPLICABLE`
  with `reason: custom Evidence store` -- NEVER `OK`, which would
  misrepresent an intentionally-skipped Requirements refresh as a
  completed one. It is also never treated as a failure (never forces a
  non-zero pytest exit status): an isolated/diagnostic Evidence run is
  not an error, only never a Requirements-updating one.
"""
from __future__ import annotations

import glob
import os
import subprocess
from dataclasses import dataclass, field

from .ingest import DEFAULT_STORE_ROOT, ingest_all_runs

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
REQUIREMENTS_SRC = os.path.join(REPO_ROOT, "requirements")
BUILD_SH = os.path.join(REQUIREMENTS_SRC, "build.sh")
DEFAULT_HTML_ROOT = os.path.join(REQUIREMENTS_SRC, "_build", "html")
DEFAULT_LANGUAGES = ("en", "de")

# The formal-run terminal-status vocabulary for a Requirements-refresh
# stage that was intentionally never attempted (custom-store mode) --
# distinct from both "OK" and "FAIL" so it can never be confused with a
# completed or a failed production formal run (CLAUDE-ADC-FORMAL-TEST-
# AUTO-REQUIREMENTS-UPDATE-003).
NOT_APPLICABLE = "NOT_APPLICABLE"
CUSTOM_STORE_SKIP_REASON = "custom Evidence store"


def is_default_store(store_root) -> bool:
    """True when `store_root` is the real, default Evidence store (None,
    or a path that resolves to it) -- the ONLY case in which an
    automatic formal run may perform Requirements finalization at all."""
    if store_root is None:
        return True
    return os.path.abspath(store_root) == os.path.abspath(DEFAULT_STORE_ROOT)

# Relative to <html_root>/<language>/ -- the existing, already-productive
# generated outputs this module only ever VERIFIES the presence of (see
# requirements/status_model.py:export_requirement_status and
# requirements/svg_status_background.py:postprocess_needflow_svgs, both
# already wired into requirements/conf.py's build-finished hooks).
_EXPECTED_OUTPUT_FILES = (
    "needs.json",
    "requirement_status.json",
    os.path.join("dashboard", "overview.html"),
    os.path.join("dashboard", "requirement_status.html"),
    os.path.join("dashboard", "traceability.html"),
)
_NEEDFLOW_SVG_GLOB = os.path.join("_images", "needflow-*.svg")


@dataclass
class FormalFinalizationResult:
    run_id: str
    run_finalize_ok: bool = False
    # Set (only by the pytest plugin, never by finalize_formal_test_run
    # itself) when a non-default --adc-evidence-store was explicitly
    # requested -- see finalize_formal_test_run's own docstring for why
    # the automatic ingest/Sphinx-refresh pipeline is never run in that
    # case. Not a failure: the operator explicitly chose a scoped/
    # diagnostic Evidence run, never a "formal Requirements-updating run"
    # against the real store.
    skipped_custom_store: bool = False
    ingest_ok: bool = False
    ingest_error: str | None = None
    test_ids_updated: dict = field(default_factory=dict)
    evidence_objects_generated: list = field(default_factory=list)
    unmapped_selectors: list = field(default_factory=list)
    build_ok: bool = False
    build_error: str | None = None
    build_returncode: int | None = None
    build_stdout: str = ""
    build_stderr: str = ""
    status_output_ok: bool = False
    trace_graph_ok: bool = False
    missing_outputs: list = field(default_factory=list)

    @property
    def outputs_ok(self) -> bool:
        return self.status_output_ok and self.trace_graph_ok

    @property
    def success(self) -> bool:
        if self.skipped_custom_store:
            return self.run_finalize_ok
        return self.run_finalize_ok and self.ingest_ok and self.build_ok and self.outputs_ok


def _expected_output_paths(html_root, languages):
    paths = []
    for lang in languages:
        base = os.path.join(html_root, lang)
        for rel in _EXPECTED_OUTPUT_FILES:
            paths.append(os.path.join(base, rel))
    return paths


def _has_trace_graph_output(html_root, languages):
    return any(
        glob.glob(os.path.join(html_root, lang, _NEEDFLOW_SVG_GLOB))
        for lang in languages
    )


def finalize_formal_test_run(
    run_id,
    *,
    store_root=None,
    tests_rst_path=None,
    evidence_generated_path=None,
    build_argv=None,
    html_root=None,
    languages=None,
) -> FormalFinalizationResult:
    """Run the mandatory post-Evidence pipeline exactly once for `run_id`.

    Callers (the pytest plugin) must invoke this only after
    `publisher.finalize_run()` has already succeeded for this run --
    never re-checked here, so a formal run whose own Evidence run was
    never successfully finalized can never reach this function and have
    it silently ingested/built anyway.

    `store_root`/`tests_rst_path`/`evidence_generated_path`/`build_argv`/
    `html_root`/`languages` are overridable purely so tests can point
    this at an entirely scratch store+tree+build instead of the real
    default store, the real `requirements/` source tree, and the real
    `requirements/build.sh` output -- production callers (the pytest
    plugin) always call this with NO overrides at all when running a
    genuine formal Requirements-updating run. Overriding `store_root`
    alone (without also overriding the rst paths) is refused by
    `ingest_all_runs` itself (see its own docstring) -- a store that is
    not the real, complete run history must never be allowed to
    regenerate the real generated Evidence representation. The pytest
    plugin therefore never calls this function at all when an operator
    explicitly requested a non-default `--adc-evidence-store`; it
    reports that run as an intentionally scoped/diagnostic Evidence
    publish instead (see `FormalFinalizationResult.skipped_custom_store`).
    """
    # Only ever called by the caller after publisher.finalize_run() has
    # already succeeded for this run_id (see pytest_plugin.py) -- never
    # re-verified here, so run_finalize_ok is always True on entry; a
    # failed finalize_run() must produce its own FormalFinalizationResult
    # with run_finalize_ok=False directly, without calling this function.
    result = FormalFinalizationResult(run_id=run_id, run_finalize_ok=True)

    try:
        report = ingest_all_runs(
            store_root=store_root,
            tests_rst_path=tests_rst_path,
            evidence_generated_path=evidence_generated_path,
        )
    except Exception as exc:  # noqa: BLE001 -- fail closed, never propagate into pytest's own exit path uncontrolled
        result.ingest_error = f"{type(exc).__name__}: {exc}"
        return result

    result.unmapped_selectors = list(report.unmapped_selectors)
    if report.malformed_events_skipped:
        result.ingest_error = (
            f"malformed Evidence events encountered: {report.malformed_events_skipped}"
        )
        return result

    result.test_ids_updated = dict(report.test_ids_updated)
    result.evidence_objects_generated = list(report.evidence_objects_generated)
    result.ingest_ok = True

    languages = tuple(languages) if languages else DEFAULT_LANGUAGES
    html_root = html_root or DEFAULT_HTML_ROOT
    argv = list(build_argv) if build_argv else [BUILD_SH]

    try:
        proc = subprocess.run(
            argv, cwd=REPO_ROOT, capture_output=True, text=True,
        )
    except OSError as exc:
        result.build_error = f"could not invoke Requirements build: {exc}"
        return result

    result.build_returncode = proc.returncode
    result.build_stdout = proc.stdout
    result.build_stderr = proc.stderr
    if proc.returncode != 0:
        result.build_error = f"Requirements build exited {proc.returncode}"
        return result
    result.build_ok = True

    missing = [
        p for p in _expected_output_paths(html_root, languages)
        if not os.path.exists(p)
    ]
    result.status_output_ok = not missing
    result.trace_graph_ok = _has_trace_graph_output(html_root, languages)
    if not result.trace_graph_ok:
        missing.append(os.path.join(html_root, "<language>", _NEEDFLOW_SVG_GLOB))
    result.missing_outputs = missing

    return result
