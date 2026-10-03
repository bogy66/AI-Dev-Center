"""Gate-2 Productive-Path proof of the S5 -> S3.5 missing-toolchain recovery
through the normal Web / application entry path (IF_REQ_037, ARC_029).

Real, unmodified internal chain:
  Web /api/workflow/start -> real discovery / Engineering Council / S2.3
  -> Web engineering-decision (real S2.4/S2.5, plan persisted with its
  planning provenance) -> Web approval -> Web execute ->
  execute_approved_plan_from_store -> real S4 -> real S5 (real
  ESPHomeCheckRunner reports TOOL_UNAVAILABLE) -> production-owned
  route_tool_unavailable_to_recovery -> real S3.5 recovery record, paused
  at pending human approval -> explicit decision -> real structured
  installer resolution -> real PythonPackageExecutor (default runner and
  default post-install verifier) -> real execute_controlled -> real
  retry of the persisted VerificationPlan.

Only true external edges are substituted:
  - the LLM provider (deterministic JSON, the same technique as
    tests/test_productive_web_e2e.py);
  - the desktop terminal that would run `pip install` (a real
    DesktopTerminalProvider wired to a script that records the argv and,
    instead of downloading anything, leaves exactly the external effect a
    real install has: distribution metadata in the target interpreter's
    site-packages and the console script on PATH);
  - the installed CLI itself (a shell script whose exit code the test
    controls, so reverification can genuinely pass or fail).
PATH lookup (shutil.which), the post-install distribution query and the
availability check are the product's own, unsubstituted code.

The identities are deliberately distinct: requirement ids, the
distribution, the executable, the installation representation, the
installer identity and the recovery capability never coincide.
"""
from __future__ import annotations

from tests.terminal_final_child_probe import _SIMULATED_STATUS_SH

import json
import os
import shlex
import shutil
import stat
import venv
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.interactive_terminal as interactive_terminal_module
from app.canonical_composition import build_canonical_components
from app.interactive_terminal import DesktopTerminalProvider
from app.web_api import (
    WebSetupComponents, app, get_web_setup_components, planning_tasks, sessions,
)
from app.workflow_plan_store import WorkflowPlanStore

from tests.test_productive_web_e2e import DeterministicProvider

# ---------------------------------------------------------------------------
# Technology-neutral, pairwise-distinct identities (IF_REQ_037).
# ---------------------------------------------------------------------------
DIST_REF = "req-cli-distribution"          # Requirement id of the package item
CLI_REF = "req-firmware-cli"               # Requirement id of the executable item
DISTRIBUTION = "specimen-firmware-cli"     # package (distribution) identity
# The executable identity is owned by the real S5 runner that looks it up
# (ESPHomeCheckRunner); it is the only value this module does not choose.
EXECUTABLE = "esphome"
INSTALL_REPRESENTATION = f"python -m pip install {DISTRIBUTION}"
INSTALLER_IDENTITY = "pip"                 # structured installer registry key
RECOVERY_CAPABILITY = "python"             # capability the recovery executes under

IDENTITIES = (DIST_REF, CLI_REF, DISTRIBUTION, EXECUTABLE,
              INSTALL_REPRESENTATION, INSTALLER_IDENTITY, RECOVERY_CAPABILITY)


class _ProductiveProvider(DeterministicProvider):
    """External LLM JSON only; every consumer of it is real."""

    def complete(self, prompt, max_tokens=None):
        if "You are the Developer of AI-Dev-Center" in prompt:
            self.prompts.append(prompt)
            return json.dumps({"changes": [{
                "file": "device.yaml", "action": "create",
                "content": "esphome:\n  name: specimen\n",
            }], "tests": []})
        if "You are the Tester of AI-Dev-Center" in prompt:
            self.prompts.append(prompt)
            return json.dumps({
                "disposition": "no_changes_required", "changes": [], "tests": [],
                "reason": "firmware verification covers the change",
            })
        if "You are the Diagnosis Reviewer" in prompt:
            raise AssertionError("TOOL_UNAVAILABLE must never reach the diagnosis reviewer")
        payload = json.loads(super().complete(prompt))
        toolchain = [
            {"requirement_ref": DIST_REF, "name": "Firmware CLI distribution",
             "type": "python_package", "technical_identity": DISTRIBUTION,
             "install_method": INSTALL_REPRESENTATION, "state": "needs_install"},
            {"requirement_ref": CLI_REF, "name": "Firmware validation CLI",
             "type": "executable", "technical_identity": EXECUTABLE,
             "provided_by": DIST_REF, "state": "needs_install"},
        ]
        if self.role == "discovery":
            # Inactive for the current request: S3 legitimately DEFERS both,
            # so S5 is what discovers the missing executable.
            payload = {"requirements": [
                {"id": DIST_REF, "name": "Firmware CLI distribution",
                 "type": "python_package", "technical_identity": DISTRIBUTION,
                 "purpose": "Provides the firmware validation CLI",
                 "required": True, "confidence": "high", "evidence": ["esphome.yaml"],
                 "active_for_current_request": False, "blocks_current_operation": False},
                {"id": CLI_REF, "name": "Firmware validation CLI", "type": "executable",
                 "purpose": "Validates the firmware configuration",
                 "required": True, "confidence": "high", "evidence": ["esphome.yaml"],
                 "active_for_current_request": False, "blocks_current_operation": False},
            ]}
        elif "variants" in payload:
            for variant in payload["variants"]:
                variant["toolchain"] = toolchain
                variant["environment"] = "venv"
        return json.dumps(payload)


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


