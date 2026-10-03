"""Deterministic, GUI-free surrogate for the real DesktopTerminalProvider
external boundary, used to inspect the FINAL CHILD process a controlled
software installation actually spawns -- not merely the arguments passed
INTO InteractiveTerminalLauncher/DesktopTerminalProvider.run().

(KIB-ADC-CAPABILITY-AUTH-TERMINAL-BOUNDARY-TC-FIX-001, section 3/7B:
"validate observable semantics at the FINAL CHILD, not merely at an
upstream launcher/mock boundary.")

app.interactive_terminal.DesktopTerminalProvider's own candidate list is
deliberately a CONSTRUCTOR PARAMETER (not a hardcoded internal constant),
specifically so the SAME real DesktopTerminalProvider machinery -- binary
discovery via shutil.which(), the real wrapper-script/status-file exit
-code mechanism, the real subprocess.Popen call -- can be exercised end
to end with one harmless, deterministic, always-available "terminal
emulator" substituted for a real GUI program.

FAKE_TERMINAL_SCRIPT is intentionally the simplest possible faithful
surrogate for a DIRECT-EXEC terminal emulator (the xterm/konsole/
x-terminal-emulator "-e" family): `exec "$@"`, replacing its own process
image with its argv, inheriting exactly the cwd/env it was itself
launched with. Empirically verified (this module's own prototyping) to
correctly propagate cwd, argv (including spaces and shell
metacharacters, via the producer's direct argv forwarding), and exit code
through the real InteractiveTerminalLauncher -> DesktopTerminalProvider
-> subprocess.Popen -> trusted Python producer -> wrapped-command chain.

What this surrogate deliberately does NOT prove: any one SPECIFIC real
terminal emulator binary -- especially a client/server one like
gnome-terminal, the first, default candidate in production -- actually
honors subprocess.Popen(cwd=..., env=...) the same way a freshly
Popen'd direct-exec process does. A client/server terminal's real shell
is commonly spawned by an already-running server process that may not
inherit the short-lived launching client's own cwd/env at all. That
remains Real-System/provider-certification territory (see
tests/test_interactive_terminal.py's own REAL_GUI_PROVIDER_CERTIFIED
note) this deterministic surrogate cannot reach and does not claim to.
"""
from __future__ import annotations

import json
import os
import shlex
import stat
import sys
from pathlib import Path

from app.interactive_terminal import DesktopTerminalProvider
from tests.terminal_status_v3_contract import SIMULATED_STATUS_PY as _SIMULATED_STATUS_PY
from app.python_distribution import (
    DISTRIBUTION_VERDICT_ABSENT,
    DISTRIBUTION_VERDICT_PRESENT,
    distribution_query_verdict_line,
)

_PRESENT_LINE = distribution_query_verdict_line(DISTRIBUTION_VERDICT_PRESENT, "0.0.1")
_ABSENT_LINE = distribution_query_verdict_line(DISTRIBUTION_VERDICT_ABSENT)

# Consumer-only simulation for INERT argv/count/provider-shape fixtures.
# These fixtures deliberately do not execute an installation. They possess
# the pre-command key as the trusted emulator fixture, and manufacture a
# protocol response; their PASS is NOT evidence of productive completion.
_SIMULATED_STATUS_SH = (
    shlex.quote(sys.executable) + ' -I -S -c '
    + shlex.quote('import sys\nstatus_path = sys.argv[1]\n' + _SIMULATED_STATUS_PY)
    + ' "$status_path"\n'
)

FAKE_TERMINAL_SCRIPT = "#!/bin/sh\nexec \"$@\"\n"

PROBE_SCRIPT = (
    "import json, os, sys\n"
    "out_path = sys.argv[1]\n"
    "exit_code = int(sys.argv[2])\n"
    "payload = {\"argv\": sys.argv[3:], \"cwd\": os.getcwd(), \"env\": dict(os.environ)}\n"
    "with open(out_path, \"w\", encoding=\"utf-8\") as f:\n"
    "    json.dump(payload, f)\n"
    "sys.exit(exit_code)\n"
)


def install_fake_terminal(tmp_path: Path, name: str = "adc-fake-terminal") -> tuple[Path, tuple]:
    """Writes a direct-exec fake terminal-emulator script under tmp_path
    and returns (script_path, candidates) -- candidates is a
    ready-to-use DesktopTerminalProvider(candidates=...) tuple naming
    this script with an empty flag prefix (this surrogate defines its
    own trivial calling convention rather than emulating one specific
    real terminal's flags)."""
    scripts_dir = tmp_path / "fake-terminal-bin"
    scripts_dir.mkdir(exist_ok=True)
    script_path = scripts_dir / name
    script_path.write_text(FAKE_TERMINAL_SCRIPT)
    script_path.chmod(
        script_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH
    )
    return script_path, ((str(script_path), ()),)


