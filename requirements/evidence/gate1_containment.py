"""Gate-1 mandatory fail-closed external-effect containment
(KIA-ADC-GATE1-HARNESS-PROOF-FIX-001 sections 2/3).

Structurally prevents, BEFORE the real spawn/connect ever begins, the
four forbidden Gate-1 external effects:

  - real desktop-terminal execution (gnome-terminal, xterm, konsole,
    xfce4-terminal, x-terminal-emulator, and equivalent real desktop/
    session provider execution);
  - external network access, including live LLM/provider endpoints;
  - real installer execution / software installation;
  - privilege elevation / sudo.

WHY THE PRIMARY LAYER IS A subprocess.Popen / socket.socket MONKEYPATCH,
NOT A PATH SHIM OR A FIXTURE: every real spawn this codebase can reach
(app.interactive_terminal.DesktopTerminalProvider.run's real
subprocess.Popen call, app.execution.execute_controlled's real
subprocess.run call, or any test/product code that calls subprocess.run/
call/check_call/check_output -- all of which construct a subprocess.Popen
under the hood) passes through exactly one chokepoint:
subprocess.Popen.__init__. Patching that one chokepoint to inspect argv
and deny a forbidden executable BEFORE calling the real __init__ (which
is what actually forks/execs) is a structural "prevent before entry",
not an after-the-fact monitor and not reliant on the forbidden binary
being merely absent from PATH. Network access is intercepted the same
way at socket.socket.connect/connect_ex/getaddrinfo -- the one
chokepoint urllib/requests/httpx/the stdlib all eventually call through,
including for TLS (ssl.SSLSocket subclasses socket.socket and calls its
connect()).

A small PATH-shadowing layer and the os.exec*/os.posix_spawn* family are
also patched as defense-in-depth against a raw bypass that never goes
through subprocess.Popen at all -- but neither PATH shims nor these
extra patches are what makes containment safe: removing them would
degrade defense-in-depth, not remove the primary guarantee, which is the
Popen/socket chokepoint patch installed unconditionally by the root
conftest.py (never inside an optional fixture a test could simply not
request).

INHERITANCE INTO CHILD PYTHON PROCESSES / NESTED PYTEST: install() also
writes a small, self-contained sitecustomize.py to a private temp
directory and prepends that directory to the PYTHONPATH environment
variable, alongside an ADC_GATE1_CONTAINMENT_ACTIVE=1 marker. Both are
ordinary environment variables, inherited by any child process this
process spawns unless a caller deliberately constructs a stripped `env=`
for that child -- exactly the case for an ordinary child Python
interpreter or a nested `python -m pytest` subprocess. Python's own
`site` module imports sitecustomize (if importable) at interpreter
startup, before any of the child's own code runs, so the guard is
reinstalled in the child before it can do anything, including before a
nested pytest session's own collection begins. (This does not reach a
child started with `python -S`/`-I`, which explicitly disables site
processing; that is a known, narrow limitation of this technique, not a
gap in the primary in-process guarantee.)

FAIL-CLOSED ON TAMPERING: the root conftest.py reinstalls this guard
before every single test item (`pytest_runtest_setup`), unconditionally
and idempotently -- there is no fixture to decline, so a test cannot
leave a LATER test uncontained merely by mutating subprocess.Popen/
socket.socket directly instead of going through pytest's own
monkeypatch fixture (which already auto-reverts at that same test's own
teardown). This deliberately does not hard-fail a test for locally
substituting subprocess.Popen/socket.socket for its own mocking
purposes during its own body -- that is normal, existing, accepted
testing practice in this suite and never itself a forbidden external
effect; see is_installed() below for the direct, mechanical way to
observe whether the guard is currently in place.

EXPLICITLY AUTHORIZED REAL-SYSTEM EXECUTION OUTSIDE GATE 1: this module
never inspects ambient state (DISPLAY, network reachability, whether a
package happens to be installed) to decide whether to contain. The one
and only bypass is the existing, explicit, human-operator-supplied
`--real-system-e2e` pytest flag (tests/conftest.py) -- ROOT conftest.py
simply does not call install() for a session invoked with that flag, so
an explicitly authorized Real-System/Gate-3 run is never contained. No
per-test fixture and no ambient condition can achieve the same effect.
"""
from __future__ import annotations

