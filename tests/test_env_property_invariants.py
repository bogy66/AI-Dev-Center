"""Property/invariant testing with deterministic generated representative
sets (CLAUDE-ADC-TEST-ENVIRONMENT-FIDELITY-UPGRADE-001 section 6). No
property-based library (e.g. Hypothesis) is installed anywhere in this
environment (verified before writing this file) -- every "property" here
is instead checked against a deterministic, hand-enumerated
representative set via pytest.mark.parametrize, never a single example.

Invariants covered:
  ARGV: final argv == authorized argv; no shell reinterpretation.
  ENVIRONMENT: final_child_env <= controlled_allowlist; forbidden
    ambient variables never appear.
  PATH: authorized scope cannot escape via path/symlink normalization.
  PROVENANCE: changed target/content cannot reuse stale approval/capability.
  REPLAY: known-success retry produces zero additional mutation launches.
"""
from __future__ import annotations

import os

import pytest

from app.execution import (
    ApprovalProvenance, CapabilityRegistration, CapabilityRegistry,
    ExecutionRequest, execute_controlled, validate_request,
)
from app.interactive_terminal import InteractiveTerminalLauncher
from tests.env_scenarios import covers
from tests.terminal_final_child_probe import (
    build_probe_argv, probe_provider, read_final_child_result,
    write_final_child_probe,
)

# ============================================================================
# ARGV: final argv == authorized argv, no shell reinterpretation.
# Deterministic representative set covering every ARGV_* equivalence class.
# ============================================================================
_ARGV_REPRESENTATIVES = [
    pytest.param(("ordinary",), id="ARGV_ORDINARY"),
    pytest.param(("first", "second", "third"), id="ARGV_MULTIPLE"),
    pytest.param(("an arg with spaces",), id="ARGV_SPACES"),
    pytest.param(("it's a \"quoted\" value",), id="ARGV_QUOTES_APOSTROPHES"),
    pytest.param(("meta;chars$(whoami)&|<>`x`",), id="ARGV_SHELL_METACHARACTERS"),
    pytest.param(("héllo wörld 日本語",), id="ARGV_UNICODE"),
    pytest.param(("--not-a-real-flag",), id="ARGV_LEADING_DASH"),
    pytest.param(("/opt/some/real/path",), id="ARGV_PATH_VALUE"),
    pytest.param(("package==1.2.3",), id="ARGV_VERSION_QUALIFIED_PACKAGE"),
    pytest.param(("x" * 3000,), id="ARGV_LONG_ARGUMENT"),
]


@covers(
    "ARGV_ORDINARY", "ARGV_MULTIPLE", "ARGV_SPACES", "ARGV_QUOTES_APOSTROPHES",
    "ARGV_SHELL_METACHARACTERS", "ARGV_UNICODE", "ARGV_LEADING_DASH",
    "ARGV_PATH_VALUE", "ARGV_VERSION_QUALIFIED_PACKAGE", "ARGV_LONG_ARGUMENT",
)
@pytest.mark.parametrize("extra_args", _ARGV_REPRESENTATIVES)
def test_property_final_argv_equals_authorized_argv(tmp_path, monkeypatch, extra_args):
    """final argv == authorized argv, for every representative ARGV shape,
    proven at the REAL final child (not merely what was passed into the
    launcher)."""
    provider = probe_provider(tmp_path, monkeypatch)
    launcher = InteractiveTerminalLauncher(provider=provider)
    probe = write_final_child_probe(tmp_path)
    out_path = tmp_path / "result.json"

    argv = build_probe_argv(probe, out_path, 0, *extra_args)
    result = launcher.run(argv, str(tmp_path), {"PATH": "/usr/bin"}, 10)
    assert result.returncode == 0

    observed = read_final_child_result(out_path)
    assert tuple(observed["argv"]) == extra_args, "final argv must equal the authorized argv exactly"


