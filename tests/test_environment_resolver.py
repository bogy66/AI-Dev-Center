import pytest
from app.test_requirements import TestRequirements
from app.esp32_preflight import PreflightResult
from app.environment_resolver import EnvironmentResolver, EnvironmentPlan


class TestEnvironmentResolver:

    @pytest.fixture
    def resolver(self):
        return EnvironmentResolver()

    # ------------------------------------------------------------------
    # 1. All requirements fulfilled → ready=True
    # ------------------------------------------------------------------
    def test_all_fulfilled(self, resolver: EnvironmentResolver):
        req = TestRequirements(
            executables=["python", "esphome"],
            capabilities=["build", "flash"],
            target="esp32",
            connection="serial"
        )
        preflight = PreflightResult(
            available_executables=["python", "esphome"],
            serial_ports=["/dev/ttyUSB0"]
        )
        plan = resolver.resolve(req, preflight)
        assert plan.ready is True
        assert plan.missing == []

    # ------------------------------------------------------------------
    # 2. Required executable missing → ready=False
    # ------------------------------------------------------------------
    def test_executable_missing(self, resolver: EnvironmentResolver):
        req = TestRequirements(executables=["python", "esphome"])
        preflight = PreflightResult(
            available_executables=["python"],
            serial_ports=["/dev/ttyUSB0"]
        )
        plan = resolver.resolve(req, preflight)
        assert plan.ready is False
        assert "esphome" in plan.missing

    # ------------------------------------------------------------------
    # 3. Multiple executables missing → all reported
    # ------------------------------------------------------------------
    def test_multiple_executables_missing(self, resolver: EnvironmentResolver):
        req = TestRequirements(executables=["python", "esphome"])
        preflight = PreflightResult(
            available_executables=[],
            serial_ports=["/dev/ttyUSB0"]
        )
        plan = resolver.resolve(req, preflight)
        assert plan.ready is False
        assert "python" in plan.missing
        assert "esphome" in plan.missing

    # ------------------------------------------------------------------
    # 4. Unknown executable missing → ready=False
    # ------------------------------------------------------------------
    def test_unknown_executable_missing(self, resolver: EnvironmentResolver):
        req = TestRequirements(executables=["custom-flasher"])
        preflight = PreflightResult(
            available_executables=[],
            serial_ports=["/dev/ttyUSB0"]
        )
        plan = resolver.resolve(req, preflight)
        assert plan.ready is False
        assert "custom-flasher" in plan.missing

    # ------------------------------------------------------------------
    # 5. Serial connection + port present → ready=True
    # ------------------------------------------------------------------
    def test_serial_with_port(self, resolver: EnvironmentResolver):
        req = TestRequirements(connection="serial")
        preflight = PreflightResult(
            available_executables=[],
            serial_ports=["/dev/ttyUSB0"]
        )
        plan = resolver.resolve(req, preflight)
        assert plan.ready is True

    # ------------------------------------------------------------------
    # 6. Serial connection + no port → ready=False
    # ------------------------------------------------------------------
    def test_serial_without_port(self, resolver: EnvironmentResolver):
        req = TestRequirements(connection="serial")
        preflight = PreflightResult(
            available_executables=[],
            serial_ports=[]
        )
        plan = resolver.resolve(req, preflight)
        assert plan.ready is False
        assert any("Port" in msg for msg in plan.missing)

    # ------------------------------------------------------------------
    # 7. Unknown connection type is not treated as serial
    # ------------------------------------------------------------------
    def test_unknown_connection(self, resolver: EnvironmentResolver):
        req = TestRequirements(connection="wifi")
        preflight = PreflightResult(
            available_executables=[],
            serial_ports=[]
        )
        plan = resolver.resolve(req, preflight)
        # Unknown connection cannot be verified, but should not
        # cause a missing entry for serial port.
        assert plan.ready is True
        assert any("wifi" in w for w in plan.warnings)

    # ------------------------------------------------------------------
    # 8. Python package requirements are not verified by invented logic
    # ------------------------------------------------------------------
    def test_python_packages_not_verified(self, resolver: EnvironmentResolver):
        req = TestRequirements(python_packages=["esphome", "pyserial"])
        preflight = PreflightResult(
            available_executables=[],
            serial_ports=["/dev/ttyUSB0"]
        )
        plan = resolver.resolve(req, preflight)
        # Should not add missing entries for packages
        assert plan.ready is True
        assert any("package" in w.lower() for w in plan.warnings)

    # ------------------------------------------------------------------
    # 9. Unknown target is not treated with stack‑specific logic
    # ------------------------------------------------------------------
    def test_unknown_target(self, resolver: EnvironmentResolver):
        req = TestRequirements(target="some-board")
        preflight = PreflightResult(
            available_executables=[],
            serial_ports=["/dev/ttyUSB0"]
        )
        plan = resolver.resolve(req, preflight)
        assert plan.ready is True
        assert any("some-board" in w for w in plan.warnings)

    # ------------------------------------------------------------------
    # 10. Empty requirements on a suitable preflight → ready=True
    # ------------------------------------------------------------------
    def test_empty_requirements(self, resolver: EnvironmentResolver):
        req = TestRequirements()
        preflight = PreflightResult(
            available_executables=[],
            serial_ports=["/dev/ttyUSB0"]
        )
        plan = resolver.resolve(req, preflight)
        assert plan.ready is True
        assert plan.missing == []

    # ------------------------------------------------------------------
    # 11. No real hardware needed
    # ------------------------------------------------------------------
    def test_no_real_hardware(self, resolver: EnvironmentResolver):
        req = TestRequirements(executables=["python"])
        preflight = PreflightResult(
            available_executables=["python"],
            serial_ports=[]
        )
        plan = resolver.resolve(req, preflight)
        # only python required, which is present
        assert plan.ready is True
        # serial port missing but not required
        assert "Kein ESP32/serieller Port gefunden." not in plan.missing
