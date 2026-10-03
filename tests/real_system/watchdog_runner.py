"""Linux, test-owned TEST_033 supervisor; never imported by product code.

Run explicitly with python -m tests.real_system.watchdog_runner. The public
CLI supervises only TEST_033. supervise() also accepts synthetic test children.
The persistent flock inode is intentionally never unlinked (avoids lock races).
No stdout/provider transcript is captured: terminal evidence is bounded process
metadata. A killed supervisor leaves ownership metadata for fail-closed recovery.
"""
from __future__ import annotations

import argparse
import ctypes
import fcntl
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from requirements.evidence.run_identity import generate_run_id, is_valid_run_id

# Current TEST_033 planning envelope (not a universal workflow maximum):
# initial + rework + conservative recovery verification: 3*(600+900)=4500s;
# Council: two parallel phases at 135s plus up to three Chairman calls at
# 195s = 855s; two install/verify envelopes = 660s; discovery/development/
# test-generation/diagnosis and filesystem/terminal overhead fit well below
# the remaining 4785s. Variable plans/configuration require budget review.
# 7200s is too close to this conservative path; 10800s is a final safety net.
OUTER_SECONDS = 10800
# Allow cleanup/trace flushing before force-killing stalled descendants.
GRACE_SECONDS = 120
TEST033 = "tests/real_system/real_system_e2e.py::test_real_esphome_esp32_hello_world_acceptance"


def build_test033_command(root, diagnostic_level, run_id):
    """Build the single supported TEST_033 command with formal Evidence on."""
    if not is_valid_run_id(run_id):
        raise ValueError("invalid TEST_033 Evidence run id")
    return [
        str(root / "venv/bin/python"), "-u", "-m", "pytest",
        "-p", "requirements.evidence.pytest_plugin", "--adc-evidence",
        f"--adc-evidence-run-id={run_id}", TEST033,
        "--real-system-e2e", f"--diagnostic-level={diagnostic_level}", "-s", "-vv",
    ]


def verify_test033_evidence(run_id, store_root):
    """Require pytest's finalized, passing event before reporting TEST_033 success."""
    if not is_valid_run_id(run_id):
        return False, "INVALID_RUN_ID"
    run_dir = Path(store_root) / "runs" / run_id
    try:
        manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        events = [json.loads(path.read_text(encoding="utf-8"))
                  for path in sorted((run_dir / "events").glob("*.json"))]
    except (OSError, ValueError, TypeError):
        return False, "FORMAL_EVIDENCE_MISSING_OR_INVALID"
    matches = [event for event in events
               if event.get("run_id") == run_id
               and event.get("test_selector") == TEST033]
    event_ids = [event.get("event_id") for event in events]
    if (manifest.get("run_id") != run_id or manifest.get("run_status") != "completed"
            or manifest.get("event_count") != len(events)
            or manifest.get("event_ids") != event_ids
            or len(matches) != 1 or matches[0].get("result") != "IO"
            or matches[0].get("repository_identity") != manifest.get("repository_identity")):
        return False, "FORMAL_TEST033_RESULT_NOT_IO"
    return True, "FORMAL_TEST033_EVIDENCE_OK"


