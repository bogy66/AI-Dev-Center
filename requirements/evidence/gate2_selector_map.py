"""Central Gate-2 obligation -> mandatory selector map
(CLAUDE-ADC-RSE033-GATE2-MECHANICAL-PROOF-GOVERNANCE-FIX-002).

The ONE place that answers, for each of the 19 existing
requirements/evidence/gate2_obligations.py obligations: which pytest
nodes prove it? Obligation ids and semantics are owned by
gate2_obligations.py and are NOT redefined here; this module only binds
each existing obligation to the tests whose real producer -> real
artifact -> real consumer composition proves it. Whether an obligation
is PROVEN is never stated here -- it is derived solely from a current
run by requirements/evidence/gate2_proof.py.

Selector semantics are those of the Gate-1 current-run tracker
(current_run_completion._selector_matches): an exact nodeid, a
``file::Class`` / ``file::test`` prefix (covering its methods and
parametrizations), or -- only for a file dedicated to that single
obligation's concern -- a whole file. Every expanded node is mandatory.

A node may intentionally prove more than one obligation (e.g. the
canonical S5->S6 composition also carries real S4 output into S5, and
its negative case runs the single bounded S5->S4 rework for real).

Deliberately NOT mapped (no truthful productive ownership):
  - tests/test_web_gui_e2e.py (application service is a Mock);
  - tests/test_final_approval.py, TestS5_to_S6_Boundary,
    TestS5_S6_FinalApprovalGate (hand-built S5 status);
  - real_system-marked tests, e.g. test_execution_consolidation.py::
    test_real_local_package_install_and_uninstall_via_central_boundary
    (Gate 3 only, never mandatory Gate-2 evidence);
  - requirements/evidence self-tests (governance, not product proof).
"""
from __future__ import annotations

_S2 = "tests/test_s2_subsubsystem_architecture.py"
_S3 = "tests/test_s3_subsubsystem_architecture.py"
_S4 = "tests/test_s4_subsubsystem_architecture.py"
_S5 = "tests/test_s5_subsubsystem_architecture.py"
_WEB = "tests/test_productive_web_e2e.py"
_S5_S6 = "tests/test_productive_boundary_contracts.py::TestS5_S6_ProductiveComposition"
_RETRY_S3 = "tests/test_execution_target_authorization_retry_s3.py"
_RETRY_SYSTEM = "tests/test_execution_target_authorization_retry_system.py"
_CONSOLIDATION = "tests/test_execution_consolidation.py"
_SUBSYSTEMS = "tests/test_execution_target_authorization_subsystems.py"

# The permanent RSE033 defect-shape regression: structural Chairman
# recovery -> binding executable omitted -> real S2.3 rejection -> one
# admissibility rework -> real S2.3 revalidation ([repaired] and
# [fail-closed] parametrizations).
RSE033_PRODUCTIVE_PATH_SELECTOR = (
    f"{_WEB}::test_application_chairman_structural_recovery_then_binding_rework"
)
S5_S6_PRODUCTIVE_PATH_SELECTOR = _S5_S6
# DEF-RSE033-ESPHOME-COMPILE-TIMEOUT: real policy-budgeted verification
# timeout through the canonical composition (real subprocess tree, real
# timeout, real S5.6 routing); only the LLM provider is substituted.
_S5_TIMEOUT = "tests/test_productive_boundary_contracts.py::TestS5_VerificationTimeoutProductiveComposition"
S5_TIMEOUT_FAIL_CLOSED_SELECTOR = (
    f"{_S5_TIMEOUT}::test_real_timeout_without_source_diagnosis_is_fail_closed_without_rework"
)
S5_TIMEOUT_BOUNDED_REWORK_SELECTOR = (
    f"{_S5_TIMEOUT}::test_diagnosed_source_correctable_timeout_uses_exactly_one_bounded_rework"
)
# EXECUTION_ERROR_CLASSIFICATION: a real, started verification process
# failing at ADC's execution boundary through the canonical composition
# (real containment, real S5.6 terminal routing, no rework, no recovery).
S5_EXECUTION_ERROR_TERMINAL_SELECTOR = (
    "tests/test_productive_boundary_contracts.py::TestS5_VerificationExecutionErrorProductiveComposition"
    "::test_real_execution_error_is_fail_closed_terminal_without_rework_or_recovery"
)

# The S5 -> S3.5 recovery Productive-Path through the normal Web /
# application entry (execute_approved_plan_from_store owns the routing):
# real S5 TOOL_UNAVAILABLE -> real recovery record -> pending approval ->
# explicit decision -> real installer resolution -> real reverification
# (pass, fail-closed failure, missing planning provenance). Only the LLM,
# the install terminal and the installed CLI are external substitutes.
_S5_S3_PRODUCTIVE = "tests/test_installer_recovery_productive_path.py"
S5_S3_PRODUCTIVE_PATH_SELECTOR = _S5_S3_PRODUCTIVE
S5_S3_PRODUCTIVE_IDENTITY_SELECTOR = (
    f"{_S5_S3_PRODUCTIVE}::test_web_execution_routes_tool_unavailable_to_"
    "approval_bound_recovery_with_distinct_identities"
)

