"""CLAUDE-E2E-003E Part 8 (negative security cases) and Part 6 (project
scope isolation) for the new executable-pinning mechanism.

Each test below drives the real, unmodified CapabilityRegistry /
execute_controlled / validate_request boundary (never a fake registry)
so a passing test is evidence about the real security boundary itself,
not about a stand-in for it. A fresh CapabilityRegistry() per test
keeps these fully isolated from the process-wide
DEFAULT_CAPABILITY_REGISTRY the subsystem/system tests populate.
"""
from __future__ import annotations

import os
import subprocess
import venv

import pytest

import app.execution as execution_module
from app.execution import (
    ApprovalProvenance,
    CapabilityRegistration,
    CapabilityRegistry,
    ExecutionRequest,
    execute_controlled,
    register_setup_step_targets,
    validate_request,
)
from app.requirement_model import SetupEffect, SetupPlan, SetupStep


def _venv_python(tmp_path, name):
    d = tmp_path / name
    venv.EnvBuilder(with_pip=True, clear=True).create(d)
    return str(d / "bin" / "python")


def _step(target_executable, is_approved=True, **overrides):
    defaults = dict(
        id="step-1", requirement_id="req-1", action="install",
        install_method="pip install requests", package="requests",
        is_approved=is_approved, setup_effect=SetupEffect.PYTHON_PACKAGE_INSTALL,
        target_executable=target_executable,
    )
    defaults.update(overrides)
    return SetupStep(**defaults)


def _plan(steps, project_id="proj-neg", status="approved"):
    return SetupPlan(
        id="plan-neg", project_id=project_id, steps=tuple(steps),
        requires_user_approval=True, status=status,
    )


def _install_request(target, project_root):
    return ExecutionRequest(
        args=(target, "-m", "pip", "install", "iniconfig"),
        cwd=str(project_root), timeout=60, tool_name="python",
        operation_type="install",
    )


class TestUnregisteredTargetFailsClosed:
    """Case 1: a target that was never registered for this project
    scope, and that PATH does not independently resolve, is rejected
    before any subprocess runs."""

    def test_unregistered_target_is_rejected(self, tmp_path, monkeypatch):
        registry = CapabilityRegistry()
        target_a = _venv_python(tmp_path, "toolchain-a")
        project_root = tmp_path / "project"
        project_root.mkdir()
        monkeypatch.setenv("PATH", "/nonexistent-bin-only")

        request = _install_request(target_a, project_root)
        with pytest.raises(ValueError):
            execute_controlled(request, project_root, capability_registry=registry)


class TestDifferentExecutableTargetBRejected:
    """Case 2: Target A is registered; a request naming Target B (a
    different, real, isolated interpreter) is rejected even though
    Target B is a perfectly valid Python executable in its own right."""

    def test_target_b_is_rejected_when_only_target_a_is_registered(self, tmp_path):
        registry = CapabilityRegistry()
        target_a = _venv_python(tmp_path, "toolchain-a")
        target_b = _venv_python(tmp_path, "toolchain-b")
        project_root = tmp_path / "project"
        project_root.mkdir()
        plan = _plan([_step(target_a)])
        register_setup_step_targets(
            plan, project_root,
            engineering_council_ref="council-1", chairman_approval_ref="variant-1",
            human_approval_ref="setup-approval:plan-neg:approved",
            capability_registry=registry,
        )

        request = _install_request(target_b, project_root)
        with pytest.raises(ValueError, match="does not match capability"):
            execute_controlled(request, project_root, capability_registry=registry)


class TestCrossProjectApprovalReuseRejected:
    """Case 3 / Part 6: a capability registered for Project A's scope
    must not authorize execution for Project B, even when Project B's
    request names the exact same physical executable path Project A
    was approved for."""

    def test_project_b_cannot_reuse_project_a_registration(self, tmp_path, monkeypatch):
        registry = CapabilityRegistry()
        target_a = _venv_python(tmp_path, "toolchain-a")
        project_a = tmp_path / "project-a"
        project_b = tmp_path / "project-b"
        project_a.mkdir()
        project_b.mkdir()
        monkeypatch.setenv("PATH", "/nonexistent-bin-only")

        plan = _plan([_step(target_a)], project_id="proj-a")
        register_setup_step_targets(
            plan, project_a,
            engineering_council_ref="council-1", chairman_approval_ref="variant-1",
            human_approval_ref="setup-approval:plan-neg:approved",
            capability_registry=registry,
        )

        assert registry.get("python", project_a) is not None
        assert registry.get("python", project_b) is None

        request = _install_request(target_a, project_b)
        with pytest.raises(ValueError):
            execute_controlled(request, project_b, capability_registry=registry)


