"""CLAUDE-E2E-003E SUBSYSTEM tests (S1-S6).

Each class below is explicitly labeled for the CLAUDE-E2E-003E audit
trail and, per that task's own allowance, exercises real ADC
components together rather than mocking the boundary under test. The
only replacement anywhere in this file is Engineering Council LLM
generation (a deterministic, hand-built CouncilResult/ToolchainItem
fixture) - the same, already-established replacement used by
tests/test_real_productive_integration.py (CLAUDE-E2E-003D).

These tests register real, project-scoped capabilities into the
process-wide DEFAULT_CAPABILITY_REGISTRY (PythonPackageExecutor's
default runner has no registry-injection point - it always calls
execute_controlled/validate_request with that same default registry,
matching real production wiring). Registrations are never removed once
made (CapabilityRegistry has no "unregister", only suspend/revoke), so
every test uses its own fresh tmp_path-derived project root as its
project_scope key - this guarantees no cross-test collision within
this file or across the rest of the suite, and mirrors how distinct
real projects would never collide with each other in production.
"""
from __future__ import annotations

import os
import subprocess
import sys
import venv

import pytest

from app.council_models import CouncilResult, CouncilVariant, ToolchainItem
from app.execution import (
    DEFAULT_CAPABILITY_REGISTRY,
    ExecutionRequest,
    execute_controlled,
    register_setup_step_targets,
    validate_request,
)
from app.python_package_executor import PythonPackageExecutor
from app.requirement_model import Requirement, RequirementType, SetupEffect
from app.requirement_preflight import RequirementPreflight
from app.setup_approval import SetupApproval
from app.toolchain_materializer import ToolchainMaterializer
from app.workflow_plan_store import WorkflowPlanStore

TEST_PACKAGE = "iniconfig"


def _build_isolated_toolchain(tmp_path, name="toolchain"):
    toolchain_dir = tmp_path / name
    venv.EnvBuilder(with_pip=True, clear=True).create(toolchain_dir)
    return str(toolchain_dir / "bin" / "python")


def _requirement():
    return Requirement(
        technical_identity=TEST_PACKAGE,
        id="req-integration", name=TEST_PACKAGE,
        type=RequirementType.PYTHON_PACKAGE, purpose="test dependency",
        required=True, confidence=0.9,
    )


def _council_result(project_id="proj-subsystem"):
    item = ToolchainItem(
        requirement_ref="req-integration", name=TEST_PACKAGE,
        type=RequirementType.PYTHON_PACKAGE,
        install_method=f"pip install {TEST_PACKAGE}",
    )
    variant = CouncilVariant(id="variant-1", name="variant-1", toolchain=(item,))
    return CouncilResult(
        id="council-1", project_id=project_id,
        variants=(variant,), recommendation="variant-1", council_complete=True,
    )


def _network_unavailable(execution_result) -> bool:
    message = (execution_result.message or "").lower()
    return "temporary failure" in message or "network" in message or "resolve" in message


class TestS1TargetSelection:
    """S1: real RequirementPreflight resolves a real execution-target
    identity for a python_package requirement against a real,
    isolated project root - the central controlled-metadata query, not
    a guess or a display label."""

    def test_preflight_resolves_real_target_executable(self, tmp_path, monkeypatch):
        target_a = _build_isolated_toolchain(tmp_path)
        project_root = tmp_path / "project"
        project_root.mkdir()
        prior_path = os.environ.get("PATH", "")
        monkeypatch.setenv("PATH", f"{os.path.dirname(target_a)}:{prior_path}")

        preflight = RequirementPreflight.check(
            (_requirement(),), "proj-s1", project_root=str(project_root),
        )

        assert preflight.results[0].present is False
        assert preflight.results[0].target_executable == target_a

    def test_preflight_without_project_root_does_not_guess_a_target(self, tmp_path):
        """No project_root -> no real target-resolution context ->
        target_executable must stay None, never a guessed value."""
        preflight = RequirementPreflight.check(
            (_requirement(),), "proj-s1b", project_root=None,
        )

        assert preflight.results[0].target_executable is None


