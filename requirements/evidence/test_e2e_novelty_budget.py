"""Tests for the E2E novelty budget
(KIA-ADC-TEST-ASSURANCE-MODEL-FIX-001 section 8)."""
from __future__ import annotations

import pytest

from requirements.evidence.e2e_novelty_budget import (
    MUST_BE_CAUGHT_GATE1, MUST_BE_CAUGHT_GATE2, REAL_SYSTEM_ONLY, classify,
)


@pytest.mark.parametrize("category", [
    "mapping_state_error", "provenance_error", "capability_authorization_error",
    "cwd_policy_error", "argv_fidelity_error", "final_child_env_policy_error",
    "lifecycle_state_error", "deterministic_process_boundary_error",
])
def test_named_internal_semantic_defects_are_never_real_system_only(category):
    assert classify(category) == MUST_BE_CAUGHT_GATE1


@pytest.mark.parametrize("category", [
    "retry_idempotency_error", "persistence_reload_error",
    "producer_consumer_handoff_error", "web_mcp_parity_error", "bounded_recovery_error",
])
def test_composition_defects_require_at_least_gate2(category):
    assert classify(category) == MUST_BE_CAUGHT_GATE2


@pytest.mark.parametrize("category", [
    "gnome_terminal_xterm_behavior", "terminal_client_server_reuse_behavior",
    "dbus_wayland_x11_session_inheritance", "pty_sudo_interaction",
    "os_scheduling_signals", "real_filesystem_mount_permission_behavior",
    "actual_installed_toolchain_variant_behavior",
    "real_external_network_cloud_provider_behavior",
])
def test_genuine_physical_machine_categories_are_real_system_only(category):
    assert classify(category) == REAL_SYSTEM_ONLY


def test_unknown_category_is_rejected_not_defaulted_to_real_system_only():
    with pytest.raises(ValueError, match="unrecognized E2E novelty-budget category"):
        classify("some_new_category_nobody_classified_yet")