class _ExternalWorld:
    """The true external edges: host PATH, the install terminal, the CLI."""

    def __init__(self, root: Path, project: Path):
        self.host_bin = root / "host-bin"
        self.host_bin.mkdir()
        self.terminal_record = root / "terminal-argv.log"
        self.cli_exit_code = root / "cli-exit-code"
        self.cli_exit_code.write_text("0", encoding="utf-8")
        self.cli_invocations = root / "cli-invocations.log"
        self.target_python = project / ".venv" / "bin" / "python"
        self.site_packages = next((project / ".venv" / "lib").glob("python*/site-packages"))

    def installing_terminal(self) -> DesktopTerminalProvider:
        """A real DesktopTerminalProvider whose terminal binary records the
        wrapped argv and, instead of running pip, leaves the external effect
        of installing DISTRIBUTION: its metadata and its console script.
        STATUS-V3 is an explicit consumer simulation here, not proof of
        an installation command completing; no pip command runs."""
        cli_script = (
            "#!/bin/sh\n"
            f"echo \"$@\" >> {shlex.quote(str(self.cli_invocations))}\n"
            f"exit \"$(cat {shlex.quote(str(self.cli_exit_code))})\"\n"
        )
        dist_info = self.site_packages / f"{DISTRIBUTION.replace('-', '_')}-1.0.0.dist-info"
        terminal = self.host_bin.parent / "terminal-bin" / "adc-installing-terminal"
        terminal.parent.mkdir()
        _write_executable(terminal, (
            "#!/bin/sh\n"
            "shift 4\n"
            'status_path="$1"\n'
            "shift\n"
            'for arg in "$@"; do\n'
            f"    printf '%s\\n' \"$arg\" >> {shlex.quote(str(self.terminal_record))}\n"
            "done\n"
            f"printf '%s\\n' '--' >> {shlex.quote(str(self.terminal_record))}\n"
            f"if [ \"$2 $3 $4 $5\" = \"-m pip install {DISTRIBUTION}\" ]; then\n"
            f"    mkdir -p {shlex.quote(str(dist_info))}\n"
            f"    printf 'Metadata-Version: 2.1\\nName: {DISTRIBUTION}\\nVersion: 1.0.0\\n' "
            f"> {shlex.quote(str(dist_info / 'METADATA'))}\n"
            # pip installs the console script into the TARGET environment's
            # bin directory; nothing is placed on the host PATH.
            f"    cat > {shlex.quote(str(self.target_python.parent / EXECUTABLE))} <<'ADC_CLI'\n"
            f"{cli_script}"
            "ADC_CLI\n"
            f"    chmod +x {shlex.quote(str(self.target_python.parent / EXECUTABLE))}\n"
            "fi\n"
            + _SIMULATED_STATUS_SH
        ))
        return DesktopTerminalProvider(candidates=((str(terminal), ()),))

    def terminal_invocations(self) -> list[list[str]]:
        if not self.terminal_record.exists():
            return []
        runs, current = [], []
        for line in self.terminal_record.read_text(encoding="utf-8").splitlines():
            if line == "--":
                runs.append(current)
                current = []
            else:
                current.append(line)
        return runs

    def cli_calls(self) -> list[str]:
        if not self.cli_invocations.exists():
            return []
        return self.cli_invocations.read_text(encoding="utf-8").splitlines()


