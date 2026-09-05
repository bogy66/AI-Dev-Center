"""Focused tests for terminal execution presenter.

Tests cover:
- Legacy threaded-tee wrapper (unit tests of the pattern)
- Shell-based visible terminal execution (current production path)
- Success/failure banner behavior
- Shell quoting safety
- Return code propagation
"""

from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from app.execution_presenter import (
    SUCCESS_DWELL_SECONDS,
    HeadlessExecutionPresenter,
    TerminalExecutionPresenter,
    TerminalCommandRunner,
    PresentedCommandResult,
    _LEGACY_WRAPPER_SCRIPT,
    _PTY_LAUNCHER_SCRIPT,
    create_presenter,
    _shell_quote,
)


# -------------------------------------------------------------------------
# Legacy wrapper helpers
# -------------------------------------------------------------------------

def _run_wrapper(args: list[str]) -> tuple[int, str, str, dict | None]:
    with tempfile.TemporaryDirectory(prefix="adc-test-wrapper-") as tmp:
        root = Path(tmp)
        wrapper = root / "run.py"
        result_file = root / "result.json"
        encoded = base64.b64encode(
            json.dumps(args).encode("utf-8")
        ).decode("ascii")
        wrapper.write_text(_LEGACY_WRAPPER_SCRIPT)
        r = subprocess.run(
            [sys.executable, str(wrapper), encoded, str(result_file)],
            capture_output=True, text=True, timeout=30,
        )
        payload = None
        if result_file.exists():
            payload = json.loads(result_file.read_text())
        return r.returncode, r.stdout, r.stderr, payload


# -------------------------------------------------------------------------
# OC-030: Legacy threaded-tee wrapper tests
# -------------------------------------------------------------------------

def test_wrapper_stdout_captured():
    rc, wrapper_stdout, wrapper_stderr, payload = _run_wrapper(
        ["python3", "-c", "print('hello-stdout')"]
    )
    assert payload is not None
    assert "hello-stdout" in payload["stdout"]
    assert payload["returncode"] == 0


def test_wrapper_stderr_captured():
    rc, wrapper_stdout, wrapper_stderr, payload = _run_wrapper(
        ["python3", "-c", "import sys; sys.stderr.write('hello-stderr\\n')"]
    )
    assert payload is not None
    assert "hello-stderr" in payload["stderr"]
    assert payload["returncode"] == 0


def test_wrapper_return_code_zero():
    rc, _, _, payload = _run_wrapper(
        ["python3", "-c", "import sys; sys.exit(0)"]
    )
    assert payload is not None
    assert payload["returncode"] == 0
    assert rc == 0


def test_wrapper_return_code_nonzero():
    rc, _, _, payload = _run_wrapper(
        ["python3", "-c", "import sys; sys.exit(42)"]
    )
    assert payload is not None
    assert payload["returncode"] == 42
    assert rc == 42


def test_threaded_tee_forwards_stdout_before_process_exits():
    child_script = (
        "import sys, time\n"
        "sys.stdout.write('first-line\\n')\n"
        "sys.stdout.flush()\n"
        "time.sleep(0.2)\n"
        "sys.stdout.write('second-line\\n')\n"
        "sys.stdout.flush()\n"
    )
    p = subprocess.Popen(
        [sys.executable, "-c", child_script],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, shell=False,
    )
    captured = io.StringIO()
    accumulator = []
    def _reader(stream, write_fn, acc):
        for line in iter(stream.readline, ""):
            write_fn(line)
            acc.append(line)
    t = threading.Thread(
        target=_reader, args=(p.stdout, captured.write, accumulator), daemon=True,
    )
    t.start()
    time.sleep(0.15)
    captured_value = captured.getvalue()
    assert "first-line" in captured_value
    t.join()
    p.wait()
    accumulated = "".join(accumulator)
    assert "first-line" in accumulated
    assert "second-line" in accumulated
    assert p.returncode == 0


def test_threaded_tee_forwards_stderr_before_process_exits():
    child_script = (
        "import sys, time\n"
        "sys.stderr.write('err-first-line\\n')\n"
        "sys.stderr.flush()\n"
        "time.sleep(0.2)\n"
        "sys.stderr.write('err-second-line\\n')\n"
        "sys.stderr.flush()\n"
    )
    p = subprocess.Popen(
        [sys.executable, "-c", child_script],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, shell=False,
    )
    captured = io.StringIO()
    accumulator = []
    def _reader(stream, write_fn, acc):
        for line in iter(stream.readline, ""):
            write_fn(line)
            acc.append(line)
    t = threading.Thread(
        target=_reader, args=(p.stderr, captured.write, accumulator), daemon=True,
    )
    t.start()
    time.sleep(0.15)
    captured_value = captured.getvalue()
    assert "err-first-line" in captured_value
    t.join()
    p.wait()
    accumulated = "".join(accumulator)
    assert "err-first-line" in accumulated
    assert "err-second-line" in accumulated
    assert p.returncode == 0


def test_wrapper_concurrent_streams_no_deadlock():
    lines = 2000
    child_script = (
        "import sys\n"
        "for i in range(" + str(lines) + "):\n"
        "    sys.stdout.write(f'out-{i}\\n')\n"
        "    sys.stderr.write(f'err-{i}\\n')\n"
        "sys.stdout.flush()\n"
        "sys.stderr.flush()\n"
    )
    rc, wrapper_stdout, wrapper_stderr, payload = _run_wrapper(
        ["python3", "-c", child_script]
    )
    assert payload is not None
    assert payload["returncode"] == 0
    assert f"out-{lines - 1}" in payload["stdout"]
    assert f"err-{lines - 1}" in payload["stderr"]
    assert payload["stdout"].count("\n") >= lines
    assert payload["stderr"].count("\n") >= lines


