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
import contextlib
import contextvars
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
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
# CLAUDE-ADC-S5-VERIFICATION-WORKSPACE-INTEGRITY-FIX-001: a verification
# runner's own reported exit status is never sufficient proof of a clean
# verification outcome -- a controlled tool that returns success while
# having introduced an unaccounted new/modified/removed path into the
# real target workspace (e.g. `esphome compile` leaving behind a
# `.gitignore`/`.esphome/` it created) must never be represented as PASS,
# and must never be silently folded into FAIL as if it were an ordinary
# tool/test failure -- it is a distinct S5.2 contract violation with its
# own attributable diagnostics. See _execute_verification_isolated().
WORKSPACE_INTEGRITY_VIOLATION = VerificationStatus("workspace_integrity_violation")

TERMINAL_STATUSES = frozenset({
    PASS.value, FAIL.value, UNSUPPORTED.value,
    TOOL_UNAVAILABLE.value, INVALID_PLAN.value,
    EXECUTION_ERROR.value, TIMEOUT.value, NOT_APPLICABLE.value,
    BLOCKED.value, WORKSPACE_INTEGRITY_VIOLATION.value,
})

_NON_BLOCKING = frozenset({
    NOT_APPLICABLE.value,
})


# ---------------------------------------------------------------------------
# Verification Execution Budget Policy (ARC_022, IF_REQ_022)
# ---------------------------------------------------------------------------
#
# CLAUDE-ADC-RSE033-ESPHOME-COMPILE-TIMEOUT-REQ-CODE-FIX-001: the execution
# time budget of an external verification/build operation is owned by the
# VerificationStep's execution policy, never by a runner constructor
# literal. The single, technology-neutral central policy below maps a
# step's generic operation class to its budget; the S5.1 producer
# (build_verification_plan) writes the selected budget explicitly into
# every step, and every runner consumes exactly that value
# (step -> runner -> ExecutionRequest.timeout). No runner guesses a
# budget from its tool name.
#
# The per-class values are the budgets this repository already established
# for the same operation classes (test: the former pytest/unittest default;
# check: the former validate/configure budgets; build: the largest build
# budget already in use), not values tuned against a single Real-System
# run. S5.2 always executes against a fresh shadow workspace, so a build
# is always a cold build; the build class is therefore never smaller than
# any previously established build budget.
MAX_VERIFICATION_EXECUTION_BUDGET_SECONDS = 3600

VERIFICATION_OPERATION_CLASS_BY_KIND: dict[str, str] = {
    "test": "test",
    "validate": "check",
    "configure": "check",
    "build": "build",
    "compile": "build",
}

VERIFICATION_EXECUTION_BUDGET_SECONDS: dict[str, int] = {
    "test": 120,
    "check": 600,
    "build": 900,
}


def verification_execution_budget(
    verification_kind: str, operation_class: str | None = None,
) -> int | None:
    """The central policy budget for one verification operation, or None
    when the policy defines none (the step then fails closed at execution
    with INVALID_PLAN instead of receiving a guessed budget).

    `operation_class` lets the plan producer declare a step's generic
    operation class explicitly when its verification kind alone
    understates it (e.g. a "test" that first performs a full build)."""
    cls = operation_class or VERIFICATION_OPERATION_CLASS_BY_KIND.get(verification_kind)
    return VERIFICATION_EXECUTION_BUDGET_SECONDS.get(cls) if cls else None


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
    # Execution policy: the explicit time budget (seconds) of this step's
    # external operation. A step constructed or deserialized without one
    # (e.g. a VerificationPlan persisted before this field existed) takes
    # the central policy budget for its verification kind -- the same
    # policy the plan producer uses -- never a runner-specific value. An
    # unknown kind or an invalid value fails closed at execution.
    execution_budget_seconds: int | None = None

    def __post_init__(self):
        if self.execution_budget_seconds is None:
            object.__setattr__(
                self, "execution_budget_seconds",
                verification_execution_budget(self.verification_kind),
            )

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
    # IF_REQ_037: for a TOOL_UNAVAILABLE outcome, the executable/tool
    # identity the runner looked up and did not find -- structured, so
    # S3.5 recovery never has to parse `diagnostics`.
    unavailable_tool: str | None = None


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
    if not cwd.is_relative_to(root):
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


def _resolve_execution_budget(step: VerificationStep) -> tuple[int | None, VerificationStepResult | None]:
    """The step's policy-owned execution budget, or a fail-closed
    INVALID_PLAN result when the step carries no valid budget."""
    budget = step.execution_budget_seconds
    if (isinstance(budget, int) and not isinstance(budget, bool)
            and 0 < budget <= MAX_VERIFICATION_EXECUTION_BUDGET_SECONDS):
        return budget, None
    return None, VerificationStepResult(
        step_id=step.step_id, area=step.area,
        status=INVALID_PLAN.value,
        verification_kind=step.verification_kind,
        runner_type=step.runner_type,
        passed=False,
        diagnostics=(
            f"VerificationStep has no valid execution budget "
            f"(execution_budget_seconds={budget!r}; policy requires an "
            f"integer in 1..{MAX_VERIFICATION_EXECUTION_BUDGET_SECONDS})"
        ),
    )


# ---------------------------------------------------------------------------
# Controlled Runner Registry
# ---------------------------------------------------------------------------

