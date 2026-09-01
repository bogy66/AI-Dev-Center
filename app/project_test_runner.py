"""Git-free, allowlist-based project test execution."""
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys


@dataclass(frozen=True)
class TestExecutionRequest:
    __test__ = False
    project_root: str | Path
    command: str = "python -m pytest -q"


@dataclass(frozen=True)
class TestResult:
    passed: bool
    return_code: int
    stdout: str
    stderr: str
    command: tuple[str, ...]
    timed_out: bool = False


class ProjectTestRunner:
    _COMMAND = "python -m pytest -q"
    def __init__(self, timeout=60, runner=subprocess.run):
        self._timeout, self._runner = timeout, runner

    def run(self, request: TestExecutionRequest) -> TestResult:
        if request.command != self._COMMAND:
            raise ValueError("Unsupported test command")
        root = Path(request.project_root).resolve()
        if not root.is_dir():
            raise ValueError("project_root must be an existing directory")
        command = (sys.executable, "-m", "pytest", "-q")
        try:
            completed = self._runner(command, cwd=root, capture_output=True, text=True, timeout=self._timeout)
        except subprocess.TimeoutExpired as exc:
            return TestResult(False, -1, exc.stdout or "", exc.stderr or "", command, True)
        return TestResult(completed.returncode == 0, completed.returncode, completed.stdout, completed.stderr, command)
