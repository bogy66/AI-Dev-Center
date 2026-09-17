"""Manually invoked paid Real-System E2E.

Run only with:
  venv/bin/python -m pytest tests/real_system/real_system_e2e.py --real-system-e2e -s
"""
from dataclasses import replace
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
from app.greenfield_project import GreenfieldProjectApproval
from app.missing_toolchain_setup import MissingToolchainSetupRequest
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


def _poll_trace_during_planning(progress, get_trace, run_id, stop_event, seen_sequences, diagnostic_level="NONE"):
    """Background thread: poll DiagnosticTrace and report new events."""
    while not stop_event.wait(2.0):
        try:
            events = get_trace(run_id)
        except Exception:
            continue
        _render_new_trace_events(progress, events, seen_sequences, diagnostic_level)


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
            target=_poll_trace_during_planning,
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
            "selection"
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
        progress.info("setup/toolchain handling")

        # --- Execute approved setup and development through central helper ---
        dev_result = execute_approved_plan_from_store(
            components.service, components.plan_store,
            "real-esphome", plan.id,
            project, REAL_TASK, run_id,
        )

        # --- ESPHome verification ---
        verification = dev_result.development_testing_result.verification_result
        assert verification is not None
        esphome_steps = [s for s in verification.steps if s.runner_type == "esphome_check"]
        assert esphome_steps, "No ESPHome verification steps were produced"
        assert {s.verification_kind for s in esphome_steps} >= {"validate", "compile"}, (
            "ESPHome verification must include validate and compile steps"
        )

        # --- MissingToolchainSetup if ESPHome is unavailable ---
        if any(s.status == TOOL_UNAVAILABLE.value for s in esphome_steps):
            dev_result = _handle_missing_esphome(
                components, project, run_id, plan_result.council_result, dev_result,
            )
            verification = dev_result.development_testing_result.verification_result
            esphome_steps = [s for s in verification.steps if s.runner_type == "esphome_check"]
            progress.info("isolated toolchain installation completed")

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
        serialized = str([event.to_record() for event in trace])
        assert REAL_TASK in serialized, (
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