GATE2_SELECTOR_MAP: dict[str, tuple[str, ...]] = {
    # Real discovery RequirementSet reaches the real Council input.
    "GATE2_S1_S2": (
        f"{_WEB}::test_productive_web_planning_reaches_real_approval_boundary",
        f"{_WEB}::test_productive_degraded_council_continues_to_approval",
    ),
    # Real S2 decision reaches real S3 materialization / setup approval.
    "GATE2_S2_S3": (
        f"{_WEB}::test_productive_web_planning_reaches_real_approval_boundary",
        f"{_WEB}::test_engineering_decision_reject_never_reaches_setup_approval",
        f"{_S2}::TestBoundaryS2ToS3",
        f"{_S2}::TestProductiveS2_4Boundary",
    ),
    "GATE2_S2_5_S3_IDENTITY": (
        f"{_S2}::TestBoundaryS2ToS3::test_s3_receives_exact_chosen_variant_chairman_selected_when_human_accepts",
        f"{_S2}::TestBoundaryS2ToS3::test_s3_receives_exact_chosen_variant_human_selected",
        f"{_S2}::TestBoundaryS2ToS3::test_raw_council_result_rejected_as_normal_engineering_decision",
        f"{_S2}::TestBoundaryS2ToS3::test_raw_council_variant_rejected_as_normal_handoff",
        f"{_S2}::TestBoundaryS2_4_to_S2_5::test_exact_selected_candidate_preservation",
        f"{_S3}::TestS2_5_to_S3_Boundary",
        # The same bound EngineeringDecision (variant, authority, distinct
        # IF_REQ_037 identities) is the one S3.5 recovery re-materializes.
        S5_S3_PRODUCTIVE_IDENTITY_SELECTOR,
    ),
    "GATE2_S3_1_TO_S3_5": (
        f"{_S3}::TestS3_1_SetupPlanning",
        f"{_S3}::TestS3_2_SetupApproval",
        f"{_S3}::TestS3_3_ControlledExecution",
        f"{_S3}::TestS3_4_ExecutionStateIdempotency",
        f"{_S3}::TestS3_5_MissingToolchainRecovery",
        _SUBSYSTEMS,
        "tests/test_real_productive_integration.py",
    ),
    # ARC_031 "S3 Execution -> EnvironmentState -> S4": the persisted,
    # real setup-execution outcome gates whether S4 may start.
    "GATE2_S3_S4_ENVIRONMENT_STATE": (
        f"{_S3}::TestS3_to_S4_Boundary",
    ),
    "GATE2_S4_1_TO_S4_4": (
        f"{_S4}::TestS4_1_DevelopmentChangeGeneration",
        f"{_S4}::TestS4_2_TestChangeGeneration",
        f"{_S4}::TestS4_3_ChangeApplication",
        f"{_S4}::TestS4_4_ChangeProvenanceAttribution",
    ),
    "GATE2_S4_S5": (
        f"{_S4}::TestS4_to_S5_Boundary",
        f"{_S5_S6}::test_accepted_real_s5_result_opens_real_s6_final_approval",
    ),
    "GATE2_S5_1_TO_S5_7": (
        f"{_S5}::TestS5_1_VerificationPlanning",
        f"{_S5}::TestS5_2_ControlledVerificationExecution",
        f"{_S5}::TestS5_3_VerificationEvidenceAggregation",
        f"{_S5}::TestS5_4_DiagnosticEvidenceFormatting",
        f"{_S5}::TestS5_5_LLMDiagnosisInterpretation",
        f"{_S5}::TestS5_6_DeterministicTestOutcomePolicy",
        f"{_S5}::TestS5_7_ControlledReworkOrchestration",
        S5_TIMEOUT_FAIL_CLOSED_SELECTOR,
        S5_EXECUTION_ERROR_TERMINAL_SELECTOR,
    ),
    "GATE2_S5_S4_BOUNDED_REWORK": (
        f"{_S5}::TestS5_to_S4_Boundary",
        f"{_S5}::TestS5_7_ControlledReworkOrchestration::test_rework_required_triggers_exactly_one_cycle",
        f"{_S5}::TestS5_7_ControlledReworkOrchestration::test_second_failure_does_not_create_a_third_cycle",
        f"{_S5_S6}::test_real_deterministic_s5_failure_never_reaches_s6",
        S5_TIMEOUT_BOUNDED_REWORK_SELECTOR,
        S5_EXECUTION_ERROR_TERMINAL_SELECTOR,
    ),
    "GATE2_S5_S3_BOUNDED_RECOVERY": (
        S5_S3_PRODUCTIVE_PATH_SELECTOR,
        S5_EXECUTION_ERROR_TERMINAL_SELECTOR,
        # Supplementary artifact/status-level coverage; never the sole proof.
        f"{_S5}::TestS5_to_S3_Boundary",
        f"{_S3}::TestS3_5_MissingToolchainRecovery",
        "tests/test_s3_missing_toolchain_capability_authorization.py",
        "tests/test_env_state_machine.py::TestMissingToolchainRecoveryStateMachine",
    ),
    "GATE2_S5_S6": (
        S5_S6_PRODUCTIVE_PATH_SELECTOR,
    ),
    "GATE2_WEB": (
        "tests/test_council_contract_storage.py::test_web_owned_result_is_charged_after_registry_expiry",
        # 028: real Council/workflow receiver -> central store -> public query.
        # Internal council_diagnosis() alone cannot satisfy this composition.
        "tests/test_council_contract_storage.py::test_public_query_retrieves_critical_diagnosis_when_callbacks_block",
        f"{_WEB}::test_productive_web_planning_reaches_real_approval_boundary",
        f"{_WEB}::test_engineering_decision_endpoints_reject_unknown_and_are_deferrable",
        f"{_WEB}::test_engineering_decision_reject_never_reaches_setup_approval",
        f"{_RETRY_SYSTEM}::test_web_http_boundary_retry_launches_zero_additional_processes",
        S5_S3_PRODUCTIVE_IDENTITY_SELECTOR,
    ),
    "GATE2_MCP": (
        "tests/test_execution_target_authorization_mcp.py",
        "tests/test_execution_target_authorization_mcp_negative.py",
        f"{_CONSOLIDATION}::test_mcp_execute_setup_plan_routes_through_execute_controlled_with_correct_cwd",
        f"{_CONSOLIDATION}::test_mcp_plan_then_execute_round_trip_persists_and_resolves_project_root",
        f"{_CONSOLIDATION}::test_mcp_execute_setup_plan_fails_closed_when_no_project_root_was_ever_associated",
        f"{_RETRY_SYSTEM}::test_mcp_boundary_retry_launches_zero_additional_processes",
    ),
    "GATE2_PERSISTENCE_RELOAD": (
        "tests/test_council_contract_storage.py::test_blocked_notification_prompt_remains_charged",
        "tests/test_council_contract_storage.py::test_retained_protocols_remain_charged_after_diagnosis_expiry",
        "tests/test_council_contract_storage.py::test_run_thread_start_failure_releases_admission_reservations",
        # Confirmed Council files must preserve the mandatory lifecycle facts.
        "tests/test_council_contract_storage.py::test_confirmed_reload_preserves_critical_completion_diagnosis",
        f"{_RETRY_S3}::TestGuardedFirstExecutionAndRetry::test_process_restart_after_succeeded_does_not_relaunch",
        f"{_RETRY_S3}::TestStaleInProgressAfterRestart",
        f"{_SUBSYSTEMS}::TestS3Persistence",
        "tests/test_workflow_plan_store_mappingproxy_persistence.py::test_persist_setup_plan_productive_path_round_trips_mappingproxy_metadata",
        "tests/test_execution_target_authorization_approved_content_immutability.py::TestPart7RestartContract",
        "tests/test_execution_target_authorization_content_immutability_and_legacy.py::TestLegacy003HUpgradeSafety",
        "tests/test_env_fault_matrix.py::test_fault_persistence_corruption_fails_closed_on_reload",
    ),
    "GATE2_RETRY_IDEMPOTENCY": (
        _RETRY_S3,
        _RETRY_SYSTEM,
        "tests/test_env_property_invariants.py::test_property_known_success_retry_produces_zero_additional_launches",
    ),
    "GATE2_CROSS_PROCESS": (
        "tests/test_execution_target_authorization_cross_process.py",
    ),
    "GATE2_LIFECYCLE_PERMUTATIONS": (
        "tests/test_env_state_machine.py",
        "tests/test_env_threeway_coverage.py::test_threeway_child_status_outcome_x_lifecycle_x_interface",
    ),
    "GATE2_ENVIRONMENT_PERMUTATIONS": (
        "tests/test_env_pairwise_coverage.py",
        "tests/test_env_threeway_coverage.py",
        "tests/test_env_property_invariants.py",
    ),
    "GATE2_FAULT_PERMUTATIONS": (
        "tests/test_env_fault_matrix.py",
        RSE033_PRODUCTIVE_PATH_SELECTOR,
        f"{_WEB}::test_productive_degraded_council_continues_to_approval",
        f"{_S5_S3_PRODUCTIVE}::test_failed_reverification_ends_recovery_fail_closed_without_a_second_cycle",
        f"{_S5_S3_PRODUCTIVE}::test_missing_planning_provenance_fails_closed_before_any_recovery",
        S5_TIMEOUT_FAIL_CLOSED_SELECTOR,
        S5_EXECUTION_ERROR_TERMINAL_SELECTOR,
    ),
}
