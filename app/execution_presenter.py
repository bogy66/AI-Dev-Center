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

import hmac
import json
import os
import secrets
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
    """The controlled command's own result.  ``completed`` is True only
    when the launcher observed the command's completion record; otherwise
    ``returncode`` is None -- no exit status is ever fabricated from the
    launcher, the shell, or a timeout."""

    returncode: int | None
    stdout: str = ""
    stderr: str = ""
    completed: bool = True


# Files shared with the PTY launcher next to the result file (see
# _PTY_LAUNCHER_SCRIPT, which defines the same names).
_RESULT_KEY_FILE = "result.key"
_CANCEL_REQUEST_FILE = "cancel.request"
# How long a cancelled run may take to confirm that it ended; covers the
# launcher's own terminate-then-kill grace.
_CANCEL_CONFIRM_SECONDS = 10.0


def _result_authentication(key: bytes, result: dict) -> str:
    """HMAC over the canonical result, excluding the authentication field."""
    body = {k: v for k, v in result.items() if k != "authentication"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hmac.new(key, canonical.encode("utf-8"), "sha256").hexdigest()


def _read_authentic_result(result_path: Path, key: bytes) -> dict | None:
    """The published result when it is authentic launcher evidence, else
    None.  Anyone able to write the result path (the controlled command runs
    as the same user) can place a file there; only the launcher holds the
    key."""
    try:
        payload = json.loads(result_path.read_text())
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    authentication = payload.get("authentication")
    if not isinstance(authentication, str) or not hmac.compare_digest(
        authentication, _result_authentication(key, payload),
    ):
        return None
    return payload


class TerminalCommandRunner:
    """Execute one structured argv command in a visible terminal.

    The visible terminal IS the execution surface.  A genuine interactive
    shell (bash -i) runs in a real PTY.  The controlled command is fed to
    the PTY where tty echo makes it visible; the command the user sees
    executing is the command that actually executes.

    There is no intermediate wrapper script, no base64 indirection, and
    no hidden subprocess.  No synthetic banners, prompts, or echo
    commands are generated.

    Only result evidence authenticated with this run's key counts.  A run
    whose result is no longer awaited (timeout, unauthentic evidence) is
    cancelled, so the command never keeps running unobserved.
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
            # Per-run key authenticating the launcher's result; the launcher
            # removes the key file before the command can start.
            key = secrets.token_bytes(32)
            key_fd = os.open(root / _RESULT_KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(key_fd, "w") as key_file:
                key_file.write(key.hex())

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
                        returncode=None, completed=False,
                        stderr="visible terminal execution timed out waiting for result evidence"
                               + self._cancel(root, key),
                    )
                time.sleep(min(0.5, max(0.01, deadline - time.monotonic())))

            payload = _read_authentic_result(result_path, key)
            if payload is None:
                # Not the launcher's evidence: the run is no longer observable.
                return PresentedCommandResult(
                    returncode=None, completed=False,
                    stderr="invalid terminal execution result evidence: unauthenticated"
                           + self._cancel(root, key),
                )

            # Only the final command's completion record is authoritative;
            # a launcher/shell lifecycle ending without it fails closed.
            returncode = payload.get("returncode") if isinstance(payload, dict) else None
            if (
                not isinstance(payload, dict)
                or payload.get("completed") is not True
                or not isinstance(returncode, int)
                or isinstance(returncode, bool)
            ):
                failure = payload.get("failure") if isinstance(payload, dict) else None
                return PresentedCommandResult(
                    returncode=None, completed=False,
                    stdout=str(payload.get("stdout", "")) if isinstance(payload, dict) else "",
                    stderr=(
                        "visible terminal execution ended without command completion "
                        f"evidence ({failure or 'invalid result evidence'})"
                    ),
                )
            return PresentedCommandResult(
                returncode=returncode,
                stdout=str(payload.get("stdout", "")),
                stderr=str(payload.get("stderr", "")),
            )

    @staticmethod
    def _cancel(root: Path, key: bytes) -> str:
        """Ask the launcher to end a run whose result is no longer awaited
        and wait (bounded) for its authentic confirmation, so no command
        keeps running unobserved.  Returns a diagnostic suffix."""
        try:
            (root / _CANCEL_REQUEST_FILE).write_text("cancel\n")
        except OSError:
            return " (cancellation could not be requested)"
        result_path = root / "result.json"
        deadline = time.monotonic() + _CANCEL_CONFIRM_SECONDS
        while time.monotonic() < deadline:
            payload = _read_authentic_result(result_path, key) if result_path.exists() else None
            if payload is not None:
                return f" (run ended: {payload.get('failure') or 'completed'})"
            time.sleep(0.05)
        return " (run end not confirmed)"


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
# 1. Reads a JSON config file containing the command to execute and turns
#    the argv into one exact line of shell input.  Arguments outside
#    printable ASCII are written as ANSI-C quoting ($'...'), so the line
#    editor and tty line discipline never interpret argument bytes; a bare
#    command word is quoted so aliases cannot replace it.  An argv that
#    cannot be typed faithfully (empty, NUL, unencodable) is never run.
# 2. Creates a FIFO and a bash rcfile whose one-shot PROMPT_COMMAND writes
#    phase records "ADC-PTY-V2 <nonce> <PHASE> ..." to the FIFO.  The
#    per-run nonce exists only in the launcher and the shell's memory (the
#    rcfile is deleted at STARTUP), so no other writer can produce a record
#    of this run.  Phases (CLAUDE-ADC-RSE033-AUTONOMOUS-PTY-CODE-PILOT-001;
#    discriminated by record type, never by timing):
#      STARTUP <status> <editing> <kind> <context>  first prompt: the shell
#          is ready; the command word resolves to <kind> (only an
#          executable file is accepted); <context> says whether cwd,
#          exported environment and umask are still as prepared after the
#          user's startup files (they are restored first).
#      COMPLETE <$?>    second prompt: the controlled command returned.
#      SUSPENDED <$?>   second prompt, but the command was only stopped.
#      HOOK_FAILED 0    the startup files prevented the hook.
# 3. Opens a real PTY with pty.fork().
# 4. In the child: execs bash --rcfile <adc_bashrc> -i (genuine interactive
#    shell with PROMPT_COMMAND hook).
# 5. In the parent: sets the outer terminal to raw mode so every byte
#    passes transparently (including paste escape sequences, control
#    characters, and arrow keys).  Sets the inner PTY window size from
#    the outer terminal dimensions.  Propagates SIGWINCH.
# 6. After the STARTUP record, and once the line editor has taken the PTY
#    out of canonical mode (observed on the slave's termios), writes ONLY
#    the exact controlled command to the PTY.  TTY echo makes it visible.
#    No instrumentation is appended.  Without a line editor the line is
#    typed at once, unless it exceeds the canonical input limit.
# 7. Proxies stdin from the terminal to the PTY (interactive input), only
#    after the command line was written.
# 8. Proxies PTY output to the terminal (live output) and capture file.
# 9. Detects command completion only via the COMPLETE record.  It then
#    drains the PTY output the command wrote before its completion and
#    writes result.json ("completed": true) with the final command's exit
#    status and output.  Every other outcome is fail-closed ("completed":
#    false, no returncode, a "failure" reason): no completion, a rejected
#    start, a suspended command, or any unauthentic, malformed or
#    out-of-order record.  A running command is hung up rather than typed
#    into; the shell's own exit status never becomes the command's result.
#    (CLAUDE-ADC-AUTONOMOUS-PTY-CODE-CORRECTION-002) The command runs only in
#    the configured cwd and with exactly the configured environment.  No
#    shell code of the user's startup files (PS0, prompt expansion, traps,
#    further PROMPT_COMMAND elements, key bindings reachable by the typed
#    line) runs between STARTUP and the final record.  result.json carries
#    an HMAC with the consumer's key (result.key, removed before the shell
#    starts); a cancel.request from the consumer ends the command's process
#    group and the run fail-closed ("cancelled").
# 10. After command completes, the interactive bash stays alive.
#     The launcher keeps proxying I/O until bash exits or the terminal closes.
# 11. On exit, restores the original outer terminal attributes.

_PTY_LAUNCHER_SCRIPT = r'''\
import fcntl
import hmac
import json
import os
import pty
import secrets
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


PROTOCOL = "ADC-PTY-V2"
PHASE_HOOK_FAILED = "HOOK_FAILED"
PHASE_STARTUP = "STARTUP"
PHASE_COMPLETE = "COMPLETE"
PHASE_SUSPENDED = "SUSPENDED"

# Field shapes after "<protocol> <nonce> <phase>".  Anything else is not a
# record of this run.
_RECORD_FIELDS = {
    PHASE_HOOK_FAILED: ("status",),
    PHASE_STARTUP: ("status", "editing", "kind", "context"),
    PHASE_COMPLETE: ("status",),
    PHASE_SUSPENDED: ("status",),
}
_EDITING_VALUES = ("0", "1")
_KIND_VALUES = ("file", "function", "builtin", "none")
_CONTEXT_VALUES = ("ok", "changed")
_MAX_RECORD_BYTES = 512

# Longest line a canonical-mode tty accepts (N_TTY_BUF_SIZE - 1, newline
# included); longer input is silently truncated by the line discipline.
_CANONICAL_LINE_LIMIT = 4095


def _parse_record(line, nonce):
    """Return (phase, fields) for one exact record of this run, else None.

    A record is authentic only with this run's nonce, which exists solely
    in the launcher and in the interactive shell's memory (never in its
    environment or in a file the controlled command can read)."""
    parts = line.split(" ")
    if len(parts) < 3 or parts[0] != PROTOCOL:
        return None
    if not hmac.compare_digest(parts[1].encode(), nonce.encode()):
        return None
    phase, values = parts[2], parts[3:]
    names = _RECORD_FIELDS.get(phase)
    if names is None or len(values) != len(names):
        return None
    fields = dict(zip(names, values))
    try:
        status = int(fields["status"])
    except ValueError:
        return None
    if not 0 <= status <= 255 or str(status) != fields["status"]:
        return None
    fields["status"] = status
    if phase == PHASE_STARTUP and (
        fields["editing"] not in _EDITING_VALUES
        or fields["kind"] not in _KIND_VALUES
        or fields["context"] not in _CONTEXT_VALUES
    ):
        return None
    return phase, fields


_ANSI_C_LITERAL = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789%+,-./:=@_ "
)


def _bash_word(arg):
    """Exact bash word for *arg* that consists of printable ASCII only.

    The word is typed into the shell's line editor, which interprets
    control characters (TAB completes, C-u kills the line, ...) and, in
    canonical mode, the tty line discipline raises signals for them.  Any
    argument outside printable ASCII is therefore written as ANSI-C
    quoting ($'...') with byte escapes, which bash decodes back to the
    exact argument bytes."""
    data = arg.encode("utf-8", "surrogateescape")
    if all(0x20 <= b < 0x7F for b in data):
        return shlex.quote(arg)
    escaped = "".join(
        chr(b) if chr(b) in _ANSI_C_LITERAL else "\\x%02x" % b for b in data
    )
    return "$'" + escaped + "'"


def _command_words(command):
    """The exact controlled command as shell words, or None when the argv
    cannot be run faithfully (empty, non-string, NUL, unencodable).  A
    bare command word is always quoted so the user's aliases (and reserved
    words) can never replace the executable."""
    if not isinstance(command, list) or not command:
        return None
    words = []
    for arg in command:
        if not isinstance(arg, str) or "\0" in arg:
            return None
        try:
            words.append(_bash_word(arg))
        except UnicodeEncodeError:
            return None
    if words[0] == command[0] and "/" not in command[0]:
        words[0] = "'" + command[0] + "'"
    return words


# Files the result consumer places next to the result file.  The key file
# is consumed before the shell starts, so the controlled command never sees
# the key; the cancel request asks the launcher to end the run.
RESULT_KEY_FILE = "result.key"
CANCEL_REQUEST_FILE = "cancel.request"
# Bounded grace between asking a cancelled command to terminate and
# forcing it.
_CANCEL_GRACE_SECONDS = 3.0


def _result_authentication(key, result):
    """HMAC over the canonical result, excluding the authentication field."""
    body = {k: v for k, v in result.items() if k != "authentication"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hmac.new(key, canonical.encode("utf-8"), "sha256").hexdigest()


def _publish_result(result_file, result, key=None):
    """Atomically publish the one, final result evidence file, authenticated
    with the consumer's key when one was supplied."""
    if key is not None:
        result = dict(result, authentication=_result_authentication(key, result))
    tmp = result_file.with_suffix(result_file.suffix + ".tmp")
    tmp.write_text(json.dumps(result))
    tmp.replace(result_file)


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

    # The consumer's result key is read and removed before anything starts:
    # only this process holds it, so no other writer of the result path (the
    # controlled command included) can publish authentic result evidence.
    result_key = None
    cancel_path = None
    if result_file:
        key_path = work_dir / RESULT_KEY_FILE
        try:
            result_key = bytes.fromhex(key_path.read_text().strip()) or None
        except (OSError, ValueError):
            result_key = None
        try:
            key_path.unlink()
        except OSError:
            pass
        cancel_path = work_dir / CANCEL_REQUEST_FILE

    # The exact command line is fixed before anything starts.  An argv that
    # cannot be typed faithfully is never run.
    words = _command_words(command)
    cmd_str = " ".join(words) if words is not None else None

    # The authorized working directory is a precondition: a command whose
    # cwd cannot be entered is never run anywhere else.
    cwd_ok = os.path.isdir(cwd)

    # The controlled environment is exactly the configured one.  The
    # launcher's own (terminal/desktop) environment only provides TERM to the
    # interactive shell -- as an unexported variable, never to the command.
    env = {str(k): str(v) for k, v in env.items()}
    shell_term = os.environ.get("TERM") if "TERM" not in env else None

    # Per-run secret authenticating every phase record: a record without it
    # (a stale run, the controlled command, the user's startup files) is
    # never a phase of this run.
    nonce = secrets.token_hex(16)

    # ---- create FIFO for phase records ----
    fifo_path = work_dir / "exit_code.fifo"
    fifo_fd = -1
    # The phase protocol is required for every run, with or without a
    # result file.
    if words is not None and cwd_ok:
        try:
            os.mkfifo(str(fifo_path))
            # O_RDWR keeps a writer open on our side: the shell's record
            # writes never block and the FIFO never reports EOF between
            # records.  The fd is not inherited by the shell.
            fifo_fd = os.open(str(fifo_path), os.O_RDWR | os.O_NONBLOCK)
        except OSError:
            fifo_fd = -1

    # ---- create bash rcfile with one-shot PROMPT_COMMAND hook ----
    rc_file = work_dir / "adc_bashrc"
    if fifo_fd >= 0:
        q_fifo = shlex.quote(str(fifo_path))
        rc_lines = [
            # The terminal type for the shell's line editor only (unexported).
            *(['TERM=' + shlex.quote(shell_term)] if shell_term else []),
            # Command context (cwd, exported environment and functions,
            # umask) as the launcher prepared it, before the user's startup
            # files run.  Those files may shape the interactive session but
            # never the controlled command's context.
            '_adc_ctxsig() { local _n IFS=$\' \\t\\n\'; builtin printf "cwd=%q\\n" "$PWD"; builtin umask;'
            ' for _n in $(builtin compgen -e); do [[ $_n == _ || $_n == OLDPWD ]] ||'
            ' builtin printf "%s=%q\\n" "$_n" "${!_n}"; done; builtin declare -Fx; }',
            '_ADC_CTX0=$(_adc_ctxsig)',
            '_ADC_ENV0=$(builtin export -p)',
            '_ADC_FX0=$(builtin declare -Fx)',
            '_ADC_CWD0=$PWD',
            '_ADC_UMASK0=$(builtin umask)',
        ]
        for src in ["/etc/bash.bashrc", os.path.expanduser("~/.bashrc")]:
            if os.path.isfile(src):
                rc_lines.append(f'[[ -r "{src}" ]] && . "{src}"')
        rc_lines += [
            # xtrace would print the record writes (and the nonce) to the
            # terminal; it is restored after the controlled command.
            '_ADC_XTRACE=0; [[ $- == *x* ]] && _ADC_XTRACE=1; builtin set +x',
            '_ADC_IFS0=$IFS; IFS=$\' \\t\\n\'',
            '[[ $PWD == "$_ADC_CWD0" ]] || builtin cd -- "$_ADC_CWD0"',
            'for _adc_n in $(builtin compgen -e); do [[ $_adc_n == _ ]] || builtin export -n -- "$_adc_n"; done 2>/dev/null',
            'while builtin read -r _ _ _adc_n; do [[ -n $_adc_n ]] && builtin export -nf -- "$_adc_n"; done <<< "$(builtin declare -Fx)"',
            'builtin eval "$_ADC_ENV0" 2>/dev/null; builtin eval "$_ADC_FX0" 2>/dev/null',
            'builtin umask "$_ADC_UMASK0"; builtin hash -r',
            '_ADC_CTX=ok; [[ "$(_adc_ctxsig)" == "$_ADC_CTX0" ]] || _ADC_CTX=changed',
            # Between STARTUP and the command's completion no shell code of the
            # user's startup files may run (it could otherwise report records):
            # PS0, prompt expansion, traps and PROMPT_COMMAND elements are
            # saved, disabled, and restored after the final record.
            '_ADC_HOOKS=$(builtin declare -p PS0 PROMPT_COMMAND 2>/dev/null; builtin trap -p;'
            ' builtin shopt -p promptvars extdebug; [[ -o functrace ]] && builtin echo "builtin set -o functrace";'
            ' [[ -o errtrace ]] && builtin echo "builtin set -o errtrace")',
            'builtin unset PS0 2>/dev/null',
            'while IFS= builtin read -r _adc_n; do [[ -n $_adc_n ]] && builtin trap - "${_adc_n##* }"; done'
            ' <<< "$(builtin trap -p)" 2>/dev/null',
            'builtin set +o functrace +o errtrace; builtin shopt -u promptvars extdebug',
            'IFS=$_ADC_IFS0; unset _adc_n _ADC_IFS0 _ADC_CTX0 _ADC_ENV0 _ADC_FX0 _ADC_CWD0 _ADC_UMASK0; unset -f _adc_ctxsig',
            # Record writer: the nonce lives only in this function body.
            f'_adc_record() {{ local IFS=" "; builtin printf "%s %s %s\\n" {PROTOCOL} {nonce} "$*" > {q_fifo}; }}',
            # STARTUP reports what the command word resolves to (aliases and
            # reserved words cannot apply to the quoted word), whether a line
            # editor reads the input, and whether the context is intact.
            f'_adc_startup() {{ local _k _kind=none _ed=0 IFS=$\' \\t\\n\';'
            f' for _k in $(builtin type -at -- {words[0]} 2>/dev/null); do'
            f' [[ $_k == alias || $_k == keyword ]] || {{ _kind=$_k; break; }}; done;'
            f' [[ -o emacs || -o vi ]] && _ed=1; local _ctx=$_ADC_CTX _b;'
            # A key binding reachable by the typed line (printable characters,
            # newline) that runs shell code or inserts other text would change
            # what runs; the typed line contains no escape/control keys.
            f' if [[ $_ed == 1 ]]; then while IFS= builtin read -r _b; do _b=${{_b#\\\"}};'
            f' [[ -z $_b || $_b == \'\\e\'* || $_b == \'\\M-\'* ||'
            f' ( $_b == \'\\C-\'* && $_b != \'\\C-\'[jmJM]* ) ]] || _ctx=changed;'
            f' done <<< "$(builtin bind -X 2>/dev/null; builtin bind -s 2>/dev/null)"; fi;'
            f' _adc_record {PHASE_STARTUP} "$1" "$_ed" "$_kind" "$_ctx"; }}',
            # Save any existing PROMPT_COMMAND so it can be restored later
            # (an array's further elements are restored from _ADC_HOOKS).
            '_ADC_SAVED_PC="${PROMPT_COMMAND:-}"',
            'builtin unset PROMPT_COMMAND 2>/dev/null',
            # Counter tracks how many prompts have fired since startup:
            #   0 on startup, 1 after first prompt, 2 after controlled command.
            '_ADC_PROMPT_COUNT=0',
        ]
        # One-shot PROMPT_COMMAND:
        #   - Save $? immediately (the previous command's exit status).
        #   - First prompt: STARTUP record (shell ready, command not typed).
        #   - Second prompt (the controlled command has returned): COMPLETE
        #     with its $? -- or SUSPENDED when it was only stopped, which is
        #     not a completion.  Then restore the original PROMPT_COMMAND
        #     (or unset if none existed) and clean up the helpers.
        #   - The final "(exit $_ADC_EC)" preserves $? so the next prompt
        #     shows the correct exit status of the previous command.
        rc_lines.append(
            f'PROMPT_COMMAND=\'_ADC_EC=$?;'
            f'_ADC_PROMPT_COUNT=$((_ADC_PROMPT_COUNT+1));'
            f'if [ $_ADC_PROMPT_COUNT -ge 2 ]; then'
            f'  if [[ -n "$(builtin jobs -ps)" ]]; then _adc_record {PHASE_SUSPENDED} $_ADC_EC;'
            f'  else _adc_record {PHASE_COMPLETE} $_ADC_EC; fi;'
            f'  [ -n "${{_ADC_SAVED_PC:-}}" ] &&'
            f'    PROMPT_COMMAND="${{_ADC_SAVED_PC}}"'
            f'    || unset PROMPT_COMMAND;'
            f'  unset -f _adc_record _adc_startup;'
            f'  builtin eval "$_ADC_HOOKS" 2>/dev/null; unset _ADC_HOOKS;'
            f'  _ADC_PROMPT_COUNT=$_ADC_XTRACE;'
            f'  unset _ADC_SAVED_PC _ADC_XTRACE _ADC_CTX;'
            f'  [ "$_ADC_PROMPT_COUNT" = 1 ] && {{ unset _ADC_PROMPT_COUNT; builtin set -x; }} || unset _ADC_PROMPT_COUNT;'
            f'else _adc_startup $_ADC_EC; fi;'
            f'(exit $_ADC_EC)\''
        )
        # A hook the user's startup files prevent (e.g. a readonly
        # PROMPT_COMMAND) could never report completion.
        rc_lines.append(
            '[[ "${PROMPT_COMMAND:-}" == _ADC_EC=* && ${#PROMPT_COMMAND[@]} == 1 && -z ${PS0+x}'
            ' && -z "$(builtin trap -p)" ]] || _adc_record ' + PHASE_HOOK_FAILED + ' 0'
        )
        rc_file.write_text("\n".join(rc_lines) + "\n")

    child_pid = None

    # The child reports its terminal (the PTY slave) so the launcher can
    # observe the line discipline the command line will be typed into.
    tty_name_r, tty_name_w = os.pipe()
    child_pid, master_fd = pty.fork()
    if child_pid == 0:
        # -------- child: run genuine interactive bash --------
        try:
            os.close(tty_name_r)
            os.write(tty_name_w, os.ttyname(0).encode())
        except OSError:
            pass
        try:
            os.setsid()
        except OSError:
            pass
        try:
            os.chdir(cwd)
        except OSError:
            # Never run anywhere but the authorized working directory.
            os._exit(126)
        os.environ.clear()
        os.environ.update(env)
        try:
            if rc_file.exists():
                os.execlp("bash", "bash", "--rcfile", str(rc_file), "-i")
            else:
                os.execlp("bash", "bash", "-i")
        except OSError:
            pass
        os._exit(127)

    # -------- parent: manage PTY and proxy I/O --------
    os.close(tty_name_w)
    slave_name = b""
    while True:
        try:
            chunk = os.read(tty_name_r, 256)
        except InterruptedError:
            continue
        except OSError:
            break
        if not chunk:
            break
        slave_name += chunk
    os.close(tty_name_r)

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

    # ---------- Proxy I/O: terminal <-> PTY ----------
    stdout_buf = bytearray()
    capture_fh = None
    if stdout_capture:
        try:
            capture_fh = open(str(stdout_capture), "wb")
        except OSError:
            pass

    def _take_pty_output(data):
        os.write(sys.stdout.buffer.fileno(), data)
        sys.stdout.buffer.flush()
        stdout_buf.extend(data)
        if capture_fh:
            capture_fh.write(data)
            capture_fh.flush()

    def _drain_pty_output():
        """Read everything the PTY already holds.  Called after a COMPLETE
        record: the command wrote its output to the PTY before the shell
        could run PROMPT_COMMAND, so it is all readable now."""
        while True:
            try:
                ready, _, _ = select.select([master_fd], [], [], 0)
                if master_fd not in ready:
                    return
                data = os.read(master_fd, 65536)
            except (BlockingIOError, InterruptedError):
                continue
            except OSError:
                return
            if not data:
                return
            _take_pty_output(data)

    # Phases are discriminated only by authentic FIFO records:
    #   starting         until STARTUP (nothing is typed before it)
    #   awaiting_editor  STARTUP seen; the line editor has not yet taken the
    #                    terminal out of canonical mode
    #   running          the command line was typed, until COMPLETE
    #   completed        the command's own status was published
    # and the fail-closed end states rejected / suspended /
    # protocol_violation / no_protocol.  Without a FIFO (or without a
    # runnable argv) no completion can ever be observed, so the command is
    # never started.
    phase = "starting" if fifo_fd >= 0 else "no_protocol"
    failure = None
    if words is None:
        failure = "invalid_command"
    elif not cwd_ok:
        failure = "cwd_unavailable"
    if phase == "no_protocol":
        # Completion could never be observed: never start the command.
        try:
            os.kill(child_pid, signal.SIGHUP)
        except OSError:
            pass
    fifo_pending = b""
    command_status = None
    protocol_violation = None
    shell_status = None
    result_written = False
    done = False
    stdin_eof = False
    exit_shell = False
    slave_fd = -1

    def _fail_closed(reason, end_phase):
        """Publish the final fail-closed result now: the outcome is known
        and no later record can change it."""
        nonlocal failure, phase, result_written
        failure = reason
        phase = end_phase
        if result_file:
            _publish_result(result_file, {
                "completed": False,
                "returncode": None,
                "failure": failure,
                "phase": phase,
                "shell_status": None,
                "stdout": bytes(stdout_buf).decode("utf-8", errors="replace"),
                "stderr": "",
            }, result_key)
        result_written = True

    def _close_fifo():
        # Unlink first: a later record write then cannot block on a FIFO
        # without reader.  The one-shot hook no longer writes after its
        # final record.
        nonlocal fifo_fd
        try:
            fifo_path.unlink()
        except OSError:
            pass
        try:
            os.close(fifo_fd)
        except OSError:
            pass
        fifo_fd = -1

    def _close_slave():
        nonlocal slave_fd
        if slave_fd >= 0:
            try:
                os.close(slave_fd)
            except OSError:
                pass
        slave_fd = -1

    def _hang_up_shell():
        # The shell forwards the hangup to its jobs (continuing stopped
        # ones), so no controlled process keeps running unobserved.
        try:
            os.kill(child_pid, signal.SIGHUP)
        except OSError:
            pass

    def _terminate_command():
        """End the typed command's process group (the terminal's foreground
        job): terminate, then force after a bounded grace."""
        try:
            pgrp = os.tcgetpgrp(master_fd)
        except OSError:
            return
        if pgrp <= 0:
            return
        for sig in (signal.SIGTERM, signal.SIGCONT):
            try:
                os.killpg(pgrp, sig)
            except OSError:
                return
        deadline = time.monotonic() + _CANCEL_GRACE_SECONDS
        while time.monotonic() < deadline:
            try:
                os.killpg(pgrp, 0)
            except OSError:
                return
            time.sleep(0.01)
        try:
            os.killpg(pgrp, signal.SIGKILL)
        except OSError:
            pass

    def _cancel_run():
        """The result consumer stopped observing the run: nothing it started
        keeps running unobserved, and the run ends fail-closed."""
        if phase == "running":
            _terminate_command()
        _close_slave()
        _fail_closed("cancelled", "cancelled")
        _close_fifo()
        _hang_up_shell()

    def _type_command():
        nonlocal phase
        phase = "running"
        # Write command to PTY - tty echo makes it visible to the user.
        # NO instrumentation is appended.  NO "exit" is sent.
        _write_to_fd(master_fd, (cmd_str + "\n").encode())

    def _editor_state():
        """True once the line editor reads the terminal (canonical mode
        off), False before, None if the terminal cannot be observed."""
        try:
            return not (termios.tcgetattr(slave_fd)[3] & termios.ICANON)
        except (termios.error, OSError):
            return None

    def _handle_record(raw):
        nonlocal phase, command_status, protocol_violation, result_written, exit_shell, slave_fd
        record = _parse_record(raw.decode("ascii", errors="replace"), nonce)
        kind = record[0] if record is not None else None
        if kind == PHASE_STARTUP and phase == "starting":
            fields = record[1]
            # The nonce now lives only in the shell's memory.
            try:
                rc_file.unlink()
            except OSError:
                pass
            if fields["kind"] != "file":
                # A shell function or builtin would replace the authorized
                # executable; an unresolvable one would never launch.
                _fail_closed("command_resolution_" + fields["kind"], "rejected")
            elif fields["context"] != "ok":
                _fail_closed("command_context_changed", "rejected")
            elif fields["editing"] == "1":
                try:
                    slave_fd = os.open(slave_name.decode(), os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
                except (OSError, UnicodeDecodeError, ValueError):
                    slave_fd = -1
                if slave_fd < 0:
                    _fail_closed("terminal_state_unobservable", "rejected")
                else:
                    phase = "awaiting_editor"
            elif len((cmd_str + "\n").encode()) > _CANONICAL_LINE_LIMIT:
                # Without a line editor the tty reads canonically and would
                # truncate the line.
                _fail_closed("command_line_exceeds_terminal_input_limit", "rejected")
            else:
                _type_command()
            if phase == "rejected":
                _close_fifo()
                exit_shell = True
            return
        if kind == PHASE_COMPLETE and phase == "running":
            command_status = record[1]["status"]
            phase = "completed"
            _drain_pty_output()
            combined_stdout = bytes(stdout_buf).decode("utf-8", errors="replace")
            result = {
                "completed": True,
                "returncode": command_status,
                "stdout": combined_stdout,
                "stderr": "",
            }
            if result_file:
                _publish_result(result_file, result, result_key)
            result_written = True
            _close_fifo()
            exit_shell = True
            return
        if kind == PHASE_SUSPENDED and phase == "running":
            # A stopped command has not completed; it is ended, not resumed
            # outside ADC's observation.
            _drain_pty_output()
            _fail_closed("command_suspended", "suspended")
            _close_fifo()
            _hang_up_shell()
            return
        if kind == PHASE_HOOK_FAILED and phase == "starting":
            _fail_closed("hook_installation_failed", "rejected")
            _close_fifo()
            exit_shell = True
            return
        # An unknown, unauthentic, malformed or out-of-order record is never
        # guessed into a phase: the command result stays unproven and the
        # run ends fail-closed.
        protocol_violation = raw.decode("ascii", errors="replace")[:80]
        command_typed = phase == "running"
        _close_slave()
        _fail_closed("protocol_violation", "protocol_violation")
        _close_fifo()
        if command_typed:
            # Never type into a running command: hang it up instead.
            _hang_up_shell()
        else:
            exit_shell = True

    try:
        while not done:
            if cancel_path is not None and not result_written and cancel_path.exists():
                _cancel_run()

            if phase == "awaiting_editor":
                ready = _editor_state()
                if ready is None:
                    _close_slave()
                    _fail_closed("terminal_state_unobservable", "rejected")
                    _close_fifo()
                    exit_shell = True
                elif ready:
                    _close_slave()
                    _type_command()

            fds = [master_fd]
            if phase not in ("starting", "awaiting_editor") and not stdin_eof:
                fds.append(sys.stdin.buffer)
            if fifo_fd >= 0:
                fds.append(fifo_fd)
            try:
                rlist, _, _ = select.select(fds, [], [], 0.05 if phase == "awaiting_editor" else 0.3)
            except InterruptedError:
                continue
            except (select.error, ValueError):
                break

            # Terminal stdin -> PTY (interactive input)
            if sys.stdin.buffer in rlist:
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
                    _take_pty_output(data)
                except (BlockingIOError, OSError):
                    pass

            # Phase records from the one-shot PROMPT_COMMAND
            if fifo_fd >= 0 and fifo_fd in rlist:
                try:
                    fifo_pending += os.read(fifo_fd, 256)
                except (BlockingIOError, OSError):
                    pass
                while fifo_fd >= 0 and b"\n" in fifo_pending:
                    raw, fifo_pending = fifo_pending.split(b"\n", 1)
                    _handle_record(raw)
                if fifo_fd >= 0 and len(fifo_pending) > _MAX_RECORD_BYTES:
                    _handle_record(fifo_pending)

            if exit_shell:
                exit_shell = False
                # The shell is idle at its prompt; headless runs end it.  A
                # rejected shell's input handling is not trusted: hang it up
                # instead of typing into it.
                if not is_real_tty:
                    if phase == "completed":
                        _write_to_fd(master_fd, b"exit\n")
                    else:
                        _hang_up_shell()

            # Check if child (bash) has exited -- lifecycle only: its status
            # never replaces the controlled command's own result.
            try:
                wpid, status = os.waitpid(child_pid, os.WNOHANG)
                if wpid == child_pid:
                    if os.WIFEXITED(status):
                        shell_status = os.WEXITSTATUS(status)
                    elif os.WIFSIGNALED(status):
                        shell_status = 128 + os.WTERMSIG(status)
                    done = True
            except ChildProcessError:
                done = True
    finally:
        # Restore original terminal attributes
        if is_real_tty:
            _restore_tty(sys.stdin.fileno())
        _close_slave()

    # Drain remaining PTY output (display/capture only after a result)
    while True:
        try:
            rlist, _, _ = select.select([master_fd], [], [], 0.1)
            if master_fd not in rlist:
                break
            data = os.read(master_fd, 4096)
            if not data:
                break
            _take_pty_output(data)
        except (BlockingIOError, OSError):
            break

    if capture_fh:
        capture_fh.close()

    if fifo_fd >= 0:
        _close_fifo()

    os.close(master_fd)

    try:
        os.waitpid(child_pid, 0)
    except OSError:
        pass

    if result_file and not result_written:
        # No COMPLETE record: the controlled command's result is unknown.
        # Fail closed without fabricating an exit status from the shell.
        combined_stdout = bytes(stdout_buf).decode("utf-8", errors="replace")
        _publish_result(result_file, {
            "completed": False,
            "returncode": None,
            "failure": failure or "no_command_completion",
            "phase": phase,
            "shell_status": shell_status,
            "stdout": combined_stdout,
            "stderr": "",
        }, result_key)

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

    sys.exit(command_status if command_status is not None else 1)

if __name__ == "__main__":
    main()
'''