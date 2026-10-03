"""Authoritative equivalence-class catalog entries
(KIA-ADC-TEST-ASSURANCE-MODEL-FIX-001 section 2).

The historical aggregate TOTAL=100 is not treated as authoritative here
(per this task's own instruction) -- the catalog is
tests/env_scenarios.py's existing, explicit, traceable 94-class catalog,
extended with the additional fields section 2 requires: GATE,
REQUIREMENT_IDS, PRODUCT_BOUNDARY_OR_BRANCH, COVERAGE_STRATEGY,
TEST_SELECTORS.

GATE, COVERAGE_STRATEGY, REQUIREMENT_IDS and TEST_SELECTORS are all
mechanically DERIVED (never hand-typed per class_id) from data this
task's own Section-1 PASS-VERIFIED coverage registry and the existing
Evidence/selector_map machinery already produce.

PRODUCT_BOUNDARY_OR_BRANCH -- the specific app/*.py file, function and
branch each class's expected_invariant targets -- is populated from
PRODUCT_BOUNDARY_OR_BRANCH_BY_CLASS below, a hand-authored, per-class
mapping produced by reading the actual product source (never templated
from a class_id or its own English description). Each of the 94 values
names a real file plus function/class and the specific conditional
branch or code path that class's test exercises: e.g. a fail-closed
`except OSError` branch, a specific `if`/`raise` inside
`validate_request()`, or a specific dict comprehension in
`DesktopTerminalProvider.run()`. A sample was cross-checked against the
actual `@covers(...)`-tagged test that exercises each class (see
`tests/env_scenarios.py`'s `coverage_report()` sources) to confirm the
named boundary is what the test really reaches, not a restatement of
the class's own description.
"""
from __future__ import annotations

from dataclasses import dataclass

from requirements.evidence.proof_obligations import read_requirement_ids_and_titles
from requirements.evidence.selector_map import resolve_selector
from tests.env_scenarios import EquivalenceClass, class_by_id, coverage_report

ALLOWED_COVERAGE_STRATEGIES = frozenset({
    "EXHAUSTIVE", "EQUIVALENCE_PARTITION", "BOUNDARY_VALUE", "PAIRWISE",
    "THREE_WAY", "STATE_MACHINE", "PROPERTY_INVARIANT", "FAULT_MATRIX",
    "REAL_SYSTEM_ONLY",
})

# Mechanically grounded in which test FILE actually exercises a given
# source ("module::qualname") -- never guessed per class_id. Any
# qualname not covered by an override below or a module default falls
# back to EQUIVALENCE_PARTITION, this catalog's original per-class
# individually-exercised design intent (tests/env_scenarios.py's own
# module docstring).
_STRATEGY_BY_SOURCE_MODULE = {
    "tests.test_env_pairwise_coverage": "PAIRWISE",
    "tests.test_env_threeway_coverage": "THREE_WAY",
    "tests.test_env_state_machine": "STATE_MACHINE",
    "tests.test_env_property_invariants": "PROPERTY_INVARIANT",
    "tests.test_env_fault_matrix": "FAULT_MATRIX",
}
# KIA-ADC-TEST-ASSURANCE-MODEL-FIX-001 section 4: these two specific
# functions were reclassified from a degenerate PAIRWISE/THREE_WAY claim
# down to an honest EQUIVALENCE_PARTITION (see
# tests/test_env_pairwise_coverage.py Domain B and
# tests/test_env_threeway_coverage.py Domain C) -- they must not inherit
# their containing module's default PAIRWISE/THREE_WAY strategy.
_QUALNAME_STRATEGY_OVERRIDES = {
    "tests.test_env_pairwise_coverage::test_pairwise_cwd_class_x_interface": "EQUIVALENCE_PARTITION",
    "tests.test_env_threeway_coverage::test_threeway_child_status_outcome_x_lifecycle_x_interface": "EQUIVALENCE_PARTITION",
}


