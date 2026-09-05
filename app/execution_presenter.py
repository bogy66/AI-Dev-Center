"""Execution presenter abstraction for controlled software setup.

ADC remains the execution authority.  The presenter is only:
- live output presentation
- OS authentication surface when future privileged operations require it
- visible terminal as the actual execution surface (not a wrapper proxy)

This module provides:
  ExecutionPresenter    — abstract base
  HeadlessExecutionPresenter  — silent, no terminal
  TerminalExecutionPresenter  — launches a visible terminal
  TerminalCommandRunner  — structured argv in visible terminal with live output
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


_KNOWN_TERMINALS = ("gnome-terminal", "konsole", "xfce4-terminal", "xterm", "kitty", "alacritty", "terminator")

SUCCESS_DWELL_SECONDS = 5


class ExecutionPresenter(ABC):
    """Abstract presentation for controlled command execution."""

    @abstractmethod
    def present_execution(
        self,
        command: list[str],
        title: str,
        *,
        auto_close_on_success: bool = True,
        display_command: str | None = None,
        stdout_capture: str | None = None,
        stderr_capture: str | None = None,
        result_file: str | None = None,
    ) -> int | None:
        """Present execution of *command* with a visible title.

        *command* is the structured argv the terminal shell will execute.
        *display_command* is the human-readable form.
        *stdout_capture*/*stderr_capture* are paths for capture.
        *result_file* is the path for result evidence JSON.

        Returns the exit code when available, or None for headless.
        """
        ...

    @abstractmethod
    def present_output(self, text: str) -> None:
        ...

    def close(self) -> None:
        """Release any presenter resources."""


class HeadlessExecutionPresenter(ExecutionPresenter):
    """Silent presenter — no terminal output, no window."""

    def present_execution(
        self,
        command: list[str],
        title: str,
        *,
        auto_close_on_success: bool = True,
        display_command: str | None = None,
        stdout_capture: str | None = None,
        stderr_capture: str | None = None,
        result_file: str | None = None,
    ) -> int | None:
        return None

    def present_output(self, text: str) -> None:
        pass


class TerminalExecutionPresenter(ExecutionPresenter):
    """Launches a visible terminal window for controlled execution.

    The terminal detects an available terminal frontend from a bounded
    adapter without becoming GNOME-specific.

    The visible terminal IS the execution surface.  A genuine interactive
    shell (bash -i) runs in a real PTY with real TTY semantics.  The
    controlled command is fed to the PTY where tty echo makes it visible
    so that the user sees exactly the command that executes.

    No synthetic banners, echo/printf/print commands, or fake prompts
    are generated.
    """

    def __init__(self, terminal_command: str | None = None) -> None:
        self._terminal = terminal_command or self._detect_terminal()
        self._command = self._terminal

    @staticmethod
    def _detect_terminal() -> str | None:
        for name in _KNOWN_TERMINALS:
            found = shutil.which(name)
            if found:
                return found
        return None

    @property
    def is_available(self) -> bool:
        return self._terminal is not None

    def present_execution(
        self,
        command: list[str],
        title: str,
        *,
        auto_close_on_success: bool = True,
        display_command: str | None = None,
        stdout_capture: str | None = None,
        stderr_capture: str | None = None,
        result_file: str | None = None,
    ) -> int | None:
        if not self.is_available:
            return None

        terminal_args = self._build_terminal_args(
            command, title, auto_close_on_success,
            display_command=display_command,
            stdout_capture=stdout_capture,
            stderr_capture=stderr_capture,
            result_file=result_file,
        )
        try:
            subprocess.Popen(terminal_args, start_new_session=True)
            return 0
        except OSError:
            return None

    def present_output(self, text: str) -> None:
        if not self.is_available:
            return
        try:
            terminal = Path(self._terminal).name
        except Exception:
            terminal = self._terminal or "terminal"

        safe_text = text.replace("'", "'\\''")
        shell_cmd = f"echo '{safe_text}'; read -p 'Press Enter to close...'"

        if terminal in ("gnome-terminal",):
            subprocess.Popen(
                ["gnome-terminal", "--", "bash", "-c", shell_cmd],
                start_new_session=True,
            )
        elif terminal in ("konsole",):
            subprocess.Popen(
                ["konsole", "-e", "bash", "-c", shell_cmd],
                start_new_session=True,
            )
        elif terminal in ("xfce4-terminal",):
            subprocess.Popen(
                ["xfce4-terminal", "-e", f"bash -c '{shell_cmd}'"],
                start_new_session=True,
            )
        elif terminal in ("xterm",):
            subprocess.Popen(
                ["xterm", "-hold", "-e", shell_cmd],
                start_new_session=True,
            )

    def _build_terminal_args(
        self,
        command: list[str],
        title: str,
        auto_close_on_success: bool,
        *,
        display_command: str | None = None,
        stdout_capture: str | None = None,
        stderr_capture: str | None = None,
        result_file: str | None = None,
    ) -> list[str]:
        terminal = Path(self._terminal).name

        config = {}
        config["command"] = command
        config["result_file"] = result_file
        config["stdout_capture"] = stdout_capture
        config["env"] = dict(os.environ)
        config["cwd"] = os.getcwd()
        config["auto_close"] = auto_close_on_success

        if result_file:
            config_dir = Path(result_file).parent
        else:
            config_dir = Path(tempfile.mkdtemp(prefix="adc-term-config-"))
        config_path = config_dir / "config.json"
        config_path.write_text(json.dumps(config))

        script_path = config_dir / "pty_launcher.py"
        script_path.write_text(_PTY_LAUNCHER_SCRIPT)

        _py = sys.executable

        if terminal in ("gnome-terminal",):
            return ["gnome-terminal", "--", _py, str(script_path), str(config_path)]
        elif terminal in ("konsole",):
            return ["konsole", "-e", _py, str(script_path), str(config_path)]
        elif terminal in ("xfce4-terminal",):
            return ["xfce4-terminal", "-e", f"{_py} {script_path} {config_path}"]
        elif terminal in ("xterm",):
            return ["xterm", "-hold", "-e", _py, str(script_path), str(config_path)]
        elif terminal in ("kitty",):
            return ["kitty", _py, str(script_path), str(config_path)]
        elif terminal in ("alacritty",):
            return ["alacritty", "-e", _py, str(script_path), str(config_path)]
        elif terminal in ("terminator",):
            return ["terminator", "-e", f"{_py} {script_path} {config_path}"]
        else:
            return ["xterm", "-hold", "-e", _py, str(script_path), str(config_path)]


@dataclass(frozen=True)
class PresentedCommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class TerminalCommandRunner:
    """Execute one structured argv command in a visible terminal.

    The visible terminal IS the execution surface.  A genuine interactive
    shell (bash -i) runs in a real PTY.  The controlled command is fed to
    the PTY where tty echo makes it visible; the command the user sees
    executing is the command that actually executes.

    There is no intermediate wrapper script, no base64 indirection, and
    no hidden subprocess.  No synthetic banners, prompts, or echo
    commands are generated.
    """

    def __init__(
        self,
        presenter: TerminalExecutionPresenter | None = None,
        *,
        result_timeout_seconds: float = 600.0,
    ) -> None:
        self.presenter = presenter or TerminalExecutionPresenter()
        self.result_timeout_seconds = result_timeout_seconds

    @property
    def is_available(self) -> bool:
        return self.presenter.is_available

    def run(self, args: list[str]) -> PresentedCommandResult:
        if not self.is_available:
            raise RuntimeError("visible terminal execution is unavailable")

        with tempfile.TemporaryDirectory(prefix="adc-terminal-exec-") as tmp:
            root = Path(tmp)
            result_path = root / "result.json"
            stdout_path = root / "stdout.capture"

            self.presenter.present_execution(
                args,
                "AI-Dev-Center Controlled Setup",
                auto_close_on_success=True,
                stdout_capture=str(stdout_path),
                stderr_capture=None,
                result_file=str(result_path),
            )

            deadline = time.monotonic() + self.result_timeout_seconds
            while not result_path.exists():
                if time.monotonic() >= deadline:
                    return PresentedCommandResult(
                        returncode=1,
                        stderr="visible terminal execution timed out waiting for result evidence",
                    )
                time.sleep(0.5)

            try:
                payload = json.loads(result_path.read_text())
            except (OSError, ValueError, TypeError) as error:
                return PresentedCommandResult(
                    returncode=1,
                    stderr=f"invalid terminal execution result evidence: {type(error).__name__}",
                )

            return PresentedCommandResult(
                returncode=int(payload.get("returncode", 1)),
                stdout=str(payload.get("stdout", "")),
                stderr=str(payload.get("stderr", "")),
            )


def create_presenter(
    use_terminal: bool = False,
    terminal_command: str | None = None,
) -> ExecutionPresenter:
    """Factory for the appropriate presenter."""
    if not use_terminal:
        return HeadlessExecutionPresenter()
    presenter = TerminalExecutionPresenter(terminal_command)
    if not presenter.is_available:
        return HeadlessExecutionPresenter()
    return presenter


def _shell_quote(s: str) -> str:
    """Quote a string for safe use as a single shell argument.

    For strings without shell metacharacters, the string is returned
    as-is.  For strings that need quoting, single-quote wrapping is
    used with internal single quotes escaped via '\''.
    """
    if not s:
        return "''"
    if _SHELL_SAFE.match(s):
        return s
    return "'" + s.replace("'", "'\\''") + "'"


_SHELL_SAFE = __import__("re").compile(r"^[a-zA-Z0-9_%+,\-./:=@^]+$")


def _py_str(s: str) -> str:
    """Return a valid Python string literal for *s*."""
    return json.dumps(s)


# Legacy wrapper script kept for focused unit tests of the threaded-tee pattern.
# It is NOT used by the visible terminal execution path.
_LEGACY_WRAPPER_SCRIPT = r"""
import base64, json, os, subprocess, sys, threading
from pathlib import Path

def _reader(stream, write_func, accumulator):
    for line in iter(stream.readline, ''):
        write_func(line)
        accumulator.append(line)

argv = json.loads(base64.b64decode(sys.argv[1]).decode('utf-8'))
result_path = Path(sys.argv[2])

p = subprocess.Popen(
    argv, shell=False, text=True,
    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
)

stdout_lines = []
stderr_lines = []

stdout_thread = threading.Thread(
    target=_reader, args=(p.stdout, sys.stdout.write, stdout_lines), daemon=True,
)
stderr_thread = threading.Thread(
    target=_reader, args=(p.stderr, sys.stderr.write, stderr_lines), daemon=True,
)

stdout_thread.start()
stderr_thread.start()

p.wait()

stdout_thread.join()
stderr_thread.join()

stdout = ''.join(stdout_lines)
stderr = ''.join(stderr_lines)

tmp_result = result_path.with_suffix('.tmp')
tmp_result.write_text(json.dumps({
    'returncode': p.returncode, 'stdout': stdout, 'stderr': stderr,
}))
tmp_result.replace(result_path)

raise SystemExit(p.returncode)
"""


# -------------------------------------------------------------------------
# PTY Launcher Script
# -------------------------------------------------------------------------
#
# This script runs INSIDE the terminal emulator.  It:
# 1. Reads a JSON config file containing the command to execute.
# 2. Creates a FIFO and a bash rcfile that sets PROMPT_COMMAND to write
#    the last command's exit status ($?) to the FIIFO after each command.
# 3. Opens a real PTY with pty.fork().
# 4. In the child: ececs bash --rfile <adc_bashrc> -i (genuine interactive
#    shell with PROMPT_COMMAND hok).
# 5. In the parent: sets the outer terminal to raw mode so every byte
#    passes transparently (including paste escape sequences, control
#    characters, and arrow keys).  Sets the inner PTY window size from
#    the outer terminal dimensions.  Prpagates SIGWINCH.
# 6. Writes ONLY the exact controlled command to the PTY.
#    TY echo makes it visible.  N instrumentation is appended.
# 7. Proxies stdin from the terminal to the PTY (interactive input).
# 8. Proxies PTY output to the terminal (live output) and capture fle.
# 9. Detects command completion via the FIO (PROMPT_COMMAND writes $?).
#    On detection, rites result.json with exit code and captured output.
# 10. After command completes, the interactive bash stays alve.
#     The launcher keeps proxying I/O until bash exits or the termina closes.
# 11. On exit, restores the original outer terminal attributes.

_PTY_LAUNCHER_SCRIPT = r'''\
import fcntl
import json
import os
import pty
import select
import shlex
import signal
import struct
import sys
import tempfile
import termios
import time
from pathlib import Path


def _write_to_fd(fd, data):
    """Write all data to fd, handling partial writes."""
    while data:
        try:
            n = os.write(fd, data)
            data = data[n:]
        except BlockingIOError:
            time.sleep(0.01)
        except OSError:
            break


_orig_tty_attrs = None


def _setup_raw_tty(fd):
    """Save current terminal attributes and set fd to raw mode."""
    global _orig_tty_attrs
    try:
        _orig_tty_attrs = termios.tcgetattr(fd)
    except termios.error:
        return False

    # Build raw attributes from saved copy
    raw = termios.tcgetattr(fd)
    raw[0] = raw[0] & ~(
        termios.IGNBRK | termios.BRKINT | termios.PARMRK
        | termios.ISTRIP | termios.INLCR | termios.IGNCR
        | termios.ICRNL | termios.IXON
    )
    # Output flags: disable post-processing
    raw[1] = raw[1] & ~termios.OPOST
    # Local flags: no ECHO, no ECHONL, no ICANON, no ISIG, no IEXTEN
    raw[3] = raw[3] & ~(
        termios.ECHO | termios.ECHONL | termios.ICANON
        | termios.ISIG | termios.IEXTEN
    )
    # Control chars: set VMIN=1, VTIME=0 (read returns >= 1 byte immediately)
    raw[6][termios.VMIN] = 1
    raw[6][termios.VTIME] = 0

    try:
        termios.tcsetattr(fd, termios.TCSANOW, raw)
    except termios.error:
        return False
    return True


def _restore_tty(fd):
    """Restore saved terminal attributes."""
    global _orig_tty_attrs
    if _orig_tty_attrs is None:
        return
    try:
        termios.tcsetattr(fd, termios.TCSANOW, _orig_tty_attrs)
    except termios.error:
        pass


def _set_pty_size(master_fd, rows, cols):
    """Propagate terminal size to the PTY via TIOCSWINSZ."""
    try:
        winsz = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsz)
    except (OSError, struct.error):
        pass


def _get_terminal_size(fd):
    """Get (rows, cols) from a terminal fd."""
    try:
        buf = fcntl.ioctl(fd, termios.TIOCGWINSZ, struct.pack("HHHH", 0, 0, 0, 0))
        rows, cols, _, _ = struct.unpack("HHHH", buf)
        if rows == 0 and cols == 0:
            return (24, 80)
        return (rows, cols)
    except (OSError, struct.error):
        return (24, 80)


def main():
    config_path = sys.argv[1]
    config = json.loads(Path(config_path).read_text())
    command = config["command"]
    result_file = Path(config["result_file"]) if config.get("result_file") else None
    stdout_capture = Path(config["stdout_capture"]) if config.get("stdout_capture") else None
    env = config.get("env", {})
    cwd = config.get("cwd") or os.getcwd()
    auto_close = config.get("auto_close", True)

    work_dir = result_file.parent if result_file else Path(tempfile.mkdtemp(prefix="adc-pty-"))

    # ---- create FIFO for exit-code signalling ----
    fifo_path = work_dir / "exit_code.fifo"
    if result_file:
        try:
            os.mkfifo(str(fifo_path))
        except OSError:
            pass

    # ---- create bash rcfile with one-shot PROMPT_COMMAND hook ----
    rc_file = work_dir / "adc_bashrc"
    if result_file:
        rc_lines = []
        for src in ["/etc/bash.bashrc", os.path.expanduser("~/.bashrc")]:
            if os.path.isfile(src):
                rc_lines.append(f'[[ -r "{src}" ]] && . "{src}"')
        # Save any existing PROMPT_COMMAND so it can be restored later.
        rc_lines.append('_ADC_SAVED_PC="${PROMPT_COMMAND:-}"')
        # Counter tracks how many prompts have fired since startup:
        #   0 on startup, 1 after first prompt, 2 after controlled command.
        rc_lines.append('_ADC_PROMPT_COUNT=0')
        # One-shot PROMPT_COMMAND:
        #   - Save $? immediately (the previous command's exit status).
        #   - Write it to the FIFO so the launcher can read it.
        #   - Increment the counter.
        #   - After the SECOND fire (controlled-command completion), restore
        #     the original PROMPT_COMMAND (or unset if none existed) and
        #     clean up the helper variables.
        #   - The final "(exit $_ADC_EC)" preserves $? so the next prompt
        #     shows the correct exit status of the previous command.
        rc_lines.append(
            f'PROMPT_COMMAND=\'_ADC_EC=$?;'
            f'echo $_ADC_EC > "{fifo_path}";'
            f'_ADC_PROMPT_COUNT=$((_ADC_PROMPT_COUNT+1));'
            f'[ $_ADC_PROMPT_COUNT -ge 2 ] && {{'
            f'  [ -n "${{_ADC_SAVED_PC:-}}" ] &&'
            f'    PROMPT_COMMAND="${{_ADC_SAVED_PC}}"'
            f'    || unset PROMPT_COMMAND;'
            f'  unset _ADC_SAVED_PC _ADC_PROMPT_COUNT _ADC_EC;'
            f'}};'
            f'(exit $_ADC_EC)\''
        )
        rc_file.write_text("\n".join(rc_lines) + "\n")

    child_pid = None

    child_pid, master_fd = pty.fork()
    if child_pid == 0:
        # -------- child: run genuine interactive bash --------
        try:
            os.setsid()
        except OSError:
            pass
        try:
            os.chdir(cwd)
        except OSError:
            pass
        for k, v in env.items():
            if k in ("TERM",) and k in os.environ:
                pass
            else:
                os.environ[k] = v
        if rc_file.exists():
            os.execlp("bash", "bash", "--rcfile", str(rc_file), "-i")
        else:
            os.execlp("bash", "bash", "-i")
        os._exit(127)

    # -------- parent: manage PTY and proxy I/O --------
    fl = fcntl.fcntl(master_fd, fcntl.F_GETFL)
    fcntl.fcntl(master_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

    try:
        fl_in = fcntl.fcntl(sys.stdin.fileno(), fcntl.F_GETFL)
        fcntl.fcntl(sys.stdin.fileno(), fcntl.F_SETFL, fl_in | os.O_NONBLOCK)
    except OSError:
        pass

    is_real_tty = os.isatty(sys.stdin.fileno())

    # ---- outer terminal raw mode (transparent byte forwarding) ----
    if is_real_tty:
        _setup_raw_tty(sys.stdin.fileno())
        rows, cols = _get_terminal_size(sys.stdin.fileno())
        _set_pty_size(master_fd, rows, cols)
        # SIGWINCH handler for resize propagation
        def _handle_sigwinch(signum, frame):
            r, c = _get_terminal_size(sys.stdin.fileno())
            _set_pty_size(master_fd, r, c)
        signal.signal(signal.SIGWINCH, _handle_sigwinch)
        # Ignore terminal-generated signals in the launcher;
        # they pass as raw bytes to the PTY where bash handles them.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGQUIT, signal.SIG_IGN)
        signal.signal(signal.SIGTSTP, signal.SIG_IGN)

    # Open FIFO for non-blocking reading
    fifo_fd = -1
    if fifo_path.exists():
        try:
            fifo_fd = os.open(str(fifo_path), os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            pass

    # Give bash time to initialize, run rcfile, and print its first prompt.
    time.sleep(0.3)

    # Read and discard the initial FIFO write (shell startup exit code)
    if fifo_fd >= 0:
        try:
            _ = os.read(fifo_fd, 256)
        except (BlockingIOError, OSError):
            pass

    # Build command line with safe POSIX shell quoting - EXACT command only.
    cmd_str = " ".join(shlex.quote(str(a)) for a in command)

    # Write command to PTY - tty echo makes it visible to the user.
    # NO instrumentation is appended.  NO "exit" is sent.
    _write_to_fd(master_fd, (cmd_str + "\n").encode())

    # ---------- Proxy I/O: terminal <-> PTY ----------
    stdout_buf = bytearray()
    capture_fh = None
    if stdout_capture:
        try:
            capture_fh = open(str(stdout_capture), "wb")
        except OSError:
            pass

    exit_code = 1
    result_written = False
    done = False
    stdin_eof = False

    try:
        while not done:
            fds = [sys.stdin.buffer, master_fd]
            if fifo_fd >= 0:
                fds.append(fifo_fd)
            try:
                rlist, _, _ = select.select(fds, [], [], 0.3)
            except (select.error, ValueError):
                break

            # Terminal stdin -> PTY (interactive input)
            if not stdin_eof and sys.stdin.buffer in rlist:
                try:
                    data = os.read(sys.stdin.fileno(), 4096)
                    if not data:
                        stdin_eof = True
                    else:
                        _write_to_fd(master_fd, data)
                except (BlockingIOError, OSError):
                    pass

            # PTY output -> terminal stdout + capture
            if master_fd in rlist:
                try:
                    data = os.read(master_fd, 4096)
                    if not data:
                        break
                    os.write(sys.stdout.buffer.fileno(), data)
                    sys.stdout.buffer.flush()
                    stdout_buf.extend(data)
                    if capture_fh:
                        capture_fh.write(data)
                        capture_fh.flush()
                except (BlockingIOError, OSError):
                    pass

            # FIFO signal: PROMPT_COMMAND wrote exit code after command finished
            if fifo_fd >= 0 and fifo_fd in rlist and not result_written:
                try:
                    raw = os.read(fifo_fd, 256)
                    if raw:
                        try:
                            exit_code = int(raw.strip())
                        except ValueError:
                            exit_code = 1
                        # Write result evidence
                        if result_file:
                            combined_stdout = bytes(stdout_buf).decode("utf-8", errors="replace")
                            result = {
                                "returncode": exit_code,
                                "stdout": combined_stdout,
                                "stderr": "",
                            }
                            tmp = result_file.with_suffix(result_file.suffix + ".tmp")
                            tmp.write_text(json.dumps(result))
                            tmp.replace(result_file)
                        result_written = True
                        # Close and unlink FIFO so no further writes are possible.
                        # The one-shot PROMPT_COMMAND has already restored the
                        # user's original PROMPT_COMMAND by this point, so the
                        # FIFO will not be written to again.
                        try:
                            os.close(fifo_fd)
                        except OSError:
                            pass
                        fifo_fd = -1
                        try:
                            fifo_path.unlink()
                        except OSError:
                            pass
                        if not is_real_tty:
                            _write_to_fd(master_fd, b"exit\n")
                except (BlockingIOError, OSError, ValueError):
                    pass

            # Check if child (bash) has exited
            try:
                wpid, status = os.waitpid(child_pid, os.WNOHANG)
                if wpid == child_pid:
                    if os.WIFEXITED(status):
                        exit_code = os.WEXITSTATUS(status)
                    elif os.WIFSIGNALED(status):
                        exit_code = 128 + os.WTERMSIG(status)
                    done = True
            except ChildProcessError:
                done = True
    finally:
        # Restore original terminal attributes
        if is_real_tty:
            _restore_tty(sys.stdin.fileno())

    # Drain remaining PTY output
    while True:
        try:
            rlist, _, _ = select.select([master_fd], [], [], 0.1)
            if master_fd not in rlist:
                break
            data = os.read(master_fd, 4096)
            if not data:
                break
            os.write(sys.stdout.buffer.fileno(), data)
            sys.stdout.buffer.flush()
            stdout_buf.extend(data)
            if capture_fh:
                capture_fh.write(data)
        except (BlockingIOError, OSError):
            break

    if capture_fh:
        capture_fh.close()

    if fifo_fd >= 0:
        os.close(fifo_fd)

    os.close(master_fd)

    try:
        os.waitpid(child_pid, 0)
    except OSError:
        pass

    if result_file and not result_written:
        combined_stdout = bytes(stdout_buf).decode("utf-8", errors="replace")
        result = {
            "returncode": exit_code,
            "stdout": combined_stdout,
            "stderr": "",
        }
        tmp = result_file.with_suffix(result_file.suffix + ".tmp")
        tmp.write_text(json.dumps(result))
        tmp.replace(result_file)

    # Clean up config dir
    config_dir = Path(config_path).parent
    try:
        for p in [config_dir / "config.json",
                   config_dir / "pty_launcher.py",
                   config_dir / "adc_bashrc",
                   config_dir / "exit_code.fifo"]:
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass
        config_dir.rmdir()
    except OSError:
        pass

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
'''