"""Tests for the terminal-provider-behaviour surrogates
(tests/terminal_final_child_probe.py) -- CLAUDE-ADC-TEST-ENVIRONMENT
-FIDELITY-UPGRADE-001 section 8.

Covers all seven named provider-behaviour classes with a real,
unmodified DesktopTerminalProvider exercised end to end each time (real
subprocess.Popen; inert client/server shape fixtures explicitly simulate
STATUS-V3, while direct and genuine two-process probes run the wrapper); only the
"terminal emulator" binary itself is a deterministic, harmless
surrogate. Never claims to prove real gnome-terminal/xterm behaviour --
see this module's own TestRealTerminalSmoke-adjacent note in
tests/test_interactive_terminal.py for the one, deliberately limited
real-terminal check this suite performs, and
tests/env_scenarios.py::TERMINAL_CLASSES for the full equivalence-class
catalog these tests draw from.
"""
from __future__ import annotations

import pytest

from app.interactive_terminal import (
    DesktopTerminalProvider,
    INTERACTIVE_TERMINAL_UNAVAILABLE,
)
from tests.env_scenarios import covers
from tests.terminal_final_child_probe import (
    build_probe_argv,
    client_server_provider,
    genuine_two_process_client_server_provider,
    install_early_exit_terminal,
    install_start_failure_terminal_candidates,
    probe_provider,
    provider_with_explicit_cwd,
    read_client_server_record,
    read_explicit_cwd_record,
    read_final_child_result,
    write_final_child_probe,
)


@covers("TERM_DIRECT_PROCESS_STYLE", "TERM_INHERITED_CWD_HANDLING")
def test_direct_process_provider_final_child_receives_confined_cwd(tmp_path, monkeypatch):
    """DIRECT_PROCESS_PROVIDER (xterm/-e family): the child directly
    execs, inheriting Popen's own cwd/env with no intermediary server
    process -- the simplest, most trustworthy provider shape."""
    provider = probe_provider(tmp_path, monkeypatch)
    from app.interactive_terminal import InteractiveTerminalLauncher
    launcher = InteractiveTerminalLauncher(provider=provider)
    probe = write_final_child_probe(tmp_path)
    out_path = tmp_path / "result.json"
    project_root = tmp_path / "project"
    project_root.mkdir()

    result = launcher.run(build_probe_argv(probe, out_path, 0), str(project_root), {"PATH": "/usr/bin"}, 10)
    assert result.returncode == 0
    observed = read_final_child_result(out_path)
    assert observed["cwd"] == str(project_root.resolve())


@covers("TERM_CLIENT_SERVER_STYLE")
def test_client_server_provider_well_behaved_matches_launcher_state(tmp_path, monkeypatch):
    """A well-behaved client/server surrogate (no divergence configured)
    still correctly forwards the client's real cwd/env -- proving the
    compliant case is representable, not just the risky one."""
    provider, record_path = client_server_provider(tmp_path, monkeypatch)
    from app.interactive_terminal import InteractiveTerminalLauncher
    launcher = InteractiveTerminalLauncher(provider=provider)
    project_root = tmp_path / "project"
    project_root.mkdir()

    result = launcher.run(("python3", "-c", "pass"), str(project_root), {"PATH": "/usr/bin"}, 10)
    assert result.returncode == 0
    record = read_client_server_record(record_path)
    assert record["final_child_cwd"] == record["launcher_cwd"]
    assert record["final_child_env"] == record["launcher_env"]


