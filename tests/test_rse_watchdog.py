"""Synthetic process tests: no RSE selector or provider is executed."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from tests.real_system.watchdog_runner import (
    TEST033, boot_id, identity, build_test033_command, verify_test033_evidence,
)
from requirements.evidence.run_identity import generate_run_id

ROOT = Path(__file__).resolve().parents[1]


def launch(tmp_path, code, seconds=0.5, grace=0.15):
    script = tmp_path / f"child-{time.monotonic_ns()}.py"
    script.write_text(code)
    wrapper = (
        "from tests.real_system.watchdog_runner import supervise; import sys; "
        f"sys.exit(supervise({[sys.executable, str(script)]!r}, "
        f"state_dir={str(tmp_path / 'state')!r}, seconds={seconds!r}, grace={grace!r}))"
    )
    return subprocess.Popen([sys.executable, "-c", wrapper], cwd=ROOT,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def finish(process):
    try:
        out, err = process.communicate(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        pytest.fail("synthetic supervisor exceeded independent test deadline")
    assert not err, err
    return process.returncode, out


def wait_file(path):
    end = time.monotonic() + 4
    while not path.exists() and time.monotonic() < end:
        time.sleep(0.01)
    assert path.exists()
    return path


@pytest.mark.parametrize("behavior", ["stop", "ignore", "descendant"])
def test_outer_watchdog_cleans_owned_group_and_preserves_control(tmp_path, behavior):
    pids = tmp_path / "pids"
    code = f"import os, signal, time\nfrom pathlib import Path\nPath({str(pids)!r}).write_text(str(os.getpid()))\n"
    if behavior == "stop":
        code += "os.kill(os.getpid(), signal.SIGSTOP)\n"
    elif behavior == "ignore":
        code += "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    else:
        code += ("pid = os.fork()\nif pid == 0:\n"
                 f"    with open({str(pids)!r}, 'a') as f: f.write(' ' + str(os.getpid()))\n"
                 "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                 "    os.kill(os.getpid(), signal.SIGSTOP)\n")
    code += "time.sleep(60)\n"
    control = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        started = time.monotonic()
        result, output = finish(launch(tmp_path, code))
        assert result == 124 and "WATCHDOG_TIMEOUT" in output
        assert time.monotonic() - started < 6
        if behavior != "stop":
            assert "KILL_ESCALATION" in output
        for pid in pids.read_text().split():
            assert identity(int(pid)) is None, f"owned process {pid} was not reaped"
        assert control.poll() is None
        assert not (tmp_path / "state/test033.json").exists()
    finally:
        control.terminate()
        control.wait(timeout=3)


def test_live_run_refused_and_timeout_marker_recovered(tmp_path):
    first = launch(tmp_path, "import time; time.sleep(60)", seconds=1.2)
    wait_file(tmp_path / "state/test033.json")
    rc, out = finish(launch(tmp_path, "raise SystemExit(0)"))
    assert rc == 125 and "STALE_LIVE_RUN_REFUSED" in out
    assert finish(first)[0] == 124
    assert finish(launch(tmp_path, "raise SystemExit(0)"))[0] == 0


@pytest.mark.parametrize("reused", [False, True])
def test_dead_or_reused_pid_marker_recovers(tmp_path, reused):
    state = tmp_path / "state"
    state.mkdir()
    old = dict(identity(os.getpid())) if reused else {"pid": 99999999, "start": 1}
    if reused:
        old["start"] -= 1
    (state / "test033.json").write_text(json.dumps({"boot": boot_id(), "supervisor": old}))
    rc, out = finish(launch(tmp_path, "raise SystemExit(7)"))
    assert rc == 7 and '"status": "PYTEST_EXIT"' in out
    assert not (state / "test033.json").exists()


def test_unrelated_pytest_named_process_does_not_block(tmp_path):
    control = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "pytest", "TEST_033"])
    try:
        assert finish(launch(tmp_path, "raise SystemExit(0)"))[0] == 0
        assert control.poll() is None
    finally:
        control.terminate()
        control.wait(timeout=3)


def test_parent_exit_still_reaps_difficult_orphan(tmp_path):
    pids = tmp_path / "orphan"
    code = ("import os, signal, time\n"
            "if os.fork() == 0:\n"
            "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            f"    open({str(pids)!r}, 'w').write(str(os.getpid()))\n"
            "    time.sleep(60)\nelse:\n    time.sleep(0.1)\n")
    rc, out = finish(launch(tmp_path, code, seconds=2))
    assert rc == 0 and "KILL_ESCALATION" in out
    assert identity(int(pids.read_text())) is None


def test_default_approved_store_is_isolated_and_explicit_path_preserved(tmp_path):
    from app.approved_plan_content import ApprovedPlanContentStore
    tracked = ROOT / "approved_plan_content.json"
    before = tracked.read_bytes()
    first, second = ApprovedPlanContentStore(), ApprovedPlanContentStore()
    assert first.storage == second.storage
    assert first.storage.resolve() != tracked
    first._save_raw({"synthetic": {}})
    assert second._load_raw() == {"synthetic": {}}
    explicit = tmp_path / "explicit.json"
    assert ApprovedPlanContentStore(explicit).storage == explicit
    assert tracked.read_bytes() == before


def test_nested_new_session_is_owned_and_reaped(tmp_path):
    pids = tmp_path / "session-child"
    code = ("import os, signal, time\n"
            "if os.fork() == 0:\n"
            "    os.setsid()\n"
            "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            f"    open({str(pids)!r}, 'w').write(str(os.getpid()))\n"
            "    os.kill(os.getpid(), signal.SIGSTOP)\n"
            "    time.sleep(60)\nelse:\n    time.sleep(60)\n")
    rc, out = finish(launch(tmp_path, code))
    assert rc == 124 and "KILL_ESCALATION" in out
    assert identity(int(pids.read_text())) is None


def test_test033_command_enables_formal_evidence_and_pins_run_id(tmp_path):
    run_id = generate_run_id()
    command = build_test033_command(tmp_path, "NORMAL", run_id)
    assert "-p" in command
    assert "requirements.evidence.pytest_plugin" in command
    assert "--adc-evidence" in command
    assert f"--adc-evidence-run-id={run_id}" in command
    assert TEST033 in command


@pytest.mark.parametrize(("result", "expected"), [("IO", True), ("NIO", False), ("NOT_RUN", False)])
def test_test033_requires_finalized_passing_formal_event(tmp_path, result, expected):
    run_id = generate_run_id()
    run_dir = tmp_path / "runs" / run_id
    events_dir = run_dir / "events"
    events_dir.mkdir(parents=True)
    repository_identity = {"commit": "abc123", "dirty": False, "worktree": "/tmp/example"}
    (run_dir / "run.json").write_text(json.dumps({
        "run_id": run_id, "run_status": "completed", "event_count": 1,
        "event_ids": ["EVT-0001"], "repository_identity": repository_identity,
    }))
    (events_dir / "EVT-0001.json").write_text(json.dumps({
        "run_id": run_id, "event_id": "EVT-0001", "test_selector": TEST033,
        "result": result, "repository_identity": repository_identity,
    }))
    assert verify_test033_evidence(run_id, tmp_path) == (
        expected, "FORMAL_TEST033_EVIDENCE_OK" if expected else "FORMAL_TEST033_RESULT_NOT_IO",
    )


def test_marker_alone_refuses_valid_live_owner(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "test033.json").write_text(json.dumps({"boot": boot_id(), "supervisor": identity(os.getpid())}))
    rc, out = finish(launch(tmp_path, "raise SystemExit(0)"))
    assert rc == 125 and "STALE_LIVE_RUN_REFUSED" in out
    assert (state / "test033.json").exists()
