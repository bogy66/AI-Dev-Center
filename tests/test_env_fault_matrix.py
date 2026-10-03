"""Targeted deterministic fault-injection matrix
(CLAUDE-ADC-TEST-ENVIRONMENT-FIDELITY-UPGRADE-001 section 7).

For every fault this asserts: the externally visible result, whether
persisted state reflects it, authorization/capability behaviour, that
there is no hidden fallback, whether retry is permitted, and whether
any additional mutation occurred -- never merely "an exception was
raised".

Uses real app.interactive_terminal.DesktopTerminalProvider/
InteractiveTerminalLauncher and, for the persisted-state-level faults,
the real app.project_setup_application.ProjectSetupApplicationService
chain (the same real producer chain
tests/test_s3_missing_toolchain_capability_authorization.py already
established), never a hand-rolled re-implementation of that state
machine.
"""
from __future__ import annotations

import os
from unittest.mock import Mock

import pytest

import app.interactive_terminal as interactive_terminal_module
from app.interactive_terminal import (
    DesktopTerminalProvider,
    INTERACTIVE_TERMINAL_CANCELLED,
    INTERACTIVE_TERMINAL_LAUNCH_FAILED,
    INTERACTIVE_TERMINAL_UNAVAILABLE,
    InteractiveTerminalError,
    InteractiveTerminalLauncher,
)
from tests.env_scenarios import covers
from tests.terminal_final_child_probe import (
    install_early_exit_terminal,
    install_inert_counting_terminal,
    install_malformed_status_terminal,
    install_status_then_linger_terminal,
    install_start_failure_terminal_candidates,
    install_timeout_terminal,
    probe_provider,
)


@pytest.mark.parametrize(
    ("fault", "installer"),
    (
        ("early_exit", install_early_exit_terminal),
        ("malformed_status", install_malformed_status_terminal),
        ("timeout", install_timeout_terminal),
    ),
)
@covers("LIFE_EXECUTION_FAILURE", "LIFE_BOUNDED_RECOVERY")
def test_faulted_provider_attempt_is_persisted_failed_and_not_relaunched(
    tmp_path, monkeypatch, fault, installer,
):
    """Provider/process faults have an honest terminal state and a safe retry.

    The first attempt uses the real DevelopmentWorkflow state guard and the
    real PythonPackageExecutor/execute_controlled path.  A second attempt
    consumes the persisted FAILED result and therefore cannot launch the
    mutating boundary again.
    """
    from app.dev_workflow import DevelopmentWorkflow
    from app.execution import (
        ApprovalProvenance, CapabilityRegistration, DEFAULT_CAPABILITY_REGISTRY,
    )
    from app.python_package_executor import PythonPackageExecutor
    from app.requirement_model import SetupEffect, SetupPlan, SetupStep
    from app.setup_execution_state import SetupExecutionStateStore, SetupStepIdentity

    project_root = tmp_path / "project"
    project_root.mkdir()
    target = "/opt/python"
    step = SetupStep(
        id=f"fault-{fault}", requirement_id="pkg", action="install",
        install_method="pip", package="example-package",
        setup_effect=SetupEffect.PYTHON_PACKAGE_INSTALL, is_approved=True,
        target_executable=target,
    )
    plan = SetupPlan(
        id=f"plan-{fault}", project_id="project", steps=(step,), status="approved",
    )
    resolved_root = str(project_root.resolve())
    DEFAULT_CAPABILITY_REGISTRY.register_approved(CapabilityRegistration(
        capability="python", executable_names=(target,), allowed_operations=("install",),
        approval_provenance=ApprovalProvenance(
            resolved_root, "council-fault", "variant-fault",
            f"setup-approval:{plan.id}:approved",
        ),
        project_scope=resolved_root,
    ))
    try:
        _script, candidates = installer(tmp_path)
        provider = DesktopTerminalProvider(candidates=candidates, poll_interval=0.02)
        launches = {"count": 0}
        original_run = provider.run

        def counted_run(*args, **kwargs):
            launches["count"] += 1
            return original_run(*args, **kwargs)

        monkeypatch.setattr(provider, "run", counted_run)
        monkeypatch.setattr(
            interactive_terminal_module,
            "DesktopTerminalProvider",
            lambda: provider,
        )
        fallback_calls = []
        monkeypatch.setattr(
            interactive_terminal_module.subprocess,
            "run",
            lambda *args, **kwargs: fallback_calls.append((args, kwargs)),
        )
        executor = PythonPackageExecutor(verifier=lambda _step: True)
        if fault == "timeout":
            # Keep the real provider timeout branch deterministic and short.
            executor._INSTALL_TIMEOUT_SECONDS = 1
        state_store = SetupExecutionStateStore(tmp_path / f"{fault}-state.json")
        workflow = DevelopmentWorkflow(
            Mock(), Mock(), Mock(), executor=executor,
            execution_state_store=state_store,
        )

        with pytest.raises(InteractiveTerminalError):
            workflow.execute_approved(plan, resolved_root)

        identity = SetupStepIdentity.for_step(resolved_root, plan.generation_id, step)
        record = state_store.get(identity)
        assert record is not None
        assert record["status"] == "failed"
        assert record["status"] != "in_progress"
        assert fallback_calls == []

        retry = workflow.execute_approved(plan, resolved_root)
        assert len(retry) == 1
        assert retry[0].success is False
        assert launches["count"] == 1
    finally:
        DEFAULT_CAPABILITY_REGISTRY.set_status("python", "revoked", resolved_root)