class VerificationRunner(ABC):
    """Base class for controlled verification runners."""

    # True only for a runner that executes through the established target
    # executable (see verification_target). A runner that resolves its own
    # tools (e.g. from PATH) cannot be shown to run in the intended target
    # environment, so while a target is scoped the registry refuses to
    # present its outcome as target verification.
    executes_through_target: bool = False

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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# CLAUDE-ADC-S5-VERIFICATION-WORKSPACE-INTEGRITY-FIX-002: size/mtime alone
# (FIX-001's original fingerprint) is not a sufficient identity proof -- a
# file can be rewritten to different content of the exact same byte length,
# with its original mtime restored/forced afterward, and neither size nor
# mtime would show any difference at all. `_entry_fingerprint` is now the
# sole authoritative identity for one filesystem entry:
#   - a symlink is identified by its own raw target string (os.readlink),
#     NEVER dereferenced/followed -- a symlink's target changing, or a
#     symlink replacing/being replaced by a different object type, is
#     itself a real-target mutation, not something to silently resolve
#     through;
#   - a regular file is identified by a cryptographic (SHA-256) CONTENT
#     hash -- the only field decisive for "content changed or not". Size
#     and mtime are deliberately never consulted here, not even as a
#     skip-hashing optimization: doing so would silently reintroduce the
#     exact same-size / mtime-preserving-mutation blind spot this fix
#     closes;
#   - any other filesystem object type (FIFO, socket, device, ...) is
#     identified by its raw mode bits alone -- never opened/read, so a
#     regular file being replaced by (or replacing) such an object is
#     still a detected identity change even though it carries no content
#     hash of its own.
# Returns None for a path that cannot be inspected (already gone, or a
# permission error) -- such a path is simply absent from the manifest,
# which the removed/added comparison below already handles correctly.
def _entry_fingerprint(path: Path) -> tuple | None:
    try:
        info = path.lstat()
    except OSError:
        return None
    mode = info.st_mode
    if stat.S_ISLNK(mode):
        try:
            return ("symlink", os.readlink(path))
        except OSError:
            return None
    if stat.S_ISREG(mode):
        try:
            return ("file", _sha256_file(path))
        except OSError:
            return None
    return ("other", stat.S_IFMT(mode))


def _workspace_manifest(root: Path) -> dict[str, tuple]:
    """Relative-path -> authoritative content/identity fingerprint (see
    `_entry_fingerprint`) for every non-directory entry under *root*,
    including symlinked directories (fingerprinted as symlinks, by their
    own target, never traversed into). `os.walk(followlinks=False)` is
    used rather than `Path.rglob` specifically so a symlinked directory
    is never silently descended into (which would risk infinite
    recursion on a symlink cycle, and would fingerprint the SAME real
    content twice under two different relative paths) -- it is instead
    fingerprinted once, as the symlink object it actually is. Never
    raises on an individual unreadable entry -- a permission error on
    one path must never abort the integrity check for every other
    path."""
    manifest: dict[str, tuple] = {}
    if not root.is_dir():
        return manifest
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        for name in dirnames:
            entry = current / name
            if not entry.is_symlink():
                continue
            fingerprint = _entry_fingerprint(entry)
            if fingerprint is not None:
                manifest[entry.relative_to(root).as_posix()] = fingerprint
        for name in filenames:
            entry = current / name
            fingerprint = _entry_fingerprint(entry)
            if fingerprint is not None:
                manifest[entry.relative_to(root).as_posix()] = fingerprint
    return manifest


def _workspace_integrity_violations(
    before: dict[str, tuple], after: dict[str, tuple],
) -> tuple[str, ...]:
    """Every path introduced, changed, or removed between two manifests
    of the SAME real target workspace. A path present in both with an
    identical fingerprint is genuinely untouched (byte-for-byte, for a
    regular file; same symlink target; same object type) and is never
    reported -- pre-existing, unrelated dirty state is never treated as
    a violation merely because it exists. "New" and "modified" are
    reported distinctly so diagnostics identify precisely what changed."""
    violations = []
    for path, fingerprint_after in after.items():
        fingerprint_before = before.get(path)
        if fingerprint_before is None:
            violations.append(f"new path introduced during verification: {path}")
        elif fingerprint_before != fingerprint_after:
            violations.append(f"path content or identity modified during verification: {path}")
    violations += [
        f"path removed during verification: {path}"
        for path in before
        if path not in after
    ]
    return tuple(sorted(violations))


class _ShadowWorkspaces:
    """Shadow workspaces of ONE plan execution, derived along `depends_on`.

    A step without an (already executed) in-plan dependency starts from a
    fresh copy of the real target workspace. A dependent step continues
    from the state its dependency legitimately produced (e.g. CMake
    configure -> build -> ctest share the configured build tree):
      * a dependency with exactly ONE dependent hands its workspace over;
      * a dependency with SEVERAL dependents (a branch) keeps its produced
        state untouched, and every dependent continues in its own copy of
        it -- sibling branches never see each other's side effects
        (configuration, build caches, ...).
    A step joining several dependencies continues from the one whose state
    already contains all the others (a transitive dependency listed
    explicitly); a join of diverged branches has no single defined input
    state and is refused (see `conflict`) rather than silently run against
    one branch. Every copy is disposable and discarded
    when the plan finishes; the real target workspace is never the working
    root."""

    def __init__(self, steps):
        known = {step.step_id for step in steps}
        self._deps = {
            step.step_id: tuple(dict.fromkeys(d for d in step.depends_on if d in known))
            for step in steps
        }
        self._dependents: dict[str, int] = {}
        for deps in self._deps.values():
            for dep_id in deps:
                self._dependents[dep_id] = self._dependents.get(dep_id, 0) + 1
        self._roots: dict[str, Path] = {}  # step_id -> workspace it ran in
        # step_id -> the steps whose produced state that workspace contains
        self._lineage: dict[str, frozenset[str]] = {}
        self._dirs: list[tempfile.TemporaryDirectory] = []

    def _copy(self, source: Path) -> Path:
        holder = tempfile.TemporaryDirectory(prefix="adc-s5-verify-shadow-")
        self._dirs.append(holder)
        shadow_root = Path(holder.name) / "workspace"
        shutil.copytree(source, shadow_root, symlinks=True)
        return shadow_root

    def _inputs(self, step: VerificationStep) -> list[tuple[str, Path]]:
        return [(d, self._roots[d]) for d in self._deps.get(step.step_id, ()) if d in self._roots]

    def _base(self, step: VerificationStep) -> tuple[str | None, str | None]:
        """(dependency whose workspace the step continues from, conflict)."""
        inputs = [d for d, _ in self._inputs(step)]
        if not inputs:
            return None, None
        for dep_id in inputs:
            if all(other in self._lineage[dep_id] for other in inputs):
                return dep_id, None
        return None, (
            "Step joins dependencies from diverged workspace branches "
            f"({', '.join(inputs)}); no single defined input state exists"
        )

    def conflict(self, step: VerificationStep) -> str | None:
        return self._base(step)[1]

    def for_step(self, step: VerificationStep, root: Path) -> Path:
        dep_id, conflict = self._base(step)
        if conflict is not None:
            raise RuntimeError(conflict)
        if dep_id is None:
            workspace, lineage = self._copy(root), frozenset()
        else:
            workspace, lineage = self._roots[dep_id], self._lineage[dep_id]
            if self._dependents.get(dep_id, 0) > 1:
                workspace = self._copy(workspace)
        self._roots[step.step_id] = workspace
        self._lineage[step.step_id] = lineage | {step.step_id}
        return workspace

    def close(self) -> None:
        for holder in self._dirs:
            holder.cleanup()
        self._dirs.clear()
        self._roots.clear()