# KIA-ADC-TEST-ASSURANCE-AB-INTEGRATE-CORRECT-002 section 8: per-class
# PRODUCT_BOUNDARY_OR_BRANCH, hand-authored from direct product-code
# reading (see module docstring). Every one of the 94 keys below is
# validated 1:1 against tests/env_scenarios.py at import time by
# build_catalog_entry() raising KeyError for any class_by_id() miss.
PRODUCT_BOUNDARY_OR_BRANCH_BY_CLASS: dict[str, str] = {
    # PROCESS -- app/interactive_terminal.py: DesktopTerminalProvider
    "PROC_SPAWN_SUCCESS": "app/interactive_terminal.py: DesktopTerminalProvider.run() -- subprocess.Popen(full_argv, ...) success branch, proceeds to _wait_for_result()",
    "PROC_SPAWN_FAILURE": "app/interactive_terminal.py: DesktopTerminalProvider.run() -- `except OSError` around Popen(), returns INTERACTIVE_TERMINAL_LAUNCH_FAILED",
    "PROC_CHILD_SUCCESS": "app/interactive_terminal.py: DesktopTerminalProvider._read_status() -- authenticates exactly one canonical STATUS-V3 record bound by HMAC to this execution identity and result, TerminalLaunchOutcome(completed=True)",
    "PROC_CHILD_NONZERO": "app/interactive_terminal.py: DesktopTerminalProvider._read_status() -- real nonzero returncode read from status file, propagated unmodified via InteractiveTerminalLauncher.run()'s CompletedProcess (never raised as an error)",
    "PROC_TIMEOUT": "app/interactive_terminal.py: DesktopTerminalProvider._wait_for_result() -- `now > deadline` branch, process.kill(), INTERACTIVE_TERMINAL_CANCELLED",
    "PROC_EARLY_PROVIDER_EXIT": "app/interactive_terminal.py: DesktopTerminalProvider._wait_for_result() -- launcher_exited_at grace-period branch (_LAUNCHER_EXIT_GRACE_SECONDS)",
    "PROC_MISSING_STATUS": "app/interactive_terminal.py: DesktopTerminalProvider._wait_for_result() -- deadline reached with status_path never created, same fail-closed INTERACTIVE_TERMINAL_CANCELLED path as PROC_TIMEOUT",
    "PROC_MALFORMED_STATUS": "app/interactive_terminal.py: DesktopTerminalProvider._read_status() -- unreadable, unauthenticated, malformed or ambiguous STATUS-V3 record, INTERACTIVE_TERMINAL_CANCELLED",
    "PROC_SIGNAL_TERMINATION": "app/interactive_terminal.py: DesktopTerminalProvider._read_status() -- a genuinely signal-terminated child yields authenticated canonical exit status 128+signal (SIGKILL: 137), propagated as a nonzero command result",

    # FILESYSTEM -- app/execution.py: validate_request() cwd containment
    "FS_VALID_ROOT": "app/execution.py: validate_request() -- `cwd.is_relative_to(root)` check, cwd == resolved project_root",
    "FS_NESTED_CWD": "app/execution.py: validate_request() -- `cwd.is_relative_to(root)` check, cwd a subdirectory of project_root",
    "FS_OUTSIDE_ROOT_CWD": "app/execution.py: validate_request() -- `not cwd.is_relative_to(root)` branch, _error(INVALID_PLAN, 'cwd escapes project root')",
    "FS_MISSING_CWD": "app/execution.py: execute_controlled() -- `except OSError: return None` fail-closed branch when subprocess.run(cwd=...) cannot resolve a nonexistent directory",
    "FS_CWD_DELETED_BEFORE_EXEC": "app/execution.py: execute_controlled() -- same `except OSError: return None` fail-closed branch, no fallback cwd is ever substituted",
    "FS_SYMLINK": "app/execution.py: validate_request() -- `Path(request.cwd).resolve()` follows the symlink before the is_relative_to containment check",
    "FS_SYMLINK_ESCAPE": "app/execution.py: validate_request() -- same resolve()-then-is_relative_to check rejects a symlink whose resolved target lies outside project_root",
    "FS_PERMISSION_DENIED": "app/execution.py: execute_controlled() -- `except OSError: return None` fail-closed branch (a mode-000 directory raises PermissionError, an OSError subclass)",
    "FS_SPACES": "app/execution.py: execute_controlled() / DesktopTerminalProvider.run() -- cwd is passed as a real Path/str, never shell-joined, so embedded spaces cannot be mangled",
    "FS_UNICODE": "app/execution.py: execute_controlled() / DesktopTerminalProvider.run() -- same Path/str plumbing, never re-encoded or transliterated",
    "FS_CHANGED_AFTER_APPROVAL": "app/approved_plan_content.py: ApprovedPlanContentStore.verify() -- same-generation content-mismatch fail-closed check",

    # ENVIRONMENT -- app/interactive_terminal.py launcher/final-child env + app/execution.py _controlled_env()
    "ENV_MINIMAL_HEADLESS": "app/interactive_terminal.py: DesktopTerminalProvider.run() -- launcher_env dict comprehension over _DESKTOP_ENVIRONMENT_KEYS is empty when none are set; is_available()/_select_binary() do not depend on them",
    "ENV_DESKTOP_X11": "app/interactive_terminal.py: DesktopTerminalProvider.run() -- launcher_env comprehension carries DISPLAY/XAUTHORITY when present in os.environ",
    "ENV_WAYLAND": "app/interactive_terminal.py: DesktopTerminalProvider.run() -- launcher_env comprehension carries WAYLAND_DISPLAY when present",
    "ENV_DBUS_SESSION": "app/interactive_terminal.py: DesktopTerminalProvider.run() -- launcher_env comprehension carries DBUS_SESSION_BUS_ADDRESS/XDG_RUNTIME_DIR when present",
    "ENV_CONTROLLED_VARS": "app/execution.py: _controlled_env() -- ENV_ALLOWLIST_PREFIXES filter over os.environ",
    "ENV_AMBIENT_FORBIDDEN": "app/execution.py: _controlled_env() -- dict comprehension structurally excludes any key not matching an ENV_ALLOWLIST_PREFIXES prefix",
    "ENV_SECRET_LIKE": "app/execution.py: _controlled_env() -- same allowlist-only construction; a secret-shaped var outside the allowlist is excluded regardless of name",
    "ENV_EMPTY_VALUE": "app/execution.py: _controlled_env() -- dict comprehension copies each value verbatim, including an empty string, no falsy-value drop",
    "ENV_UNICODE_VALUE": "app/interactive_terminal.py: DesktopTerminalProvider.run() / terminal_status_producer.main() -- controlled environment passes through JSON and subprocess.Popen(env=env) without shell interpretation",
    "ENV_SPACES_VALUE": "app/terminal_status_producer.py: main() -- environment values containing spaces are passed as dictionary values to subprocess.Popen(env=env)",
    "ENV_SHELL_METACHAR_VALUE": "app/terminal_status_producer.py: main() -- controlled environment is passed directly to Popen; values are never evaluated by a shell",
    "ENV_LARGE_VALUE": "app/execution.py: _controlled_env() / env dict plumbing -- no length truncation applied anywhere in the copy path",
    "ENV_CONTROLLED_OVERRIDES_AMBIENT": "app/interactive_terminal.py: DesktopTerminalProvider.run() -- `launcher_env.update(env)` applies the controlled env AFTER the ambient desktop-only base, so it wins on key collision",
    "ENV_LAUNCHER_ONLY_DESKTOP_VARS": "app/interactive_terminal.py: DesktopTerminalProvider.run() -- launcher_env (restricted to _DESKTOP_ENVIRONMENT_KEYS) is a distinct dict from the producer's final-child environment; desktop vars never reach the wrapped command",
    "ENV_FINAL_CHILD_ALLOWLIST_ONLY": "app/interactive_terminal.py: DesktopTerminalProvider.run() -- trusted producer starts the final child with exactly the controlled environment from the private launch file",

    # TERMINAL -- app/interactive_terminal.py
    "TERM_PROVIDER_AVAILABLE": "app/interactive_terminal.py: DesktopTerminalProvider.is_available()/_select_binary() -- shutil.which() resolves a candidate binary",
    "TERM_NO_PROVIDER": "app/interactive_terminal.py: InteractiveTerminalLauncher.run() -- `if not self._provider.is_available()` branch raises before any Popen call",
    "TERM_STARTUP_FAILURE": "app/interactive_terminal.py: DesktopTerminalProvider.run() -- `except OSError` around subprocess.Popen(full_argv, ...)",
    "TERM_EARLY_EXIT": "app/interactive_terminal.py: DesktopTerminalProvider._wait_for_result() -- launcher_exited_at grace-period branch (the terminal's own client process, distinct axis from PROC_EARLY_PROVIDER_EXIT's wrapped command)",
    "TERM_DIRECT_PROCESS_STYLE": "app/interactive_terminal.py: DesktopTerminalProvider.run() -- full_argv/cwd/env passed straight to subprocess.Popen; for a directly-execing terminal (xterm/-e family) these ARE the eventual child's cwd/env",
    "TERM_CLIENT_SERVER_STYLE": "app/interactive_terminal.py: DesktopTerminalProvider._wait_for_result() -- process.poll() (the launching client) can exit while the real work continues under an existing server, which is exactly why the grace-period/status-file design exists rather than trusting client exit status",
    "TERM_EXPLICIT_CWD_HANDLING": "app/interactive_terminal.py: DesktopTerminalProvider.run() -- Popen(cwd=cwd) is passed explicitly regardless of candidate, authoritative whenever the provider's own process model honors Popen's cwd",
    "TERM_INHERITED_CWD_HANDLING": "app/interactive_terminal.py: DesktopTerminalProvider.run() -- same Popen(cwd=cwd) call; for a client/server provider, correctness depends on whether the eventual server-spawned child actually inherits it, proven per-provider by tests/terminal_final_child_probe.py's real subprocess probes rather than assumed",
    "TERM_USER_CANCEL_EQUIVALENT": "app/interactive_terminal.py: DesktopTerminalProvider._wait_for_result() -- status file never appears plus launcher-exit path, same INTERACTIVE_TERMINAL_CANCELLED outcome as a closed terminal window",

    # ARGV -- app/python_package_executor.py + app/execution.py argv plumbing
    "ARGV_ORDINARY": "app/python_package_executor.py: PythonPackageExecutor.execute() -- command list `[target_python, \"-m\", \"pip\", \"install\", package_arg]` passed unmodified through execute_controlled()/subprocess.run(list(...))",
    "ARGV_MULTIPLE": "app/python_package_executor.py: PythonPackageExecutor.execute() -- same command list construction, each element a distinct list entry, never joined",
    "ARGV_SPACES": "app/execution.py: execute_controlled() -- subprocess.run(list(request.args), ...), a real argv list, shell=True never used on this path",
    "ARGV_QUOTES_APOSTROPHES": "app/execution.py: execute_controlled() -- same list-based subprocess call never re-parses argument text",
    "ARGV_SHELL_METACHARACTERS": "app/execution.py: validate_request() -- `_DENIED_ARGS` substring check, combined with the same list-based (never shell=True) execution making metacharacters inert even where not denied",
    "ARGV_UNICODE": "app/execution.py: execute_controlled() / DesktopTerminalProvider.run() -- str arguments pass through Python's own list-based Popen/subprocess.run argv marshalling, never re-encoded",
    "ARGV_LEADING_DASH": "app/python_package_executor.py: PythonPackageExecutor._build_package_arg() -- package_arg is constructed as one opaque list element for pip, never split or reparsed as flags",
    "ARGV_PATH_VALUE": "app/execution.py: execute_controlled() -- subprocess.run(list(request.args), ...) applies no normalization to argv elements distinct from cwd handling",
    "ARGV_VERSION_QUALIFIED_PACKAGE": "app/python_package_executor.py: PythonPackageExecutor._build_package_arg() -- version-operator-prefix logic (==/>=/<=/!=/>/<), combined into one argument",
    "ARGV_LONG_ARGUMENT": "app/execution.py: execute_controlled() -- list-based subprocess call imposes no length limit anywhere in the argv path",
    "ARGV_MALFORMED_VALUE": "app/python_package_executor.py: PythonPackageExecutor._validate_step() -- `_PACKAGE_NAME.fullmatch()` rejects a structurally invalid package string via PackageMissingError, before _run()/execute_controlled() is ever reached",

    # TOOLCHAIN -- app/toolchain_materializer.py + app/python_package_executor.py
    "TOOLCHAIN_PRESENT": "app/toolchain_materializer.py: ToolchainMaterializer._materialize_item()/assess_item() -- preflight-satisfied branch, no install SetupStep materializes",
    "TOOLCHAIN_ABSENT": "app/toolchain_materializer.py: ToolchainMaterializer._materialize_item() -- active+required+missing branch materializes an install SetupStep",
    "TOOLCHAIN_WRONG_VERSION": "app/toolchain_materializer.py: ToolchainMaterializer preflight-comparison branch (assess_item()/_classify_item_baseline()) -- a required_version mismatch is treated as not-satisfied, not as present",
    "TOOLCHAIN_VERIFIER_SUCCESS": "app/python_package_executor.py: PythonPackageExecutor.execute()/_run_verification() -- verifier() True branch, verification_passed=True",
    "TOOLCHAIN_VERIFIER_FAILURE": "app/python_package_executor.py: PythonPackageExecutor.execute() -- verifier() False despite result.returncode==0, verification_passed=False, never silently promoted to success",
    "TOOLCHAIN_PIP_UNAVAILABLE_EQUIVALENT": "app/python_package_executor.py: PythonPackageExecutor._validate_install_method()/_is_supported_install_method() -- UnsupportedInstallMethodError when no structured installer matches install_method",
    "TOOLCHAIN_WRONG_INTERPRETER_EQUIVALENT": "app/execution.py: validate_request() -- `actual not in approved` branch rejects a target_executable that does not match the capability-registered identity",
    "TOOLCHAIN_METADATA_EXECUTABLE_DISAGREEMENT": "app/toolchain_materializer.py: ToolchainMaterializer._preflight_satisfaction_is_target_bound()/assess_item() -- target-bound resolution overrides a stale/generic metadata-only satisfaction signal",
    "TOOLCHAIN_DEFERRED_REQUIREMENT": "app/toolchain_materializer.py: ToolchainMaterializer.materialize()/_classify_item_baseline() -- inactive-requirement branch, explicit deferred_requirement_ids, legitimately zero SetupSteps",
    "TOOLCHAIN_ACTIVE_MISSING_REQUIREMENT": "app/toolchain_materializer.py: ToolchainMaterializer.materialize() -- active+required+missing+controllable branch, a materialized step or an explicit structured blocker",
    "TOOLCHAIN_UNSUPPORTED_BACKEND": "app/toolchain_materializer.py: ToolchainMaterializer._materialize_item() -- `controlled = is_controlled_setup_effect(effect)` False branch, surfaced via unsupported_backend_effects",

    # AUTHORITY -- app/execution.py CapabilityRegistry/validate_request + app/requirement_model.py SetupPlan.status + app/approved_plan_content.py
    "AUTH_PENDING_APPROVAL": "app/requirement_model.py: SetupPlan.status (default 'pending_approval') -- app/dev_workflow.py's execution path only proceeds from an 'approved' plan",
    "AUTH_REJECTED_APPROVAL": "app/requirement_model.py: SetupPlan.status -- an explicit 'rejected' status short-circuits before any capability/execution call",
    "AUTH_APPROVED": "app/requirement_model.py: SetupPlan.status -- 'approved' is the sole status that reaches capability registration and execute_controlled()",
    "AUTH_STALE_APPROVAL": "app/approved_plan_content.py: ApprovedPlanContentStore.verify() -- a generation_id earlier than the content being executed is rejected",
    "AUTH_CONTENT_MUTATION": "app/approved_plan_content.py: ApprovedPlanContentStore.verify()/record_approved() -- same-generation content-mismatch fail-closed check",
    "AUTH_WRONG_TARGET": "app/execution.py: validate_request() -- `actual not in approved` branch, no substitution ever silently accepted",
    "AUTH_WRONG_PROJECT": "app/execution.py: validate_request() -- `registration.project_scope is not None and root != Path(registration.project_scope)` branch",
    "AUTH_MISSING_CAPABILITY": "app/execution.py: validate_request() -- `registration is None` branch, CapabilityRegistry.get() finds no registration",
    "AUTH_WRONG_OPERATION_CAPABILITY": "app/execution.py: validate_request() -- `request.operation_type not in registration.allowed_operations` branch",
    "AUTH_WRONG_EXECUTABLE_CAPABILITY": "app/execution.py: validate_request() -- same `actual not in approved` executable-identity check, no PATH-coincidence substitution",
    "AUTH_VALID_PROVENANCE_CAPABILITY": "app/execution.py: validate_request() -- mutating-operation branch requiring `provenance.is_complete()`, success path proceeds to execution",

    # LIFECYCLE -- app/setup_execution_state.py SetupExecutionStateStore
    "LIFE_FIRST_EXECUTION": "app/setup_execution_state.py: SetupExecutionStateStore.begin() -- no prior record for this (project, generation, step), a fresh IN_PROGRESS record is claimed",
    "LIFE_SUCCESS": "app/setup_execution_state.py: SetupExecutionStateStore.finish() -- SUCCEEDED status transition",
    "LIFE_EXECUTION_FAILURE": "app/setup_execution_state.py: SetupExecutionStateStore.finish() -- FAILED status transition, never silently success",
    "LIFE_PRE_EXECUTION_AUTH_FAILURE": "app/execution.py: validate_request() raising before app/setup_execution_state.py's claim_or_report()/begin() is ever called -- no IN_PROGRESS record is ever persisted for a rejected request",
    "LIFE_PROVIDER_FAILURE": "app/interactive_terminal.py: InteractiveTerminalLauncher.run() raising InteractiveTerminalError, propagated into SetupExecutionStateStore.finish()'s FAILED persistence",
    "LIFE_VERIFIER_FAILURE": "app/python_package_executor.py: PythonPackageExecutor.execute() -- verification_passed=False result persisted via SetupExecutionStateStore.finish() as a real failure, not success",
    "LIFE_RETRY": "app/setup_execution_state.py: SetupExecutionStateStore.claim_or_report() -- an existing SUCCEEDED/FAILED record short-circuits without a new begin()/execution attempt",
    "LIFE_DUPLICATE_REQUEST": "app/setup_execution_state.py: SetupExecutionStateStore.claim_or_report() -- fcntl.flock-guarded check-and-claim sequence, only one caller ever transitions a NOT_STARTED identity to IN_PROGRESS",
    "LIFE_ALREADY_EXECUTING": "app/setup_execution_state.py: SetupExecutionStateStore.claim_or_report() -- an existing IN_PROGRESS/RECOVERY_REQUIRED record raises SetupExecutionStateError rather than reclaiming",
    "LIFE_ALREADY_COMPLETED": "app/setup_execution_state.py: SetupExecutionStateStore.claim_or_report() -- an existing SUCCEEDED record is returned as-is, no new claim or mutation launch",
    "LIFE_RESTART_RELOAD": "app/setup_execution_state.py: SetupExecutionStateStore._load_raw()/get() -- a fresh store instance re-reads the same persisted JSON file and reaches the same decision",
    "LIFE_BOUNDED_RECOVERY": "app/project_setup_application.py: execute_missing_toolchain_setup() combined with app/setup_execution_state.py's claim_or_report() -- recovery for an already-recovered/in-flight identity routes through the SAME bounding as any other identity, never a separate unbounded path",

    # INTERFACE -- shared app/execution.py execute_controlled() boundary + adapter entry points
    "IFACE_INTERNAL": "app/execution.py: execute_controlled() -- the baseline, directly-called path every adapter routes through",
    "IFACE_WEB": "app/web_api.py: POST /api/workflow/{session_id}/execute route handler -- routes to the same execute_approved_setup_from_store()/execute_controlled() boundary as IFACE_INTERNAL, no adapter-specific bypass",
    "IFACE_MCP": "app/mcp_server.py: execute_setup_plan() MCP tool -- routes to the same execute_approved_setup_from_store()/execute_controlled() boundary as IFACE_INTERNAL",
    "IFACE_PERSISTED_RELOAD": "app/setup_execution_state.py: SetupExecutionStateStore -- same mechanism as LIFE_RESTART_RELOAD, exercised via a fresh store instance across an interface boundary",
    "IFACE_CROSS_PROCESS": "app/setup_execution_state.py: SetupExecutionStateStore.claim_or_report() -- fcntl.flock file lock proven to hold across genuinely separate OS processes, not just within one Python process",
}


