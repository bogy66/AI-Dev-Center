"""Gate-3 defect -> lower-gate containment register
(CLAUDE-ADC-RSE033-INSTALLER-RECOVERY-CLOSURE-FIX-002 section 19).

Not an issue tracker. Each entry records, for one defect class a Gate-3
Real-System run exposed, which LOWER gate now owns it and which permanent
regression nodes prove that ownership. Whether an entry is CLOSED is never
stated here -- it is derived from a current proof run only:

  CLOSED -- every registered selector resolves to >=1 collected node, every
            such node is inside the owning obligation's current mandatory
            scope (Gate-1 SELECTOR_MAP / Gate-2 GATE2_SELECTOR_MAP), every
            node PASSED in the current run, and the owning obligation
            itself is PROVEN by that same current proof;
  OPEN   -- anything else (stale / zero-node selector, node no longer
            mandatory, failed/skipped/missing node, owning obligation not
            proven), with the reasons.

The authoritative Gate-1 meta-gate (tests/test_gate1_proof_meta_gate.py)
evaluates the GATE1 entries in-session; `python -m
requirements.evidence.gate2_proof verify` evaluates the GATE2 entries from
its own run and fails unless they are all CLOSED. The Real-System TEST_033
selector is never a lower-gate regression.
"""
from __future__ import annotations

from dataclasses import dataclass

from .current_run_completion import _selector_matches
from .gate2_selector_map import GATE2_SELECTOR_MAP
from .selector_map import SELECTOR_MAP, is_gate3_only_nodeid

CLOSED, OPEN = "CLOSED", "OPEN"
GATE1, GATE2 = "GATE1", "GATE2"
PASSED, PROVEN = "PASSED", "PROVEN"

# Defect classes of the RSE033 installer/recovery cycle.
INSTALLER_REGISTRY_RESOLUTION_DEFECT = "INSTALLER_REGISTRY_RESOLUTION_DEFECT"
MISSING_RECOVERY_COMPOSITION = "MISSING_RECOVERY_COMPOSITION"
FAILED_REVERIFICATION_CONTAINMENT = "FAILED_REVERIFICATION_CONTAINMENT"

RSE033_INSTALLER_RECOVERY_DEFECT_ID = "DEF-RSE033-INSTALLER-RECOVERY"

# Defect classes of the RSE033 verification-timeout cycle
# (CLAUDE-ADC-RSE033-ESPHOME-COMPILE-TIMEOUT-REQ-CODE-FIX-001).
VERIFICATION_BUDGET_POLICY_ESCAPE = "VERIFICATION_BUDGET_POLICY_ESCAPE"
PROCESS_TIMEOUT_DESCENDANT_CLEANUP = "PROCESS_TIMEOUT_DESCENDANT_CLEANUP"
TIMEOUT_REWORK_CLASSIFICATION = "TIMEOUT_REWORK_CLASSIFICATION"
# CLAUDE-ADC-RSE033-EXECUTION-ERROR-REQ-CODE-FIX-001: a started process's
# execution-boundary failure was reported as TOOL_UNAVAILABLE.
EXECUTION_ERROR_CLASSIFICATION = "EXECUTION_ERROR_CLASSIFICATION"

# CLAUDE-ADC-RSE033-RESIDUAL-DISTRIBUTION-PTY-CLOSURE-FIX-003: a query that
# produced no presence verdict was read as absence (a false missing
# requirement and setup step), and a terminal launcher's startup/lifecycle
# status stood in for the final command's own status and output.
NO_VERDICT_AS_ABSENCE_CLASSIFICATION = "NO_VERDICT_AS_ABSENCE_CLASSIFICATION"
FINAL_CHILD_STATUS_FIDELITY = "FINAL_CHILD_STATUS_FIDELITY"
RSE033_COMPILE_TIMEOUT_DEFECT_ID = "DEF-RSE033-ESPHOME-COMPILE-TIMEOUT"


class MalformedDefectRegister(ValueError):
    """The register cannot describe a mechanically checkable containment."""


