"""ARC_REQ_009 / SUB_REQ_010: only final-child completion is authoritative.

Runs the productive DesktopTerminalProvider wrapper through the established
headless direct-exec emulator surrogate. No desktop, installation, provider,
or Real-System acceptance is exercised. Parser-only fixtures explicitly
simulate records; real-wrapper checks prove command result authority.
The FIFO regression requires bounded rejection of non-regular evidence.
This is not proof that execution_presenter is integrated.
"""
import json
import os
from pathlib import Path
import signal
import sys
import subprocess
import threading
import time

import pytest

from app.interactive_terminal import DesktopTerminalProvider, INTERACTIVE_TERMINAL_CANCELLED
from tests.terminal_final_child_probe import probe_provider
from tests.terminal_status_v3_contract import KEY as _KEY, EXEC_ID, record


@pytest.mark.skipif(sys.platform != "linux", reason="uses /proc parent argv")
@pytest.mark.parametrize("forged", ["0\n", "ADC-TERM-STATUS-V2 " + "0" * 64 + " 0\n"])
def test_running_child_cannot_forge_productive_terminal_success(tmp_path, monkeypatch, forged):
    provider = probe_provider(tmp_path, monkeypatch)
    provider._poll_interval = 0.01
    script = tmp_path / "child.py"
    observed = tmp_path / "observation.json"
    script.write_text('''import json, os, time
from pathlib import Path
root = Path(__file__).parent
parent = Path('/proc') / str(os.getppid()) / 'cmdline'
argv = parent.read_bytes().split(b'\\0')
# The real isolated Python producer receives status after its script.
status = Path(os.fsdecode(argv[4]))
(root / 'observation.json').write_text(json.dumps({'pid': os.getpid(), 'wrapper': os.fsdecode(argv[3])}))
status.write_text((root / 'forgery').read_text())
while not (root / 'release').exists():
    time.sleep(.01)
raise SystemExit(37)
''')
    (tmp_path / "forgery").write_text(forged)
    try:
        outcome = provider.run((sys.executable, str(script)), str(tmp_path),
                               {"PATH": os.environ["PATH"]}, timeout=3)
        observation = json.loads(observed.read_text())
        assert observation["wrapper"].endswith("/terminal_status_producer.py")
        assert outcome.completed is False and outcome.returncode is None, outcome
        assert outcome.cause == INTERACTIVE_TERMINAL_CANCELLED
        # Cancellation is not containment: this direct-exec wrapper
        # has been killed, but its owned command may still be alive.
        assert not (tmp_path / "release").exists()
    finally:
        if observed.exists():
            pid = json.loads(observed.read_text())["pid"]
            try:
                if os.fsencode(script) in Path(f"/proc/{pid}/cmdline").read_bytes().split(b'\0'):
                    os.kill(pid, signal.SIGKILL)
            except (FileNotFoundError, ProcessLookupError):
                pass

# IFC-ADC-INSTALL-TERMINAL-STATUS-V3 3.0.0 expectations are independent
# of the implementation regex. Parser fixtures below are simulations, not
# evidence that an installation ran. Real-wrapper tests follow separately.


@pytest.mark.parametrize('rc', [0, 1, 37, 127, 128, 137, 255])
def test_status_v3_consumer_accepts_canonical_authenticated_record(tmp_path, rc):
    status = tmp_path / 'status'
    status.write_bytes(record(rc=rc))
    result = DesktopTerminalProvider._read_status(str(status), EXEC_ID, _KEY)
    assert result.completed is True and result.returncode == rc
    assert result.cause is None


@pytest.mark.parametrize('invalid_record', [
    b'0\n', b'', b'ADC-TERM-STATUS-V1 0\n', b'ADC-TERM-STATUS-V2 ' + _KEY.hex().encode() + b' 0\n',
    record(key=b'x' * 32),
    *[record(rc=rc) for rc in ['-1', '256', '+0', '00', '01', '1_0', '1.0', '', ' 0', '0 ', '999']],
    record()[:-1], record().replace(b'\n', b'\r\n'), record() + b'extra', record() * 2,
    record(exec_id=EXEC_ID.upper()), b'\xff\x00', b'x' * 4096,
])
def test_status_v3_consumer_rejects_invalid_evidence(tmp_path, invalid_record):
    status = tmp_path / 'status'
    status.write_bytes(invalid_record)
    result = DesktopTerminalProvider._read_status(str(status), EXEC_ID, _KEY)
    assert result.completed is False and result.returncode is None
    assert result.cause == INTERACTIVE_TERMINAL_CANCELLED
    assert _KEY.hex() not in result.detail