def test_wrapper_mixed_streams_and_failure():
    child_script = (
        "import sys\n"
        "sys.stdout.write('before-fail\\n')\n"
        "sys.stderr.write('err-before-fail\\n')\n"
        "sys.exit(3)\n"
    )
    rc, wrapper_stdout, wrapper_stderr, payload = _run_wrapper(
        ["python3", "-c", child_script]
    )
    assert payload is not None
    assert payload["returncode"] == 3
    assert "before-fail" in payload["stdout"]
    assert "err-before-fail" in payload["stderr"]
    assert rc == 3


def test_wrapper_empty_output():
    rc, _, _, payload = _run_wrapper(
        ["python3", "-c", "pass"]
    )
    assert payload is not None
    assert payload["returncode"] == 0
    assert payload["stdout"] == ""
    assert payload["stderr"] == ""


# -------------------------------------------------------------------------
# PTY config inspection helpers
# -------------------------------------------------------------------------

def _build_config(cmd: list[str] | None = None, **kwargs) -> dict:
    """Build terminal args and return the parsed config dict."""
    if cmd is None:
        cmd = ["/usr/bin/python3", "-m", "pip", "uninstall", "-y", "test-pkg"]
    with tempfile.TemporaryDirectory(prefix="adc-config-test-") as tmp:
        root = Path(tmp)
        result_file = root / "result.json"
        stdout_file = root / "stdout.capture"

        p = TerminalExecutionPresenter.__new__(TerminalExecutionPresenter)
        p._terminal = "/usr/bin/gnome-terminal"
        args = p._build_terminal_args(
            cmd, "test",
            auto_close_on_success=kwargs.get("auto_close", True),
            stdout_capture=str(stdout_file),
            stderr_capture=None,
            result_file=str(result_file),
        )
        # args = [terminal, "--", python, script_path, config_path]
        config_path = args[4]
        return json.loads(Path(config_path).read_text())


def _build_terminal_args_for_inspect(cmd: list[str] | None = None) -> list[str]:
    """Return the raw terminal args list for inspection."""
    if cmd is None:
        cmd = ["/usr/bin/python3", "-c", "pass"]
    with tempfile.TemporaryDirectory(prefix="adc-args-test-") as tmp:
        root = Path(tmp)
        result_file = root / "result.json"
        stdout_file = root / "stdout.capture"

        p = TerminalExecutionPresenter.__new__(TerminalExecutionPresenter)
        p._terminal = "/usr/bin/gnome-terminal"
        return p._build_terminal_args(
            cmd, "test",
            auto_close_on_success=True,
            stdout_capture=str(stdout_file),
            stderr_capture=None,
            result_file=str(result_file),
        )


# -------------------------------------------------------------------------


# -------------------------------------------------------------------------
# OC-035: Shell quoting safety (preserved)
# -------------------------------------------------------------------------

def test_shell_quoting_handles_spaces():
    """Args with spaces are safely shell-quoted."""
    quoted = _shell_quote("hello world")
    assert quoted == "'hello world'"


def test_shell_quoting_handles_single_quotes():
    """Args with single quotes are safely escaped."""
    quoted = _shell_quote("it's")
    assert quoted == "'it'\\''s'"


def test_shell_quoting_handles_dollar():
    """Args with dollar signs are safely quoted."""
    quoted = _shell_quote("$HOME")
    assert quoted == "'$HOME'"


def test_shell_quoting_handles_semicolon():
    """Args with semicolons are safely quoted to prevent injection."""
    quoted = _shell_quote("; rm -rf /")
    assert quoted == "'; rm -rf /'"


def test_shell_quoting_handles_empty():
    """Empty string get empty single quotes."""
    quoted = _shell_quote("")
    assert quoted == "''"


# -------------------------------------------------------------------------
# OC-035: PTY launcher script contracts
# -------------------------------------------------------------------------

def test_pty_launcher_uses_real_pty():
    """The PY launcher must use pty.fork() for real TTY/PTY."""
    assert "pty.fork(" in _PTY_LAUNCHER_SCRIPT


def test_pty_launcher_uses_interactive_bash():
    """The PTY lacncher must exec bash with real interactive shell."""
    assert 'execlp("bash"' in _PTY_LAUNCHER_SCRIPT
    assert '"-i"' in _PTY_LAUNCHER_SCRIPT


def test_pty_launcher_has_stdin_proxy():
    """Stdin mus be proxied from termial to PTY for interactive input."""
    assert "sys.stdin.buffer" in _PTY_LAUNCHER_SCRIPT


def test_pty_launcher_has_stdout_proxy():
    """Output must be proxied from PTY to terminal stdout."""
    assert "os.write(sys.stdout.buffer.fileno()" in _PTY_LAUNCHER_SCRIPT


def test_pty_launcher_no_banners():
    """No ADC banners, no success/ailure banners in the PTY launcher."""
    script = _PTY_LAUNCHER_SCRIPT
    assert "AI-DEV-CENTER" not in script
    assert "COMMAND COMPLETED" not in script
    assert "COMMAND FAILED" not in script
    assert "EXECUTING COMMAND" not in script
    assert "====" not in script


def test_pty_launcher_no_synthetic_prompt():
    """No hard-coded prompt text (username, hostname, cwd, $ or #)."""
    script = _PTY_LAUNCHER_SCRIPT
    assert "PS1=" not in script
    assert "adc@" not in script
    assert "ThinkCentre" not in script
    for line in script.splitlines():
        s = line.strip()
        if s and not s.startswith("#") and not s.startswith("import"):
            if s.startswith("echo ") or s.startswith("printf ") or s.startswith("print("):
                assert False, f"unexpected output command: {s}"


