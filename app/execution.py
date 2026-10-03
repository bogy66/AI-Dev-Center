"""Controlled subprocess execution for potentially untrusted project code."""
from __future__ import annotations

from dataclasses import dataclass
import errno as _errno
import os as _os
from pathlib import Path
import shutil
import signal
import subprocess
import sys

from app.interactive_terminal import InteractiveTerminalLauncher
from app.requirement_model import SetupEffect
from app.verification import (
    EXECUTION_ERROR, INVALID_PLAN, TOOL_UNAVAILABLE, UNSUPPORTED, VerificationStep, VerificationStepResult,
)


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
        # project scope -> execution targets (resolved executable paths)
        # an approved setup plan selected for that project. Technology
        # neutral: a target is only an absolute executable path.
        self._approved_targets: dict[str, dict[str, ApprovalProvenance]] = {}
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

    def approve_execution_target(
        self, project_scope: str | Path, target_executable: str,
        provenance: ApprovalProvenance,
    ) -> None:
        """Record that an approved plan selected exactly this execution
        target for this project. Requires complete provenance bound to the
        same project scope and an absolute target path; anything else is
        rejected, never normalized into an approval."""
        scope = str(Path(project_scope).resolve())
        if (not isinstance(target_executable, str) or not target_executable
                or "\x00" in target_executable
                or not Path(target_executable).is_absolute()):
            raise ValueError("Execution target must be an absolute executable path")
        if provenance is None or not provenance.is_complete():
            raise ValueError("Complete approval provenance is required")
        if Path(provenance.project_intelligence_ref).resolve() != Path(scope):
            raise ValueError("Project scope does not match Project Intelligence provenance")
        self._approved_targets.setdefault(scope, {})[target_executable] = provenance

    def is_execution_target_approved(
        self, project_scope: str | Path, target_executable: str | None,
    ) -> bool:
        if not target_executable:
            return False
        scope = str(Path(project_scope).resolve())
        return target_executable in self._approved_targets.get(scope, {})

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


def _installer_identity_resolvers() -> dict:
    from app.python_package_executor import resolve_python_package_installer_identity
    return {SetupEffect.PYTHON_PACKAGE_INSTALL: resolve_python_package_installer_identity}


def resolve_structured_installer_identity(
    setup_effect: str | None, install_method: str | None, package: str | None,
) -> str | None:
    """IF_REQ_037: the one central resolution from a validated
    install_method assertion to its structured installer identity.

    Delegates to the resolver registered for the controlled setup_effect
    -- the same parser that effect's executor and ToolchainMaterializer
    already use -- so accepted equivalent representations resolve to one
    installer identity. An uncontrolled effect, a controlled effect with
    no registered resolver, a missing package identity or a rejected
    install_method all resolve to None (fail closed)."""
    if not is_controlled_setup_effect(setup_effect):
        return None
    resolver = _installer_identity_resolvers().get(setup_effect)
    if resolver is None or not package:
        return None
    return resolver(install_method, package)


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
    # The approved plan's selected execution targets (each approved step's
    # target and the environment the plan itself selected, which exists
    # independent of its steps) are approved for target-bound execution.
    provenance = ApprovalProvenance(
        project_intelligence_ref=resolved_root,
        engineering_council_ref=engineering_council_ref,
        chairman_approval_ref=chairman_approval_ref,
        human_approval_ref=human_approval_ref,
    )
    selected = {step.target_executable for step in plan.steps
                if step.is_approved and step.target_executable}
    plan_target = getattr(plan, "environment_target_executable", None)
    if isinstance(plan_target, str) and plan_target:
        selected.add(plan_target)
    for target in sorted(selected):
        if Path(target).is_absolute():  # a non-absolute target is never approved
            capability_registry.approve_execution_target(resolved_root, target, provenance)
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
    # The selected, approved execution target this request is bound to
    # (IF_REQ_038). When set, the executable is identified ONLY relative to
    # that target's own environment directory; a host PATH lookup is never
    # consulted or substituted. None = legacy host-resolved request.
    target_executable: str | None = None
    # The project whose approved plan selected `target_executable`. Set by
    # ADC's own verification scope (never by project content): S5 runs in an
    # isolated workspace copy whose root is not the approved project.
    approval_scope: str | None = None


