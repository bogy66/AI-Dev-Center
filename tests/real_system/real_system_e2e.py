"""Manually invoked paid Real-System E2E.

Run only with:
  venv/bin/python -m pytest tests/real_system/real_system_e2e.py --real-system-e2e -s
"""
from dataclasses import asdict, replace
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import venv

import pytest
import yaml

from app.canonical_composition import build_canonical_components
from app.diagnostic_trace import DiagnosticDetailLevel, render_diagnostic_trace_event
from app.engineering_decision import EngineeringVariantSelection, select_engineering_variant
from app.execution import is_controlled_setup_effect
from app.greenfield_project import GreenfieldProjectApproval
from app.missing_toolchain_setup import MissingToolchainSetupRequest
from app.requirement_model import classify_setup_effect
from app.setup_approval import SetupApproval
from app.verification import (
    PASS, TOOL_UNAVAILABLE, build_verification_plan,
    trusted_verification_identity_groups,
)


REAL_TASK = 'Create an ESPHome project for an ESP32 that logs "Hello World" periodically.'

class _DynamicStdoutHandler(logging.Handler):
    """Write to whatever sys.stdout currently is at emit time.

    A plain logging.StreamHandler(sys.stdout) binds the stream object
    once, at construction time - which, at module import, is whatever
    sys.stdout happened to be then. That breaks output capture under
    tools that swap sys.stdout per-invocation (e.g. pytest's capsys
    fixture), since the handler keeps writing to the original, already
    -replaced stream. Resolving sys.stdout fresh on every emit avoids
    that class of bug entirely.
    """

    def emit(self, record):
        try:
            sys.stdout.write(self.format(record) + "\n")
            sys.stdout.flush()
        except Exception:
            self.handleError(record)


logger = logging.getLogger("ai_dev_center.real_system_e2e")
logger.setLevel(logging.DEBUG)
logger.propagate = False
if not logger.handlers:
    _handler = _DynamicStdoutHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_handler)


_TRACE_PHASE_MILESTONE = {
    ("requirement_discovery", "completed"): (20, "Requirement Discovery completed"),
    ("requirement_validation", "completed"): (25, "Requirement Validation completed"),
    ("preflight", "completed"): (30, "Preflight completed"),
}


class _E2EProgress:
    """Real-System E2E progress tracker with elapsed time and milestone percentage."""

    _LOCK = threading.Lock()

    def __init__(self):
        self._start = time.monotonic()
        self._pct = 0
        self._emitted_milestones = set()

    @property
    def pct(self):
        return self._pct

    def _elapsed(self):
        s = int(time.monotonic() - self._start)
        return f"{s // 60:02d}:{s % 60:02d}"

    def milestone(self, pct, label):
        with self._LOCK:
            milestone = (pct, label)
            if pct < self._pct or milestone in self._emitted_milestones:
                return
            self._pct = pct
            self._emitted_milestones.add(milestone)
        logger.info("[REAL-E2E][%s%%][%s] %s", pct, self._elapsed(), label)

    def info(self, label):
        with self._LOCK:
            pct = self._pct
        logger.info("[REAL-E2E][%s%%][%s] %s", pct, self._elapsed(), label)

    def cleanup_start(self):
        logger.info("[REAL-E2E] cleanup started")

    def cleanup_done(self):
        logger.info("[REAL-E2E] cleanup completed")

    def fail(self, label):
        with self._LOCK:
            pct = self._pct
        logger.error("[REAL-E2E][%s%%][%s] FAIL: %s", pct, self._elapsed(), label)
        logger.error("[REAL-E2E][%s%%] E2E completion at failure", pct)


def _council_progress_line(event) -> str | None:
    """Bounded, safe live-progress text for one Engineering Council activity event.

    Built only from the already-redacted ``event.summary`` that
    DiagnosticTrace.record() produces for engineering_council phase
    events - e.g. "Agent A1 started" or "Chairman completed" - never
    from raw prompts, responses, chain-of-thought, or other details.
    This exists because render_diagnostic_trace_event() intentionally
    returns "" at diagnostic_level=NONE, which would otherwise leave
    the Council's (often multi-minute) phase completely silent.
    """
    if getattr(event, "phase", "") != "engineering_council":
        return None
    details = getattr(event, "details", {}) or {}
    if not details.get("actor"):
        return None
    return f"Engineering Council: {event.summary}"


_POST_APPROVAL_PHASE_LABEL = {
    "setup_execution": "Setup execution",
    "development": "Development",
    "test_generation": "Test generation",
    "testing": "Testing",
    "diagnosis_review": "Diagnosis review",
    "controlled_rework": "Controlled rework",
}


def _post_approval_progress_line(event) -> str | None:
    """Honest, phase-aware progress text for the single broad
    execute_approved_plan_from_store() call.

    Without this, the last label the RSE progress log shows before that
    call is the fixed "setup/toolchain handling" line set right before
    it -- and since the call itself runs the entire remaining
    setup/development/testing/rework lifecycle internally (potentially
    several rework cycles) before returning, that stale label stays
    visible on screen long after the real workflow has moved on,
    falsely implying setup/toolchain work is still what's happening.
    Mapping each phase's own DiagnosticTrace events to an honest label,
    polled the same way planning phases already are, keeps the visible
    stage truthful. See KIB-ADC-RSE-SETUP-TRACE-DUAL-DEFECT-FIX-001
    section 4.
    """
    phase = getattr(event, "phase", "")
    label = _POST_APPROVAL_PHASE_LABEL.get(phase)
    if label is None:
        return None
    status = getattr(event, "status", "")
    return f"{label}: {status}"


def _render_new_trace_events(progress, events, seen_sequences, diagnostic_level="NONE"):
    """Render each central event once and advance each acceptance milestone once."""
    for event in events:
        seq = getattr(event, "sequence", None)
        if seq is not None and seq in seen_sequences:
            continue
        if seq is not None:
            seen_sequences.add(seq)

        key = (getattr(event, "phase", ""), getattr(event, "status", ""))
        if key in _TRACE_PHASE_MILESTONE:
            pct, label = _TRACE_PHASE_MILESTONE[key]
            progress.milestone(pct, label)
        rendered = render_diagnostic_trace_event(event, diagnostic_level)
        if rendered:
            logger.info(rendered)
        else:
            council_line = _council_progress_line(event)
            if council_line is not None:
                progress.info(council_line)
            else:
                phase_line = _post_approval_progress_line(event)
                if phase_line is not None:
                    progress.info(phase_line)


def _poll_trace_during_call(progress, get_trace, run_id, stop_event, seen_sequences, diagnostic_level="NONE"):
    """Background thread: poll DiagnosticTrace and report new events while
    a single long-running service call (planning, or the broad approved
    setup+development execution) is in flight."""
    while not stop_event.wait(2.0):
        try:
            events = get_trace(run_id)
        except Exception:
            continue
        _render_new_trace_events(progress, events, seen_sequences, diagnostic_level)