import inspect
import ipaddress
import os
import re
import shlex
import shutil
import socket as _socket_module
import subprocess as _subprocess_module
import sys
import tempfile
from pathlib import Path

ENV_MARKER = "ADC_GATE1_CONTAINMENT_ACTIVE"
_SITE_DIR_ENV = "ADC_GATE1_SITECUSTOMIZE_DIR"


class Gate1ContainmentViolation(RuntimeError):
    """Raised BEFORE a forbidden Gate-1 external effect is allowed to
    begin (real desktop-terminal launch, external network connection,
    real installer execution, or privilege elevation). Never raised
    after the effect has already started -- every guard in this module
    checks and raises strictly before delegating to the real
    implementation."""


# ---------------------------------------------------------------------
# Forbidden-executable classification. A curated, auditable set -- not a
# claim to enumerate every real terminal/installer/elevation binary on
# Earth, but exactly the ones named in KIA-ADC-GATE1-HARNESS-PROOF-FIX
# -001 section 2, plus the unambiguous system-level package managers
# (never used by this repo's own hermetic/local pip-wheel test
# machinery -- see tests/local_package_fixture.py -- so blocking them
# outright carries no risk of colliding with an accepted Gate-1
# mechanism). Real, non-local `pip install <pypi-package>` still
# requires the terminal (blocked) or external network (also
# independently blocked below) in this codebase's own architecture
# (app.execution.execute_controlled routes every operation_type=="install"
# request through InteractiveTerminalLauncher -- never a direct,
# invisible subprocess call).
# ---------------------------------------------------------------------
REAL_DESKTOP_TERMINALS = frozenset({
    "gnome-terminal", "xterm", "konsole", "xfce4-terminal", "x-terminal-emulator",
})

PRIVILEGE_ELEVATION_BINARIES = frozenset({"sudo", "pkexec", "doas"})

SYSTEM_PACKAGE_MANAGERS = frozenset({
    "apt-get", "apt", "dpkg", "yum", "dnf", "microdnf", "zypper", "pacman",
    "apk", "brew", "snap", "flatpak", "rpm", "yast", "choco", "winget",
})

FORBIDDEN_EXECUTABLES = REAL_DESKTOP_TERMINALS | PRIVILEGE_ELEVATION_BINARIES | SYSTEM_PACKAGE_MANAGERS

_LOOPBACK_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0", "", "ip6-localhost"})

# ---------------------------------------------------------------------
# Installer-MODULE containment (KIA-ADC-GATE1-CONTAINMENT-GATE-SCOPING
# -FIX-001 sections 2/3/4). A python interpreter's own basename is never
# itself forbidden (tests/product code launches plain `python`/
# `python3` constantly for entirely harmless reasons), but the SPECIFIC
# OPERATION it is instructed to run can be: `-m ensurepip` / `-m pip`
# bootstraps/installs real packages regardless of whether the caller
# considers it "local", "offline", "bundled-wheel", or "under tmp_path"
# -- none of those qualify for an exemption (section 4). This is
# EXACTLY the escape KI-B's independent analysis proved:
# venv.EnvBuilder(with_pip=True) -> EnvBuilder._setup_pip -> a NEW
# child interpreter run as `<python> -m ensurepip --upgrade
# --default-pip` -> subprocess.Popen -- argv[0] is an ordinary,
# never-forbidden python interpreter, so the pre-existing
# FORBIDDEN_EXECUTABLES basename check never saw it.
# ---------------------------------------------------------------------
_PYTHON_INTERPRETER_RE = re.compile(r"^python3?(\.\d+)?(\.exe)?$")

FORBIDDEN_INSTALLER_MODULES = frozenset({"ensurepip", "pip"})


def _is_python_interpreter_name(name: str | None) -> bool:
    return bool(name) and bool(_PYTHON_INTERPRETER_RE.match(name))