def target_environment_dir(target_executable: str | None) -> str | None:
    """Directory holding the executables of the environment `target_executable`
    belongs to: its own directory as given (symlinks deliberately not
    resolved, so an isolated environment's tool directory is used rather
    than the base installation it links to). None when the target is not an
    existing, absolute, executable file."""
    if not target_executable:
        return None
    path = Path(target_executable)
    if not (path.is_absolute() and path.is_file() and _os.access(path, _os.X_OK)):
        return None
    return str(path.parent)


def resolve_tool_in_target(target_executable: str | None, *names: str) -> str | None:
    """Find a tool by name ONLY in the selected target's environment
    directory -- never on the host PATH and never by a different tool's
    name. Unknown or unusable target, or tool absent there -> None."""
    env_dir = target_environment_dir(target_executable)
    if env_dir is None:
        return None
    for name in names:
        if not name or Path(name).name != name:
            continue
        found = shutil.which(name, path=env_dir)
        if found and Path(found).parent == Path(env_dir):
            return found
    return None


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

    if request.target_executable is not None:
        violation = _target_bound_violation(request, registration, root, capability_registry)
        if violation is not None:
            return violation
        return _common_argument_violation(request)

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

    return _common_argument_violation(request)


def _common_argument_violation(request: ExecutionRequest) -> VerificationStepResult | None:
    args_flat = " ".join(str(arg) for arg in request.args)
    for denied in _DENIED_ARGS:
        if denied in args_flat:
            return _error(INVALID_PLAN, f"Denied argument pattern: {denied}")
    if request.timeout <= 0:
        return _error(INVALID_PLAN, "Execution timeout must be positive")
    return None


def _target_bound_violation(
    request: ExecutionRequest, registration: CapabilityRegistration,
    root: Path, capability_registry: CapabilityRegistry,
) -> VerificationStepResult | None:
    """Validate a request bound to a selected execution target. The tool
    must be one of the capability's own approved executable identities (by
    name), and must live in the environment directory of a target that an
    approved plan selected for this project. The host PATH is not consulted
    at all: an unknown, unapproved, or unusable target, or a tool outside
    the target's environment, fails closed."""
    target = request.target_executable
    if not capability_registry.is_execution_target_approved(request.approval_scope or root, target):
        return _error(INVALID_PLAN, f"Execution target is not approved for this project: {target}")
    env_dir = target_environment_dir(target)
    if env_dir is None:
        return _error(TOOL_UNAVAILABLE, f"Execution target is not usable: {target}")
    command = str(request.args[0])
    command_path = Path(command)
    if not command_path.is_absolute() or Path(_os.path.normpath(command)).parent != Path(env_dir):
        return _error(INVALID_PLAN, f"Executable is outside the selected target environment: {command}")
    approved_names = {Path(name).name for name in registration.executable_names}
    if command_path.name not in approved_names:
        return _error(INVALID_PLAN, f"Executable does not match capability {request.tool_name}: {command}")
    if not (command_path.is_file() and _os.access(command_path, _os.X_OK)):
        return _error(TOOL_UNAVAILABLE, f"Executable not found in target environment: {command}")
    return None


ENV_ALLOWLIST_PREFIXES = frozenset({"PATH", "HOME", "USER", "LANG", "LC_", "PYTHON", "VIRTUAL_ENV", "CONDA"})


def _controlled_env() -> dict[str, str]:
    return {key: value for key, value in _os.environ.items()
            if any(key.startswith(prefix) for prefix in ENV_ALLOWLIST_PREFIXES)}


# CLAUDE-ADC-VISIBLE-TERMINAL-FOR-SOFTWARE-INSTALLATION-001: the single,
# central, deterministic classification of which controlled operations
# are a software installation. This is exactly
# ExecutionRequest.operation_type == "install" -- the same structured
# field validate_request() already treats as mutating
# (_MUTATING_OPERATION_TYPES) -- never inferred from command text/argv.
# "install" is constructed in exactly one place in this codebase
# (PythonPackageExecutor._run(), whose "install" default is used only
# for the real pip-install call itself; its post-install verification
# call explicitly overrides operation_type to "verification"), so this
# classification is ecosystem-neutral by construction: any future
# controlled executor for another ecosystem (system packages, project
# toolchains, ...) that builds an ExecutionRequest with
# operation_type="install" is automatically routed the same way,
# without this function -- or execute_controlled itself -- ever
# needing to change.
def is_software_installation_request(request: ExecutionRequest) -> bool:
    """Return True when *request* is a controlled software installation."""
    return request.operation_type == "install"