@dataclass(frozen=True)
class CatalogEntry:
    class_id: str
    dimension: str
    gate: str
    requirement_ids: tuple[str, ...]
    product_boundary_or_branch: str  # always populated, see PRODUCT_BOUNDARY_OR_BRANCH_BY_CLASS
    coverage_strategy: str | None            # None == no PASS-VERIFIED source yet
    test_selectors: tuple[str, ...]


def _qualname_to_pytest_selector(qualname: str) -> str:
    """'tests.test_env_state_machine::TestX.test_y' ->
    'tests/test_env_state_machine.py::TestX::test_y' -- the pytest
    node-id shape resolve_selector() and SELECTOR_MAP both use."""
    module, _, dotted = qualname.partition("::")
    file_path = module.replace(".", "/") + ".py"
    return file_path + "::" + dotted.replace(".", "::")


def _strategy_for_source(qualname: str) -> str:
    if qualname in _QUALNAME_STRATEGY_OVERRIDES:
        return _QUALNAME_STRATEGY_OVERRIDES[qualname]
    module = qualname.split("::", 1)[0]
    return _STRATEGY_BY_SOURCE_MODULE.get(module, "EQUIVALENCE_PARTITION")


def build_catalog_entry(class_id: str, live_report: dict | None = None) -> CatalogEntry:
    """live_report should be tests.env_scenarios.coverage_report(),
    passed in by a session-scoped caller that ran after the covering
    tests actually executed (see the ordering note on
    tests/test_env_equivalence_classes.py). Left None, TEST_SELECTORS
    and COVERAGE_STRATEGY reflect zero PASS-VERIFIED sources (never
    fabricated)."""
    equivalence_class: EquivalenceClass = class_by_id(class_id)  # raises for an unknown id
    report = live_report if live_report is not None else coverage_report()
    sources = tuple(report.get("sources", {}).get(class_id, ()))

    test_selectors = tuple(_qualname_to_pytest_selector(q) for q in sources)
    strategy = _strategy_for_source(sources[0]) if sources else None

    requirement_ids: tuple[str, ...] = ()
    if test_selectors:
        req_titles = read_requirement_ids_and_titles()
        seen_test_ids = []
        for selector in test_selectors:
            test_id = resolve_selector(selector)
            if test_id and test_id not in seen_test_ids:
                seen_test_ids.append(test_id)
        req_id_set: list[str] = []
        for test_id in seen_test_ids:
            for rid in req_titles.get(test_id, ((), ""))[0]:
                if rid and rid not in req_id_set:
                    req_id_set.append(rid)
        requirement_ids = tuple(req_id_set)

    return CatalogEntry(
        class_id=class_id,
        dimension=equivalence_class.dimension,
        gate="GATE1",  # every tests/env_scenarios.py class is exercised by a focused/deterministic test
        requirement_ids=requirement_ids,
        product_boundary_or_branch=PRODUCT_BOUNDARY_OR_BRANCH_BY_CLASS[class_id],
        coverage_strategy=strategy,
        test_selectors=test_selectors,
    )


def validate_catalog_entry(entry: CatalogEntry) -> tuple[bool, tuple[str, ...]]:
    """A catalog entry without a valid Requirement/contract/
    architectural-boundary justification must fail assurance
    validation (section 2). Returns (is_valid, reasons)."""
    reasons = []
    if entry.gate not in {"GATE1", "GATE2", "GATE3"}:
        reasons.append(f"invalid gate {entry.gate!r}")
    if entry.coverage_strategy is not None and entry.coverage_strategy not in ALLOWED_COVERAGE_STRATEGIES:
        reasons.append(f"invalid coverage_strategy {entry.coverage_strategy!r}")
    if not entry.test_selectors:
        reasons.append("no PASS-VERIFIED test_selectors")
    if not entry.requirement_ids:
        reasons.append("no traceable requirement_ids")
    if entry.product_boundary_or_branch is None:
        reasons.append("product_boundary_or_branch not yet assigned")
    return (len(reasons) == 0, tuple(reasons))
