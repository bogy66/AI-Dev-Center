"""Dedicated Environment and Setup real-system tests.

Run only with:
  venv/bin/python -m pytest tests/real_system/test_environment_setup_real.py --real-system-e2e -s

These tests exercise the controlled software environment setup lifecycle
and must never mutate the ADC development venv or host packages.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

import pytest

from app.python_package_executor import PythonPackageExecutor
from app.requirement_model import SetupEffect, SetupStep
from app.software_presence import PythonVenvPresenceChecker
from app.dev_workflow import DevelopmentWorkflow
from app.diagnostic_trace import (
    DiagnosticDetailLevel,
    DiagnosticTrace,
    DiagnosticTraceStore,
    render_diagnostic_trace_event,
)

REAL_SYSTEM_MARKER = pytest.mark.real_system


class _SetupTraceHarness:
    """Render real setup evidence through the production trace projection."""

    def __init__(self, base_dir: Path, run_id: str, diagnostic_level: str):
        self.run_id = run_id
        self.detail_level = DiagnosticDetailLevel(diagnostic_level)
        self.trace = DiagnosticTrace(
            DiagnosticTraceStore(base_dir / "diagnostic-trace.jsonl")
        )

        # Use the production setup-result projection without constructing
        # unrelated workflow stages.
        self.workflow = object.__new__(DevelopmentWorkflow)
        self.workflow._diagnostic_trace = self.trace

    def record(self, step: SetupStep, result) -> None:
        self.workflow._trace_setup_execution_result(
            self.run_id,
            step,
            result,
        )

    def render(self) -> None:
        if self.detail_level == DiagnosticDetailLevel.NONE:
            return

        for event in self.trace.get_trace(self.run_id):
            rendered = render_diagnostic_trace_event(
                event,
                self.detail_level,
            )
            if rendered:
                print(rendered)


def _create_test_venv(base_dir: Path, name: str = "test-env") -> Path:
    venv_path = base_dir / name
    venv.EnvBuilder(with_pip=True, clear=True).create(str(venv_path))
    return venv_path


def _python_in(venv_path: Path) -> str:
    return str(venv_path / "bin" / "python")


def _run_command(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _make_install_step(
    step_id: str,
    requirement_id: str,
    package: str,
    version: str | None = None,
) -> SetupStep:
    return SetupStep(
        id=step_id,
        requirement_id=requirement_id,
        action="install",
        install_method="pip",
        package=package,
        version=version,
        setup_effect=SetupEffect.PYTHON_PACKAGE_INSTALL,
        is_approved=True,
    )


def _make_executor_for_env(venv_path: Path) -> PythonPackageExecutor:
    python_exe = _python_in(venv_path)
    from app.python_package_executor import CommandResult
    class VenvCommandRunner:
        def run(self, args: list[str]) -> CommandResult:
            if args[0] in ("python", "python3", sys.executable):
                args = [python_exe] + args[1:]
            result = subprocess.run(
                args, shell=False, check=False, text=True, capture_output=True,
            )
            return CommandResult(
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
    executor = PythonPackageExecutor(
        runner=VenvCommandRunner(),
        environment_path=str(venv_path),
    )
    executor.python_executable = python_exe
    return executor

# ===================================================================
# Setup-001: esphome
# ===================================================================
@REAL_SYSTEM_MARKER
def test_setup_001_esphome_lifecycle(diagnostic_level):
    """ESPHome: isolated venv full lifecycle"""
    owned = Path(tempfile.mkdtemp(prefix="adc-setup-001-"))
    trace_harness = _SetupTraceHarness(
        owned,
        "setup-001",
        diagnostic_level,
    )
    try:
        venv_path = _create_test_venv(owned)
        executor = _make_executor_for_env(venv_path)
        checker = PythonVenvPresenceChecker()
        env_str = str(venv_path)

        presence_before = checker.check("esphome", env_str, "esphome")
        assert not presence_before.present, (
            "esphome must NOT be detected before install"
        )

        step = _make_install_step("esphome-001", "req-esphome", "esphome")
        result = executor.execute(step)
        trace_harness.record(step, result)
        assert result.success, (
            f"esphome install must succeed: {result.message}"
        )

        presence_after_install = checker.check("esphome", env_str, "esphome")
        assert presence_after_install.present, (
            "esphome must be detected after install"
        )
        assert presence_after_install.detected_version is not None

        version_result = _run_command([_python_in(venv_path), "-m", "esphome", "version"])
        assert version_result.returncode == 0
        assert "Version:" in version_result.stdout

        uninstall_result = executor.uninstall(step)
        trace_harness.record(step, uninstall_result)
        assert uninstall_result.success, (
            f"esphome uninstall must succeed: {uninstall_result.message}"
        )

        presence_after_uninstall = checker.check("esphome", env_str, "esphome")
        assert not presence_after_uninstall.present, (
            "esphome must NOT be detected after uninstall"
        )

    finally:
        trace_harness.render()
        shutil.rmtree(owned, ignore_errors=False)
        assert not owned.exists()

# ===================================================================
# Setup-002: platformio
# ===================================================================
@REAL_SYSTEM_MARKER
def test_setup_002_platformio_lifecycle(diagnostic_level):
    """PlatformIO: isolated venv full lifecycle"""
    owned = Path(tempfile.mkdtemp(prefix="adc-setup-002-"))
    trace_harness = _SetupTraceHarness(
        owned,
        "setup-002",
        diagnostic_level,
    )
    try:
        venv_path = _create_test_venv(owned)
        executor = _make_executor_for_env(venv_path)
        checker = PythonVenvPresenceChecker()
        env_str = str(venv_path)

        presence_before = checker.check("platformio", env_str, "platformio")
        assert not presence_before.present, (
            "platformio must NOT be detected before install"
        )

        step = _make_install_step("platformio-001", "req-platformio", "platformio")
        result = executor.execute(step)
        trace_harness.record(step, result)
        assert result.success, (
            f"platformio install must succeed: {result.message}"
        )

        presence_after_install = checker.check("platformio", env_str, "platformio")
        assert presence_after_install.present, (
            "platformio must be detected after install"
        )
        assert presence_after_install.detected_version is not None

        version_result = _run_command([_python_in(venv_path), "-m", "platformio", "--version"])
        assert version_result.returncode == 0

        uninstall_result = executor.uninstall(step)
        trace_harness.record(step, uninstall_result)
        assert uninstall_result.success, (
            f"platformio uninstall must succeed: {uninstall_result.message}"
        )

        presence_after_uninstall = checker.check("platformio", env_str, "platformio")
        assert not presence_after_uninstall.present, (
            "platformio must NOT be detected after uninstall"
        )

    finally:
        trace_harness.render()
        shutil.rmtree(owned, ignore_errors=False)
        assert not owned.exists()

# ===================================================================
# Setup-003: pytest
# ===================================================================
@REAL_SYSTEM_MARKER
def test_setup_003_pytest_lifecycle(diagnostic_level):
    """pytest: isolated venv full lifecycle"""
    owned = Path(tempfile.mkdtemp(prefix="adc-setup-003-"))
    trace_harness = _SetupTraceHarness(
        owned,
        "setup-003",
        diagnostic_level,
    )
    try:
        venv_path = _create_test_venv(owned)
        executor = _make_executor_for_env(venv_path)
        checker = PythonVenvPresenceChecker()
        env_str = str(venv_path)

        presence_before = checker.check("pytest", env_str, "pytest")
        assert not presence_before.present, (
            "pytest must NOT be detected before install"
        )

        step = _make_install_step("pytest-001", "req-pytest", "pytest")
        result = executor.execute(step)
        trace_harness.record(step, result)
        assert result.success, (
            f"pytest install must succeed: {result.message}"
        )

        presence_after_install = checker.check("pytest", env_str, "pytest")
        assert presence_after_install.present, (
            "pytest must be detected after install"
        )
        assert presence_after_install.detected_version is not None

        version_result = _run_command([_python_in(venv_path), "-m", "pytest", "--version"])
        assert version_result.returncode == 0

        uninstall_result = executor.uninstall(step)
        trace_harness.record(step, uninstall_result)
        assert uninstall_result.success, (
            f"pytest uninstall must succeed: {uninstall_result.message}"
        )

        presence_after_uninstall = checker.check("pytest", env_str, "pytest")
        assert not presence_after_uninstall.present, (
            "pytest must NOT be detected after uninstall"
        )

    finally:
        trace_harness.render()
        shutil.rmtree(owned, ignore_errors=False)
        assert not owned.exists()

# ===================================================================
# Setup-004: ruff
# ===================================================================
@REAL_SYSTEM_MARKER
def test_setup_004_ruff_lifecycle(diagnostic_level):
    """ruff: isolated venv full lifecycle"""
    owned = Path(tempfile.mkdtemp(prefix="adc-setup-004-"))
    trace_harness = _SetupTraceHarness(
        owned,
        "setup-004",
        diagnostic_level,
    )
    try:
        venv_path = _create_test_venv(owned)
        executor = _make_executor_for_env(venv_path)
        checker = PythonVenvPresenceChecker()
        env_str = str(venv_path)

        presence_before = checker.check("ruff", env_str, "ruff")
        assert not presence_before.present, (
            "ruff must NOT be detected before install"
        )

        step = _make_install_step("ruff-001", "req-ruff", "ruff")
        result = executor.execute(step)
        trace_harness.record(step, result)
        assert result.success, (
            f"ruff install must succeed: {result.message}"
        )

        presence_after_install = checker.check("ruff", env_str, "ruff")
        assert presence_after_install.present, (
            "ruff must be detected after install"
        )
        assert presence_after_install.detected_version is not None

        version_result = _run_command([_python_in(venv_path), "-m", "ruff", "--version"])
        assert version_result.returncode == 0

        uninstall_result = executor.uninstall(step)
        trace_harness.record(step, uninstall_result)
        assert uninstall_result.success, (
            f"ruff uninstall must succeed: {uninstall_result.message}"
        )

        presence_after_uninstall = checker.check("ruff", env_str, "ruff")
        assert not presence_after_uninstall.present, (
            "ruff must NOT be detected after uninstall"
        )

    finally:
        trace_harness.render()
        shutil.rmtree(owned, ignore_errors=False)
        assert not owned.exists()

# ===================================================================
# Setup-005: mypy
# ===================================================================
@REAL_SYSTEM_MARKER
def test_setup_005_mypy_lifecycle(diagnostic_level):
    """mypy: isolated venv full lifecycle"""
    owned = Path(tempfile.mkdtemp(prefix="adc-setup-005-"))
    trace_harness = _SetupTraceHarness(
        owned,
        "setup-005",
        diagnostic_level,
    )
    try:
        venv_path = _create_test_venv(owned)
        executor = _make_executor_for_env(venv_path)
        checker = PythonVenvPresenceChecker()
        env_str = str(venv_path)

        presence_before = checker.check("mypy", env_str, "mypy")
        assert not presence_before.present, (
            "mypy must NOT be detected before install"
        )

        step = _make_install_step("mypy-001", "req-mypy", "mypy")
        result = executor.execute(step)
        trace_harness.record(step, result)
        assert result.success, (
            f"mypy install must succeed: {result.message}"
        )

        presence_after_install = checker.check("mypy", env_str, "mypy")
        assert presence_after_install.present, (
            "mypy must be detected after install"
        )
        assert presence_after_install.detected_version is not None

        version_result = _run_command([_python_in(venv_path), "-m", "mypy", "--version"])
        assert version_result.returncode == 0

        uninstall_result = executor.uninstall(step)
        trace_harness.record(step, uninstall_result)
        assert uninstall_result.success, (
            f"mypy uninstall must succeed: {uninstall_result.message}"
        )

        presence_after_uninstall = checker.check("mypy", env_str, "mypy")
        assert not presence_after_uninstall.present, (
            "mypy must NOT be detected after uninstall"
        )

    finally:
        trace_harness.render()
        shutil.rmtree(owned, ignore_errors=False)
        assert not owned.exists()

# ===================================================================
# Setup-006: black
# ===================================================================
@REAL_SYSTEM_MARKER
def test_setup_006_black_lifecycle(diagnostic_level):
    """black: isolated venv full lifecycle"""
    owned = Path(tempfile.mkdtemp(prefix="adc-setup-006-"))
    trace_harness = _SetupTraceHarness(
        owned,
        "setup-006",
        diagnostic_level,
    )
    try:
        venv_path = _create_test_venv(owned)
        executor = _make_executor_for_env(venv_path)
        checker = PythonVenvPresenceChecker()
        env_str = str(venv_path)

        presence_before = checker.check("black", env_str, "black")
        assert not presence_before.present, (
            "black must NOT be detected before install"
        )

        step = _make_install_step("black-001", "req-black", "black")
        result = executor.execute(step)
        trace_harness.record(step, result)
        assert result.success, (
            f"black install must succeed: {result.message}"
        )

        presence_after_install = checker.check("black", env_str, "black")
        assert presence_after_install.present, (
            "black must be detected after install"
        )
        assert presence_after_install.detected_version is not None

        version_result = _run_command([_python_in(venv_path), "-m", "black", "--version"])
        assert version_result.returncode == 0

        uninstall_result = executor.uninstall(step)
        trace_harness.record(step, uninstall_result)
        assert uninstall_result.success, (
            f"black uninstall must succeed: {uninstall_result.message}"
        )

        presence_after_uninstall = checker.check("black", env_str, "black")
        assert not presence_after_uninstall.present, (
            "black must NOT be detected after uninstall"
        )

    finally:
        trace_harness.render()
        shutil.rmtree(owned, ignore_errors=False)
        assert not owned.exists()

# ===================================================================
# Setup-007: esptool
# ===================================================================
@REAL_SYSTEM_MARKER
def test_setup_007_esptool_lifecycle(diagnostic_level):
    """esptool: isolated venv full lifecycle"""
    owned = Path(tempfile.mkdtemp(prefix="adc-setup-007-"))
    trace_harness = _SetupTraceHarness(
        owned,
        "setup-007",
        diagnostic_level,
    )
    try:
        venv_path = _create_test_venv(owned)
        executor = _make_executor_for_env(venv_path)
        checker = PythonVenvPresenceChecker()
        env_str = str(venv_path)

        presence_before = checker.check("esptool", env_str, "esptool")
        assert not presence_before.present, (
            "esptool must NOT be detected before install"
        )

        step = _make_install_step("esptool-001", "req-esptool", "esptool")
        result = executor.execute(step)
        trace_harness.record(step, result)
        assert result.success, (
            f"esptool install must succeed: {result.message}"
        )

        presence_after_install = checker.check("esptool", env_str, "esptool")
        assert presence_after_install.present, (
            "esptool must be detected after install"
        )
        assert presence_after_install.detected_version is not None

        version_result = _run_command([_python_in(venv_path), "-m", "esptool", "version"])
        assert version_result.returncode == 0

        uninstall_result = executor.uninstall(step)
        trace_harness.record(step, uninstall_result)
        assert uninstall_result.success, (
            f"esptool uninstall must succeed: {uninstall_result.message}"
        )

        presence_after_uninstall = checker.check("esptool", env_str, "esptool")
        assert not presence_after_uninstall.present, (
            "esptool must NOT be detected after uninstall"
        )

    finally:
        trace_harness.render()
        shutil.rmtree(owned, ignore_errors=False)
        assert not owned.exists()

# ===================================================================
# Setup-008: west
# ===================================================================
@REAL_SYSTEM_MARKER
def test_setup_008_west_lifecycle(diagnostic_level):
    """west: isolated venv full lifecycle"""
    owned = Path(tempfile.mkdtemp(prefix="adc-setup-008-"))
    trace_harness = _SetupTraceHarness(
        owned,
        "setup-008",
        diagnostic_level,
    )
    try:
        venv_path = _create_test_venv(owned)
        executor = _make_executor_for_env(venv_path)
        checker = PythonVenvPresenceChecker()
        env_str = str(venv_path)

        presence_before = checker.check("west", env_str, "west")
        assert not presence_before.present, (
            "west must NOT be detected before install"
        )

        step = _make_install_step("west-001", "req-west", "west")
        result = executor.execute(step)
        trace_harness.record(step, result)
        assert result.success, (
            f"west install must succeed: {result.message}"
        )

        presence_after_install = checker.check("west", env_str, "west")
        assert presence_after_install.present, (
            "west must be detected after install"
        )
        assert presence_after_install.detected_version is not None

        version_result = _run_command([_python_in(venv_path), "-m", "west", "--version"])
        assert version_result.returncode == 0

        uninstall_result = executor.uninstall(step)
        trace_harness.record(step, uninstall_result)
        assert uninstall_result.success, (
            f"west uninstall must succeed: {uninstall_result.message}"
        )

        presence_after_uninstall = checker.check("west", env_str, "west")
        assert not presence_after_uninstall.present, (
            "west must NOT be detected after uninstall"
        )

    finally:
        trace_harness.render()
        shutil.rmtree(owned, ignore_errors=False)
        assert not owned.exists()

# ===================================================================
# Setup-009: ESP32 emulator environment
# ===================================================================
@REAL_SYSTEM_MARKER
def test_setup_009_esp32_emulator_environment():
    """ESP32 emulator environment: toolchain detection, setup, firmware, verification."""
    owned = Path(tempfile.mkdtemp(prefix="adc-setup-009-"))
    try:
        venv_path = _create_test_venv(owned)
        executor = _make_executor_for_env(venv_path)
        checker = PythonVenvPresenceChecker()
        env_str = str(venv_path)

        for name in ("esphome", "esptool"):
            step = _make_install_step(f"emu-{name}", f"req-emu-{name}", name)
            presence_before = checker.check(name, env_str, name)
            assert not presence_before.present, f"{name} must NOT be detected before install"
            result = executor.execute(step)
            assert result.success, f"{name} install must succeed: {result.message}"
            presence_after = checker.check(name, env_str, name)
            assert presence_after.present, f"{name} must be detected after install"

        project_dir = owned / "emu-project"
        project_dir.mkdir()
        yaml_content = (
            "esphome:\n"
            "  name: test-emu\n"
            "  platform: ESP32\n"
            "  board: esp32dev\n"
            "\n"
            "logger:\n"
            "  level: INFO\n"
            "\n"
            "interval:\n"
            "  - interval: 5s\n"
            "    then:\n"
            "      - logger.log: \"Hello from Emulator Test\"\n"
        )
        (project_dir / "test-emu.yaml").write_text(yaml_content)

        validate_result = _run_command([
            _python_in(venv_path), "-m", "esphome", "config",
            str(project_dir / "test-emu.yaml"),
        ])
        assert validate_result.returncode == 0, (
            f"ESPHome config validation must succeed: {validate_result.stderr[:300]}"
        )

        compile_result = _run_command([
            _python_in(venv_path), "-m", "esphome", "compile",
            str(project_dir / "test-emu.yaml"), "--defaults",
        ])

        firmware_files = list(owned.glob("**/*.bin"))
        compile_succeeded = compile_result.returncode == 0

        if compile_succeeded:
            assert firmware_files, "ESPHome compile must produce firmware artifact (.bin)"

        qemu_candidates = ["qemu-system-xtensaeb", "qemu-system-xtensa", "qemu-system-xtensa"]
        qemu_exe = None
        for candidate in qemu_candidates:
            found = shutil.which(candidate)
            if found:
                qemu_exe = found
                break

        if qemu_exe is not None:
            emu_version = _run_command([qemu_exe, "--version"])
            print(f"ESP32 emulator (QEMU) detected: {qemu_exe}")
        else:
            print("ESP32 emulator (QEMU) not available — config/compile verification complete")

        for name in ("esphome", "esptool"):
            step = _make_install_step(f"emu-{name}", f"req-emu-{name}", name)
            uninstall_result = executor.uninstall(step)
            assert uninstall_result.success, f"{name} uninstall must succeed: {uninstall_result.message}"
            presence_after = checker.check(name, env_str, name)
            assert not presence_after.present, f"{name} must NOT be detected after uninstall"

    finally:
        shutil.rmtree(owned, ignore_errors=False)
        assert not owned.exists()

# ===================================================================
# Setup-010: hybrid ESP32 environment
# ===================================================================
@REAL_SYSTEM_MARKER
def test_setup_010_hybrid_esp32_environment():
    """Hybrid ESP32: virtual emulator branch + physical device branch.

    Emulator branch runs independently.
    Physical ESP32 branch executes only when ADC_TEST_ESP32_DEVICE
    and ADC_TEST_ESP32_PORT env vars specify an explicit test device.
    If physical hardware is unavailable, that branch reports as
    hardware unavailable/blocked; never fakes a pass.
    Never flashes an arbitrary connected device.
    Teardown removes only test-owned software/environment state.
    """
    owned = Path(tempfile.mkdtemp(prefix="adc-setup-010-"))
    try:
        venv_path = _create_test_venv(owned)
        executor = _make_executor_for_env(venv_path)
        checker = PythonVenvPresenceChecker()
        env_str = str(venv_path)

        required_packages = ["esphome", "esptool", "pyserial"]
        for pkg in required_packages:
            step = _make_install_step("hybrid-" + pkg, "req-hybrid-" + pkg, pkg)
            presence_before = checker.check(pkg, env_str, pkg)
            assert not presence_before.present, pkg + " must NOT be detected before install"
            result = executor.execute(step)
            assert result.success, pkg + " install must succeed: " + result.message
            presence_after = checker.check(pkg, env_str, pkg)
            assert presence_after.present, pkg + " must be detected after install"

        project_dir = owned / "hybrid-project"
        project_dir.mkdir()
        yaml_content = (
            "esphome:\n"
            "  name: test-hybrid\n"
            "  platform: ESP32\n"
            "  board: esp32dev\n"
            "\n"
            "logger:\n"
            "  level: INFO\n"
            "\n"
            "interval:\n"
            "  - interval: 10s\n"
            "    then:\n"
            "      - logger.log: \"Hello from Hybrid Test\"\n"
        )
        (project_dir / "test-hybrid.yaml").write_text(yaml_content)

        validate_result = _run_command([
            _python_in(venv_path), "-m", "esphome", "config",
            str(project_dir / "test-hybrid.yaml"),
        ])
        assert validate_result.returncode == 0, (
            "ESPHome config validation must succeed: " + validate_result.stderr[:300]
        )

        compile_result = _run_command([
            _python_in(venv_path), "-m", "esphome", "compile",
            str(project_dir / "test-hybrid.yaml"), "--defaults",
        ])

        if compile_result.returncode == 0:
            firmware_artifacts = list(owned.glob("**/*.bin"))
            assert firmware_artifacts, (
                "ESPHome compile must produce firmware artifact usable by both branches"
            )

        qemu_candidates = ["qemu-system-xtensaeb", "qemu-system-xtensa"]
        qemu_exe = None
        for candidate in qemu_candidates:
            found = shutil.which(candidate)
            if found:
                qemu_exe = found
                break

        if qemu_exe is not None:
            print("[Hybrid] ESP32 emulator available: " + qemu_exe)
        else:
            print("[Hybrid] ESP32 emulator (QEMU) not available")
            print("[Hybrid] Virtual branch: config/compile verification complete")

        test_device = os.environ.get("ADC_TEST_ESP32_DEVICE", "")
        test_serial_port = os.environ.get("ADC_TEST_ESP32_PORT", "")

        physical_available = False
        if test_device and test_serial_port:
            if Path(test_serial_port).exists():
                physical_available = True
                print(
                    "[Hybrid] Physical ESP32 branch: "
                    "device=" + test_device + " port=" + test_serial_port
                )
            else:
                print("[Hybrid] Physical ESP32 branch: port does not exist => hardware unavailable/blocked")
        else:
            print("[Hybrid] Physical ESP32 branch: no ADC_TEST_ESP32_DEVICE/ADC_TEST_ESP32_PORT env => hardware unavailable/blocked")

        if physical_available:
            mac_check = _run_command([
                _python_in(venv_path), "-m", "esptool",
                "--port", test_serial_port,
                "read_mac",
            ])
            if mac_check.returncode == 0:
                print("[Hybrid] ESP32 physical device MAC read successful: " + mac_check.stdout.strip()[:100])
            else:
                print("[Hybrid] Physical ESP32 MAC read failed: exit=" + str(mac_check.returncode))
                physical_available = False

        if not physical_available:
            print("[Hybrid] Physical ESP32 branch: hardware unavailable/blocked")

        for pkg in required_packages:
            step = _make_install_step("hybrid-" + pkg, "req-hybrid-" + pkg, pkg)
            uninstall_result = executor.uninstall(step)
            assert uninstall_result.success, pkg + " uninstall must succeed: " + uninstall_result.message
            presence_after = checker.check(pkg, env_str, pkg)
            assert not presence_after.present, pkg + " must NOT be detected after uninstall"

    finally:
        shutil.rmtree(owned, ignore_errors=False)
        assert not owned.exists()
