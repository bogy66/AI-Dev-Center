"""Central visible-interactive-terminal execution surface for every
ADC-controlled software installation
(CLAUDE-ADC-VISIBLE-TERMINAL-FOR-SOFTWARE-INSTALLATION-001).

Every controlled software installation must run inside a real, visible,
interactive terminal so a human can observe the install and answer a
`sudo` password prompt directly, in the terminal's own PTY -- never as
data ADC itself receives, stores, or forwards. This module is the ONE
place that opens such a terminal; it never creates installation
authority itself (app.execution.execute_controlled has already
validated capability/approval/provenance before InteractiveTerminalLauncher
is ever reached) -- it is only the execution surface for an
already-authorized command.

Architecture: InteractiveTerminalLauncher depends on a small
TerminalProvider abstraction, never on one specific desktop terminal
program. DesktopTerminalProvider is the production provider: it tries a
short, ordered, extensible list of common Linux desktop terminal
emulators (never hard-coded solely to gnome-terminal) and uses whichever
one is actually present on PATH. Automated tests inject a fake provider
instead (see tests/test_interactive_terminal.py) so the deterministic
test suite never depends on a real GUI.

How the real exit code is obtained without ADC ever touching the
command's own stdin/stdout/stderr: the terminal emulator is launched
with the trusted Python producer (app/terminal_status_producer.py, run by
the absolute ADC interpreter in isolated mode) as its child. It runs the
real, already-authorized argv unmodified (passed as separate argv
elements -- never re-quoted or re-interpreted through a shell string, so
arguments containing spaces or special characters can never be
misparsed) exactly once, waits for it to actually complete and only then
publishes the REAL exit code to a status file inside an ADC-created 0700
execution directory.

Result authority (Interface Contract IFC-ADC-INSTALL-TERMINAL-STATUS-V3,
3.0.0): the status file's mere presence or content proves nothing by
itself, because the controlled command runs under the same account and
can discover, read and write that path. Each execution therefore gets a
fresh random 128-bit exec_id and a fresh 256-bit secret K, handed to the
producer in an exclusively created 0600 launch file it reads and removes
BEFORE the command starts; K never appears in argv, the command's
environment, the published record, diagnostics or logs. After the
command exits the producer atomically publishes exactly
`ADC-TERM-STATUS-V3 <exec_id> <outcome> <rc> <tag>\n`, where tag is
HMAC-SHA256 under K over exec_id, outcome and rc. Because the record does
not disclose K, reading a genuine record (e.g. by a descendant that
outlives the command) gives no ability to produce a valid record with
another rc, outcome or exec_id. A valid EXITED record is the command's
real completion; a valid NOT_STARTED record (the command could not be
started at all) is INTERACTIVE_TERMINAL_LAUNCH_FAILED; a missing,
malformed, unauthenticated (constant-time comparison), foreign or V1/V2
record, the terminal window being closed/cancelled, the terminal process
vanishing, or the deadline being reached is always
InteractiveTerminalError, never invented success.

Trust boundary: the result is protected against the controlled command
and its descendants acting through ordinary filesystem and process
interfaces, provided kernel.yama.ptrace_scope >= 1 (otherwise a
descendant could read the producer's memory; see
descendant_result_protection_available()). It is not protection against
root, against unrelated hostile processes of the same user -- including
processes left behind by an EARLIER execution, which could read the
launch file before the producer removes it --, against compromised ADC or
interpreter code, or against availability attacks (deleting or garbling
the record only ever makes the run fail closed). Status integrity is not
process-tree containment: a fail-closed outcome does not mean the command
or its descendants have stopped running in the terminal.

The wrapped command's real stdin/stdout/stderr belong entirely to the
terminal emulator's own PTY, never to this Python process, which is what
structurally guarantees ADC can never receive a sudo password (or any
other interactive input) as application data -- there is no code path
in this module, or anywhere else in ADC, that reads or forwards the
wrapped command's stdin.
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Protocol

from app import terminal_status_producer as _producer

# Structured, stable fail-closed cause identities. Never inferred or
# free-text -- callers (and Evidence/DiagnosticTrace consumers) can
# match on these exact values.
INTERACTIVE_TERMINAL_UNAVAILABLE = "INTERACTIVE_TERMINAL_UNAVAILABLE"
INTERACTIVE_TERMINAL_LAUNCH_FAILED = "INTERACTIVE_TERMINAL_LAUNCH_FAILED"
INTERACTIVE_TERMINAL_CANCELLED = "INTERACTIVE_TERMINAL_CANCELLED"


class InteractiveTerminalError(RuntimeError):
    """Raised whenever a controlled software installation cannot be
    proven to have run to completion inside a real, visible, interactive
    terminal. Never raised for a real command exit code: a command that
    genuinely ran to completion inside the terminal, even with a
    non-zero exit code, is reported as an ordinary
    subprocess.CompletedProcess by InteractiveTerminalLauncher.run(),
    not this exception. This is reserved for the terminal mechanism
    itself failing to provide that guarantee at all -- no terminal
    provider available, the terminal process failed to launch, or the
    terminal was closed/cancelled/timed out before the command reported
    a real result. `cause` is always one of the three module-level
    constants above.
    """

    def __init__(self, cause: str, detail: str = ""):
        message = f"{cause}: {detail}" if detail else cause
        super().__init__(message)
        self.cause = cause


@dataclass(frozen=True)
class TerminalLaunchOutcome:
    """What a TerminalProvider observed about one command it ran inside
    a real terminal. `completed=True` is the only shape that carries a
    real, trustworthy `returncode`; every other shape means the caller
    must not treat the installation as having succeeded."""
    completed: bool
    returncode: int | None = None
    cause: str | None = None
    detail: str = ""


class TerminalProvider(Protocol):
    """One concrete way of opening a real, visible, interactive terminal
    on this host and running exactly one already-authorized command
    inside it. InteractiveTerminalLauncher depends only on this
    protocol, never on any one provider's implementation, so ADC is not
    permanently tied to one desktop terminal program and a later
    provider can be added without touching any caller."""

    def is_available(self) -> bool:
        ...

    def run(
        self, argv: tuple[str, ...], cwd: str, env: dict[str, str], timeout: int,
    ) -> TerminalLaunchOutcome:
        ...


# Ordered, extensible candidate list of common Linux desktop terminal
# emulators -- a detection *strategy*, deliberately never a hard
# dependency on any single one of them. The first candidate whose
# binary is actually present on PATH is used. Each entry's flags are
# chosen so the terminal (a) blocks the launching process until the
# window itself closes rather than handing off to a background
# server-process and returning immediately (`--wait` for gnome-terminal;
# `--disable-server` for xfce4-terminal, which otherwise also uses a
# client/server model) and (b) closes automatically once the wrapped
# command finishes -- never `--hold`/`-hold`, which would keep a
# finished installation's window open and defeat "closes automatically
# when the installation command has terminated". Adding support for a
# different terminal later means adding one more entry here, never
# touching InteractiveTerminalLauncher or any of its callers.
_CANDIDATE_TERMINALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("gnome-terminal", ("--wait", "--")),
    ("xfce4-terminal", ("--disable-server", "-x")),
    ("konsole", ("-e",)),
    ("x-terminal-emulator", ("-e",)),
    ("xterm", ("-e",)),
)

# Only desktop/session connectivity is added to the controlled environment
# for the emulator. None of these additions is inherited by the command.
_DESKTOP_ENVIRONMENT_KEYS = frozenset({
    "DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS",
    "XDG_RUNTIME_DIR", "XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP", "DESKTOP_SESSION",
})

_POLL_INTERVAL_SECONDS = 0.25
# Some desktop terminals use a client/server model even with the flags
# above (e.g. an already-running server instance). If the launching
# process exits before the status file appears, this grace period is
# given for the real window's own child to still finish and write it,
# before the run is conservatively treated as cancelled -- avoiding a
# false "cancelled" verdict from a quick-returning launcher client.
_LAUNCHER_EXIT_GRACE_SECONDS = 2.0

# IFC-ADC-INSTALL-TERMINAL-STATUS-V3 record:
# "ADC-TERM-STATUS-V3 <exec_id> <outcome> <rc> <tag>\n". Only the exact
# grammar is parsed; the tag is then recomputed under this execution's K.
_STATUS_V3_RECORD = re.compile(
    rb"ADC-TERM-STATUS-V3 ([0-9a-f]{32}) "
    rb"(?:(EXITED) (0|[1-9][0-9]{0,2})|(NOT_STARTED) (-)) ([0-9a-f]{64})\n"
)

# The producer is started by the absolute ADC interpreter in isolated mode
# without site processing (-I -S): no PYTHON* variables, user site, script
# directory or third-party .pth code can influence it.
_PRODUCER_PATH = os.path.abspath(_producer.__file__)
_PRODUCER_INTERPRETER_FLAGS = ("-I", "-S")

_PTRACE_SCOPE_PATH = "/proc/sys/kernel/yama/ptrace_scope"
_logger = logging.getLogger(__name__)
_ptrace_warning_emitted = False


def descendant_result_protection_available(
    ptrace_scope_path: str = _PTRACE_SCOPE_PATH,
) -> bool:
    """Whether the STATUS-V3 prerequisite kernel.yama.ptrace_scope >= 1
    holds on this host. Only then may the guarantee "a descendant of the
    command cannot forge its result" be claimed: with ptrace_scope 0 (or
    no Yama LSM) a descendant may read the producer's memory, including
    the execution secret. Unknown is reported as not available."""
    try:
        with open(ptrace_scope_path, "rb") as f:
            return int(f.read(16).strip()) >= 1
    except (OSError, ValueError):
        return False


def _warn_if_descendant_protection_unavailable() -> None:
    global _ptrace_warning_emitted
    if _ptrace_warning_emitted or descendant_result_protection_available():
        return
    _ptrace_warning_emitted = True
    _logger.warning(
        "kernel.yama.ptrace_scope is not >= 1 (or unknown): terminal "
        "completion results are NOT protected against descendants of the "
        "installation command (IFC-ADC-INSTALL-TERMINAL-STATUS-V3 prerequisite)",
    )


class DesktopTerminalProvider:
    """Production TerminalProvider for a Linux desktop session. See
    module docstring for how the real exit code is obtained without
    ADC ever touching the wrapped command's own stdin/stdout/stderr."""

    def __init__(
        self,
        candidates: tuple[tuple[str, tuple[str, ...]], ...] = _CANDIDATE_TERMINALS,
        poll_interval: float = _POLL_INTERVAL_SECONDS,
        launcher_exit_grace: float = _LAUNCHER_EXIT_GRACE_SECONDS,
    ):
        self._candidates = candidates
        self._poll_interval = poll_interval
        self._launcher_exit_grace = launcher_exit_grace

    def _select_binary(self) -> tuple[str, tuple[str, ...]] | tuple[None, None]:
        for name, prefix in self._candidates:
            resolved = shutil.which(name)
            if resolved:
                return resolved, prefix
        return None, None

    def is_available(self) -> bool:
        binary, _ = self._select_binary()
        return binary is not None

    def run(
        self, argv: tuple[str, ...], cwd: str, env: dict[str, str], timeout: int,
    ) -> TerminalLaunchOutcome:
        binary, prefix = self._select_binary()
        if binary is None:
            return TerminalLaunchOutcome(
                completed=False, cause=INTERACTIVE_TERMINAL_UNAVAILABLE,
                detail="no supported visible interactive terminal emulator "
                       "was found on PATH",
            )

        if not sys.executable or not os.path.isabs(sys.executable):
            return TerminalLaunchOutcome(
                completed=False, cause=INTERACTIVE_TERMINAL_LAUNCH_FAILED,
                detail="the absolute ADC interpreter path for the terminal "
                       "status producer is unavailable",
            )
        _warn_if_descendant_protection_unavailable()
        # mkdtemp creates the private execution directory with mode 0700.
        with tempfile.TemporaryDirectory(prefix="adc-terminal-") as tmpdir:
            os.chmod(tmpdir, 0o700)
            status_path = os.path.join(tmpdir, _producer.STATUS_FILENAME)
            launch_path = os.path.join(tmpdir, _producer.LAUNCH_FILENAME)
            exec_id = secrets.token_hex(_producer.EXEC_ID_BYTES)
            status_key = secrets.token_bytes(_producer.KEY_BYTES)
            # The controlled environment travels with K in the private
            # launch file, so the command receives exactly `env` (never
            # the emulator's or an existing terminal server's). The cwd is
            # the one the terminal gives the producer, unchanged from V2.
            self._write_launch_file(launch_path, json.dumps({
                "key": status_key.hex(), "exec_id": exec_id, "env": dict(env),
            }).encode("utf-8"))

            # The emulator needs desktop connectivity; its child must not
            # inherit that environment. The command argv is forwarded as
            # separate argv elements and started by the producer as is.
            full_argv = [
                binary, *prefix, sys.executable, *_PRODUCER_INTERPRETER_FLAGS,
                _PRODUCER_PATH, status_path, *argv,
            ]
            launcher_env = {key: value for key, value in os.environ.items()
                            if key in _DESKTOP_ENVIRONMENT_KEYS}
            launcher_env.update(env)
            try:
                process = subprocess.Popen(
                    full_argv, cwd=cwd, env=launcher_env,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError as exc:
                return TerminalLaunchOutcome(
                    completed=False, cause=INTERACTIVE_TERMINAL_LAUNCH_FAILED,
                    detail=str(exc),
                )

            return self._wait_for_result(
                process, status_path, timeout, exec_id, status_key,
            )

    @staticmethod
    def _write_launch_file(launch_path: str, content: bytes) -> None:
        fd = os.open(
            launch_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            os.fchmod(fd, 0o600)
            view = memoryview(content)
            while view:
                view = view[os.write(fd, view):]
        finally:
            os.close(fd)

    def _wait_for_result(
        self, process: subprocess.Popen, status_path: str, timeout: int,
        exec_id: str, status_key: bytes,
    ) -> TerminalLaunchOutcome:
        deadline = time.monotonic() + timeout
        launcher_exited_at: float | None = None
        while True:
            if os.path.lexists(status_path):
                outcome = self._read_status(status_path, exec_id, status_key)
                try:
                    process.wait(timeout=max(self._poll_interval, 1))
                except subprocess.TimeoutExpired:
                    self._kill_launcher(process)
                return outcome

            now = time.monotonic()
            if process.poll() is not None:
                if launcher_exited_at is None:
                    launcher_exited_at = now
                elif now - launcher_exited_at >= self._launcher_exit_grace:
                    return TerminalLaunchOutcome(
                        completed=False, cause=INTERACTIVE_TERMINAL_CANCELLED,
                        detail="the terminal ended before the installation "
                               "command reported a result",
                    )
            if now > deadline:
                self._kill_launcher(process)
                return TerminalLaunchOutcome(
                    completed=False, cause=INTERACTIVE_TERMINAL_CANCELLED,
                    detail=f"terminal-hosted installation exceeded {timeout}s; "
                           "the command may still be running in the terminal",
                )
            time.sleep(self._poll_interval)

    @staticmethod
    def _kill_launcher(process: subprocess.Popen) -> None:
        """SIGKILL is asynchronous: reap the launcher so it is actually
        gone (not merely signalled) when the outcome is returned. This
        stops only the launcher process, not necessarily the command
        running inside the terminal."""
        process.kill()
        process.wait()

    @staticmethod
    def _read_status(
        status_path: str, exec_id: str, status_key: bytes,
    ) -> TerminalLaunchOutcome:
        """Accepts only one complete IFC-ADC-INSTALL-TERMINAL-STATUS-V3
        record of this execution whose tag verifies under this
        execution's secret; anything else fails closed immediately. Never
        echoes the file's content into the outcome detail.

        The status path is discoverable by the controlled command, so any
        filesystem object may appear there. Only a regular file is ever
        read, and nothing here may block: a FIFO, socket, device,
        directory or symlink is rejected from lstat() without being
        opened (opening a FIFO or a device can block indefinitely or have
        side effects), the open itself is non-blocking and never follows
        a symlink or acquires a controlling terminal, and fstat() must
        confirm it is still the same regular file (an object swapped in
        after lstat() is rejected, not waited on)."""
        not_regular = TerminalLaunchOutcome(
            completed=False, cause=INTERACTIVE_TERMINAL_CANCELLED,
            detail="terminal exit status was not a regular file; no result is "
                   "accepted and the command may still be running in the terminal",
        )
        try:
            before = os.lstat(status_path)
        except OSError as exc:
            return TerminalLaunchOutcome(
                completed=False, cause=INTERACTIVE_TERMINAL_CANCELLED,
                detail=f"terminal exit status could not be read: {exc.strerror}",
            )
        if not stat.S_ISREG(before.st_mode):
            return not_regular
        try:
            fd = os.open(
                status_path,
                os.O_RDONLY | os.O_NONBLOCK | os.O_NOCTTY
                | getattr(os, "O_NOFOLLOW", 0),
            )
        except OSError as exc:
            return TerminalLaunchOutcome(
                completed=False, cause=INTERACTIVE_TERMINAL_CANCELLED,
                detail=f"terminal exit status could not be read: {exc.strerror}",
            )
        try:
            opened = os.fstat(fd)
            if (not stat.S_ISREG(opened.st_mode)
                    or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)):
                return not_regular
            raw = os.read(fd, _producer.STATUS_MAX_BYTES + 1)
        except OSError as exc:
            return TerminalLaunchOutcome(
                completed=False, cause=INTERACTIVE_TERMINAL_CANCELLED,
                detail=f"terminal exit status could not be read: {exc.strerror}",
            )
        finally:
            os.close(fd)

        match = (_STATUS_V3_RECORD.fullmatch(raw)
                 if len(raw) <= _producer.STATUS_MAX_BYTES else None)
        authentic = False
        if match is not None:
            record_exec_id = match.group(1).decode("ascii")
            outcome = (match.group(2) or match.group(4)).decode("ascii")
            rc = (match.group(3) or match.group(5)).decode("ascii")
            expected_tag = _producer.status_tag(status_key, exec_id, outcome, rc)
            # Both comparisons always run: constant time, no early exit.
            same_exec = hmac.compare_digest(record_exec_id.encode("ascii"),
                                            exec_id.encode("ascii"))
            same_tag = hmac.compare_digest(match.group(6),
                                           expected_tag.encode("ascii"))
            authentic = same_exec and same_tag
        if not authentic:
            return TerminalLaunchOutcome(
                completed=False, cause=INTERACTIVE_TERMINAL_CANCELLED,
                detail="terminal exit status was not an authenticated completion "
                       "record of this execution; no result is accepted and the "
                       "command may still be running in the terminal",
            )
        if outcome == _producer.OUTCOME_NOT_STARTED:
            return TerminalLaunchOutcome(
                completed=False, cause=INTERACTIVE_TERMINAL_LAUNCH_FAILED,
                detail="the installation command could not be started inside "
                       "the terminal",
            )
        returncode = int(rc)
        if returncode > 255:
            return TerminalLaunchOutcome(
                completed=False, cause=INTERACTIVE_TERMINAL_CANCELLED,
                detail="terminal exit status was outside the valid range 0..255",
            )
        return TerminalLaunchOutcome(completed=True, returncode=returncode)


class InteractiveTerminalLauncher:
    """The single, central execution surface every ADC-controlled
    software installation runs through. Never creates installation
    authority itself -- app.execution.execute_controlled has already
    performed capability/approval/provenance validation before this
    class is ever reached; this class's only job is to run an
    already-authorized command inside a real, visible, interactive
    terminal and report back its real result, or fail closed with a
    structured cause."""

    def __init__(self, provider: TerminalProvider | None = None):
        self._provider = provider if provider is not None else DesktopTerminalProvider()

    def run(
        self, argv: tuple[str, ...], cwd: str, env: dict[str, str], timeout: int,
    ) -> subprocess.CompletedProcess:
        """Run argv inside a real, visible, interactive terminal and
        wait for it to actually complete. Returns an ordinary
        subprocess.CompletedProcess carrying the REAL command's exit
        code on success. Raises InteractiveTerminalError -- never
        returns a synthetic success -- when no terminal is available,
        launching one fails, or the terminal is cancelled/times out
        before the command reports a result."""
        if not self._provider.is_available():
            raise InteractiveTerminalError(
                INTERACTIVE_TERMINAL_UNAVAILABLE,
                "no supported visible interactive terminal provider is "
                "available on this host",
            )
        outcome = self._provider.run(argv, cwd, env, timeout)
        if not outcome.completed:
            raise InteractiveTerminalError(
                outcome.cause or INTERACTIVE_TERMINAL_UNAVAILABLE, outcome.detail,
            )
        return subprocess.CompletedProcess(list(argv), outcome.returncode, "", "")
