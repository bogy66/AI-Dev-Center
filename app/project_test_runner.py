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
class StepFailureEvidence:
    """One deterministically attributable failing step's own evidence.

    Generic across any controlled verifier (pytest, a compiler, a config
    validator, ...) -- mirrors the fields a VerificationStepResult already
    carries, so a TestResult built from several failing steps can still
    represent each one individually instead of flattening them into a
    single, potentially misattributed command/return_code/stdout/stderr.
    """
    area: str
    step_id: str
    runner_type: str
    verification_kind: str
    status: str
    command: tuple[str, ...] = ()
    return_code: int | None = None
    timed_out: bool = False
    error_category: str | None = None
    diagnostics: str = ""
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class TestResult:
    passed: bool
    return_code: int
    stdout: str
    stderr: str
    command: tuple[str, ...]
    timed_out: bool = False
    # Populated only when this TestResult was folded from a VerificationResult
    # with one or more failing steps; empty for a plain pytest/unittest run.
    # The scalar fields above remain a safe, neutral aggregate view (never a
    # single step's value presented as if it described every failure); this
    # tuple is the attributable per-step detail.
    step_failures: tuple[StepFailureEvidence, ...] = ()


class ProjectTestRunner:
    _COMMAND = "python -m pytest -q"

    def __init__(self, timeout=60, runner=None):
        """runner is an explicit test-injection seam only.

        Passing a callable here (as this class's own tests do) preserves
        the exact original direct-call shape, unconfined by the central
        execution boundary, for isolated unit testing of this class's
        own argv/cwd/timeout construction. Leaving it unset (the
        productive default) routes the actual subprocess through
        app.execution.execute_controlled instead.
        """
        self._timeout, self._runner = timeout, runner

    def run(self, request: TestExecutionRequest) -> TestResult:
        if request.command != self._COMMAND:
            raise ValueError("Unsupported test command")
        root = Path(request.project_root).resolve()
        if not root.is_dir():
            raise ValueError("project_root must be an existing directory")
        command = (sys.executable, "-m", "pytest", "-q")

        if self._runner is not None:
            try:
                completed = self._runner(command, cwd=root, capture_output=True, text=True, timeout=self._timeout)
            except subprocess.TimeoutExpired as exc:
                return TestResult(False, -1, exc.stdout or "", exc.stderr or "", command, True)
            return TestResult(completed.returncode == 0, completed.returncode, completed.stdout, completed.stderr, command)

        from app.execution import ExecutionRequest, execute_controlled

        exec_request = ExecutionRequest(command, str(root), self._timeout, "python", "test")
        completed = execute_controlled(exec_request, root)
        if completed is None:
            return TestResult(False, -1, "", "Execution failed: tool unavailable", command, False)
        timed_out = getattr(completed, "timed_out", False)
        return TestResult(
            completed.returncode == 0, completed.returncode,
            completed.stdout or "", completed.stderr or "", command, timed_out,
        )