def find_silently_lost_active_setup_requirements(plan, preflight_result):
    """Fail-fast observability helper (KIB-ADC-RSE-SETUP-TRACE-DUAL-DEFECT
    -FIX-001 section 3).

    KIB-ADC-RSE-SETUP-TRACE-DUAL-DEFECT-ANALYSIS-001's Defect A finding
    was that a SetupPlan with zero steps for a missing dependency is
    NOT, by itself, evidence of a bug: an inactive/deferred requirement
    (Preflight ran before the engineering decision that would need it
    was even made) legitimately produces no step yet, and that must
    stay legitimate. But an ACTIVE, REQUIRED, ADC-controllable
    requirement disappearing from the plan with no trace at all would
    be a real, silent defect -- the RSE should fail fast on that shape
    rather than let it surface later as a confusing downstream failure
    (or, worse, not surface at all).

    Returns the tuple of requirement_ids that are: still missing
    (`not present`/`not satisfied`), `active` (not legitimately
    deferred), `required=True` on their underlying Requirement, and
    have a `setup_effect` central classify_setup_effect()/
    is_controlled_setup_effect() itself considers ADC-controllable --
    but ended up in NONE of the SetupPlan's own explicit, structured
    accounting: not a materialized SetupStep.requirement_id, not
    `deferred_requirement_ids`, not `provided_requirement_ids`, and
    their setup_effect is not listed in `unsupported_backend_effects`
    either. An empty result proves every such requirement was
    genuinely, structurally accounted for -- never merely "probably
    fine because nothing complained".

    Deliberately reuses the SAME central classify_setup_effect()/
    is_controlled_setup_effect() functions ToolchainMaterializer itself
    uses to decide controllability, rather than re-deriving that
    judgment independently (which could silently drift from the real
    classification and either over- or under-report).
    """
    accounted_for = (
        {step.requirement_id for step in plan.steps}
        | set(plan.deferred_requirement_ids)
        | set(plan.provided_requirement_ids)
    )
    missing_by_id = {req.id: req for req in preflight_result.missing_requirements}

    lost = []
    for result in preflight_result.results:
        if result.present or result.satisfied:
            continue
        if not result.active:
            continue  # legitimately deferred -- Defect A's proven-safe case
        if result.requirement_id in accounted_for:
            continue
        requirement = missing_by_id.get(result.requirement_id)
        if requirement is None or not requirement.required:
            continue
        effect = classify_setup_effect(
            requirement.type, requirement.name, requirement.install_method,
        )
        if not effect or effect == "manual" or not is_controlled_setup_effect(effect):
            continue  # ADC genuinely has no controlled backend -- correctly unsupported, not lost
        if effect in plan.unsupported_backend_effects:
            continue  # explicitly, structurally recorded as unsupported -- not silent
        lost.append(result.requirement_id)
    return tuple(lost)


def assert_no_silently_lost_active_setup_requirements(plan, preflight_result):
    """Raises with a diagnostic-friendly message if
    find_silently_lost_active_setup_requirements() finds anything --
    the RSE's own fail-fast gate for this invariant."""
    lost = find_silently_lost_active_setup_requirements(plan, preflight_result)
    if lost:
        raise AssertionError(
            "Active, required, ADC-controllable requirement(s) "
            f"{lost!r} have NEITHER a materialized SetupStep NOR an "
            "explicit deferred/provided/unsupported-backend marker in "
            "the SetupPlan. This is the silent-loss shape distinct from "
            "the legitimate 'inactive/deferred' case "
            "(KIB-ADC-RSE-SETUP-TRACE-DUAL-DEFECT-ANALYSIS-001 Defect A) "
            "-- failing fast here instead of continuing with a plan "
            "that has quietly dropped a real, active requirement."
        )


def _extract_council_activity(trace_events):
    council_events = []
    for event in trace_events:
        details = getattr(event, "details", {}) or {}
        phase = getattr(event, "phase", "")
        if "council" in phase.lower() and details.get("actor"):
            council_events.append(event)
    return council_events


def _stage_interface_warnings(trace_events, stage):
    """Return the safe, structured warnings recorded for one workflow
    stage's interface trace event, if present.

    Reads only the already-sanitized DiagnosticTrace 'warnings' field
    (never prompts, raw responses, or reasoning) from the interface_data
    every DevelopmentWorkflow stage already records regardless of
    diagnostic_level, so a failing stage's root cause (e.g. why an LLM
    provider call was treated as unusable) is visible on failure without
    needing a higher --diagnostic-level.
    """
    for event in trace_events:
        details = getattr(event, "details", {}) or {}
        if details.get("result_kind") != "interface":
            continue
        if details.get("interface_stage") != stage:
            continue
        interface_data = details.get("interface_data")
        if not isinstance(interface_data, dict):
            continue
        verbose = interface_data.get("verbose")
        if not isinstance(verbose, dict):
            continue
        y = verbose.get("y")
        if not isinstance(y, dict):
            continue
        data = y.get("data")
        if not isinstance(data, dict):
            continue
        warnings = data.get("warnings")
        if isinstance(warnings, (list, tuple)):
            return [str(item) for item in warnings]
    return []


def _council_reached_complete(trace_info) -> bool:
    """True when SOME event anywhere in this trace recorded
    council_complete=True -- i.e. the Engineering Council eventually
    reached a complete Chairman decision, regardless of any earlier
    per-agent retry along the way."""
    return any(
        (getattr(event, "details", {}) or {}).get("council_complete") is True
        for event in trace_info
    )


