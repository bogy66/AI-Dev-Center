"""CLAUDE-E2E-003D: real productive integration acceptance.

This file exercises the actual productive ADC component chain together,
with as few internal mocks as possible, per the binding ADC test
principle this task establishes: a mock of a critical internal ADC
boundary is not sufficient as the SOLE acceptance evidence for that
boundary. The only thing replaced here is Engineering Council LLM
generation (a deterministic, hand-built CouncilResult/ToolchainItem
fixture stands in for it) — LLM nondeterminism is not the subject of
this test, and no LLM/network provider call is made anywhere in this
file.

NOT mocked, monkeypatched, or replaced anywhere below:
  RequirementPreflight, ToolchainMaterializer, WorkflowPlanStore,
  SetupApproval, PythonPackageExecutor (default, no injected runner),
  ExecutionRequest, execute_controlled, validate_request,
  CapabilityRegistry (the real DEFAULT_CAPABILITY_REGISTRY), the local
  subprocess boundary, and post-install distribution verification.

The one real, external, nondeterministic dependency this file has is
outbound network access for a single real "pip install" of a tiny,
zero-dependency, stable PyPI package (iniconfig — already an existing
transitive dependency of pytest itself, so its wheel is typically
already present in the local pip cache). If that specific install step
fails for an environment reason (no network), the affected test skips
rather than reporting a false failure; the PATH-mutation scenario
requires no network at all, since it is rejected by the controlled
execution boundary before any subprocess is ever attempted.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import venv

import pytest

from app.council_models import CouncilResult, CouncilVariant, ToolchainItem
from app.python_package_executor import PythonPackageExecutor
from app.requirement_model import Requirement, RequirementType
from app.requirement_preflight import RequirementPreflight
from app.setup_approval import SetupApproval
from app.toolchain_materializer import ToolchainMaterializer
from app.workflow_plan_store import WorkflowPlanStore

TEST_PACKAGE = "iniconfig"


def _build_isolated_toolchain(tmp_path):
    """A real, isolated venv with pip — this is Target A."""
    toolchain_dir = tmp_path / "toolchain"
    venv.EnvBuilder(with_pip=True, clear=True).create(toolchain_dir)
    return str(toolchain_dir / "bin" / "python")


def _make_deterministic_council_result(requirement_ref: str) -> CouncilResult:
    """Stand-in for Engineering Council LLM generation: a hand-built,
    fully deterministic structured fixture, not a mock of the Council
    object itself — no EngineeringCouncil instance exists in this test
    at all, real or mocked, so there is nothing Council-shaped to mock."""
    item = ToolchainItem(
        requirement_ref=requirement_ref, name=TEST_PACKAGE,
        type=RequirementType.PYTHON_PACKAGE,
        install_method=f"pip install {TEST_PACKAGE}",
    )
    variant = CouncilVariant(id="variant-1", name="variant-1", toolchain=(item,))
    return CouncilResult(
        id="council-1", project_id="proj-integration",
        variants=(variant,), recommendation="variant-1", council_complete=True,
    )


def _network_unavailable(execution_result) -> bool:
    message = (execution_result.message or "").lower()
    return "temporary failure" in message or "network" in message or "resolve" in message


class TestRealProductiveIntegrationStablePath:
    """PART 1: the real component chain, PATH stable throughout —
    establishes the positive/happy-path acceptance evidence (real
    install, real post-install verification) that the PATH-mutation
    scenario below cannot reach on its own, since that one is rejected
    before any subprocess runs."""

    def test_real_chain_installs_and_verifies_with_stable_path(self, tmp_path, monkeypatch):
        target_a = _build_isolated_toolchain(tmp_path)
        project_root = tmp_path / "project"
        project_root.mkdir()

        prior_path = os.environ.get("PATH", "")
        monkeypatch.setenv("PATH", f"{os.path.dirname(target_a)}:{prior_path}")

        requirement = Requirement(
            id="req-integration", name=TEST_PACKAGE,
            type=RequirementType.PYTHON_PACKAGE, purpose="test dependency",
            required=True, confidence=0.9,
        )

        # --- REAL RequirementPreflight ---
        preflight = RequirementPreflight.check(
            (requirement,), "proj-integration", project_root=str(project_root),
        )
        assert preflight.results[0].present is False
        assert preflight.results[0].target_executable == target_a

        # --- REAL ToolchainMaterializer, fed a deterministic (non-LLM) CouncilResult ---
        council_result = _make_deterministic_council_result(requirement.id)
        plan = ToolchainMaterializer().materialize(
            council_result, "proj-integration", preflight=preflight,
        )
        assert len(plan.steps) == 1
        assert plan.steps[0].action == "install"
        assert plan.steps[0].package == TEST_PACKAGE
        assert plan.steps[0].target_executable == target_a

        # --- REAL WorkflowPlanStore save/load ---
        store = WorkflowPlanStore(tmp_path / "plans")
        store.save(plan)
        loaded_plan = store.load("proj-integration", plan.id)
        assert loaded_plan == plan
        assert loaded_plan.steps[0].target_executable == target_a

        # --- REAL SetupApproval ---
        approved_plan = SetupApproval.approve(loaded_plan)
        assert approved_plan.status == "approved"
        assert approved_plan.steps[0].is_approved is True

        # --- REAL PythonPackageExecutor: default construction, no runner injected ---
        executor = PythonPackageExecutor()
        assert executor._uses_default_runner is True

        result = executor.execute(approved_plan.steps[0], str(project_root))

        if not result.success and _network_unavailable(result):
            pytest.skip(f"No network access for a real pip install: {result.message}")

        # --- REAL subprocess + REAL post-install distribution verification ---
        assert result.success is True
        assert result.verification_passed is True

        check = subprocess.run(
            [target_a, "-c", f"import {TEST_PACKAGE}; print({TEST_PACKAGE}.__file__)"],
            capture_output=True, text=True, timeout=30,
        )
        assert check.returncode == 0
        assert "toolchain" in check.stdout


class TestRealProductiveIntegrationPathMutation:
    """PART 2 + PART 3: Target A is selected during real Preflight, the
    plan is really persisted and reloaded, really approved, PATH is
    then mutated so a fresh python/python3 lookup resolves a different
    interpreter (Target B), and the real approved execution path is
    then run — with no prediction of the outcome, only observation.
    Requires no network: the controlled execution boundary rejects
    Target A before any subprocess (network or otherwise) is attempted.
    """

    def test_real_chain_after_path_mutation(self, tmp_path, monkeypatch):
        target_a = _build_isolated_toolchain(tmp_path)
        project_root = tmp_path / "project"
        project_root.mkdir()

        prior_path = os.environ.get("PATH", "")
        monkeypatch.setenv("PATH", f"{os.path.dirname(target_a)}:{prior_path}")

        requirement = Requirement(
            id="req-integration", name=TEST_PACKAGE,
            type=RequirementType.PYTHON_PACKAGE, purpose="test dependency",
            required=True, confidence=0.9,
        )

        # --- REAL Preflight: Target A selected while genuinely on PATH ---
        preflight = RequirementPreflight.check(
            (requirement,), "proj-integration", project_root=str(project_root),
        )
        assert preflight.results[0].target_executable == target_a

        # --- REAL Materializer ---
        council_result = _make_deterministic_council_result(requirement.id)
        plan = ToolchainMaterializer().materialize(
            council_result, "proj-integration", preflight=preflight,
        )
        assert plan.steps[0].target_executable == target_a

        # --- REAL persistence: save, then reload before approval/execution ---
        store = WorkflowPlanStore(tmp_path / "plans")
        store.save(plan)
        loaded_plan = store.load("proj-integration", plan.id)
        assert loaded_plan.steps[0].target_executable == target_a

        # --- REAL approval ---
        approved_plan = SetupApproval.approve(loaded_plan)

        # --- PATH MUTATION: Target A's directory removed from PATH ---
        monkeypatch.setenv("PATH", prior_path)
        target_b = shutil.which("python") or sys.executable
        assert target_b != target_a, (
            "test setup invalid: PATH mutation did not actually change "
            "what a fresh python lookup resolves to"
        )

        # A fresh, real, default-composed executor built AFTER the
        # mutation genuinely would resolve Target B on its own --
        # proving the mutation is real, not assumed.
        fresh_executor = PythonPackageExecutor()
        assert fresh_executor.python_executable == target_b

        # --- REAL execution attempt through the real, unmocked boundary ---
        executor = PythonPackageExecutor()
        raised = None
        result = None
        try:
            result = executor.execute(approved_plan.steps[0], str(project_root))
        except Exception as exc:  # noqa: BLE001 - recording the real, unpredicted outcome
            raised = exc

        # --- Observed, not predicted, outcome: PART 3's "B" case ---
        assert raised is not None, (
            "expected the real controlled execution boundary to reject "
            "Target A once it is no longer PATH-authorized; if this "
            "assertion fails, the architecture has changed and PART 3's "
            "acceptance conclusion must be re-evaluated, not assumed"
        )
        assert isinstance(raised, ValueError)
        assert "capability" in str(raised).lower()
        assert target_a in str(raised)
        # Target B's path must never appear anywhere in the rejection —
        # it was never substituted, never considered, never launched.
        assert target_b not in str(raised)

        # No install happened anywhere: not on Target A (rejected before
        # any subprocess), and Target B was never touched by this
        # operation at all (its own interpreter's real package state is
        # simply irrelevant here — no command naming it was ever built).
        check_a = subprocess.run(
            [target_a, "-c", f"import {TEST_PACKAGE}"],
            capture_output=True, text=True, timeout=30,
        )
        assert check_a.returncode != 0, "Target A must remain untouched: no install ran"