# The shadow workspaces of the plan currently executing in this context
# (set only by execute_plan); a lone execute_step() gets a fresh copy.
_ACTIVE_SHADOWS: contextvars.ContextVar["_ShadowWorkspaces | None"] = contextvars.ContextVar(
    "adc_verification_shadows", default=None,
)


# The execution target established before generation (app.target_environment)
# for the plan currently executing; None = no target scoped (host default,
# legacy callers only -- the S5 stage never treats "no target" as verified).
_ACTIVE_TARGET_EXECUTABLE: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "adc_verification_target_executable", default=None,
)


# The project (not its isolated verification copy) whose approved plan
# selected the active target: where the boundary looks up the approval.
_ACTIVE_TARGET_SCOPE: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "adc_verification_target_scope", default=None,
)


@contextlib.contextmanager
def verification_target(executable: str | None, project_scope: str | os.PathLike | None = None):
    """Run verification through the given established target executable,
    approved for `project_scope` (the real project of the run)."""
    token = _ACTIVE_TARGET_EXECUTABLE.set(executable)
    scope_token = _ACTIVE_TARGET_SCOPE.set(None if project_scope is None else str(project_scope))
    try:
        yield
    finally:
        _ACTIVE_TARGET_SCOPE.reset(scope_token)
        _ACTIVE_TARGET_EXECUTABLE.reset(token)


def _execution_python() -> str:
    return _ACTIVE_TARGET_EXECUTABLE.get() or sys.executable


def _target_environment_dir() -> str | None:
    """Directory holding the executables of the established target
    environment (see app.execution.target_environment_dir). None when no
    target is scoped or it is not an existing absolute executable file."""
    from app.execution import target_environment_dir
    return target_environment_dir(_ACTIVE_TARGET_EXECUTABLE.get())


def _resolve_tool(*names: str) -> str | None:
    """Resolve a verification tool by name, technology neutral.

    No target scoped (legacy callers): host lookup. Target scoped: ONLY the
    target environment's own tool directory is searched -- a host/default
    tool is never substituted. A tool not installed there yields None, i.e.
    honestly unavailable/unconfirmed."""
    target = _ACTIVE_TARGET_EXECUTABLE.get()
    if target is None:
        for name in names:
            found = shutil.which(name)
            if found:
                return found
        return None
    from app.execution import resolve_tool_in_target
    return resolve_tool_in_target(target, *names)


def _execute_verification_isolated(
    runner: "VerificationRunner", step: VerificationStep, root: Path,
    shadow: "_ShadowWorkspaces | None" = None,
) -> VerificationStepResult:
    """S5.2 workspace-integrity contract: a controlled verification
    runner is executed against a disposable shadow copy of the real
    target workspace, never the real workspace itself, so a runner's own
    incidental filesystem side effects (build/tool caches, generated
    config, metadata files, ...) land only in the shadow copy and are
    discarded with it -- "running a controlled process" authorizes
    process execution, never target-workspace mutation. The real target
    workspace is additionally snapshotted before and after as
    deterministic, attributable proof (defense-in-depth: a runner is
    trusted to honor the *given* working root, but this check never
    merely assumes that) -- if the real workspace is found to differ
    regardless, the step is reported as WORKSPACE_INTEGRITY_VIOLATION
    rather than whatever status/exit-code the runner itself reported, so
    a verifier's own success can never silently legitimize an unaccounted
    real mutation. Neither branch deletes, reverts, or otherwise touches
    any pre-existing or newly-observed path -- fail-closed reporting
    only, never silent repair."""
    baseline = _workspace_manifest(root)
    if shadow is not None:
        result = runner.execute(step, shadow.for_step(step, root))
    else:
        with tempfile.TemporaryDirectory(prefix="adc-s5-verify-shadow-") as shadow_parent:
            shadow_root = Path(shadow_parent) / "workspace"
            shutil.copytree(root, shadow_root, symlinks=True)
            result = runner.execute(step, shadow_root)
    violations = _workspace_integrity_violations(baseline, _workspace_manifest(root))
    if not violations:
        return result
    return VerificationStepResult(
        step_id=step.step_id, area=step.area,
        status=WORKSPACE_INTEGRITY_VIOLATION.value,
        verification_kind=step.verification_kind,
        runner_type=step.runner_type,
        passed=False,
        return_code=result.return_code,
        stdout=result.stdout, stderr=result.stderr,
        command=result.command,
        timed_out=result.timed_out,
        truncated_output=result.truncated_output,
        diagnostics=(
            f"Verification runner reported status={result.status!r} but left "
            "unauthorized target-workspace mutation (incidental verifier side "
            "effects are never automatically approved changes): "
            + "; ".join(violations)
        )[:_MAX_OUTPUT],
    )