@covers("TERM_CLIENT_SERVER_STYLE", "ENV_LAUNCHER_ONLY_DESKTOP_VARS")
def test_client_server_provider_can_detect_cwd_env_divergence(tmp_path, monkeypatch):
    """The DIVERGENT client/server shape (the real gnome-terminal risk):
    the "server" uses its own stale cwd/env rather than the client's
    real Popen(cwd=, env=) arguments -- this test proves that
    divergence is DETECTABLE, not that it is acceptable. This is
    exactly the structural risk
    tests/test_interactive_terminal.py::TestDesktopTerminalProviderFinalChildBoundary's
    own class docstring already documents as out of that deterministic
    surrogate's reach; this one makes the divergence itself observable."""
    stale_cwd = str(tmp_path / "stale-server-cwd")
    (tmp_path / "stale-server-cwd").mkdir()
    stale_env = {"PATH": "/stale/server/path"}
    provider, record_path = client_server_provider(
        tmp_path, monkeypatch, server_cwd=stale_cwd, server_env=stale_env,
    )
    from app.interactive_terminal import InteractiveTerminalLauncher
    launcher = InteractiveTerminalLauncher(provider=provider)
    project_root = tmp_path / "project"
    project_root.mkdir()

    result = launcher.run(("python3", "-c", "pass"), str(project_root), {"PATH": "/usr/bin"}, 10)
    assert result.returncode == 0
    record = read_client_server_record(record_path)
    # The simulated final child's cwd/env diverge from what the client
    # Popen call actually received -- exactly the risk a real
    # client/server terminal poses, now an observable test assertion.
    assert record["final_child_cwd"] != record["launcher_cwd"]
    assert record["final_child_env"] != record["launcher_env"]
    assert record["final_child_cwd"] == stale_cwd


@covers("TERM_EXPLICIT_CWD_HANDLING")
def test_provider_with_explicit_cwd_flag_honors_the_flag_not_inherited_cwd(tmp_path, monkeypatch):
    """PROVIDER_WITH_EXPLICIT_CWD: a provider whose candidate flags
    carry an explicit --working-directory=-style argument -- correctness
    does not depend on whether the underlying process model inherits
    Popen's own cwd at all, which is exactly the DEF-013A remediation
    direction for a real client/server terminal like gnome-terminal."""
    record_path = tmp_path / "explicit-cwd-record.json"
    provider = provider_with_explicit_cwd(tmp_path, monkeypatch, record_path)
    from app.interactive_terminal import InteractiveTerminalLauncher
    launcher = InteractiveTerminalLauncher(provider=provider)

    # Deliberately pass a DIFFERENT cwd to Popen than the provider's
    # own --working-directory= flag names, to prove the flag -- not
    # inherited Popen(cwd=) -- is what this provider class honors.
    other_cwd = tmp_path / "other-cwd"
    other_cwd.mkdir()
    result = launcher.run(("python3", "-c", "pass"), str(other_cwd), {"PATH": "/usr/bin"}, 10)
    assert result.returncode == 0
    record = read_explicit_cwd_record(record_path)
    assert record["honored_cwd"] == str(tmp_path)


@covers("TERM_EARLY_EXIT", "TERM_USER_CANCEL_EQUIVALENT")
def test_early_exit_provider_is_cancelled_not_success(tmp_path, monkeypatch):
    """PROVIDER_EARLY_EXIT: the terminal exits before ever running the
    wrapper script -- the same observable shape as a user closing the
    terminal window before the command could even start."""
    script_path, candidates = install_early_exit_terminal(tmp_path)
    monkeypatch.setenv("PATH", f"{script_path.parent}:{__import__('os').environ.get('PATH', '')}")
    provider = DesktopTerminalProvider(candidates=candidates, launcher_exit_grace=0.05)
    outcome = provider.run(("python3", "-c", "pass"), str(tmp_path), {"PATH": "/usr/bin"}, 5)
    assert outcome.completed is False
    from app.interactive_terminal import INTERACTIVE_TERMINAL_CANCELLED
    assert outcome.cause == INTERACTIVE_TERMINAL_CANCELLED


@covers("TERM_NO_PROVIDER", "TERM_STARTUP_FAILURE")
def test_start_failure_provider_fails_closed_with_no_popen(tmp_path):
    """PROVIDER_START_FAILURE / TERM_NO_PROVIDER: no candidate binary
    exists at all -- fails closed before any subprocess is attempted."""
    candidates = install_start_failure_terminal_candidates(tmp_path)
    provider = DesktopTerminalProvider(candidates=candidates)
    assert provider.is_available() is False
    outcome = provider.run(("python3", "-c", "pass"), str(tmp_path), {"PATH": "/usr/bin"}, 5)
    assert outcome.completed is False
    assert outcome.cause == INTERACTIVE_TERMINAL_UNAVAILABLE