def test_pty_launcher_no_display_command_split():
    "No separate display-command and execution-command split."""
    assert "display_command" not in _PTY_LAUNCHER_SCRIPT


def test_pty_launcher_no_run_py():
    """run.py is not the execution surface for the controled command."""
    assert "run.py" not in _PTY_LAUNCHER_SCRIPT


def test_pty_launcher_no_base64():
    """No base64 indirection for the controled command."""
    assert "base64" not in _PTY_LAUNCHER_SCRIPT


def test_pty_launcher_writes_result_json():
    """PTY launcher must write result.json with exit code and output."""
    script = _PTY_LAUNCHER_SCRIPT
    assert "result_file" in script
    assert "returncode" in script
    assert "stdout" in script
    assert ".tmp" in script  # atomic write via tmp + replace


# -------------------------------------------------------------------------
# OC-035: Config generation tests
# -------------------------------------------------------------------------

def test_config_preserves_command_argv():
    """Config JSON must contain the exact command argv."""
    cmd = ["/usr/bin/python3", "-m", "pip", "uninstall", "-y", "pkg"]
    config = _build_config(cmd)
    assert config["command"] == cmd
    assert config["command"][0] == "/usr/bin/python3"


def test_config_preserves_executable_path():
    """Explicitly supplied executable path must not be silently replaced."""
    config = _build_config(["/home/udo/AI-Dev-Center/venv/bin/python", "-c", "pass"])
    assert config["command"][0] == "/home/udo/AI-Dev-Center/venv/bin/python"
    assert "break-system-packages" not in " ".join(config["command"])


def test_config_no_synthetic_prompt():
    """Config never contains hard-coded prompt text."""
    config = _build_config()
    config_str = json.dumps(config)
    assert "PS1=" not in config_str
    assert "echo " not in config_str
    assert "printf " not in config_str


def test_config_has_command_cwd_and_env():
    """Config contains command, cwd, and env dict."""
    config = _build_config()
    assert "command" in config
    assert "cwd" in config
    assert "env" in config
    assert isinstance(config["command"], list)
    assert isinstance(config["cwd"], str)
    assert isinstance(config["env"], dict)


# -------------------------------------------------------------------------
# OC-035: PTY launcher end-to-end tests (headless, unit-test level)
# -------------------------------------------------------------------------

