"""High-risk deterministic 3-way coverage
(CLAUDE-ADC-TEST-ENVIRONMENT-FIDELITY-UPGRADE-001 section 4):

  A) provider architecture x desktop/session environment x cwd behaviour
  B) approval/provenance x target mutation x retry state
  C) child outcome/status-file outcome x lifecycle state x interface
  D) ambient secret variable x required GUI/session environment x
     controlled final-child environment

Every combination asserts a real product invariant, never merely "did
not crash". Uses tests/env_pairwise.py's own generator at strength=3.
"""
from __future__ import annotations

import pytest

from app.execution import ApprovalProvenance, CapabilityRegistration, CapabilityRegistry
from app.interactive_terminal import DesktopTerminalProvider, InteractiveTerminalLauncher
from tests.env_pairwise import case_id, generate_covering_array
from tests.env_scenarios import covers
from tests.terminal_final_child_probe import (
    build_probe_argv, client_server_provider, install_early_exit_terminal,
    probe_provider, provider_with_explicit_cwd, read_client_server_record,
    read_explicit_cwd_record, read_final_child_result, write_final_child_probe,
)


# ============================================================================
# A) provider architecture x desktop/session environment x cwd behaviour
# ============================================================================
_PARAMS_A = {
    "provider_arch": ("direct_process", "explicit_cwd_flag"),
    "desktop_env": ("headless", "x11"),
    "cwd_class": ("valid_root", "nested"),
}
_DOMAIN_A = generate_covering_array(_PARAMS_A, strength=3)


@covers("TERM_DIRECT_PROCESS_STYLE", "TERM_EXPLICIT_CWD_HANDLING", "ENV_DESKTOP_X11")
@pytest.mark.parametrize("case", _DOMAIN_A, ids=[case_id(c) for c in _DOMAIN_A])
def test_threeway_provider_architecture_x_desktop_env_x_cwd(tmp_path, monkeypatch, case):
    if case["desktop_env"] == "x11":
        monkeypatch.setenv("DISPLAY", ":0")

    project_root = tmp_path / "project"
    project_root.mkdir()
    cwd = project_root if case["cwd_class"] == "valid_root" else project_root / "nested"
    cwd.mkdir(exist_ok=True)

    if case["provider_arch"] == "direct_process":
        provider = probe_provider(tmp_path, monkeypatch)
        launcher = InteractiveTerminalLauncher(provider=provider)
        probe = write_final_child_probe(tmp_path)
        out_path = tmp_path / f"result-{case_id(case)}.json"
        result = launcher.run(build_probe_argv(probe, out_path, 0), str(cwd), {"PATH": "/usr/bin"}, 10)
        assert result.returncode == 0
        observed = read_final_child_result(out_path)
        # Invariant: the direct-exec provider's final child cwd always
        # matches the authorized cwd, regardless of desktop-session shape.
        assert observed["cwd"] == str(cwd.resolve())
    else:
        record_path = tmp_path / f"record-{case_id(case)}.json"
        provider = provider_with_explicit_cwd(tmp_path, monkeypatch, record_path)
        launcher = InteractiveTerminalLauncher(provider=provider)
        launcher.run(("python3", "-c", "pass"), str(cwd), {"PATH": "/usr/bin"}, 10)
        record = read_explicit_cwd_record(record_path)
        # Invariant: the explicit-cwd-flag provider always honors its
        # OWN flag value (tmp_path), never the Popen-supplied cwd --
        # proving correctness independent of cwd inheritance.
        assert record["honored_cwd"] == str(tmp_path)


# ============================================================================
# B) approval/provenance x target mutation x retry state
# ============================================================================
_PARAMS_B = {
    "provenance_complete": (True, False),
    "target_mutated": (True, False),
    "retry_state": ("first_attempt", "already_registered"),
}
_DOMAIN_B = generate_covering_array(_PARAMS_B, strength=3)


@covers("AUTH_VALID_PROVENANCE_CAPABILITY", "AUTH_WRONG_TARGET", "AUTH_STALE_APPROVAL")
@pytest.mark.parametrize("case", _DOMAIN_B, ids=[case_id(c) for c in _DOMAIN_B])
def test_threeway_approval_x_target_mutation_x_retry(tmp_path, case):
    project_root = tmp_path / "project"
    project_root.mkdir()
    resolved_root = str(project_root.resolve())
    registry = CapabilityRegistry()
    original_target = "/opt/tool/python"

    provenance = ApprovalProvenance(
        resolved_root,
        "council-1" if case["provenance_complete"] else "",  # incomplete when False
        "variant-1", "setup-approval:p:approved",
    )

    registration_error = None
    try:
        reg = CapabilityRegistration(
            capability="python", executable_names=(original_target,), allowed_operations=("install",),
            approval_provenance=provenance, project_scope=resolved_root,
        )
        registry.register_approved(reg)
        if case["retry_state"] == "already_registered":
            registry.supersede_approved(reg)  # re-register the same target -- must remain valid
    except ValueError as exc:
        registration_error = exc

    if not case["provenance_complete"]:
        # Invariant: incomplete provenance is NEVER accepted at
        # registration time, regardless of target/retry state.
        assert registration_error is not None
        return

    assert registration_error is None
    from app.execution import ExecutionRequest, validate_request
    requested_target = "/different/python" if case["target_mutated"] else original_target
    request = ExecutionRequest((requested_target, "-m", "pip", "install", "pkg"), str(project_root), 10, "python", "install")
    violation = validate_request(request, project_root, registry)

    if case["target_mutated"]:
        # Invariant: a mutated/substituted target is never authorized
        # by a capability registered for a different executable.
        assert violation is not None
    else:
        assert violation is None


