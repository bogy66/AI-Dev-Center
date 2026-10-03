"""Independent IFC-ADC-INSTALL-TERMINAL-STATUS-V3 3.0.0 regressions.

Authority: approved contract in task 005; ARC_REQ_009 / ARC_REQ_025 /
SUB_REQ_010 / SUB_REQ_032. Consumer fixtures use a separate MAC oracle.
Productive cases run the actual producer and consumer with a GUI-free
direct-exec terminal. They prove neither a desktop nor tree containment.
"""
import hashlib
import hmac
import json
import os
from pathlib import Path
import signal
import shlex
import sys

import pytest

from app.interactive_terminal import (
    DesktopTerminalProvider, INTERACTIVE_TERMINAL_CANCELLED,
    INTERACTIVE_TERMINAL_LAUNCH_FAILED,
)
from tests.terminal_final_child_probe import probe_provider
from tests.terminal_status_v3_contract import KEY, EXEC_ID, record


def consume(tmp_path, raw, exec_id=EXEC_ID, key=KEY):
    path = tmp_path / 'status'
    path.write_bytes(raw)
    return DesktopTerminalProvider._read_status(str(path), exec_id, key)


@pytest.mark.parametrize('raw', [
    record(exec_id='c3' * 16),
    record(outcome='NOT_STARTED', rc='-').replace(b'NOT_STARTED -', b'EXITED 0'),
    record(rc=37).replace(b'EXITED 37', b'EXITED 0'),
    record().replace(b'EXITED 0', b'EXITED 37'),
    record().replace(EXEC_ID.encode(), b'c3' * 16),
    record().replace(b'EXITED 0', b'NOT_STARTED -'),
    record(outcome='NOT_STARTED', rc='0'),
    record(outcome='EXITED', rc='-'),
    record(outcome='STOPPED', rc='0'),
    record(outcome='exited', rc='0'),
    record(exec_id='a' * 31), record(exec_id='a' * 33),
    record()[:-65] + record()[-65:-1].upper() + b'\n',
    record() + b'\0', b' ' + record(), record().replace(b' ', b'  ', 1),
    record() + b' ' * (256 - len(record())),
    record() + b' ' * (257 - len(record())),
])
def test_tampered_or_noncanonical_record_never_authorizes_completion(tmp_path, raw):
    result = consume(tmp_path, raw)
    assert not result.completed and result.returncode is None
    assert result.cause == INTERACTIVE_TERMINAL_CANCELLED
    assert KEY.hex() not in repr(result)


@pytest.mark.parametrize('domain', [b'', b'ADC-TERM-STATUS-V2\0', b'ADC-TERM-STATUS-V3'])
def test_mac_domain_separator_is_mandatory(tmp_path, domain):
    message = domain + EXEC_ID.encode() + b'\0EXITED\0' + b'0'
    tag = hmac.new(KEY, message, hashlib.sha256).hexdigest()
    raw = f'ADC-TERM-STATUS-V3 {EXEC_ID} EXITED 0 {tag}\n'.encode()
    assert consume(tmp_path, raw).cause == INTERACTIVE_TERMINAL_CANCELLED


def test_valid_not_started_is_launch_failure_not_completion(tmp_path):
    result = consume(tmp_path, record(outcome='NOT_STARTED', rc='-'))
    assert not result.completed and result.returncode is None
    assert result.cause == INTERACTIVE_TERMINAL_LAUNCH_FAILED


@pytest.mark.parametrize('foreign', [False, True])
def test_authentication_uses_constant_time_comparison_even_for_foreign_identity(tmp_path, monkeypatch, foreign):
    original = hmac.compare_digest
    comparisons = []
    def compare(left, right):
        comparisons.append((left, right))
        return original(left, right)
    monkeypatch.setattr(hmac, 'compare_digest', compare)
    raw = record(exec_id='c3' * 16) if foreign else record()
    result = consume(tmp_path, raw)
    assert result.completed is (not foreign)
    assert any(len(left) == len(right) == 64 for left, right in comparisons)


