"""Controlled subprocess execution for potentially untrusted project code."""
from __future__ import annotations

from dataclasses import dataclass
import os as _os
from pathlib import Path
import shutil
import subprocess
import sys

from app.verification import INVALID_PLAN, TOOL_UNAVAILABLE, UNSUPPORTED, VerificationStep, VerificationStepResult


@dataclass(frozen=True)
class CapabilityRegistration:
    """Approved executable identities for one narrowly named capability."""
    capability: str
    executable_names: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.capability or not self.executable_names:
            raise ValueError("Capability and executable identities are required")
        if any(not name or "\x00" in name for name in self.executable_names):
            raise ValueError("Executable identities must be non-empty paths or names")


class CapabilityRegistry:
    """Explicit set of capabilities admitted by the approval/registration flow."""
    def __init__(self, registrations: tuple[CapabilityRegistration, ...] = ()):
        self._registrations: dict[str, CapabilityRegistration] = {}
        for registration in registrations:
            self.register_approved(registration)

    def register_approved(self, registration: CapabilityRegistration) -> None:
        """Consume an approved registration; the approval workflow owns the decision."""
        if registration.capability in self._registrations:
            raise ValueError(f"Capability already registered: {registration.capability}")
        self._registrations[registration.capability] = registration

    def get(self, capability: str) -> CapabilityRegistration | None:
        return self._registrations.get(capability)


# Bootstrap registrations for today's runners, not a closed validation allowlist.
DEFAULT_CAPABILITY_REGISTRY = CapabilityRegistry((
    CapabilityRegistration("python", (sys.executable, "python", "python3")),
    CapabilityRegistration("esphome", ("esphome",)),
    CapabilityRegistration("platformio", ("platformio", "pio")),
    CapabilityRegistration("cmake", ("cmake",)),
    CapabilityRegistration("ctest", ("ctest",)),
    CapabilityRegistration("make", ("make",)),
    CapabilityRegistration("npm", ("npm",)),
    CapabilityRegistration("pnpm", ("pnpm",)),
    CapabilityRegistration("yarn", ("yarn",)),
))

_DENIED_ARGS = frozenset({
    "shell=True", "shell = True", "rm -rf", "shutdown", "reboot",
    "--device", "--privileged", "/var/run/docker.sock",
})


def _find_executable(name: str) -> str | None:
    return shutil.which(name)


@dataclass(frozen=True)
class ExecutionRequest:
    args: tuple[str, ...]
    cwd: str
    timeout: int
    tool_name: str


def _error(status, diagnostics: str) -> VerificationStepResult:
    return VerificationStepResult(
        step_id="boundary", area=".", status=status.value,
        verification_kind="execution", runner_type="controlled_boundary",
        passed=False, diagnostics=diagnostics,
    )


def _resolved_command(command: str) -> Path | None:
    found = _find_executable(command) if Path(command).name == command else command
    if not found:
        return None
    path = Path(found)
    return path.resolve()


def validate_request(
    request: ExecutionRequest, project_root: str | Path,
    capability_registry: CapabilityRegistry = DEFAULT_CAPABILITY_REGISTRY,
) -> VerificationStepResult | None:
    """Return an error when a request violates any execution boundary rule."""
    root = Path(project_root).resolve()
    cwd = Path(request.cwd).resolve()
    if not cwd.is_relative_to(root):
        return _error(INVALID_PLAN, f"cwd escapes project root: {cwd}")

    registration = capability_registry.get(request.tool_name)
    if registration is None:
        return _error(UNSUPPORTED, f"Capability not registered: {request.tool_name}")
    if not request.args:
        return _error(INVALID_PLAN, "Execution argv must not be empty")

    actual = _resolved_command(str(request.args[0]))
    approved = {
        resolved for name in registration.executable_names
        if (resolved := _resolved_command(name)) is not None
    }
    if not approved:
        return _error(TOOL_UNAVAILABLE, f"Tool not found: {request.tool_name}")
    if actual is None:
        return _error(TOOL_UNAVAILABLE, f"Executable not found: {request.args[0]}")
    if actual not in approved:
        return _error(INVALID_PLAN, f"Executable does not match capability {request.tool_name}: {request.args[0]}")

    args_flat = " ".join(str(arg) for arg in request.args)
    for denied in _DENIED_ARGS:
        if denied in args_flat:
            return _error(INVALID_PLAN, f"Denied argument pattern: {denied}")
    if request.timeout <= 0:
        return _error(INVALID_PLAN, "Execution timeout must be positive")
    return None


ENV_ALLOWLIST_PREFIXES = frozenset({"PATH", "HOME", "USER", "LANG", "LC_", "PYTHON", "VIRTUAL_ENV", "CONDA"})


def _controlled_env() -> dict[str, str]:
    return {key: value for key, value in _os.environ.items()
            if any(key.startswith(prefix) for prefix in ENV_ALLOWLIST_PREFIXES)}


def execute_controlled(
    request: ExecutionRequest, project_root: str | Path,
    capability_registry: CapabilityRegistry = DEFAULT_CAPABILITY_REGISTRY,
) -> subprocess.CompletedProcess | None:
    """Validate and execute a request. There is no unvalidated subprocess path."""
    violation = validate_request(request, project_root, capability_registry)
    if violation is not None:
        raise ValueError(violation.diagnostics)
    try:
        return subprocess.run(
            list(request.args), cwd=str(Path(request.cwd).resolve()),
            capture_output=True, text=True, timeout=request.timeout, check=False,
            env=_controlled_env(),
        )
    except subprocess.TimeoutExpired as exc:
        result = subprocess.CompletedProcess(list(request.args), -1, exc.stdout or "", exc.stderr or "")
        result.timed_out = True
        return result
    except OSError:
        return None


def execute_step_controlled(
    step: VerificationStep, project_root: str | Path, args: tuple[str, ...],
    tool_name: str, timeout: int,
    capability_registry: CapabilityRegistry = DEFAULT_CAPABILITY_REGISTRY,
) -> VerificationStepResult:
    """Full boundary check and controlled execution for one verification step."""
    from app.verification import _build_step_result, _resolve_cwd
    root = Path(project_root).resolve()
    cwd, err = _resolve_cwd(root, step)
    if err is not None:
        return err
    request = ExecutionRequest(args, str(cwd), timeout, tool_name)
    violation = validate_request(request, root, capability_registry)
    if violation is not None:
        return VerificationStepResult(
            step_id=step.step_id, area=step.area, status=violation.status,
            verification_kind=step.verification_kind, runner_type=step.runner_type,
            passed=False, diagnostics=violation.diagnostics,
        )
    result = execute_controlled(request, root, capability_registry)
    if result is None:
        return VerificationStepResult(
            step_id=step.step_id, area=step.area, status=TOOL_UNAVAILABLE.value,
            verification_kind=step.verification_kind, runner_type=step.runner_type,
            passed=False, diagnostics=f"Execution failed: {tool_name}",
        )
    return _build_step_result(step, result, args)