class ControlledRunnerRegistry:
    """Central registry mapping test_system/kind to controlled runners."""

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
        if _ACTIVE_TARGET_EXECUTABLE.get() is not None and not runner.executes_through_target:
            # Recoverable environment/setup outcome, never a source defect:
            # this runner's tools are not resolved through the established
            # target environment, so nothing is executed on a substitute.
            return VerificationStepResult(
                step_id=step.step_id, area=step.area,
                status=TOOL_UNAVAILABLE.value,
                verification_kind=step.verification_kind,
                runner_type=step.runner_type,
                passed=False,
                diagnostics=(
                    f"Runner {step.runner_type!r} cannot be executed through the "
                    "established target environment; not run on a substitute "
                    "environment. Compatibility is unconfirmed."
                ),
                unavailable_tool=step.test_system or step.runner_type,
            )
        try:
            root = Path(project_root)
            if root.is_dir():
                shadow = _ACTIVE_SHADOWS.get()
                conflict = shadow.conflict(step) if shadow is not None else None
                if conflict is not None:
                    return VerificationStepResult(
                        step_id=step.step_id, area=step.area,
                        status=INVALID_PLAN.value,
                        verification_kind=step.verification_kind,
                        runner_type=step.runner_type,
                        passed=False,
                        diagnostics=conflict,
                    )
                return _execute_verification_isolated(runner, step, root, shadow)
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
        shadow = _ShadowWorkspaces(plan.steps)
        token = _ACTIVE_SHADOWS.set(shadow)
        try:
            self._execute_steps(plan, results)
        finally:
            _ACTIVE_SHADOWS.reset(token)
            shadow.close()
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

    def _execute_steps(self, plan, results) -> None:
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


# ---------------------------------------------------------------------------
# Pytest Runner
# ---------------------------------------------------------------------------

_MAX_OUTPUT = 50_000

def _safe_exec(
    args: tuple[str, ...],
    cwd: Path,
    timeout: int,
    tool_name: str = "python",
    operation_type: str = "verification",
    target_executable: str | None = None,
) -> subprocess.CompletedProcess | None:
    """Controlled subprocess execution with registered capability validation.

    `target_executable`: the selected, approved target this tool was
    resolved through; the boundary then binds the executable to that
    target's environment instead of a host PATH identity.

    Returns None only for a boundary rejection or an executable that could
    not be started (the runner reports TOOL_UNAVAILABLE). A failure after
    the process started raises app.execution.ControlledExecutionError,
    which ControlledRunnerRegistry.execute_step reports as
    EXECUTION_ERROR -- never TOOL_UNAVAILABLE."""
    from app.execution import execute_controlled, ExecutionRequest
    try:
        req = ExecutionRequest(
            args=args, cwd=str(cwd), timeout=timeout, tool_name=tool_name,
            operation_type=operation_type, target_executable=target_executable,
            approval_scope=_ACTIVE_TARGET_SCOPE.get() if target_executable else None,
        )
        return execute_controlled(req, cwd)
    except UnicodeError:
        # Output handling is never a boundary rejection: it must not be
        # reported as an unavailable tool (which routes to S3 recovery).
        raise
    except ValueError:
        return None

import os as _os_module
os = _os_module


class PytestRunner(VerificationRunner):
    """Controlled pytest execution with allowlisted args and no shell access."""

    runner_type = "pytest"
    executes_through_target = True

    def can_run(self, step: VerificationStep) -> bool:
        return step.runner_type == "pytest"

    def execute(
        self, step: VerificationStep, project_root: str | Path,
    ) -> VerificationStepResult:
        root = Path(project_root).resolve()
        cwd = (root / step.working_directory).resolve()
        if not cwd.is_relative_to(root):
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

        budget, err = _resolve_execution_budget(step)
        if err is not None:
            return err
        python = _execution_python()
        args = (python, "-m", "pytest", "-q")
        result = _safe_exec(args, cwd, budget, operation_type="test")

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
    executes_through_target = True

    def can_run(self, step: VerificationStep) -> bool:
        return step.runner_type == "python_unittest"

    def execute(
        self, step: VerificationStep, project_root: str | Path,
    ) -> VerificationStepResult:
        root = Path(project_root).resolve()
        cwd = (root / step.working_directory).resolve()
        if not cwd.is_relative_to(root):
            return VerificationStepResult(
                step_id=step.step_id, area=step.area,
                status=INVALID_PLAN.value,
                verification_kind=step.verification_kind,
                runner_type=step.runner_type,
                passed=False,
                diagnostics=f"Working directory escapes project root: {cwd}",
            )

        budget, err = _resolve_execution_budget(step)
        if err is not None:
            return err
        python = _execution_python()
        args = (python, "-m", "unittest", "discover", "-s", cwd.name, "-v")
        result = _safe_exec(args, cwd.parent if cwd.name == "tests" else cwd,
                            budget, operation_type="test")

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

# CLAUDE-ARCH-S2-013G: hoisted to module level (unchanged values, unchanged
# behavior inside build_verification_plan() below) so app.engineering_
# decision's S2.3 Verification Feasibility can IMPORT the exact same,
# single, ADC-owned mapping from a detected Project Intelligence identity
# to its canonical runner/mechanism identity -- as independent, trusted
# evidence that a claimed verification mechanism corresponds to something
# ADC itself already knows how to run -- rather than re-declaring a
# second, competing copy of this mapping. Never edited to special-case a
# single candidate; a change here changes what S5 Generalized Verification
# itself would build a plan for.
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

# The firmware branch below has always special-cased "esphome" and
# "platformio" inline rather than through a dict; hoisted here (same
# values, same behavior) purely so the mapping is importable evidence.
FIRMWARE_RUNNER_MAP: dict[str, str] = {
    "esphome": "esphome_check",
    "platformio": "platformio",
}