def observe_launch_and_publication(provider, monkeypatch):
    """Observe trusted test boundaries; neither replace nor sign evidence."""
    launches, published = [], []
    writer, reader = provider._write_launch_file, provider._read_status
    def write(path, content):
        writer(path, content)
        launch = json.loads(content)
        assert Path(path).stat().st_mode & 0o777 == 0o600
        assert Path(path).parent.stat().st_mode & 0o777 == 0o700
        assert len(launch['exec_id']) == 32 and set(launch['exec_id']) <= set('0123456789abcdef')
        assert len(launch['key']) == 64 and set(launch['key']) <= set('0123456789abcdef')
        launches.append(launch)
    def read(path, exec_id, key):
        raw = Path(path).read_bytes()
        published.append(raw)
        assert key.hex().encode() not in raw and key not in raw
        assert len(raw) <= 256
        assert not Path(path).with_name('status.key').exists()
        return reader(path, exec_id, key)
    monkeypatch.setattr(provider, '_write_launch_file', write)
    monkeypatch.setattr(provider, '_read_status', read)
    return launches, published


@pytest.mark.parametrize('rc', [0, 37, 126, 127, 255])
def test_real_producer_mac_and_exit_status_match_independent_contract(tmp_path, monkeypatch, rc):
    provider = probe_provider(tmp_path, monkeypatch)
    launches, published = observe_launch_and_publication(provider, monkeypatch)
    result = provider.run((sys.executable, '-c', f'raise SystemExit({rc})'), str(tmp_path), {}, 5)
    assert result.completed and result.returncode == rc and result.cause is None
    launch = launches[0]
    assert published == [record(bytes.fromhex(launch['key']), launch['exec_id'], rc=rc)]


@pytest.mark.parametrize('sig', [signal.SIGTERM, signal.SIGKILL, signal.SIGINT])
def test_real_signalled_child_is_exited_not_not_started(tmp_path, monkeypatch, sig):
    provider = probe_provider(tmp_path, monkeypatch)
    launches, published = observe_launch_and_publication(provider, monkeypatch)
    result = provider.run((sys.executable, '-c', f'import os;os.kill(os.getpid(),{sig})'), str(tmp_path), {}, 5)
    assert result.completed and result.returncode == 128 + sig
    assert published == [record(bytes.fromhex(launches[0]['key']), launches[0]['exec_id'], rc=128 + sig)]


@pytest.mark.parametrize('kind', ['missing', 'not_executable', 'exec_format', 'directory'])
def test_real_command_start_failure_is_authenticated_not_started(tmp_path, monkeypatch, kind):
    provider = probe_provider(tmp_path, monkeypatch)
    launches, published = observe_launch_and_publication(provider, monkeypatch)
    executable = tmp_path / 'command'
    if kind == 'directory':
        executable.mkdir()
    elif kind in ('not_executable', 'exec_format'):
        executable.write_text('this is not an executable image\n')
        executable.chmod(0o700 if kind == 'exec_format' else 0o600)
    argv = (str(executable),)
    result = provider.run(argv, str(tmp_path), {}, 5)
    assert not result.completed and result.returncode is None
    assert result.cause == INTERACTIVE_TERMINAL_LAUNCH_FAILED
    assert published == [record(bytes.fromhex(launches[0]['key']), launches[0]['exec_id'], 'NOT_STARTED', '-')]


def test_real_execution_ids_keys_and_records_cannot_be_replayed(tmp_path, monkeypatch):
    provider = probe_provider(tmp_path, monkeypatch)
    launches, published = observe_launch_and_publication(provider, monkeypatch)
    for rc in (0, 37):
        result = provider.run((sys.executable, '-c', f'raise SystemExit({rc})'), str(tmp_path), {}, 5)
        assert result.completed and result.returncode == rc
    first, second = launches
    assert first['exec_id'] != second['exec_id'] and first['key'] != second['key']
    # Actual old producer record presented to the new consumer context.
    result = consume(tmp_path, published[0], second['exec_id'], bytes.fromhex(second['key']))
    assert not result.completed and result.returncode is None
    assert result.cause == INTERACTIVE_TERMINAL_CANCELLED


@pytest.mark.parametrize('fault', ['missing', 'corrupt', 'fifo', 'symlink'])
def test_invalid_launch_material_never_starts_command(tmp_path, monkeypatch, fault):
    provider = probe_provider(tmp_path, monkeypatch)
    provider._launcher_exit_grace = .01
    provider._poll_interval = .01
    original = provider._write_launch_file
    paths = []
    def damage(path, content):
        original(path, content)
        path = Path(path)
        paths.append(path)
        path.unlink()
        if fault == 'corrupt':
            path.write_bytes(b'{invalid')
        elif fault == 'fifo':
            os.mkfifo(path)
        elif fault == 'symlink':
            target = tmp_path / 'launch-target'
            target.write_bytes(content)
            path.symlink_to(target)
    monkeypatch.setattr(provider, '_write_launch_file', damage)
    marker = tmp_path / 'command-started'
    result = provider.run((sys.executable, '-c', f'open({str(marker)!r},"w").close()'), str(tmp_path), {}, 2)
    assert not result.completed and result.returncode is None
    assert not marker.exists() and not paths[0].parent.exists()