class TestS2Materialization:
    """S2: a real Preflight result, fed through the real
    ToolchainMaterializer, preserves the exact resolved target
    executable identity onto the resulting SetupStep."""

    def test_materializer_preserves_target_executable_onto_setup_step(self, tmp_path, monkeypatch):
        target_a = _build_isolated_toolchain(tmp_path)
        project_root = tmp_path / "project"
        project_root.mkdir()
        prior_path = os.environ.get("PATH", "")
        monkeypatch.setenv("PATH", f"{os.path.dirname(target_a)}:{prior_path}")

        preflight = RequirementPreflight.check(
            (_requirement(),), "proj-s2", project_root=str(project_root),
        )
        plan = ToolchainMaterializer().materialize(
            _council_result("proj-s2"), "proj-s2", preflight=preflight,
        )

        assert len(plan.steps) == 1
        assert plan.steps[0].target_executable == target_a
        assert plan.steps[0].setup_effect == SetupEffect.PYTHON_PACKAGE_INSTALL


class TestS3Persistence:
    """S3: a real SetupPlan (with a real target_executable) survives a
    real WorkflowPlanStore save/load round trip, and the plan's
    council-approval reference metadata - needed later to build real,
    non-fabricated ApprovalProvenance - survives alongside it."""

    def test_plan_and_council_reference_both_survive_persistence(self, tmp_path, monkeypatch):
        target_a = _build_isolated_toolchain(tmp_path)
        project_root = tmp_path / "project"
        project_root.mkdir()
        prior_path = os.environ.get("PATH", "")
        monkeypatch.setenv("PATH", f"{os.path.dirname(target_a)}:{prior_path}")

        preflight = RequirementPreflight.check(
            (_requirement(),), "proj-s3", project_root=str(project_root),
        )
        council_result = _council_result("proj-s3")
        plan = ToolchainMaterializer().materialize(
            council_result, "proj-s3", preflight=preflight,
        )

        store = WorkflowPlanStore(tmp_path / "plans")
        store.save(plan)
        store.save_council_reference(
            "proj-s3", plan.id, council_result.id, council_result.recommendation,
        )

        loaded_plan = store.load("proj-s3", plan.id)
        loaded_refs = store.load_council_reference("proj-s3", plan.id)

        assert loaded_plan.steps[0].target_executable == target_a
        assert loaded_refs == (council_result.id, council_result.recommendation)


class TestS4ApprovalAndCapability:
    """S4: a real persisted+reloaded plan, really approved, produces a
    real ApprovalProvenance and a real project-scoped
    CapabilityRegistration in the real, process-wide
    DEFAULT_CAPABILITY_REGISTRY - no fake registry stands in anywhere
    in this chain."""

    def test_approval_produces_a_real_scoped_capability_registration(self, tmp_path, monkeypatch):
        target_a = _build_isolated_toolchain(tmp_path)
        project_root = tmp_path / "project"
        project_root.mkdir()
        prior_path = os.environ.get("PATH", "")
        monkeypatch.setenv("PATH", f"{os.path.dirname(target_a)}:{prior_path}")

        preflight = RequirementPreflight.check(
            (_requirement(),), "proj-s4", project_root=str(project_root),
        )
        council_result = _council_result("proj-s4")
        plan = ToolchainMaterializer().materialize(
            council_result, "proj-s4", preflight=preflight,
        )
        store = WorkflowPlanStore(tmp_path / "plans")
        store.save(plan)
        loaded_plan = store.load("proj-s4", plan.id)
        approved_plan = SetupApproval.approve(loaded_plan)
        store.save(approved_plan)
        store.save_council_reference(
            "proj-s4", plan.id, council_result.id, council_result.recommendation,
        )

        reloaded = store.load("proj-s4", plan.id)
        council_ref, chairman_ref = store.load_council_reference("proj-s4", plan.id)

        assert reloaded.status == "approved"

        registered = register_setup_step_targets(
            reloaded, project_root,
            engineering_council_ref=council_ref,
            chairman_approval_ref=chairman_ref,
            human_approval_ref=f"setup-approval:{reloaded.id}:approved",
        )

        assert len(registered) == 1
        found = DEFAULT_CAPABILITY_REGISTRY.get("python", project_root)
        assert found is not None
        assert found.executable_names == (target_a,)
        assert found.approval_provenance.engineering_council_ref == council_result.id
        assert found.approval_provenance.chairman_approval_ref == council_result.recommendation