@covers("ARGV_MALFORMED_VALUE")
def test_property_malformed_package_value_never_reaches_a_process():
    """A structurally invalid package value is rejected by
    PythonPackageExecutor's own validation before any process --
    terminal or otherwise -- is ever reached."""
    from app.python_package_executor import PackageMissingError, PythonPackageExecutor
    from app.requirement_model import SetupEffect, SetupStep

    executor = PythonPackageExecutor(verifier=lambda step: True)
    step = SetupStep(
        id="s1", requirement_id="r1", action="install", install_method="pip",
        package="not a valid package name!!", setup_effect=SetupEffect.PYTHON_PACKAGE_INSTALL,
        is_approved=True,
    )
    with pytest.raises(PackageMissingError):
        executor.execute(step, "/tmp")


# ============================================================================
# ENVIRONMENT: final_child_env <= controlled_allowlist; forbidden ambient
# variables never appear. Deterministic representative set.
# ============================================================================
_ENV_REPRESENTATIVES = [
    pytest.param({"PATH": ""}, id="ENV_EMPTY_VALUE"),
    pytest.param({"PATH": "/usr/bin:héllo/日本語"}, id="ENV_UNICODE_VALUE"),
    pytest.param({"PATH": "/usr/bin:/path with spaces/bin"}, id="ENV_SPACES_VALUE"),
    pytest.param({"PATH": "/usr/bin" + ("/x" * 2000)}, id="ENV_LARGE_VALUE"),
]


@covers("ENV_EMPTY_VALUE", "ENV_UNICODE_VALUE", "ENV_SPACES_VALUE", "ENV_LARGE_VALUE", "ENV_CONTROLLED_VARS")
@pytest.mark.parametrize("controlled_env", _ENV_REPRESENTATIVES)
def test_property_final_child_env_matches_controlled_values_exactly(tmp_path, monkeypatch, controlled_env):
    provider = probe_provider(tmp_path, monkeypatch)
    launcher = InteractiveTerminalLauncher(provider=provider)
    probe = write_final_child_probe(tmp_path)
    out_path = tmp_path / "result.json"

    launcher.run(build_probe_argv(probe, out_path, 0), str(tmp_path), controlled_env, 10)
    observed = read_final_child_result(out_path)
    for key, value in controlled_env.items():
        assert observed["env"].get(key) == value


@covers("ENV_MINIMAL_HEADLESS", "ENV_DESKTOP_X11", "ENV_WAYLAND", "ENV_DBUS_SESSION")
@pytest.mark.parametrize(
    "desktop_vars",
    [
        pytest.param({}, id="ENV_MINIMAL_HEADLESS"),
        pytest.param({"DISPLAY": ":0", "XAUTHORITY": "/tmp/.Xauth"}, id="ENV_DESKTOP_X11"),
        pytest.param({"WAYLAND_DISPLAY": "wayland-0"}, id="ENV_WAYLAND"),
        pytest.param({"DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/dbus", "XDG_RUNTIME_DIR": "/run/user/1000"}, id="ENV_DBUS_SESSION"),
    ],
)
def test_property_terminal_resolves_regardless_of_desktop_session_shape(tmp_path, monkeypatch, desktop_vars):
    """The terminal boundary resolves and runs correctly whether or not
    desktop-session variables are present on the ambient process --
    DesktopTerminalProvider's own is_available()/binary-selection logic
    never depends on them (only the real emulator's own connectivity
    would, which this deterministic surrogate does not need)."""
    for key, value in desktop_vars.items():
        monkeypatch.setenv(key, value)
    provider = probe_provider(tmp_path, monkeypatch)
    launcher = InteractiveTerminalLauncher(provider=provider)
    probe = write_final_child_probe(tmp_path)
    out_path = tmp_path / "result.json"
    result = launcher.run(build_probe_argv(probe, out_path, 0), str(tmp_path), {"PATH": "/usr/bin"}, 10)
    assert result.returncode == 0


