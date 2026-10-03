"""Tests for the central visible-interactive-terminal execution surface
(CLAUDE-ADC-VISIBLE-TERMINAL-FOR-SOFTWARE-INSTALLATION-001).

All deterministic tests use a fake TerminalProvider -- never a real GUI
-- so the focused suite never depends on a desktop session. See
test_real_terminal_smoke_check below for the one best-effort, harmless,
non-sudo, no-install real-terminal check (section 8 of the task), which
reports NOT_AVAILABLE rather than faking a PASS when no GUI is present.
"""
import shutil
import subprocess

import pytest

from app.interactive_terminal import (
    DesktopTerminalProvider,
    InteractiveTerminalError,
    InteractiveTerminalLauncher,
    INTERACTIVE_TERMINAL_CANCELLED,
    INTERACTIVE_TERMINAL_LAUNCH_FAILED,
    INTERACTIVE_TERMINAL_UNAVAILABLE,
    TerminalLaunchOutcome,
)


class FakeTerminalProvider:
    """Deterministic stand-in for a real desktop terminal. Records every
    call so tests can assert on invocation count/order/arguments."""

    def __init__(self, outcome: TerminalLaunchOutcome, available: bool = True):
        self._outcome = outcome
        self._available = available
        self.calls: list[dict] = []

    def is_available(self) -> bool:
        return self._available

    def run(self, argv, cwd, env, timeout) -> TerminalLaunchOutcome:
        self.calls.append({"argv": argv, "cwd": cwd, "env": env, "timeout": timeout})
        return self._outcome


# ============================================================================
# InteractiveTerminalLauncher: success / failure / fail-closed
# ============================================================================

class TestInteractiveTerminalLauncherSuccess:
    def test_successful_command_returns_real_returncode(self, tmp_path):
        provider = FakeTerminalProvider(TerminalLaunchOutcome(completed=True, returncode=0))
        launcher = InteractiveTerminalLauncher(provider)
        result = launcher.run(("pip", "install", "esphome"), str(tmp_path), {"PATH": "/usr/bin"}, 30)
        assert result.returncode == 0
        assert provider.calls == [{
            "argv": ("pip", "install", "esphome"), "cwd": str(tmp_path),
            "env": {"PATH": "/usr/bin"}, "timeout": 30,
        }]

    def test_nonzero_exit_is_propagated_not_raised(self, tmp_path):
        provider = FakeTerminalProvider(TerminalLaunchOutcome(completed=True, returncode=1))
        launcher = InteractiveTerminalLauncher(provider)
        result = launcher.run(("pip", "install", "doesnotexist"), str(tmp_path), {}, 30)
        assert result.returncode == 1

    def test_launcher_invoked_exactly_once_per_run_call(self, tmp_path):
        provider = FakeTerminalProvider(TerminalLaunchOutcome(completed=True, returncode=0))
        launcher = InteractiveTerminalLauncher(provider)
        launcher.run(("pip", "install", "x"), str(tmp_path), {}, 30)
        assert len(provider.calls) == 1