class TestMissingHumanApprovalNeverRegisters:
    """Case 4: a plan that has not reached plan-level "approved" status
    must never be registered, even if council references are supplied
    (mirroring how execute_approved_setup_and_development gates its own
    call to register_setup_step_targets on plan.status)."""

    def test_pending_approval_plan_can_still_be_registered_by_a_misusing_caller(self, tmp_path):
        """register_setup_step_targets() itself only trusts its caller
        to have already checked plan-level approval (documented, not
        re-derived here) -- so this test documents the real contract:
        the actual approval gate lives in
        ProjectSetupApplicationService.execute_approved_setup_and_development,
        not in this lower-level function. A pending_approval plan whose
        individual steps were never marked is_approved (the real,
        pre-existing SetupApproval.approve() invariant) is still
        rejected by the per-step is_approved guard below."""
        registry = CapabilityRegistry()
        target_a = _venv_python(tmp_path, "toolchain-a")
        project_root = tmp_path / "project"
        project_root.mkdir()
        plan = _plan([_step(target_a, is_approved=False)], status="pending_approval")

        registered = register_setup_step_targets(
            plan, project_root,
            engineering_council_ref="council-1", chairman_approval_ref="variant-1",
            human_approval_ref="setup-approval:plan-neg:approved",
            capability_registry=registry,
        )

        assert registered == ()
        assert registry.get("python", project_root) is None


class TestUnapprovedStepNeverRegistered:
    """Case 8: even within a plan whose overall status is "approved",
    an individual step that is not itself is_approved is never
    authorized. Today's only production path to an approved plan
    (SetupApproval.approve()) always sets is_approved=True uniformly,
    so this scenario cannot arise from real approval flow -- this test
    covers the defensive guard directly, for a hand-built or future
    partial-approval plan shape."""

    def test_step_marked_not_approved_is_skipped_even_in_an_approved_plan(self, tmp_path):
        registry = CapabilityRegistry()
        target_a = _venv_python(tmp_path, "toolchain-a")
        project_root = tmp_path / "project"
        project_root.mkdir()
        plan = _plan([_step(target_a, is_approved=False)], status="approved")

        registered = register_setup_step_targets(
            plan, project_root,
            engineering_council_ref="council-1", chairman_approval_ref="variant-1",
            human_approval_ref="setup-approval:plan-neg:approved",
            capability_registry=registry,
        )

        assert registered == ()
        assert registry.get("python", project_root) is None


class TestForgedProvenanceRejectedAtTheRegistryItself:
    """Case 5: even bypassing register_setup_step_targets entirely and
    calling CapabilityRegistry.register_approved() directly with a
    provenance whose project_intelligence_ref does not match the
    registration's own project_scope (a forged/mismatched provenance),
    the existing, unmodified registry rejects it."""

    def test_mismatched_project_intelligence_ref_is_rejected(self, tmp_path):
        registry = CapabilityRegistry()
        project_root = tmp_path / "project"
        project_root.mkdir()
        other_dir = tmp_path / "somewhere-else"
        other_dir.mkdir()

        provenance = ApprovalProvenance(
            project_intelligence_ref=str(other_dir),
            engineering_council_ref="council-1",
            chairman_approval_ref="variant-1",
            human_approval_ref="setup-approval:plan-neg:approved",
        )
        registration = CapabilityRegistration(
            capability="python", executable_names=("/opt/toolchain/bin/python",),
            allowed_operations=("install", "verification"),
            approval_provenance=provenance, project_scope=str(project_root),
        )

        with pytest.raises(ValueError, match="Project scope does not match"):
            registry.register_approved(registration)


