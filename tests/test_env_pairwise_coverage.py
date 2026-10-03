"""Deterministic pairwise coverage for the interaction domains
(CLAUDE-ADC-TEST-ENVIRONMENT-FIDELITY-UPGRADE-001 section 3):

  A) process outcome x terminal/provider state
  B) cwd class x interface
  C) launcher environment x final-child environment
  D) approval state x capability state
  E) target identity x retry state

Uses tests/env_pairwise.py's own deterministic covering-array generator
(no external pairwise library exists in this environment) and real
product collaborators throughout -- never a hand-rolled re-
implementation of execute_controlled/CapabilityRegistry/
SetupExecutionStateStore logic.
"""
from __future__ import annotations

import os
from unittest.mock import Mock

import pytest

from app.execution import (
    ApprovalProvenance, CapabilityRegistration, CapabilityRegistry,
    ExecutionRequest, execute_controlled, validate_request,
)
from app.interactive_terminal import (
    DesktopTerminalProvider, INTERACTIVE_TERMINAL_CANCELLED,
    INTERACTIVE_TERMINAL_UNAVAILABLE, InteractiveTerminalError,
    InteractiveTerminalLauncher,
)
from tests.env_pairwise import case_id, generate_covering_array
from tests.env_scenarios import covers
from tests.terminal_final_child_probe import (
    build_probe_argv, install_early_exit_terminal,
    install_start_failure_terminal_candidates, probe_provider,
    write_final_child_probe,
)


# ============================================================================
# A) process outcome x terminal/provider state
# ============================================================================
_PARAMS_A = {
    "process_outcome": ("success", "nonzero", "spawn_failure"),
    "provider_state": ("available", "unavailable", "early_exit"),
}
_DOMAIN_A = generate_covering_array(_PARAMS_A, strength=2)


@covers(
    "PROC_SPAWN_SUCCESS", "PROC_SPAWN_FAILURE", "PROC_CHILD_SUCCESS",
    "PROC_CHILD_NONZERO", "TERM_PROVIDER_AVAILABLE",
)
@pytest.mark.parametrize("case", _DOMAIN_A, ids=[case_id(c) for c in _DOMAIN_A])
def test_pairwise_process_outcome_x_provider_state(tmp_path, monkeypatch, case):
    process_outcome = case["process_outcome"]
    provider_state = case["provider_state"]

    if provider_state == "unavailable":
        candidates = install_start_failure_terminal_candidates(tmp_path)
        provider = DesktopTerminalProvider(candidates=candidates)
    elif provider_state == "early_exit":
        _script, candidates = install_early_exit_terminal(tmp_path)
        provider = DesktopTerminalProvider(candidates=candidates, launcher_exit_grace=0.05)
    else:
        provider = probe_provider(tmp_path, monkeypatch)

    launcher = InteractiveTerminalLauncher(provider=provider)

    if provider_state != "available":
        # Provider-level faults dominate regardless of what the process
        # outcome would otherwise have been -- it never gets far enough
        # to matter.
        with pytest.raises(InteractiveTerminalError):
            launcher.run(("python3", "-c", "pass"), str(tmp_path), {"PATH": "/usr/bin"}, 5)
        return

    if process_outcome == "spawn_failure":
        def _raise(*a, **kw):
            raise OSError("simulated")
        monkeypatch.setattr("app.interactive_terminal.subprocess.Popen", _raise)
        with pytest.raises(InteractiveTerminalError):
            launcher.run(("python3", "-c", "pass"), str(tmp_path), {"PATH": "/usr/bin"}, 5)
        return

    probe = write_final_child_probe(tmp_path)
    out_path = tmp_path / f"result-{case_id(case)}.json"
    exit_code = 0 if process_outcome == "success" else 7
    result = launcher.run(build_probe_argv(probe, out_path, exit_code), str(tmp_path), {"PATH": "/usr/bin"}, 10)
    assert result.returncode == exit_code


# ============================================================================
# B) cwd class (EQUIVALENCE_PARTITION, not pairwise -- see note below)
# ============================================================================
# KIA-ADC-TEST-ASSURANCE-MODEL-FIX-001 section 4: this domain has only ONE
# genuinely varying dimension (cwd_class); "interface" is pinned to a single
# constant value ("internal") because Web/MCP parity for path confinement is
# established separately by tests/test_execution_consolidation.py's own MCP
# test and tests/test_execution_target_authorization_web_system.py's own Web
# test, both of which route through this SAME execute_controlled boundary --
# confinement logic is interface-agnostic by construction (Web/MCP never
# re-implement it), so this domain focuses its own sweep on the boundary
# itself rather than re-driving each adapter for every cwd class. A
# one-dimensional sweep is honestly an EQUIVALENCE_PARTITION over cwd_class,
# not a PAIRWISE claim -- generate_covering_array(strength=2) now refuses to
# generate this shape at all (see tests/env_pairwise.py), so it is expressed
# directly as one case per cwd_class value instead.
_PARAMS_B = {"cwd_class": ("valid_root", "nested", "outside_root", "missing")}
_DOMAIN_B = tuple(
    {"cwd_class": cwd_class, "interface": "internal"}
    for cwd_class in _PARAMS_B["cwd_class"]
)