class TestInteractiveTerminalLauncherFailClosed:
    def test_no_provider_available_raises_structured_unavailable(self, tmp_path):
        provider = FakeTerminalProvider(TerminalLaunchOutcome(completed=True, returncode=0), available=False)
        launcher = InteractiveTerminalLauncher(provider)
        with pytest.raises(InteractiveTerminalError) as exc_info:
            launcher.run(("pip", "install", "x"), str(tmp_path), {}, 30)
        assert exc_info.value.cause == INTERACTIVE_TERMINAL_UNAVAILABLE
        assert provider.calls == []  # never attempted a run when unavailable

    def test_terminal_launch_failure_raises_not_success(self, tmp_path):
        provider = FakeTerminalProvider(TerminalLaunchOutcome(
            completed=False, cause=INTERACTIVE_TERMINAL_LAUNCH_FAILED, detail="boom",
        ))
        launcher = InteractiveTerminalLauncher(provider)
        with pytest.raises(InteractiveTerminalError) as exc_info:
            launcher.run(("pip", "install", "x"), str(tmp_path), {}, 30)
        assert exc_info.value.cause == INTERACTIVE_TERMINAL_LAUNCH_FAILED

    def test_cancelled_terminal_is_not_success(self, tmp_path):
        provider = FakeTerminalProvider(TerminalLaunchOutcome(
            completed=False, cause=INTERACTIVE_TERMINAL_CANCELLED, detail="closed",
        ))
        launcher = InteractiveTerminalLauncher(provider)
        with pytest.raises(InteractiveTerminalError) as exc_info:
            launcher.run(("pip", "install", "x"), str(tmp_path), {}, 30)
        assert exc_info.value.cause == INTERACTIVE_TERMINAL_CANCELLED

    def test_no_hidden_subprocess_fallback_exists(self, tmp_path, monkeypatch):
        """When the terminal is unavailable, InteractiveTerminalLauncher
        must never fall back to running the command directly."""
        run = None

        def _forbidden(*args, **kwargs):
            nonlocal run
            run = (args, kwargs)
            raise AssertionError("must never run the command directly")

        monkeypatch.setattr("app.interactive_terminal.subprocess.run", _forbidden)
        provider = FakeTerminalProvider(TerminalLaunchOutcome(completed=True, returncode=0), available=False)
        launcher = InteractiveTerminalLauncher(provider)
        with pytest.raises(InteractiveTerminalError):
            launcher.run(("pip", "install", "x"), str(tmp_path), {}, 30)
        assert run is None


# ============================================================================
# DesktopTerminalProvider: provider-selection / wrapper-script contract
# ============================================================================

class TestDesktopTerminalProviderSelection:
    def test_not_available_when_no_candidate_binary_on_path(self, monkeypatch):
        monkeypatch.setattr("app.interactive_terminal.shutil.which", lambda name: None)
        provider = DesktopTerminalProvider()
        assert provider.is_available() is False

    def test_available_when_a_candidate_binary_is_on_path(self, monkeypatch):
        monkeypatch.setattr(
            "app.interactive_terminal.shutil.which",
            lambda name: "/usr/bin/xterm" if name == "xterm" else None,
        )
        provider = DesktopTerminalProvider()
        assert provider.is_available() is True

    def test_first_candidate_in_order_wins(self, monkeypatch):
        monkeypatch.setattr(
            "app.interactive_terminal.shutil.which",
            lambda name: f"/usr/bin/{name}",
        )
        provider = DesktopTerminalProvider()
        binary, prefix = provider._select_binary()
        assert binary == "/usr/bin/gnome-terminal"

    def test_no_candidate_is_hard_coded_to_gnome_terminal_only(self):
        names = [name for name, _ in DesktopTerminalProvider()._candidates]
        assert "gnome-terminal" in names
        assert len(names) > 1  # extensible beyond one hard-coded program

    def test_unavailable_run_returns_structured_cause_without_popen(self, monkeypatch):
        monkeypatch.setattr("app.interactive_terminal.shutil.which", lambda name: None)
        popen_called = []
        monkeypatch.setattr(
            "app.interactive_terminal.subprocess.Popen",
            lambda *a, **kw: popen_called.append(1),
        )
        provider = DesktopTerminalProvider()
        outcome = provider.run(("pip", "install", "x"), "/tmp", {}, 5)
        assert outcome.completed is False
        assert outcome.cause == INTERACTIVE_TERMINAL_UNAVAILABLE
        assert popen_called == []

    def test_wrapper_script_never_reinterprets_argv_through_shell(self, tmp_path, monkeypatch):
        """Authorized arguments remain data at the real direct child."""
        import json
        import sys
        from tests.terminal_final_child_probe import probe_provider
        output = tmp_path / 'args.json'
        marker = tmp_path / 'unexpected-shell-execution'
        arguments = ('two words', "single'quote", f'$(touch {marker})', '; exit 99')
        script = 'import json,sys;open(sys.argv[1],"w").write(json.dumps(sys.argv[2:]))'
        result = probe_provider(tmp_path, monkeypatch).run(
            (sys.executable, '-c', script, str(output), *arguments), str(tmp_path), {}, 5)
        assert result.completed and result.returncode == 0
        assert json.loads(output.read_text()) == list(arguments)
        assert not marker.exists()

    def test_no_hold_flag_keeps_terminal_closing_after_completion(self):
        """None of the candidate terminal flags use -hold/--hold, which
        would keep a finished installation's window open instead of
        closing it automatically."""
        for _name, flags in DesktopTerminalProvider()._candidates:
            assert not any("hold" in flag for flag in flags)

    def test_gnome_terminal_candidate_has_no_explicit_working_directory_flag(self):
        """Cheap provider-contract documentation, not a live-GUI check
        (KIB-ADC-CAPABILITY-AUTH-TERMINAL-BOUNDARY-TC-FIX-001 section
        5): gnome-terminal is the FIRST, default production candidate
        and commonly uses a client/server model -- a short-lived
        `gnome-terminal ...` client invocation can hand off to an
        already-running server process, whose spawned shell is not
        guaranteed to inherit the client invocation's own
        subprocess.Popen(cwd=...) at all unless an explicit
        `--working-directory=DIR` argument is passed. This candidate's
        own flags, `("--wait", "--")`, currently include no such flag.
        This test only asserts that fact about the static candidate
        list -- it does NOT launch gnome-terminal and does NOT prove
        cwd propagation succeeds or fails for a real session; that is
        Real-System/provider-certification territory (see
        TestDesktopTerminalProviderFinalChildBoundary's own class
        docstring and TestRealTerminalSmoke below)."""
        candidates = dict(DesktopTerminalProvider()._candidates)
        assert "gnome-terminal" in candidates
        assert not any(
            flag.startswith("--working-directory") for flag in candidates["gnome-terminal"]
        )


