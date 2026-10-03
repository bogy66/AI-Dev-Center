"""Independent adversarial regressions from task 004, migrated to V3 in 005.

ARC_REQ_009 / SUB_REQ_010 / SUB_REQ_032 require the actual command's
exit status. Descendant containment is not required by these tests.
The direct-exec emulator runs the genuine productive wrapper; delaying
the consumer models scheduling, never substitutes completion evidence.
"""
import json
import multiprocessing
import os
from pathlib import Path
import signal
import socket
import sys
import time
from unittest.mock import patch

import pytest

from app.interactive_terminal import DesktopTerminalProvider
from tests.terminal_final_child_probe import probe_provider
from tests.terminal_status_v3_contract import KEY, EXEC_ID, record

pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='Linux filesystem and /proc contract')


def _consume_status_replacement(directory, replacement):
    tmp_path = Path(directory)
    status = tmp_path / 'status'
    key = KEY
    encoded = record()
    status.write_bytes(encoded)
    target = tmp_path / 'target'
    target.write_bytes(encoded)
    original_open = os.open
    endpoint = None

    def replace_then_open(path, flags, *args, **kwargs):
        nonlocal endpoint
        if str(path) == str(status):
            # Keep the original inode allocated to prevent inode reuse.
            status.rename(tmp_path / 'old-status')
            if replacement == 'fifo':
                os.mkfifo(status)
            elif replacement == 'symlink':
                status.symlink_to(target)
            elif replacement == 'directory':
                status.mkdir()
            elif replacement == 'socket':
                endpoint = socket.socket(socket.AF_UNIX)
                endpoint.bind(str(status))
            else:
                status.write_bytes(encoded)
        return original_open(path, flags, *args, **kwargs)

    try:
        with patch.object(os, 'open', replace_then_open):
            result = DesktopTerminalProvider._read_status(str(status), EXEC_ID, key)
        assert not result.completed and result.returncode is None
        assert result.cause == 'INTERACTIVE_TERMINAL_CANCELLED'
    finally:
        if endpoint is not None:
            endpoint.close()


@pytest.mark.parametrize('replacement', ['fifo', 'symlink', 'directory', 'socket', 'regular'])
def test_status_replacement_between_inspection_and_open_is_rejected(tmp_path, replacement):
    # An older blocking reader must fail without hanging the test session.
    consumer = multiprocessing.get_context('spawn').Process(
        target=_consume_status_replacement, args=(str(tmp_path), replacement))
    consumer.start()
    try:
        consumer.join(5)
        assert not consumer.is_alive(), 'status replacement blocked the consumer'
        assert consumer.exitcode == 0
    finally:
        if consumer.is_alive():
            consumer.kill()
        consumer.join(5)


@pytest.mark.parametrize('real_rc,forged_rc', [(37, 0), (0, 37)])
def test_descendant_cannot_rewrite_published_real_child_result(tmp_path, monkeypatch, real_rc, forged_rc):
    """A descendant reads and alters actual published completion evidence.

    No ptrace, access to status.key, trusted-boundary secret injection,
    or fabricated producer is used. The reader yields until the owned
    descendant has rewritten the rc while preserving the tag, modeling
    a descheduled ADC.
    Authentication must reject tampering or preserve the true result.
    """
    provider = probe_provider(tmp_path, monkeypatch)
    provider._poll_interval = .01
    child = tmp_path / 'child.py'
    ready = tmp_path / 'descendant.json'
    changed = tmp_path / 'changed.json'
    child.write_text('''import json, os, subprocess, sys, time
from pathlib import Path
root = Path(__file__).parent
if len(sys.argv) == 1:
    argv = Path('/proc', str(os.getppid()), 'cmdline').read_bytes().split(b'\\0')
    status = os.fsdecode(argv[4])
    subprocess.Popen([sys.executable, __file__, status],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 3
    while not (root / 'descendant.json').exists():
        if time.monotonic() > deadline: raise SystemExit(98)
        time.sleep(.001)
    raise SystemExit(''' + str(real_rc) + ''')
status = Path(sys.argv[1])
(root / 'descendant.json').write_text(json.dumps({'pid': os.getpid(),
    'key_file_exists': status.with_name('status.key').exists()}))
deadline = time.monotonic() + 4
while time.monotonic() < deadline:
    try:
        original = status.read_text()
    except FileNotFoundError:
        time.sleep(.001)
        continue
    parts = original.split()
    if len(parts) != 5:
        time.sleep(.001)
        continue
    status.write_text(' '.join(parts[:3]) + ' ''' + str(forged_rc) + ''' ' + parts[4] + '\\n')
    (root / 'changed.tmp').write_text(json.dumps({'original_rc': int(parts[3])}))
    (root / 'changed.tmp').rename(root / 'changed.json')
    break
''')
    original_reader = provider._read_status

    def scheduled_reader(path, exec_id, key):
        deadline = time.monotonic() + 5
        while not changed.exists() and time.monotonic() < deadline:
            time.sleep(.005)
        assert changed.exists(), 'descendant did not reach publication boundary'
        return original_reader(path, exec_id, key)

    monkeypatch.setattr(provider, '_read_status', scheduled_reader)
    try:
        result = provider.run((sys.executable, str(child)), str(tmp_path),
                              {'PATH': os.environ['PATH']}, timeout=8)
        assert json.loads(ready.read_text())['key_file_exists'] is False
        assert json.loads(changed.read_text())['original_rc'] == real_rc
        assert (not result.completed and result.returncode is None) or (
            result.completed and result.returncode == real_rc), result
    finally:
        if ready.exists():
            pid = json.loads(ready.read_text())['pid']
            try:
                if os.fsencode(child) in Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0'):
                    os.kill(pid, signal.SIGKILL)
            except (FileNotFoundError, ProcessLookupError):
                pass