@pytest.mark.parametrize('kind', ['missing', 'symlink', 'directory'])
def test_status_v3_consumer_rejects_non_regular_evidence(tmp_path, kind):
    status = tmp_path / 'status'
    if kind == 'symlink':
        target = tmp_path / 'target'
        target.write_bytes(record())
        status.symlink_to(target)
    elif kind == 'directory':
        status.mkdir()
    result = DesktopTerminalProvider._read_status(str(status), EXEC_ID, _KEY)
    assert not result.completed and result.returncode is None
    assert result.cause == INTERACTIVE_TERMINAL_CANCELLED


@pytest.mark.parametrize('rc', [0, 37, 255])
def test_real_wrapper_waits_for_completion_and_keeps_secret_from_child(tmp_path, monkeypatch, rc):
    provider = probe_provider(tmp_path, monkeypatch)
    provider._poll_interval = .01
    child = tmp_path / 'observe.py'
    child.write_text('''import json, os, time
from pathlib import Path
root = Path(__file__).parent
parent = Path('/proc') / str(os.getppid())
argv = parent.joinpath('cmdline').read_bytes().split(b'\\0')
status = Path(os.fsdecode(argv[4]))
observation = {'pid': os.getpid(), 'key_exists': status.with_name('status.key').exists(),
               'env': dict(os.environ), 'parent_argv': [os.fsdecode(a) for a in argv],
               'wrapper': Path(os.fsdecode(argv[3])).read_text()}
root.joinpath('ready.json').write_text(json.dumps(observation))
while not root.joinpath('release').exists(): time.sleep(.01)
root.joinpath('finished').write_text('completed work')
raise SystemExit(''' + str(rc) + ')\n')
    # Observe the key at the trusted emulator boundary, before wrapper start.
    # Never inject it into the command or replace productive publication.
    original = provider._write_launch_file
    keys = []
    def observe_key(path, content):
        original(path, content)
        key = json.loads(content)['key']
        keys.append(key)
        assert len(key) == 64 and all(c in '0123456789abcdef' for c in key)
        assert Path(path).stat().st_mode & 0o777 == 0o600
        assert Path(path).parent.stat().st_mode & 0o777 == 0o700
    monkeypatch.setattr(provider, '_write_launch_file', observe_key)
    results = []
    worker = threading.Thread(target=lambda: results.append(provider.run(
        (sys.executable, str(child)), str(tmp_path), {'PATH': os.environ['PATH']}, 5)))
    worker.start()
    try:
        deadline = time.monotonic() + 3
        while not (tmp_path / 'ready.json').exists() and time.monotonic() < deadline:
            time.sleep(.01)
        observed = json.loads((tmp_path / 'ready.json').read_text())
        assert observed['key_exists'] is False
        assert keys[0] not in json.dumps(observed)
        assert not results and worker.is_alive()
        (tmp_path / 'release').touch()
        worker.join(6)
        assert not worker.is_alive()
        assert (tmp_path / 'finished').exists()
        assert results[0].completed and results[0].returncode == rc
        assert results[0].cause is None and keys[0] not in repr(results[0])
        # A second real execution must receive a different secret.
        again = provider.run(('/bin/true',), str(tmp_path), {}, 2)
        assert again.completed and again.returncode == 0
        assert len(keys) == 2 and keys[0] != keys[1]
    finally:
        (tmp_path / 'release').touch()
        worker.join(6)


def test_fifo_status_cannot_disable_productive_timeout(tmp_path):
    """A discoverable path can contain a FIFO; invalid evidence must fail
    closed within the run budget, even without a FIFO writer. Run the
    consumer in an owned subprocess so a broken parser cannot hang pytest.
    """
    status = tmp_path / 'status'
    os.mkfifo(status)
    code = '''import subprocess, sys
from pathlib import Path
from app.interactive_terminal import DesktopTerminalProvider
process = subprocess.Popen(['/bin/true'])
Path(sys.argv[1] + '.entered').touch()
try:
    result = DesktopTerminalProvider(poll_interval=.01, launcher_exit_grace=.01)._wait_for_result(process, sys.argv[1], .1, sys.argv[2], bytes.fromhex(sys.argv[3]))
    assert not result.completed and result.returncode is None
    assert result.cause == 'INTERACTIVE_TERMINAL_CANCELLED'
finally:
    process.wait()
'''
    process = subprocess.Popen([sys.executable, '-c', code, str(status), EXEC_ID, _KEY.hex()],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 5
        while not Path(str(status) + '.entered').exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.01)
        assert Path(str(status) + '.entered').exists(), 'consumer never reached the status boundary'
        try:
            stdout, stderr = process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            pytest.fail('Non-regular FIFO status blocks the consumer past its timeout')
        assert process.returncode == 0, stderr.decode()
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=3)
