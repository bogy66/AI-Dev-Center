"""Canonical Generalized Verification Architecture.

Converts Project Intelligence into a typed, area-aware VerificationPlan
and executes controlled, allowlisted runners.  Never accepts arbitrary
shell commands, never installs dependencies, never mutates Git.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any


# ---------------------------------------------------------------------------
# Verification Status
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VerificationStatus:
    value: str

    def __str__(self) -> str:
        return self.value

    def __eq__(self, other: object) -> bool:
        if isinstance(other, VerificationStatus):
            return self.value == other.value
        if isinstance(other, str):
            return self.value == other
        return False

    def __hash__(self) -> int:
        return hash(self.value)


PASS = VerificationStatus("pass")
FAIL = VerificationStatus("fail")
UNSUPPORTED = VerificationStatus("unsupported")
TOOL_UNAVAILABLE = VerificationStatus("tool_unavailable")
INVALID_PLAN = VerificationStatus("invalid_plan")
EXECUTION_ERROR = VerificationStatus("execution_error")
TIMEOUT = VerificationStatus("timeout")
NOT_APPLICABLE = VerificationStatus("not_applicable")

TERMINAL_STATUSES = frozenset({
    PASS.value, FAIL.value, UNSUPPORTED.value,
    TOOL_UNAVAILABLE.value, INVALID_PLAN.value,
    EXECUTION_ERROR.value, TIMEOUT.value, NOT_APPLICABLE.value,
})

_NON_BLOCKING = frozenset({
    NOT_APPLICABLE.value,
})


# ---------------------------------------------------------------------------
# Verification Step & Plan
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VerificationStep:
    step_id: str
    area: str
    working_directory: str
    verification_kind: str  # "test" | "build" | "validate" | "compile_check"
    test_system: str        # e.g. "pytest", "unittest", "vitest", "jest", etc.
    runner_type: str        # e.g. "pytest", "python_unittest", "cmake_build", "npm"
    policy: str             # "controlled_execution" | "unsupported" | "deferred"
    evidence: tuple[str, ...] = ()
    status: str = "pending"

    @property
    def is_executable(self) -> bool:
        return self.policy == "controlled_execution"


@dataclass(frozen=True)
class VerificationPlan:
    run_id: str
    project_root: str
    project_kind: str
    area_count: int
    steps: tuple[VerificationStep, ...]
    created_from_intelligence: bool = True

    @property
    def executable_steps(self) -> tuple[VerificationStep, ...]:
        return tuple(s for s in self.steps if s.is_executable)

    @property
    def all_steps(self) -> tuple[VerificationStep, ...]:
        return self.steps

    def step_ids(self) -> tuple[str, ...]:
        return tuple(s.step_id for s in self.steps)


# ---------------------------------------------------------------------------
# Verification Step Result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VerificationStepResult:
    step_id: str
    area: str
    status: str
    verification_kind: str
    runner_type: str
    passed: bool
    return_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    command: tuple[str, ...] = ()
    timed_out: bool = False
    truncated_output: bool = False
    error_category: str | None = None
    diagnostics: str = ""


@dataclass(frozen=True)
class VerificationResult:
    run_id: str
    steps: tuple[VerificationStepResult, ...]
    aggregate_status: str

    @property
    def passed(self) -> bool:
        return self.aggregate_status == PASS.value

    @property
    def step_count(self) -> int:
        return len(self.steps)

    @property
    def passed_count(self) -> int:
        return sum(1 for s in self.steps if s.status == PASS.value)

    @property
    def failed_count(self) -> int:
        return sum(1 for s in self.steps if s.status == FAIL.value)

    @property
    def unsupported_count(self) -> int:
        return sum(1 for s in self.steps
                   if s.status in (UNSUPPORTED.value, TOOL_UNAVAILABLE.value,
                                   INVALID_PLAN.value, EXECUTION_ERROR.value,
                                   TIMEOUT.value, NOT_APPLICABLE.value))

    @property
    def failure_summary(self) -> str:
        failures = [s for s in self.steps if s.status != PASS.value]
        return "; ".join(
            f"{s.area}/{s.step_id}: {s.status}"
            for s in failures
        ) if failures else ""


def _aggregate(steps: tuple[VerificationStepResult, ...]) -> str:
    # Only not_applicable is truly non-blocking (e.g. greenfield).
    # All other statuses — fail, unsupported, tool_unavailable, deferred,
    # execution_error, timeout, invalid_plan — block aggregate PASS.
    requires_pass = [s for s in steps
                     if s.status != NOT_APPLICABLE.value]
    if not requires_pass:
        return NOT_APPLICABLE.value
    if all(s.status == PASS.value for s in requires_pass):
        return PASS.value
    return FAIL.value


# ---------------------------------------------------------------------------
# Controlled Runner Registry
# ---------------------------------------------------------------------------

class VerificationRunner(ABC):
    """Base class for allowlisted controlled verification runners."""

    @property
    @abstractmethod
    def runner_type(self) -> str:
        ...

    @abstractmethod
    def can_run(self, step: VerificationStep) -> bool:
        ...

    @abstractmethod
    def execute(
        self, step: VerificationStep, project_root: str | Path,
    ) -> VerificationStepResult:
        ...


class ControlledRunnerRegistry:
    """Allowlist-based registry mapping test_system/kind → runner."""

    def __init__(self, runners: list[VerificationRunner] | None = None):
        self._runners: list[VerificationRunner] = list(runners or [])

    def register(self, runner: VerificationRunner) -> None:
        self._runners.append(runner)

    def find(self, step: VerificationStep) -> VerificationRunner | None:
        for runner in self._runners:
            if runner.can_run(step):
                return runner
        return None

    def execute_step(
        self, step: VerificationStep, project_root: str | Path,
    ) -> VerificationStepResult:
        if step.runner_type == "none" or step.test_system == "unknown":
            return VerificationStepResult(
                step_id=step.step_id, area=step.area,
                status=NOT_APPLICABLE.value,
                verification_kind=step.verification_kind,
                runner_type=step.runner_type,
                passed=False,
                diagnostics="No verification target applicable",
            )
        if step.policy == "unsupported":
            return VerificationStepResult(
                step_id=step.step_id, area=step.area,
                status=UNSUPPORTED.value,
                verification_kind=step.verification_kind,
                runner_type=step.runner_type,
                passed=False,
                diagnostics=f"Verification runner not supported: {step.runner_type}",
            )
        if step.policy == "deferred":
            return VerificationStepResult(
                step_id=step.step_id, area=step.area,
                status=UNSUPPORTED.value,
                verification_kind=step.verification_kind,
                runner_type=step.runner_type,
                passed=False,
                diagnostics=f"Verification deferred — future scope: {step.runner_type}",
            )
        runner = self.find(step)
        if runner is None:
            return VerificationStepResult(
                step_id=step.step_id, area=step.area,
                status=UNSUPPORTED.value,
                verification_kind=step.verification_kind,
                runner_type=step.runner_type,
                passed=False,
                diagnostics=f"No registered runner for: {step.runner_type}",
            )
        try:
            return runner.execute(step, project_root)
        except Exception as exc:
            return VerificationStepResult(
                step_id=step.step_id, area=step.area,
                status=EXECUTION_ERROR.value,
                verification_kind=step.verification_kind,
                runner_type=step.runner_type,
                passed=False,
                error_category=type(exc).__name__,
                diagnostics=str(exc)[:500],
            )

    def execute_plan(
        self, plan: VerificationPlan,
    ) -> VerificationResult:
        results: list[VerificationStepResult] = []
        for step in plan.steps:
            result = self.execute_step(step, plan.project_root)
            results.append(result)
        return VerificationResult(
            run_id=plan.run_id,
            steps=tuple(results),
            aggregate_status=_aggregate(tuple(results)),
        )


# ---------------------------------------------------------------------------
# Pytest Runner
# ---------------------------------------------------------------------------

_MAX_OUTPUT = 50_000
_DEFAULT_TIMEOUT = 120


def _safe_exec(
    args: tuple[str, ...],
    cwd: Path,
    timeout: int = _DEFAULT_TIMEOUT,
) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            list(args), cwd=str(cwd),
            capture_output=True, text=True,
            timeout=timeout, check=False,
            env={k: v for k, v in os.environ.items()
                 if k.startswith(("PATH", "HOME", "USER", "LANG", "PYTHON", "VIRTUAL_ENV", "CONDA"))},
        )
    except subprocess.TimeoutExpired as exc:
        result = subprocess.CompletedProcess(list(args), -1, exc.stdout or "", exc.stderr or "")
        result.timed_out = True
        return result
    except OSError:
        return None

import os as _os_module
os = _os_module


class PytestRunner(VerificationRunner):
    """Controlled pytest execution with allowlisted args and no shell access."""

    runner_type = "pytest"

    def __init__(self, timeout=_DEFAULT_TIMEOUT):
        self._timeout = timeout

    def can_run(self, step: VerificationStep) -> bool:
        return step.runner_type == "pytest"

    def execute(
        self, step: VerificationStep, project_root: str | Path,
    ) -> VerificationStepResult:
        root = Path(project_root).resolve()
        cwd = (root / step.working_directory).resolve()
        if not str(cwd).startswith(str(root)):
            return VerificationStepResult(
                step_id=step.step_id, area=step.area,
                status=INVALID_PLAN.value,
                verification_kind=step.verification_kind,
                runner_type=step.runner_type,
                passed=False,
                diagnostics=f"Working directory escapes project root: {cwd}",
            )
        if not cwd.is_dir():
            return VerificationStepResult(
                step_id=step.step_id, area=step.area,
                status=INVALID_PLAN.value,
                verification_kind=step.verification_kind,
                runner_type=step.runner_type,
                passed=False,
                diagnostics=f"Working directory does not exist: {step.working_directory}",
            )

        python = shutil.which("python") or shutil.which("python3") or sys.executable
        args = (python, "-m", "pytest", "-q")
        result = _safe_exec(args, cwd, self._timeout)

        if result is None:
            return VerificationStepResult(
                step_id=step.step_id, area=step.area,
                status=TOOL_UNAVAILABLE.value,
                verification_kind=step.verification_kind,
                runner_type=step.runner_type,
                passed=False,
                diagnostics="Python executable not found",
            )

        timed_out = getattr(result, "timed_out", False)
        stdout = (result.stdout or "")[:_MAX_OUTPUT]
        stderr = (result.stderr or "")[:_MAX_OUTPUT]
        truncated = (len(result.stdout or "") > _MAX_OUTPUT or
                     len(result.stderr or "") > _MAX_OUTPUT)
        passed = result.returncode == 0 and not timed_out

        if timed_out:
            status = TIMEOUT.value
        elif result.returncode == 0:
            status = PASS.value
        else:
            status = FAIL.value

        return VerificationStepResult(
            step_id=step.step_id, area=step.area,
            status=status,
            verification_kind=step.verification_kind,
            runner_type=step.runner_type,
            passed=passed,
            return_code=result.returncode,
            stdout=stdout, stderr=stderr,
            command=args,
            timed_out=timed_out,
            truncated_output=truncated,
        )


# ---------------------------------------------------------------------------
# Python Unittest Runner
# ---------------------------------------------------------------------------

class PythonUnittestRunner(VerificationRunner):
    """Controlled unittest execution."""

    runner_type = "python_unittest"

    def __init__(self, timeout=_DEFAULT_TIMEOUT):
        self._timeout = timeout

    def can_run(self, step: VerificationStep) -> bool:
        return step.runner_type == "python_unittest"

    def execute(
        self, step: VerificationStep, project_root: str | Path,
    ) -> VerificationStepResult:
        root = Path(project_root).resolve()
        cwd = (root / step.working_directory).resolve()
        if not str(cwd).startswith(str(root)):
            return VerificationStepResult(
                step_id=step.step_id, area=step.area,
                status=INVALID_PLAN.value,
                verification_kind=step.verification_kind,
                runner_type=step.runner_type,
                passed=False,
                diagnostics=f"Working directory escapes project root: {cwd}",
            )

        python = shutil.which("python") or shutil.which("python3") or sys.executable
        args = (python, "-m", "unittest", "discover", "-s", cwd.name, "-v")
        result = _safe_exec(args, cwd.parent if cwd.name == "tests" else cwd,
                            self._timeout)

        if result is None:
            return VerificationStepResult(
                step_id=step.step_id, area=step.area,
                status=TOOL_UNAVAILABLE.value,
                verification_kind=step.verification_kind,
                runner_type=step.runner_type,
                passed=False,
                diagnostics="Python executable not found",
            )

        timed_out = getattr(result, "timed_out", False)
        stdout = (result.stdout or "")[:_MAX_OUTPUT]
        stderr = (result.stderr or "")[:_MAX_OUTPUT]
        truncated = (len(result.stdout or "") > _MAX_OUTPUT or
                     len(result.stderr or "") > _MAX_OUTPUT)
        passed = result.returncode == 0 and not timed_out

        status = TIMEOUT.value if timed_out else (
            PASS.value if result.returncode == 0 else FAIL.value)

        return VerificationStepResult(
            step_id=step.step_id, area=step.area,
            status=status,
            verification_kind=step.verification_kind,
            runner_type=step.runner_type,
            passed=passed,
            return_code=result.returncode,
            stdout=stdout, stderr=stderr,
            command=args,
            timed_out=timed_out,
            truncated_output=truncated,
        )


# ---------------------------------------------------------------------------
# Verification Planner
# ---------------------------------------------------------------------------

def build_verification_plan(intelligence, run_id: str) -> VerificationPlan:
    """Convert ProjectIntelligence into a typed VerificationPlan.

    Supports:
      - pytest → controlled PytestRunner
      - unittest → controlled PythonUnittestRunner
      - vitest, jest, mocha, ctest → unsupported (safe deferred)
      - cmake, make → unsupported (safe deferred)
      - platformio → unsupported (safe deferred)
      - esphome → unsupported (safe deferred)
      - unknown → unsupported
    """
    if intelligence is None:
        return VerificationPlan(
            run_id=run_id, project_root="", project_kind="greenfield",
            area_count=0, steps=(),
        )

    project_root = getattr(intelligence, "project_root", "")
    project_kind = getattr(intelligence, "project_kind", "greenfield")
    areas = getattr(intelligence, "areas", ()) or ()
    steps: list[VerificationStep] = []

    RUNNER_MAP: dict[str, tuple[str, str]] = {
        "pytest": ("pytest", "controlled_execution"),
        "unittest": ("python_unittest", "controlled_execution"),
        "vitest": ("vitest", "deferred"),
        "jest": ("jest", "deferred"),
        "mocha": ("mocha", "deferred"),
        "ctest": ("ctest", "deferred"),
    }

    BUILD_RUNNER_MAP: dict[str, tuple[str, str]] = {
        "cmake": ("cmake_build", "deferred"),
        "make": ("make", "deferred"),
        "platformio": ("platformio", "unsupported"),
    }

    for area in areas:
        area_path = getattr(area, "path", "") or "."
        wd = "." if area_path == "." or not area_path else area_path

        for ts in (getattr(area, "test_systems", ()) or ()):
            ts_name = getattr(ts, "name", str(ts))
            tpl = RUNNER_MAP.get(ts_name)
            if tpl is None:
                runner_type = ts_name
                policy = "unsupported"
            else:
                runner_type, policy = tpl
            steps.append(VerificationStep(
                step_id=f"{area_path or 'root'}-test-{ts_name}",
                area=area_path, working_directory=wd,
                verification_kind="test",
                test_system=ts_name,
                runner_type=runner_type,
                policy=policy,
                evidence=tuple(e.path for e in (getattr(ts, "evidence", ()) or ())),
            ))

        for bs in (getattr(area, "build_systems", ()) or ()):
            bs_name = getattr(bs, "name", str(bs))
            tpl = BUILD_RUNNER_MAP.get(bs_name)
            if tpl is None:
                runner_type = bs_name
                policy = "unsupported"
            else:
                runner_type, policy = tpl
            steps.append(VerificationStep(
                step_id=f"{area_path or 'root'}-build-{bs_name}",
                area=area_path, working_directory=wd,
                verification_kind="build",
                test_system=bs_name,
                runner_type=runner_type,
                policy=policy,
                evidence=tuple(e.path for e in (getattr(bs, "evidence", ()) or ())),
            ))

    if not steps:
        steps.append(VerificationStep(
            step_id="no-verification-target",
            area=".", working_directory=".",
            verification_kind="test",
            test_system="unknown",
            runner_type="none",
            policy="unsupported",
        ))

    return VerificationPlan(
        run_id=run_id, project_root=project_root,
        project_kind=project_kind, area_count=len(areas),
        steps=tuple(steps),
    )


def build_default_registry() -> ControlledRunnerRegistry:
    registry = ControlledRunnerRegistry()
    registry.register(PytestRunner())
    registry.register(PythonUnittestRunner())
    return registry