# CLAUDE-ARCH-S2-014E: FIRMWARE_RUNNER_MAP["esphome"] names S5's own
# internal runner_type ("esphome_check", the VerificationStep.runner_type
# ESPHomeCheckRunner registers under -- see build_verification_plan()'s
# firmware branch above). That is NOT the mechanism vocabulary
# app.council_prompts/app.council_models actually instruct Council
# candidates to declare for ESPHome's "validate" step: both modules'
# own docstrings, and app.engineering_decision's
# `_is_structured_verification_token()` docstring, give "esphome_validate"
# as the canonical example (mirroring the "validate"/"compile"
# VerificationStep.verification_kind split build_verification_plan()
# itself produces for every esphome firmware indicator). Before this fix,
# a genuinely-detected ESPHome project could never independently
# corroborate a correctly-vocabularied candidate: `_independently_
# corroborated()` requires the claimed mechanism to be a member of the
# SAME trusted identity group as the evidence identity, and that group
# never contained "esphome_validate" -- so real ESPHome capability was
# rejected as if it were self-certified, exactly the CLAUDE-ADC-E2E-
# VERIFICATION-EVIDENCE-FIX-001 Real-System-E2E failure (binding
# requirement inadmissible: "no independent Project Intelligence
# evidence linking both to the same real capability"). Both names are
# now interchangeable identities for the SAME real, always-controlled
# ESPHome capability (ESPHome has no untrusted-hooks concept, unlike
# PlatformIO) -- "esphome_check" is kept, unchanged, so every existing
# caller/test that already legitimately uses it stays exactly as
# productive as before; this only ADDS the one missing, genuinely
# documented alias, it never weakens `_independently_corroborated()`'s
# own fail-closed matching rule.
_ESPHOME_MECHANISM_ALIASES = frozenset({"esphome_validate"})


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
                execution_budget_seconds=verification_execution_budget("test"),
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
                    execution_budget_seconds=verification_execution_budget("configure"),
                    runner_type=runner_type, policy=policy,
                ))
                steps.append(VerificationStep(
                    step_id=c2, area=area_path, working_directory=wd,
                    verification_kind="build", test_system="cmake",
                    execution_budget_seconds=verification_execution_budget("build"),
                    runner_type=runner_type, policy=policy,
                    depends_on=(c1,),
                ))
            else:
                steps.append(VerificationStep(
                    step_id=f"{area_path or 'root'}-build-{bs_name}",
                    area=area_path, working_directory=wd,
                    verification_kind="build",
                    execution_budget_seconds=verification_execution_budget("build"),
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
                    execution_budget_seconds=verification_execution_budget("validate"),
                    runner_type="esphome_check", policy="controlled_execution",
                    metadata={"config": cfg},
                ))
                steps.append(VerificationStep(
                    step_id=s2_id, area=area_path, working_directory=wd,
                    verification_kind="compile", test_system="esphome",
                    execution_budget_seconds=verification_execution_budget("compile"),
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
                        execution_budget_seconds=verification_execution_budget("build"),
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
                            # builds the native target before testing it
                            execution_budget_seconds=verification_execution_budget(
                                "test", operation_class="build",
                            ),
                            metadata={"environment": "native"},
                            depends_on=(bid,),
                        ))

    if not steps:
        steps.append(VerificationStep(
            step_id="no-verification-target",
            area=".", working_directory=".",
            verification_kind="test",
            execution_budget_seconds=verification_execution_budget("test"),
            test_system="unknown",
            runner_type="none",
            policy="unsupported",
        ))

    return VerificationPlan(
        run_id=run_id, project_root=project_root,
        project_kind=project_kind, area_count=len(areas),
        steps=tuple(steps),
    )


PROJECT_GLOBAL_SCOPE = "."


@dataclass(frozen=True)
class TrustedVerificationGroup:
    """CLAUDE-ARCH-S2-014D: one independently-detected capability's
    interchangeable identities (unchanged meaning from before this task),
    PLUS the exact `ProjectArea.path` Project Intelligence detected it in
    -- never lost/flattened away.

    `scope` is always a concrete `ProjectArea.path` string
    (`PROJECT_GLOBAL_SCOPE` == "." for the project root). Root-scoped
    evidence is the one, explicit, mechanically-derived (never merely
    asserted) "project-global" case S2.3's scope-binding check exempts
    from area/path matching: the root area's own working directory is,
    by simple filesystem containment, an ancestor of every other area,
    so capability genuinely detected there is honestly project-wide --
    never an assumption, never a default applied to evidence Project
    Intelligence actually found somewhere else. A capability detected
    ONLY inside a non-root area (e.g. "backend", "firmware/esp32") keeps
    that area's own path as its scope and is NEVER treated as covering
    an unrelated area."""
    identities: frozenset[str]
    scope: str


# CLAUDE-ADC-S23-VERIFICATION-EVIDENCE-ARCHITECTURE-001: the one central,
# closed-set mechanism token for Python distribution package-presence
# verification -- ADC's own controlled equivalent of running `pip show
# <technical_identity>`. This is NOT a second, competing mechanism
# vocabulary: it is one more concrete, single-token identity a candidate
# may legitimately declare in ToolchainItem.provides_verification /
# VerificationCoverage.mechanism, exactly like "pytest" or
# "esphome_validate" already are (see app.council_models.ToolchainItem's
# own docstring). Fixed and importable so a candidate can never invent
# its own spelling and have it silently treated as this trusted category.
#
# CLAUDE-ADC-S23-VERIFICATION-EVIDENCE-ARCHITECTURE-FIX-002: this module
# no longer produces any TrustedVerificationGroup for this mechanism (see
# all_trusted_verification_groups()'s own docstring) -- the trust
# boundary for a "pip_show" VerificationCoverage claim now lives entirely
# in app.engineering_decision._python_package_verification_capability(),
# as an item-scoped, pre-install CAPABILITY check, never an
# environment-wide presence fact.
PACKAGE_PRESENCE_MECHANISM = "pip_show"


def _area_groups_from_pairs(
    areas: list[tuple[str, list[str], list[str], list]],
) -> tuple[TrustedVerificationGroup, ...]:
    """Shared group-building step for both the real-dataclass and dict
    shapes below -- takes each area's own (path, test_names, build_names,
    firmware_entries) and applies the SAME controlled-capability rules
    013G/014C already established, just now emitting one scope-tagged
    group per area instead of one project-wide group."""
    groups: list[TrustedVerificationGroup] = []

    def _controlled_group(name: str, table: dict) -> frozenset | None:
        entry = table.get(name)
        if entry is None or entry[1] != "controlled_execution":
            return None
        return frozenset({name, entry[0]})

    for area_path, test_names, build_names, firmware_entries in areas:
        for name in test_names:
            group = _controlled_group(name, RUNNER_MAP)
            if group:
                groups.append(TrustedVerificationGroup(group, area_path))
        for name in build_names:
            group = _controlled_group(name, BUILD_RUNNER_MAP)
            if group:
                groups.append(TrustedVerificationGroup(group, area_path))
        for fw_name, has_untrusted_hooks in firmware_entries:
            if fw_name == "esphome":
                groups.append(TrustedVerificationGroup(
                    frozenset({fw_name, FIRMWARE_RUNNER_MAP.get(fw_name, fw_name)})
                    | _ESPHOME_MECHANISM_ALIASES,
                    area_path,
                ))
            elif fw_name == "platformio" and has_untrusted_hooks is False:
                groups.append(TrustedVerificationGroup(
                    frozenset({fw_name, FIRMWARE_RUNNER_MAP.get(fw_name, fw_name)}), area_path,
                ))
    return tuple(groups)


