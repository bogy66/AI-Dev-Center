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

    @staticmethod
    def _validate_registration(registration: CapabilityRegistration) -> None:
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

    def register_approved(self, registration: CapabilityRegistration) -> None:
        """Consume a complete approval decision, without accepting command policy."""
        self._validate_registration(registration)
        key = self._key(registration.capability, registration.project_scope)
        current = self._registrations.get(key)
        if current == registration:
            return
        if current is not None:
            raise ValueError(
                f"Capability already registered for project scope: {registration.capability}"
            )
        self._registrations[key] = registration

    def supersede_approved(self, registration: CapabilityRegistration) -> None:
        """Replace an existing project-scoped registration for the same
        (capability, project_scope) key with a new one carrying fresh,
        complete approval provenance (CLAUDE-E2E-003I).

        register_approved() deliberately refuses ANY conflicting entry
        for the same key, by design -- but that design predates the
        notion of a setup *generation*: an environment-repair scenario
        (a tool successfully installed once, later removed externally,
        needing a legitimate new setup generation to reinstall it at
        the exact same target path) produces a new, genuinely valid
        registration for a key an OLD generation's registration still
        occupies. This method performs the exact same validation
        register_approved() does -- it does not weaken any check -- the
        only difference is that an existing entry for the same key is
        replaced rather than rejected. Callers (register_setup_step_targets)
        only ever reach this after register_approved() itself reports a
        same-key conflict, and only ever with freshly-built, real
        provenance sourced from the current plan/generation -- never
        with anything client-suppliable.
        """
        self._validate_registration(registration)
        key = self._key(registration.capability, registration.project_scope)
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


# The single, generic, ecosystem-neutral map from a controlled
# SetupEffect to the capability/tool_name identity execute_controlled
# already uses for it. This makes explicit and reusable a mapping that
# was previously only implicit in how each adapter-specific executor
# happens to construct its own ExecutionRequest (e.g.
# PythonPackageExecutor always uses tool_name="python" for
# PYTHON_PACKAGE_INSTALL), so capability authorization and actual
# execution can never silently disagree about which capability a given
# setup effect belongs to. Adding a future controlled effect (a
# compiler, a build tool, an SDK) means adding one entry here — never a
# new, ecosystem-specific authorization mechanism.
_CAPABILITY_BY_SETUP_EFFECT: dict[str, str] = {
    SetupEffect.PYTHON_PACKAGE_INSTALL: "python",
}


def capability_for_setup_effect(setup_effect: str | None) -> str | None:
    """Return the capability/tool_name identity for a controlled SetupEffect,
    or None when the effect has no execution-target/capability concept."""
    if not setup_effect:
        return None
    return _CAPABILITY_BY_SETUP_EFFECT.get(setup_effect)


# CLAUDE-E2E-NIO-008A: the single, generic, ecosystem-neutral map from a
# controlled SetupEffect to the install_method compatibility contract its
# own controlled executor enforces at execution time. A real
# Real-System-E2E reached 50% and failed because ToolchainMaterializer
# (the producer that decides whether a SetupStep may become an
# approvable "install" action) never consulted this contract before
# letting a free-form, compound shell install_method through -- only
# PythonPackageExecutor (the consumer, at execution time) ever checked
# it, too late to prevent an already-approved, already-unexecutable
# step. Registering the SAME function each controlled executor already
# uses (never a second, heuristic, or duplicated implementation) here
# means the producer and the consumer can never silently disagree about
# what "compatible" means for a given effect. Adding a future controlled
# effect (a compiler, a build tool, an SDK) means adding one entry here
# -- never a new, ecosystem-specific compatibility mechanism, and never
# a requirement that the materializer parse or understand command syntax
# itself.
def _install_method_validators() -> dict:
    from app.python_package_executor import is_supported_python_package_install_method
    return {SetupEffect.PYTHON_PACKAGE_INSTALL: is_supported_python_package_install_method}


def is_install_method_compatible_with_controlled_executor(
    setup_effect: str | None, install_method: str | None, package: str,
) -> bool:
    """True when setup_effect is not currently controlled at all
    (nothing further constrains an uncontrolled/manual-review effect
    here -- it was never going to become an executable "install" action
    regardless), or when the compatibility contract registered for a
    controlled setup_effect accepts install_method for package.

    CLAUDE-PRE-E2E-009A: a CONTROLLED setup_effect with no registered
    validator fails closed (False), never silently True. Real-System-E2E
    #4 exposed exactly this gap for python_package_install specifically;
    generalizing "no validator" to "assume compatible" would let the
    identical failure class recur, undetected, for the next controlled
    effect anyone adds to CONTROLLED_SETUP_EFFECTS without also
    registering its own compatibility contract here. Adding a new
    controlled effect therefore REQUIRES registering its validator in
    the same change -- there is no silent, permissive default.

    Never inspects install_method's own text/syntax itself -- always
    delegates to the exact same function the effect's own controlled
    executor uses."""
    if not is_controlled_setup_effect(setup_effect):
        return True
    validator = _install_method_validators().get(setup_effect)
    if validator is None:
        return False
    return validator(install_method, package)


