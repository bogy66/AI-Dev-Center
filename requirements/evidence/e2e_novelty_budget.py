"""E2E novelty budget (KIA-ADC-TEST-ASSURANCE-MODEL-FIX-001 section 8).

Classifies defect/error CATEGORIES into:

  MUST_BE_CAUGHT_GATE1   -- a deterministic, focused test must catch it.
  MUST_BE_CAUGHT_GATE2   -- a real productive-composition test must catch it.
  REAL_SYSTEM_ONLY       -- only genuine Real-System-E2E can catch it.

The whole point of this budget is that REAL_SYSTEM_ONLY must be earned,
not defaulted into: `classify()` only ever returns REAL_SYSTEM_ONLY for
a category on the explicit `_GENUINE_REAL_SYSTEM_ONLY_CATEGORIES`
allowlist below -- every category this task's own spec names as
"legitimate Gate-3-only novelty" (real terminal-emulator/session/OS
behavior actually requiring the physical machine), and nothing else.
Every other category defaults to MUST_BE_CAUGHT_GATE1 (the safer,
stricter default), and `classify()` raises for a completely unknown
category rather than silently guessing REAL_SYSTEM_ONLY for it.
"""
from __future__ import annotations

MUST_BE_CAUGHT_GATE1 = "MUST_BE_CAUGHT_GATE1"
MUST_BE_CAUGHT_GATE2 = "MUST_BE_CAUGHT_GATE2"
REAL_SYSTEM_ONLY = "REAL_SYSTEM_ONLY"

_VALID_CLASSIFICATIONS = frozenset({MUST_BE_CAUGHT_GATE1, MUST_BE_CAUGHT_GATE2, REAL_SYSTEM_ONLY})

# Internal semantic defect categories this task's own spec explicitly
# requires to be caught below Gate 3 -- never REAL_SYSTEM_ONLY, no
# matter whether a deterministic lower-level test happens to exist yet.
_MUST_BE_CAUGHT_GATE1_CATEGORIES = frozenset({
    "mapping_state_error",
    "provenance_error",
    "capability_authorization_error",
    "cwd_policy_error",
    "argv_fidelity_error",
    "final_child_env_policy_error",
    "lifecycle_state_error",
    "deterministic_process_boundary_error",
})
_MUST_BE_CAUGHT_GATE2_CATEGORIES = frozenset({
    "retry_idempotency_error",
    "persistence_reload_error",
    "producer_consumer_handoff_error",
    "web_mcp_parity_error",
    "bounded_recovery_error",
})

# The ONLY categories this task's own spec names as legitimate Gate-3
# novelty -- real, physical-machine-dependent behavior no deterministic
# test can reproduce.
_GENUINE_REAL_SYSTEM_ONLY_CATEGORIES = frozenset({
    "gnome_terminal_xterm_behavior",
    "terminal_client_server_reuse_behavior",
    "dbus_wayland_x11_session_inheritance",
    "pty_sudo_interaction",
    "os_scheduling_signals",
    "real_filesystem_mount_permission_behavior",
    "actual_installed_toolchain_variant_behavior",
    "real_external_network_cloud_provider_behavior",
})

_ALL_KNOWN_CATEGORIES = (
    _MUST_BE_CAUGHT_GATE1_CATEGORIES
    | _MUST_BE_CAUGHT_GATE2_CATEGORIES
    | _GENUINE_REAL_SYSTEM_ONLY_CATEGORIES
)


def classify(category: str) -> str:
    """Classify a defect/error category. Raises ValueError for a
    category this budget does not recognize at all, rather than
    silently defaulting it anywhere -- an unrecognized category must be
    added to exactly one of the sets above by a human, never inferred."""
    if category in _GENUINE_REAL_SYSTEM_ONLY_CATEGORIES:
        return REAL_SYSTEM_ONLY
    if category in _MUST_BE_CAUGHT_GATE2_CATEGORIES:
        return MUST_BE_CAUGHT_GATE2
    if category in _MUST_BE_CAUGHT_GATE1_CATEGORIES:
        return MUST_BE_CAUGHT_GATE1
    raise ValueError(
        f"unrecognized E2E novelty-budget category {category!r}: it must be "
        f"explicitly added to exactly one of "
        f"_MUST_BE_CAUGHT_GATE1_CATEGORIES / _MUST_BE_CAUGHT_GATE2_CATEGORIES / "
        f"_GENUINE_REAL_SYSTEM_ONLY_CATEGORIES in this module -- never inferred "
        f"as REAL_SYSTEM_ONLY merely because no lower-level test currently exists."
    )
