from dataclasses import dataclass, field
from app.test_requirements import TestRequirements
from app.environment_resolver import EnvironmentPlan


@dataclass
class SetupStep:
    """Describes a single setup action that needs to be performed."""
    requirement: str
    kind: str  # "install_python_package", "hardware_required", "unknown"
    action: str
    automatic: bool
    reason: str


class SetupPlanner:
    """Plans which setup steps are needed based on requirements and
    the current environment plan.

    The planner is stack‑neutral and does not perform any installation.
    """

    # Known Python packages that can be installed automatically
    _KNOWN_PYTHON_PACKAGES = {
        "esphome",
        "pyserial",
    }

    def plan(
        self,
        requirements: TestRequirements,
        plan: EnvironmentPlan,
    ) -> list[SetupStep]:
        steps: list[SetupStep] = []

        # 1. Missing executables
        for exe in requirements.executables:
            if exe in plan.missing:
                step = self._classify_executable(exe)
                steps.append(step)

        # 2. Missing Python packages (already in requirements, but
        #    we also check if the executable requirement included them)
        #    We treat python_packages from requirements as well.
        for pkg in requirements.python_packages:
            if pkg in self._KNOWN_PYTHON_PACKAGES:
                steps.append(SetupStep(
                    requirement=pkg,
                    kind="install_python_package",
                    action=f"pip install {pkg}",
                    automatic=True,
                    reason=f"Python package '{pkg}' is not installed."
                ))
            else:
                steps.append(SetupStep(
                    requirement=pkg,
                    kind="unknown",
                    action="",
                    automatic=False,
                    reason=f"Python package '{pkg}' could not be "
                           f"automatically resolved."
                ))

        # 3. Missing serial port (hardware)
        if not plan.missing:
            pass  # no missing items
        else:
            for missing_item in plan.missing:
                # If it's already handled as an executable or package,
                # skip. We only add hardware/unknown items here.
                if missing_item in requirements.executables:
                    continue
                # Check if it's a known Python package (already handled above)
                if missing_item in self._KNOWN_PYTHON_PACKAGES:
                    continue
                # If the missing item is the serial port message
                if "Port" in missing_item or "seriell" in missing_item:
                    steps.append(SetupStep(
                        requirement=missing_item,
                        kind="hardware_required",
                        action="",
                        automatic=False,
                        reason=missing_item
                    ))
                else:
                    steps.append(SetupStep(
                        requirement=missing_item,
                        kind="unknown",
                        action="",
                        automatic=False,
                        reason=missing_item
                    ))

        # 4. Remove duplicates (by requirement)
        seen = set()
        unique_steps = []
        for step in steps:
            if step.requirement not in seen:
                seen.add(step.requirement)
                unique_steps.append(step)

        return unique_steps

    def _classify_executable(self, exe: str) -> SetupStep:
        # Check if the executable is known to be installable as a Python package
        if exe in self._KNOWN_PYTHON_PACKAGES:
            return SetupStep(
                requirement=exe,
                kind="install_python_package",
                action=f"pip install {exe}",
                automatic=True,
                reason=f"Executable '{exe}' is missing but can be installed "
                       f"as a Python package."
            )
        else:
            return SetupStep(
                requirement=exe,
                kind="unknown",
                action="",
                automatic=False,
                reason=f"Executable '{exe}' is missing and no automatic "
                       f"installation strategy is known."
            )