def trusted_verification_identity_groups(project_intelligence) -> tuple[TrustedVerificationGroup, ...]:
    """CLAUDE-ARCH-S2-013G/014C: the independent, ADC-owned evidence that
    a verification identity genuinely exists in a given project AND has
    an actual controlled, registered execution route -- derived from
    Project Intelligence's own read-only, evidence-based detection
    (app.project_intelligence), deterministic and computed BEFORE the
    Engineering Council ever runs, so it can never be produced or
    influenced by the same Agent/Chairman call that authors an S2
    candidate.

    CLAUDE-ARCH-S2-014C (F2) closes a gap CDX-REVIEW-S2-014A reproduced:
    013G granted trust to any RECOGNIZED name (e.g. "ctest", "jest")
    regardless of whether S5's own Generalized Verification would ever
    actually run it in a controlled way. RUNNER_MAP/BUILD_RUNNER_MAP's
    OWN policy field ("controlled_execution" | "deferred" | "unsupported")
    already, correctly distinguishes a genuinely registered, controlled
    runner (pytest, python_unittest, cmake) from a recognized-but-not-
    controllable one (vitest, jest, mocha, ctest, make are "deferred" --
    no runner is registered for them in build_default_registry() at
    all). A group is only ever emitted when policy == "controlled_
    execution" -- recognition/name-mapping alone is NEVER treated as
    capability proof; this function proves recognized capability -> ADC-
    owned capability evidence -> a controlled, registered route, which is
    exactly the "applicable to this project/scope" + "controlled route
    exists" links S2.3 needs before "result can be observed" and
    "admissible" can even be considered.

    Firmware indicators need one extra dimension build_verification_plan()
    itself already models: PlatformIO's controllability depends on
    DetectedFirmware.has_untrusted_hooks (untrusted build-code hooks make
    its own VerificationStep policy "unsupported", never "controlled_
    execution" -- see build_verification_plan()'s firmware branch, reused
    here rather than re-derived). ESPHome has no such hook concept and is
    always controlled. The dict summary shape
    (CouncilInput.project_intelligence, used for Council/Chairman
    prompts) LOSES has_untrusted_hooks entirely (ProjectIntelligence.
    to_summary() only keeps firmware names) -- from that lossy shape,
    PlatformIO can therefore never be trusted (fail-closed: absence of
    the hook signal is never treated as "no untrusted hooks"), while
    esphome (no hook concept) still can be.

    Each returned group is the set of interchangeable identity strings
    (a detected test/build/firmware system name AND its canonical
    runner identity) for ONE real, controllable capability. Reusing
    RUNNER_MAP/BUILD_RUNNER_MAP/FIRMWARE_RUNNER_MAP (never copied) means
    this function carries no mechanism-name knowledge beyond what
    build_verification_plan() itself already encodes, and never becomes
    a second, competing verification source of truth.

    S2.3 Verification Feasibility (app.engineering_decision) is the
    intended consumer, but ALWAYS via an already-computed
    `trusted_verification_groups` parameter passed in by S2.3's caller
    (app.dev_workflow, app.engineering_council) -- app.engineering_
    decision itself never imports this module, so S2.3 stays free of any
    dependency on S5 execution code (see
    tests/test_s2_subsubsystem_architecture.py's own source-inspection
    boundary test), and S2.3 never executes S5 verification itself.

    Accepts either the real ProjectIntelligence dataclass or its dict
    summary -- both already-existing shapes, nothing new invented.
    Returns an empty tuple when no independent evidence is available at
    all (project_intelligence is None), which the S2.3 caller's own
    fail-closed compatibility check then treats as "no mechanism/
    evidence pair can be proven compatible" -- absence of independent
    evidence is never treated as permission.

    CLAUDE-ARCH-S2-014D closes the scope leak CDX-REVIEW-S2-014D
    reproduced: every group emitted above 014D was already implicitly
    "project-global" because it was built from
    ProjectIntelligence.test_system_names/build_system_names -- a
    DEDUPED UNION across every ProjectArea that discards exactly which
    area each capability was actually detected in (example: Area A has
    pytest, Area B has nothing to do with pytest at all -- the old
    project-wide union still handed S2.3 a single unscoped {"pytest",
    "pytest"} group that could corroborate a claim made anywhere in the
    project, including Area B). Every group returned now instead comes
    from ONE ProjectArea's own test_systems/build_systems/
    firmware_indicators and carries that exact `ProjectArea.path` as its
    `scope` -- an identity detected only in Area A never again produces a
    group usable to corroborate Area B. `PROJECT_GLOBAL_SCOPE` ("." , the
    project root) is the sole, mechanically-derived exception (see
    TrustedVerificationGroup's own docstring): root-detected evidence is
    honestly project-wide by filesystem containment, never merely
    defaulted.

    Both accepted shapes preserve their EXISTING project-wide behavior
    (scope=PROJECT_GLOBAL_SCOPE for every emitted group) whenever they
    carry no per-area breakdown at all -- the real dataclass's own
    `areas` tuple empty (as every pre-014D caller/test that hand-builds a
    ProjectIntelligence with `areas=()` already does), or the dict
    summary missing the new `"areas"` key (as every pre-014D caller/test
    that hand-builds the old flat dict shape already does) -- so no
    existing single-area caller loses any previously-productive
    corroboration. A project whose OWN inspection genuinely found more
    than one area (`inspect_project()`'s real, current-production output
    always populates both the flat project-wide fields AND the new
    `"areas"`/`.areas` breakdown) gets the full per-area scope binding
    from area breakdown alone.

    CLAUDE-ADC-S23-VERIFICATION-EVIDENCE-ARCHITECTURE-FIX-002: a prior
    revision of this module additionally produced Python-package
    "presence" groups from distributions installed in ADC's OWN
    CONTROLLER PROCESS environment (via importlib.metadata.distributions())
    and merged them into every caller's evidence as PROJECT_GLOBAL_SCOPE
    trust (see all_trusted_verification_groups()). Independent review
    (CDX-ADC-S23-VERIFICATION-EVIDENCE-ARCHITECTURE-REVIEW-001) correctly
    rejected that: the controller process's own Python environment can
    differ from whatever environment/interpreter a candidate's install
    would actually target, so "importable by ADC itself" never honestly
    corroborates "will be present in the real install target". That
    producer has been removed entirely (never repaired) -- S2.3's
    Python-package verification-coverage check
    (app.engineering_decision._python_package_verification_capability())
    no longer consults this function's output, or any other
    environment-wide evidence, for the "pip_show" mechanism at all; it
    instead proves an item-scoped, pre-install CAPABILITY directly from
    the SAME candidate's own toolchain materialization outcome. This
    function's own contract (file-based test/build/firmware detection
    only) is therefore now its ONLY contract, not merely its default
    one."""
    if project_intelligence is None:
        return ()

    if isinstance(project_intelligence, dict):
        raw_areas = project_intelligence.get("areas") or []
        if raw_areas:
            return _area_groups_from_pairs([
                (
                    str(area.get("path") or PROJECT_GLOBAL_SCOPE),
                    list(area.get("test_systems") or []),
                    list(area.get("build_systems") or []),
                    [
                        (fw.get("name"), fw.get("has_untrusted_hooks", True))
                        for fw in (area.get("firmware_indicators") or [])
                        if isinstance(fw, dict)
                    ],
                )
                for area in raw_areas if isinstance(area, dict)
            ])
        # No per-area breakdown available at all (legacy/lossy summary
        # shape) -- fall back to the pre-014D project-wide behavior,
        # scoped to PROJECT_GLOBAL_SCOPE so every existing single-area
        # caller/test stays exactly as productive as before.
        test_names = project_intelligence.get("test_systems", []) or []
        build_names = project_intelligence.get("build_systems", []) or []
        # PlatformIO's hook status is lost in this legacy summary shape --
        # never trusted from here. ESPHome has no hook concept.
        firmware_entries = [
            (name, True) for name in (project_intelligence.get("firmware_indicators", []) or [])
        ]
        return _area_groups_from_pairs([
            (PROJECT_GLOBAL_SCOPE, list(test_names), list(build_names), firmware_entries),
        ])

    areas = getattr(project_intelligence, "areas", ()) or ()
    if areas:
        return _area_groups_from_pairs([
            (
                area.path,
                [ts.name for ts in area.test_systems],
                [bs.name for bs in area.build_systems],
                [
                    (fw.name, getattr(fw, "has_untrusted_hooks", True))
                    for fw in area.firmware_indicators
                ],
            )
            for area in areas
        ])

    # No per-area breakdown available at all (a hand-built
    # ProjectIntelligence with areas=(), as pre-014D tests/callers use) --
    # same pre-014D project-wide fallback as the dict shape above.
    test_names = getattr(project_intelligence, "test_system_names", ()) or ()
    build_names = getattr(project_intelligence, "build_system_names", ()) or ()
    firmware_indicators = getattr(project_intelligence, "firmware_indicators", ()) or ()
    firmware_entries = [
        (fw.name, getattr(fw, "has_untrusted_hooks", True)) for fw in firmware_indicators
    ]
    return _area_groups_from_pairs([
        (PROJECT_GLOBAL_SCOPE, list(test_names), list(build_names), firmware_entries),
    ])