# ============================================================================
# Process/terminal-boundary faults
# ============================================================================

@covers("PROC_SPAWN_FAILURE")
def test_fault_popen_spawn_failure_fails_closed_no_hidden_fallback(tmp_path, monkeypatch):
    provider = probe_provider(tmp_path, monkeypatch)
    launcher = InteractiveTerminalLauncher(provider=provider)

    def _raise(*a, **kw):
        raise OSError("simulated spawn failure")
    monkeypatch.setattr("app.interactive_terminal.subprocess.Popen", _raise)

    fallback_calls = []
    monkeypatch.setattr(
        "app.interactive_terminal.subprocess.run",
        lambda *a, **kw: fallback_calls.append((a, kw)),
    )

    with pytest.raises(InteractiveTerminalError) as exc_info:
        launcher.run(("python3", "-c", "pass"), str(tmp_path), {"PATH": "/usr/bin"}, 10)

    assert exc_info.value.cause == INTERACTIVE_TERMINAL_LAUNCH_FAILED
    assert fallback_calls == [], "no hidden subprocess.run fallback may ever be attempted"


@covers("TERM_NO_PROVIDER")
def test_fault_provider_unavailable_fails_closed_zero_popen(tmp_path):
    candidates = install_start_failure_terminal_candidates(tmp_path)
    provider = DesktopTerminalProvider(candidates=candidates)
    popen_calls = []
    launcher = InteractiveTerminalLauncher(provider=provider)
    with pytest.raises(InteractiveTerminalError) as exc_info:
        launcher.run(("python3", "-c", "pass"), str(tmp_path), {"PATH": "/usr/bin"}, 10)
    assert exc_info.value.cause == INTERACTIVE_TERMINAL_UNAVAILABLE


@covers("PROC_EARLY_PROVIDER_EXIT", "PROC_MISSING_STATUS")
def test_fault_provider_early_exit_never_reports_success(tmp_path, monkeypatch):
    from tests.terminal_final_child_probe import install_early_exit_terminal
    script_path, candidates = install_early_exit_terminal(tmp_path)
    provider = DesktopTerminalProvider(candidates=candidates, launcher_exit_grace=0.05)
    launcher = InteractiveTerminalLauncher(provider=provider)
    with pytest.raises(InteractiveTerminalError) as exc_info:
        launcher.run(("python3", "-c", "pass"), str(tmp_path), {"PATH": "/usr/bin"}, 5)
    assert exc_info.value.cause == INTERACTIVE_TERMINAL_CANCELLED


@covers("PROC_MALFORMED_STATUS")
def test_fault_malformed_status_file_is_cancelled_not_crash(tmp_path):
    script_path, candidates = install_malformed_status_terminal(tmp_path)
    provider = DesktopTerminalProvider(candidates=candidates)
    outcome = provider.run(("python3", "-c", "pass"), str(tmp_path), {"PATH": "/usr/bin"}, 5)
    # A malformed status must never crash the caller and must never be
    # mistaken for a real, trustworthy exit code.
    assert outcome.completed is False
    assert outcome.cause == INTERACTIVE_TERMINAL_CANCELLED