def execute_controlled(
    request: ExecutionRequest, project_root: str | Path,
    capability_registry: CapabilityRegistry = DEFAULT_CAPABILITY_REGISTRY,
    terminal_launcher: InteractiveTerminalLauncher | None = None,
) -> subprocess.CompletedProcess | None:
    """Validate and execute a request. There is no unvalidated subprocess
    path, and -- CLAUDE-ADC-VISIBLE-TERMINAL-FOR-SOFTWARE-INSTALLATION-001
    -- no hidden-subprocess path for a request classified as a software
    installation: every such request is routed through
    InteractiveTerminalLauncher (a visible, interactive terminal),
    never through the direct, invisible subprocess.run() call below,
    which remains exactly as before for every non-installation
    operation type (verification, test, build, compile, configure,
    validate). `terminal_launcher` is an injection point for tests
    only; production callers always use the default, real launcher."""
    violation = validate_request(request, project_root, capability_registry)
    if violation is not None:
        raise ValueError(violation.diagnostics)

    if is_software_installation_request(request):
        launcher = terminal_launcher if terminal_launcher is not None else InteractiveTerminalLauncher()
        return launcher.run(
            request.args, str(Path(request.cwd).resolve()), _controlled_env(),
            request.timeout,
        )

    try:
        return run_contained_process(
            list(request.args), cwd=str(Path(request.cwd).resolve()),
            timeout=request.timeout, env=_controlled_env(),
        )
    except OSError as exc:
        # Raised only by the launch itself: the process never started.
        if exc.errno in _EXECUTABLE_UNAVAILABLE_ERRNOS:
            return None
        raise ControlledExecutionError(
            f"Controlled process could not be started: {exc}", started=False,
        ) from exc


# CLAUDE-ADC-RSE033-TIMEOUT-TAXONOMY-GATE-PROOF-CLOSURE-FIX-003: launch
# failures that mean "this executable cannot be executed" -- the only
# controlled-execution failures that are evidence of an unavailable tool
# (execute_controlled() returns None for them).
_EXECUTABLE_UNAVAILABLE_ERRNOS = frozenset({
    _errno.ENOENT, _errno.EACCES, _errno.EPERM, _errno.ENOEXEC,
    _errno.ENOTDIR, _errno.ELOOP, _errno.ENAMETOOLONG,
})


class ControlledExecutionError(RuntimeError):
    """The controlled execution itself failed -- never evidence that the
    tool is unavailable. `started` records whether the process had been
    started: once it has, any later runtime/communication failure is an
    execution error, never TOOL_UNAVAILABLE. Deliberately not a
    ValueError/OSError, so no caller can mistake it for a boundary
    rejection or an unavailable executable."""

    def __init__(self, message: str, *, started: bool):
        super().__init__(message)
        self.started = started


# CLAUDE-ADC-RSE033-ESPHOME-COMPILE-TIMEOUT-REQ-CODE-FIX-001: the return
# code a timed-out controlled process result carries. It is a synthetic
# timeout marker, never a real child exit status -- `timed_out` on the
# same result is the authoritative timeout fact.
TIMEOUT_RETURN_CODE = -1
# Bounded grace between asking the timed-out process tree to terminate
# and forcing it; the whole tree is always force-killed afterwards.
_TERMINATION_GRACE_SECONDS = 5


def _as_text(value) -> str:
    """The one deterministic decoding of captured process output: UTF-8
    with errors="replace" (an undecodable byte becomes U+FFFD, the
    surrounding valid text is kept) and universal-newline translation,
    as text mode would apply. Never raises -- output is diagnostic
    evidence, so a malformed byte can never change a process outcome."""
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
    elif not isinstance(value, str):
        value = str(value)
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _signal_process_tree(process: subprocess.Popen, *, force: bool) -> None:
    """Ask (SIGTERM) or force (SIGKILL) the controlled process's whole
    session/process group to stop (POSIX), or the process itself where
    process groups are unavailable."""
    try:
        if _os.name == "posix":
            _os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
        elif force:
            process.kill()
        else:
            process.terminate()
    except (ProcessLookupError, PermissionError):
        pass


