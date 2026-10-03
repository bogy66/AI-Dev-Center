"""Central, reusable, TEST-ONLY environment-scenario model
(CLAUDE-ADC-TEST-ENVIRONMENT-FIDELITY-UPGRADE-001).

This module defines the material environment DIMENSIONS ADC's behaviour
depends on (process outcomes, filesystem/cwd shapes, environment
variable composition, terminal-provider behaviour, argv shapes,
toolchain states, authority/capability states, lifecycle states, and
entry-interface identity), and an explicit, mechanically-enumerable
EQUIVALENCE CLASS for each concrete case within a dimension.

Nothing in this module executes anything by itself -- it is pure data
plus a small coverage-tracking registry. Individual test modules
(tests/test_env_*.py) consume these classes to build data-driven,
pairwise, 3-way, state-machine, property and fault-injection coverage,
and MARK which classes they actually exercise via `covers()`, so
"which classes exist / have tests / remain uncovered" is always a
mechanical query (see `coverage_report()` below and
tests/test_env_equivalence_classes.py, which asserts every MANDATORY
class is covered).

Each EquivalenceClass is intentionally lightweight data, not behavior:
it names a dimension, a representative concrete value/shape, the
product invariant a test exercising it is expected to confirm, and a
risk category -- never product logic. Tests that consume a class still
build their own fixtures/scenarios; this module only prevents that
enumeration from being buried, ad hoc and un-auditable inside
individual test bodies.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EquivalenceClass:
    class_id: str
    dimension: str
    representative: str
    expected_invariant: str
    risk_category: str  # "high" | "medium" | "low"


# ============================================================================
# PROCESS
# ============================================================================
PROCESS_CLASSES: tuple[EquivalenceClass, ...] = (
    EquivalenceClass("PROC_SPAWN_SUCCESS", "PROCESS", "Popen succeeds, real PID", "execution proceeds to completion tracking", "medium"),
    EquivalenceClass("PROC_SPAWN_FAILURE", "PROCESS", "Popen raises OSError", "fails closed with a structured, non-crash cause", "high"),
    EquivalenceClass("PROC_CHILD_SUCCESS", "PROCESS", "child exits 0", "result reports success, real returncode 0", "medium"),
    EquivalenceClass("PROC_CHILD_NONZERO", "PROCESS", "child exits nonzero", "result reports failure, real returncode propagated, never silently success", "high"),
    EquivalenceClass("PROC_TIMEOUT", "PROCESS", "child runs past deadline", "killed, reported as cancelled/timeout, never success", "high"),
    EquivalenceClass("PROC_EARLY_PROVIDER_EXIT", "PROCESS", "launcher/provider process exits before child reports", "treated as cancelled after grace period, never success", "high"),
    EquivalenceClass("PROC_MISSING_STATUS", "PROCESS", "no status file ever appears", "cancelled, never a fabricated success", "high"),
    EquivalenceClass("PROC_MALFORMED_STATUS", "PROCESS", "status file contains malformed or unauthenticated STATUS-V3 evidence", "cancelled with a structured cause, never a crash leaking to the caller", "high"),
    EquivalenceClass("PROC_SIGNAL_TERMINATION", "PROCESS", "child terminated by signal (canonical shell status 128+signal)", "treated as a real, non-zero, non-success outcome", "medium"),
)

# ============================================================================
# FILESYSTEM / CWD
# ============================================================================
FILESYSTEM_CLASSES: tuple[EquivalenceClass, ...] = (
    EquivalenceClass("FS_VALID_ROOT", "FILESYSTEM", "cwd == resolved project_root", "execution confined exactly to project_root", "medium"),
    EquivalenceClass("FS_NESTED_CWD", "FILESYSTEM", "cwd is a subdirectory of project_root", "still confined within project_root's own tree", "medium"),
    EquivalenceClass("FS_OUTSIDE_ROOT_CWD", "FILESYSTEM", "cwd escapes project_root entirely", "rejected or never constructed as an authorized request", "high"),
    EquivalenceClass("FS_MISSING_CWD", "FILESYSTEM", "cwd path does not exist", "fails closed, never silently falls back to another directory", "high"),
    EquivalenceClass("FS_CWD_DELETED_BEFORE_EXEC", "FILESYSTEM", "cwd existed at authorization time, removed before execution", "execution fails closed, no hidden fallback cwd", "high"),
    EquivalenceClass("FS_SYMLINK", "FILESYSTEM", "cwd is a symlink to a real directory inside project_root", "resolves and confines correctly through the symlink", "medium"),
    EquivalenceClass("FS_SYMLINK_ESCAPE", "FILESYSTEM", "symlink target resolves outside project_root", "confinement rejects the resolved (not literal) path", "high"),
    EquivalenceClass("FS_PERMISSION_DENIED", "FILESYSTEM", "directory exists but is not readable/enterable (mode 000)", "fails closed with a structured cause, never a raw crash", "medium"),
    EquivalenceClass("FS_SPACES", "FILESYSTEM", "path contains embedded spaces", "path threaded through argv/cwd unmangled", "medium"),
    EquivalenceClass("FS_UNICODE", "FILESYSTEM", "path contains non-ASCII Unicode characters", "path threaded through argv/cwd unmangled", "medium"),
    EquivalenceClass("FS_CHANGED_AFTER_APPROVAL", "FILESYSTEM", "step content/target mutated after Human Approval, same generation", "fails closed, stale approval never authorizes new content", "high"),
)

# ============================================================================
# ENVIRONMENT
# ============================================================================
ENVIRONMENT_CLASSES: tuple[EquivalenceClass, ...] = (
    EquivalenceClass("ENV_MINIMAL_HEADLESS", "ENVIRONMENT", "no desktop/session variables present at all", "terminal launcher/provider still resolves PATH-only identity correctly", "medium"),
    EquivalenceClass("ENV_DESKTOP_X11", "ENVIRONMENT", "DISPLAY/XAUTHORITY present", "launcher environment carries desktop connectivity vars to the provider process", "medium"),
    EquivalenceClass("ENV_WAYLAND", "ENVIRONMENT", "WAYLAND_DISPLAY present", "launcher environment carries desktop connectivity vars to the provider process", "medium"),
    EquivalenceClass("ENV_DBUS_SESSION", "ENVIRONMENT", "DBUS_SESSION_BUS_ADDRESS/XDG_RUNTIME_DIR present", "launcher environment carries session-bus vars to the provider process", "medium"),
    EquivalenceClass("ENV_CONTROLLED_VARS", "ENVIRONMENT", "PATH/HOME/PYTHON*/VIRTUAL_ENV/CONDA present", "final child environment includes exactly these, unmodified", "high"),
    EquivalenceClass("ENV_AMBIENT_FORBIDDEN", "ENVIRONMENT", "a non-allowlisted ambient var set on the ADC process (e.g. an unrelated app config value)", "final child environment never contains it", "high"),
    EquivalenceClass("ENV_SECRET_LIKE", "ENVIRONMENT", "a secret-shaped ambient var (token/key/password-named)", "final child environment never contains it, under any provider class", "high"),
    EquivalenceClass("ENV_EMPTY_VALUE", "ENVIRONMENT", "a controlled var present with an empty string value", "propagated as an empty string, never dropped or defaulted", "low"),
    EquivalenceClass("ENV_UNICODE_VALUE", "ENVIRONMENT", "a controlled var value contains Unicode", "propagated byte-for-byte to the final child", "low"),
    EquivalenceClass("ENV_SPACES_VALUE", "ENVIRONMENT", "a controlled var value contains embedded spaces", "propagated as one value, never split", "low"),
    EquivalenceClass("ENV_SHELL_METACHAR_VALUE", "ENVIRONMENT", "a controlled var value contains shell metacharacters ($();|&<>`)", "propagated literally, never interpreted", "high"),
    EquivalenceClass("ENV_LARGE_VALUE", "ENVIRONMENT", "a controlled var value is very long (>4KB)", "propagated intact, not truncated or corrupted", "low"),
    EquivalenceClass("ENV_CONTROLLED_OVERRIDES_AMBIENT", "ENVIRONMENT", "the controlled allowlisted PATH differs from the ambient process PATH", "the controlled value wins in the final child, never the ambient one", "high"),
    # Explicitly separate: launcher environment vs. final wrapped child environment.
    EquivalenceClass("ENV_LAUNCHER_ONLY_DESKTOP_VARS", "ENVIRONMENT", "launcher (provider/terminal-emulator) environment carries desktop vars the final child does not need", "final child environment excludes them unless independently allowlisted", "high"),
    EquivalenceClass("ENV_FINAL_CHILD_ALLOWLIST_ONLY", "ENVIRONMENT", "final wrapped child process's own os.environ", "subset of exactly the controlled allowlist, regardless of what the launcher process itself received", "high"),
)

# ============================================================================
# TERMINAL
# ============================================================================
TERMINAL_CLASSES: tuple[EquivalenceClass, ...] = (
    EquivalenceClass("TERM_PROVIDER_AVAILABLE", "TERMINAL", "a candidate terminal binary is resolvable via PATH", "provider.is_available() True, launch attempted", "medium"),
    EquivalenceClass("TERM_NO_PROVIDER", "TERMINAL", "no candidate terminal binary is resolvable", "fails closed with INTERACTIVE_TERMINAL_UNAVAILABLE, zero Popen call", "high"),
    EquivalenceClass("TERM_STARTUP_FAILURE", "TERMINAL", "Popen itself raises OSError launching the terminal binary", "fails closed with INTERACTIVE_TERMINAL_LAUNCH_FAILED", "high"),
    EquivalenceClass("TERM_EARLY_EXIT", "TERMINAL", "terminal process exits before the wrapped command reports a status", "cancelled after grace period, never success", "high"),
    EquivalenceClass("TERM_DIRECT_PROCESS_STYLE", "TERMINAL", "terminal directly execs its argv as its own child (xterm/-e family)", "cwd/env passed to Popen are exactly what the final child receives", "high"),
    EquivalenceClass("TERM_CLIENT_SERVER_STYLE", "TERMINAL", "terminal client hands off to an already-running server process (gnome-terminal family)", "the final child's cwd/env may diverge from what was passed to the client Popen call -- must be detectable, not silently assumed correct", "high"),
    EquivalenceClass("TERM_EXPLICIT_CWD_HANDLING", "TERMINAL", "provider honors an explicit --working-directory-style argument", "final child cwd matches the authorized cwd", "high"),
    EquivalenceClass("TERM_INHERITED_CWD_HANDLING", "TERMINAL", "provider has no explicit cwd flag and relies on inherited Popen(cwd=...)", "final child cwd matches ONLY if the provider's own process model actually inherits it -- proven per provider class, never assumed", "high"),
    EquivalenceClass("TERM_USER_CANCEL_EQUIVALENT", "TERMINAL", "terminal window closed/cancelled before completion (no status written, launcher already exited)", "reported as cancelled, never success, never silently retried", "high"),
)

# ============================================================================
# ARGV
# ============================================================================
ARGV_CLASSES: tuple[EquivalenceClass, ...] = (
    EquivalenceClass("ARGV_ORDINARY", "ARGV", "plain alphanumeric arguments", "final child argv == authorized argv, unmodified", "low"),
    EquivalenceClass("ARGV_MULTIPLE", "ARGV", "several distinct arguments", "each preserved as a distinct element, order preserved", "medium"),
    EquivalenceClass("ARGV_SPACES", "ARGV", "an argument containing embedded spaces", "preserved as one element, never split by a shell", "high"),
    EquivalenceClass("ARGV_QUOTES_APOSTROPHES", "ARGV", "an argument containing quote/apostrophe characters", "preserved literally, never used to break out of quoting", "high"),
    EquivalenceClass("ARGV_SHELL_METACHARACTERS", "ARGV", "an argument containing ;|&$()<>` characters", "preserved literally, never shell-interpreted", "high"),
    EquivalenceClass("ARGV_UNICODE", "ARGV", "an argument containing non-ASCII Unicode", "preserved byte-for-byte", "medium"),
    EquivalenceClass("ARGV_LEADING_DASH", "ARGV", "an argument starting with '-' that is not a flag", "preserved as a positional value, never misparsed as an option", "medium"),
    EquivalenceClass("ARGV_PATH_VALUE", "ARGV", "an argument that is itself a filesystem path", "preserved exactly, no normalization side effects", "low"),
    EquivalenceClass("ARGV_VERSION_QUALIFIED_PACKAGE", "ARGV", "package==1.2.3-style argument", "preserved as one argument, version operator intact", "medium"),
    EquivalenceClass("ARGV_LONG_ARGUMENT", "ARGV", "a very long single argument (>2KB)", "preserved intact, not truncated", "low"),
    EquivalenceClass("ARGV_MALFORMED_VALUE", "ARGV", "a structurally invalid package/step value (e.g. embedded null-like or empty string)", "rejected before any process is spawned, never passed through", "high"),
)

# ============================================================================
# TOOLCHAIN
# ============================================================================
TOOLCHAIN_CLASSES: tuple[EquivalenceClass, ...] = (
    EquivalenceClass("TOOLCHAIN_PRESENT", "TOOLCHAIN", "package already importable/detectable", "no install step materializes; already-satisfied path taken", "medium"),
    EquivalenceClass("TOOLCHAIN_ABSENT", "TOOLCHAIN", "package genuinely missing", "install step materializes when active+required", "high"),
    EquivalenceClass("TOOLCHAIN_WRONG_VERSION", "TOOLCHAIN", "installed version does not satisfy required_version", "treated as not-satisfied, not as present", "medium"),
    EquivalenceClass("TOOLCHAIN_VERIFIER_SUCCESS", "TOOLCHAIN", "post-install verifier reports True", "result.verification_passed True, status completed", "medium"),
    EquivalenceClass("TOOLCHAIN_VERIFIER_FAILURE", "TOOLCHAIN", "post-install verifier reports False despite a zero install exit code", "result reports verification failed, never silently treated as success", "high"),
    EquivalenceClass("TOOLCHAIN_PIP_UNAVAILABLE_EQUIVALENT", "TOOLCHAIN", "installer.is_available() finds no structured installer for the install_method", "fails closed with 'No structured installer is registered'", "high"),
    EquivalenceClass("TOOLCHAIN_WRONG_INTERPRETER_EQUIVALENT", "TOOLCHAIN", "target_executable resolves to a different capability-registered identity than approved", "rejected by capability/target-identity validation", "high"),
    EquivalenceClass("TOOLCHAIN_METADATA_EXECUTABLE_DISAGREEMENT", "TOOLCHAIN", "distribution metadata query and the actual install target disagree on presence", "the real, target-specific query wins, never a cached/assumed value", "medium"),
    EquivalenceClass("TOOLCHAIN_DEFERRED_REQUIREMENT", "TOOLCHAIN", "requirement inactive at Preflight time", "legitimately zero initial SetupSteps, explicit deferred_requirement_ids", "high"),
    EquivalenceClass("TOOLCHAIN_ACTIVE_MISSING_REQUIREMENT", "TOOLCHAIN", "requirement active+required+missing+controllable", "must appear as a materialized step or an explicit structured blocker, never silently lost", "high"),
    EquivalenceClass("TOOLCHAIN_UNSUPPORTED_BACKEND", "TOOLCHAIN", "no controlled executor exists for the classified setup_effect", "surfaced via unsupported_backend_effects, never forced through an incompatible executor", "medium"),
)

# ============================================================================
# AUTHORITY
# ============================================================================
AUTHORITY_CLASSES: tuple[EquivalenceClass, ...] = (
    EquivalenceClass("AUTH_PENDING_APPROVAL", "AUTHORITY", "plan/recovery still pending_approval", "zero authorization, zero execution", "high"),
    EquivalenceClass("AUTH_REJECTED_APPROVAL", "AUTHORITY", "plan/recovery explicitly rejected", "zero authorization, zero execution", "high"),
    EquivalenceClass("AUTH_APPROVED", "AUTHORITY", "plan/recovery approved with complete provenance", "authorization proceeds, execution permitted exactly once per generation", "medium"),
    EquivalenceClass("AUTH_STALE_APPROVAL", "AUTHORITY", "approval references an earlier generation than the content being executed", "rejected, stale approval never authorizes new content", "high"),
    EquivalenceClass("AUTH_CONTENT_MUTATION", "AUTHORITY", "execution-relevant content changed after approval, same generation", "fails closed, zero authorization for the mutated content", "high"),
    EquivalenceClass("AUTH_WRONG_TARGET", "AUTHORITY", "request names an executable identity different from the registered/approved one", "rejected, no substitution ever silently accepted", "high"),
    EquivalenceClass("AUTH_WRONG_PROJECT", "AUTHORITY", "request/verification-plan project_root differs from the authorized project scope", "fails closed, cross-project reuse rejected", "high"),
    EquivalenceClass("AUTH_MISSING_CAPABILITY", "AUTHORITY", "no capability registration exists at all for the requested tool_name", "rejected, no bootstrap fallback authorizes a mutation", "high"),
    EquivalenceClass("AUTH_WRONG_OPERATION_CAPABILITY", "AUTHORITY", "capability registered but does not list the requested operation_type", "rejected", "medium"),
    EquivalenceClass("AUTH_WRONG_EXECUTABLE_CAPABILITY", "AUTHORITY", "capability registered for a different executable_names set", "rejected, no PATH-coincidence substitution", "medium"),
    EquivalenceClass("AUTH_VALID_PROVENANCE_CAPABILITY", "AUTHORITY", "capability registered with complete ApprovalProvenance matching project/target/operation", "authorization succeeds", "medium"),
)

# ============================================================================
# LIFECYCLE
# ============================================================================
LIFECYCLE_CLASSES: tuple[EquivalenceClass, ...] = (
    EquivalenceClass("LIFE_FIRST_EXECUTION", "LIFECYCLE", "no prior SetupExecutionState record exists", "begin() claims a fresh record, execution proceeds", "medium"),
    EquivalenceClass("LIFE_SUCCESS", "LIFECYCLE", "execution completes with a real success result", "record transitions to known-success, reusable", "medium"),
    EquivalenceClass("LIFE_EXECUTION_FAILURE", "LIFECYCLE", "execution completes with a real failure result", "record reflects failure, not silently success", "high"),
    EquivalenceClass("LIFE_PRE_EXECUTION_AUTH_FAILURE", "LIFECYCLE", "authorization itself fails before any executor call", "no execution ever attempted, no state left claiming 'executing' forever", "high"),
    EquivalenceClass("LIFE_PROVIDER_FAILURE", "LIFECYCLE", "the terminal/provider boundary itself fails (unavailable/launch-failed/cancelled)", "reported as a real failure, persisted state reflects it, no hidden success", "high"),
    EquivalenceClass("LIFE_VERIFIER_FAILURE", "LIFECYCLE", "post-install verifier disagrees despite a successful install exit code", "reported as verification failed, not success", "high"),
    EquivalenceClass("LIFE_RETRY", "LIFECYCLE", "the same already-attempted request is retried", "known-success/known-failure state governs reuse, never a blind re-execution", "high"),
    EquivalenceClass("LIFE_DUPLICATE_REQUEST", "LIFECYCLE", "a second concurrent/near-simultaneous request for the same identity", "claim/check protection prevents a second real execution", "high"),
    EquivalenceClass("LIFE_ALREADY_EXECUTING", "LIFECYCLE", "a request arrives while status is 'executing'", "recovery_required / rejected, never a second concurrent real launch", "high"),
    EquivalenceClass("LIFE_ALREADY_COMPLETED", "LIFECYCLE", "a request arrives after status is already 'completed'", "reused/reported without a new mutation launch", "high"),
    EquivalenceClass("LIFE_RESTART_RELOAD", "LIFECYCLE", "a fresh process/store instance reloads persisted state from disk", "identical decisions to the pre-restart process for the same identity", "high"),
    EquivalenceClass("LIFE_BOUNDED_RECOVERY", "LIFECYCLE", "MissingToolchain recovery is invoked for an already-recovered or in-flight identity", "recovery remains exactly bounded, never repeats indefinitely", "high"),
)

# ============================================================================
# INTERFACE
# ============================================================================
INTERFACE_CLASSES: tuple[EquivalenceClass, ...] = (
    EquivalenceClass("IFACE_INTERNAL", "INTERFACE", "direct Python-level service/application call", "baseline productive behavior, no adapter-specific logic", "low"),
    EquivalenceClass("IFACE_WEB", "INTERFACE", "real FastAPI TestClient HTTP boundary", "identical guarantees to the internal path, no adapter-specific bypass", "high"),
    EquivalenceClass("IFACE_MCP", "INTERFACE", "real MCP JSON-RPC tool boundary", "identical guarantees to the internal path, no adapter-specific bypass", "high"),
    EquivalenceClass("IFACE_PERSISTED_RELOAD", "INTERFACE", "state reloaded from disk by a fresh store instance", "identical decisions as the original in-process instance", "high"),
    EquivalenceClass("IFACE_CROSS_PROCESS", "INTERFACE", "a genuinely separate OS process races on the same identity", "the same claim/check protection holds across process boundaries, not just within one Python process", "high"),
)

ALL_DIMENSIONS: dict[str, tuple[EquivalenceClass, ...]] = {
    "PROCESS": PROCESS_CLASSES,
    "FILESYSTEM": FILESYSTEM_CLASSES,
    "ENVIRONMENT": ENVIRONMENT_CLASSES,
    "TERMINAL": TERMINAL_CLASSES,
    "ARGV": ARGV_CLASSES,
    "TOOLCHAIN": TOOLCHAIN_CLASSES,
    "AUTHORITY": AUTHORITY_CLASSES,
    "LIFECYCLE": LIFECYCLE_CLASSES,
    "INTERFACE": INTERFACE_CLASSES,
}


def all_classes() -> tuple[EquivalenceClass, ...]:
    return tuple(c for classes in ALL_DIMENSIONS.values() for c in classes)


def class_by_id(class_id: str) -> EquivalenceClass:
    for c in all_classes():
        if c.class_id == class_id:
            return c
    raise KeyError(class_id)


# ============================================================================
# Coverage tracking (KIA-ADC-TEST-ASSURANCE-MODEL-FIX-001 section 1):
#
# `covers(...)` only DECLARES, at IMPORT time, that a test function is
# intended to exercise the given equivalence class id(s). A declaration
# is never by itself proof of coverage: a class only becomes PASS-VERIFIED
# once `record_test_outcome(...)` is told, by the real pytest 'call'-phase
# report (see tests/conftest.py::pytest_runtest_makereport), that a test
# carrying that declaration was actually collected, actually executed,
# and completed with a genuine PASS. A test that fails, is skipped, or
# is xfailed (either xfail-as-skip or an unexpected XPASS) never reaches
# that call, or is explicitly excluded before passed=True is passed in,
# so it can never promote a declared class to covered. This is a plain,
# process-local registry -- it only reflects the outcomes pytest
# actually observed in the current session (see the ordering note on
# tests/test_env_equivalence_classes.py for why that module must be the
# last one pytest executes in a given session).
# ============================================================================
_DECLARED_COVERAGE: dict[str, set[str]] = {}    # "module::qualname" -> {class_id, ...}
_COVERAGE_SOURCES: dict[str, list[str]] = {}    # class_id -> [declaring "module::qualname", ...]
_PASS_VERIFIED_CLASS_IDS: set[str] = set()
_PASS_VERIFIED_SOURCES: dict[str, list[str]] = {}  # class_id -> [PASS-backed "module::qualname", ...]


def covers(*class_ids: str):
    """Decorator: DECLARES that a test function is intended to exercise
    the given equivalence class id(s). Raises KeyError immediately (at
    import time, i.e. at test-collection time) for an unknown id, so a
    typo can never silently fail to register even a declaration. This
    alone does NOT count as coverage -- see record_test_outcome()."""
    for cid in class_ids:
        class_by_id(cid)  # validates existence

    def _decorate(fn):
        key = f"{fn.__module__}::{fn.__qualname__}"
        _DECLARED_COVERAGE.setdefault(key, set()).update(class_ids)
        for cid in class_ids:
            _COVERAGE_SOURCES.setdefault(cid, []).append(key)
        return fn
    return _decorate


def record_test_outcome(module: str, qualname: str, passed: bool) -> None:
    """Called once per executed test from the pytest 'call'-phase report
    hook (tests/conftest.py::pytest_runtest_makereport). Only a genuine
    PASS on the 'call' phase may promote a class declared via covers()
    on that test function to PASS-VERIFIED.

    A failing test calls this with passed=False and promotes nothing. A
    skipped test (pytest.mark.skip/skipif, or an xfail that fails as
    expected) never reaches the 'call' phase at all, so this is simply
    never invoked for it. An XPASS (xfail test that unexpectedly
    succeeds) is excluded by the caller before passed=True is ever
    passed in, so it cannot promote coverage either. A test whose
    function was never declared via covers() is a no-op lookup."""
    key = f"{module}::{qualname}"
    class_ids = _DECLARED_COVERAGE.get(key)
    if not class_ids or not passed:
        return
    for cid in class_ids:
        _PASS_VERIFIED_CLASS_IDS.add(cid)
        _PASS_VERIFIED_SOURCES.setdefault(cid, []).append(key)


def coverage_report() -> dict[str, object]:
    all_ids = {c.class_id for c in all_classes()}
    covered = all_ids & _PASS_VERIFIED_CLASS_IDS
    uncovered = all_ids - _PASS_VERIFIED_CLASS_IDS
    declared_only = (all_ids & set(_COVERAGE_SOURCES)) - covered
    return {
        "total": len(all_ids),
        "covered": sorted(covered),
        "uncovered": sorted(uncovered),
        "declared_but_not_pass_verified": sorted(declared_only),
        "sources": dict(_PASS_VERIFIED_SOURCES),
    }