@covers("FS_VALID_ROOT", "FS_NESTED_CWD", "FS_OUTSIDE_ROOT_CWD", "FS_MISSING_CWD", "IFACE_INTERNAL")
@pytest.mark.parametrize("case", _DOMAIN_B, ids=[case_id(c) for c in _DOMAIN_B])
def test_pairwise_cwd_class_x_interface(tmp_path, case):
    project_root = tmp_path / "project"
    project_root.mkdir()
    cwd_class = case["cwd_class"]

    if cwd_class == "valid_root":
        cwd = project_root
    elif cwd_class == "nested":
        cwd = project_root / "nested"
        cwd.mkdir()
    elif cwd_class == "outside_root":
        cwd = tmp_path / "outside"
        cwd.mkdir()
    else:  # missing
        cwd = project_root / "does-not-exist"

    request = ExecutionRequest(("python3", "-c", "pass"), str(cwd), 10, "python", "verification")

    if cwd_class in ("valid_root", "nested"):
        result = execute_controlled(request, project_root)
        assert result is not None and result.returncode == 0
    elif cwd_class == "outside_root":
        with pytest.raises(ValueError, match="cwd escapes project root"):
            execute_controlled(request, project_root)
    else:  # missing: passes validate_request (still within project_root),
        # but the OS itself cannot chdir into it -- fails closed to None.
        result = execute_controlled(request, project_root)
        assert result is None


# ============================================================================
# C) launcher environment x final-child environment
# ============================================================================
_PARAMS_C = {
    "provider_class": ("direct_process", "client_server_divergent"),
    "ambient_secret_present": (True, False),
}
_DOMAIN_C = generate_covering_array(_PARAMS_C, strength=2)


@covers(
    "ENV_SECRET_LIKE", "ENV_AMBIENT_FORBIDDEN", "ENV_CONTROLLED_OVERRIDES_AMBIENT",
    "ENV_FINAL_CHILD_ALLOWLIST_ONLY", "TERM_CLIENT_SERVER_STYLE",
)
@pytest.mark.parametrize("case", _DOMAIN_C, ids=[case_id(c) for c in _DOMAIN_C])
def test_pairwise_launcher_env_x_final_child_env(tmp_path, monkeypatch, case):
    from tests.terminal_final_child_probe import client_server_provider, read_client_server_record

    if case["ambient_secret_present"]:
        monkeypatch.setenv("ADC_TEST_SECRET_TOKEN", "should-not-leak")

    controlled_env = {"PATH": "/usr/bin"}

    if case["provider_class"] == "direct_process":
        provider = probe_provider(tmp_path, monkeypatch)
        launcher = InteractiveTerminalLauncher(provider=provider)
        probe = write_final_child_probe(tmp_path)
        out_path = tmp_path / f"result-{case_id(case)}.json"
        launcher.run(build_probe_argv(probe, out_path, 0), str(tmp_path), controlled_env, 10)
        from tests.terminal_final_child_probe import read_final_child_result
        observed_env = read_final_child_result(out_path)["env"]
    else:
        provider, record_path = client_server_provider(
            tmp_path, monkeypatch, server_env={"PATH": "/stale/server/path"},
        )
        launcher = InteractiveTerminalLauncher(provider=provider)
        launcher.run(("python3", "-c", "pass"), str(tmp_path), controlled_env, 10)
        observed_env = read_client_server_record(record_path)["final_child_env"]

    if case["provider_class"] == "direct_process":
        # The controlled allowlist wins in the final child regardless
        # of any ambient secret on the ADC process.
        assert "ADC_TEST_SECRET_TOKEN" not in observed_env
        assert observed_env.get("PATH") == "/usr/bin"
    else:
        # The divergent client/server surrogate demonstrates the
        # opposite, real risk: the final child's env is whatever the
        # (simulated stale) server used, not the controlled allowlist --
        # proving this divergence is observable, not silently assumed away.
        assert observed_env.get("PATH") == "/stale/server/path"


# ============================================================================
# D) approval/provenance state x capability state
# ============================================================================
_PARAMS_D = {
    "approval_state": ("approved_complete", "incomplete_provenance"),
    "capability_state": ("none_registered", "registered_matching", "registered_wrong_executable"),
}
_DOMAIN_D = generate_covering_array(_PARAMS_D, strength=2)