@pytest.fixture
def productive_web_recovery(tmp_path, monkeypatch, request):
    owned_root = tmp_path / "adc-recovery"
    owned_root.mkdir()
    project = owned_root / "project"
    project.mkdir()
    (project / "README.md").write_text("# Specimen firmware project\n", encoding="utf-8")
    (project / "esphome.yaml").write_text("esphome:\n  name: specimen\n", encoding="utf-8")
    # The selected candidate's own "venv" environment: a real, pip-less
    # project interpreter (no installer module ever runs).
    venv.EnvBuilder(with_pip=False, clear=True, symlinks=True).create(project / ".venv")
    config_path = owned_root / "config" / "ai-dev-center.yml"
    config_path.parent.mkdir()
    shutil.copy2(Path(__file__).parents[1] / "config" / "ai-dev-center.yml", config_path)
    world = _ExternalWorld(owned_root, project)
    monkeypatch.setenv("PATH", os.pathsep.join((str(world.host_bin), "/usr/bin", "/bin")))
    monkeypatch.setattr(
        interactive_terminal_module, "DesktopTerminalProvider", world.installing_terminal,
    )
    original_cwd = Path.cwd()
    monkeypatch.chdir(owned_root)
    providers = {role: _ProductiveProvider(role) for role in (
        "discovery", "environment_architect", "toolchain_integrator", "risk_assessor", "chairman",
    )}
    monkeypatch.setattr(
        "app.canonical_composition.create_llm_provider",
        lambda *_args, **_kwargs: providers["discovery"],
    )
    monkeypatch.setattr(
        "app.engineering_council.create_council_provider",
        lambda config, *_args, **_kwargs: providers[config.role],
    )
    canonical = build_canonical_components(str(config_path))
    components = WebSetupComponents(
        canonical.service, canonical.plan_store, canonical.approval,
        canonical.development_workflow,
    )
    app.dependency_overrides[get_web_setup_components] = lambda: components
    try:
        yield project, components, world
    finally:
        for task in tuple(planning_tasks.values()):
            task.result(timeout=5)
        sessions.clear()
        app.dependency_overrides.clear()
        monkeypatch.chdir(original_cwd)


def _web_execute(client, project, *, before_execute=None):
    started = client.post("/api/workflow/start", json={
        "project_name": "specimen-recovery", "project_directory": str(project),
        "task_description": "Add the specimen device configuration.",
    })
    assert started.status_code == 202, started.text
    session_id = started.json()["session_id"]
    task = planning_tasks.get(session_id)
    if task is not None:
        task.result(timeout=30)
    state = client.get(f"/api/state/{session_id}").json()
    assert state["workflow_status"] == "pending_engineering_selection", state
    accepted = client.post(f"/api/workflow/{session_id}/engineering-decision", json={"action": "accept"})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["selection_authority"] == "human"
    approved = client.post(f"/api/workflow/{session_id}/approval")
    assert approved.status_code == 200, approved.text
    session = sessions[session_id]
    if before_execute is not None:
        before_execute(session)
    executed = client.post(f"/api/workflow/{session_id}/execute")
    assert executed.status_code == 200, executed.text
    return session, executed.json()


def _recovery_record(components, plan_id):
    return components.service._workflow_manager.get_missing_toolchain_setup(plan_id)


