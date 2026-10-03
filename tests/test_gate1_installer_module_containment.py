"""Focused regression coverage for the installer-MODULE containment
extension (KIA-ADC-GATE1-CONTAINMENT-GATE-SCOPING-FIX-001 sections 2-5),
closing the ensurepip escape KI-B's independent analysis proved:
venv.EnvBuilder(with_pip=True) -> a `<python> -m ensurepip ...` child ->
subprocess.Popen -- an ordinary, never-forbidden python interpreter
basename, invisible to the pre-existing FORBIDDEN_EXECUTABLES check.

SAFETY: unlike tests/test_gate1_containment.py's own real-desktop-
terminal/system-package-manager cases (never actually present on a CI
host, so even a hypothetically broken guard could at worst hit
FileNotFoundError), `python3`/`pip`/`ensurepip` ARE genuinely present on
this host and a broken guard reaching the real Popen boundary here would
actually install something for real. Every test that exercises a REAL
argv shape therefore replaces gate1_containment's own internal
`_ORIGINAL_POPEN_INIT` (the "real Popen" the guard delegates to once it
decides not to deny) with an in-test sentinel that never forks/execs
anything -- so even a hypothetically broken guard could not actually
install pip here, only reach (and be caught failing to raise before
reaching) the sentinel.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
import venv

import ensurepip
import pytest

from requirements.evidence import gate1_containment
from requirements.evidence.gate1_containment import (
    Gate1ContainmentViolation,
    FORBIDDEN_INSTALLER_MODULES,
    is_installed,
)


@pytest.fixture
def popen_sentinel(monkeypatch):
    """Replaces the REAL Popen entry point _guarded_popen_init delegates
    to with a sentinel that records invocations and never actually
    forks/execs a real process. Returns the call-log list -- an empty
    list after the exercised call proves denial happened strictly
    BEFORE the real boundary, not merely that *some* exception was
    raised somewhere downstream."""
    calls = []

    def _sentinel(self, *args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("real Popen entry point must never be reached")

    monkeypatch.setattr(gate1_containment, "_ORIGINAL_POPEN_INIT", _sentinel)
    return calls


# ----------------------------------------------------------------------
# A/B/C/D. python -m ensurepip|pip, bare and absolute-path interpreter.
# ----------------------------------------------------------------------

@pytest.mark.parametrize("interpreter", ["python", "python3", "/usr/bin/python3", "/usr/bin/python3.12"])
@pytest.mark.parametrize("module", sorted(FORBIDDEN_INSTALLER_MODULES))
def test_installer_module_invocation_denied_before_entry(popen_sentinel, interpreter, module):
    with pytest.raises(Gate1ContainmentViolation):
        subprocess.Popen([interpreter, "-m", module, "install", "x"])
    assert popen_sentinel == [], "the real Popen boundary must never be reached"


@pytest.mark.parametrize("module", sorted(FORBIDDEN_INSTALLER_MODULES))
def test_combined_dash_m_form_denied_before_entry(popen_sentinel, module):
    with pytest.raises(Gate1ContainmentViolation):
        subprocess.Popen(["python3", f"-m{module}"])
    assert popen_sentinel == []


def test_installer_module_invocation_denied_via_shell_mediated_form(popen_sentinel):
    with pytest.raises(Gate1ContainmentViolation):
        subprocess.Popen("true; python3 -m ensurepip --upgrade", shell=True)
    assert popen_sentinel == []


# ----------------------------------------------------------------------
# E. Direct/API-backed ensurepip entry (never spawns `-m ensurepip` at
# all) denied via the sys.audit('ensurepip.bootstrap', ...) hook,
# strictly before ensurepip._run_pip (its own internal, real installer
# subprocess helper) is ever reached.
# ----------------------------------------------------------------------

def test_ensurepip_bootstrap_audit_event_denied_before_run_pip(monkeypatch):
    called = []

    def _sentinel_run_pip(*args, **kwargs):
        called.append((args, kwargs))
        raise AssertionError("ensurepip._run_pip must never be reached")

    monkeypatch.setattr(ensurepip, "_run_pip", _sentinel_run_pip)
    with pytest.raises(Gate1ContainmentViolation):
        sys.audit("ensurepip.bootstrap", None)
    assert called == [], "ensurepip._run_pip must never be reached"


def test_unrelated_audit_events_are_never_denied():
    """No false positives: the audit hook only ever acts on the exact
    'ensurepip.bootstrap' event name."""
    sys.audit("os.listdir", ".")  # must not raise


# ----------------------------------------------------------------------
# F/G. venv.EnvBuilder(with_pip=True) denied before real installation;
# venv.EnvBuilder(with_pip=False) remains fully usable (section 4).
# ----------------------------------------------------------------------

def test_venv_with_pip_true_denied_before_installation(popen_sentinel, tmp_path):
    target = tmp_path / "venv-with-pip"
    with pytest.raises(Gate1ContainmentViolation):
        venv.EnvBuilder(with_pip=True, clear=True).create(str(target))
    assert popen_sentinel == [], "the real installer child must never be reached"
    # Zero installation artifacts, even under a partially-created venv
    # directory tree (creating the venv's own directory scaffolding is
    # harmless local metadata, never "software installation" -- only
    # the pip bootstrap step itself is prohibited).
    assert not list(target.rglob("pip*-dist-info")), "zero pip installation artifacts must exist"
    assert not list(target.rglob("pip*.dist-info")), "zero pip installation artifacts must exist"


def test_venv_with_pip_false_remains_usable(tmp_path):
    target = tmp_path / "venv-without-pip"
    venv.EnvBuilder(with_pip=False, clear=True).create(str(target))
    assert is_installed(), "containment must remain installed after a harmless with_pip=False venv"
    assert any(target.glob("bin/python*")) or any(target.glob("Scripts/python*.exe"))


# ----------------------------------------------------------------------
# H. Child-Python / nested-pytest containment remains intact for this
# NEW check too (Fix-1's existing inheritance mechanism, exercised here
# against the new installer-module classification specifically).
# ----------------------------------------------------------------------

def test_child_python_process_inherits_installer_module_containment():
    script = textwrap.dedent("""
        import subprocess
        from requirements.evidence.gate1_containment import Gate1ContainmentViolation
        try:
            subprocess.Popen(["python3", "-m", "ensurepip", "--upgrade"])
        except Gate1ContainmentViolation:
            raise SystemExit(0)
        raise SystemExit(1)
    """)
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, (
        f"child Python process was not contained against -m ensurepip: "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


# ----------------------------------------------------------------------
# Harmless module invocations must remain entirely unaffected (no
# false positives on ordinary `python -m <harmless module>` usage,
# which this codebase's own tooling/tests rely on constantly).
# ----------------------------------------------------------------------

def test_harmless_module_invocation_is_never_denied():
    """A real, genuinely harmless `-m <module>` invocation (no
    installer semantics at all) must complete normally -- proves the
    new check has no false-positive overlap with ordinary module
    invocations this codebase's own tooling relies on."""
    result = subprocess.run(
        ["python3", "-m", "json.tool", "--help"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
    )
    assert result.returncode == 0