@covers(
    "AUTH_VALID_PROVENANCE_CAPABILITY", "AUTH_MISSING_CAPABILITY",
    "AUTH_WRONG_EXECUTABLE_CAPABILITY", "AUTH_STALE_APPROVAL",
)
@pytest.mark.parametrize("case", _DOMAIN_D, ids=[case_id(c) for c in _DOMAIN_D])
def test_pairwise_approval_state_x_capability_state(tmp_path, case):
    project_root = tmp_path / "project"
    project_root.mkdir()
    resolved_root = str(project_root.resolve())
    registry = CapabilityRegistry()
    target = "/opt/tool/python"

    def _provenance():
        if case["approval_state"] == "incomplete_provenance":
            # A missing engineering_council_ref -- CapabilityRegistry's
            # own completeness check must reject this at REGISTRATION
            # time, before validate_request is ever reached.
            return ApprovalProvenance(resolved_root, "", "variant-1", "setup-approval:p:approved")
        return ApprovalProvenance(resolved_root, "council-1", "variant-1", "setup-approval:p:approved")

    registration_error = None
    if case["capability_state"] == "registered_matching":
        try:
            registry.register_approved(CapabilityRegistration(
                capability="python", executable_names=(target,), allowed_operations=("install",),
                approval_provenance=_provenance(), project_scope=resolved_root,
            ))
        except ValueError as exc:
            registration_error = exc
    elif case["capability_state"] == "registered_wrong_executable":
        try:
            registry.register_approved(CapabilityRegistration(
                capability="python", executable_names=("/other/python",), allowed_operations=("install",),
                approval_provenance=_provenance(), project_scope=resolved_root,
            ))
        except ValueError as exc:
            registration_error = exc
    # "none_registered": leave registry empty entirely.

    if case["approval_state"] == "incomplete_provenance" and case["capability_state"] != "none_registered":
        assert registration_error is not None, "incomplete provenance must be rejected at registration time"

    request = ExecutionRequest((target, "-m", "pip", "install", "pkg"), str(project_root), 10, "python", "install")
    violation = validate_request(request, project_root, registry)

    if (
        case["capability_state"] == "registered_matching"
        and case["approval_state"] == "approved_complete"
    ):
        assert violation is None
    else:
        assert violation is not None


# ============================================================================
# E) target identity x retry state
# ============================================================================
_PARAMS_E = {
    "target_identity": ("target_a", "target_b_different"),
    "retry_state": ("first_attempt", "already_completed", "already_executing"),
}
_DOMAIN_E = generate_covering_array(_PARAMS_E, strength=2)


@covers("AUTH_WRONG_TARGET", "LIFE_FIRST_EXECUTION", "LIFE_ALREADY_COMPLETED", "LIFE_ALREADY_EXECUTING")
@pytest.mark.parametrize("case", _DOMAIN_E, ids=[case_id(c) for c in _DOMAIN_E])
def test_pairwise_target_identity_x_retry_state(tmp_path, case):
    from app.setup_execution_state import SetupExecutionStateStore, SetupStepIdentity
    from app.requirement_model import SetupEffect, SetupStep

    project_root = tmp_path / "project"
    project_root.mkdir()
    store = SetupExecutionStateStore(tmp_path / f"exec-state-{case_id(case)}.json")
    step = SetupStep(
        id="s1", requirement_id="r1", action="install", install_method="pip",
        package="pkg", setup_effect=SetupEffect.PYTHON_PACKAGE_INSTALL,
        is_approved=True, target_executable="/opt/tool/python",
    )
    identity = SetupStepIdentity.for_step(str(project_root), "gen-1", step)

    if case["retry_state"] == "already_completed":
        store.begin(identity, "owner-1")
        store.finish(identity, "owner-1", "succeeded", {"success": True})
    elif case["retry_state"] == "already_executing":
        store.begin(identity, "owner-1")

    current = store.get(identity)
    if case["retry_state"] == "first_attempt":
        assert current is None
    elif case["retry_state"] == "already_completed":
        assert current is not None and current["status"] == "succeeded"
    else:
        assert current is not None and current["status"] == "in_progress"

    # target_identity dimension: a DIFFERENT step (same step_id, a
    # different target_executable -- e.g. a substitution attempt) is a
    # genuinely different identity by content, but shares the SAME
    # (project, generation, step) lookup key as the original. Proves
    # target substitution can never silently reuse another target's
    # persisted state: when a record already exists for that key (any
    # non-first-attempt retry_state), the content-immutability check
    # correctly fails closed rather than returning None or reusing it.
    if case["target_identity"] == "target_b_different":
        other_step = SetupStep(
            id="s1", requirement_id="r1", action="install", install_method="pip",
            package="pkg", setup_effect=SetupEffect.PYTHON_PACKAGE_INSTALL,
            is_approved=True, target_executable="/different/python",
        )
        other_identity = SetupStepIdentity.for_step(str(project_root), "gen-1", other_step)
        assert other_identity != identity
        if case["retry_state"] == "first_attempt":
            assert store.get(other_identity) is None
        else:
            from app.setup_execution_state import SetupExecutionStateError
            with pytest.raises(SetupExecutionStateError, match="different execution-relevant content"):
                store.get(other_identity)