class TestDesktopTerminalProviderRealLaunchWithFakeBinary:
    """Exercises the real Popen + polling + status-file contract end to
    end, using a tiny real script in place of a real GUI terminal
    emulator -- deterministic, no display required, but a genuine
    subprocess is spawned so the wrapper-script/status-file protocol
    itself is proven, not just mocked away."""

    def test_successful_command_produces_completed_outcome_with_real_returncode(self, tmp_path):
        fake_terminal = tmp_path / "fake-terminal.sh"
        # Emulates "gnome-terminal -- <wrapper> <status_path> <argv...>":
        # simply execs whatever argv it was given, mirroring how a real
        # terminal emulator ultimately runs its child.
        fake_terminal.write_text("#!/bin/sh\nexec \"$@\"\n")
        fake_terminal.chmod(0o700)

        provider = DesktopTerminalProvider(candidates=((str(fake_terminal), ()),))
        outcome = provider.run(("sh", "-c", "exit 0"), str(tmp_path), {}, 10)
        assert outcome.completed is True
        assert outcome.returncode == 0

    def test_nonzero_exit_is_captured_via_status_file(self, tmp_path):
        fake_terminal = tmp_path / "fake-terminal.sh"
        fake_terminal.write_text("#!/bin/sh\nexec \"$@\"\n")
        fake_terminal.chmod(0o700)

        provider = DesktopTerminalProvider(candidates=((str(fake_terminal), ()),))
        outcome = provider.run(("sh", "-c", "exit 7"), str(tmp_path), {}, 10)
        assert outcome.completed is True
        assert outcome.returncode == 7

    def test_terminal_that_never_writes_status_is_cancelled_not_success(self, tmp_path):
        # Emulates a window closed by the user before the wrapped
        # command finishes: the "terminal" here exits immediately
        # without ever invoking the wrapper/status-file protocol.
        fake_terminal = tmp_path / "cancelling-terminal.sh"
        fake_terminal.write_text("#!/bin/sh\nexit 0\n")
        fake_terminal.chmod(0o700)

        provider = DesktopTerminalProvider(
            candidates=((str(fake_terminal), ()),), launcher_exit_grace=0.05,
        )
        outcome = provider.run(("sh", "-c", "exit 0"), str(tmp_path), {}, 5)
        assert outcome.completed is False
        assert outcome.cause == INTERACTIVE_TERMINAL_CANCELLED

    def test_launch_failure_when_binary_disappears(self, tmp_path, monkeypatch):
        # Simulates a TOCTOU race: the candidate was found via which()
        # at selection time but Popen() itself fails (binary removed,
        # permission revoked, exec format error, ...).
        fake_terminal = tmp_path / "fake-terminal.sh"
        fake_terminal.write_text("#!/bin/sh\nexec \"$@\"\n")
        fake_terminal.chmod(0o700)
        provider = DesktopTerminalProvider(candidates=((str(fake_terminal), ()),))

        def _raise(*args, **kwargs):
            raise OSError("binary vanished")

        monkeypatch.setattr("app.interactive_terminal.subprocess.Popen", _raise)
        outcome = provider.run(("sh", "-c", "exit 0"), str(tmp_path), {}, 5)
        assert outcome.completed is False
        assert outcome.cause == INTERACTIVE_TERMINAL_LAUNCH_FAILED

    def test_argument_with_spaces_survives_unmangled(self, tmp_path):
        """Proves the producer's direct argv forwarding, not shell
        string re-quoting, is what actually runs -- an argument with an
        embedded space is passed through exactly."""
        marker = tmp_path / "marker.txt"
        fake_terminal = tmp_path / "fake-terminal.sh"
        fake_terminal.write_text("#!/bin/sh\nexec \"$@\"\n")
        fake_terminal.chmod(0o700)

        provider = DesktopTerminalProvider(candidates=((str(fake_terminal), ()),))
        outcome = provider.run(
            ("sh", "-c", f'printf %s "$1" > "{marker}"', "_", "hello world"),
            str(tmp_path), {}, 10,
        )
        assert outcome.completed is True
        assert outcome.returncode == 0
        assert marker.read_text() == "hello world"