def _validate_final_diagnostic_trace(trace, real_task: str) -> str:
    """The final Central-Diagnostic-Trace acceptance contract, shared by
    the Real-System-E2E and its focused regression coverage
    (KIB-ADC-RSE-DIAGNOSTIC-TRACE-TC-FIX-001).

    Serializes every persisted DiagnosticTraceEvent via the REAL
    product contract -- dataclasses.asdict(event), the exact same
    function app.diagnostic_trace.DiagnosticTraceStore.append() already
    uses to persist each event to its JSONL audit file -- as genuine
    JSON text (json.dumps), never a Python repr/str() of a list of
    dicts: the assertions below look for double-quoted JSON keys like
    '"x"'/'"execution_identity"', which only ever appear in real
    JSON output, not in Python's single-quoted dict repr. There never
    was a DiagnosticTraceEvent.to_record() product method (confirmed by
    direct inspection of app/diagnostic_trace.py: only a from_record()
    classmethod exists, for deserializing a persisted JSONL line back
    into an event) -- this was a stale test-only assumption, now
    replaced by the actual product serialization contract.

    Deliberately independent of DiagnosticDetailLevel: this inspects
    the RAW PERSISTED events (via asdict()), never the presentation-
    layer render_diagnostic_trace_event() projection, so
    DiagnosticDetailLevel.NONE (used for live progress suppression)
    never erases the audit evidence this function checks for -- the
    persisted trace always carries full details regardless of what a
    human-readable rendering chooses to show.

    Raises AssertionError with the same messages the original inline
    RSE block used, so a real Real-System-E2E failure here reads
    exactly as it did before."""
    serialized = json.dumps([asdict(event) for event in trace])
    # REAL_TASK itself contains literal double quotes ('... logs "Hello
    # World" periodically.'); genuine JSON serialization escapes those
    # (\\") inside string values, so the raw real_task text never
    # appears byte-for-byte inside `serialized` even when it is
    # genuinely present -- checking for its OWN json-escaped form is
    # what correctly proves presence inside real JSON output (the
    # unescaped check that would have been used against a Python
    # repr/str() never actually ran successfully before this fix, since
    # to_record() always raised first).
    real_task_escaped = json.dumps(real_task)[1:-1]
    assert real_task_escaped in serialized, (
        "Central trace must contain the original task description"
    )

    assert all(
        actor in serialized
        for actor in ("Agent A1", "Agent A2", "Agent A3", "Chairman")
    ), "Central trace must reference all Council agents and Chairman"
    for forbidden in ("system_prompt", "raw_response", "chain_of_thought", "api_key"):
        assert forbidden not in serialized, (
            f"Central trace must not expose '{forbidden}'"
        )

    assert '"x"' in serialized and '"y"' in serialized and '"f"' in serialized, (
        "Central trace must contain safe x → f → y records for relevant "
        "traced workflow boundaries"
    )
    assert (
        '"type"' in serialized
        and '"interface"' in serialized
        and '"source"' in serialized
        and '"destination"' in serialized
    ), (
        "Central trace must contain typed x/y metadata (type, interface, "
        "source, destination)"
    )
    assert '"execution_identity"' in serialized and (
        '"entity"' in serialized and '"entity_version"' in serialized
        and '"implementation_version"' in serialized
    ), (
        "Central trace must contain execution identity with entity, "
        "entity_version and implementation_version"
    )
    return serialized


