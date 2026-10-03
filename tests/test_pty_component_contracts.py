"""Independent execution-surface contract tests (autonomy pilot 001).

Authority: ARC_REQ_009 and SUB_REQ_010 (exact final-child argv, cwd,
controlled environment, exactly one launch and real status); SUB_REQ_032
(no invented completion). These exercise the PTY COMPONENT, not the
productive InteractiveTerminalLauncher or a real desktop terminal.

Assertions intentionally remain red when the candidate violates a contract.
Readiness uses child artifacts/result publication; timeouts only bound a
broken run. No test treats elapsed startup time as completion evidence.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

import pytest

from app.execution_presenter import _PTY_LAUNCHER_SCRIPT, TerminalCommandRunner

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or shutil.which("bash") is None,
    reason="real Linux PTY and bash required",
)


def _wait(predicate, description, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            pytest.fail(f"deadline waiting for {description}")
        time.sleep(0.01)


def _descendants(pid):
    """Only children of this test's launcher; never host-wide process kills."""
    try:
        children = Path(f"/proc/{pid}/task/{pid}/children").read_text().split()
    except (FileNotFoundError, ProcessLookupError):
        # The process may exit between listing and reading (ESRCH).
        return []
    result = []
    for child in children:
        result.extend(_descendants(int(child)))
        result.append(int(child))
    return result


class Launch:
    def __init__(self, root, body, *, args=(), bashrc="", command=None,
                 child_env=None, ambient=None, cwd=None, terminal_input=False, result_path=None):
        self.root = root
        root.mkdir()
        home = root / "home"
        home.mkdir()
        (home / ".bashrc").write_text(bashrc)
        self.artifact = root / "child.json"
        self.result_path = Path(result_path) if result_path else root / "result.json"
        self.script = root / "child.py"
        self.script.write_text(body)
        # Keep real secrets/session data out of child-observation artifacts.
        inherited = {k: v for k, v in os.environ.items() if k in {
            "PATH", "LANG", "LC_ALL", "PYTHONPATH", "ADC_GATE1_CONTAINMENT_ACTIVE",
            "ADC_GATE1_SITECUSTOMIZE_DIR",
        }}
        env = {**inherited, "HOME": str(home), "TERM": "dumb", **(ambient or {})}
        config = {
            "command": command if command is not None else [sys.executable, str(self.script), *args],
            "cwd": str(cwd if cwd is not None else root),
            "env": env if child_env is None else {**child_env, "HOME": str(home)},
            "auto_close": True,
            "result_file": str(self.result_path),
            "stdout_capture": str(root / "stdout.capture"),
        }
        (root / "config.json").write_text(json.dumps(config))
        (root / "pty_launcher.py").write_text(_PTY_LAUNCHER_SCRIPT)
        self.output = (root / "launcher.output").open("wb")
        self.master = self.slave = None
        if terminal_input:
            self.master, self.slave = os.openpty()
        self.process = subprocess.Popen(
            [sys.executable, str(root / "pty_launcher.py"), str(root / "config.json")],
            stdin=self.slave if terminal_input else subprocess.DEVNULL,
            stdout=self.output, stderr=self.output, env=env, start_new_session=True,
        )

    def result(self):
        _wait(self.result_path.exists, "published result")
        return json.loads(self.result_path.read_text())

    def child(self):
        _wait(self.artifact.exists, "child observation")
        return json.loads(self.artifact.read_text())

    def close(self):
        # Capture ownership before terminating ancestors. Include the observed
        # child even when a broken launcher already orphaned it.
        pids = _descendants(self.process.pid)
        if self.artifact.exists():
            try:
                pid = json.loads(self.artifact.read_text()).get("pid")
                if pid and pid not in pids:
                    try:
                        argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
                    except FileNotFoundError:
                        argv = []
                    if os.fsencode(self.script) in argv:
                        pids.append(pid)
            except (ValueError, AttributeError):
                pass
        for pid in [*pids, self.process.pid]:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        self.process.wait(timeout=5)
        self.output.close()
        for fd in (self.master, self.slave):
            if fd is not None:
                os.close(fd)


@pytest.fixture
def launch(tmp_path):
    launches = []

    def start(body, **kwargs):
        child = Launch(tmp_path / f"run-{len(launches)}", body, **kwargs)
        launches.append(child)
        return child

    yield start
    for child in reversed(launches):
        child.close()