def _classify_installer_module_argv(tokens) -> str | None:
    """`tokens[0]` a python interpreter (any basename shape: `python`,
    `python3`, `python3.12`, an absolute path to any of those, ...)
    immediately followed by `-m ensurepip`/`-m pip` (or the combined
    `-mensurepip`/`-mpip` form) -- exactly the proven venv.EnvBuilder
    escape shape (`[env_exec_cmd, '-m', 'ensurepip', '--upgrade',
    '--default-pip']`, no intervening flags). Deliberately narrow, like
    every other check in this module: the scan stops at the first token
    that is neither `-m`/`-m<module>` nor itself a `-`-prefixed flag, so
    it does not attempt to model every python CLI flag's arity (a flag
    taking a separate value, e.g. `-X dev`, stops the scan at `dev`
    rather than continuing past it to a later `-m`) -- no call site in
    this codebase's proven escape path places such a flag between the
    interpreter and `-m`, so this narrower shape does not miss the
    proven defect while keeping the same low false-positive posture as
    _check_direct_argv's own basename check. Returns a human-readable
    reason string when found, else
    None. Deliberately does NOT try to also parse a `-c <code>` payload
    for an embedded `runpy.run_module("pip", ...)` string (ensurepip's
    OWN internal `_run_pip` helper uses exactly this shape once already
    inside a contained child) -- that inner subprocess.Popen call is
    itself independently intercepted by this exact same guard when it
    fires (containment is chokepoint-based and re-applies to every
    single Popen call, nested or not), and the ONE additional entry
    this module deliberately does add for that same internal shape is
    the `sys.audit('ensurepip.bootstrap', ...)` hook below, which fires
    even earlier -- before `_run_pip` is ever reached at all."""
    if not tokens:
        return None
    texts = [_as_text(t) for t in tokens]
    first_name = _basename_of(texts[0])
    if not _is_python_interpreter_name(first_name):
        return None
    rest = texts[1:]
    for idx, arg in enumerate(rest):
        if arg == "-m":
            if idx + 1 < len(rest) and rest[idx + 1] in FORBIDDEN_INSTALLER_MODULES:
                return (
                    f"python interpreter {texts[0]!r} invoked with "
                    f"-m {rest[idx + 1]!r} (installer-module bootstrap)"
                )
            break
        if arg.startswith("-m") and len(arg) > 2:
            module = arg[2:]
            if module in FORBIDDEN_INSTALLER_MODULES:
                return (
                    f"python interpreter {texts[0]!r} invoked with "
                    f"{arg!r} (installer-module bootstrap)"
                )
            break
        if not arg.startswith("-"):
            break  # first positional (a script path, etc.) -- not a `-m ...` invocation shape.
    return None


def _check_installer_module_invocation(tokens) -> None:
    reason = _classify_installer_module_argv(tokens)
    if reason:
        _deny(reason)


def _deny(reason: str) -> None:
    raise Gate1ContainmentViolation(
        f"GATE1 CONTAINMENT: denied before real effect -- {reason}. This is "
        "the mandatory, unconditional Gate-1 external-effect boundary "
        "(KIA-ADC-GATE1-HARNESS-PROOF-FIX-001); it cannot be bypassed by "
        "omitting a fixture, and is not conditioned on ambient host state."
    )


def _basename_of(executable) -> str | None:
    if executable is None:
        return None
    if isinstance(executable, (bytes, bytearray)):
        executable = executable.decode("utf-8", "surrogateescape")
    executable = os.fspath(executable) if hasattr(executable, "__fspath__") else str(executable)
    return os.path.basename(executable).lower()


def _as_text(item) -> str:
    if isinstance(item, (bytes, bytearray)):
        return item.decode("utf-8", "surrogateescape")
    return os.fspath(item) if hasattr(item, "__fspath__") else str(item)


