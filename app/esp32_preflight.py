import shutil
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class PreflightResult:
    ready: bool = False
    esphome_available: bool = False
    python_available: bool = False
    serial_ports: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    available_executables: list[str] = field(default_factory=list)


class ESP32Preflight:
    """Checks whether the local environment is ready for ESPHome/ESP32 testing.

    All external dependencies (shutil.which, serial port detection) are
    injected via callables so that unit tests can replace them with mocks.
    """

    def __init__(
        self,
        which: Callable[[str], str | None] = shutil.which,
        list_ports: Callable[[], list[str]] | None = None,
    ):
        self._which = which
        self._list_ports = list_ports

    def check(self) -> PreflightResult:
        result = PreflightResult()

        # 1. Python availability
        python_path = self._which("python")
        if python_path is None:
            python_path = self._which("python3")
        result.python_available = python_path is not None
        if not result.python_available:
            result.missing.append("Python")
        else:
            result.available_executables.append("python")

        # 2. ESPHome availability
        esphome_path = self._which("esphome")
        result.esphome_available = esphome_path is not None
        if not result.esphome_available:
            result.missing.append("ESPHome")
        else:
            result.available_executables.append("esphome")

        # 3. Serial ports
        if self._list_ports is not None:
            try:
                ports = self._list_ports()
                result.serial_ports = list(ports)
            except Exception as exc:
                result.warnings.append(
                    f"Could not list serial ports: {exc}"
                )
        else:
            # pyserial not available – fallback unavailable
            result.warnings.append(
                "pyserial not available; serial port detection skipped."
            )

        # 4. Always add missing entry when no serial ports are found
        if not result.serial_ports:
            result.missing.append("Kein ESP32/serieller Port gefunden.")

        # 5. Compute overall readiness
        result.ready = (
            result.python_available
            and result.esphome_available
            and bool(result.serial_ports)
        )

        return result
