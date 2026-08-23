import pytest
from app.test_requirements import TestRequirements


class TestTestRequirements:

    def test_empty_requirements(self):
        req = TestRequirements()
        assert req.executables == []
        assert req.python_packages == []
        assert req.capabilities == []
        assert req.target == ""
        assert req.connection == ""

    def test_executables_are_stored(self):
        req = TestRequirements(executables=["python", "esphome"])
        assert req.executables == ["python", "esphome"]

    def test_python_packages_are_stored(self):
        req = TestRequirements(python_packages=["esphome", "pyserial"])
        assert req.python_packages == ["esphome", "pyserial"]

    def test_capabilities_are_stored(self):
        req = TestRequirements(capabilities=["build", "flash", "serial_log"])
        assert req.capabilities == ["build", "flash", "serial_log"]

    def test_target_is_stored(self):
        req = TestRequirements(target="esp32")
        assert req.target == "esp32"

    def test_connection_is_stored(self):
        req = TestRequirements(connection="serial")
        assert req.connection == "serial"

    def test_esphome_like_requirements(self):
        req = TestRequirements(
            executables=["python", "esphome"],
            capabilities=["build", "flash", "serial_log"],
            target="esp32",
            connection="serial"
        )
        assert req.executables == ["python", "esphome"]
        assert req.capabilities == ["build", "flash", "serial_log"]
        assert req.target == "esp32"
        assert req.connection == "serial"

    def test_esp_idf_like_requirements(self):
        req = TestRequirements(
            executables=["python", "idf.py"],
            capabilities=["build", "flash", "serial_log"],
            target="esp32",
            connection="serial"
        )
        assert req.executables == ["python", "idf.py"]
        assert req.capabilities == ["build", "flash", "serial_log"]
        assert req.target == "esp32"
        assert req.connection == "serial"

    def test_unknown_custom_requirements(self):
        req = TestRequirements(
            executables=["custom-tool"],
            python_packages=["custom-package"],
            capabilities=["deploy", "monitor"],
            target="some-board",
            connection="wifi"
        )
        assert req.executables == ["custom-tool"]
        assert req.python_packages == ["custom-package"]
        assert req.capabilities == ["deploy", "monitor"]
        assert req.target == "some-board"
        assert req.connection == "wifi"

    def test_immutable(self):
        req = TestRequirements(executables=["python"])
        with pytest.raises(AttributeError):
            req.executables = []
        with pytest.raises(AttributeError):
            req.target = "other"