def probe_provider(tmp_path: Path, monkeypatch, name: str = "adc-fake-terminal") -> DesktopTerminalProvider:
    """A real DesktopTerminalProvider wired to the fake terminal script,
    with the script's own directory prepended to PATH so shutil.which()
    -- exactly as production _select_binary() calls it -- finds it."""
    script_path, candidates = install_fake_terminal(tmp_path, name)
    monkeypatch.setenv(
        "PATH", f"{script_path.parent}{os.pathsep}{os.environ.get('PATH', '')}",
    )
    return DesktopTerminalProvider(candidates=candidates)


def write_final_child_probe(tmp_path: Path) -> Path:
    """A tiny, real Python script standing in for "the wrapped
    command": dumps its OWN real argv/cwd/env -- exactly as the OS gave
    them to it, never as constructed by any caller -- to a JSON file and
    exits with a caller-chosen exit code. This is the one thing that
    proves what the FINAL CHILD process actually received, independent
    of any upstream mock or spy."""
    path = tmp_path / "final_child_probe.py"
    path.write_text(PROBE_SCRIPT)
    return path


def build_probe_argv(
    probe_script: Path, out_path: Path, exit_code: int, *extra_args: str,
) -> tuple[str, ...]:
    return (sys.executable, str(probe_script), str(out_path), str(exit_code), *extra_args)


def read_final_child_result(out_path: Path) -> dict:
    with open(out_path, encoding="utf-8") as f:
        return json.load(f)


def install_inert_recording_terminal(
    tmp_path: Path, record_path: Path, name: str = "adc-inert-terminal",
) -> tuple[Path, tuple]:
    """Writes an INERT fake terminal-emulator script: it records the
    exact real wrapped argv it would otherwise have run (one argument
    per line, to `record_path`) and reports a synthetic success exit
    code, WITHOUT ever executing the wrapped command at all.

    (KIB-ADC-CAPABILITY-AUTH-TERMINAL-BOUNDARY-TC-CORRECTION-001: the
    prior FAKE_TERMINAL_SCRIPT/probe_provider surrogate above is a
    faithful DIRECT-EXEC terminal emulator -- it genuinely runs the
    wrapped command, which is exactly right for proving cwd/env/argv/
    exit-code fidelity, but is wrong for a test whose wrapped command is
    a real `<python> -m pip install <package>` invocation: that surrogate
    would genuinely install the package. This one instead intercepts and
    records the real command's argv -- proving DesktopTerminalProvider's
    own wrapper-script/status-file protocol threads the EXACT
    already-authorized argv all the way to the terminal boundary --
    without ever letting pip, or anything else, actually run.)

    DesktopTerminalProvider builds `full_argv = [binary, *prefix,
    python, "-I", "-S", producer_path, status_path, *argv]` and Popen's this
    terminal `binary` directly; with an empty prefix (the candidate
    tuple this function returns), the script below receives exactly
    [python, "-I", "-S", producer_path, status_path, *argv] as its own $1.. --
    `shift 4` drops the interpreter, isolation flags and producer,
    leaving $1=status_path and
    "$@" (after one more shift) as the real wrapped argv.
    """
    import shlex

    scripts_dir = tmp_path / "inert-terminal-bin"
    scripts_dir.mkdir(exist_ok=True)
    script_path = scripts_dir / name
    script_path.write_text(
        "#!/bin/sh\n"
        "shift 4\n"
        'status_path="$1"\n'
        "shift\n"
        f"record_path={shlex.quote(str(record_path))}\n"
        ': > "$record_path"\n'
        'for arg in "$@"; do\n'
        '    printf \'%s\\n\' "$arg" >> "$record_path"\n'
        "done\n"
        + _SIMULATED_STATUS_SH
    )
    script_path.chmod(
        script_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH
    )
    return script_path, ((str(script_path), ()),)


def inert_recording_provider(
    tmp_path: Path, monkeypatch, record_path: Path, name: str = "adc-inert-terminal",
) -> DesktopTerminalProvider:
    """A real DesktopTerminalProvider wired to the inert recording
    terminal script above -- the real wrapper-script/status-file
    consumer and the real subprocess.Popen call still run (the wrapper is
    bypassed by an explicit protocol simulation), but the
    wrapped command itself (e.g. a real `pip install`) is NEVER
    executed, only recorded."""
    script_path, candidates = install_inert_recording_terminal(tmp_path, record_path, name)
    monkeypatch.setenv(
        "PATH", f"{script_path.parent}{os.pathsep}{os.environ.get('PATH', '')}",
    )
    return DesktopTerminalProvider(candidates=candidates)