def _verification_failure_bundle(dev_result, trace_events, run_id: str) -> str | None:
    """Build a compact safe diagnosis when S4/S5 returned without
    verification. Include no prompts, paths, file content or responses."""
    workflow_result = getattr(dev_result, "development_testing_result", None)
    if workflow_result is None or getattr(workflow_result, "verification_result", None) is not None:
        return None

    development = getattr(workflow_result, "development_result", None)
    generation = getattr(development, "generation_evidence", None)
    if not isinstance(generation, dict):
        generation = {}
    generated = getattr(development, "generated_changes", None)
    generated_changes = generated.get("changes") if isinstance(generated, dict) else None
    generated_count = generation.get("generated_change_count")
    if not isinstance(generated_count, int) or isinstance(generated_count, bool) or generated_count < 0:
        generated_count = len(generated_changes) if isinstance(generated_changes, (list, tuple)) else "unknown"

    applied = getattr(development, "applied_changes", None)
    applied_paths = applied.get("applied") if isinstance(applied, dict) else None
    skipped_paths = applied.get("skipped") if isinstance(applied, dict) else None
    applied_count = len(applied_paths) if isinstance(applied_paths, (list, tuple)) else 0
    skipped_count = len(skipped_paths) if isinstance(skipped_paths, (list, tuple)) else 0

    phases = {
        "setup_execution", "development", "test_generation", "change_provenance",
        "testing", "diagnosis_review", "controlled_rework", "verification",
    }
    events = sorted(
        (event for event in trace_events if getattr(event, "phase", None) in phases),
        key=lambda event: getattr(event, "sequence", 0),
    )
    failure_stage = getattr(workflow_result, "failure_stage", None)
    if failure_stage is None and getattr(development, "status", None) == "apply_failed":
        failure_stage = "development_apply"
    failure_event = next(
        (event for event in events
         if failure_stage is not None
         and (getattr(event, "details", {}) or {}).get("failure_stage") == failure_stage),
        None,
    )
    if failure_event is None:
        failure_event = next(
            (event for event in events
             if event.status in {"failed", "rejected", "timeout"}
             and not _phase_later_recovered(events, event)),
            None,
        )
    if failure_stage is None and failure_event is not None:
        failure_stage = failure_event.phase
    category = (getattr(failure_event, "details", {}) or {}).get("failure_category") if failure_event else None
    if category is None:
        category = getattr(workflow_result, "status", "unknown")
    safe_category = category if isinstance(category, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", category) else "unknown"
    safe_failure_stage = failure_stage if isinstance(failure_stage, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", failure_stage) else "unknown"
    workflow_status = getattr(workflow_result, "status", "unknown")
    safe_workflow_status = workflow_status if isinstance(workflow_status, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", workflow_status) else "unknown"
    repair_attempted = generation.get("repair_attempted")
    apply_attempted = generation.get("apply_attempted")
    repair_attempted = repair_attempted if isinstance(repair_attempted, bool) else "unknown"
    apply_attempted = apply_attempted if isinstance(apply_attempted, bool) else "unknown"

    failure_sequence = getattr(failure_event, "sequence", None)
    successful_statuses = {"completed", "passed", "accepted", "approved", "committed"}
    prior = [event for event in events
             if getattr(event, "sequence", None) is not None
             and (failure_sequence is None or event.sequence < failure_sequence)
             and event.status in successful_statuses]
    last_successful_stage = prior[-1].phase if prior else "none"
    seqs = [event.sequence for event in events if isinstance(getattr(event, "sequence", None), int)]
    trace_range = f"{min(seqs)}-{max(seqs)}" if seqs else "none"
    trace_summary = ",".join(
        f"{event.sequence}:{event.phase}/{event.event_type}/{event.status}"
        for event in events[-12:]
    ) or "none"
    return (
        "Verification was not reached; workflow stopped before producing a verification result. "
        f"run_id={run_id}; workflow_status={safe_workflow_status}; "
        f"first_failure_stage={safe_failure_stage}; failure_category={safe_category}; "
        f"last_successful_stage={last_successful_stage}; generated_change_count={generated_count}; "
        f"applied_path_count={applied_count}; skipped_path_count={skipped_count}; "
        f"generation_attempted={development is not None}; "
        f"repair_attempted={repair_attempted}; "
        f"apply_attempted={apply_attempted}; "
        f"verification_reached=False; trace_sequence_range={trace_range}; "
        f"trace_events=[{trace_summary}]"
    )


def _assert_verification_reached(dev_result, trace_events, run_id: str):
    """Keep RSE acceptance strict while surfacing pre-verification state."""
    bundle = _verification_failure_bundle(dev_result, trace_events, run_id)
    assert bundle is None, bundle
    workflow_result = getattr(dev_result, "development_testing_result", None)
    verification = getattr(workflow_result, "verification_result", None)
    assert verification is not None, "Development testing must produce a verification result"
    return verification


def _phase_later_recovered(trace_info, event) -> bool:
    """True when some LATER event (by sequence) on the SAME phase as
    *event* reports a non-failure status -- i.e. *event* was a
    transient, already-resolved retry within its own phase, never a
    terminal cause (KIB-ADC-RSE-DIAGNOSTIC-TRACE-TC-FIX-001).

    This generalizes the engineering_council-specific recovery check
    just below (which uses the council_complete signal, a concept that
    only exists for that one phase) to every phase: it never claims a
    DIFFERENT, later phase supersedes an earlier one -- it only
    recognizes that THIS SAME phase itself moved past the failure. A
    phase that fails and is never retried, or is retried and fails
    again, is correctly NOT recognized as recovered here -- there must
    be a genuinely later, same-phase, non-failure event."""
    phase = getattr(event, "phase", "")
    sequence = getattr(event, "sequence", 0)
    return any(
        getattr(later, "phase", "") == phase
        and getattr(later, "sequence", 0) > sequence
        and getattr(later, "status", "") not in ("failed", "blocked", "error", "timeout")
        for later in trace_info
    )


def _emit_failure_diagnostics(e, progress, trace_events):
    logger.error("[REAL-E2E] failure diagnostics:")

    trace_info = list(trace_events)
    if not trace_info:
        logger.error("  (no DiagnosticTrace events available)")
        logger.error("  last_completed_percentage: %s%%", progress.pct)
        return

    council_recovered = _council_reached_complete(trace_info)

    failed_event = None
    for event in reversed(trace_info):
        status = getattr(event, "status", "")
        if status not in ("failed", "blocked", "error", "timeout"):
            continue
        # CLAUDE-ADC-E2E-HUMAN-SELECTION-EMULATION-001: a per-agent
        # Engineering Council activity event (Agent A1/A2/A3 "failed" or
        # "timeout" on one retry attempt) that the Council itself went
        # on to RECOVER FROM (council_complete=True appears anywhere
        # later in this same trace) is a transient, already-resolved
        # retry -- never the terminal failure. Promoting it to the
        # top-level stage/actor/failure_category would misattribute the
        # real terminal defect (e.g. a later stage's own genuine
        # failure, or -- when nothing later actually failed at the
        # trace level -- no trace-level failure at all) to a non-issue
        # that already resolved itself. A genuinely UNRECOVERED
        # Council/agent failure (the Council never reached
        # council_complete=True) is never skipped here, and neither is
        # any failure on a phase other than engineering_council.
        if (
            council_recovered
            and getattr(event, "phase", "") == "engineering_council"
            and (getattr(event, "details", {}) or {}).get("actor")
        ):
            continue
        # KIB-ADC-RSE-DIAGNOSTIC-TRACE-TC-FIX-001: the same
        # already-resolved-transient-retry principle, generalized to
        # every phase (not just engineering_council) -- a stale
        # "testing" (or any other phase) failure that this SAME phase
        # itself later recovered from must not be promoted to the
        # top-level stage either. Reproduced concretely: a trace ending
        # in a genuinely successful controlled_git commit, with an
        # earlier transient "testing"-phase retry, previously reported
        # "stage: testing" even though the run demonstrably succeeded
        # all the way through Git commit.
        if _phase_later_recovered(trace_info, event):
            continue
        failed_event = event
        break

    council_events = _extract_council_activity(trace_info)
    latest_council = council_events[-1] if council_events else None

    source = failed_event or latest_council or trace_info[-1]
    details = getattr(source, "details", {}) or {}

    stage = details.get("execution_stage") or getattr(source, "phase", "")
    if stage:
        logger.error("  stage: %s", stage)
        for warning in _stage_interface_warnings(trace_info, stage):
            logger.error("  warning: %s", _safe_diagnostic_value(warning))

    actor = details.get("actor", "")
    if actor:
        logger.error("  actor: %s", actor)

    runtime_state = details.get("runtime_state", "")
    if runtime_state:
        logger.error("  runtime_state: %s", runtime_state)

    provider = details.get("provider", "")
    if provider:
        logger.error("  provider: %s", provider)

    model = details.get("model", "")
    if model:
        logger.error("  model: %s", model)

    error_category = details.get("error_category", "")
    if error_category:
        logger.error("  error_category: %s", error_category)

    failure_category = details.get("failure_category", "")
    if failure_category:
        logger.error("  failure_category: %s", failure_category)

    for event in trace_info:
        evt_details = getattr(event, "details", {}) or {}
        if evt_details.get("council_complete") is not None:
            logger.error("  council_complete: %s", evt_details["council_complete"])

    for event in council_events:
        evt_details = getattr(event, "details", {}) or {}
        evt_actor = evt_details.get("actor", "unknown")
        evt_status = getattr(event, "status", "unknown")
        evt_summary = getattr(event, "summary", "")
        evt_failure = evt_details.get("failure_category", "")
        parts = [f"    {evt_actor}: status={evt_status}"]
        if evt_failure:
            parts.append(f"failure_category={evt_failure}")
        if evt_summary:
            parts.append(f"summary={evt_summary}")
        logger.error("  ".join(parts))

    logger.error("  last_completed_percentage: %s%%", progress.pct)
    logger.error("  exception: %s: %s", type(e).__name__, _safe_exception_message(e))

    # CLAUDE-ADC-S23-RSE-PREFLIGHT-TEST-HARDENING-001, Part H: additive
    # only -- covers any OTHER code path where a NoEligibleEngineering
    # CandidateError reaches this generic handler directly (rather than
    # via the assert selection.admissible_variants branch above, which
    # already embeds the same evidence in its own message). Never
    # changes control flow, retries, or the pass/fail outcome.
    validations = getattr(e, "validations", None)
    if validations:
        rejected = [v for v in validations if not getattr(v, "admissible", True)]
        for line in _engineering_candidate_rejection_evidence_lines(rejected):
            logger.error("  %s", line)


def _safe_exception_message(e):
    message = str(e)
    for char in "\n\r\t":
        message = message.replace(char, " ")
    if len(message) > 500:
        message = message[:500] + "..."
    return message


def _safe_diagnostic_value(value):
    """Format an approved structured field without leaking embedded secrets."""
    if value is None:
        return "null"
    value = getattr(value, "value", value)
    text = str(value).replace("\n", " ").replace("\r", " ").replace("\t", " ")
    text = re.sub(
        r"(?i)((?:(?:api[_-]?key|token|password|credential)\s*[:=]\s*)|"
        r"(?:bearer\s+))[^\s,;]+",
        r"\1[REDACTED]",
        text,
    )
    return text[:300] + ("..." if len(text) > 300 else "")


def _redact_secrets_preserving_layout(text: str) -> str:
    """Redact obvious embedded secrets from already-bounded, multi-line
    diagnostic text (see _MAX_OUTPUT in app/verification.py) without
    collapsing newlines or truncating to a few hundred characters, which
    is what _safe_diagnostic_value does for short scalar fields and
    would destroy the readability of a labeled STDOUT/STDERR block."""
    return re.sub(
        r"(?i)((?:(?:api[_-]?key|token|password|credential)\s*[:=]\s*)|"
        r"(?:bearer\s+))[^\s,;]+",
        r"\1[REDACTED]",
        str(text),
    )


def _esphome_failure_evidence_lines(esphome_steps) -> list[str]:
    """Bounded, safe structured evidence for each failed ESPHome
    verification step, meant to make the next paid Real-System E2E
    failure fully diagnosable without needing to preserve the temp
    workspace.

    Reads only fields VerificationStepResult already carries (kind,
    status, return_code, the resolved controlled-execution command, the
    bounded diagnostics text, and truncation/stream-presence flags) --
    never environment variables, secrets, arbitrary project file
    contents, or LLM prompts/responses, none of which
    VerificationStepResult holds in the first place. A step's diagnostics
    text is redacted for obvious embedded secrets but otherwise printed
    as-is, since app.verification._build_step_result already bounds it
    to _MAX_OUTPUT.
    """
    lines = []
    for step in esphome_steps:
        if getattr(step, "status", None) == PASS.value:
            continue
        command = getattr(step, "command", None) or ()
        tool = command[0] if command else None
        lines.append(
            "ESPHome verification failure: "
            f"kind={_safe_diagnostic_value(getattr(step, 'verification_kind', None))} "
            f"status={_safe_diagnostic_value(getattr(step, 'status', None))} "
            f"return_code={_safe_diagnostic_value(getattr(step, 'return_code', None))} "
            f"tool={_safe_diagnostic_value(tool)} "
            f"stdout_present={bool(getattr(step, 'stdout', ''))} "
            f"stderr_present={bool(getattr(step, 'stderr', ''))} "
            f"truncated_output={bool(getattr(step, 'truncated_output', False))}"
        )
        diagnostics = getattr(step, "diagnostics", "")
        if diagnostics:
            lines.append(
                "  diagnostics:\n" + _redact_secrets_preserving_layout(diagnostics)
            )
    return lines


def _engineering_candidate_rejection_evidence_lines(rejected_candidates) -> list[str]:
    """CLAUDE-ADC-S23-RSE-PREFLIGHT-TEST-HARDENING-001, Part H: bounded,
    safe, structured evidence for every rejected S2.3 CandidateValidation
    (`rejected_candidates` is `EngineeringVariantSelection.rejected_variants`
    or `NoEligibleEngineeringCandidateError.validations` filtered to
    inadmissible ones -- both already the SAME structured objects S2.3
    itself produced). Diagnostic output only: never re-validates,
    auto-repairs, or otherwise feeds back into which candidates are
    admissible -- it only renders fields validate_variants() already
    computed, exactly mirroring _esphome_failure_evidence_lines()'s own
    reuse-only, no-secrets style."""
    lines = []
    for candidate in rejected_candidates:
        variant = getattr(candidate, "variant", None)
        candidate_id = getattr(variant, "id", None) if variant is not None else None
        lines.append(
            "S2.3 rejected candidate: "
            f"candidate_id={_safe_diagnostic_value(candidate_id)} "
            f"missing_binding_requirement_ids={_safe_diagnostic_value(list(getattr(candidate, 'missing_binding_requirement_ids', ())))} "
            f"verification_feasibility_gap_ids={_safe_diagnostic_value(list(getattr(candidate, 'verification_feasibility_gap_ids', ())))} "
            f"unmaterializable_items={_safe_diagnostic_value(list(getattr(candidate, 'unmaterializable_items', ())))} "
            f"platform_conflict={_safe_diagnostic_value(getattr(candidate, 'platform_conflict', None))}"
        )
    return lines


def _choose_human_selected_variant_id(selection: "EngineeringVariantSelection") -> str:
    """CLAUDE-ADC-E2E-HUMAN-SELECTION-EMULATION-001: TEST-HARNESS-ONLY
    human-selection emulation for the paused S2.4 Human Engineering
    Authority boundary (app.dev_workflow.DevelopmentWorkflow.run() stops
    here and returns setup_plan=None whenever at least one candidate is
    admissible -- see EngineeringVariantSelection's own docstring).

    Mirrors exactly the choice a real human makes at the SAME productive
    web boundary (app.web_api's engineering-decision endpoint,
    action="accept" vs action="select"): the Chairman recommendation is
    accepted only when it is ITSELF technically admissible; a candidate
    is never chosen merely because the Chairman recommended it. When the
    recommendation is inadmissible (or absent), an admissible
    alternative is chosen deterministically -- the lowest variant id,
    so a rerun of this harness against the same CouncilResult always
    emulates the identical human choice, never a random/order-dependent
    one. This function makes no product decision itself; it only
    decides which already-admissible id this TEST HARNESS will pass as
    `human_selected_variant_id` to the real
    DevelopmentWorkflow.resolve_engineering_selection() call, which is
    the sole productive authority that may turn it into an
    EngineeringDecision."""
    admissible_ids = {variant.id for variant in selection.admissible_variants}
    if not admissible_ids:
        raise AssertionError(
            "human-selection emulation has no admissible engineering "
            "candidate to choose from -- S2.3 must have rejected every "
            "candidate, which should already have raised "
            "NoEligibleEngineeringCandidateError before reaching here"
        )
    if selection.chairman_recommendation in admissible_ids:
        return selection.chairman_recommendation
    return sorted(admissible_ids)[0]


def _emit_planning_contract_mapping(plan_result, selected_variant_id):
    """Print Requirement → Preflight → selected toolchain → SetupStep.

    `selected_variant_id` MUST be the actual, resolved
    EngineeringDecision.variant.id -- i.e. the id
    DevelopmentWorkflow.resolve_engineering_selection() was actually
    called with (human_selected_variant_id), never
    `council.recommendation` (CDX-ADC-E2E-HUMAN-SELECTION-REVIEW-001,
    finding F1): the Chairman recommendation is only ever a suggestion
    and, when it is technically inadmissible, the emulated human
    correctly selects a DIFFERENT admissible candidate -- execution
    already follows that choice, so this evidence mapping must too.
    `council.recommendation` is still printed alongside, but purely as
    separate diagnostic metadata that is never conflated with the
    actual selection."""
    validation = plan_result.validation_result
    requirements = tuple(validation.normalized_requirements)
    preflight = plan_result.preflight_result
    preflight_by_id = {
        result.requirement_id: result for result in preflight.results
    }
    council = plan_result.council_result
    selected = next(
        (
            variant for variant in council.variants
            if variant.id == selected_variant_id
        ),
        None,
    )
    selected_items = tuple(selected.toolchain) if selected is not None else ()
    items_by_requirement = {}
    for item in selected_items:
        items_by_requirement.setdefault(item.requirement_ref, []).append(item)
    steps_by_requirement = {}
    for step in plan_result.setup_plan.steps:
        steps_by_requirement.setdefault(step.requirement_id, []).append(step)

    logger.info("[REAL-E2E] planning contract mapping:")
    logger.info(
        "  selected_variant: "
        f"id={_safe_diagnostic_value(getattr(selected, 'id', None))} "
        f"recommendation={_safe_diagnostic_value(council.recommendation)}"
    )
    requirement_ids = set()
    for requirement in requirements:
        requirement_ids.add(requirement.id)
        logger.info(
            "  Requirement: "
            f"id={_safe_diagnostic_value(requirement.id)} "
            f"name={_safe_diagnostic_value(requirement.name)} "
            f"type={_safe_diagnostic_value(requirement.type)} "
            f"required={_safe_diagnostic_value(requirement.required)} "
            f"install_method={_safe_diagnostic_value(requirement.install_method)}"
        )
        preflight_result = preflight_by_id.get(requirement.id)
        if preflight_result is not None:
            logger.info(
                "    -> Preflight: "
                f"requirement_id={_safe_diagnostic_value(preflight_result.requirement_id)} "
                f"present={_safe_diagnostic_value(preflight_result.present)} "
                f"satisfied={_safe_diagnostic_value(preflight_result.satisfied)} "
                f"detected_version={_safe_diagnostic_value(preflight_result.detected_version)}"
            )
        else:
            logger.info("    -> Preflight: no result")

        for item in items_by_requirement.get(requirement.id, ()):
            logger.info(
                "    -> selected ToolchainItem: "
                f"requirement_ref={_safe_diagnostic_value(item.requirement_ref)} "
                f"name={_safe_diagnostic_value(item.name)} "
                f"type={_safe_diagnostic_value(item.type)} "
                f"install_method={_safe_diagnostic_value(item.install_method)} "
                f"state={_safe_diagnostic_value(item.state)} "
                f"environment_constraint={_safe_diagnostic_value(item.environment_constraint)}"
            )
        if requirement.id not in items_by_requirement:
            logger.info("    -> selected ToolchainItem: none")

        for step in steps_by_requirement.get(requirement.id, ()):
            logger.info(
                "    -> SetupStep: "
                f"id={_safe_diagnostic_value(step.id)} "
                f"requirement_id={_safe_diagnostic_value(step.requirement_id)} "
                f"action={_safe_diagnostic_value(step.action)} "
                f"install_method={_safe_diagnostic_value(step.install_method)} "
                f"package={_safe_diagnostic_value(step.package)} "
                f"version={_safe_diagnostic_value(step.version)}"
            )
        if requirement.id not in steps_by_requirement:
            logger.info("    -> SetupStep: none")

    for requirement_ref, items in items_by_requirement.items():
        if requirement_ref in requirement_ids:
            continue
        for item in items:
            logger.info(
                "  Unmatched selected ToolchainItem: "
                f"requirement_ref={_safe_diagnostic_value(item.requirement_ref)} "
                f"name={_safe_diagnostic_value(item.name)} "
                f"type={_safe_diagnostic_value(item.type)} "
                f"install_method={_safe_diagnostic_value(item.install_method)} "
                f"state={_safe_diagnostic_value(item.state)} "
                f"environment_constraint={_safe_diagnostic_value(item.environment_constraint)}"
            )
    for requirement_id, steps in steps_by_requirement.items():
        if requirement_id in requirement_ids:
            continue
        for step in steps:
            logger.info(
                "  Unmatched SetupStep: "
                f"id={_safe_diagnostic_value(step.id)} "
                f"requirement_id={_safe_diagnostic_value(step.requirement_id)} "
                f"action={_safe_diagnostic_value(step.action)} "
                f"install_method={_safe_diagnostic_value(step.install_method)} "
                f"package={_safe_diagnostic_value(step.package)} "
                f"version={_safe_diagnostic_value(step.version)}"
            )


def _run(cmd, cwd):
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr.strip()
    return result


def _assert_hello_world(config_path):
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and "esphome" in data, (
        "ESPHome YAML must contain an 'esphome' top-level key"
    )
    esp32 = data.get("esp32") or {}
    assert esp32.get("board") == "esp32dev", (
        "ESP32 target must specify board: esp32dev"
    )
    assert "logger" in data, "ESPHome project must enable logging"
    intervals = data.get("interval") or []
    if isinstance(intervals, dict):
        intervals = [intervals]
    assert intervals, "ESPHome project must define a periodic mechanism (interval)"
    assert "Hello World" in str(intervals), (
        "Periodic mechanism must contain 'Hello World' text"
    )


def _handle_missing_esphome(components, project, run_id, council_result, dev_result):
    verification = dev_result.development_testing_result.verification_result
    assert verification is not None, "Development testing must produce a verification result"

    esphome_steps = [s for s in verification.steps if s.runner_type == "esphome_check"]
    if not any(s.status == TOOL_UNAVAILABLE.value for s in esphome_steps):
        return dev_result

    intelligence = components.service.build_intelligence(project)
    verification_plan = build_verification_plan(intelligence, run_id)

    request = MissingToolchainSetupRequest(
        project_id="real-esphome",
        project_root=str(project),
        toolchain="esphome",
        operation_type="validate",
        council_result=council_result,
        verification_plan=verification_plan,
        verification_result=verification,
    )
    prepare = components.service.prepare_missing_toolchain_setup(request)
    assert prepare.plan_id, f"Missing toolchain setup preparation failed: {prepare.blockers}"
    assert prepare.status == "pending_approval", prepare.status

    decide = components.service.decide_missing_toolchain_setup(
        prepare.plan_id, "approved",
        approved_by="real-e2e-operator",
        comment="Real-System E2E approves structured ESPHome install into isolated toolchain environment",
    )
    assert decide.status == "approved", f"Missing toolchain setup approval blocked: {decide.blockers}"

    execute = components.service.execute_missing_toolchain_setup(prepare.plan_id)
    assert execute.status in {"completed", "already_available"}, (
        f"ESPHome setup failed: {execute.blockers}"
    )

    retry = components.service.retry_missing_toolchain_verification(prepare.plan_id)
    assert retry.status == "verification_completed", retry.status
    assert retry.verification_result is not None

    return replace(
        dev_result,
        controlled_rework_result=replace(
            dev_result.controlled_rework_result,
            initial_result=replace(
                dev_result.controlled_rework_result.initial_result,
                verification_result=retry.verification_result,
            ),
        ),
    )


@pytest.mark.real_system
def test_real_esphome_esp32_hello_world_acceptance(monkeypatch, diagnostic_level):
    progress = _E2EProgress()
    progress.milestone(0, "test started")

    owned = Path(tempfile.mkdtemp(prefix="ai-dev-center-real-e2e-"))
    prior_cwd = Path.cwd()
    prior_path = os.environ.get("PATH", "")
    components = None
    run_id = None
    seen_trace_sequences = set()
    try:
        progress.milestone(5, "owned workspace ready")

        project = owned / "project"
        config_dest = owned / "ai-dev-center.yml"
        shutil.copy2(Path(__file__).parents[2] / "config" / "ai-dev-center.yml", config_dest)

        # --- Isolated toolchain environment ---
        toolchain_env = owned / "toolchain"
        venv.EnvBuilder(with_pip=True, clear=True).create(toolchain_env)
        progress.milestone(10, "isolated toolchain environment ready")

        monkeypatch.setenv("PATH", f"{toolchain_env / 'bin'}:{prior_path}")
        monkeypatch.chdir(owned)

        # CLAUDE-ADC-COUNCIL-DIAGNOSTIC-TRACE-INTEGRATION-FIX-001: the
        # central DiagnosticTrace's own events.jsonl is, by default,
        # anchored relative to the process's CURRENT working directory
        # (via WorkflowManager's own default storage path) -- which is
        # `owned` from the chdir() just above. Without an explicit
        # override it would be created and deleted alongside `owned` by
        # this test's own cleanup, taking the Council's diagnostic
        # evidence with it regardless of pass/fail. Anchoring explicitly
        # to the repository root (never CWD) keeps the SAME central
        # events.jsonl contract/format while surviving cleanup.
        diagnostic_trace_path = (
            Path(__file__).resolve().parents[2] / ".diagnostic-traces" / "events.jsonl"
        )
        components = build_canonical_components(
            str(config_dest), diagnostic_trace_path=diagnostic_trace_path,
        )
        run_id = f"real-e2e-{owned.name}"

        # --- Greenfield project ---
        components.service.materialize_approved_greenfield(GreenfieldProjectApproval(
            run_id, "real-esphome", str(project), "real-e2e-operator",
        ))
        progress.milestone(15, "greenfield project materialized")
        _run(["git", "config", "user.name", "AI Dev Center Real E2E"], project)
        _run(["git", "config", "user.email", "real-e2e@invalid.local"], project)

        # --- Planning with live trace visibility ---
        progress.info("planning start")
        stop_event = threading.Event()
        poll_thread = threading.Thread(
            target=_poll_trace_during_call,
            args=(progress, components.service.get_diagnostic_trace, run_id,
                  stop_event, seen_trace_sequences, diagnostic_level),
            daemon=True,
        )
        poll_thread.start()
        try:
            plan_result = components.service.plan_project_setup(
                "real-esphome", str(project), run_id,
                entry_interface="web",
                entry_data={"task_description": REAL_TASK},
            )
        finally:
            stop_event.set()
            poll_thread.join(timeout=5.0)

        # --- Post-planning: render events not observed by the final poll ---
        trace_events = components.service.get_diagnostic_trace(run_id)
        _render_new_trace_events(progress, trace_events, seen_trace_sequences, diagnostic_level)

        # --- S2.4 Human Engineering Authority: productive pause contract ---
        # CLAUDE-ARCH-S2-013C: run() ALWAYS stops here (setup_plan=None,
        # engineering_selection populated) whenever S2.3 found at least
        # one admissible candidate -- it never materializes a SetupPlan
        # on its own. Asserting that contract FIRST (rather than jumping
        # straight to a SetupPlan expectation) is what this task's
        # CLAUDE-ADC-E2E-HUMAN-SELECTION-EMULATION-001 fix corrects: the
        # harness's own prior assumption (a SetupPlan exists immediately
        # after plan_project_setup()) was stale against this
        # already-productive two-gate architecture, not a product defect.
        assert plan_result.setup_plan is None, (
            "SetupPlan must not exist before an explicit human "
            "engineering selection (S2.4) -- run() materialized one "
            "on its own, which would bypass the human-authority boundary"
        )
        selection = plan_result.engineering_selection
        assert selection is not None, (
            "no pending EngineeringVariantSelection artifact was returned "
            "-- the human engineering-selection boundary was not exposed"
        )
        assert isinstance(selection, EngineeringVariantSelection)
        assert selection.admissible_variants, (
            "no admissible engineering candidate is available for human "
            "selection; " + " | ".join(
                _engineering_candidate_rejection_evidence_lines(selection.rejected_variants)
            )
        )
        progress.milestone(
            35, "Engineering Council including Chairman completed; "
                "human engineering selection pending",
        )

        # --- Human Engineering Selection: TEST HARNESS EMULATION ONLY ---
        # Never product auto-selection: this chooses the SAME id a real
        # human would submit through app.web_api's engineering-decision
        # endpoint (accept the Chairman recommendation only when it is
        # itself admissible; otherwise pick a genuinely admissible
        # alternative), then submits it through the SAME productive
        # service boundary real application code uses
        # (DevelopmentWorkflow.resolve_engineering_selection() --
        # never a low-level decision/materializer call).
        human_selected_variant_id = _choose_human_selected_variant_id(selection)
        progress.info(
            "TEST HARNESS human-selection emulation: selecting variant "
            f"{human_selected_variant_id!r} "
            f"(chairman_recommendation={selection.chairman_recommendation!r})"
        )

        engineering_decision = select_engineering_variant(
            plan_result.council_result, plan_result.preflight_result, plan_result.platform,
            chairman_recommendation=selection.chairman_recommendation,
            human_selected_variant_id=human_selected_variant_id,
            trusted_verification_groups=trusted_verification_identity_groups(
                plan_result.project_intelligence,
            ),
        )
        assert engineering_decision.selection_authority == "human"
        assert engineering_decision.variant.id == human_selected_variant_id

        paused_result = plan_result
        plan_result = components.development_workflow.resolve_engineering_selection(
            paused_result.council_result, paused_result.preflight_result, paused_result.platform,
            "real-esphome", human_selected_variant_id=human_selected_variant_id,
            run_id=run_id, project_intelligence=paused_result.project_intelligence,
        )
        trace_events = components.service.get_diagnostic_trace(run_id)
        _render_new_trace_events(progress, trace_events, seen_trace_sequences, diagnostic_level)

        plan = plan_result.setup_plan
        assert plan is not None, "SetupPlan was not materialized"
        assert plan.status == "pending_approval", plan.status
        assert_no_silently_lost_active_setup_requirements(
            plan, paused_result.preflight_result,
        )
        _emit_planning_contract_mapping(
            replace(plan_result, validation_result=paused_result.validation_result),
            engineering_decision.variant.id,
        )
        progress.milestone(50, "Human engineering selection resolved; Setup Plan materialized")

        # --- Setup Approval through the REAL central lifecycle helpers ---
        # CLAUDE-ADC-RSE-CENTRAL-LIFECYCLE-001: the RSE previously called
        # SetupApproval.approve(plan) + service.execute_approved_setup_and_development(...)
        # directly, bypassing persist_setup_plan/approve_setup_plan/
        # execute_approved_plan_from_store. That shortcut skipped the entire
        # authorize_setup_plan_targets() -> register_setup_step_targets()
        # -> CapabilityRegistration -> ApprovalProvenance chain, so
        # Controlled Execution's B1 mutating-operations gate rejected the
        # install with "requires approval-provenance-backed capability".
        # Using the same central helpers Web/API adapters use closes that gap.
        from app.project_setup_application import (
            approve_setup_plan, execute_approved_plan_from_store, persist_setup_plan,
        )

        persist_setup_plan(components.plan_store, plan, plan_result.council_result)
        approve_setup_plan(
            components.service, components.plan_store,
            "real-esphome", plan.id, run_id,
        )
        progress.info(
            "setup/toolchain handling (approved plan execution starting: "
            "setup, then development/testing/rework as needed)"
        )

        # --- Execute approved setup and development through central helper ---
        # This single call runs the entire remaining setup_execution ->
        # development -> test_generation -> testing -> (diagnosis_review ->
        # controlled_rework)* lifecycle internally, potentially across
        # several rework cycles, before returning. Polling the
        # DiagnosticTrace live during the call (the same pattern already
        # used for planning) keeps the visible progress label honest
        # about which phase is actually running, instead of leaving
        # "setup/toolchain handling" on screen for the whole call.
        post_approval_stop_event = threading.Event()
        post_approval_poll_thread = threading.Thread(
            target=_poll_trace_during_call,
            args=(progress, components.service.get_diagnostic_trace, run_id,
                  post_approval_stop_event, seen_trace_sequences, diagnostic_level),
            daemon=True,
        )
        post_approval_poll_thread.start()
        try:
            dev_result = execute_approved_plan_from_store(
                components.service, components.plan_store,
                "real-esphome", plan.id,
                project, REAL_TASK, run_id,
            )
        finally:
            post_approval_stop_event.set()
            post_approval_poll_thread.join(timeout=5.0)

        # --- Post-execution: render events not observed by the final poll ---
        trace_events = components.service.get_diagnostic_trace(run_id)
        _render_new_trace_events(progress, trace_events, seen_trace_sequences, diagnostic_level)

        # --- ESPHome verification ---
        verification = _assert_verification_reached(dev_result, trace_events, run_id)
        esphome_steps = [s for s in verification.steps if s.runner_type == "esphome_check"]
        assert esphome_steps, "No ESPHome verification steps were produced"
        assert {s.verification_kind for s in esphome_steps} >= {"validate", "compile"}, (
            "ESPHome verification must include validate and compile steps"
        )

        # --- MissingToolchainSetup if ESPHome is unavailable ---
        if any(s.status == TOOL_UNAVAILABLE.value for s in esphome_steps):
            progress.info("missing toolchain recovery: ESPHome")
            dev_result = _handle_missing_esphome(
                components, project, run_id, plan_result.council_result, dev_result,
            )
            verification = dev_result.development_testing_result.verification_result
            esphome_steps = [s for s in verification.steps if s.runner_type == "esphome_check"]
            progress.info("missing toolchain recovery: ESPHome completed")

        progress.milestone(60, "setup/toolchain handling completed")
        progress.milestone(70, "Developer and required project files completed")

        validate_steps = [s for s in esphome_steps if s.verification_kind == "validate"]
        compile_steps = [s for s in esphome_steps if s.verification_kind == "compile"]

        if validate_steps and all(s.status == PASS.value for s in validate_steps):
            progress.milestone(80, "ESPHome validation completed")
        if (compile_steps and all(s.status == PASS.value for s in compile_steps)
                and progress.pct >= 80):
            progress.milestone(90, "ESPHome compile completed")

        for line in _esphome_failure_evidence_lines(esphome_steps):
            logger.error(line)

        assert all(s.status == PASS.value for s in esphome_steps), (
            "ESPHome verification steps failed: "
            f"{[(s.verification_kind, s.status) for s in esphome_steps]}"
        )

        # --- Semantic result acceptance ---
        configs = list(project.glob("**/*.yaml")) + list(project.glob("**/*.yml"))
        config_path = next(
            path for path in configs
            if "esphome:" in path.read_text(encoding="utf-8")
        )
        _assert_hello_world(config_path)

        # --- Final Approval ---
        approval = components.service.decide_final_approval(
            run_id, "approved", "real-e2e-operator",
            "Real validation and compile passed",
        )
        assert approval.ready_for_git, "Final approval must mark the result ready_for_git"
        progress.milestone(93, "development approval completed")

        # --- Controlled Git ---
        commit = components.service.commit_approved_run(
            run_id, project,
            "Create ESP32 ESPHome Hello World project",
        )
        assert commit.status == "committed" and commit.commit_hash, (
            f"Git commit failed: status={commit.status}, blockers={commit.blockers}"
        )
        assert not _run(["git", "status", "--porcelain"], project).stdout.strip(), (
            "Working tree must be clean after commit"
        )
        assert not _run(["git", "remote"], project).stdout.strip(), (
            "Local repository must have no remotes"
        )
        progress.milestone(96, "local Git commit completed")

        # --- Central Diagnostic Trace ---
        trace = components.service.get_diagnostic_trace(run_id)
        _render_new_trace_events(progress, trace, seen_trace_sequences, diagnostic_level)
        serialized = _validate_final_diagnostic_trace(trace, REAL_TASK)

        progress.milestone(98, "outcome and DiagnosticTrace validation completed")
        progress.milestone(100, "complete acceptance path passed")
        logger.info("[REAL-E2E] PASS")

    except Exception as e:
        progress.fail(str(e))
        if components is not None and run_id is not None:
            try:
                trace_events = components.service.get_diagnostic_trace(run_id)
                _render_new_trace_events(
                    progress, trace_events, seen_trace_sequences,
                    diagnostic_level,
                )
                _emit_failure_diagnostics(e, progress, trace_events)
            except Exception as diag_exc:
                logger.error(
                    "[REAL-E2E] unable to retrieve DiagnosticTrace: %s: %s",
                    type(diag_exc).__name__, _safe_exception_message(diag_exc),
                )
        raise

    finally:
        progress.cleanup_start()
        monkeypatch.chdir(prior_cwd)
        shutil.rmtree(owned, ignore_errors=False)
        assert not owned.exists(), "All test-owned resources must be removed on exit"
        progress.cleanup_done()