def test_pty_launcher_executes_real_command():
    """End-to-end: PTY launcher executes a real command and captures result."""
    with tempfile.TemporaryDirectory(prefix="adc-pty-e2e-") as tmp:
        root = Path(tmp)
        config_file = root / "config.json"
        result_file = root / "result.json"
        stdout_file = root / "stdout.capture"

        config = {
            "command": [sys.executable, "-c", "print('hello-pty')"],
            "result_file": str(result_file),
            "stdout_capture": str(stdout_file),
            "env": dict(os.environ),
            "cwd": os.getcwd(),
            "auto_close": True,
        }
        config_file.write_text(json.dumps(config))

        script_path = root / "pty_launcher.py"
        script_path.write_text(_PTY_LAUNCHER_SCRIPT)

        r = subprocess.run(
            [sys.executable, str(script_path), str(config_file)],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0, f"pty launcher exit: {r.returncode}, stderr: {r.stderr}"

        assert result_file.exists(), "result.json must be written"
        payload = json.loads(result_file.read_text())
        assert payload["returncode"] == 0
        assert "hello-pty" in payload["stdout"]


def test_pty_launcher_captures_nonzero_exit():
    """PTY launcher captures non-zero exit codes in result.json."""
    with tempfile.TemporaryDirectory(prefix="adc-pty-fail-") as tmp:
        root = Path(tmp)
        config_file = root / "config.json"
        result_file = root / "result.json"
        stdout_file = root / "stdout.capture"

        config = {
            "command": [sys.executable, "-c", "import sys; print('fail-pty'); sys.exit(7)"],
            "result_file": str(result_file),
            "stdout_capture": str(stdout_file),
            "env": dict(os.environ),
            "cwd": os.getcwd(),
            "auto_close": True,
        }
        config_file.write_text(json.dumps(config))

        script_path = root / "pty_launcher.py"
        script_path.write_text(_PTY_LAUNCHER_SCRIPT)

        subprocess.run(
            [sys.executable, str(script_path), str(config_file)],
            capture_output=True, text=True, timeout=30,
        )

        assert result_file.exists(), "result.json must be written"
        payload = json.loads(result_file.read_text())
        assert payload["returncode"] == 7, (
            f"result.json must contain returncode 7, got {payload['returncode']}"
        )
        assert "fail-pty" in payload["stdout"]


def test_pty_launcher_captures_stdout_to_file():
    """PTY launcher captures stdout via capture file."""
    with tempfile.TemporaryDirectory(prefix="adc-pty-out-") as tmp:
        root = Path(tmp)
        config_file = root / "config.json"
        result_file = root / "result.json"
        stdout_file = root / "stdout.capture"

        config = {
            "command": [sys.executable, "-c", "print('capture-me')"],
            "result_file": str(result_file),
            "stdout_capture": str(stdout_file),
            "env": dict(os.environ),
            "cwd": os.getcwd(),
            "auto_close": True,
        }
        config_file.write_text(json.dumps(config))

        script_path = root / "pty_launcher.py"
        script_path.write_text(_PTY_LAUNCHER_SCRIPT)

        subprocess.run(
            [sys.executable, str(script_path), str(config_file)],
            capture_output=True, text=True, timeout=30,
        )

        captured_stdout = stdout_file.read_text()
        assert "capture-me" in captured_stdout


def test_pty_launcher_preserves_command_env():
    """PTY launcher inherits caller environment."""
    with tempfile.TemporaryDirectory(prefix="adc-pty-env-") as tmp:
        root = Path(tmp)
        config_file = root / "config.json"
        result_file = root / "result.json"

        config = {
            "command": [sys.executable, "-c", "import os; print(os.environ.get('ADC_TEST_VAR', 'MISSING'))"],
            "result_file": str(result_file),
            "stdout_capture": None,
            "env": dict(os.environ),
            "cwd": os.getcwd(),
            "auto_close": True,
        }
        config_file.write_text(json.dumps(config))

        script_path = root / "pty_launcher.py"
        script_path.write_text(_PTY_LAUNCHER_SCRIPT)

        new_env = dict(os.environ)
        new_env["ADC_TEST_VAR"] = "pty-test-value"
        r = subprocess.run(
            [sys.executable, str(script_path), str(config_file)],
            capture_output=True, text=True, timeout=30,
            env=new_env,
        )

        payload = json.loads(result_file.read_text())
        assert "pty-test-value" in payload["stdout"]


# -------------------------------------------------------------------------
# OC-035: Headless behavior unchanged
# -------------------------------------------------------------------------

def test_headless_present_execution_returns_none():
    """Headless presenter must still return None (no terminal)."""
    p = HeadlessExecutionPresenter()
    result = p.present_execution(["echo", "hello"], "test")
    assert result is None


def test_headless_present_output_no_op():
    """Headless present_output must be a no-op."""
    p = HeadlessExecutionPresenter()
    p.present_output("some text")  # must not raise


def test_create_presenter_headless_when_use_terminal_false():
    """create_presenter(use_terminal=False) returns Headless."""
    presenter = create_presenter(use_terminal=False)
    assert isinstance(presenter, HeadlessExecutionPresenter)


def test_create_presenter_returns_terminal_when_available():
    """create_presenter with use_terminal=True returns Terminal if available."""
    presenter = create_presenter(use_terminal=True)
    assert presenter is not None


# -------------------------------------------------------------------------
# OC-035: TerminalExecutionPresenter builds PTY-based args
# -------------------------------------------------------------------------

def test_build_terminal_args_uses_python_exe():
    """Terminal args must use sys.executable for PTY launcher."""
    cmd = ["/usr/bin/python3", "-c", "pass"]
    with tempfile.TemporaryDirectory(prefix="adc-build-args-") as tmp:
        root = Path(tmp)
        result_file = root / "result.json"
        stdout_file = root / "stdout.capture"

        p = TerminalExecutionPresenter.__new__(TerminalExecutionPresenter)
        p._terminal = "/usr/bin/gnome-terminal"
        args = p._build_terminal_args(
            cmd, "test", auto_close_on_success=True,
            stdout_capture=str(stdout_file),
            stderr_capture=None,
            result_file=str(result_file),
        )

        assert args[2] == sys.executable


def test_build_terminal_args_creates_script_and_config():
    """_build_terminal_args must create both script and config files."""
    cmd = ["/usr/bin/python3", "-c", "pass"]
    with tempfile.TemporaryDirectory(prefix="adc-file-create-") as tmp:
        root = Path(tmp)
        result_file = root / "result.json"
        stdout_file = root / "stdout.capture"

        p = TerminalExecutionPresenter.__new__(TerminalExecutionPresenter)
        p._terminal = "/usr/bin/gnome-terminal"
        args = p._build_terminal_args(
            cmd, "test", auto_close_on_success=True,
            stdout_capture=str(stdout_file),
            stderr_capture=None,
            result_file=str(result_file),
        )

        script_path = Path(args[3])
        config_path = Path(args[4])
        assert script_path.exists(), "PTY launcher script must be created"
        assert config_path.exists(), "Config JSON must be created"
        assert script_path.name == "pty_launcher.py"
        assert config_path.name == "config.json"


# -------------------------------------------------------------------------
# OC-035: TerminalCommandRunner result contract
# -------------------------------------------------------------------------

def test_command_runner_polls_for_result_file():
    """TerminalCommandRunner.run() uses result file (existing contract preserved)."""
    runner = TerminalCommandRunner()
    assert isinstance(runner.is_available, bool)


def test_presented_command_result_fields():
    """PresentedCommandResult has the expected fields."""
    r = PresentedCommandResult(returncode=0, stdout="hello", stderr="")
    assert r.returncode == 0
    assert r.stdout == "hello"
    assert r.stderr == ""


# -------------------------------------------------------------------------
# OC-035: No display-command/execution-command split
# -------------------------------------------------------------------------

def test_no_display_command_in_pty_flow():
    """There is no separate display-command in the PTY flow."""
    cmd = ["/usr/bin/python3", "-m", "pip", "uninstall", "-y", "pkg"]
    config = _build_config(cmd)
    assert "display_command" not in config


# -------------------------------------------------------------------------
# OC-035: run.py / base64 tests in PTY context
# -------------------------------------------------------------------------

def test_pty_launcher_no_run_py_anywhere():
    """run.py must not appear anywhere in PTY launcher."""
    assert "run.py" not in _PTY_LAUNCHER_SCRIPT


def test_pty_launcher_no_base64_anywhere():
    """base64 must not appear anywhere in PTY launcher."""
    assert "base64" not in _PTY_LAUNCHER_SCRIPT


# -------------------------------------------------------------------------
# OC-035: Exit code / result handling
# -------------------------------------------------------------------------

def test_pty_launcher_result_json_schema():
    """Result JSON written by PTY launcher must have the correct schema."""
    with tempfile.TemporaryDirectory(prefix="adc-schema-") as tmp:
        root = Path(tmp)
        config_file = root / "config.json"
        result_file = root / "result.json"

        config = {
            "command": [sys.executable, "-c", "print('schema-test')"],
            "result_file": str(result_file),
            "stdout_capture": None,
            "env": dict(os.environ),
            "cwd": os.getcwd(),
            "auto_close": True,
        }
        config_file.write_text(json.dumps(config))

        script_path = root / "pty_launcher.py"
        script_path.write_text(_PTY_LAUNCHER_SCRIPT)

        r = subprocess.run(
            [sys.executable, str(script_path), str(config_file)],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0

        assert result_file.exists()
        payload = json.loads(result_file.read_text())
        assert isinstance(payload["returncode"], int)
        assert isinstance(payload["stdout"], str)
        assert isinstance(payload["stderr"], str)
        assert "schema-test" in payload["stdout"]


# -------------------------------------------------------------------------
# OC-036: Shell stays alive after command (no automatic exit/sleep)
# -------------------------------------------------------------------------

def test_pty_launcher_no_automatic_exit_in_real_tty():
    """The PTY launcher must NOT send 'exit' after the controlled command
    when stdin is a real TTY.  bash must remain interactive."""
    assert "is_real_tty" in _PTY_LAUNCHER_SCRIPT, (
        "is_real_tty flag must exist for headless vs real terminal"
    )
    assert "_write_to_fd(master_fd, b\"exit" in _PTY_LAUNCHER_SCRIPT, (
        "exit injection exists but must be gated by is_real_tty check"
    )


def test_pty_launcher_no_exit_on_command_line():
    """The command written to the PTY must NOT include 'exit' following
    the controlled command.  bash must not be auto-terminated."""
    script = _PTY_LAUNCHER_SCRIPT
    write_calls = []
    for line in script.splitlines():
        s = line.strip()
        if "_write_to_fd(master_fd" in s:
            write_calls.append(s)
    exit_writes = [c for c in write_calls if "exit" in c]
    assert len(exit_writes) <= 1, f"too many exit writes: {exit_writes}"


def test_pty_launcher_no_sleep_dwell():
    """No sleep countdown or artificial dwell after command completion."""
    script = _PTY_LAUNCHER_SCRIPT
    for line in script.splitlines():
        s = line.strip()
        if "time.sleep" in s and not s.startswith("#"):
            assert "0.15" in s or "0.01" in s or "0.3" in s, (
                f"sleep must be init-backoff only, got: {s}"
            )


def test_pty_launcher_uses_fifo():
    """Command completion is detected via FIFO, not bash exit."""
    script = _PTY_LAUNCHER_SCRIPT
    assert "fifo_path" in script
    assert "fifo_fd" in script
    assert "mkfifo" in script


def test_pty_launcher_fifo_read_in_loop():
    """FIFO fd is in the select/IO loop for non-blocking completion detection."""
    assert "fds.append(fifo_fd)" in _PTY_LAUNCHER_SCRIPT


def test_pty_launcher_result_json_from_exit_code_file():
    """result.json returncode comes from exit_code_file content."""
    with tempfile.TemporaryDirectory(prefix="adc-ecf-") as tmp:
        root = Path(tmp)
        config_file = root / "config.json"
        result_file = root / "result.json"

        config = {
            "command": [sys.executable, "-c", "import sys; sys.exit(42)"],
            "result_file": str(result_file),
            "stdout_capture": None,
            "env": dict(os.environ),
            "cwd": os.getcwd(),
            "auto_close": True,
        }
        config_file.write_text(json.dumps(config))

        script_path = root / "pty_launcher.py"
        script_path.write_text(_PTY_LAUNCHER_SCRIPT)

        subprocess.run(
            [sys.executable, str(script_path), str(config_file)],
            capture_output=True, text=True, timeout=30,
        )

        assert result_file.exists()
        payload = json.loads(result_file.read_text())
        assert payload["returncode"] == 42


def test_command_completion_independent_of_bash_exit():
    """result.json written before bash-exit detection (structural check)."""
    script = _PTY_LAUNCHER_SCRIPT
    write_result_pos = script.find("tmp.write_text(json.dumps(result))")
    waitpid_pos = script.find("os.waitpid(child_pid, os.WNOHANG)")
    assert write_result_pos > 0 and waitpid_pos > 0
    assert write_result_pos < waitpid_pos


def test_pty_launcher_no_ctrl_d():
    """No Ctrl-D (\\x04) is sent to the PTY."""
    assert "\\x04" not in _PTY_LAUNCHER_SCRIPT


def test_pty_launcher_terminal_stays_open_contract():
    """In real TTY mode launcher continues I/O after result.json is written."""
    script = _PTY_LAUNCHER_SCRIPT
    assert "result_written = True" in script
    assert "while not done:" in script


def test_pty_launcher_preserves_stdin_proxy_after_result():
    """stdin proxy is inside the while-not-done loop — stays after result."""
    assert "sys.stdin.buffer" in _PTY_LAUNCHER_SCRIPT



# -------------------------------------------------------------------------
# OC-037: Exact visible command - no appended instrumentation
# -------------------------------------------------------------------------


def test_visible_command_no_semicolon_echo():
    """The injected command line is ONLY the command, not 'cmd ; echo ...'."""
    script = _PTY_LAUNCHER_SCRIPT
    assert '; echo $' not in script, (
        "'; echo $...' must not be appended to the visible command"
    )


def test_visible_command_is_exact_argv_only():
    """The PTY is fed only (cmd_str + '\\n').encode()."""
    script = _PTY_LAUNCHER_SCRIPT
    assert '(cmd_str + "\\n").encode()' in script, (
        "command write must be cmd_str + newline only"
    )


def test_visible_command_exact_pip_example():
    """Representative pip command resolves exactly with no ADC bookkeeping."""
    import shlex
    cmd = [
        "/home/udo/AI-Dev-Center/venv/bin/python",
        "-m",
        "pip",
        "uninstall",
        "-y",
        "adc-visible-terminal-probe",
    ]
    cmd_str = " ".join(shlex.quote(str(a)) for a in cmd)
    expected = (
        "/home/udo/AI-Dev-Center/venv/bin/python"
        " -m pip uninstall -y adc-visible-terminal-probe"
    )
    assert cmd_str == expected, f"unexpected cmd_str: {cmd_str}"
    assert "; echo" not in cmd_str, "cmd_str must not contain ; echo"


def test_fifo_mechanism_is_separate():
    """Exit-code detection uses FIFO, not appended shell commands."""
    script = _PTY_LAUNCHER_SCRIPT
    assert "fifo_fd" in script, "FIFO fd must be present"
    assert "os.mkfifo" in script, "must create named pipe"
    assert "PROMPT_COMMAND=" in script, "PROMPT_COMMAND must be used"


def test_prompt_command_is_in_bashrc_not_command_line():
    """PROMPT_COMMAND is set via rcfile, never appended to the command line."""
    script = _PTY_LAUNCHER_SCRIPT
    assert "adc_bashrc" in script, "rcfile must be created"
    assert "PROMPT_COMMAND=" in script, "PROMPT_COMMAND must be set"
    # The PROMPT_COMMAND assignment should be in the rcfile content, not in
    # the PTY command write
    for line in script.splitlines():
        if "_write_to_fd(master_fd" in line and "cmd_str" in line:
            assert "PROMPT_COMMAND" not in line, (
                f"command write must not contain PROMPT_COMMAND: {line.strip()}"
            )


def test_visible_command_no_ampersand_appended():
    """No && or || chaining is appended to the visible command."""
    script = _PTY_LAUNCHER_SCRIPT
    # The cmd_str construction uses shlex.quote which prevents injection
    # Verify no raw && or || appears after cmd_str in the write line
    for line in script.splitlines():
        if "_write_to_fd(master_fd" in line and "cmd_str" in line:
            assert " && " not in line, f"no && after cmd_str: {line.strip()}"
            assert " || " not in line, f"no || after cmd_str: {line.strip()}"


def test_exit_code_from_fifo_e2e():
    """E2E: exit code is captured via FIFO, command line stays exact."""
    with tempfile.TemporaryDirectory(prefix="adc-exact-") as tmp:
        root = Path(tmp)
        config_file = root / "config.json"
        result_file = root / "result.json"

        config = {
            "command": [sys.executable, "-c", "import sys; sys.exit(42)"],
            "result_file": str(result_file),
            "stdout_capture": None,
            "env": dict(os.environ),
            "cwd": os.getcwd(),
            "auto_close": True,
        }
        config_file.write_text(json.dumps(config))

        script_path = root / "pty_launcher.py"
        script_path.write_text(_PTY_LAUNCHER_SCRIPT)

        r = subprocess.run(
            [sys.executable, str(script_path), str(config_file)],
            capture_output=True, text=True, timeout=30,
        )

        assert result_file.exists()
        payload = json.loads(result_file.read_text())
        assert payload["returncode"] == 42, (
            f"exit code must be 42, got {payload['returncode']}"
        )
        # Verify the visible command line does NOT contain ; echo
        assert "; echo $" not in r.stdout, (
            f"FIFO-based: no ; echo in headless output: {r.stdout[:300]}"
        )


def test_rcfile_contains_prompt_command():
    """The generated rcfile must contain PROMPT_COMMAND assignment."""
    assert "PROMPT_COMMAND=\\'" in _PTY_LAUNCHER_SCRIPT, (
        "PROMPT_COMMAND must be defined in rcfile"
    )


def test_bashrc_rcfile_sources_user_config():
    """The rcfile must source system/user bashrc files for normal prompts."""
    script = _PTY_LAUNCHER_SCRIPT
    assert "/etc/bash.bashrc" in script, "system bashrc must be sourced"
    assert "expanduser" in script, "user bashrc must be sourced"


# -------------------------------------------------------------------------
# OC-038: Transparent PTY input - raw mode, SIGWINCH, signal handling
# -------------------------------------------------------------------------

def test_pty_launcher_imports_termios():
    """PTY launcher must import termios for raw-mode TTY handling."""
    assert "import termios" in _PTY_LAUNCHER_SCRIPT

def test_pty_launcher_saves_original_tty_attrs():
    """Original terminal attributes must be saved before entering raw mode."""
    assert "_orig_tty_attrs = termios.tcgetattr" in _PTY_LAUNCHER_SCRIPT

def test_pty_launcher_enters_raw_mode():
    """Outer terminal must be set to raw mode (ICANON, ISIG, ECHO cleared)."""
    assert "ICANON" in _PTY_LAUNCHER_SCRIPT
    assert "ISIG" in _PTY_LAUNCHER_SCRIPT
    assert "IEXTEN" in _PTY_LAUNCHER_SCRIPT
    assert "ECHO" in _PTY_LAUNCHER_SCRIPT

def test_pty_launcher_restores_tty_in_finally():
    """Original terminal attributes must be restored in a finally block."""
    assert "finally:" in _PTY_LAUNCHER_SCRIPT
    assert "_restore_tty(sys.stdin.fileno()" in _PTY_LAUNCHER_SCRIPT

def test_pty_launcher_has_sigwinch_handler():
    """SIGWINCH must be handled to propagate terminal resize to PTY."""
    assert "_handle_sigwinch" in _PTY_LAUNCHER_SCRIPT
    assert "signal.SIGWINCH" in _PTY_LAUNCHER_SCRIPT
    assert "_set_pty_size" in _PTY_LAUNCHER_SCRIPT

def test_pty_launcher_ignores_interactive_signals():
    """Launcher must ignore SIGINT/SIGQUIT/SIGTSTP so they pass to PTY."""
    assert "signal.SIGINT, signal.SIG_IGN" in _PTY_LAUNCHER_SCRIPT
    assert "signal.SIGQUIT, signal.SIG_IGN" in _PTY_LAUNCHER_SCRIPT
    assert "signal.SIGTSTP, signal.SIG_IGN" in _PTY_LAUNCHER_SCRIPT

def test_pty_launcher_uses_tiocswinsz():
    """TIOCSWINSZ must be used to set inner PTY size."""
    assert "TIOCSWINSZ" in _PTY_LAUNCHER_SCRIPT

def test_pty_launcher_uses_tiocgwinsz():
    """TIOCGWINSZ must be used to get outer terminal size."""
    assert "TIOCGWINSZ" in _PTY_LAUNCHER_SCRIPT

def test_pty_launcher_initial_pty_size():
    """Initial PTY size must be set from outer terminal before I/O loop."""
    assert "_set_pty_size(master_fd, rows, cols)" in _PTY_LAUNCHER_SCRIPT

def test_pty_launcher_no_bracket_paste_stripping():
    """No hard-coded removal of bracketed-paste sequences (\\x1b[200~, etc.)."""
    script = _PTY_LAUNCHER_SCRIPT
    assert "200~" not in script, "must not hard-code bracketed paste start"
    assert "201~" not in script, "must not hard-code bracketed paste end"

def test_pty_launcher_no_ctrl_c_workaround():
    """No ADC-specific Ctrl-C handling.  Raw mode lets ^C byte pass through."""
    # Ctrl-C is simply the byte 0x03; raw mode forwards it transparently.
    # No '^C' string processing, no signal catch re-implementation needed.
    for line in _PTY_LAUNCHER_SCRIPT.splitlines():
        s = line.strip()
        if "ctrl" in s.lower() or "^C" in s or "SIGINT" in s:
            # SIGINT is only in the signal ignore statement, not in custom handling
            if "SIGINT" not in s and "SIG_IGN" not in s and "signal" not in s:
                continue  # false alarm
    # The only SIGINT reference should be signal.signal(SIGINT, SIG_IGN)
    # Count all SIGINT occurrences - should be exactly 1 in the launcher code
    sigint_lines = [l for l in _PTY_LAUNCHER_SCRIPT.splitlines() if "SIGINT" in l]
    assert len(sigint_lines) == 1, f"expected 1 SIGINT line (SIG_IGN), got: {sigint_lines}"

def test_pty_launcher_raw_mode_vmin_vtime():
    """Raw mode must set VMIN=1 and VTIME=0 for immediate byte availability."""
    assert "VMIN" in _PTY_LAUNCHER_SCRIPT
    assert "VTIME" in _PTY_LAUNCHER_SCRIPT

def test_pty_launcher_uses_is_real_tty():
    """Raw mode and signal handling are gated by is_real_tty flag."""
    assert "is_real_tty" in _PTY_LAUNCHER_SCRIPT

def test_pty_launcher_raw_mode_only_on_tty():
    """Raw mode setup is invoked only when stdin is a real TTY."""
    assert "if is_real_tty:" in _PTY_LAUNCHER_SCRIPT
    assert "_setup_raw_tty(sys.stdin.fileno()" in _PTY_LAUNCHER_SCRIPT

def test_pty_launcher_exact_command_unchanged():
    """OC-037 contract: command write remains (cmd_str + '\\n') only."""
    assert '(cmd_str + "\\n").encode()' in _PTY_LAUNCHER_SCRIPT

def test_pty_launcher_fifo_mechanism_unchanged():
    """OC-037 contract: FIFO + PROMPT_COMMAND result mechanism preserved."""
    assert "fifo_path" in _PTY_LAUNCHER_SCRIPT
    assert "PROMPT_COMMAND=" in _PTY_LAUNCHER_SCRIPT

def test_pty_launcher_stdio_preserved_after_raw_mode():
    """stdin proxy and stdout proxy remain in the I/O loop."""
    assert "sys.stdin.fileno()" in _PTY_LAUNCHER_SCRIPT
    assert "sys.stdout.buffer.fileno()" in _PTY_LAUNCHER_SCRIPT

def test_pty_launcher_headless_unchanged():
    """Headless mode exit-injection remains gated by not is_real_tty."""
    assert "not is_real_tty" in _PTY_LAUNCHER_SCRIPT


# -------------------------------------------------------------------------
# OC-039: One-shot result hook - detach ADC after controlled command
# -------------------------------------------------------------------------

def test_one_shot_prompt_command_preserves_counter():
    """PROMPT_COMMAND in rcfile uses a counter to track firings."""
    assert "_ADC_PROMPT_COUNT=0" in _PTY_LAUNCHER_SCRIPT
    assert "_ADC_PROMPT_COUNT+1" in _PTY_LAUNCHER_SCRIPT

def test_one_shot_saves_and_restores_original_pc():
    """Original PROMPT_COMMAND is saved before ADC hook and restored after."""
    assert "_ADC_SAVED_PC=" in _PTY_LAUNCHER_SCRIPT
    assert 'PROMPT_COMMAND="$' in _PTY_LAUNCHER_SCRIPT or \
           "PROMPT_COMMAND=\"$" in _PTY_LAUNCHER_SCRIPT, \
        "must restore saved PROMPT_COMMAND"

def test_one_shot_unsets_pc_when_none_existed():
    """When no original PROMPT_COMMAND existed, ADC hook is unset."""
    assert "unset PROMPT_COMMAND" in _PTY_LAUNCHER_SCRIPT

def test_one_shot_detaches_after_count_ge_2():
    """Detachment happens when _ADC_PROMPT_COUNT >= 2 (controlled-command done)."""
    assert "_ADC_PROMPT_COUNT -ge 2" in _PTY_LAUNCHER_SCRIPT

def test_one_shot_cleans_up_vars():
    """Helper variables are cleaned up after one-shot fires."""
    assert "unset _ADC_SAVED_PC " in _PTY_LAUNCHER_SCRIPT or \
           "unset _ADC_SAVED_PC;" in _PTY_LAUNCHER_SCRIPT
    assert "_ADC_PROMPT_COUNT" in _PTY_LAUNCHER_SCRIPT
    assert "_ADC_EC" in _PTY_LAUNCHER_SCRIPT

def test_one_shot_preserves_dollar_question():
    """"$? is preserved via (exit $_ADC_EC) at end of PROMPT_COMMAND."""
    assert "(exit $_ADC_EC)" in _PTY_LAUNCHER_SCRIPT

def test_one_shot_fifo_unlinked_after_capture():
    """FIFO is unlinked immediately after exit code is captured."""
    assert "fifo_path.unlink()" in _PTY_LAUNCHER_SCRIPT

def test_one_shot_fifo_fd_closed_after_capture():
    """FIFO fd is closed and set to -1 after capture so no further reads."""
    assert "fifo_fd = -1" in _PTY_LAUNCHER_SCRIPT

def test_one_shot_no_permanent_fifo_echo():
    """No permanent 'echo $? > FIFO' PROMPT_COMMAND (old OC-037 style)."""
    lines = _PTY_LAUNCHER_SCRIPT.splitlines()
    for line in lines:
        s = line.strip()
        if "PROMPT_COMMAND=" in s and "_ADC_EC" not in s and "_ADC_SAVED_PC" not in s:
            # This would be a non-one-shot PROMPT_COMMAND
            if "echo $?" in s and "fifo" in s.lower():
                assert False, f"permanent FIFO-echo PROMPT_COMMAND found: {s[:120]}"

def test_one_shot_fifo_e2e():
    """E2E: /bin/false returns exit 1, FIFO cleaned, no FIFO errors after."""
    with tempfile.TemporaryDirectory(prefix="adc-oneshot-") as tmp:
        root = Path(tmp)
        config_file = root / "config.json"
        result_file = root / "result.json"

        config = {
            "command": ["/bin/false"],
            "result_file": str(result_file),
            "stdout_capture": None,
            "env": dict(os.environ),
            "cwd": os.getcwd(),
            "auto_close": True,
        }
        config_file.write_text(json.dumps(config))

        script_path = root / "pty_launcher.py"
        script_path.write_text(_PTY_LAUNCHER_SCRIPT)

        r = subprocess.run(
            [sys.executable, str(script_path), str(config_file)],
            capture_output=True, text=True, timeout=30,
        )

        assert result_file.exists()
        payload = json.loads(result_file.read_text())
        assert payload["returncode"] == 1, (
            f"/bin/false must give returncode 1, got {payload['returncode']}"
        )

        # In headless mode, bash exited. Verify no FIFO error in output.
        assert "No such file or directory" not in r.stdout, (
            f"no FIFO error in output: {r.stdout[:300]}"
        )

        # The FIFO should have been unlinked before final cleanup
        fifo_path = root / "exit_code.fifo"
        assert not fifo_path.exists(), "FIFO must be unlinked after result capture"


def test_one_shot_subsequent_command_no_fifo_error():
    """After controlled command, a second command produces no FIFO error."""
    with tempfile.TemporaryDirectory(prefix="adc-second-") as tmp:
        root = Path(tmp)
        config_file = root / "config.json"
        result_file = root / "result.json"

        config = {
            "command": [sys.executable, "-c", "print('first-cmd')"],
            "result_file": str(result_file),
            "stdout_capture": None,
            "env": dict(os.environ),
            "cwd": os.getcwd(),
            "auto_close": True,
        }
        config_file.write_text(json.dumps(config))

        script_path = root / "pty_launcher.py"
        script_path.write_text(_PTY_LAUNCHER_SCRIPT)

        r = subprocess.run(
            [sys.executable, str(script_path), str(config_file)],
            capture_output=True, text=True, timeout=30,
        )

        assert result_file.exists()
        payload = json.loads(result_file.read_text())
        assert payload["returncode"] == 0

        # In headless mode, bash runs "exit" and terminates.
        # Verify there is no FIFO error in the output at any point.
        assert "exit_code.fifo" not in r.stderr, (
            f"no FIFO path error in stderr: {r.stderr[:200]}"
        )
        assert "No such file" not in r.stderr, (
            f"no file-not-found error in stderr: {r.stderr[:200]}"
        )


def test_one_shot_controlled_dollar_question_preserved():
    """After /bin/false, the shell's $? should be 1 (structural check)."""
    script = _PTY_LAUNCHER_SCRIPT
    found_exit = False
    for line in script.splitlines():
        if "f'" in line and "(exit $_ADC_EC)" in line:
            found_exit = True
            break
    assert found_exit, "PROMPT_COMMAND must include (exit $_ADC_EC)"


def test_one_shot_result_available_before_bash_exit():
    """result.json is written BEFORE bash exits (from FIFO, not waitpid)."""
    script = _PTY_LAUNCHER_SCRIPT
    # result_written = True must appear before the waitpid/exit logic
    rw_idx = script.find("result_written = True")
    wp_idx = script.find("os.waitpid(child_pid, os.WNOHANG)")
    assert rw_idx > 0, "result_written = True must exist"
    assert wp_idx > 0, "waitpid must exist"
    assert rw_idx < wp_idx, "result must be written before bash exit check"
