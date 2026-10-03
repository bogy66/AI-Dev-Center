"""Trusted producer of IFC-ADC-INSTALL-TERMINAL-STATUS-V3 completion
evidence (the ADC terminal wrapper).

DesktopTerminalProvider launches this file inside the visible terminal as
`<absolute ADC interpreter> -I -S <this file> <status path> <argv...>`.
It is deliberately self-contained (standard library only) because -I/-S
keep the script directory, user site and third-party packages off
sys.path, and it is also imported by the consumer so both sides share one
MAC definition.

Why a Python producer: the interpreter reads and compiles this whole file
before anything runs, so the productive command cannot rewrite code that
is still to be interpreted by the process holding the secret (a shell
re-reads its script file while its child runs), the MAC is computed
in-process (the secret never becomes argv of a helper), and a command that
could not be started is distinguishable from one that started and exited.

Sequence, per execution:
1. Read the private launch file (secret K, exec_id, controlled
   environment) that ADC exclusively created in its 0700 execution
   directory, and remove it; if it cannot be read and verifiably removed
   nothing is started and nothing is published.
2. Start the authorized argv exactly once -- unmodified, with exactly the
   controlled environment, the cwd the terminal gave the producer and the
   terminal's own stdin/stdout/stderr -- and wait for that direct child
   to exit.
3. Publish exactly one record, atomically:
   "ADC-TERM-STATUS-V3 <exec_id> <outcome> <rc> <tag>\\n"
   with tag = HMAC-SHA256(K, "ADC-TERM-STATUS-V3\\0" exec_id "\\0"
   outcome "\\0" rc). The record never contains K, so reading it gives no
   ability to produce a record with another outcome, rc or exec_id.
"""
import hashlib
import hmac
import json
import os
import re
import signal
import stat
import subprocess
import sys

STATUS_RECORD_TYPE = "ADC-TERM-STATUS-V3"
OUTCOME_EXITED = "EXITED"
OUTCOME_NOT_STARTED = "NOT_STARTED"
NOT_STARTED_RC = "-"
LAUNCH_FILENAME = "status.key"
STATUS_FILENAME = "exit_status"
KEY_BYTES = 32
EXEC_ID_BYTES = 16
# Upper bounds: a genuine record is at most 136 bytes.
STATUS_MAX_BYTES = 256
_LAUNCH_MAX_BYTES = 1 << 20
_EXEC_ID = re.compile(r"[0-9a-f]{32}")
_KEY_HEX = re.compile(r"[0-9a-f]{64}")
# Exit code of the producer itself when no secret is available; nothing is
# started and no record can be published.
_PRODUCER_UNAVAILABLE_EXIT = 125
_NOT_STARTED_EXIT = 127


def status_tag(key: bytes, exec_id: str, outcome: str, rc: str) -> str:
    """The contract MAC over the deterministic ASCII serialization."""
    message = b"\0".join(
        part.encode("ascii") for part in (STATUS_RECORD_TYPE, exec_id, outcome, rc)
    )
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def status_record(key: bytes, exec_id: str, outcome: str, rc: str) -> bytes:
    tag = status_tag(key, exec_id, outcome, rc)
    return f"{STATUS_RECORD_TYPE} {exec_id} {outcome} {rc} {tag}\n".encode("ascii")


def _read_launch_file(path: str) -> dict:
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOCTTY | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("launch file is not a regular file")
        chunks = []
        remaining = _LAUNCH_MAX_BYTES + 1
        while remaining > 0:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
    finally:
        os.close(fd)
    raw = b"".join(chunks)
    if len(raw) > _LAUNCH_MAX_BYTES:
        raise ValueError("launch file too large")
    return json.loads(raw.decode("utf-8"))


def _take_launch(path: str) -> tuple[bytes, str, dict[str, str]]:
    """Reads and removes the launch file; succeeds only if it is gone."""
    try:
        launch = _read_launch_file(path)
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
    if os.path.lexists(path):
        raise ValueError("launch file could not be removed")
    key_hex, exec_id = launch["key"], launch["exec_id"]
    env = launch["env"]
    if (not isinstance(key_hex, str) or not _KEY_HEX.fullmatch(key_hex)
            or not isinstance(exec_id, str) or not _EXEC_ID.fullmatch(exec_id)
            or not isinstance(env, dict)
            or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items())):
        raise ValueError("launch file is malformed")
    return bytes.fromhex(key_hex), exec_id, env


def _publish(status_path: str, record: bytes) -> bool:
    tmp_path = status_path + ".tmp"
    try:
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except OSError:
        return False
    try:
        written = os.write(fd, record)
    except OSError:
        written = -1
    finally:
        os.close(fd)
    if written != len(record):
        return False
    try:
        os.rename(tmp_path, status_path)
    except OSError:
        return False
    return True


def main(args: list[str]) -> int:
    # Behave like a plain shell wrapper on Ctrl-C: default disposition, so
    # an interrupt that ends the command also ends the producer and no
    # completion is published (cancellation, not a result).
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    if len(args) < 2:
        print("ADC: terminal wrapper invoked without a command; nothing started",
              file=sys.stderr)
        return _PRODUCER_UNAVAILABLE_EXIT
    status_path, argv = args[0], args[1:]
    launch_path = os.path.join(os.path.dirname(status_path), LAUNCH_FILENAME)
    try:
        key, exec_id, env = _take_launch(launch_path)
    except Exception:
        print("ADC: terminal execution secret unavailable; command not started",
              file=sys.stderr)
        return _PRODUCER_UNAVAILABLE_EXIT

    try:
        # Popen reports exec failures of the child as OSError, so
        # reaching wait() means the command's own image actually started.
        process = subprocess.Popen(argv, env=env, close_fds=True)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        reason = exc.strerror if isinstance(exc, OSError) and exc.strerror else type(exc).__name__
        print(f"ADC: the installation command could not be started: {reason}",
              file=sys.stderr)
        _publish(status_path, status_record(key, exec_id, OUTCOME_NOT_STARTED, NOT_STARTED_RC))
        return _NOT_STARTED_EXIT

    returncode = process.wait()
    rc = returncode if returncode >= 0 else 128 - returncode
    if not _publish(status_path, status_record(key, exec_id, OUTCOME_EXITED, str(rc))):
        print("ADC: the command's completion could not be recorded", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