def _check_direct_argv(argv) -> None:
    """The precise, non-shell invocation shape: only the executable
    actually being run (argv[0], and where it's a bare name, what it
    resolves to on PATH) is checked -- deliberately narrow, so ordinary
    arguments that merely happen to contain a forbidden word as DATA
    (e.g. a filename) are never false-positively denied."""
    if argv is None:
        return
    if isinstance(argv, (str, bytes)):
        tokens = [argv]
    else:
        try:
            tokens = list(argv)
        except TypeError:
            return
    if not tokens:
        return
    first = _as_text(tokens[0])
    name = _basename_of(first)
    if name in FORBIDDEN_EXECUTABLES:
        _deny(f"executable {first!r} (resolved name {name!r}) is a forbidden Gate-1 external effect")
    if os.sep not in first and (os.altsep is None or os.altsep not in first):
        resolved = shutil.which(first)
        if resolved and _basename_of(resolved) in FORBIDDEN_EXECUTABLES:
            _deny(f"executable {first!r} resolves via PATH to forbidden binary {resolved!r}")
    _check_installer_module_invocation(tokens)


def _check_shell_command_line(command_line) -> None:
    """shell=True is the documented "shell-mediated child execution"
    bypass shape: the real executable is decided by /bin/sh, not by
    argv[0], and a forbidden binary can appear anywhere in a compound
    command (`true; sudo apt-get install x`, `a | gnome-terminal`).
    Deliberately broader than _check_direct_argv (every token is
    checked, not just the first) -- shell=True is rare in this
    codebase's own product/test code (no call site uses it), so the
    small extra false-positive surface (a forbidden word appearing as
    shell-quoted DATA) is an acceptable, documented trade-off for
    closing this specific, explicitly named bypass shape."""
    if command_line is None:
        return
    text = _as_text(command_line)
    try:
        tokens = shlex.split(text)
    except ValueError:
        tokens = text.split()
    for token in tokens:
        name = _basename_of(token)
        if name in FORBIDDEN_EXECUTABLES:
            _deny(f"shell command line contains forbidden executable {token!r} (resolved name {name!r})")
    # Same installer-module classification as _check_direct_argv, applied
    # starting from every position in the compound line (shell=True can
    # place the real interpreter invocation anywhere in a `;`/`&&`/`|`
    # separated line, not only at token 0) -- consistent with this
    # function's own already-broader, false-positive-accepting stance.
    for start in range(len(tokens)):
        reason = _classify_installer_module_argv(tokens[start:])
        if reason:
            _deny(f"shell command line: {reason}")


_ORIGINAL_POPEN_INIT = _subprocess_module.Popen.__init__
_POPEN_INIT_SIGNATURE = inspect.signature(_ORIGINAL_POPEN_INIT)


def _guarded_popen_init(self, *args, **kwargs):
    bound = _POPEN_INIT_SIGNATURE.bind_partial(self, *args, **kwargs)
    argv = bound.arguments.get("args")
    shell = bound.arguments.get("shell", False)
    executable = bound.arguments.get("executable")
    if executable:
        name = _basename_of(executable)
        if name in FORBIDDEN_EXECUTABLES:
            _deny(f"Popen(executable={executable!r}) is a forbidden Gate-1 external effect")
    if shell:
        command_line = argv if isinstance(argv, (str, bytes)) else (argv[0] if argv else None)
        _check_shell_command_line(command_line)
    else:
        _check_direct_argv(argv)
    return _ORIGINAL_POPEN_INIT(self, *args, **kwargs)


def _patch_subprocess() -> None:
    if _subprocess_module.Popen.__init__ is not _guarded_popen_init:
        _subprocess_module.Popen.__init__ = _guarded_popen_init


# ---------------------------------------------------------------------
# Defense-in-depth: the raw os.exec*/os.posix_spawn*/os.spawn* family,
# for a bypass that constructs a real process image replacement without
# ever going through subprocess.Popen at all.
# ---------------------------------------------------------------------
_RAW_EXEC_ORIGINALS: dict[str, object] = {}
_RAW_EXEC_NAMES = (
    "execl", "execle", "execlp", "execlpe", "execv", "execve", "execvp", "execvpe",
    "posix_spawn", "posix_spawnp",
    "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe",
)