@pytest.mark.parametrize('kind', ['fifo', 'directory', 'symlink'])
def test_child_preplanted_publication_artifact_cannot_disable_timeout(tmp_path, monkeypatch, kind):
    provider = probe_provider(tmp_path, monkeypatch)
    provider._poll_interval = .01
    provider._launcher_exit_grace = .01
    marker = tmp_path / 'command-did-run'
    script = '''import os
from pathlib import Path
argv = Path('/proc', str(os.getppid()), 'cmdline').read_bytes().split(b'\\0')
status = Path(os.fsdecode(argv[4]) + '.tmp')
'''
    script += {'fifo': 'os.mkfifo(status)\n', 'directory': 'status.mkdir()\n',
               'symlink': "status.symlink_to('/dev/null')\n"}[kind]
    script += f'Path({str(marker)!r}).touch()\n'
    result = provider.run((sys.executable, '-c', script), str(tmp_path), {}, 2)
    assert marker.exists()
    assert not result.completed and result.returncode is None
    assert result.cause == INTERACTIVE_TERMINAL_CANCELLED


def test_secret_is_absent_from_child_views_and_terminal_output(tmp_path, monkeypatch):
    # Output belongs to this terminal fixture, never to ADC's provider.
    terminal = tmp_path / 'terminal'
    stdout, stderr = tmp_path / 'terminal.stdout', tmp_path / 'terminal.stderr'
    terminal.write_text('#!/bin/sh\nexec "$@" > ' + shlex.quote(str(stdout))
                        + ' 2> ' + shlex.quote(str(stderr)) + '\n')
    terminal.chmod(0o700)
    provider = DesktopTerminalProvider(candidates=((str(terminal), ()),))
    launches, published = observe_launch_and_publication(provider, monkeypatch)
    script = '''import json, os, sys
from pathlib import Path
parent = Path('/proc', str(os.getppid()))
argv = parent.joinpath('cmdline').read_bytes().split(b'\\0')
status = Path(os.fsdecode(argv[4]))
assert not status.with_name('status.key').exists()
print(json.dumps({'argv': sys.argv, 'env': dict(os.environ),
    'parent_argv': os.fsdecode(parent.joinpath('cmdline').read_bytes()),
    'parent_env': os.fsdecode(parent.joinpath('environ').read_bytes()),
    'fds': [os.readlink(p) for p in Path('/proc/self/fd').iterdir() if p.exists()]}))
print('child-stderr', file=sys.stderr)
'''
    result = provider.run((sys.executable, '-c', script), str(tmp_path), {'ONLY_CONTROLLED': 'value'}, 5)
    assert result.completed and result.returncode == 0
    views = json.loads(stdout.read_text())
    assert views['env']['ONLY_CONTROLLED'] == 'value'
    assert not any('status.key' in fd for fd in views['fds'])
    assert launches[0]['key'].encode() not in stdout.read_bytes() + stderr.read_bytes() + published[0]
    assert bytes.fromhex(launches[0]['key']) not in stdout.read_bytes() + stderr.read_bytes() + published[0]


@pytest.mark.parametrize('sig', [signal.SIGINT, signal.SIGTERM])
def test_producer_termination_cannot_become_child_completion(tmp_path, monkeypatch, sig):
    provider = probe_provider(tmp_path, monkeypatch)
    provider._poll_interval = .01
    provider._launcher_exit_grace = .1
    marker = tmp_path / 'child-continued'
    script = f'''import os, time
from pathlib import Path
os.kill(os.getppid(), {sig})
Path({str(marker)!r}).touch()
raise SystemExit(37)
'''
    result = provider.run((sys.executable, '-c', script), str(tmp_path), {}, 3)
    assert marker.exists()
    assert not result.completed and result.returncode is None
    assert result.cause == INTERACTIVE_TERMINAL_CANCELLED