@dataclass(frozen=True)
class LowerGateRegression:
    defect_id: str
    defect_class: str
    owning_gate: str            # GATE1 | GATE2
    owning_obligation: str      # TEST_* (Gate 1) | GATE2_* (Gate 2)
    selectors: tuple[str, ...]  # permanent regression nodes


@dataclass(frozen=True)
class RegisterProof:
    entry: LowerGateRegression
    state: str
    node_outcomes: tuple[tuple[str, str], ...]
    reasons: tuple[str, ...]


_IDENTITY = "tests/test_installer_recovery_identity.py"
_S3_5 = "tests/test_missing_toolchain_setup.py"
_PRODUCTIVE = "tests/test_installer_recovery_productive_path.py"
_TIMEOUT_POLICY = "tests/test_verification_timeout_policy.py"
_TIMEOUT_PRODUCTIVE = "tests/test_productive_boundary_contracts.py::TestS5_VerificationTimeoutProductiveComposition"
_EXECUTION_ERROR = "tests/test_verification_execution_error.py"
_NO_VERDICT = "tests/test_distribution_no_verdict_preflight.py"
_FINAL_CHILD = "tests/test_pty_final_child_fidelity.py"
_PRESENTER = "tests/test_execution_presenter.py"
_EXECUTION_ERROR_PRODUCTIVE = (
    "tests/test_productive_boundary_contracts.py::TestS5_VerificationExecutionErrorProductiveComposition"
    "::test_real_execution_error_is_fail_closed_terminal_without_rework_or_recovery"
)