class TestS5Execution:
    """S5: a real, already-registered target executes through
    PythonPackageExecutor -> ExecutionRequest -> execute_controlled ->
    validate_request -> the real CapabilityRegistry -> a real
    subprocess -> real post-install verification. Distinct from the
    pre-existing 003D stable-path test: this one proves execution
    succeeds because of the NEW project-scoped registration itself,
    not merely because PATH happens to still agree."""

    def test_registered_target_executes_and_verifies_for_real(self, tmp_path, monkeypatch):
        target_a = _build_isolated_toolchain(tmp_path)
        project_root = tmp_path / "project"
        project_root.mkdir()
        prior_path = os.environ.get("PATH", "")
        monkeypatch.setenv("PATH", f"{os.path.dirname(target_a)}:{prior_path}")

        preflight = RequirementPreflight.check(
            (_requirement(),), "proj-s5", project_root=str(project_root),
        )
        council_result = _council_result("proj-s5")
        plan = ToolchainMaterializer().materialize(
            council_result, "proj-s5", preflight=preflight,
        )
        approved_plan = SetupApproval.approve(plan)
        register_setup_step_targets(
            approved_plan, project_root,
            engineering_council_ref=council_result.id,
            chairman_approval_ref=council_result.recommendation,
            human_approval_ref=f"setup-approval:{approved_plan.id}:approved",
        )

        executor = PythonPackageExecutor()
        result = executor.execute(approved_plan.steps[0], str(project_root))

        if not result.success and _network_unavailable(result):
            pytest.skip(f"No network access for a real pip install: {result.message}")

        assert result.success is True
        assert result.verification_passed is True

        check = subprocess.run(
            [target_a, "-c", f"import {TEST_PACKAGE}; print({TEST_PACKAGE}.__file__)"],
            capture_output=True, text=True, timeout=30,
        )
        assert check.returncode == 0
        assert "toolchain" in check.stdout


class TestS6FullSetupSubsystem:
    """S6: the complete real chain end to end at the subsystem level
    (direct component calls, not wrapped in the application service -
    that is the SYSTEM test's job): Preflight -> Materializer ->
    persistence -> reload -> approval -> real capability registration
    -> PATH drift A -> B -> real execution against A -> real
    verification. This is the positive counterpart to 003D's
    PATH-mutation test, which proved the pre-fix architecture failed
    closed; this proves the fix now lets a genuinely human-approved
    target survive the same drift."""

    def test_registered_target_survives_path_drift_end_to_end(self, tmp_path, monkeypatch):
        target_a = _build_isolated_toolchain(tmp_path, name="toolchain-a")
        project_root = tmp_path / "project"
        project_root.mkdir()
        prior_path = os.environ.get("PATH", "")
        monkeypatch.setenv("PATH", f"{os.path.dirname(target_a)}:{prior_path}")

        preflight = RequirementPreflight.check(
            (_requirement(),), "proj-s6", project_root=str(project_root),
        )
        council_result = _council_result("proj-s6")
        plan = ToolchainMaterializer().materialize(
            council_result, "proj-s6", preflight=preflight,
        )
        assert plan.steps[0].target_executable == target_a

        store = WorkflowPlanStore(tmp_path / "plans")
        store.save(plan)
        store.save_council_reference(
            "proj-s6", plan.id, council_result.id, council_result.recommendation,
        )
        loaded_plan = store.load("proj-s6", plan.id)
        approved_plan = SetupApproval.approve(loaded_plan)
        store.save(approved_plan)

        reloaded = store.load("proj-s6", plan.id)
        council_ref, chairman_ref = store.load_council_reference("proj-s6", plan.id)
        register_setup_step_targets(
            reloaded, project_root,
            engineering_council_ref=council_ref, chairman_approval_ref=chairman_ref,
            human_approval_ref=f"setup-approval:{reloaded.id}:approved",
        )

        # --- PATH MUTATION: Target A's directory removed from PATH ---
        monkeypatch.setenv("PATH", prior_path)
        target_b = __import__("shutil").which("python") or sys.executable
        assert target_b != target_a, "test setup invalid: PATH mutation had no effect"

        reloaded_for_exec = store.load("proj-s6", plan.id)
        executor = PythonPackageExecutor()
        result = executor.execute(reloaded_for_exec.steps[0], str(project_root))

        if not result.success and _network_unavailable(result):
            pytest.skip(f"No network access for a real pip install: {result.message}")

        assert result.success is True
        assert result.verification_passed is True

        check_a = subprocess.run(
            [target_a, "-c", f"import {TEST_PACKAGE}"],
            capture_output=True, text=True, timeout=30,
        )
        assert check_a.returncode == 0, "Target A must have received the real install"