def _contain_process_tree(process: subprocess.Popen) -> None:
    """Final containment of an owned process tree: force-kill the whole
    session/process group (POSIX) and reap the leader. Idempotent."""
    _signal_process_tree(process, force=True)
    try:
        process.kill()
    except OSError:
        pass
    process.wait()


def run_contained_process(
    args: list[str], *, cwd: str, timeout: int, env: dict[str, str],
) -> subprocess.CompletedProcess:
    """Run one already-validated argv (never a shell) as the leader of its
    own session/process group, so everything it spawns can be contained.

    On timeout the whole process tree is asked to terminate (SIGTERM),
    given a bounded grace, then force-killed (SIGKILL) -- no descendant of
    the controlled process that stays in its session/process group
    outlives the budget. Output is captured as raw bytes and decoded once
    by _as_text only after cleanup, so no output content can interrupt
    it. The result carries `timed_out=True`, the synthetic
    TIMEOUT_RETURN_CODE and the partial stdout/stderr captured so far,
    always as str."""
    if _os.name == "posix":
        isolation = {"start_new_session": True}
    else:
        isolation = {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    try:
        process = subprocess.Popen(
            args, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, **isolation,
        )
    except OSError:
        raise  # not started; execute_controlled() classifies the launch errno
    except Exception as exc:
        raise ControlledExecutionError(
            f"Controlled process could not be started: {exc}", started=False,
        ) from exc
    # From here on the process has started.
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        stdout, stderr = _terminate_process_tree(process, exc.stdout, exc.stderr)
        result = subprocess.CompletedProcess(
            args, TIMEOUT_RETURN_CODE, _as_text(stdout), _as_text(stderr),
        )
        result.timed_out = True
        return result
    except Exception as exc:
        _contain_process_tree(process)
        raise ControlledExecutionError(
            f"Controlled execution failed after the process started: {exc}", started=True,
        ) from exc
    except BaseException:
        _contain_process_tree(process)
        raise
    return subprocess.CompletedProcess(args, process.returncode, _as_text(stdout), _as_text(stderr))


def _terminate_process_tree(process: subprocess.Popen, stdout, stderr) -> tuple:
    """TERM -> bounded grace -> KILL for the whole tree; returns all raw
    output captured so far (communicate() keeps what it already read),
    falling back to the given partial output. The final group
    containment runs whatever draining the output raises: the timeout
    stays the outcome, only the diagnostic output can be shorter."""
    try:
        _signal_process_tree(process, force=False)
        try:
            stdout, stderr = process.communicate(timeout=_TERMINATION_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            _signal_process_tree(process, force=True)
            try:
                stdout, stderr = process.communicate(timeout=_TERMINATION_GRACE_SECONDS)
            except subprocess.TimeoutExpired as exc:
                # A descendant left the process group and still holds the
                # output pipes: stop reading, keep what was captured.
                stdout, stderr = exc.stdout, exc.stderr
                for stream in (process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()
    except Exception:
        # Draining failed (e.g. a pipe error): keep the partial output
        # captured before the budget expired; the timeout stands.
        pass
    finally:
        # A descendant that ignored SIGTERM may survive the leader's exit.
        _contain_process_tree(process)
    return stdout, stderr


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
    try:
        result = execute_controlled(request, root, capability_registry)
    except ControlledExecutionError as exc:
        return VerificationStepResult(
            step_id=step.step_id, area=step.area, status=EXECUTION_ERROR.value,
            verification_kind=step.verification_kind, runner_type=step.runner_type,
            passed=False, error_category=type(exc).__name__, diagnostics=str(exc)[:500],
        )
    if result is None:
        return VerificationStepResult(
            step_id=step.step_id, area=step.area, status=TOOL_UNAVAILABLE.value,
            verification_kind=step.verification_kind, runner_type=step.runner_type,
            passed=False, diagnostics=f"Execution failed: {tool_name}",
        )
    return _build_step_result(step, result, args)