DEFECT_REGISTER: tuple[LowerGateRegression, ...] = (
    # Literal install_method registry lookup ("No structured installer is
    # registered" for an accepted representation).
    LowerGateRegression(
        RSE033_INSTALLER_RECOVERY_DEFECT_ID, INSTALLER_REGISTRY_RESOLUTION_DEFECT, GATE1, "TEST_014", (
            f"{_IDENTITY}::test_supported_forms_resolve_through_materializer_to_one_registered_installer",
            f"{_IDENTITY}::test_unsupported_forms_never_become_install_steps_or_resolve",
            f"{_IDENTITY}::test_distinct_identities_correlate_only_through_explicit_relations",
        ),
    ),
    LowerGateRegression(
        RSE033_INSTALLER_RECOVERY_DEFECT_ID, INSTALLER_REGISTRY_RESOLUTION_DEFECT, GATE2,
        "GATE2_S5_S3_BOUNDED_RECOVERY", (
            f"{_PRODUCTIVE}::test_web_execution_routes_tool_unavailable_to_approval_bound_recovery_with_distinct_identities",
        ),
    ),
    # The normal Web / persisted-plan execution never entered S3.5.
    LowerGateRegression(
        RSE033_INSTALLER_RECOVERY_DEFECT_ID, MISSING_RECOVERY_COMPOSITION, GATE2,
        "GATE2_S5_S3_BOUNDED_RECOVERY", (
            f"{_PRODUCTIVE}::test_web_execution_routes_tool_unavailable_to_approval_bound_recovery_with_distinct_identities",
            f"{_PRODUCTIVE}::test_missing_planning_provenance_fails_closed_before_any_recovery",
        ),
    ),
    # A reverification that did not pass was reported as completed.
    LowerGateRegression(
        RSE033_INSTALLER_RECOVERY_DEFECT_ID, FAILED_REVERIFICATION_CONTAINMENT, GATE1, "TEST_014", (
            f"{_S3_5}::test_failed_reverification_never_reports_recovery_completed",
            f"{_S3_5}::test_reverification_without_a_structured_result_fails_closed",
        ),
    ),
    LowerGateRegression(
        RSE033_INSTALLER_RECOVERY_DEFECT_ID, FAILED_REVERIFICATION_CONTAINMENT, GATE2,
        "GATE2_S5_S3_BOUNDED_RECOVERY", (
            f"{_PRODUCTIVE}::test_failed_reverification_ends_recovery_fail_closed_without_a_second_cycle",
        ),
    ),
    # A runner-constructor literal, not the VerificationPlan/Step policy,
    # decided the compile budget.
    LowerGateRegression(
        RSE033_COMPILE_TIMEOUT_DEFECT_ID, VERIFICATION_BUDGET_POLICY_ESCAPE, GATE1, "TEST_021", (
            f"{_TIMEOUT_POLICY}::TestVerificationBudgetPolicy::test_producer_writes_explicit_policy_budget_into_every_step",
            f"{_TIMEOUT_POLICY}::TestVerificationBudgetPolicy::test_budget_depends_on_generic_operation_class_never_on_tool",
            f"{_TIMEOUT_POLICY}::TestVerificationBudgetPolicy::test_runners_have_no_constructor_budget",
        ),
    ),
    LowerGateRegression(
        RSE033_COMPILE_TIMEOUT_DEFECT_ID, VERIFICATION_BUDGET_POLICY_ESCAPE, GATE1, "TEST_022", (
            f"{_TIMEOUT_POLICY}::TestBudgetConsumptionAndProcessBoundary::test_changing_step_policy_changes_the_real_execution_budget",
            f"{_TIMEOUT_POLICY}::TestBudgetConsumptionAndProcessBoundary::test_invalid_budget_fails_closed_before_any_process",
        ),
    ),
    # Timeout killed only the direct child; descendants survived and the
    # partial output kept the wrong type. FIX-002: invalid UTF-8 partial
    # output aborted timeout cleanup (a SIGTERM-resistant descendant
    # survived) and the decode error surfaced as TOOL_UNAVAILABLE, the
    # S5 -> S3 missing-toolchain trigger.
    LowerGateRegression(
        RSE033_COMPILE_TIMEOUT_DEFECT_ID, PROCESS_TIMEOUT_DESCENDANT_CLEANUP, GATE1, "TEST_022", (
            f"{_TIMEOUT_POLICY}::TestBudgetConsumptionAndProcessBoundary::test_real_process_timeout_contains_tree_and_keeps_str_partial_output",
            f"{_TIMEOUT_POLICY}::TestBudgetConsumptionAndProcessBoundary::test_real_runner_timeout_through_registry_is_structured_timeout",
            f"{_TIMEOUT_POLICY}::TestBudgetConsumptionAndProcessBoundary::test_real_timeout_with_invalid_utf8_output_contains_tree_and_stays_timeout",
            f"{_TIMEOUT_POLICY}::TestBudgetConsumptionAndProcessBoundary::test_real_timeout_output_is_always_str_and_keeps_valid_text",
            f"{_TIMEOUT_POLICY}::TestBudgetConsumptionAndProcessBoundary::test_output_draining_failure_cannot_bypass_process_group_containment",
            f"{_TIMEOUT_POLICY}::TestBudgetConsumptionAndProcessBoundary::test_invalid_output_timeout_through_real_runner_is_generic_timeout_never_s3",
            f"{_TIMEOUT_POLICY}::TestBudgetConsumptionAndProcessBoundary::test_output_handling_error_is_never_reported_as_unavailable_tool",
        ),
    ),
    LowerGateRegression(
        RSE033_COMPILE_TIMEOUT_DEFECT_ID, PROCESS_TIMEOUT_DESCENDANT_CLEANUP, GATE2,
        "GATE2_S5_1_TO_S5_7", (
            f"{_TIMEOUT_PRODUCTIVE}::test_real_timeout_without_source_diagnosis_is_fail_closed_without_rework",
        ),
    ),
    # A timeout without any source-correctable diagnosis consumed the
    # single bounded S5 -> S4 rework.
    LowerGateRegression(
        RSE033_COMPILE_TIMEOUT_DEFECT_ID, TIMEOUT_REWORK_CLASSIFICATION, GATE1, "TEST_026", (
            f"{_TIMEOUT_POLICY}::TestTimeoutReworkClassification",
            "tests/test_testing_stage.py::test_timed_out_test_not_accepted_by_reviewer",
            "tests/test_testing_stage.py::test_timed_out_test_without_diagnosis_fails_closed_when_diagnosis_reviewer_raises",
        ),
    ),
    LowerGateRegression(
        RSE033_COMPILE_TIMEOUT_DEFECT_ID, TIMEOUT_REWORK_CLASSIFICATION, GATE2,
        "GATE2_FAULT_PERMUTATIONS", (
            f"{_TIMEOUT_PRODUCTIVE}::test_real_timeout_without_source_diagnosis_is_fail_closed_without_rework",
        ),
    ),
    LowerGateRegression(
        RSE033_COMPILE_TIMEOUT_DEFECT_ID, TIMEOUT_REWORK_CLASSIFICATION, GATE2,
        "GATE2_S5_S4_BOUNDED_REWORK", (
            f"{_TIMEOUT_PRODUCTIVE}::test_diagnosed_source_correctable_timeout_uses_exactly_one_bounded_rework",
        ),
    ),
    # A controlled verification process that had started and then failed
    # at ADC's execution boundary was reported as TOOL_UNAVAILABLE -- the
    # S5 -> S3.5 trigger -- instead of a fail-closed EXECUTION_ERROR.
    LowerGateRegression(
        RSE033_COMPILE_TIMEOUT_DEFECT_ID, EXECUTION_ERROR_CLASSIFICATION, GATE1, "TEST_022", (
            f"{_EXECUTION_ERROR}::TestExecutionErrorClassification::test_four_way_taxonomy_through_real_boundary_and_runners",
            f"{_EXECUTION_ERROR}::TestExecutionErrorClassification::test_post_start_runtime_error_is_execution_error_after_containment",
            f"{_EXECUTION_ERROR}::TestExecutionErrorClassification::test_launch_failure_before_start_is_tool_unavailable",
            f"{_EXECUTION_ERROR}::TestExecutionErrorClassification::test_launch_failure_that_provisioning_cannot_remedy_is_not_tool_unavailable",
            # The auxiliary python-distribution consumer: a no-verdict
            # target-Python query is neither "unavailable" nor "missing".
            f"{_EXECUTION_ERROR}::TestExecutionErrorClassification::test_python_distribution_keeps_unavailable_and_execution_error_distinct",
            f"{_EXECUTION_ERROR}::TestExecutionErrorClassification::test_python_distribution_execution_error_never_authorizes_setup",
        ),
    ),
    LowerGateRegression(
        RSE033_COMPILE_TIMEOUT_DEFECT_ID, EXECUTION_ERROR_CLASSIFICATION, GATE1, "TEST_026", (
            f"{_EXECUTION_ERROR}::TestExecutionErrorOutcomePolicy",
        ),
    ),
    LowerGateRegression(
        RSE033_COMPILE_TIMEOUT_DEFECT_ID, EXECUTION_ERROR_CLASSIFICATION, GATE1, "TEST_027", (
            f"{_EXECUTION_ERROR}::TestExecutionErrorReworkBudget",
        ),
    ),
    LowerGateRegression(
        RSE033_COMPILE_TIMEOUT_DEFECT_ID, EXECUTION_ERROR_CLASSIFICATION, GATE1, "TEST_014", (
            f"{_EXECUTION_ERROR}::TestExecutionErrorToolchainRecoveryBoundary",
        ),
    ),
    LowerGateRegression(
        RSE033_COMPILE_TIMEOUT_DEFECT_ID, EXECUTION_ERROR_CLASSIFICATION, GATE2,
        "GATE2_S5_1_TO_S5_7", (_EXECUTION_ERROR_PRODUCTIVE,),
    ),
    LowerGateRegression(
        RSE033_COMPILE_TIMEOUT_DEFECT_ID, EXECUTION_ERROR_CLASSIFICATION, GATE2,
        "GATE2_S5_S4_BOUNDED_REWORK", (_EXECUTION_ERROR_PRODUCTIVE,),
    ),
    LowerGateRegression(
        RSE033_COMPILE_TIMEOUT_DEFECT_ID, EXECUTION_ERROR_CLASSIFICATION, GATE2,
        "GATE2_S5_S3_BOUNDED_RECOVERY", (_EXECUTION_ERROR_PRODUCTIVE,),
    ),
    LowerGateRegression(
        RSE033_COMPILE_TIMEOUT_DEFECT_ID, EXECUTION_ERROR_CLASSIFICATION, GATE2,
        "GATE2_FAULT_PERMUTATIONS", (_EXECUTION_ERROR_PRODUCTIVE,),
    ),
    # A started distribution query that crashed (nonzero exit, no verdict)
    # was parsed as "not installed": Preflight listed the requirement as
    # missing and SetupPlanner planned its installation. Present / absent /
    # unavailable / runtime / timeout / malformed stay distinct, and every
    # no-verdict outcome fails Preflight closed before setup or Council.
    LowerGateRegression(
        RSE033_COMPILE_TIMEOUT_DEFECT_ID, NO_VERDICT_AS_ABSENCE_CLASSIFICATION, GATE1, "TEST_010", (
            f"{_NO_VERDICT}::TestDistributionPresenceClassification",
            f"{_NO_VERDICT}::TestPreflightNoVerdictFailsClosed",
            f"{_NO_VERDICT}::TestValidAbsenceStillAuthorizesSetup",
        ),
    ),
    # The PTY launcher discarded the shell's startup status only after a
    # fixed pause, so a slow startup value was published as the command's
    # exit status before the command ran, and a shell ending without a
    # completion record had its own status written as the command result.
    LowerGateRegression(
        RSE033_COMPILE_TIMEOUT_DEFECT_ID, FINAL_CHILD_STATUS_FIDELITY, GATE1, "TEST_012", (
            f"{_FINAL_CHILD}::TestStartupIsNotCompletion",
            f"{_FINAL_CHILD}::TestFinalChildStatusIsAuthoritative",
            f"{_FINAL_CHILD}::TestFinalChildOutputFidelity",
            f"{_FINAL_CHILD}::TestTerminalCommandRunnerConsumesOnlyCompletion",
            f"{_PRESENTER}::test_pty_launcher_captures_nonzero_exit",
            f"{_PRESENTER}::test_pty_launcher_preserves_command_env",
            f"{_PRESENTER}::test_pty_launcher_result_json_from_exit_code_file",
            f"{_PRESENTER}::test_exit_code_from_fifo_e2e",
            f"{_PRESENTER}::test_one_shot_fifo_e2e",
            # Productive STATUS-V3 result authority is independent of the
            # non-productive PTY component's authenticated completion.
            "tests/test_terminal_result_authority.py::test_fifo_status_cannot_disable_productive_timeout",
            "tests/test_terminal_status_adversarial.py::test_status_replacement_between_inspection_and_open_is_rejected",
            "tests/test_terminal_status_adversarial.py::test_descendant_cannot_rewrite_published_real_child_result",
            "tests/test_terminal_status_v3_contract.py::test_real_producer_mac_and_exit_status_match_independent_contract",
            "tests/test_terminal_status_v3_contract.py::test_real_command_start_failure_is_authenticated_not_started",
            "tests/test_terminal_status_v3_contract.py::test_real_execution_ids_keys_and_records_cannot_be_replayed",
        ),
    ),
)