class TestDesktopTerminalProviderFinalChildBoundary:
    """KIB-ADC-CAPABILITY-AUTH-TERMINAL-BOUNDARY-TC-FIX-001 section 3/7B:
    validate observable semantics at the FINAL CHILD process a
    controlled installation actually spawns, not merely the cwd/env
    arguments passed INTO DesktopTerminalProvider.run() -- a passing
    assertion on the latter alone does not prove the former, since
    DesktopTerminalProvider.run() itself recomposes the environment
    (`launcher_env = {**os.environ, **env}`) before ever reaching
    subprocess.Popen. Every test here inspects a real, independent
    JSON side-channel file written by the actual spawned process
    (see tests/terminal_final_child_probe.py), never a mock's recorded
    call arguments.

    Uses the same "exec passthrough" fake-terminal-emulator pattern as
    TestDesktopTerminalProviderRealLaunchWithFakeBinary above (a real,
    harmless, GUI-free subprocess is genuinely spawned) but drives it
    through the real wrapped-command argv/cwd/env InteractiveTerminalLauncher
    itself builds, exactly as PythonPackageExecutor/execute_controlled
    would for a real installation.

    What this class deliberately does NOT prove: whether a real,
    specific terminal emulator binary -- especially a client/server one
    such as gnome-terminal, the first and default production candidate
    -- actually honors subprocess.Popen(cwd=..., env=...) for the shell
    it opens. A client/server emulator's real shell is commonly spawned
    by an already-running server process that may not inherit the
    short-lived launching client's own cwd/env at all. That remains
    Real-System/provider-certification territory this deterministic
    surrogate cannot reach; see TestRealTerminalSmoke below for the
    only real-terminal check this suite performs, which is a pure
    availability probe, never a cwd/env certification.
    """

    def test_final_child_receives_the_exact_confined_cwd(self, tmp_path, monkeypatch):
        from tests.terminal_final_child_probe import (
            build_probe_argv, probe_provider, read_final_child_result,
            write_final_child_probe,
        )
        provider = probe_provider(tmp_path, monkeypatch)
        launcher = InteractiveTerminalLauncher(provider=provider)
        probe = write_final_child_probe(tmp_path)
        out_path = tmp_path / "result.json"
        project_root = tmp_path / "project"
        project_root.mkdir()

        argv = build_probe_argv(probe, out_path, 0)
        result = launcher.run(argv, str(project_root), {"PATH": "/usr/bin"}, 10)

        assert result.returncode == 0
        observed = read_final_child_result(out_path)
        assert observed["cwd"] == str(project_root.resolve())

    def test_final_child_receives_only_the_controlled_allowlisted_environment(self, tmp_path, monkeypatch):
        """The important assertion: what the FINAL CHILD's own os.environ
        actually contains, not what was passed as the `env` argument to
        DesktopTerminalProvider.run()."""
        from tests.terminal_final_child_probe import (
            build_probe_argv, probe_provider, read_final_child_result,
            write_final_child_probe,
        )
        monkeypatch.setenv("ADC_TEST_SECRET_TOKEN", "should-not-leak")
        provider = probe_provider(tmp_path, monkeypatch)
        launcher = InteractiveTerminalLauncher(provider=provider)
        probe = write_final_child_probe(tmp_path)
        out_path = tmp_path / "result.json"
        controlled_env = {"PATH": "/usr/bin", "HOME": "/tmp"}

        launcher.run(build_probe_argv(probe, out_path, 0), str(tmp_path), controlled_env, 10)

        observed = read_final_child_result(out_path)
        # EXPECTED RED against the frozen pre-fix baseline
        # (KIB-ADC-CAPABILITY-AUTH-TERMINAL-BOUNDARY-TC-FIX-001,
        # DEF-013B): DesktopTerminalProvider.run()'s current
        # `launcher_env = {**os.environ, **env}` composition means the
        # ADC process's own full host environment -- including this
        # secret-like variable -- reaches the wrapped command
        # unfiltered, because a dict update only OVERRIDES keys present
        # in `env`; every other key from os.environ passes through
        # unchanged. This must become False once a future authorized
        # product fix confines the wrapped command's own environment to
        # exactly the controlled allowlist while still giving the
        # terminal EMULATOR process itself whatever real desktop-session
        # variables it separately needs.
        assert "ADC_TEST_SECRET_TOKEN" not in observed["env"]
        assert observed["env"].get("PATH") == "/usr/bin"
        assert observed["env"].get("HOME") == "/tmp"

    def test_final_child_argv_preserves_spaces_and_shell_metacharacters(self, tmp_path, monkeypatch):
        from tests.terminal_final_child_probe import (
            build_probe_argv, probe_provider, read_final_child_result,
            write_final_child_probe,
        )
        provider = probe_provider(tmp_path, monkeypatch)
        launcher = InteractiveTerminalLauncher(provider=provider)
        probe = write_final_child_probe(tmp_path)
        out_path = tmp_path / "result.json"
        dangerous_args = ("an arg with spaces", "meta;chars$(whoami)&|<>`x`")

        launcher.run(
            build_probe_argv(probe, out_path, 0, *dangerous_args),
            str(tmp_path), {"PATH": "/usr/bin"}, 10,
        )

        observed = read_final_child_result(out_path)
        assert observed["argv"] == list(dangerous_args)

    def test_final_child_exit_code_propagates_exactly(self, tmp_path, monkeypatch):
        from tests.terminal_final_child_probe import (
            build_probe_argv, probe_provider, write_final_child_probe,
        )
        provider = probe_provider(tmp_path, monkeypatch)
        launcher = InteractiveTerminalLauncher(provider=provider)
        probe = write_final_child_probe(tmp_path)
        out_path = tmp_path / "result.json"

        result = launcher.run(
            build_probe_argv(probe, out_path, 13), str(tmp_path), {"PATH": "/usr/bin"}, 10,
        )
        assert result.returncode == 13

    def test_final_child_is_spawned_exactly_once(self, tmp_path, monkeypatch):
        """A REAL, subprocess.Popen()-independent launch count: the
        final child itself appends a line to a counter file before
        writing its result -- the same "count via a real observable
        side effect, never a mock's call count" principle
        tests/local_package_fixture.py::build_launch_counting_target
        already establishes for the direct execute_controlled path."""
        from tests.terminal_final_child_probe import (
            build_probe_argv, probe_provider, write_final_child_probe,
        )
        provider = probe_provider(tmp_path, monkeypatch)
        launcher = InteractiveTerminalLauncher(provider=provider)
        probe = write_final_child_probe(tmp_path)
        out_path = tmp_path / "result.json"
        counter_file = tmp_path / "launch-count.txt"

        # A tiny wrapper counting script fronts the probe: it appends
        # one line then execs the probe unchanged, so the count is a
        # real filesystem side effect of the FINAL exec chain, not a
        # count of DesktopTerminalProvider.run() invocations.
        counting_wrapper = tmp_path / "counting-wrapper.sh"
        counting_wrapper.write_text(
            f'#!/bin/sh\necho launch >> "{counter_file}"\nexec "$@"\n'
        )
        counting_wrapper.chmod(0o700)

        argv = (str(counting_wrapper),) + build_probe_argv(probe, out_path, 0)
        launcher.run(argv, str(tmp_path), {"PATH": "/usr/bin"}, 10)

        assert counter_file.read_text().count("launch") == 1