_OBSERVE = """import json, os, sys
from pathlib import Path
Path(__file__).with_name('child.json').write_text(json.dumps({
    'argv': sys.argv[1:], 'cwd': os.getcwd(), 'env': dict(os.environ),
    'pid': os.getpid(), 'tty': os.isatty(0),
}))
"""


@pytest.mark.parametrize("status", [0, 37, 143])
def test_final_status_and_output_are_child_observations(launch, status):
    run = launch(_OBSERVE + f"print('end-' + 'pilot-391d');sys.exit({status})\n",
                 bashrc="trap 'exit 29' EXIT\n")
    result = run.result()
    assert result["completed"] is True and result["returncode"] == status
    assert "end-pilot-391d\r\n" in result["stdout"]
    assert run.child()["tty"] is True
    run.process.wait(timeout=5)


@pytest.mark.parametrize("editing", ["", "set +o emacs; set +o vi\n"])
def test_argument_bytes_survive_terminal_input(launch, editing):
    args = ["", "a b", "tab\there", "line\nbreak", "\x03\x15\x7f", "ü/雪", "'\"$;\\"]
    run = launch(_OBSERVE, args=args, bashrc=editing)
    assert run.result()["returncode"] == 0
    assert run.child()["argv"] == args


def test_long_argument_is_complete_with_line_editor(launch):
    value = "long-" * 1400
    run = launch(_OBSERVE, args=[value])
    assert run.result()["returncode"] == 0
    assert run.child()["argv"] == [value]


def test_canonical_input_overflow_never_runs_truncated_command(launch):
    run = launch(_OBSERVE, args=["long-" * 1400], bashrc="set +o emacs; set +o vi\n")
    result = run.result()
    assert result.get("completed") is False and result["returncode"] is None
    assert not run.artifact.exists()


@pytest.mark.parametrize("command", [[], [""], [sys.executable, "bad\x00argument"]])
def test_invalid_argv_never_acquires_completion_authority(launch, command):
    run = launch(_OBSERVE, command=command)
    result = run.result()
    assert result.get("completed") is False and result["returncode"] is None
    assert not run.artifact.exists()


def test_startup_environment_changes_do_not_reach_child(launch):
    run = launch(_OBSERVE, ambient={"PILOT_APPROVED": "original"},
                 bashrc="export PILOT_APPROVED=changed; export PILOT_INJECTED=yes; cd /\n")
    assert run.result()["returncode"] == 0
    observed = run.child()
    assert observed["cwd"] == str(run.root)
    assert observed["env"]["PILOT_APPROVED"] == "original"
    assert "PILOT_INJECTED" not in observed["env"]


def test_excluded_launcher_environment_never_reappears_in_child(launch):
    """SUB_REQ_010: launcher/session variables are not child authority."""
    run = launch(_OBSERVE, child_env={"PATH": os.environ["PATH"], "TERM": "dumb"},
                 ambient={"PILOT_EXCLUDED_SECRET": "not-authorized"})
    assert run.result()["returncode"] == 0
    assert run.child()["env"].get("PILOT_EXCLUDED_SECRET") is None


def test_unavailable_cwd_never_falls_back_to_launcher_cwd(launch, tmp_path):
    """ARC_REQ_009: failure to enter the authorized cwd forbids execution."""
    run = launch(_OBSERVE, cwd=tmp_path / "missing-cwd")
    result = run.result()
    assert result.get("completed") is False and result["returncode"] is None
    assert not run.artifact.exists()


def test_unavailable_completion_hook_fails_before_child_start(launch):
    run = launch(_OBSERVE, bashrc="readonly PROMPT_COMMAND=':'\n")
    result = run.result()
    assert result.get("completed") is False and result["returncode"] is None
    assert not run.artifact.exists()


@pytest.mark.parametrize("record", [
    "ADC-PTY-V1 COMPLETE 0\n",
    "ADC-PTY-V2 stale-run COMPLETE 0\n",
    "ADC-PTY-V2 stale-run COMPLETE 0\nADC-PTY-V2 stale-run COMPLETE 37\n",
    "garbage\n",
    "x" * 513,
])
def test_foreign_transport_records_never_authorize_success(launch, record):
    body = _OBSERVE + f"\nwith open(Path(__file__).with_name('exit_code.fifo'), 'w') as stream:\n    stream.write({record!r})\nraise SystemExit(37)\n"
    run = launch(body)
    result = run.result()
    assert result.get("completed") is False and result["returncode"] is None


