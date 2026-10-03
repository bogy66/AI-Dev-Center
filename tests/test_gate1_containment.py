"""Focused regression coverage for the Gate-1 mandatory fail-closed
external-effect containment mechanism
(KIA-ADC-GATE1-HARNESS-PROOF-FIX-001 sections 2/3/10).

Every test here proves DENIAL BEFORE THE REAL EFFECT BEGINS, using
sentinels/fake boundaries -- none of these tests contacts real network,
launches a real terminal, invokes real sudo, or installs software, even
if the underlying binary happened to be present on this host (the
containment mechanism itself, not ambient host state, is what these
tests exercise).
"""
from __future__ import annotations

import socket
import subprocess
import sys
import textwrap

import pytest

from requirements.evidence.gate1_containment import (
    FORBIDDEN_EXECUTABLES,
    Gate1ContainmentViolation,
    REAL_DESKTOP_TERMINALS,
    is_installed,
)


# ----------------------------------------------------------------------
# A. Containment activates without any explicit test fixture opt-in.
# ----------------------------------------------------------------------

def test_containment_is_already_installed_with_no_fixture_requested():
    """This test requests no special fixture at all -- containment must
    already be active purely because the root conftest.py installs it
    unconditionally at pytest_configure time, before any test runs."""
    assert is_installed()


# ----------------------------------------------------------------------
# B. Real desktop-terminal execution denied BEFORE real spawn.
# ----------------------------------------------------------------------

@pytest.mark.parametrize("terminal", sorted(REAL_DESKTOP_TERMINALS))
def test_real_desktop_terminal_denied_before_spawn(terminal):
    with pytest.raises(Gate1ContainmentViolation):
        subprocess.Popen([terminal, "--version"])


# ----------------------------------------------------------------------
# C. External network access denied BEFORE external connection.
# ----------------------------------------------------------------------

def test_external_network_connect_denied_before_connection():
    # 203.0.113.0/24 is the RFC 5737 TEST-NET-3 documentation range --
    # never routable -- used only so this assertion never depends on
    # whether *some* real address happens to be reachable/unreachable
    # from this host; the guard must deny it before any socket-level
    # connection attempt is even made.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(Gate1ContainmentViolation):
            sock.connect(("203.0.113.5", 81))
    finally:
        sock.close()


def test_external_dns_resolution_denied_before_resolution():
    with pytest.raises(Gate1ContainmentViolation):
        socket.getaddrinfo("example.invalid.adc-gate1-test", 80)


def test_loopback_connect_is_never_denied_by_containment():
    """Preserves legitimate local IPC / localhost test servers: a
    loopback connect must fail (nothing is listening) for an ordinary
    networking reason, never Gate1ContainmentViolation."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    try:
        with pytest.raises(ConnectionRefusedError):
            sock.connect(("127.0.0.1", 1))
    finally:
        sock.close()


# ----------------------------------------------------------------------
# D. Real installer execution denied BEFORE real installation activity.
# ----------------------------------------------------------------------

def test_system_package_manager_denied_before_installation():
    with pytest.raises(Gate1ContainmentViolation):
        subprocess.Popen(["apt-get", "install", "-y", "cowsay"])


# ----------------------------------------------------------------------
# E. Privilege elevation denied BEFORE sudo/elevation entry.
# ----------------------------------------------------------------------

def test_sudo_denied_before_elevation_entry():
    with pytest.raises(Gate1ContainmentViolation):
        subprocess.Popen(["sudo", "true"])


def test_pkexec_denied_before_elevation_entry():
    with pytest.raises(Gate1ContainmentViolation):
        subprocess.Popen(["pkexec", "true"])


# ----------------------------------------------------------------------
# F. A child Python process inherits the guard (no explicit opt-in in
# the child -- the child only imports the exception type to assert on
# it; installation itself must come purely from inheritance).
# ----------------------------------------------------------------------

def test_child_python_process_inherits_containment():
    script = textwrap.dedent("""
        import subprocess
        from requirements.evidence.gate1_containment import Gate1ContainmentViolation
        try:
            subprocess.Popen(["gnome-terminal", "--version"])
        except Gate1ContainmentViolation:
            raise SystemExit(0)
        raise SystemExit(1)
    """)
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, (
        f"child Python process was not contained: stdout={result.stdout!r} stderr={result.stderr!r}"
    )


# ----------------------------------------------------------------------
# G. A nested pytest process inherits the guard.
# ----------------------------------------------------------------------

def test_nested_pytest_inherits_containment(tmp_path):
    nested_test = tmp_path / "test_nested_containment_probe.py"
    nested_test.write_text(textwrap.dedent("""
        import subprocess
        import pytest
        from requirements.evidence.gate1_containment import Gate1ContainmentViolation

        def test_nested_containment_is_active():
            with pytest.raises(Gate1ContainmentViolation):
                subprocess.Popen(["xterm", "-e", "true"])
    """))
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(nested_test), "-p", "no:cacheprovider", "-q"],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, (
        f"nested pytest process was not contained:\nstdout={result.stdout}\nstderr={result.stderr}"
    )


# ----------------------------------------------------------------------
# H. Absolute-path bypass fails closed.
# ----------------------------------------------------------------------

def test_absolute_path_bypass_fails_closed():
    """A nonexistent absolute path is denied purely by basename match --
    never because the file happens to be absent (section 3: must not
    rely on a package being merely assumed not to exist)."""
    with pytest.raises(Gate1ContainmentViolation):
        subprocess.Popen(["/usr/bin/gnome-terminal", "--version"])


# ----------------------------------------------------------------------
# I. Shell-mediated bypass fails closed.
# ----------------------------------------------------------------------

def test_shell_mediated_bypass_fails_closed():
    with pytest.raises(Gate1ContainmentViolation):
        subprocess.Popen("true; sudo apt-get install -y cowsay", shell=True)


# ----------------------------------------------------------------------
# Bonus: fail-closed tamper detection (section 2's "must fail closed
# when a test attempts to bypass ordinary fixture injection" -- proven
# directly at the mechanism level here, without actually tampering with
# the real session-wide guard, which would risk leaving a later test
# uncontained if this test failed midway).
# ----------------------------------------------------------------------

def test_tamper_is_detected_by_is_installed():
    import subprocess as subprocess_module

    from requirements.evidence import gate1_containment

    original = subprocess_module.Popen.__init__
    try:
        subprocess_module.Popen.__init__ = object.__init__
        assert gate1_containment.is_installed() is False
    finally:
        subprocess_module.Popen.__init__ = original
        assert gate1_containment.is_installed() is True


# ----------------------------------------------------------------------
# A harmless, deterministic local test mechanism (an inert final-child
# probe executable, not any name in FORBIDDEN_EXECUTABLES) must remain
# entirely unaffected by containment.
# ----------------------------------------------------------------------

def test_harmless_local_subprocess_is_not_denied(tmp_path):
    probe = tmp_path / "harmless_probe.py"
    probe.write_text("import sys\nsys.exit(0)\n")
    result = subprocess.run([sys.executable, str(probe)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0