# ============================================================================
# Security: no path in this module ever touches the wrapped command's
# own stdin -- structural proof that ADC cannot receive a sudo password.
# ============================================================================

class TestNoPasswordHandling:
    def test_provider_run_signature_has_no_credential_parameter(self):
        import inspect
        sig = inspect.signature(DesktopTerminalProvider.run)
        for name in sig.parameters:
            assert "password" not in name.lower()
            assert "credential" not in name.lower()

    def test_launcher_run_signature_has_no_credential_parameter(self):
        import inspect
        sig = inspect.signature(InteractiveTerminalLauncher.run)
        for name in sig.parameters:
            assert "password" not in name.lower()
            assert "credential" not in name.lower()

    def test_module_never_constructs_a_sudo_invocation_itself(self):
        """The only surfaces this module ever builds argv on are the
        candidate terminal flags and the wrapper script -- neither may
        ever reference sudo; the module's own prose docstrings may
        (and do) mention sudo when explaining the design, which is not
        what this test is about."""
        from app.interactive_terminal import _CANDIDATE_TERMINALS
        from app import terminal_status_producer
        import ast
        import inspect
        # Exclude explanatory prose; inspect executable literals for any
        # product-created sudo invocation, preserving the original purpose.
        tree = ast.parse(inspect.getsource(terminal_status_producer.main))
        assert not any(isinstance(node, ast.Constant) and isinstance(node.value, str)
                       and "sudo" in node.value.lower() for node in ast.walk(tree))
        for name, flags in _CANDIDATE_TERMINALS:
            assert "sudo" not in name.lower()
            assert not any("sudo" in flag.lower() for flag in flags)

    def test_wrapped_command_stdio_is_never_piped_back_to_adc(self):
        import inspect
        source = inspect.getsource(DesktopTerminalProvider.run)
        assert "PIPE" not in source  # the wrapped command's stdio is never piped back to ADC

    def test_outer_popen_never_pipes_stdin_stdout_stderr_of_wrapped_command(self):
        import inspect
        source = inspect.getsource(DesktopTerminalProvider.run)
        assert "stdin=subprocess.DEVNULL" in source
        assert "stdout=subprocess.DEVNULL" in source
        assert "stderr=subprocess.DEVNULL" in source


# ============================================================================
# Section 8: real terminal smoke check (harmless, best-effort, no sudo,
# no install). Reports NOT_AVAILABLE rather than faking a PASS.
#
# KIA-ADC-GATE1-HARNESS-PROOF-FIX-001 section 9: this intrinsically
# launches a REAL desktop terminal emulator whenever one happens to be
# present on PATH -- exactly the kind of ambient-host-state-dependent
# real effect Gate-1 must never run as ordinary deterministic
# verification. Marked real_system (the existing, established opt-in
# marker; see tests/conftest.py) so it is skipped unless a human
# operator explicitly passes --real-system-e2e, instead of silently
# depending on whether this host happens to have a terminal installed.
# ============================================================================

@pytest.mark.real_system
class TestRealTerminalSmoke:
    def test_real_terminal_smoke_check(self, tmp_path):
        provider = DesktopTerminalProvider()
        if not provider.is_available():
            pytest.skip("REAL_TERMINAL_SMOKE=NOT_AVAILABLE: no supported "
                        "visible terminal emulator on PATH in this environment")
        launcher = InteractiveTerminalLauncher(provider)
        result = launcher.run(("true",), str(tmp_path), {"PATH": "/usr/bin:/bin"}, 15)
        assert result.returncode == 0
