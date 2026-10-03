"""DEF-RSE033-ESPHOME-COMPILE-TIMEOUT / FINAL_CHILD_STATUS_FIDELITY:
permanent lower-gate regressions.

CLAUDE-ADC-RSE033-RESIDUAL-DISTRIBUTION-PTY-CLOSURE-FIX-003. The visible
PTY launcher read untyped exit values from its FIFO and discarded the
shell's startup value after a fixed 0.3 s pause. When the shell needed
longer to start, the startup value was published as the controlled
command's exit status -- before the command had even run -- and a shell
ending without a completion record had its own exit status written as
the command's returncode.

ARC_REQ_009 / SUB_REQ_010 / SUB_REQ_032: the final productive child's
real exit status and output are authoritative; launcher/shell lifecycle
and cleanup never replace or pre-empt them, and no completion means a
fail-closed result, never success and never a fabricated status. Every
case runs the REAL launcher script in a real PTY with a real interactive
bash; adversarial shell behavior comes from a real ~/.bashrc (HOME is
pointed at a temporary directory). No sleep in this file decides a
phase: tests wait for evidence files or process exit.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.execution_presenter import (
    _PTY_LAUNCHER_SCRIPT,
    PresentedCommandResult,
    TerminalCommandRunner,
    TerminalExecutionPresenter,
)

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or shutil.which("bash") is None,
    reason="needs a Linux PTY and bash",
)

_EXIT = "import sys; sys.exit({code})"


def _py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def _home(root: Path, bashrc: str | None) -> Path:
    home = root / "home"
    home.mkdir()
    if bashrc is not None:
        (home / ".bashrc").write_text(bashrc)
    return home


def _launch(root: Path, command: list[str], *, bashrc: str | None = None, extra_env=None):
    """Start the real launcher headless; returns (process, result_file)."""
    home = _home(root, bashrc)
    env = {**os.environ, "HOME": str(home), **(extra_env or {})}
    result_file = root / "result.json"
    config = {
        "command": command, "result_file": str(result_file), "stdout_capture": None,
        "env": env, "cwd": str(root), "auto_close": True,
    }
    (root / "config.json").write_text(json.dumps(config))
    script = root / "pty_launcher.py"
    script.write_text(_PTY_LAUNCHER_SCRIPT)
    process = subprocess.Popen(
        [sys.executable, str(script), str(root / "config.json")],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        env=env, start_new_session=True,
    )
    return process, result_file


def _run(root: Path, command: list[str], **kwargs) -> tuple[int, dict]:
    process, result_file = _launch(root, command, **kwargs)
    _, stderr = process.communicate(timeout=60)
    assert result_file.exists(), stderr
    return process.returncode, json.loads(result_file.read_text())


def _wait_for(path: Path, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        assert time.monotonic() < deadline, f"no evidence at {path}"
        time.sleep(0.05)


class TestStartupIsNotCompletion:
    @pytest.mark.parametrize("startup_delay", ["0", "1", "2"])
    def test_slow_shell_startup_never_becomes_the_command_result(self, tmp_path, startup_delay):
        """The parent defect: a shell that is still starting after the old
        fixed 0.3 s pause had its startup status published as the result."""
        code = "import sys; print('command-' + 'ran'); sys.exit(42)"
        launcher_status, result = _run(tmp_path, _py(code), bashrc=f"sleep {startup_delay}\n")
        assert result["completed"] is True
        assert result["returncode"] == 42 and launcher_status == 42
        assert "command-ran" in result["stdout"]

    def test_spoofed_early_completion_record_is_a_protocol_violation(self, tmp_path):
        """A COMPLETE record before the shell is even ready is never
        accepted as a command result: the command is not run, and the run
        fails closed without a returncode."""
        marker = tmp_path / "command-ran"
        fifo = tmp_path / "exit_code.fifo"
        bashrc = f'printf "ADC-PTY-V1 COMPLETE 0\\n" > "{fifo}"\n'
        launcher_status, result = _run(
            tmp_path, _py(f"open({str(marker)!r}, 'w').close()"), bashrc=bashrc,
        )
        assert result["completed"] is False and result["returncode"] is None
        assert result["failure"] == "protocol_violation"
        assert launcher_status != 0 and not marker.exists()


class TestFinalChildStatusIsAuthoritative:
    def test_case_a_shell_ends_0_final_child_nonzero(self, tmp_path):
        launcher_status, result = _run(tmp_path, _py(_EXIT.format(code=5)), bashrc="trap 'exit 0' EXIT\n")
        assert (result["completed"], result["returncode"], launcher_status) == (True, 5, 5)

    def test_case_b_shell_ends_nonzero_after_final_child_0(self, tmp_path):
        shell_ended = tmp_path / "shell-ended-9"
        bashrc = f"trap 'touch {shell_ended}; exit 9' EXIT\n"
        launcher_status, result = _run(tmp_path, _py(_EXIT.format(code=0)), bashrc=bashrc)
        assert shell_ended.exists()  # the shell lifecycle really ended with 9 ...
        assert (result["completed"], result["returncode"], launcher_status) == (True, 0, 0)  # ... cleanup-only

    @pytest.mark.parametrize("code", [0, 7])
    def test_case_c_matching_statuses_are_preserved(self, tmp_path, code):
        launcher_status, result = _run(tmp_path, _py(_EXIT.format(code=code)))
        assert (result["completed"], result["returncode"], launcher_status) == (True, code, code)

    def test_signal_killed_final_child_is_its_real_status(self, tmp_path):
        _, result = _run(tmp_path, _py("import os, signal; os.kill(os.getpid(), signal.SIGTERM)"))
        assert (result["completed"], result["returncode"]) == (True, 128 + signal.SIGTERM)

    def test_case_d_shell_ending_without_completion_fabricates_no_status(self, tmp_path):
        marker = tmp_path / "command-ran"
        launcher_status, result = _run(
            tmp_path, _py(f"open({str(marker)!r}, 'w').close()"), bashrc="exit 5\n",
        )
        assert result["completed"] is False and result["returncode"] is None
        assert result["failure"] == "no_command_completion" and result["shell_status"] == 5
        assert launcher_status != 0 and not marker.exists()

    def test_case_e_result_survives_later_launcher_kill_and_reap(self, tmp_path):
        """Completion is recorded while the shell lifecycle is still running
        (its EXIT trap keeps it alive); killing and reaping the launcher
        afterwards cannot overwrite the published result."""
        code = "import sys; print('final-' + 'output'); sys.exit(3)"
        process, result_file = _launch(tmp_path, _py(code), bashrc="trap 'sleep 5' EXIT\n")
        _wait_for(result_file)
        published = result_file.read_bytes()
        assert process.poll() is None  # lifecycle still running
        os.killpg(process.pid, signal.SIGKILL)
        assert process.wait(timeout=30) == -signal.SIGKILL
        assert result_file.read_bytes() == published
        result = json.loads(published)
        assert (result["completed"], result["returncode"]) == (True, 3)
        assert "final-output" in result["stdout"]


class TestFinalChildOutputFidelity:
    def test_all_output_written_before_completion_is_in_the_result(self, tmp_path):
        code = (
            "import sys; sys.stdout.write(('x' * 99 + chr(10)) * 3000); "
            "print('END-' + 'MARKER'); sys.stdout.flush(); sys.exit(4)"
        )
        _, result = _run(tmp_path, _py(code), bashrc="sleep 1\n")
        assert result["returncode"] == 4
        assert result["stdout"].count("x" * 99) == 3000
        assert "END-MARKER" in result["stdout"]

    def test_command_environment_output_is_captured_after_slow_startup(self, tmp_path):
        """The reproduced escape: the environment reached the child, but the
        result was published before the child's output was captured."""
        code = "import os; print('env=' + os.environ.get('ADC_FIDELITY_VAR', 'MISSING'))"
        _, result = _run(
            tmp_path, _py(code), bashrc="sleep 1\n", extra_env={"ADC_FIDELITY_VAR": "reached"},
        )
        assert result["completed"] is True and result["returncode"] == 0
        assert "env=reached" in result["stdout"]