def test_web_execution_routes_tool_unavailable_to_approval_bound_recovery_with_distinct_identities(
    productive_web_recovery,
):
    project, components, world = productive_web_recovery
    assert len(set(IDENTITIES)) == len(IDENTITIES)
    service = components.service

    with TestClient(app) as client:
        session, body = _web_execute(client, project)

    # Planning provenance: the exact WorkflowResult the Web adapter
    # persisted with the plan, never a caller argument.
    planning = components.plan_store.load_planning_result(session.project_id, session.plan_id)
    decision = planning.engineering_decision
    assert decision.selection_authority == "human"
    assert planning.setup_plan.steps == ()  # inactive + needs_install -> DEFERRED
    assert set(planning.setup_plan.deferred_requirement_ids) == {DIST_REF, CLI_REF}

    # Real S5 producer -> real TOOL_UNAVAILABLE -> production-owned routing.
    assert body["development_status"] == "tool_unavailable"
    recovery = body["missing_toolchain_recovery"]
    assert recovery["status"] == "pending_approval", recovery
    record = _recovery_record(components, recovery["plan_id"])
    assert record["status"] == "pending_approval"
    assert record["project_id"] == session.project_id
    assert record["run_id"] == session.run_id
    assert record["verification_result"]["run_id"] == session.run_id
    assert record["verification_result"]["aggregate_status"] == "fail"
    assert record["verification_result"]["unavailable_step_ids"]
    assert set(record["verification_result"]["unavailable_step_ids"]) <= {
        step["step_id"] for step in record["verification_plan"]["steps"]
    }
    assert record["chairman_approval_ref"] == decision.variant.id
    assert record["council_result_id"] == planning.council_result.id
    assert record["selection_authority"] == "human"
    # IF_REQ_037 relations, each a different value.
    assert record["toolchain"] == EXECUTABLE
    assert record["provisioning_requirement_ref"] == DIST_REF
    assert record["package_identity"] == DISTRIBUTION
    assert record["install_method"] == INSTALL_REPRESENTATION
    assert record["installer_identity"] == INSTALLER_IDENTITY
    (step,) = record["setup_plan"]["steps"]
    assert step["requirement_id"] == DIST_REF
    assert step["package"] == DISTRIBUTION
    assert step["target_executable"] == str(world.target_python)
    assert record["verification_retry_status"] == "pending"

    # Human authority: no decision -> no mutating terminal invocation.
    assert service.execute_missing_toolchain_setup(recovery["plan_id"]).status == "pending_approval"
    assert world.terminal_invocations() == []
    assert service.decide_missing_toolchain_setup(recovery["plan_id"], "approved", "human").status == "approved"

    executed = service.execute_missing_toolchain_setup(recovery["plan_id"])
    assert executed.status == "completed", executed.blockers
    assert world.terminal_invocations() == [
        [str(world.target_python), "-m", "pip", "install", DISTRIBUTION],
    ]
    registration = service._capability_registry.get(RECOVERY_CAPABILITY, str(project.resolve()))
    assert registration is not None
    assert registration.approval_provenance.chairman_approval_ref == decision.variant.id

    # Real reverification of the persisted S5 plan passes -> completed.
    retried = service.retry_missing_toolchain_verification(recovery["plan_id"])
    assert retried.status == "verification_completed", (retried.blockers, [(r.status, r.diagnostics) for r in (retried.verification_result.steps if retried.verification_result else ())])
    assert retried.verification_result.aggregate_status == "pass"
    assert retried.verification_result.run_id == session.run_id
    assert world.cli_calls()
    assert _recovery_record(components, recovery["plan_id"])["verification_retry_status"] == "completed"

    # Bounded: no second install, no second recovery record.
    assert service.execute_missing_toolchain_setup(recovery["plan_id"]).status == "completed"
    assert len(world.terminal_invocations()) == 1
    assert list(service._workflow_manager.load()["missing_toolchain_setups"]) == [recovery["plan_id"]]


def test_failed_reverification_ends_recovery_fail_closed_without_a_second_cycle(
    productive_web_recovery,
):
    project, components, world = productive_web_recovery
    world.cli_exit_code.write_text("1", encoding="utf-8")  # the installed CLI rejects the config
    service = components.service

    with TestClient(app) as client:
        _, body = _web_execute(client, project)
    plan_id = body["missing_toolchain_recovery"]["plan_id"]
    service.decide_missing_toolchain_setup(plan_id, "approved", "human")
    assert service.execute_missing_toolchain_setup(plan_id).status == "completed"

    retried = service.retry_missing_toolchain_verification(plan_id)
    assert retried.status == "verification_failed"
    assert retried.verification_result.aggregate_status == "fail"
    assert retried.blockers == ("Reverification after recovery did not pass: fail",)
    record = _recovery_record(components, plan_id)
    assert record["verification_retry_status"] == "failed"
    assert record["verification_retry_aggregate"] == "fail"
    calls = world.cli_calls()

    # Terminal: never re-run, never a second install, never a new recovery.
    again = service.retry_missing_toolchain_verification(plan_id)
    assert again.status == "verification_failed" and again.verification_result is None
    assert world.cli_calls() == calls
    assert service.execute_missing_toolchain_setup(plan_id).status == "completed"
    assert len(world.terminal_invocations()) == 1
    assert list(service._workflow_manager.load()["missing_toolchain_setups"]) == [plan_id]


def test_missing_planning_provenance_fails_closed_before_any_recovery(productive_web_recovery):
    """A plan whose planning provenance is not bound (e.g. a store
    reloaded after a process restart) is still routed, and the routing
    fails closed instead of reselecting a variant."""
    project, components, world = productive_web_recovery

    def reload_store(session):
        session.plan_store = WorkflowPlanStore(components.plan_store.root)

    with TestClient(app) as client:
        _, body = _web_execute(client, project, before_execute=reload_store)

    assert body["development_status"] == "tool_unavailable"
    recovery = body["missing_toolchain_recovery"]
    assert recovery == {
        "plan_id": "", "status": "rejected",
        "blockers": ["Selected EngineeringDecision is required for recovery"],
    }
    assert components.service._workflow_manager.load().get("missing_toolchain_setups", {}) == {}
    assert world.terminal_invocations() == []
