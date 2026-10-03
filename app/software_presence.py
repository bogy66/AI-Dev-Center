"""Reusable software/component presence detection.

Presence checks operate against an explicitly selected target environment.
They must not accidentally discover software from ADC's development venv or
unrelated host PATH entries when an isolated environment was requested.
"""

from dataclasses import dataclass
import subprocess
import sys
from typing import Protocol


@dataclass(frozen=True)
class SoftwarePresence:
    """Result of a presence check for one software component.

    Attributes:
        name: Software/component name (e.g. "esphome").
        environment: Target environment path (e.g. venv path or system label).
        executable: Executable or package name being checked.
        present: Whether the software was detected.
        detected_version: Version string when available.
        verification_method: How the presence check was performed.
    """
    name: str
    environment: str
    executable: str
    present: bool
    detected_version: str | None = None
    verification_method: str = "unknown"


class PresenceChecker(Protocol):
    """Protocol for checking whether software is present in an environment."""

    def check(self, name: str, environment: str, executable: str) -> SoftwarePresence:
        ...


class PythonVenvPresenceChecker:
    """Checks for Python packages in a specific Python environment.

    Uses the target environment's Python interpreter to check via
    importlib.metadata, ensuring the check resolves against the isolated
    environment - not the ADC development venv or host PATH entries.

    For executables (console_scripts installed by pip), resolves them
    relative to the venv's bin directory.
    """

    def check(self, name: str, environment: str, executable: str) -> SoftwarePresence:
        python = self._resolve_python(environment)
        version = self._resolve_version(python, executable)
        present = version is not None

        if present:
            method = f"importlib.metadata via {python}"
        else:
            method = f"importlib.metadata via {python} (not found)"

        return SoftwarePresence(
            name=name,
            environment=environment,
            executable=executable,
            present=present,
            detected_version=version,
            verification_method=method,
        )

    @staticmethod
    def _resolve_python(environment: str) -> str:
        import os
        env_bin = os.path.join(environment, "bin", "python")
        return env_bin

    @staticmethod
    def _resolve_version(python: str, package: str) -> str | None:
        try:
            result = subprocess.run(
                [python, "-c",
                 "import sys; import importlib.metadata as m; print(m.version(sys.argv[1]))",
                 package],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
            return None
        except (subprocess.TimeoutExpired, OSError):
            return None


class CommandPresenceChecker:
    """Checks for an executable on PATH within a given environment context.

    Resolves the executable against the provided environment's bin directory
    first, then falls back to the current PATH.  This prevents accidentally
    discovering software from unrelated PATH entries when an isolated
    environment was requested.
    """

    def check(self, name: str, environment: str, executable: str) -> SoftwarePresence:
        import os
        import shutil

        env_bin = os.path.join(environment, "bin")
        candidate = os.path.join(env_bin, executable)
        resolved = shutil.which(candidate) or shutil.which(executable)

        present = resolved is not None
        version = None
        method = "command resolution"

        if present:
            version = self._resolve_version(resolved)

        return SoftwarePresence(
            name=name,
            environment=environment,
            executable=executable,
            present=present,
            detected_version=version,
            verification_method=method,
        )

    @staticmethod
    def _resolve_version(executable_path: str) -> str | None:
        for arg in ("--version", "-V", "version"):
            try:
                result = subprocess.run(
                    [executable_path, arg],
                    capture_output=True, text=True, timeout=15,
                )
                if result.returncode == 0:
                    output = result.stdout.strip() or result.stderr.strip()
                    if output:
                        return output.split("\n")[0][:200]
            except (subprocess.TimeoutExpired, OSError):
                pass
        return None