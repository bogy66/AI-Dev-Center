import pytest
from app.esp32_preflight import ESP32Preflight, PreflightResult


class TestESP32Preflight:

    # ------------------------------------------------------------------
    # Helper: create a mock `which` that returns a path for given commands
    # ------------------------------------------------------------------
    @staticmethod
    def _mock_which(available: set[str]):
        def which(cmd: str) -> str | None:
            if cmd in available:
                return f"/usr/bin/{cmd}"
            return None
        return which

    # ------------------------------------------------------------------
    # 1. Everything present → ready=True
    # ------------------------------------------------------------------
    def test_all_present(self):
        which = self._mock_which({"python", "esphome"})
        preflight = ESP32Preflight(
            which=which,
            list_ports=lambda: ["/dev/ttyUSB0"]
        )
        result = preflight.check()
        assert result.ready is True
        assert result.python_available is True
        assert result.esphome_available is True
        assert result.serial_ports == ["/dev/ttyUSB0"]
        assert result.missing == []
        assert "python" in result.available_executables
        assert "esphome" in result.available_executables

    # ------------------------------------------------------------------
    # 2. ESPHome missing → ready=False
    # ------------------------------------------------------------------
    def test_esphome_missing(self):
        which = self._mock_which({"python"})
        preflight = ESP32Preflight(
            which=which,
            list_ports=lambda: ["/dev/ttyUSB0"]
        )
        result = preflight.check()
        assert result.ready is False
        assert result.esphome_available is False
        assert "ESPHome" in result.missing
        assert "python" in result.available_executables
        assert "esphome" not in result.available_executables

    # ------------------------------------------------------------------
    # 3. Python missing → ready=False
    # ------------------------------------------------------------------
    def test_python_missing(self):
        which = self._mock_which({"esphome"})
        preflight = ESP32Preflight(
            which=which,
            list_ports=lambda: ["/dev/ttyUSB0"]
        )
        result = preflight.check()
        assert result.ready is False
        assert result.python_available is False
        assert "Python" in result.missing
        assert "python" not in result.available_executables
        assert "esphome" in result.available_executables

    # ------------------------------------------------------------------
    # 4. No serial port → ready=False
    # ------------------------------------------------------------------
    def test_no_serial_port(self):
        which = self._mock_which({"python", "esphome"})
        preflight = ESP32Preflight(
            which=which,
            list_ports=lambda: []
        )
        result = preflight.check()
        assert result.ready is False
        assert "Kein ESP32/serieller Port gefunden." in result.missing

    # ------------------------------------------------------------------
    # 5. ESPHome and Python present, but no ESP32 → informative message
    # ------------------------------------------------------------------
    def test_no_esp32_informative(self):
        which = self._mock_which({"python", "esphome"})
        preflight = ESP32Preflight(
            which=which,
            list_ports=lambda: []
        )
        result = preflight.check()
        assert result.ready is False
        assert any("Port" in msg for msg in result.missing)

    # ------------------------------------------------------------------
    # 6. Multiple serial ports are detected
    # ------------------------------------------------------------------
    def test_multiple_serial_ports(self):
        which = self._mock_which({"python", "esphome"})
        preflight = ESP32Preflight(
            which=which,
            list_ports=lambda: ["/dev/ttyUSB0", "/dev/ttyUSB1"]
        )
        result = preflight.check()
        assert result.ready is True
        assert len(result.serial_ports) == 2

    # ------------------------------------------------------------------
    # 7. Missing list is correctly populated
    # ------------------------------------------------------------------
    def test_missing_list(self):
        which = self._mock_which(set())
        preflight = ESP32Preflight(
            which=which,
            list_ports=lambda: []
        )
        result = preflight.check()
        assert "Python" in result.missing
        assert "ESPHome" in result.missing
        assert "Kein ESP32/serieller Port gefunden." in result.missing
        assert result.available_executables == []

    # ------------------------------------------------------------------
    # 8. Warnings are correctly handled (pyserial not available)
    # ------------------------------------------------------------------
    def test_warning_when_no_list_ports(self):
        which = self._mock_which({"python", "esphome"})
        # No list_ports callable provided → fallback warning
        preflight = ESP32Preflight(which=which, list_ports=None)
        result = preflight.check()
        assert any("pyserial not available" in w for w in result.warnings)

    # ------------------------------------------------------------------
    # 9. Tests work without real hardware
    # ------------------------------------------------------------------
    def test_no_real_hardware_needed(self):
        # This test itself proves the point: no real hardware is accessed.
        which = self._mock_which({"python", "esphome"})
        preflight = ESP32Preflight(
            which=which,
            list_ports=lambda: ["/dev/ttyUSB0"]
        )
        result = preflight.check()
        assert result.ready is True

    # ------------------------------------------------------------------
    # 10. Tests work without real ESPHome installation
    # ------------------------------------------------------------------
    def test_no_real_esphome_needed(self):
        which = self._mock_which({"python"})
        preflight = ESP32Preflight(
            which=which,
            list_ports=lambda: ["/dev/ttyUSB0"]
        )
        result = preflight.check()
        assert result.ready is False
        assert result.esphome_available is False

    # ------------------------------------------------------------------
    # 11. available_executables reflects python3 when python is not found
    # ------------------------------------------------------------------
    def test_available_executables_with_python3(self):
        def which(cmd: str) -> str | None:
            if cmd == "python":
                return None
            if cmd == "python3":
                return "/usr/bin/python3"
            if cmd == "esphome":
                return "/usr/bin/esphome"
            return None

        preflight = ESP32Preflight(
            which=which,
            list_ports=lambda: ["/dev/ttyUSB0"]
        )
        result = preflight.check()
        # python_available should be True because python3 was found
        assert result.python_available is True
        # The executable name stored is "python" (the generic name)
        assert "python" in result.available_executables
        assert "esphome" in result.available_executables