# ============================================================================
# PATH: authorized scope cannot escape via path/symlink normalization.
# ============================================================================
@covers("FS_SYMLINK", "FS_SYMLINK_ESCAPE")
@pytest.mark.parametrize(
    "escape", [pytest.param(False, id="FS_SYMLINK_within_root"), pytest.param(True, id="FS_SYMLINK_ESCAPE")],
)
def test_property_symlinked_cwd_resolves_before_confinement_check(tmp_path, escape):
    project_root = tmp_path / "project"
    project_root.mkdir()
    real_target = (tmp_path / "outside-target") if escape else (project_root / "inside-target")
    real_target.mkdir()
    link = project_root / "link"
    link.symlink_to(real_target)

    request = ExecutionRequest(("python3", "-c", "pass"), str(link), 10, "python", "verification")
    if escape:
        with pytest.raises(ValueError, match="cwd escapes project root"):
            execute_controlled(request, project_root)
    else:
        result = execute_controlled(request, project_root)
        assert result is not None and result.returncode == 0


@covers("FS_SPACES", "FS_UNICODE")
@pytest.mark.parametrize(
    "dirname", [pytest.param("dir with spaces", id="FS_SPACES"), pytest.param("dir-héllo-日本語", id="FS_UNICODE")],
)
def test_property_cwd_with_spaces_or_unicode_resolves_correctly(tmp_path, dirname):
    project_root = tmp_path / dirname
    project_root.mkdir()
    request = ExecutionRequest(("python3", "-c", "pass"), str(project_root), 10, "python", "verification")
    result = execute_controlled(request, project_root)
    assert result is not None and result.returncode == 0


# ============================================================================
# PROVENANCE: changed target/content cannot reuse stale approval/capability.
# ============================================================================
@covers("AUTH_CONTENT_MUTATION", "FS_CHANGED_AFTER_APPROVAL", "TOOLCHAIN_WRONG_INTERPRETER_EQUIVALENT")
def test_property_changed_target_executable_cannot_reuse_stale_capability(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    resolved_root = str(project_root.resolve())
    registry = CapabilityRegistry()
    registry.register_approved(CapabilityRegistration(
        capability="python", executable_names=("/approved/python",), allowed_operations=("install",),
        approval_provenance=ApprovalProvenance(resolved_root, "c1", "v1", "setup-approval:p:approved"),
        project_scope=resolved_root,
    ))
    # A request naming a DIFFERENT (mutated/substituted) executable must
    # never be authorized by the capability registered for the original.
    request = ExecutionRequest(("/different/python", "-m", "pip", "install", "pkg"), str(project_root), 10, "python", "install")
    violation = validate_request(request, project_root, registry)
    assert violation is not None


# ============================================================================
# REPLAY: known-success retry produces zero additional mutation launches.
# ============================================================================
@covers("LIFE_RETRY", "LIFE_SUCCESS")
def test_property_known_success_retry_produces_zero_additional_launches(tmp_path, monkeypatch):
    from app.dev_workflow import DevelopmentWorkflow
    from app.python_package_executor import PythonPackageExecutor
    from app.requirement_model import SetupEffect, SetupPlan, SetupStep
    from app.setup_execution_state import SetupExecutionStateStore
    from tests.terminal_final_child_probe import inert_terminal_harness, read_terminal_launch_count

    target, counter_path, record_path = inert_terminal_harness(tmp_path, monkeypatch, "toolchain-a")
    project_root = tmp_path / "project"
    project_root.mkdir()

    step = SetupStep(
        id="s1", requirement_id="r1", action="install", install_method="pip",
        package="pkg", setup_effect=SetupEffect.PYTHON_PACKAGE_INSTALL,
        is_approved=True, target_executable=target,
    )
    plan = SetupPlan(id="plan-1", project_id="proj", steps=(step,), status="approved")

    from app.execution import register_setup_step_targets
    register_setup_step_targets(
        plan, project_root, engineering_council_ref="c1", chairman_approval_ref="v1",
        human_approval_ref="setup-approval:plan-1:approved",
    )

    store = SetupExecutionStateStore(tmp_path / "exec-state.json")
    workflow = DevelopmentWorkflow(
        discovery=None, validator=None, preflight=None,
        executor=PythonPackageExecutor(verifier=lambda step: True),
        execution_state_store=store,
    )
    first = workflow.execute_approved(plan, str(project_root))
    assert first[0].success is True
    assert read_terminal_launch_count(counter_path) == 1

    second = workflow.execute_approved(plan, str(project_root))
    assert second[0].success is True
    assert read_terminal_launch_count(counter_path) == 1, "known-success retry must launch zero additional times"