def read_recorded_argv(record_path: Path) -> list[str]:
    """The exact argv the inert recording terminal would otherwise have
    executed, one element per line as install_inert_recording_terminal
    wrote it."""
    if not record_path.exists():
        return []
    return record_path.read_text().splitlines()


def install_client_server_terminal(
    tmp_path: Path, name: str = "adc-client-server-terminal",
    server_cwd: str | None = None, server_env: dict[str, str] | None = None,
) -> tuple[Path, tuple]:
    """A CLIENT_SERVER_PROVIDER surrogate for a terminal emulator that
    hands off to an already-running server process (the real
    gnome-terminal/xfce4-terminal shape) -- structurally distinct from
    the DIRECT_PROCESS_PROVIDER surrogate (FAKE_TERMINAL_SCRIPT above),
    which always faithfully execs with the cwd/env Popen gave it.

    When `server_cwd`/`server_env` are omitted (None), this surrogate
    behaves like a WELL-BEHAVED client/server terminal that correctly
    forwards the client's own Popen(cwd=..., env=...) to the spawned
    child -- proving the compliant case is at least representable.

    When `server_cwd`/`server_env` ARE supplied, this surrogate
    deliberately IGNORES the cwd/env the client Popen call actually
    received and instead runs the wrapped command with these
    caller-supplied "stale server state" values instead -- exactly the
    real, structural risk a client/server terminal emulator poses (its
    spawned shell is owned by an already-running server process that
    may have started with, and kept, a different cwd/environment than
    any later client invocation's own Popen(cwd=, env=) arguments). A
    test using this shape is what lets "launcher environment differs
    from final child environment" become an OBSERVABLE, asserted
    condition instead of an unverified assumption.

    This is an explicit STATUS-V3 consumer simulation, not productive
    completion evidence. It never actually runs the wrapped command for real
    either way -- like install_inert_recording_terminal, it records
    the argv it WOULD have run (this time alongside the cwd/env it
    WOULD have used) and reports synthetic success, so no real process
    -- pip or otherwise -- ever executes.
    """
    import shlex

    scripts_dir = tmp_path / "client-server-terminal-bin"
    scripts_dir.mkdir(exist_ok=True)
    script_path = scripts_dir / name
    record_path = tmp_path / f"{name}-server-record.json"

    server_cwd_repr = repr(server_cwd) if server_cwd is not None else "None"
    server_env_repr = repr(server_env) if server_env is not None else "None"

    # A real, tiny Python "server-shaped" script: reads the client's
    # own Popen-supplied cwd/env from its OWN os.getcwd()/os.environ
    # (exactly what a direct-exec child would see), but then records
    # EITHER that real state (well-behaved server) OR the caller
    # -supplied override (divergent server) as "what the final child
    # would actually have received" -- the divergence itself, when
    # configured, is what a client/server terminal's own server-owned
    # process could structurally introduce.
    server_script = (
        "import json, os, sys\n"
        "status_path = sys.argv[5]\n"
        "real_argv = sys.argv[6:]\n"
        f"server_cwd = {server_cwd_repr}\n"
        f"server_env = {server_env_repr}\n"
        "final_cwd = server_cwd if server_cwd is not None else os.getcwd()\n"
        "final_env = server_env if server_env is not None else dict(os.environ)\n"
        "payload = {\"argv\": real_argv, \"launcher_cwd\": os.getcwd(), "
        "\"launcher_env\": dict(os.environ), \"final_child_cwd\": final_cwd, "
        "\"final_child_env\": final_env}\n"
        f"with open({str(record_path)!r}, 'w', encoding='utf-8') as f:\n"
        "    json.dump(payload, f)\n"
        + _SIMULATED_STATUS_PY
    )
    server_script_path = tmp_path / f"{name}-server.py"
    server_script_path.write_text(server_script)

    # The "client" binary DesktopTerminalProvider actually Popen's:
    # receives [python, -I, -S, producer_path, status_path, *argv] as its own
    # args (matching install_inert_recording_terminal's own contract),
    # and hands off to the real Python "server" script above, passing
    # its OWN argv straight through (the server itself decides,
    # per its own configuration, whether to honor or diverge from
    # the client's real cwd/env).
    script_path.write_text(
        "#!/bin/sh\n"
        f"exec {shlex.quote(sys.executable)} {shlex.quote(str(server_script_path))} "
        '"$@"\n'
    )
    script_path.chmod(
        script_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH
    )
    return script_path, ((str(script_path), ()),), record_path


