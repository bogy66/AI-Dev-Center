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
BLOCKED = VerificationStatus("blocked")

TERMINAL_STATUSES = frozenset({
    PASS.value, FAIL.value, UNSUPPORTED.value,
    TOOL_UNAVAILABLE.value, INVALID_PLAN.value,
    EXECUTION_ERROR.value, TIMEOUT.value, NOT_APPLICABLE.value,
    BLOCKED.value,
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
    verification_kind: str  # "test" | "build" | "validate" | "compile" | "configure"
    test_system: str        # e.g. "pytest", "unittest", "vitest", "jest", etc.
    runner_type: str        # e.g. "pytest", "python_unittest", "cmake_build", "esphome_check"
    policy: str             # "controlled_execution" | "unsupported" | "deferred"
    evidence: tuple[str, ...] = ()
    status: str = "pending"
    depends_on: tuple[str, ...] = ()
    metadata: dict | None = None  # e.g. {"environment": "esp32dev", "config": "esphome/device.yaml"}

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
    requires_pass = [s for s in steps
                     if s.status != NOT_APPLICABLE.value]
    if not requires_pass:
        return NOT_APPLICABLE.value
    if all(s.status == PASS.value for s in requires_pass):
        return PASS.value
    return FAIL.value


def _resolve_cwd(root: Path, step: VerificationStep) -> tuple[Path, VerificationStepResult | None]:
    """Validate and resolve working directory. Returns (cwd, None) or (root, error)."""
    cwd = (root / step.working_directory).resolve()
    if not str(cwd).startswith(str(root)):
        return root, VerificationStepResult(
            step_id=step.step_id, area=step.area,
            status=INVALID_PLAN.value,
            verification_kind=step.verification_kind,
            runner_type=step.runner_type,
            passed=False,
            diagnostics=f"Working directory escapes project root: {cwd}",
        )
    if not cwd.is_dir():
        return root, VerificationStepResult(
            step_id=step.step_id, area=step.area,
            status=INVALID_PLAN.value,
            verification_kind=step.verification_kind,
            runner_type=step.runner_type,
            passed=False,
            diagnostics=f"Working directory does not exist: {step.working_directory}",
        )
    return cwd, None


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
        results: dict[str, VerificationStepResult] = {}
        for step in plan.steps:
            # Check dependencies — if any previous step failed/blocked,
            # mark this step as blocked
            blocked_by = None
            for dep_id in step.depends_on:
                prev = results.get(dep_id)
                if prev is not None and prev.status != PASS.value:
                    blocked_by = dep_id
                    break
            if blocked_by is not None:
                result = VerificationStepResult(
                    step_id=step.step_id, area=step.area,
                    status=BLOCKED.value,
                    verification_kind=step.verification_kind,
                    runner_type=step.runner_type,
                    passed=False,
                    diagnostics=f"Blocked by failed dependency: {blocked_by}",
                )
                results[step.step_id] = result
                continue
            result = self.execute_step(step, plan.project_root)
            results[step.step_id] = result
        ordered = tuple(results.get(s.step_id, VerificationStepResult(
            step_id=s.step_id, area=s.area, status=BLOCKED.value,
            verification_kind=s.verification_kind, runner_type=s.runner_type,
            passed=False, diagnostics="Step result missing",
        )) for s in plan.steps)
        return VerificationResult(
            run_id=plan.run_id,
            steps=ordered,
            aggregate_status=_aggregate(ordered),
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
        "cmake": ("cmake", "controlled_execution"),
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
            if bs_name == "cmake" and policy == "controlled_execution":
                c1 = f"{area_path or 'root'}-cmake-configure"
                c2 = f"{area_path or 'root'}-cmake-build"
                steps.append(VerificationStep(
                    step_id=c1, area=area_path, working_directory=wd,
                    verification_kind="configure", test_system="cmake",
                    runner_type=runner_type, policy=policy,
                ))
                steps.append(VerificationStep(
                    step_id=c2, area=area_path, working_directory=wd,
                    verification_kind="build", test_system="cmake",
                    runner_type=runner_type, policy=policy,
                    depends_on=(c1,),
                ))
            else:
                steps.append(VerificationStep(
                    step_id=f"{area_path or 'root'}-build-{bs_name}",
                    area=area_path, working_directory=wd,
                    verification_kind="build",
                    test_system=bs_name,
                    runner_type=runner_type,
                    policy=policy,
                    evidence=tuple(e.path for e in (getattr(bs, "evidence", ()) or ())),
                ))

        for fw in (getattr(area, "firmware_indicators", ()) or ()):
            fw_name = getattr(fw, "name", str(fw))
            if fw_name == "esphome":
                cfg = getattr(fw, "config_path", None) or None
                s1_id = f"{area_path or 'root'}-esphome-validate"
                s2_id = f"{area_path or 'root'}-esphome-compile"
                steps.append(VerificationStep(
                    step_id=s1_id, area=area_path, working_directory=wd,
                    verification_kind="validate", test_system="esphome",
                    runner_type="esphome_check", policy="controlled_execution",
                    metadata={"config": cfg},
                ))
                steps.append(VerificationStep(
                    step_id=s2_id, area=area_path, working_directory=wd,
                    verification_kind="compile", test_system="esphome",
                    runner_type="esphome_check", policy="controlled_execution",
                    depends_on=(s1_id,),
                    metadata={"config": cfg},
                ))
            elif fw_name == "platformio":
                boards = getattr(fw, "boards", ()) or ()
                has_hooks = getattr(fw, "has_untrusted_hooks", False)
                for env_name in boards or ("default",):
                    env = env_name if env_name else "default"
                    policy = "unsupported" if has_hooks else "controlled_execution"
                    steps.append(VerificationStep(
                        step_id=f"{area_path or 'root'}-pio-build-{env}",
                        area=area_path, working_directory=wd,
                        verification_kind="build", test_system="platformio",
                        runner_type="platformio", policy=policy,
                        metadata={"environment": env},
                    ))
                    if env == "native" and not has_hooks:
                        bid = f"{area_path or 'root'}-pio-build-native"
                        steps.append(VerificationStep(
                            step_id=f"{area_path or 'root'}-pio-test-native",
                            area=area_path, working_directory=wd,
                            verification_kind="test", test_system="platformio",
                            runner_type="platformio", policy="controlled_execution",
                            metadata={"environment": "native"},
                            depends_on=(bid,),
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
    registry.register(ESPHomeCheckRunner())
    registry.register(PlatformIORunner())
    registry.register(CMakeRunner())
    return registry


# ---------------------------------------------------------------------------
# ESPHome Check Runner — validate + compile only, no hardware
# ---------------------------------------------------------------------------

class ESPHomeCheckRunner(VerificationRunner):
    runner_type = "esphome_check"

    def __init__(self, timeout=600):
        self._timeout = timeout

    def can_run(self, step: VerificationStep) -> bool:
        return step.runner_type == "esphome_check"

    def execute(self, step: VerificationStep, project_root: str | Path) -> VerificationStepResult:
        root = Path(project_root).resolve()
        cwd, err = _resolve_cwd(root, step)
        if err is not None:
            return err

        esphome_bin = shutil.which("esphome")
        if esphome_bin is None:
            return VerificationStepResult(
                step_id=step.step_id, area=step.area,
                status=TOOL_UNAVAILABLE.value,
                verification_kind=step.verification_kind,
                runner_type=step.runner_type,
                passed=False,
                diagnostics="ESPHome CLI not found",
            )

        if step.verification_kind == "validate":
            meta = step.metadata or {}
            cfg = meta.get("config")
            if cfg:
                target = str(cwd / cfg)
            else:
                target = str(cwd)
            args = (esphome_bin, "config", target)
        elif step.verification_kind == "compile":
            meta = step.metadata or {}
            cfg = meta.get("config")
            if cfg:
                target = str(cwd / cfg)
            else:
                target = str(cwd)
            args = (esphome_bin, "compile", target)
        else:
            return VerificationStepResult(
                step_id=step.step_id, area=step.area,
                status=UNSUPPORTED.value,
                verification_kind=step.verification_kind,
                runner_type=step.runner_type,
                passed=False,
                diagnostics=f"ESPHome operation not supported: {step.verification_kind}",
            )

        result = _safe_exec(args, cwd, self._timeout)
        if result is None:
            return VerificationStepResult(
                step_id=step.step_id, area=step.area,
                status=TOOL_UNAVAILABLE.value,
                verification_kind=step.verification_kind,
                runner_type=step.runner_type,
                passed=False,
                diagnostics="ESPHome execution failed",
            )

        return _build_step_result(step, result, args)


# ---------------------------------------------------------------------------
# PlatformIO Runner — build + native test only, no hardware
# ---------------------------------------------------------------------------

class PlatformIORunner(VerificationRunner):
    runner_type = "platformio"

    _FORBIDDEN_TARGETS = frozenset({"upload", "uploadfs", "monitor",
                                     "device", "remote"})
    _FORBIDDEN_ARGS = frozenset({"--upload-port", "--monitor-port"})

    def __init__(self, timeout=900):
        self._timeout = timeout
        self._pio_cmd = shutil.which("platformio") or shutil.which("pio") or "platformio"

    def can_run(self, step: VerificationStep) -> bool:
        return step.runner_type == "platformio"

    def execute(self, step: VerificationStep, project_root: str | Path) -> VerificationStepResult:
        root = Path(project_root).resolve()
        cwd, err = _resolve_cwd(root, step)
        if err is not None:
            return err

        if shutil.which("platformio") is None and shutil.which("pio") is None:
            return VerificationStepResult(
                step_id=step.step_id, area=step.area,
                status=TOOL_UNAVAILABLE.value,
                verification_kind=step.verification_kind,
                runner_type=step.runner_type,
                passed=False,
                diagnostics="PlatformIO CLI not found",
            )

        meta = step.metadata or {}
        env = meta.get("environment", "")

        if step.verification_kind == "build":
            args = (self._pio_cmd, "run")
            if env:
                args = (*args, "-e", env)
        elif step.verification_kind == "test" and env == "native":
            args = (self._pio_cmd, "test", "-e", "native",
                    "--without-uploading", "--without-publishing")
        else:
            return VerificationStepResult(
                step_id=step.step_id, area=step.area,
                status=UNSUPPORTED.value,
                verification_kind=step.verification_kind,
                runner_type=step.runner_type,
                passed=False,
                diagnostics=f"PlatformIO operation not supported: {step.verification_kind}",
            )

        result = _safe_exec(args, cwd, self._timeout)
        if result is None:
            return VerificationStepResult(
                step_id=step.step_id, area=step.area,
                status=TOOL_UNAVAILABLE.value,
                verification_kind=step.verification_kind,
                runner_type=step.runner_type,
                passed=False,
                diagnostics="PlatformIO execution failed",
            )

        return _build_step_result(step, result, args)


# ---------------------------------------------------------------------------
# CMake Runner — configure → build → ctest, controlled build dir
# ---------------------------------------------------------------------------

class CMakeRunner(VerificationRunner):
    runner_type = "cmake"

    def __init__(self, timeout=600):
        self._timeout = timeout

    def can_run(self, step: VerificationStep) -> bool:
        return step.runner_type in ("cmake", "cmake_build")

    def execute(self, step: VerificationStep, project_root: str | Path) -> VerificationStepResult:
        root = Path(project_root).resolve()
        cwd, err = _resolve_cwd(root, step)
        if err is not None:
            return err

        cmake_bin = shutil.which("cmake")
        if cmake_bin is None:
            return VerificationStepResult(
                step_id=step.step_id, area=step.area,
                status=TOOL_UNAVAILABLE.value,
                verification_kind=step.verification_kind,
                runner_type=step.runner_type,
                passed=False,
                diagnostics="CMake not found",
            )

        build_dir = root / ".ai-build"
        build_dir.mkdir(exist_ok=True)

        if step.verification_kind == "configure":
            args = (cmake_bin, "-S", str(cwd), "-B", str(build_dir))
        elif step.verification_kind == "build":
            args = (cmake_bin, "--build", str(build_dir))
        elif step.verification_kind == "test" and step.test_system == "ctest":
            ctest_bin = shutil.which("ctest")
            if ctest_bin is None:
                return VerificationStepResult(
                    step_id=step.step_id, area=step.area,
                    status=TOOL_UNAVAILABLE.value,
                    verification_kind=step.verification_kind,
                    runner_type=step.runner_type,
                    passed=False,
                    diagnostics="CTest not found",
                )
            args = (ctest_bin, "--test-dir", str(build_dir))
        else:
            return VerificationStepResult(
                step_id=step.step_id, area=step.area,
                status=UNSUPPORTED.value,
                verification_kind=step.verification_kind,
                runner_type=step.runner_type,
                passed=False,
                diagnostics=f"CMake operation not supported: {step.verification_kind}",
            )

        result = _safe_exec(args, cwd.parent if step.verification_kind == "configure" else cwd,
                            self._timeout)
        if result is None:
            return VerificationStepResult(
                step_id=step.step_id, area=step.area,
                status=TOOL_UNAVAILABLE.value,
                verification_kind=step.verification_kind,
                runner_type=step.runner_type,
                passed=False,
                diagnostics="CMake execution failed",
            )

        return _build_step_result(step, result, args)


def _build_step_result(step, result, args):
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