def _make_guarded_exec(name, original):
    def _guarded(*args, **kwargs):
        # Every one of these signatures carries the target executable as
        # its first positional argument (`path`/`file`/`mode`+`path` for
        # the spawn* family, where args[1] is the real path).
        candidate = args[1] if name.startswith("spawn") and len(args) > 1 else (args[0] if args else None)
        if candidate is not None:
            resolved_name = _basename_of(candidate)
            if resolved_name in FORBIDDEN_EXECUTABLES:
                _deny(f"os.{name}({candidate!r}) is a forbidden Gate-1 external effect")
        return original(*args, **kwargs)
    _guarded.__name__ = f"gate1_guarded_{name}"
    return _guarded


def _patch_os_exec_family() -> None:
    for name in _RAW_EXEC_NAMES:
        original = getattr(os, name, None)
        if original is None:
            continue
        current = os.__dict__.get(name)
        if name not in _RAW_EXEC_ORIGINALS:
            _RAW_EXEC_ORIGINALS[name] = original
        expected_guard_name = f"gate1_guarded_{name}"
        if getattr(current, "__name__", "") != expected_guard_name:
            setattr(os, name, _make_guarded_exec(name, _RAW_EXEC_ORIGINALS[name]))


# ---------------------------------------------------------------------
# Network containment: deny any non-loopback AF_INET/AF_INET6 connect
# (and the DNS resolution that would normally precede a hostname-based
# one) before it reaches the OS. AF_UNIX and loopback are always
# allowed, preserving legitimate local IPC and localhost test servers.
# ---------------------------------------------------------------------
_ORIGINAL_SOCKET_CONNECT = _socket_module.socket.connect
_ORIGINAL_SOCKET_CONNECT_EX = _socket_module.socket.connect_ex
_ORIGINAL_GETADDRINFO = _socket_module.getaddrinfo


def _is_loopback_host(host) -> bool:
    if host is None:
        return True
    host = _as_text(host)
    if host in _LOOPBACK_HOSTNAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False  # a hostname, not a literal IP -- resolved separately.


def _is_loopback_address(sock, address) -> bool:
    if sock.family not in (_socket_module.AF_INET, _socket_module.AF_INET6):
        return True  # AF_UNIX etc. -- not the forbidden external-network surface.
    if not (isinstance(address, tuple) and address):
        return True
    return _is_loopback_host(address[0])


def _guarded_connect(self, address):
    if not _is_loopback_address(self, address):
        _deny(f"socket.connect({address!r}) is external network access")
    return _ORIGINAL_SOCKET_CONNECT(self, address)


def _guarded_connect_ex(self, address):
    if not _is_loopback_address(self, address):
        _deny(f"socket.connect_ex({address!r}) is external network access")
    return _ORIGINAL_SOCKET_CONNECT_EX(self, address)


def _guarded_getaddrinfo(host, *args, **kwargs):
    if not _is_loopback_host(host):
        _deny(f"getaddrinfo({host!r}, ...) is external DNS/address resolution")
    return _ORIGINAL_GETADDRINFO(host, *args, **kwargs)


def _patch_socket() -> None:
    if _socket_module.socket.connect is not _guarded_connect:
        _socket_module.socket.connect = _guarded_connect
    if _socket_module.socket.connect_ex is not _guarded_connect_ex:
        _socket_module.socket.connect_ex = _guarded_connect_ex
    if _socket_module.getaddrinfo is not _guarded_getaddrinfo:
        _socket_module.getaddrinfo = _guarded_getaddrinfo


# ---------------------------------------------------------------------
# Direct/API-backed ensurepip entry (KIA-ADC-GATE1-CONTAINMENT-GATE-
# SCOPING-FIX-001 section 3): a caller invoking ensurepip.bootstrap()
# directly, in-process -- never spawning a `-m ensurepip` child at all
# -- would otherwise bypass every argv-based check above entirely.
# CPython's own ensurepip._bootstrap() calls `sys.audit("ensurepip.
# bootstrap", root)` as its very FIRST side-effecting statement (PEP
# 578), strictly before it stages any bundled wheel into a temp
# directory or spawns the internal `<python> -c "...runpy.run_module(
# 'pip', ...)"` subprocess _run_pip() ultimately uses -- so an audit
# hook denying on this exact event is a real "before entry" boundary,
# not a race. (That internal _run_pip() subprocess call is ALSO
# independently caught by this same module's Popen chokepoint if it is
# ever reached at all -- defense-in-depth, not the primary layer here.)
# A `-m ensurepip` child spawned by venv.EnvBuilder is what section 3's
# primary fix (_classify_installer_module_argv, above) already denies
# before that child is even created; if it is nonetheless ever
# created (e.g. a future code path this module has not anticipated),
# ensurepip.__main__ calls this exact same _bootstrap(), so the
# sitecustomize-inherited audit hook in that child independently denies
# it too.
# ---------------------------------------------------------------------
_AUDIT_HOOK_INSTALLED = False