class TestPathIdentityIsNotContentPinned:
    """Case 6 (TOCTOU / executable-replacement): this project's chosen
    security model pins an absolute PATH STRING as the executable
    identity, not the underlying binary's content. This test honestly
    documents that residual gap rather than silently leaving it
    unproven: replacing the file at an already-registered path with a
    different, unrelated script is NOT detected by
    execute_controlled/validate_request, because path identity alone is
    what capability validation checks. This is a known, accepted
    architectural limitation (see the CLAUDE-E2E-003E report's security
    model discussion), not a claim that TOCTOU protection exists.
    """

    def test_replacing_the_registered_executable_is_not_detected(self, tmp_path):
        registry = CapabilityRegistry()
        target_dir = tmp_path / "toolchain-a" / "bin"
        target_dir.mkdir(parents=True)
        target_path = target_dir / "python"
        target_path.write_text("#!/bin/sh\necho original\n")
        target_path.chmod(0o755)

        project_root = tmp_path / "project"
        project_root.mkdir()
        plan = _plan([_step(str(target_path))])
        register_setup_step_targets(
            plan, project_root,
            engineering_council_ref="council-1", chairman_approval_ref="variant-1",
            human_approval_ref="setup-approval:plan-neg:approved",
            capability_registry=registry,
        )

        # --- Simulated compromise: same path, swapped-in content ---
        target_path.write_text("#!/bin/sh\necho swapped\n")
        target_path.chmod(0o755)

        request = ExecutionRequest(
            args=(str(target_path),), cwd=str(project_root), timeout=10,
            tool_name="python", operation_type="install",
        )
        # validate_request raises nothing: the path string still
        # matches the registered identity. This is the documented gap,
        # not a security guarantee.
        violation = validate_request(request, project_root, capability_registry=registry)
        assert violation is None


class TestExecutionCountGuarantees:
    """Part 9: exactly-once execution against the approved target, no
    duplicate/pre-validation subprocess call, no fallback execution
    against Target B, and no headless retry after a denied target --
    proven by counting real subprocess.run invocations through the
    real execute_controlled boundary, never a fake stand-in for it."""

    def test_approved_target_executes_exactly_once(self, tmp_path, monkeypatch):
        registry = CapabilityRegistry()
        target_a = _venv_python(tmp_path, "toolchain-a")
        project_root = tmp_path / "project"
        project_root.mkdir()
        plan = _plan([_step(target_a)])
        register_setup_step_targets(
            plan, project_root,
            engineering_council_ref="council-1", chairman_approval_ref="variant-1",
            human_approval_ref="setup-approval:plan-neg:approved",
            capability_registry=registry,
        )

        calls = []
        real_run = subprocess.run

        def counting_run(args, **kwargs):
            calls.append(list(args))
            return real_run(args, **kwargs)

        monkeypatch.setattr(execution_module.subprocess, "run", counting_run)

        request = ExecutionRequest(
            args=(target_a, "--version"), cwd=str(project_root), timeout=10,
            tool_name="python", operation_type="install",
        )
        result = execute_controlled(request, project_root, capability_registry=registry)

        assert result.returncode == 0
        assert len(calls) == 1
        assert calls[0][0] == target_a

    def test_denied_target_b_never_reaches_a_subprocess_and_target_a_is_never_substituted(
        self, tmp_path, monkeypatch,
    ):
        registry = CapabilityRegistry()
        target_a = _venv_python(tmp_path, "toolchain-a")
        target_b = _venv_python(tmp_path, "toolchain-b")
        project_root = tmp_path / "project"
        project_root.mkdir()
        plan = _plan([_step(target_a)])
        register_setup_step_targets(
            plan, project_root,
            engineering_council_ref="council-1", chairman_approval_ref="variant-1",
            human_approval_ref="setup-approval:plan-neg:approved",
            capability_registry=registry,
        )

        calls = []
        monkeypatch.setattr(
            execution_module.subprocess, "run",
            lambda args, **kwargs: calls.append(list(args)),
        )

        request = ExecutionRequest(
            args=(target_b, "--version"), cwd=str(project_root), timeout=10,
            tool_name="python", operation_type="install",
        )
        with pytest.raises(ValueError, match="does not match capability"):
            execute_controlled(request, project_root, capability_registry=registry)

        # No subprocess call at all was made -- no fallback, no
        # silent substitution of Target A, no retry of any kind.
        assert calls == []
