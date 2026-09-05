"""Controlled subprocess execution for potentially untrusted project code."""
from __future__ import annotations

from dataclasses import dataclass
import os as _os
from pathlib import Path
import shutil
import subprocess
import sys

from app.requirement_model import SetupEffect
from app.verification import INVALID_PLAN, TOOL_UNAVAILABLE, UNSUPPORTED, VerificationStep, VerificationStepResult


ACTIVE = "active"
SUSPENDED = "suspended"
REVOKED = "revoked"
_REGISTRATION_STATUSES = frozenset({ACTIVE, SUSPENDED, REVOKED})
_SAFE_OPERATION_TYPES = frozenset({
    "verification", "validate", "compile", "build", "test", "configure",
    "install",
})

# Setup effects for which ADC currently has a controlled execution backend.
# This is a capability-policy boundary, not a shell-command allowlist.
CONTROLLED_SETUP_EFFECTS = frozenset({
    SetupEffect.PYTHON_PACKAGE_INSTALL,
})


def is_controlled_setup_effect(effect: str | None) -> bool:
    """Return True when ADC has a controlled backend for *effect*."""
    if not effect or not isinstance(effect, str):
        return False
    return effect in CONTROLLED_SETUP_EFFECTS


@dataclass(frozen=True)
class ApprovalProvenance:
    """References proving the complete authority chain for a registration."""
    project_intelligence_ref: str
    engineering_council_ref: str
    chairman_approval_ref: str
    human_approval_ref: str

    def is_complete(self) -> bool:
        return all((
            self.project_intelligence_ref,
            self.engineering_council_ref,
            self.chairman_approval_ref,
            self.human_approval_ref,
        ))


@dataclass(frozen=True)
class CapabilityRegistration:
    """Approval-aware executable capability; never an argv or host policy."""
    capability: str
    executable_names: tuple[str, ...]
    allowed_operations: tuple[str, ...]
    approval_provenance: ApprovalProvenance | None
    project_scope: str | None = None
    status: str = ACTIVE
    bootstrap_compatibility: bool = False

    def __post_init__(self) -> None:
        if not self.capability or not self.executable_names or not self.allowed_operations:
            raise ValueError("Capability, executable identities and operations are required")
        if any(not name or "\x00" in name for name in self.executable_names):
            raise ValueError("Executable identities must be non-empty paths or names")
        if self.status not in _REGISTRATION_STATUSES:
            raise ValueError(f"Unknown registration status: {self.status}")
        unsupported = set(self.allowed_operations) - _SAFE_OPERATION_TYPES
        if unsupported:
            raise ValueError(f"Unsafe or unknown operation types: {sorted(unsupported)}")
        if self.project_scope is not None:
            object.__setattr__(self, "project_scope", str(Path(self.project_scope).resolve()))