@covers("TERM_PROVIDER_AVAILABLE", "PROC_CHILD_NONZERO")
def test_child_failure_provider_propagates_nonzero_exit(tmp_path, monkeypatch):
    """PROVIDER_CHILD_FAILURE: the wrapped command itself fails (real
    nonzero exit) -- already fully covered by the existing direct-exec
    surrogate plus a nonzero exit code, reused here under this class's
    own explicit name for completeness of the 7-class catalog."""
    provider = probe_provider(tmp_path, monkeypatch)
    from app.interactive_terminal import InteractiveTerminalLauncher
    launcher = InteractiveTerminalLauncher(provider=provider)
    probe = write_final_child_probe(tmp_path)
    out_path = tmp_path / "result.json"

    result = launcher.run(build_probe_argv(probe, out_path, 13), str(tmp_path), {"PATH": "/usr/bin"}, 10)
    assert result.returncode == 13


def test_genuine_two_process_server_preserves_wrapper_contract_and_exposes_divergence(
    tmp_path, monkeypatch,
):
    """The client and already-running server are distinct OS processes.

    The real DesktopTerminalProvider wrapper/status protocol is retained;
    only the terminal-provider processes are deterministic local surrogates.
    The final probe proves cwd/argv/environment at the child boundary.
    """
    import os

    server_cwd = tmp_path / "server-cwd"
    client_cwd = tmp_path / "client-cwd"
    server_cwd.mkdir()
    client_cwd.mkdir()
    provider, record_path, cleanup = genuine_two_process_client_server_provider(
        tmp_path, monkeypatch,
        server_cwd=server_cwd,
        server_env={"PATH": "/server/path", "ADC_SERVER_ONLY": "present"},
    )
    try:
        launcher = __import__("app.interactive_terminal", fromlist=["InteractiveTerminalLauncher"]).InteractiveTerminalLauncher(provider=provider)
        probe = write_final_child_probe(tmp_path)
        out_path = tmp_path / "two-process-child.json"
        result = launcher.run(
            build_probe_argv(probe, out_path, 0, "arg with spaces", "meta;chars"),
            str(client_cwd),
            {"PATH": "/controlled/path"},
            10,
        )
        assert result.returncode == 0
        observed = read_final_child_result(out_path)
        record = read_client_server_record(record_path)
        assert record["server_pid"] != record["client_pid"]
        assert record["launcher_cwd"] == str(client_cwd)
        assert record["server_cwd"] == str(server_cwd)
        assert observed["cwd"] == str(server_cwd)
        assert tuple(observed["argv"]) == ("arg with spaces", "meta;chars")
        assert observed["env"].get("PATH") == "/controlled/path"
        assert "ADC_SERVER_ONLY" not in observed["env"]
    finally:
        cleanup()


def test_genuine_two_process_server_early_return_is_cancellation(
    tmp_path, monkeypatch,
):
    provider, _record_path, cleanup = genuine_two_process_client_server_provider(
        tmp_path, monkeypatch,
        server_cwd=tmp_path,
        server_env={"PATH": "/server/path"},
        mode="early",
    )
    try:
        from app.interactive_terminal import InteractiveTerminalError, InteractiveTerminalLauncher, INTERACTIVE_TERMINAL_CANCELLED
        launcher = InteractiveTerminalLauncher(provider=provider)
        with pytest.raises(InteractiveTerminalError) as exc_info:
            launcher.run(("python3", "-c", "pass"), str(tmp_path), {"PATH": "/controlled/path"}, 1)
        assert exc_info.value.cause == INTERACTIVE_TERMINAL_CANCELLED
    finally:
        cleanup()