def client_server_provider(
    tmp_path: Path, monkeypatch, name: str = "adc-client-server-terminal",
    server_cwd: str | None = None, server_env: dict[str, str] | None = None,
) -> tuple[DesktopTerminalProvider, Path]:
    """A real DesktopTerminalProvider wired to the CLIENT_SERVER_PROVIDER
    surrogate above. Returns (provider, record_path); read record_path
    with read_client_server_record()."""
    script_path, candidates, record_path = install_client_server_terminal(
        tmp_path, name, server_cwd=server_cwd, server_env=server_env,
    )
    monkeypatch.setenv(
        "PATH", f"{script_path.parent}{os.pathsep}{os.environ.get('PATH', '')}",
    )
    return DesktopTerminalProvider(candidates=candidates), record_path


def read_client_server_record(record_path: Path) -> dict:
    with open(record_path, encoding="utf-8") as f:
        return json.load(f)


def genuine_two_process_client_server_provider(
    tmp_path: Path, monkeypatch, *, server_cwd: Path, server_env: dict[str, str],
    mode: str = "normal", name: str = "adc-two-process-terminal",
) -> tuple[DesktopTerminalProvider, Path, object]:
    """Build a TEST-ONLY client/server terminal with two OS processes.

    The already-running Python server owns local FIFO IPC endpoints.  The
    provider's client process connects to it and asks it to launch the real
    DesktopTerminalProvider wrapper/status command.  The server intentionally
    uses its own cwd/environment, allowing tests to observe client/server
    divergence while the producer's explicit environment still controls the final child.
    This models process separation only; it is not a claim about any specific
    gnome-terminal implementation.
    """
    import shlex
    import subprocess
    import time

    scripts_dir = tmp_path / "two-process-terminal-bin"
    scripts_dir.mkdir(exist_ok=True)
    request_fifo = str(tmp_path / f"{name}.request.fifo")
    response_fifo = str(tmp_path / f"{name}.response.fifo")
    ready_path = str(tmp_path / f"{name}.ready")
    record_path = tmp_path / f"{name}-record.json"
    server_script = tmp_path / f"{name}-server.py"
    client_script = scripts_dir / f"{name}-client.py"
    server_env_repr = repr(dict(server_env))
    server_cwd_repr = repr(str(server_cwd))
    record_repr = repr(str(record_path))
    request_repr = repr(request_fifo)
    response_repr = repr(response_fifo)
    ready_repr = repr(ready_path)

    server_script.write_text(
        "import json, os, subprocess, sys\n"
        f"request_fifo = {request_repr}\n"
        f"response_fifo = {response_repr}\n"
        f"ready_path = {ready_repr}\n"
        f"record_path = {record_repr}\n"
        f"server_cwd = {server_cwd_repr}\n"
        f"server_env = {server_env_repr}\n"
        f"mode = {mode!r}\n"
        "os.mkfifo(request_fifo)\n"
        "os.mkfifo(response_fifo)\n"
        "open(ready_path, 'w', encoding='ascii').close()\n"
        "while True:\n"
        "    with open(request_fifo, 'r', encoding='utf-8') as request_file:\n"
        "        request = json.loads(request_file.readline())\n"
        "    if request.get('shutdown'):\n"
        "        break\n"
        "    if mode == 'early':\n"
        "        # Close a response writer so the client observes a clean\n"
        "        # provider-side early return instead of blocking forever.\n"
        "        with open(response_fifo, 'w', encoding='utf-8'):\n"
        "            pass\n"
        "        continue\n"
        "    command = request['command']\n"
        "    child = subprocess.Popen(command, cwd=server_cwd, env=server_env)\n"
        "    rc = child.wait()\n"
        "    payload = {'server_pid': os.getpid(), 'client_pid': request['client_pid'],\n"
        "               'launcher_cwd': request['launcher_cwd'],\n"
        "               'launcher_env': request['launcher_env'],\n"
        "               'server_cwd': server_cwd, 'server_env': server_env,\n"
        "               'returncode': rc}\n"
        "    with open(record_path, 'w', encoding='utf-8') as out:\n"
        "        json.dump(payload, out)\n"
        "    with open(response_fifo, 'w', encoding='utf-8') as response_file:\n"
        "        response_file.write(json.dumps({'returncode': rc}) + '\\n')\n"
    )
    client_script.write_text(
        "import json, os, sys\n"
        f"request_fifo = {request_repr}\n"
        f"response_fifo = {response_repr}\n"
        "command = sys.argv[1:]\n"
        "payload = {'command': command, 'client_pid': os.getpid(),\n"
        "           'launcher_cwd': os.getcwd(), 'launcher_env': dict(os.environ)}\n"
        "with open(request_fifo, 'w', encoding='utf-8') as request_file:\n"
        "    request_file.write(json.dumps(payload) + '\\n')\n"
        "with open(response_fifo, 'r', encoding='utf-8') as response_file:\n"
        "    response = response_file.readline()\n"
        "if response:\n"
        "    data = json.loads(response)\n"
        "    sys.exit(int(data.get('returncode', 1)))\n"
        "sys.exit(1)\n"
    )
    client = scripts_dir / name
    client.write_text(
        "#!/bin/sh\n"
        f"exec {shlex.quote(sys.executable)} {shlex.quote(str(client_script))} \"$@\"\n"
    )
    client.chmod(0o755)
    server_env_full = os.environ.copy()
    server_env_full.update(server_env)
    server_process = subprocess.Popen(
        [sys.executable, str(server_script)],
        cwd=str(server_cwd), env=server_env_full,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(100):
        if os.path.exists(ready_path):
            break
        time.sleep(0.01)
    else:
        server_process.kill()
        raise RuntimeError("two-process terminal server did not become ready")

    monkeypatch.setenv(
        "PATH", f"{scripts_dir}{os.pathsep}{os.environ.get('PATH', '')}",
    )
    provider = DesktopTerminalProvider(candidates=((str(client), ()),))

    def cleanup():
        if server_process.poll() is None:
            try:
                with open(request_fifo, "w", encoding="utf-8") as request_file:
                    request_file.write('{"shutdown": true}\n')
            except OSError:
                pass
            server_process.terminate()
        try:
            server_process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            server_process.kill()
            server_process.wait()

    return provider, record_path, cleanup


def install_provider_with_explicit_cwd_flag(
    tmp_path: Path, record_path: Path, name: str = "adc-explicit-cwd-terminal",
) -> tuple[Path, tuple]:
    """A PROVIDER_WITH_EXPLICIT_CWD surrogate: candidates carry an
    explicit `--working-directory=` -style flag (the real
    gnome-terminal remediation this task's own DEF-013A analysis
    recommended), and the script itself records ONLY that flag value as
    the cwd it would have honored, never its own real Popen-supplied
    os.getcwd() -- modeling a provider whose correctness does NOT
    depend on whether the underlying process model inherits cwd at
    all. A pure Python script (not POSIX sh) to keep argv[1]
    (`--working-directory=...`) parsing simple and unambiguous. The
    surrogate then executes the real wrapper in that directory; callers
    use only harmless commands."""
    record_path_repr = repr(str(record_path))
    script = (
        "import json, sys, subprocess\n"
        "cwd_flag = sys.argv[1]\n"
        "status_path = sys.argv[6]\n"  # cwd flag, Python, -I, -S, producer, status
        "real_argv = sys.argv[7:]\n"
        "assert cwd_flag.startswith('--working-directory=')\n"
        "honored_cwd = cwd_flag[len('--working-directory='):]\n"
        f"with open({record_path_repr}, 'w', encoding='utf-8') as f:\n"
        "    json.dump({'honored_cwd': honored_cwd, 'argv': real_argv}, f)\n"
        "raise SystemExit(subprocess.call(sys.argv[2:], cwd=honored_cwd))\n"
    )
    scripts_dir = tmp_path / "explicit-cwd-terminal-bin"
    scripts_dir.mkdir(exist_ok=True)
    script_path = scripts_dir / f"{name}.py"
    script_path.write_text(script)
    wrapper_path = scripts_dir / name
    import shlex
    wrapper_path.write_text(
        f"#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(script_path))} \"$@\"\n"
    )
    wrapper_path.chmod(
        wrapper_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH
    )
    # prefix carries the explicit cwd flag as a candidate-specific
    # argument, exactly like a real --working-directory=DIR flag would.
    return wrapper_path, ((str(wrapper_path), (f"--working-directory={tmp_path}",)),)


def install_early_exit_terminal(tmp_path: Path, name: str = "adc-early-exit-terminal") -> tuple[Path, tuple]:
    """A PROVIDER_EARLY_EXIT surrogate: the terminal process exits
    immediately WITHOUT ever running the wrapper script or writing a
    status file -- models a window closed/crashed before the wrapped
    command could report any result at all (never even started)."""
    scripts_dir = tmp_path / "early-exit-terminal-bin"
    scripts_dir.mkdir(exist_ok=True)
    script_path = scripts_dir / name
    script_path.write_text("#!/bin/sh\nexit 0\n")
    script_path.chmod(
        script_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH
    )
    return script_path, ((str(script_path), ()),)


def install_start_failure_terminal_candidates(tmp_path: Path) -> tuple:
    """A PROVIDER_START_FAILURE surrogate: a candidates tuple naming a
    binary that does not exist on disk at all -- DesktopTerminalProvider's
    own shutil.which()-based _select_binary() will not find it, exactly
    modeling "no supported terminal provider is available" without
    needing to fake subprocess.Popen itself."""
    nonexistent = tmp_path / "does-not-exist" / "no-such-terminal-binary"
    return ((str(nonexistent), ()),)


def provider_with_explicit_cwd(
    tmp_path: Path, monkeypatch, record_path: Path, name: str = "adc-explicit-cwd-terminal",
) -> DesktopTerminalProvider:
    """A real DesktopTerminalProvider wired to the PROVIDER_WITH_EXPLICIT_CWD
    surrogate above."""
    script_path, candidates = install_provider_with_explicit_cwd_flag(tmp_path, record_path, name)
    monkeypatch.setenv(
        "PATH", f"{script_path.parent}{os.pathsep}{os.environ.get('PATH', '')}",
    )
    return DesktopTerminalProvider(candidates=candidates)


def read_explicit_cwd_record(record_path: Path) -> dict:
    with open(record_path, encoding="utf-8") as f:
        return json.load(f)


def install_malformed_status_terminal(tmp_path: Path, name: str = "adc-malformed-status-terminal") -> tuple[Path, tuple]:
    """A PROC_MALFORMED_STATUS fault surrogate: writes a non-integer
    status file (never an authenticated completion record) -- DesktopTerminalProvider's
    own authenticated _read_status() must treat this as cancelled, never crash and
    never fabricate a success."""
    scripts_dir = tmp_path / "malformed-status-terminal-bin"
    scripts_dir.mkdir(exist_ok=True)
    script_path = scripts_dir / name
    script_path.write_text(
        "#!/bin/sh\n"
        "shift 4\n"
        'status_path="$1"\n'
        'echo "not-a-number" > "$status_path"\n'
    )
    script_path.chmod(
        script_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH
    )
    return script_path, ((str(script_path), ()),)


def install_timeout_terminal(tmp_path: Path, name: str = "adc-timeout-terminal") -> tuple[Path, tuple]:
    """A PROC_TIMEOUT fault surrogate: sleeps well past any reasonable
    test timeout without ever writing a status file -- proves
    DesktopTerminalProvider's own deadline handling kills the process
    and reports cancelled rather than hanging forever."""
    scripts_dir = tmp_path / "timeout-terminal-bin"
    scripts_dir.mkdir(exist_ok=True)
    script_path = scripts_dir / name
    script_path.write_text("#!/bin/sh\nexec /bin/sleep 3600\n")
    script_path.chmod(
        script_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH
    )
    return script_path, ((str(script_path), ()),)


def install_status_then_linger_terminal(
    tmp_path: Path, name: str = "adc-status-then-linger-terminal",
) -> tuple[Path, tuple]:
    """Terminal surrogate whose launcher remains alive after publishing a
    valid child status.

    This is distinct from ``install_timeout_terminal``: DesktopTerminalProvider
    has already observed a trustworthy result, but its ``process.wait`` still
    times out and must kill the lingering terminal process before returning
    that result.
    """
    scripts_dir = tmp_path / "status-then-linger-terminal-bin"
    scripts_dir.mkdir(exist_ok=True)
    script_path = scripts_dir / name
    script_path.write_text(
        "#!/bin/sh\n"
        '"$@"\n'
        "exec /bin/sleep 3600\n"
    )
    script_path.chmod(
        script_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH
    )
    return script_path, ((str(script_path), ()),)


def install_inert_counting_terminal(
    tmp_path: Path, counter_path: Path, record_path: Path,
    name: str = "adc-inert-counting-terminal",
) -> tuple[Path, tuple]:
    """As install_inert_recording_terminal above, but ALSO appends one
    line to `counter_path` on every invocation -- a real, observable,
    subprocess-independent "how many times did execute_controlled's
    install branch genuinely reach the terminal boundary" count, the
    same "count via a real filesystem side effect of the FINAL exec
    chain" principle tests/local_package_fixture.py::
    build_launch_counting_target and
    tests/test_interactive_terminal.py::
    TestDesktopTerminalProviderFinalChildBoundary::
    test_final_child_is_spawned_exactly_once already establish --
    needed here because build_launch_counting_target's own counter only
    increments when its wrapper script actually EXECUTES, which an
    inert terminal boundary, by design, never lets happen.

    (CLAUDE-ADC-TEST-GATE1-SAFETY-CORRECTION-001, DEF-014: a system
    -level Web/MCP retry test needs to distinguish "the install genuinely
    reached the terminal boundary once" from "retry reached it a second
    time" without ever letting a real process -- pip or otherwise --
    actually run.)

    `record_path` still captures only the LAST invocation's argv (an
    identity/no-substitution check across calls is a same-vs-different
    comparison the caller makes itself by reading it after each call,
    same as install_inert_recording_terminal); `counter_path` is what
    proves the call COUNT.
    """
    import shlex

    scripts_dir = tmp_path / "inert-counting-terminal-bin"
    scripts_dir.mkdir(exist_ok=True)
    script_path = scripts_dir / name
    script_path.write_text(
        "#!/bin/sh\n"
        "shift 4\n"
        'status_path="$1"\n'
        "shift\n"
        f"counter_path={shlex.quote(str(counter_path))}\n"
        f"record_path={shlex.quote(str(record_path))}\n"
        'echo launch >> "$counter_path"\n'
        ': > "$record_path"\n'
        'for arg in "$@"; do\n'
        '    printf \'%s\\n\' "$arg" >> "$record_path"\n'
        "done\n"
        + _SIMULATED_STATUS_SH
    )
    script_path.chmod(
        script_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH
    )
    return script_path, ((str(script_path), ()),)


def inert_counting_provider(
    tmp_path: Path, monkeypatch, counter_path: Path, record_path: Path,
    name: str = "adc-inert-counting-terminal",
) -> DesktopTerminalProvider:
    """A real DesktopTerminalProvider wired to the inert COUNTING
    terminal script above."""
    script_path, candidates = install_inert_counting_terminal(
        tmp_path, counter_path, record_path, name,
    )
    monkeypatch.setenv(
        "PATH", f"{script_path.parent}{os.pathsep}{os.environ.get('PATH', '')}",
    )
    return DesktopTerminalProvider(candidates=candidates)


def read_terminal_launch_count(counter_path: Path) -> int:
    if not counter_path.exists():
        return 0
    return len([line for line in counter_path.read_text().splitlines() if line.strip()])


def synthetic_target_python(tmp_path: Path, name: str = "toolchain-a") -> str:
    """A harmless, always-exits-0 placeholder standing in for a real
    Python interpreter's own executable identity: present and
    executable on PATH (so real RequirementPreflight/ToolchainMaterializer/
    CapabilityRegistry resolution succeeds exactly as it would for a
    real interpreter), but never actually invoked with real pip-install
    arguments when wired to an inert terminal boundary -- this script's
    own trivial body (`exit 0`) is a second, defense-in-depth layer even
    for any non-mutating "verification"/"query" style direct invocation
    that might occur outside the terminal-routed install path.

    (CLAUDE-ADC-TEST-ENVIRONMENT-FIDELITY-UPGRADE-001: the shared
    replacement for tests/local_package_fixture.py's real, hermetic
    venv/wheel-based `build_isolated_toolchain`/`build_local_wheel_index`
    wherever a test only needs a real, PATH-resolvable executable
    IDENTITY, never a real interpreter that actually runs anything.)

    CLAUDE-ADC-RSE033-RESIDUAL-DISTRIBUTION-PTY-CLOSURE-FIX-003: a blank
    exit-0 answer is no longer a presence verdict, so a distribution
    query shape (``-c <script> <name>``) answers with the protocol's
    explicit ABSENT verdict line -- the placeholder still never runs
    the script it is handed.
    """
    bin_dir = tmp_path / f"{name}-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    target = bin_dir / "python"
    target.write_text(
        "#!/bin/sh\n"
        'if [ "$#" -eq 3 ] && [ "$1" = "-c" ]; then\n'
        f"  printf '%s\\n' '{_ABSENT_LINE}'\n"
        "fi\n"
        "exit 0\n"
    )
    target.chmod(0o755)
    return str(target)


def inert_terminal_harness(tmp_path: Path, monkeypatch, name: str = "toolchain-a"):
    """One-call replacement for the
    "build_local_wheel_index + build_launch_counting_target + bare
    PythonPackageExecutor() + real, unmocked terminal" pattern that
    several CLAUDE-E2E-003* system-level test files used before
    CLAUDE-ADC-TEST-ENVIRONMENT-FIDELITY-UPGRADE-001: that combination
    genuinely executes `pip install` (a real, if hermetic and
    no-network, software installation) once the wrapped command
    actually runs inside a real, unmocked terminal, and can genuinely
    attempt to launch a real GUI terminal emulator if one happens to be
    on PATH (as gnome-terminal/x-terminal-emulator commonly are).

    Returns (target_python, counter_path, record_path):
      - target_python: a synthetic_target_python() identity, already
        placed on PATH (via monkeypatch.setenv), for
        RequirementPreflight/ToolchainMaterializer/CapabilityRegistry
        resolution.
      - counter_path / record_path: read with read_terminal_launch_count()
        / read_recorded_argv() to observe exactly how many times, and
        with what exact argv, execute_controlled()'s install branch
        genuinely reached the (inert) terminal boundary.

    Monkeypatches app.interactive_terminal.DesktopTerminalProvider
    globally for the duration of the test (auto-reverted by pytest's
    monkeypatch fixture), since PythonPackageExecutor's default runner
    gives execute_controlled() no way to inject a custom
    terminal_launcher directly. Callers still need their own
    PythonPackageExecutor(verifier=...) with a deterministic verifier
    (this helper does not construct the executor itself, since callers
    wire it into a DevelopmentWorkflow/ProjectSetupApplicationService
    in different shapes).
    """
    import app.interactive_terminal as interactive_terminal_module

    target_python = synthetic_target_python(tmp_path, name)
    prior_path = os.environ.get("PATH", "")
    monkeypatch.setenv(
        "PATH", f"{os.path.dirname(target_python)}{os.pathsep}{prior_path}",
    )

    counter_path = tmp_path / f"{name}-terminal-launch-count.txt"
    record_path = tmp_path / f"{name}-terminal-recorded-argv.txt"
    provider = inert_counting_provider(tmp_path, monkeypatch, counter_path, record_path, name=f"{name}-inert-terminal")
    monkeypatch.setattr(interactive_terminal_module, "DesktopTerminalProvider", lambda: provider)

    return target_python, counter_path, record_path


def write_recording_python_wrapper(
    tmp_path: Path, real_python: str, out_path: Path, name: str = "recording-python",
) -> Path:
    """A python-shaped wrapper script that records the FINAL CHILD's own
    real cwd/env/argv to `out_path` as JSON, then execs the real
    `real_python` interpreter unchanged -- so a caller that hard-codes
    `[target_python, "-m", "pip", "install", package]` (as
    PythonPackageExecutor.execute() does) still genuinely runs a real
    pip install through this wrapper, while this module observes
    exactly what environment/cwd/argv the OS actually gave the process,
    independent of any spy on a Python-level function."""
    import shlex

    wrapper_dir = tmp_path / f"{name}-bin"
    wrapper_dir.mkdir(parents=True, exist_ok=True)
    wrapper_path = wrapper_dir / name
    probe = write_final_child_probe(tmp_path)
    wrapper_path.write_text(
        "#!/bin/sh\n"
        f'{shlex.quote(sys.executable)} {shlex.quote(str(probe))} '
        f'{shlex.quote(str(out_path))} 0 "$@" > /dev/null\n'
        f'exec {shlex.quote(real_python)} "$@"\n'
    )
    wrapper_path.chmod(0o755)
    return wrapper_path


def write_package_operation_probe(tmp_path: Path, out_path: Path, *,
                                  name: str = "package-probe", success_package=None) -> Path:
    """An inert OS child: record every call; simulate package state with a file.

    Arguments are data only: neither -m nor -c is interpreted or executed.
    No installer, network, subprocess, or software installation is involved.
    Unknown operations fail closed. A named success package is useful for
    retry tests; otherwise the package operation deterministically fails.
    """
    directory = tmp_path / f"{name}-bin"
    directory.mkdir()
    target = directory / name
    target.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        f"output = Path({str(out_path)!r})\n"
        "state = output.with_suffix('.state')\n"
        "args = sys.argv[1:]\n"
        "with output.open('a') as stream:\n"
        "    stream.write(json.dumps({'cwd': os.getcwd(), 'argv': sys.argv, "
        "'env': dict(os.environ), 'pid': os.getpid()}) + '\\n')\n"
        f"package = {success_package!r}\n"
        "if len(args) == 4 and args[:3] == ['-m', 'pip', 'install']:\n"
        "    if package is not None and args[3] == package:\n"
        "        state.write_text('simulated success')\n"
        "        sys.exit(0)\n"
        "    sys.exit(17)\n"
        "if len(args) == 3 and args[0] == '-c':\n"
        f"    print({_PRESENT_LINE!r} if state.exists() and args[2] == package "
        f"else {_ABSENT_LINE!r})\n"
        "    sys.exit(0)\n"
        "sys.exit(23)\n"
    )
    target.chmod(0o755)
    return target