class CapabilityRegistry:
    """Explicit set of capabilities admitted by the approval/registration flow."""
    def __init__(self, registrations: tuple[CapabilityRegistration, ...] = ()):
        self._registrations: dict[tuple[str, str | None], CapabilityRegistration] = {}
        for registration in registrations:
            self.register_approved(registration)

    @staticmethod
    def _key(capability: str, project_scope: str | Path | None) -> tuple[str, str | None]:
        scope = None if project_scope is None else str(Path(project_scope).resolve())
        return capability, scope

    def register_approved(self, registration: CapabilityRegistration) -> None:
        """Consume a complete approval decision, without accepting command policy."""
        if registration.status != ACTIVE:
            raise ValueError("Only active capability registrations may be registered")
        if registration.bootstrap_compatibility:
            raise ValueError("Bootstrap compatibility entries cannot use the approval API")
        if registration.project_scope is None:
            raise ValueError("Dynamic capability registration requires a project scope")
        provenance = registration.approval_provenance
        if provenance is None or not provenance.is_complete():
            raise ValueError("Complete approval provenance is required")
        if Path(provenance.project_intelligence_ref).resolve() != Path(registration.project_scope):
            raise ValueError("Project scope does not match Project Intelligence provenance")
        key = self._key(registration.capability, registration.project_scope)
        current = self._registrations.get(key)
        if current == registration:
            return
        if current is not None:
            raise ValueError(
                f"Capability already registered for project scope: {registration.capability}"
            )
        self._registrations[key] = registration

    def _register_bootstrap(self, registration: CapabilityRegistration) -> None:
        """Internal compatibility path for the fixed runners shipped today."""
        if not registration.bootstrap_compatibility:
            raise ValueError("Bootstrap registration must be marked as compatibility")
        key = self._key(registration.capability, None)
        if key in self._registrations:
            raise ValueError(f"Capability already registered: {registration.capability}")
        self._registrations[key] = registration

    def get(
        self, capability: str, project_root: str | Path | None = None,
    ) -> CapabilityRegistration | None:
        if project_root is not None:
            scoped = self._registrations.get(self._key(capability, project_root))
            if scoped is not None:
                return scoped
        bootstrap = self._registrations.get(self._key(capability, None))
        if bootstrap is not None and bootstrap.bootstrap_compatibility:
            return bootstrap
        return None

    def set_status(
        self, capability: str, status: str,
        project_scope: str | Path | None = None,
    ) -> None:
        """Suspend or revoke a registration without replacing its provenance."""
        if status not in (SUSPENDED, REVOKED):
            raise ValueError("An existing registration may only be suspended or revoked")
        key = self._key(capability, project_scope)
        current = self._registrations.get(key)
        if current is None:
            raise KeyError(capability)
        self._registrations[key] = CapabilityRegistration(
            capability=current.capability,
            executable_names=current.executable_names,
            allowed_operations=current.allowed_operations,
            approval_provenance=current.approval_provenance,
            project_scope=current.project_scope,
            status=status,
            bootstrap_compatibility=current.bootstrap_compatibility,
        )


# Bootstrap registrations for today's runners, not a closed validation allowlist.
def _bootstrap(capability: str, executables: tuple[str, ...], operations: tuple[str, ...]) -> CapabilityRegistration:
    return CapabilityRegistration(
        capability, executables, operations, approval_provenance=None,
        bootstrap_compatibility=True,
    )


DEFAULT_CAPABILITY_REGISTRY = CapabilityRegistry()
for _registration in (
    _bootstrap("python", (sys.executable, "python", "python3"), ("verification", "test", "install")),
    _bootstrap("esphome", ("esphome",), ("validate", "compile")),
    _bootstrap("platformio", ("platformio", "pio"), ("build", "test")),
    _bootstrap("cmake", ("cmake",), ("configure", "build")),
    _bootstrap("ctest", ("ctest",), ("test",)),
    _bootstrap("make", ("make",), ("build", "test")),
    _bootstrap("npm", ("npm",), ("build", "test")),
    _bootstrap("pnpm", ("pnpm",), ("build", "test")),
    _bootstrap("yarn", ("yarn",), ("build", "test")),
):
    DEFAULT_CAPABILITY_REGISTRY._register_bootstrap(_registration)
del _registration

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
    operation_type: str = "verification"


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

    registration = capability_registry.get(request.tool_name, root)
    if registration is None:
        return _error(UNSUPPORTED, f"Capability not registered: {request.tool_name}")
    if registration.status != ACTIVE:
        return _error(UNSUPPORTED, f"Capability registration is {registration.status}: {request.tool_name}")
    if request.operation_type not in registration.allowed_operations:
        return _error(INVALID_PLAN, f"Operation {request.operation_type} is not approved for capability {request.tool_name}")
    if registration.project_scope is not None and root != Path(registration.project_scope):
        return _error(INVALID_PLAN, f"Capability is not registered for project scope: {root}")
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
    operation_type: str | None = None,
) -> VerificationStepResult:
    """Full boundary check and controlled execution for one verification step."""
    from app.verification import _build_step_result, _resolve_cwd
    root = Path(project_root).resolve()
    cwd, err = _resolve_cwd(root, step)
    if err is not None:
        return err
    request = ExecutionRequest(
        args, str(cwd), timeout, tool_name,
        operation_type or step.verification_kind,
    )
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