_REQUIRED_CLASSES = frozenset({
    INSTALLER_REGISTRY_RESOLUTION_DEFECT, MISSING_RECOVERY_COMPOSITION,
    FAILED_REVERIFICATION_CONTAINMENT,
    VERIFICATION_BUDGET_POLICY_ESCAPE, PROCESS_TIMEOUT_DESCENDANT_CLEANUP,
    TIMEOUT_REWORK_CLASSIFICATION, EXECUTION_ERROR_CLASSIFICATION,
    NO_VERDICT_AS_ABSENCE_CLASSIFICATION, FINAL_CHILD_STATUS_FIDELITY,
})
_REAL_SYSTEM_SELECTORS = frozenset(SELECTOR_MAP["TEST_033"])


def _obligation_scope(gate: str):
    return SELECTOR_MAP if gate == GATE1 else GATE2_SELECTOR_MAP


def validate_register(register=DEFECT_REGISTER) -> None:
    if not register:
        raise MalformedDefectRegister("the defect register is empty")
    for entry in register:
        if not isinstance(entry, LowerGateRegression):
            raise MalformedDefectRegister(f"not a LowerGateRegression: {entry!r}")
        if entry.owning_gate not in (GATE1, GATE2):
            raise MalformedDefectRegister(f"unknown owning gate {entry.owning_gate!r}")
        scope = _obligation_scope(entry.owning_gate)
        if entry.owning_obligation not in scope or entry.owning_obligation == "TEST_033":
            raise MalformedDefectRegister(
                f"{entry.owning_obligation!r} is not a {entry.owning_gate} obligation"
            )
        if not isinstance(entry.selectors, tuple) or not entry.selectors:
            raise MalformedDefectRegister(f"{entry.defect_class}: regression selectors must be a non-empty tuple")
        if len(set(entry.selectors)) != len(entry.selectors):
            raise MalformedDefectRegister(f"{entry.defect_class}: duplicate regression selector")
        for selector in entry.selectors:
            if (not isinstance(selector, str) or not selector.startswith("tests/")
                    or "::" not in selector or any(ch.isspace() for ch in selector)):
                raise MalformedDefectRegister(f"malformed regression selector {selector!r}")
            if selector in _REAL_SYSTEM_SELECTORS or selector.startswith("tests/real_system/"):
                raise MalformedDefectRegister(
                    f"{selector!r} is Real-System (Gate 3) and never a lower-gate regression"
                )
    missing = _REQUIRED_CLASSES - {e.defect_class for e in register}
    if missing:
        raise MalformedDefectRegister(f"required defect classes are unregistered: {sorted(missing)}")


