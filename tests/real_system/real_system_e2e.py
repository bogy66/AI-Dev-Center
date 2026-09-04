"""Manually invoked paid Real-System E2E.

Run only with:
  venv/bin/python -m pytest tests/real_system/real_system_e2e.py --real-system-e2e -s
"""
from dataclasses import replace
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
import venv

import pytest
import yaml

from app.canonical_composition import build_canonical_components
from app.diagnostic_trace import DiagnosticDetailLevel, render_diagnostic_trace_event
from app.greenfield_project import GreenfieldProjectApproval
from app.missing_toolchain_setup import MissingToolchainSetupRequest
from app.setup_approval import SetupApproval
from app.verification import PASS, TOOL_UNAVAILABLE, build_verification_plan


REAL_TASK = 'Create an ESPHome project for an ESP32 that logs "Hello World" periodically.'


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
        print(f"[REAL-E2E][{pct}%][{self._elapsed()}] {label}")

    def info(self, label):
        with self._LOCK:
            pct = self._pct
        print(f"[REAL-E2E][{pct}%][{self._elapsed()}] {label}")

    def cleanup_start(self):
        print("[REAL-E2E] cleanup started")

    def cleanup_done(self):
        print("[REAL-E2E] cleanup completed")

    def fail(self, label):
        with self._LOCK:
            pct = self._pct
        print(f"[REAL-E2E][{pct}%][{self._elapsed()}] FAIL: {label}")
        print(f"[REAL-E2E][{pct}%] E2E completion at failure")


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
            print(rendered)


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


def _emit_failure_diagnostics(e, progress, trace_events):
    print("[REAL-E2E] failure diagnostics:")

    trace_info = list(trace_events)
    if not trace_info:
        print("  (no DiagnosticTrace events available)")
        print(f"  last_completed_percentage: {progress.pct}%")
        return

    failed_event = None
    for event in reversed(trace_info):
        status = getattr(event, "status", "")
        if status in ("failed", "blocked", "error", "timeout"):
            failed_event = event
            break

    council_events = _extract_council_activity(trace_info)
    latest_council = council_events[-1] if council_events else None

    source = failed_event or latest_council or trace_info[-1]
    details = getattr(source, "details", {}) or {}

    stage = details.get("execution_stage") or getattr(source, "phase", "")
    if stage:
        print(f"  stage: {stage}")

    actor = details.get("actor", "")
    if actor:
        print(f"  actor: {actor}")

    runtime_state = details.get("runtime_state", "")
    if runtime_state:
        print(f"  runtime_state: {runtime_state}")

    provider = details.get("provider", "")
    if provider:
        print(f"  provider: {provider}")

    model = details.get("model", "")
    if model:
        print(f"  model: {model}")

    error_category = details.get("error_category", "")
    if error_category:
        print(f"  error_category: {error_category}")

    failure_category = details.get("failure_category", "")
    if failure_category:
        print(f"  failure_category: {failure_category}")

    for event in trace_info:
        evt_details = getattr(event, "details", {}) or {}
        if evt_details.get("council_complete") is not None:
            print(f"  council_complete: {evt_details['council_complete']}")

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
        print("  ".join(parts))

    print(f"  last_completed_percentage: {progress.pct}%")
    print(f"  exception: {type(e).__name__}: {_safe_exception_message(e)}")


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


def _emit_planning_contract_mapping(plan_result):
    """Print Requirement → Preflight → selected toolchain → SetupStep."""
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
            if variant.id == council.recommendation
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

    print("[REAL-E2E] planning contract mapping:")
    print(
        "  selected_variant: "
        f"id={_safe_diagnostic_value(getattr(selected, 'id', None))} "
        f"recommendation={_safe_diagnostic_value(council.recommendation)}"
    )
    requirement_ids = set()
    for requirement in requirements:
        requirement_ids.add(requirement.id)
        print(
            "  Requirement: "
            f"id={_safe_diagnostic_value(requirement.id)} "
            f"name={_safe_diagnostic_value(requirement.name)} "
            f"type={_safe_diagnostic_value(requirement.type)} "
            f"required={_safe_diagnostic_value(requirement.required)} "
            f"install_method={_safe_diagnostic_value(requirement.install_method)}"
        )
        preflight_result = preflight_by_id.get(requirement.id)
        if preflight_result is not None:
            print(
                "    -> Preflight: "
                f"requirement_id={_safe_diagnostic_value(preflight_result.requirement_id)} "
                f"present={_safe_diagnostic_value(preflight_result.present)} "
                f"satisfied={_safe_diagnostic_value(preflight_result.satisfied)} "
                f"detected_version={_safe_diagnostic_value(preflight_result.detected_version)}"
            )
        else:
            print("    -> Preflight: no result")

        for item in items_by_requirement.get(requirement.id, ()):
            print(
                "    -> selected ToolchainItem: "
                f"requirement_ref={_safe_diagnostic_value(item.requirement_ref)} "
                f"name={_safe_diagnostic_value(item.name)} "
                f"type={_safe_diagnostic_value(item.type)} "
                f"install_method={_safe_diagnostic_value(item.install_method)} "
                f"state={_safe_diagnostic_value(item.state)} "
                f"environment_constraint={_safe_diagnostic_value(item.environment_constraint)}"
            )
        if requirement.id not in items_by_requirement:
            print("    -> selected ToolchainItem: none")

        for step in steps_by_requirement.get(requirement.id, ()):
            print(
                "    -> SetupStep: "
                f"id={_safe_diagnostic_value(step.id)} "
                f"requirement_id={_safe_diagnostic_value(step.requirement_id)} "
                f"action={_safe_diagnostic_value(step.action)} "
                f"install_method={_safe_diagnostic_value(step.install_method)} "
                f"package={_safe_diagnostic_value(step.package)} "
                f"version={_safe_diagnostic_value(step.version)}"
            )
        if requirement.id not in steps_by_requirement:
            print("    -> SetupStep: none")

    for requirement_ref, items in items_by_requirement.items():
        if requirement_ref in requirement_ids:
            continue
        for item in items:
            print(
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
            print(
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

        components = build_canonical_components(str(config_dest))
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

        plan = plan_result.setup_plan
        assert plan is not None, "SetupPlan was not materialized"
        assert plan.status == "pending_approval", plan.status
        _emit_planning_contract_mapping(plan_result)
        progress.milestone(50, "Engineering Council including Chairman completed")

        # --- Setup Approval ---
        approved_plan = SetupApproval.approve(plan)
        assert approved_plan.status == "approved"
        progress.info("setup/toolchain handling")

        # --- Execute approved setup and development ---
        dev_result = components.service.execute_approved_setup_and_development(
            approved_plan, "real-esphome", project, REAL_TASK, run_id,
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

        assert all(s.status == PASS.value for s in esphome_steps), (
            f"ESPHome verification steps failed: "
            f"{[(s.verification_kind, s.status, s.diagnostics) for s in esphome_steps]}"
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
        print("[REAL-E2E] PASS")

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
                print(f"[REAL-E2E] unable to retrieve DiagnosticTrace: {type(diag_exc).__name__}: {_safe_exception_message(diag_exc)}")
        raise

    finally:
        progress.cleanup_start()
        monkeypatch.chdir(prior_cwd)
        shutil.rmtree(owned, ignore_errors=False)
        assert not owned.exists(), "All test-owned resources must be removed on exit"
        progress.cleanup_done()