def test_suspended_child_is_not_a_completed_command(launch):
    run = launch(_OBSERVE + "import signal;os.kill(os.getpid(), signal.SIGSTOP)\n")
    result = run.result()
    assert result.get("completed") is False and result["returncode"] is None


@pytest.mark.parametrize("hook", [
    "_adc_record COMPLETE 0",
    "_adc_record COMPLETE 0; _adc_record COMPLETE 37",
])
def test_shell_startup_cannot_supply_forged_child_completion(launch, hook):
    """Startup configuration has no authority to report a child's success.

    Bash PS0 is expanded before executing the typed command. A startup
    file must not gain authority over completion by expanding a shell hook;
    the command must still run and finish before a result becomes valid.
    """
    rc = "PS0='$(" + hook + ")'\n"
    run = launch(_OBSERVE + "raise SystemExit(37)\n", bashrc=rc)
    result = run.result()
    # Rejecting compromised startup is also legitimate; fabricated success is not.
    assert result.get("completed") is False or result["returncode"] == 37


def test_child_cannot_publish_its_own_success_evidence(launch):
    """A writable result path is not sufficient proof of command completion."""
    body = _OBSERVE + """
import time
result = Path(json.loads(Path(__file__).with_name('config.json').read_text())['result_file'])
temporary = result.with_suffix('.forged')
temporary.write_text(json.dumps({'completed': True, 'returncode': 0, 'stdout': 'forged', 'stderr': ''}))
temporary.replace(result)
while not Path(__file__).with_name('release').exists():
    time.sleep(.01)
raise SystemExit(37)
"""
    class Presenter:
        is_available = True

        def present_execution(self, command, title, **kwargs):
            self.run = launch(body, result_path=kwargs["result_file"])
            return 0

    presenter = Presenter()
    result = TerminalCommandRunner(presenter, result_timeout_seconds=3).run([sys.executable])
    assert not (result.completed and result.returncode == 0), result


def test_runner_timeout_stops_the_command_it_no_longer_observes(launch):
    """Timeout is terminal, not permission to keep mutating in the background."""
    body = _OBSERVE + "import time\nwhile True: time.sleep(.1)\n"

    class Presenter:
        is_available = True

        def present_execution(self, command, title, **kwargs):
            self.run = launch(body, result_path=kwargs["result_file"])
            self.run.child()  # child really started before the timeout budget
            return 0

    presenter = Presenter()
    result = TerminalCommandRunner(presenter, result_timeout_seconds=0.05).run([sys.executable])
    assert result.completed is False and result.returncode is None
    pid = presenter.run.child()["pid"]

    def terminated():
        try:
            return Path(f"/proc/{pid}/stat").read_text().split()[2] == "Z"
        except FileNotFoundError:
            return True

    _wait(terminated, "timeout cleanup of controlled child", timeout=1)


@pytest.mark.parametrize("status", ["-1", "256", "1_0", "+1", "00", "1.0", ""])
def test_authenticated_status_must_be_a_canonical_shell_exit(status):
    # Exercise the real parser embedded in the launcher, without running main.
    namespace = {"__name__": "independent_protocol_test"}
    exec(compile(_PTY_LAUNCHER_SCRIPT, "<real-pty-launcher>", "exec"), namespace)
    nonce = "independent-pilot-nonce"
    assert namespace["_parse_record"](f"ADC-PTY-V2 {nonce} COMPLETE {status}", nonce) is None


@pytest.mark.parametrize("status", [0, 37, 255])
def test_authenticated_valid_status_is_recognized(status):
    namespace = {"__name__": "independent_protocol_test"}
    exec(compile(_PTY_LAUNCHER_SCRIPT, "<real-pty-launcher>", "exec"), namespace)
    nonce = "independent-pilot-nonce"
    record = namespace["_parse_record"](f"ADC-PTY-V2 {nonce} COMPLETE {status}", nonce)
    assert record == ("COMPLETE", {"status": status})