class _HeadlessLaunchPresenter(TerminalExecutionPresenter):
    """The real presenter configuration and launcher, run without a
    terminal emulator (the emulator prefix of the real argv is dropped)."""

    def __init__(self):
        super().__init__(terminal_command="/usr/bin/gnome-terminal")
        self.processes: list[subprocess.Popen] = []

    def present_execution(self, command, title, **kwargs):
        args = self._build_terminal_args(
            command, title, kwargs.get("auto_close_on_success", True),
            stdout_capture=kwargs.get("stdout_capture"), stderr_capture=kwargs.get("stderr_capture"),
            result_file=kwargs.get("result_file"),
        )
        assert args[:2] == ["gnome-terminal", "--"]
        self.processes.append(subprocess.Popen(
            args[2:], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
        ))
        return 0  # launcher start "succeeded" -- never the command's result


@pytest.fixture
def runner_env(tmp_path, monkeypatch):
    def configure(bashrc: str | None, timeout: float = 60.0):
        monkeypatch.setenv("HOME", str(_home(tmp_path, bashrc)))
        presenter = _HeadlessLaunchPresenter()
        return TerminalCommandRunner(presenter, result_timeout_seconds=timeout), presenter

    yield configure


class TestTerminalCommandRunnerConsumesOnlyCompletion:
    def test_runner_returns_final_child_status_and_output(self, runner_env):
        runner, presenter = runner_env("sleep 1\ntrap 'exit 0' EXIT\n")
        result = runner.run(_py("import sys; print('runner-' + 'out'); sys.exit(6)"))
        assert result == PresentedCommandResult(returncode=6, stdout=result.stdout, stderr="", completed=True)
        assert "runner-out" in result.stdout
        presenter.processes[0].wait(timeout=30)

    def test_runner_fails_closed_without_completion(self, runner_env):
        runner, presenter = runner_env("exit 5\n")
        result = runner.run(_py(_EXIT.format(code=0)))
        assert result.completed is False and result.returncode is None
        assert "no_command_completion" in result.stderr
        presenter.processes[0].wait(timeout=30)

    def test_runner_timeout_is_fail_closed_without_status(self, runner_env):
        runner, presenter = runner_env(None, timeout=1)
        try:
            result = runner.run(_py("import time; time.sleep(60)"))
            assert result.completed is False and result.returncode is None
            assert "timed out" in result.stderr
        finally:
            for process in presenter.processes:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=30)