def register_setup_step_targets(
    plan,
    project_root: str | Path,
    *,
    engineering_council_ref: str,
    chairman_approval_ref: str,
    human_approval_ref: str,
    capability_registry: CapabilityRegistry = DEFAULT_CAPABILITY_REGISTRY,
) -> tuple[CapabilityRegistration, ...]:
    """Authorize each already-approved SetupStep's already-resolved
    execution target for later execution, pinned to its exact resolved
    path and scoped to this project — independent of any later PATH
    lookup change.

    This function does not itself decide or check plan-level approval:
    it is the caller's responsibility to invoke it only for a plan whose
    status is genuinely "approved" (mirroring CapabilityRegistration's
    own design of consuming, never making, an approval decision). It
    does, however, defensively re-check each individual step's own
    is_approved flag before registering that step's target — today's
    only production path to a plan.status == "approved" plan
    (SetupApproval.approve()) sets is_approved=True for every step whose
    action is a concrete executable action (currently "install"), never
    for a "manual_review" step, so a step that is not itself approved
    is never authorized for execution, whether because it is a
    "manual_review" step or because a future partial-approval model, or
    a hand-built/forged plan, ever produced some other mismatch between
    plan-level and step-level approval. It builds
    one project-scoped CapabilityRegistration per distinct (capability,
    target_executable) pair present in the plan's steps and registers
    each through the existing, unmodified, approval-provenance-gated
    CapabilityRegistry.register_approved() — there is no second,
    competing authorization mechanism, and no new field is added to any
    central model to support this.

    Ecosystem-neutral by construction: capability_for_setup_effect() is
    the only place a SetupEffect maps to a capability/tool_name
    identity; a step whose type has no such mapping (today, anything
    other than a controlled Python-package install) is silently
    skipped — never guessed at.

    Raises whatever CapabilityRegistry.register_approved() raises (a
    ValueError) for an incomplete/mismatched provenance, an already-
    registered conflicting capability for this project scope, or any
    other violation of that existing, unmodified validation — this
    function fails closed exactly the same way the underlying
    mechanism already does, never with a softer or different failure
    mode of its own.
    """
    resolved_root = str(Path(project_root).resolve())
    registered: dict[tuple[str, str], CapabilityRegistration] = {}
    for step in plan.steps:
        if not step.is_approved:
            continue
        if not step.target_executable:
            continue
        capability = capability_for_setup_effect(step.setup_effect)
        if capability is None:
            continue
        key = (capability, step.target_executable)
        if key in registered:
            continue
        provenance = ApprovalProvenance(
            project_intelligence_ref=resolved_root,
            engineering_council_ref=engineering_council_ref,
            chairman_approval_ref=chairman_approval_ref,
            human_approval_ref=human_approval_ref,
        )
        registration = CapabilityRegistration(
            capability=capability,
            executable_names=(step.target_executable,),
            allowed_operations=("install", "verification"),
            approval_provenance=provenance,
            project_scope=resolved_root,
        )
        try:
            capability_registry.register_approved(registration)
        except ValueError as error:
            if "already registered" not in str(error):
                raise
            existing = capability_registry.get(capability, resolved_root)
            if existing is None or existing.executable_names != registration.executable_names:
                # A genuinely different executable identity for this
                # capability/scope is a different, more dangerous kind
                # of conflict (e.g. Target A vs Target B) -- never
                # silently superseded, fails closed exactly as before
                # CLAUDE-E2E-003I.
                raise
            # CLAUDE-E2E-003I: same capability, same scope, same exact
            # target_executable, only the approval provenance differs --
            # this is the environment-repair shape (an earlier setup
            # generation's registration for this exact target is still
            # on file; a new generation's real, freshly-built provenance
            # now supersedes it). `registration` here is always built
            # from the CURRENT plan's real generation/council/chairman/
            # human-approval references, never client-suppliable, so
            # replacing the stale entry is safe: the old generation's
            # approval is never reused, a genuinely new one authorizes this.
            capability_registry.supersede_approved(registration)
        registered[key] = registration
    return tuple(registered.values())


# CLAUDE-ADC-ZIELBILD-DIFF-FIX-001 (B1): operation types that mutate
# project/host state. A bootstrap registration (approval_provenance=None,
# see _bootstrap() above) may still authorize non-mutating operations
# (verification/test/build/...) exactly as it always has -- the outer
# setup workflow's own plan/step approval + ApprovedPlanContent checks
# are unaffected either way -- but Controlled Execution itself must
# never let a mutating operation such as "install" run from a
# capability registration that carries no ApprovalProvenance, per the
# target architecture's Section 16 boundary.
_MUTATING_OPERATION_TYPES = frozenset({"install"})


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
    if request.operation_type in _MUTATING_OPERATION_TYPES:
        provenance = registration.approval_provenance
        if provenance is None or not provenance.is_complete():
            return _error(
                INVALID_PLAN,
                f"Mutating operation {request.operation_type} requires an "
                f"approval-provenance-backed capability registration: {request.tool_name}",
            )
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