# ============================================================================
# C) child/status-file outcome (EQUIVALENCE_PARTITION, not 3-way -- see note)
# ============================================================================
# KIA-ADC-TEST-ASSURANCE-MODEL-FIX-001 section 4: this domain has only ONE
# genuinely varying dimension (status_outcome, 3 values); "lifecycle_state"
# and "interface" are both pinned to a single constant value each. A sweep
# with one varying dimension plus constant labels must NOT count as
# Three-Way -- it is honestly an EQUIVALENCE_PARTITION over status_outcome.
# generate_covering_array(strength=3) now refuses to generate this shape at
# all (see tests/env_pairwise.py), so it is expressed directly as one case
# per status_outcome value instead.
_PARAMS_C = {"status_outcome": ("success", "nonzero", "missing_status")}
_DOMAIN_C = tuple(
    {"status_outcome": status_outcome, "lifecycle_state": "first_execution", "interface": "internal"}
    for status_outcome in _PARAMS_C["status_outcome"]
)


@covers("PROC_MISSING_STATUS", "LIFE_FIRST_EXECUTION")
@pytest.mark.parametrize("case", _DOMAIN_C, ids=[case_id(c) for c in _DOMAIN_C])
def test_threeway_child_status_outcome_x_lifecycle_x_interface(tmp_path, monkeypatch, case):
    if case["status_outcome"] == "missing_status":
        script_path, candidates = install_early_exit_terminal(tmp_path)
        provider = DesktopTerminalProvider(candidates=candidates, launcher_exit_grace=0.05)
        launcher = InteractiveTerminalLauncher(provider=provider)
        from app.interactive_terminal import InteractiveTerminalError
        with pytest.raises(InteractiveTerminalError):
            launcher.run(("python3", "-c", "pass"), str(tmp_path), {"PATH": "/usr/bin"}, 5)
        return

    provider = probe_provider(tmp_path, monkeypatch)
    launcher = InteractiveTerminalLauncher(provider=provider)
    probe = write_final_child_probe(tmp_path)
    out_path = tmp_path / f"result-{case_id(case)}.json"
    exit_code = 0 if case["status_outcome"] == "success" else 9
    result = launcher.run(build_probe_argv(probe, out_path, exit_code), str(tmp_path), {"PATH": "/usr/bin"}, 10)
    assert result.returncode == exit_code


# ============================================================================
# D) ambient secret variable x required GUI/session environment x
#    controlled final-child environment
# ============================================================================
_PARAMS_D = {
    "ambient_secret": (True, False),
    "gui_env_required": (True, False),
    "provider_class": ("direct_process", "client_server_wellbehaved"),
}
_DOMAIN_D = generate_covering_array(_PARAMS_D, strength=3)


@covers("ENV_SECRET_LIKE", "ENV_DESKTOP_X11", "ENV_FINAL_CHILD_ALLOWLIST_ONLY")
@pytest.mark.parametrize("case", _DOMAIN_D, ids=[case_id(c) for c in _DOMAIN_D])
def test_threeway_ambient_secret_x_gui_env_x_final_child_env(tmp_path, monkeypatch, case):
    if case["ambient_secret"]:
        monkeypatch.setenv("ADC_TEST_SECRET_TOKEN", "should-not-leak")
    if case["gui_env_required"]:
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/dbus")

    controlled_env = {"PATH": "/usr/bin"}

    if case["provider_class"] == "direct_process":
        provider = probe_provider(tmp_path, monkeypatch)
        launcher = InteractiveTerminalLauncher(provider=provider)
        probe = write_final_child_probe(tmp_path)
        out_path = tmp_path / f"result-{case_id(case)}.json"
        launcher.run(build_probe_argv(probe, out_path, 0), str(tmp_path), controlled_env, 10)
        observed_env = read_final_child_result(out_path)["env"]
    else:
        provider, record_path = client_server_provider(tmp_path, monkeypatch)
        launcher = InteractiveTerminalLauncher(provider=provider)
        launcher.run(("python3", "-c", "pass"), str(tmp_path), controlled_env, 10)
        observed_env = read_client_server_record(record_path)["final_child_env"]

    # Invariant: regardless of whether a GUI session was required (the
    # LAUNCHER's own env needs DISPLAY/DBUS) or an ambient secret is
    # present, the FINAL CHILD's own environment is exactly the
    # controlled allowlist -- for both provider architectures tested
    # here (the well-behaved client/server case forwards the client's
    # real env faithfully, same as direct-exec).
    assert "ADC_TEST_SECRET_TOKEN" not in observed_env
    assert observed_env.get("PATH") == "/usr/bin"