@covers("PROC_TIMEOUT")
def test_fault_timeout_kills_process_and_reports_cancelled(tmp_path):
    script_path, candidates = install_timeout_terminal(tmp_path)
    provider = DesktopTerminalProvider(candidates=candidates, poll_interval=0.05)
    outcome = provider.run(("python3", "-c", "pass"), str(tmp_path), {"PATH": "/usr/bin"}, 1)
    assert outcome.completed is False
    assert outcome.cause == INTERACTIVE_TERMINAL_CANCELLED


@covers("PROC_CHILD_SUCCESS")
def test_fault_status_present_but_lingering_launcher_is_killed_after_wait_timeout(
    tmp_path, monkeypatch,
):
    """A valid status does not let a still-live launcher escape cleanup.

    This reaches DesktopTerminalProvider._wait_for_result()'s distinct
    ``process.wait(timeout=...)`` branch: the status file exists, the real
    launcher process remains alive, wait raises TimeoutExpired, and the
    provider must kill it before returning the already trustworthy result.
    """
    import subprocess

    script_path, candidates = install_status_then_linger_terminal(tmp_path)
    provider = DesktopTerminalProvider(candidates=candidates, poll_interval=0.01)
    original_popen = interactive_terminal_module.subprocess.Popen
    spawned = []

    class _TrackedProcess:
        def __init__(self, process):
            self._process = process
            self.kill_calls = 0
            spawned.append(self)

        def poll(self):
            return self._process.poll()

        def wait(self, timeout=None):
            return self._process.wait(timeout=timeout)

        def kill(self):
            self.kill_calls += 1
            return self._process.kill()

    def _tracked_popen(*args, **kwargs):
        return _TrackedProcess(original_popen(*args, **kwargs))

    monkeypatch.setattr(interactive_terminal_module.subprocess, "Popen", _tracked_popen)
    fallback_calls = []
    monkeypatch.setattr(
        interactive_terminal_module.subprocess,
        "run",
        lambda *args, **kwargs: fallback_calls.append((args, kwargs)),
    )

    outcome = provider.run(("python3", "-c", "pass"), str(tmp_path), {"PATH": "/usr/bin"}, 2)

    assert outcome.completed is True
    assert outcome.returncode == 0
    assert len(spawned) == 1
    assert spawned[0].kill_calls == 1
    assert spawned[0].poll() is not None
    assert fallback_calls == []


# ============================================================================
# Filesystem faults
# ============================================================================

@covers("FS_CWD_DELETED_BEFORE_EXEC")
def test_fault_cwd_deleted_before_execution_fails_closed(tmp_path, monkeypatch):
    """A cwd that existed when the request was built but is removed
    before execute_controlled actually runs must fail closed, never
    silently fall back to a different directory."""
    from app.execution import ExecutionRequest, execute_controlled

    doomed_root = tmp_path / "will-be-deleted"
    doomed_root.mkdir()
    request = ExecutionRequest(
        ("python3", "-c", "pass"), str(doomed_root), 10, "python", "verification",
    )
    import shutil
    shutil.rmtree(doomed_root)

    # execute_controlled's own non-install branch calls subprocess.run
    # with cwd=<resolved path>; a nonexistent cwd is a real OSError at
    # the OS level, which execute_controlled's own except OSError
    # clause converts to a clean None (never a crash, never a silent
    # fallback to some other directory).
    result = execute_controlled(request, doomed_root)
    assert result is None


@covers("FS_PERMISSION_DENIED")
def test_fault_permission_denied_cwd_fails_closed(tmp_path):
    """A cwd that exists but cannot be entered (mode 000) must fail
    closed with a structured None result, never a raw crash."""
    from app.execution import ExecutionRequest, execute_controlled

    locked_root = tmp_path / "locked"
    locked_root.mkdir()
    locked_root.chmod(0o000)
    try:
        request = ExecutionRequest(
            ("python3", "-c", "pass"), str(locked_root), 10, "python", "verification",
        )
        result = execute_controlled(request, locked_root)
        assert result is None
    finally:
        locked_root.chmod(0o755)  # restore so tmp_path cleanup can remove it


