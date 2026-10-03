"""Scoped normative adoption 026, without promoting legacy reproductions.

The original selector declaration (including foreign FIX019 additions) remains
intact. Its effective TEST_003 scope is alternatives/cross-review only. Acceptance 028 adds explicitly reviewed contract selectors.
These selectors do not inherit historical IO or constitute product evidence. Reproductions are retained
for investigation, not silently reinterpreted as adopted transport guarantees.
"""

COUNCIL_LIFECYCLE_OBLIGATIONS = ("TEST_036", "TEST_037", "TEST_038", "TEST_039")


COUNCIL_CONTRACT_SELECTORS = {
    "TEST_036": (
        "tests/test_council_contract_transport.py",
        "tests/test_council_contract_native_transport.py",
        # A failed run-thread handover must release the request booking and
        # permit a later valid handover; this is the lifecycle closure edge.
        "tests/test_resource_contract_closure_037.py::test_run_thread_start_failure_releases_input_booking",
    ),
    "TEST_037": (
        "tests/test_council_contract_storage.py",
        "tests/test_fix034_acceptance.py",
        # Pending persistence owns a booked payload until the writer drops it.
        "tests/test_resource_contract_closure_037.py::test_pending_persistence_payload_booked_until_writer_drops_it",
        "tests/test_fix032_ownership.py::test_instance_and_session_result_release",
        "tests/test_fix032_ownership.py::test_unbookable_result_fails_closed_and_releases",
        "tests/test_fix032_ownership.py::test_retained_exception_traceback_keeps_data_charged",
        "tests/test_fix032_ownership.py::test_finalization_exception_keeps_large_result_charged",
    ),
    "TEST_038": (
        "tests/test_council_contract_notification.py",
        "tests/test_fix032_ownership.py::test_queue_coalescing_close_and_actual_release",
        "tests/test_fix032_ownership.py::test_independent_parallel_instances",
        "tests/test_fix032_ownership.py::test_same_instance_refusal_starts_no_second_body_and_recovers",
        # Actual overload, refused booking, and capacity release/recovery.
        "tests/test_resource_contract_closure_037.py::test_unbookable_input_refuses_admission_bounded_and_recovers",
        "tests/test_resource_contract_closure_037.py::test_unbookable_prompt_starts_no_invocation",
        "tests/test_resource_contract_closure_037.py::test_unbookable_response_is_dropped_and_not_retried",
        "tests/test_resource_contract_closure_037.py::test_concurrent_admission_refused_while_capacity_held_then_recovers",
    ),
    "TEST_039": (
        "tests/test_council_contract_deadline.py",
        # Bookings survive a quarantined worker or retained exception until
        # the final owner actually exits / is collected.
        "tests/test_resource_contract_closure_037.py::test_quarantined_worker_keeps_working_data_booked_until_it_ends",
        "tests/test_resource_contract_closure_037.py::test_body_exception_in_gc_cycle_keeps_run_data_booked",
    ),
}


def separate_council_lifecycle(selector_map):
    scoped = {key: list(value) for key, value in selector_map.items()}
    legacy = tuple(
        selector for selector in scoped["TEST_003"]
        if not selector.startswith("tests/test_engineering_council.py::")
    )
    scoped["TEST_003"] = [
        selector for selector in scoped["TEST_003"] if selector not in legacy
    ]
    for obligation in COUNCIL_LIFECYCLE_OBLIGATIONS:
        if obligation in scoped:
            raise ValueError(f"Lifecycle acceptance mapping must be reviewed explicitly: {obligation}")
        scoped[obligation] = list(COUNCIL_CONTRACT_SELECTORS[obligation])
    return scoped, legacy