def identity(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return {"pid": int(pid), "state": fields[0], "ppid": int(fields[1]), "pgid": int(fields[2]),
                "sid": int(fields[3]), "start": int(fields[19])}
    except (FileNotFoundError, ProcessLookupError):
        return None


def members(pgid):
    found = []
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            item = identity(int(entry.name))
            if item and item["pgid"] == pgid and item["sid"] == pgid:
                found.append(item)
    return found


def owned(pgid):
    """Include nested sessions created by ADC's own execution isolation.

    This dedicated supervisor is a subreaper; even double-forked children
    become its children. Never use process names to infer ownership.
    """
    processes = []
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            item = identity(int(entry.name))
            if item:
                processes.append(item)
    parents = {os.getpid()}
    selected = {}
    while True:
        added = [p for p in processes if p["ppid"] in parents and p["pid"] not in selected]
        if not added:
            return list(selected.values())
        for p in added:
            selected[p["pid"]] = p
            parents.add(p["pid"])


def signal_owned(pgid, sig):
    # The primary group's SID/PGID was created exclusively for this child.
    snapshot = owned(pgid)
    if any(p["pgid"] == pgid and p["sid"] == pgid for p in snapshot):
        _signal(pgid, sig)
    for old in snapshot:
        now = identity(old["pid"])
        if now and now["start"] == old["start"]:
            try:
                os.kill(old["pid"], sig)
            except ProcessLookupError:
                pass


def boot_id():
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def prior_live(record):
    if record.get("boot") != boot_id():
        return False
    for old in [record.get("supervisor"), record.get("child"), *record.get("owned", [])]:
        now = identity(old["pid"]) if isinstance(old, dict) and "pid" in old else None
        if now and now["start"] == old.get("start") and now["state"] != "Z":
            return True
    child = record.get("child")
    if isinstance(child, dict):
        # An orphan in the original session still belongs to the old run.
        # A reused leader PID with a different start time is not that session.
        leader = identity(child["pid"])
        if leader and leader["start"] != child["start"]:
            return False
        return any(p["start"] >= child["start"] and p["state"] != "Z"
                   for p in members(child["pid"]))
    return False


def emit(status, **fields):
    print("RSE_SUPERVISOR " + json.dumps({"status": status, **fields}, sort_keys=True), flush=True)


def _signal(pgid, sig):
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        pass


def _reap(pgid):
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid == 0:
            return


def supervise(command, *, state_dir, seconds=OUTER_SECONDS, grace=GRACE_SECONDS):
    """Return 124 for timeout, 125 for stale/cleanup failure, child rc otherwise.

    Must run in a dedicated supervisor process: Linux subreaper adoption allows
    orphaned grandchildren in the owned session to be reaped, not just killed.
    Nested sessions remain owned through ancestry and subreaper adoption.
    """
    if not all(math.isfinite(v) and v > 0 for v in (seconds, grace)):
        raise ValueError("watchdog budgets must be finite and positive")
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    marker = state_dir / "test033.json"
    with (state_dir / "test033.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            emit("STALE_LIVE_RUN_REFUSED")
            return 125
        if marker.exists():
            try:
                record = json.loads(marker.read_text())
                live = prior_live(record)
            except (ValueError, TypeError, KeyError, AttributeError):
                emit("INVALID_OWNERSHIP_MARKER")
                return 125
            if live:
                emit("STALE_LIVE_RUN_REFUSED")
                return 125
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
            raise OSError(ctypes.get_errno(), "Cannot enable child subreaper")
        interrupted = []
        old_handlers = {}
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            old_handlers[sig] = signal.signal(sig, lambda s, f: interrupted.append(s))
        child = None
        cleaned = False
        started = time.monotonic()
        record = {"boot": boot_id(), "supervisor": identity(os.getpid())}
        def save():
            temp = marker.with_suffix(".tmp")
            temp.write_text(json.dumps(record))
            os.replace(temp, marker)
        save()  # lock is already held, including the spawn/metadata interval
        try:
            child = subprocess.Popen(command, start_new_session=True, pass_fds=(lock.fileno(),))
            pgid = child.pid
            record["child"] = identity(pgid)
            save()
            emit("STARTED", pid=pgid, seconds=seconds, grace=grace)
            while child.poll() is None and time.monotonic() - started < seconds and not interrupted:
                current = owned(pgid)
                if current != record.get("owned"):
                    record["owned"] = current
                    save()
                time.sleep(0.02)
            expired = child.poll() is None and not interrupted
            rc = child.poll()
            remaining = owned(pgid)
            if remaining:
                emit("WATCHDOG_TIMEOUT" if expired else "CLEANUP", members=remaining[:32],
                     member_count=len(remaining))
                signal_owned(pgid, signal.SIGTERM)
                signal_owned(pgid, signal.SIGCONT)
                deadline = time.monotonic() + grace
                while time.monotonic() < deadline:
                    child.poll()
                    _reap(pgid)
                    if not owned(pgid):
                        break
                    time.sleep(0.02)
                if owned(pgid):
                    emit("KILL_ESCALATION")
                    signal_owned(pgid, signal.SIGKILL)
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    child.poll()
                    _reap(pgid)
                    if not owned(pgid):
                        break
                    time.sleep(0.02)
            cleaned = not owned(pgid)
            if not cleaned:
                emit("CLEANUP_FAILED")
                return 125
            child.wait()
            result = 124 if expired else (128 + interrupted[0] if interrupted else rc)
            # A signal-killed pytest must never be mapped to success.
            if result is not None and result < 0:
                result = 128 - result
            emit("WATCHDOG_TIMEOUT" if expired else "INTERRUPTED" if interrupted else "PYTEST_EXIT",
                 returncode=result, elapsed_seconds=round(time.monotonic() - started, 3))
            return result
        except Exception as error:
            # Error type only: exception text/argv might contain credentials.
            emit("SUPERVISOR_ERROR", error_type=type(error).__name__)
            return 125
        finally:
            if child is not None and not cleaned:
                signal_owned(child.pid, signal.SIGKILL)
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
                _reap(child.pid)
            if cleaned or child is None:
                marker.unlink(missing_ok=True)
            for sig, handler in old_handlers.items():
                signal.signal(sig, handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=OUTER_SECONDS)
    parser.add_argument("--grace", type=float, default=GRACE_SECONDS)
    parser.add_argument("--diagnostic-level", choices=["NONE", "NORMAL", "INFO", "VERBOSE", "VERY_VERBOSE"], default="NORMAL")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    os.chdir(root)
    run_id = generate_run_id()
    result = supervise(build_test033_command(root, args.diagnostic_level, run_id),
                       state_dir=root / ".rse-supervisor", seconds=args.seconds, grace=args.grace)
    if result == 0:
        valid, status = verify_test033_evidence(
            run_id, root / "requirements" / "_evidence",
        )
        emit(status, run_id=run_id)
        if not valid:
            return 1
        return 0
    emit("FORMAL_TEST033_RUN_INCOMPLETE", run_id=run_id, pytest_returncode=result)
    return result


if __name__ == "__main__":
    sys.exit(main())