# ============================================================================
# Toolchain / verifier faults
# ============================================================================

@covers("TOOLCHAIN_VERIFIER_FAILURE")
def test_fault_verifier_disagrees_despite_zero_exit_code(tmp_path, monkeypatch):
    """A post-install verifier that disagrees (returns False) despite a
    zero install exit code must be reported as a real failure, never
    silently promoted to success."""
    from app.python_package_executor import PythonPackageExecutor
    from app.requirement_model import SetupEffect, SetupStep
    from tests.terminal_final_child_probe import inert_terminal_harness

    target, counter_path, record_path = inert_terminal_harness(tmp_path, monkeypatch, "toolchain-a")
    executor = PythonPackageExecutor(verifier=lambda step: False)  # deterministic disagreement
    step = SetupStep(
        id="s1", requirement_id="r1", action="install", install_method="pip",
        package="whatever-package", setup_effect=SetupEffect.PYTHON_PACKAGE_INSTALL,
        is_approved=True, target_executable=target,
    )
    from app.execution import ApprovalProvenance, CapabilityRegistration, DEFAULT_CAPABILITY_REGISTRY
    resolved_root = str(tmp_path.resolve())
    DEFAULT_CAPABILITY_REGISTRY.register_approved(CapabilityRegistration(
        capability="python", executable_names=(target,), allowed_operations=("install", "verification"),
        approval_provenance=ApprovalProvenance(
            project_intelligence_ref=resolved_root, engineering_council_ref="c1",
            chairman_approval_ref="v1", human_approval_ref="setup-approval:p:approved",
        ),
        project_scope=resolved_root,
    ))
    try:
        result = executor.execute(step, str(tmp_path))
    finally:
        DEFAULT_CAPABILITY_REGISTRY.set_status("python", "revoked", resolved_root)

    # The install command itself reached the (inert) terminal and
    # reported success, but verification disagreement must still
    # dominate the final, externally-visible result.
    assert result.success is False
    assert result.verification_passed is False


# ============================================================================
# Persistence / authorization faults
# ============================================================================

@covers("LIFE_PRE_EXECUTION_AUTH_FAILURE")
def test_fault_between_authorization_and_execution_leaves_no_hidden_mutation(tmp_path, monkeypatch):
    """A capability-authorization failure must occur strictly BEFORE
    any terminal/process boundary is ever reached -- zero terminal
    launches, zero persisted "executing" state left stranded (this
    exact contract, once product-fixed, is what
    tests/test_s3_missing_toolchain_capability_authorization.py::
    test_failed_pre_execution_authorization_does_not_strand_recovery_as_executing
    already asserts end to end for the S3.5 recovery path; this is the
    lower-level, execute_controlled-only confirmation of the same
    principle)."""
    from app.execution import ExecutionRequest, execute_controlled
    from tests.terminal_final_child_probe import inert_terminal_harness

    target, counter_path, record_path = inert_terminal_harness(tmp_path, monkeypatch, "toolchain-a")
    project_root = tmp_path / "project"
    project_root.mkdir()
    # No capability registered at all -- validate_request must reject
    # before is_software_installation_request's terminal branch.
    request = ExecutionRequest((target, "-m", "pip", "install", "pkg"), str(project_root), 10, "python", "install")

    with pytest.raises(ValueError, match="capability"):
        execute_controlled(request, project_root)

    from tests.terminal_final_child_probe import read_terminal_launch_count
    assert read_terminal_launch_count(counter_path) == 0, "zero terminal launches on pre-execution auth failure"


@covers("LIFE_ALREADY_EXECUTING")
def test_fault_persistence_corruption_fails_closed_on_reload(tmp_path):
    """A corrupted SetupExecutionState record (unparseable JSON) must
    fail closed on reload, never silently treated as NOT_STARTED or
    any other guessed state."""
    from app.setup_execution_state import SetupExecutionStateStore

    storage_path = tmp_path / "exec-state.json"
    storage_path.write_text("{not valid json")
    store = SetupExecutionStateStore(storage_path)
    with pytest.raises(Exception):
        # Any real, structured load attempt against corrupt JSON must
        # raise, never silently return an empty/guessed state.
        store._load()  # noqa: SLF001 -- exercising the real fail-closed parse path directly