def _gate1_audit_hook(event: str, args) -> None:
    if event == "ensurepip.bootstrap":
        _deny(
            "ensurepip.bootstrap(...) direct/API-backed installer entry invoked "
            "in-process -- denied before any bundled-wheel staging, subprocess "
            "spawn, or filesystem mutation (sys.audit('ensurepip.bootstrap', ...))"
        )


def _patch_audit_hook() -> None:
    # sys.addaudithook installs are permanent for the life of the
    # interpreter (PEP 578 deliberately provides no removal API) --
    # install() itself is called before every single test item, so this
    # must stay idempotent via its own flag rather than relying on any
    # "already installed?" query (none exists for audit hooks).
    global _AUDIT_HOOK_INSTALLED
    if not _AUDIT_HOOK_INSTALLED:
        sys.addaudithook(_gate1_audit_hook)
        _AUDIT_HOOK_INSTALLED = True


# ---------------------------------------------------------------------
# Inheritance into child Python processes / nested pytest via PYTHONPATH
# + a generated sitecustomize.py (see module docstring).
# ---------------------------------------------------------------------
_SITECUSTOMIZE_TEMPLATE = """\
# Auto-generated by requirements.evidence.gate1_containment.install().
# Reinstalls the Gate-1 fail-closed external-effect containment guard at
# the start of every child Python interpreter that inherits
# {env_marker}=1 from its parent's environment, before any of the
# child's own import-time or module-level code can run.
import os
import sys

if os.environ.get({env_marker!r}) == "1":
    _repo_root = {repo_root!r}
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)
    from requirements.evidence import gate1_containment as _g1c
    _g1c.install()
"""


def _ensure_sitecustomize_on_pythonpath() -> None:
    site_dir = os.environ.get(_SITE_DIR_ENV)
    if not site_dir or not os.path.isfile(os.path.join(site_dir, "sitecustomize.py")):
        site_dir = tempfile.mkdtemp(prefix="adc-gate1-sitecustomize-")
        repo_root = str(Path(__file__).resolve().parents[2])
        content = _SITECUSTOMIZE_TEMPLATE.format(env_marker=ENV_MARKER, repo_root=repo_root)
        with open(os.path.join(site_dir, "sitecustomize.py"), "w", encoding="utf-8") as f:
            f.write(content)
        os.environ[_SITE_DIR_ENV] = site_dir
    existing = os.environ.get("PYTHONPATH", "")
    parts = [p for p in existing.split(os.pathsep) if p] if existing else []
    if site_dir not in parts:
        os.environ["PYTHONPATH"] = os.pathsep.join([site_dir, *parts])
    os.environ[ENV_MARKER] = "1"


def install() -> None:
    """Idempotent. Installs every containment layer and marks child
    processes for inheritance. Safe, and cheap, to call repeatedly (the
    root conftest.py calls this before every single test item as a
    self-healing measure)."""
    _patch_subprocess()
    _patch_os_exec_family()
    _patch_socket()
    _patch_audit_hook()
    _ensure_sitecustomize_on_pythonpath()


def is_installed() -> bool:
    """True only when every primary containment layer is currently in
    place. Used by the root conftest.py's fail-closed tamper check."""
    return (
        _subprocess_module.Popen.__init__ is _guarded_popen_init
        and _socket_module.socket.connect is _guarded_connect
        and _socket_module.socket.connect_ex is _guarded_connect_ex
        and _socket_module.getaddrinfo is _guarded_getaddrinfo
        and _AUDIT_HOOK_INSTALLED
    )