def mandatory_scope(entry: LowerGateRegression, collected) -> frozenset[str]:
    """The owning obligation's current mandatory nodes."""
    selectors = _obligation_scope(entry.owning_gate)[entry.owning_obligation]
    nodes = {n for n in collected for s in selectors if _selector_matches(n, s)}
    if entry.owning_gate == GATE1:
        nodes = {n for n in nodes if not is_gate3_only_nodeid(n)}
    return frozenset(nodes)


def evaluate_entry(entry, collected, outcomes, obligation_status) -> RegisterProof:
    collected = frozenset(collected)
    scope = mandatory_scope(entry, collected)
    reasons, nodes = [], set()
    for selector in entry.selectors:
        matched = {n for n in collected if _selector_matches(n, selector)}
        if not matched:
            reasons.append(f"stale or zero-node selector {selector}")
        nodes.update(matched)
    for node in sorted(nodes - scope):
        reasons.append(f"not mandatory in {entry.owning_obligation}: {node}")
    node_outcomes = tuple((n, outcomes.get(n, "MISSING")) for n in sorted(nodes))
    for node, outcome in node_outcomes:
        if outcome != PASSED:
            reasons.append(f"{outcome} {node}")
    status = obligation_status.get(entry.owning_obligation, "MISSING")
    if status != PROVEN:
        reasons.append(f"owning obligation {entry.owning_obligation} is {status} in the current proof")
    return RegisterProof(entry, OPEN if reasons else CLOSED, node_outcomes, tuple(reasons))


def evaluate_register(gate, collected, outcomes, obligation_status, register=DEFECT_REGISTER):
    """Evaluate the entries owned by `gate` against one current proof run."""
    validate_register(register)
    return tuple(
        evaluate_entry(entry, collected, outcomes, obligation_status)
        for entry in register if entry.owning_gate == gate
    )


def register_lines(proofs) -> list[str]:
    lines = []
    for proof in proofs:
        e = proof.entry
        lines.append(
            f"GATE3_DEFECT {e.defect_id} {e.defect_class} -> {e.owning_gate}:{e.owning_obligation} "
            f"nodes={len(proof.node_outcomes)} state={proof.state}"
        )
        lines.extend(f"  {reason}" for reason in proof.reasons)
    return lines
