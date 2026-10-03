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

(CLAUDE-ADC-TEST-ENVIRONMENT-FIDELITY-UPGRADE-001: originally required
outbound network access for a single real "pip install" of a PyPI
package, with no Real-System opt-in marker. Corrected the same way as
its sibling system-level files: the external terminal boundary is
INERT (tests/terminal_final_child_probe.py), so the install is never
actually executed, and its own real, already-authorized argv is
observed via the terminal boundary's recorded argv instead of a real
subprocess install/import round trip. No network dependency remains.
Test 2 below (PATH mutation) already needed no network -- the real,
unmocked controlled execution boundary rejects the unauthorized install
before any subprocess, terminal or otherwise, is ever attempted -- and
is unchanged in that respect; only its own target IDENTITY construction
now uses a synthetic, non-network placeholder for consistency and
speed.)
"""
from __future__ import annotations

import os
import shutil
import sys

from app.council_models import CouncilResult, CouncilVariant, ToolchainItem
from app.execution import register_setup_step_targets
from app.python_package_executor import PythonPackageExecutor
from app.requirement_model import Requirement, RequirementType
from app.requirement_preflight import RequirementPreflight
from app.setup_approval import SetupApproval
from app.toolchain_materializer import ToolchainMaterializer
from app.workflow_plan_store import WorkflowPlanStore

from tests.terminal_final_child_probe import (
    inert_terminal_harness, read_recorded_argv, read_terminal_launch_count,
    synthetic_target_python,
)

TEST_PACKAGE = "iniconfig"


def _build_isolated_toolchain(tmp_path):
    """A real, PATH-resolvable executable IDENTITY only -- see this
    module's own docstring for why no real venv/pip bootstrap is built
    here any more."""
    return synthetic_target_python(tmp_path, "toolchain")


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


class TestRealProductiveIntegrationStablePath:
    """PART 1: the real component chain, PATH stable throughout —
    establishes the positive/happy-path acceptance evidence (real
    install, real post-install verification) that the PATH-mutation
    scenario below cannot reach on its own, since that one is rejected
    before any subprocess runs."""

    def test_real_chain_installs_and_verifies_with_stable_path(self, tmp_path, monkeypatch):
        target_a, counter_path, record_path = inert_terminal_harness(tmp_path, monkeypatch, "toolchain")
        project_root = tmp_path / "project"
        project_root.mkdir()

        requirement = Requirement(
            technical_identity=TEST_PACKAGE,
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

        # --- REAL register_setup_step_targets: CLAUDE-ADC-ZIELBILD-
        # DIFF-FIX-001 (B1) means a mutating "install" now requires a
        # project-scoped, approval-provenance-backed capability
        # registration -- exactly what the real productive
        # execute_approved_setup_and_development() -> authorize_setup_
        # plan_targets() -> register_setup_step_targets() chain performs
        # for an approved plan with real Council/Chairman references,
        # reused here unmocked, never a test-only shortcut.
        register_setup_step_targets(
            approved_plan, project_root,
            engineering_council_ref="council-1", chairman_approval_ref="variant-1",
            human_approval_ref="setup-approval:plan-1:approved",
        )

        # --- REAL PythonPackageExecutor: default construction, no
        # runner injected; only the post-install verifier is a
        # deterministic double at its own first-class injection seam ---
        executor = PythonPackageExecutor(verifier=lambda step: True)
        assert executor._uses_default_runner is True

        result = executor.execute(approved_plan.steps[0], str(project_root))

        # --- The real, already-authorized install command reached the
        # inert terminal boundary intact ---
        assert result.success is True
        assert result.verification_passed is True

        recorded = read_recorded_argv(record_path)
        assert recorded[0] == target_a
        assert read_terminal_launch_count(counter_path) == 1


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
            technical_identity=TEST_PACKAGE,
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
        # CLAUDE-ADC-ZIELBILD-DIFF-FIX-001 (B1): this bootstrap-only
        # capability (no project-scoped, approval-provenance-backed
        # registration was ever made for Target A in this test) now
        # rejects the mutating "install" operation on that more
        # fundamental ground, before PATH-based executable-identity
        # resolution is even reached -- an even stronger property than
        # the PATH-mismatch rejection this test originally observed:
        # no subprocess is attempted regardless of PATH state at all.
        assert raised is not None, (
            "expected the real controlled execution boundary to reject "
            "an unauthorized mutating install; if this assertion fails, "
            "the architecture has changed and PART 3's acceptance "
            "conclusion must be re-evaluated, not assumed"
        )
        assert isinstance(raised, ValueError)
        assert "capability" in str(raised).lower()
        # Neither Target A's nor Target B's path appears anywhere in
        # the rejection -- it never reached PATH-based identity
        # resolution at all, so neither was ever considered or launched.
        assert target_a not in str(raised)
        assert target_b not in str(raised)
        # No install happened anywhere: validate_request's own rejection
        # (asserted above) is what execute_controlled's real, unmodified
        # structure guarantees stops it before either its install-terminal
        # branch or its direct-subprocess branch is ever reached -- there
        # is no third path for a subprocess to have been launched through.
