from dataclasses import dataclass, field
from app.test_requirements import TestRequirements
from app.esp32_preflight import PreflightResult


@dataclass
class EnvironmentPlan:
    ready: bool = False
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class EnvironmentResolver:
    """Resolves whether the environment is ready for a given set of requirements,
    based on a PreflightResult.

    The resolver is stack‑neutral and does not contain any ESPHome, ESP32,
    pytest or other framework‑specific logic.
    """

    def resolve(
        self,
        requirements: TestRequirements,
        preflight: PreflightResult,
    ) -> EnvironmentPlan:
        plan = EnvironmentPlan()
        missing = []
        warnings = []

        # 1. Check executables generically
        for exe in requirements.executables:
            if exe not in preflight.available_executables:
                missing.append(exe)

        # 2. Python packages – cannot verify
        if requirements.python_packages:
            warnings.append(
                "Python package requirements could not be verified "
                "by the current preflight."
            )

        # 3. Capabilities – cannot verify
        if requirements.capabilities:
            warnings.append(
                "Capability requirements could not be verified "
                "by the current preflight."
            )

        # 4. Target – cannot verify
        if requirements.target:
            warnings.append(
                f"Target '{requirements.target}' could not be verified "
                "by the current preflight."
            )

        # 5. Connection
        if requirements.connection == "serial":
            if not preflight.serial_ports:
                missing.append(
                    "Kein ESP32/serieller Port gefunden."
                )
        elif requirements.connection:
            # Unknown connection type – cannot verify
            warnings.append(
                f"Connection type '{requirements.connection}' could not "
                "be verified by the current preflight."
            )

        plan.missing = missing
        plan.warnings = warnings
        plan.ready = len(missing) == 0
        return plan