def all_trusted_verification_groups(
    project_intelligence,
) -> tuple[TrustedVerificationGroup, ...]:
    """CLAUDE-ADC-S23-VERIFICATION-EVIDENCE-ARCHITECTURE-FIX-002:
    productive S2.3 callers (app.dev_workflow, app.engineering_council,
    app.toolchain_materializer) call this instead of
    trusted_verification_identity_groups() directly, so a single call
    site can absorb future evidence-composition changes without every
    caller needing to know about them.

    A prior revision of this function additionally composed in
    installed_python_package_identity_groups() -- Python distributions
    present in ADC's OWN CONTROLLER PROCESS environment, treated as
    PROJECT_GLOBAL_SCOPE trust for a candidate's "pip_show" verification
    claim. Independent review (CDX-ADC-S23-VERIFICATION-EVIDENCE-
    ARCHITECTURE-REVIEW-001) correctly rejected that: the controller
    process's own environment is not provably the same
    environment/interpreter a candidate's install would actually target,
    so a package being importable by ADC itself never honestly
    corroborates presence in the real install target. That producer has
    been removed entirely (never repaired, never replaced by a
    differently-scoped equivalent) -- this function is now a plain,
    unmodified passthrough to trusted_verification_identity_groups()
    (Project-Intelligence-derived, file-based evidence only:
    pytest/unittest/cmake/esphome/platformio). Python-package
    ("pip_show") verification coverage is corroborated entirely inside
    S2.3 itself now, from an item-scoped pre-install CAPABILITY check
    (app.engineering_decision._python_package_verification_capability())
    that never consults this function's output at all -- see that
    function's own docstring for the corrected architecture."""
    return trusted_verification_identity_groups(project_intelligence)


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
    executes_through_target = True

    def can_run(self, step: VerificationStep) -> bool:
        return step.runner_type == "esphome_check"

    def execute(self, step: VerificationStep, project_root: str | Path) -> VerificationStepResult:
        root = Path(project_root).resolve()
        cwd, err = _resolve_cwd(root, step)
        if err is not None:
            return err

        esphome_bin = _resolve_tool("esphome")
        if esphome_bin is None:
            return VerificationStepResult(
                step_id=step.step_id, area=step.area,
                status=TOOL_UNAVAILABLE.value,
                verification_kind=step.verification_kind,
                runner_type=step.runner_type,
                passed=False,
                diagnostics="ESPHome CLI not found",
                unavailable_tool="esphome",
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

        budget, err = _resolve_execution_budget(step)
        if err is not None:
            return err
        result = _safe_exec(
            args, cwd, budget, tool_name="esphome",
            operation_type=step.verification_kind,
            target_executable=_ACTIVE_TARGET_EXECUTABLE.get(),
        )
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
    executes_through_target = True

    _FORBIDDEN_TARGETS = frozenset({"upload", "uploadfs", "monitor",
                                     "device", "remote"})
    _FORBIDDEN_ARGS = frozenset({"--upload-port", "--monitor-port"})

    def __init__(self):
        self._pio_cmd = shutil.which("platformio") or shutil.which("pio") or "platformio"

    def _command(self) -> str | None:
        """The PlatformIO executable to run, or None when unavailable. With
        a target scoped it comes only from the target environment."""
        if _ACTIVE_TARGET_EXECUTABLE.get() is not None:
            return _resolve_tool("platformio", "pio")
        if shutil.which("platformio") is None and shutil.which("pio") is None:
            return None
        return self._pio_cmd

    def can_run(self, step: VerificationStep) -> bool:
        return step.runner_type == "platformio"

    def execute(self, step: VerificationStep, project_root: str | Path) -> VerificationStepResult:
        root = Path(project_root).resolve()
        cwd, err = _resolve_cwd(root, step)
        if err is not None:
            return err

        pio_cmd = self._command()
        if pio_cmd is None:
            return VerificationStepResult(
                step_id=step.step_id, area=step.area,
                status=TOOL_UNAVAILABLE.value,
                verification_kind=step.verification_kind,
                runner_type=step.runner_type,
                passed=False,
                diagnostics="PlatformIO CLI not found",
                unavailable_tool="platformio",
            )

        meta = step.metadata or {}
        env = meta.get("environment", "")

        if step.verification_kind == "build":
            args = (pio_cmd, "run")
            if env:
                args = (*args, "-e", env)
        elif step.verification_kind == "test" and env == "native":
            args = (pio_cmd, "test", "-e", "native",
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

        budget, err = _resolve_execution_budget(step)
        if err is not None:
            return err
        result = _safe_exec(
            args, cwd, budget, tool_name="platformio",
            operation_type=step.verification_kind,
            target_executable=_ACTIVE_TARGET_EXECUTABLE.get(),
        )
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
    executes_through_target = True

    def can_run(self, step: VerificationStep) -> bool:
        return step.runner_type in ("cmake", "cmake_build")

    def execute(self, step: VerificationStep, project_root: str | Path) -> VerificationStepResult:
        root = Path(project_root).resolve()
        cwd, err = _resolve_cwd(root, step)
        if err is not None:
            return err

        cmake_bin = _resolve_tool("cmake")
        if cmake_bin is None:
            return VerificationStepResult(
                step_id=step.step_id, area=step.area,
                status=TOOL_UNAVAILABLE.value,
                verification_kind=step.verification_kind,
                runner_type=step.runner_type,
                passed=False,
                diagnostics="CMake not found",
                unavailable_tool="cmake",
            )

        # One build tree per source directory: a CMake cache is bound to the
        # source it was configured from, so two areas sharing a workspace
        # must never configure/build into the same cache.
        area_key = cwd.relative_to(root).as_posix()
        build_dir = root / ".ai-build" / (
            "root" if area_key == "." else hashlib.sha256(area_key.encode()).hexdigest()[:16]
        )
        build_dir.mkdir(parents=True, exist_ok=True)

        if step.verification_kind == "configure":
            args = (cmake_bin, "-S", str(cwd), "-B", str(build_dir))
        elif step.verification_kind == "build":
            args = (cmake_bin, "--build", str(build_dir))
        elif step.verification_kind == "test" and step.test_system == "ctest":
            ctest_bin = _resolve_tool("ctest")
            if ctest_bin is None:
                return VerificationStepResult(
                    step_id=step.step_id, area=step.area,
                    status=TOOL_UNAVAILABLE.value,
                    verification_kind=step.verification_kind,
                    runner_type=step.runner_type,
                    passed=False,
                    diagnostics="CTest not found",
                unavailable_tool="ctest",
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

        budget, err = _resolve_execution_budget(step)
        if err is not None:
            return err
        tool_name = "ctest" if step.verification_kind == "test" else "cmake"
        result = _safe_exec(
            args, cwd, budget, tool_name=tool_name,
            operation_type=step.verification_kind,
            target_executable=_ACTIVE_TARGET_EXECUTABLE.get(),
        )
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


def _combined_stream_diagnostics(*, prefix: str, stdout: str, stderr: str) -> str:
    """Bounded, generic diagnostic text that never silently drops a stream.

    When both stdout and stderr contain data, a controlled process may
    put purely informational lines on one stream and its actual error
    detail on the other (order depends on the tool, not on ADC), so
    both are preserved here, clearly labeled, rather than picking one
    stream and discarding the other. When only one stream has data,
    that stream alone is labeled and returned. The result is truncated
    to the same _MAX_OUTPUT bound already applied to each individual
    stream, so combining both streams never doubles the intended
    bounded diagnostic size.
    """
    sections = []
    if stdout:
        sections.append(f"STDOUT:\n{stdout}")
    if stderr:
        sections.append(f"STDERR:\n{stderr}")
    body = "\n\n".join(sections)
    text = f"{prefix}\n{body}" if prefix and body else (prefix or body)
    return text[:_MAX_OUTPUT]


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

    diagnostics = ""
    if timed_out:
        diagnostics = _combined_stream_diagnostics(
            prefix="Execution timed out.", stdout=stdout, stderr=stderr,
        )
    elif status == FAIL.value:
        if stdout or stderr:
            diagnostics = _combined_stream_diagnostics(
                prefix="", stdout=stdout, stderr=stderr,
            )
        else:
            diagnostics = f"Process exited with return code {result.returncode}"

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
        diagnostics=diagnostics,
    )
