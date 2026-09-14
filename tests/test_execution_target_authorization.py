"""CLAUDE-E2E-003E UNIT tests: registration validation, provenance
validation, target identity, project isolation, serialization, and
rejection paths for app.execution.register_setup_step_targets and the
WorkflowPlanStore council-reference side-channel it depends on.

Mocks/fresh, isolated in-memory instances are acceptable at this layer
(a fresh CapabilityRegistry() per test avoids any cross-test pollution
of the real global DEFAULT_CAPABILITY_REGISTRY, which subsystem/system
tests use instead).
"""
import pytest

from app.execution import (
    ApprovalProvenance,
    CapabilityRegistration,
    CapabilityRegistry,
    capability_for_setup_effect,
    register_setup_step_targets,
)
from app.requirement_model import SetupEffect, SetupPlan, SetupStep
from app.workflow_plan_store import WorkflowPlanStore, WorkflowPlanStoreError


def _step(target_executable=None, setup_effect=SetupEffect.PYTHON_PACKAGE_INSTALL, **overrides):
    defaults = dict(
        id="step-1", requirement_id="req-1", action="install",
        install_method="pip install requests", package="requests",
        is_approved=True, setup_effect=setup_effect,
        target_executable=target_executable,
    )
    defaults.update(overrides)
    return SetupStep(**defaults)


def _plan(steps, project_id="proj-unit"):
    return SetupPlan(
        id="plan-unit", project_id=project_id, steps=tuple(steps),
        requires_user_approval=True, status="approved",
    )


# ---------------------------------------------------------------------------
# capability_for_setup_effect
# ---------------------------------------------------------------------------

def test_capability_for_setup_effect_maps_python_package_install():
    assert capability_for_setup_effect(SetupEffect.PYTHON_PACKAGE_INSTALL) == "python"


def test_capability_for_setup_effect_returns_none_for_unmapped_effect():
    assert capability_for_setup_effect(SetupEffect.PROJECT_TOOL_INSTALL) is None


def test_capability_for_setup_effect_returns_none_for_none():
    assert capability_for_setup_effect(None) is None


# ---------------------------------------------------------------------------
# register_setup_step_targets — registration validation / target identity
# ---------------------------------------------------------------------------

def test_registers_one_capability_for_a_python_package_step(tmp_path):
    registry = CapabilityRegistry()
    plan = _plan([_step(target_executable="/isolated/toolchain/bin/python")])

    registered = register_setup_step_targets(
        plan, tmp_path,
        engineering_council_ref="council-1", chairman_approval_ref="variant-1",
        human_approval_ref="setup-approval:plan-unit:approved",
        capability_registry=registry,
    )

    assert len(registered) == 1
    assert registered[0].capability == "python"
    assert registered[0].executable_names == ("/isolated/toolchain/bin/python",)
    assert registered[0].project_scope == str(tmp_path.resolve())
    found = registry.get("python", tmp_path)
    assert found is not None
    assert found.executable_names == ("/isolated/toolchain/bin/python",)


def test_step_without_target_executable_is_skipped(tmp_path):
    registry = CapabilityRegistry()
    plan = _plan([_step(target_executable=None)])

    registered = register_setup_step_targets(
        plan, tmp_path,
        engineering_council_ref="council-1", chairman_approval_ref="variant-1",
        human_approval_ref="setup-approval:plan-unit:approved",
        capability_registry=registry,
    )

    assert registered == ()
    assert registry.get("python", tmp_path) is None


def test_step_with_unmapped_setup_effect_is_skipped(tmp_path):
    """A manual_review SDK/toolchain step, for example, has no
    execute_controlled capability concept at all — never guessed at."""
    registry = CapabilityRegistry()
    plan = _plan([_step(
        target_executable="/some/path", setup_effect=SetupEffect.PROJECT_TOOL_INSTALL,
    )])

    registered = register_setup_step_targets(
        plan, tmp_path,
        engineering_council_ref="council-1", chairman_approval_ref="variant-1",
        human_approval_ref="setup-approval:plan-unit:approved",
        capability_registry=registry,
    )

    assert registered == ()


def test_duplicate_capability_target_pairs_register_once(tmp_path):
    registry = CapabilityRegistry()
    plan = _plan([
        _step(id="step-a", requirement_id="req-a", target_executable="/isolated/bin/python"),
        _step(id="step-b", requirement_id="req-b", target_executable="/isolated/bin/python"),
    ])

    registered = register_setup_step_targets(
        plan, tmp_path,
        engineering_council_ref="council-1", chairman_approval_ref="variant-1",
        human_approval_ref="setup-approval:plan-unit:approved",
        capability_registry=registry,
    )

    assert len(registered) == 1


def test_registration_allows_operations_needed_by_the_executor(tmp_path):
    registry = CapabilityRegistry()
    plan = _plan([_step(target_executable="/isolated/bin/python")])

    registered = register_setup_step_targets(
        plan, tmp_path,
        engineering_council_ref="council-1", chairman_approval_ref="variant-1",
        human_approval_ref="setup-approval:plan-unit:approved",
        capability_registry=registry,
    )

    assert "install" in registered[0].allowed_operations
    assert "verification" in registered[0].allowed_operations


# ---------------------------------------------------------------------------
# register_setup_step_targets — provenance validation / rejection paths
# ---------------------------------------------------------------------------

def test_missing_chairman_approval_ref_is_rejected(tmp_path):
    """Malformed/forged/incomplete provenance must fail closed via the
    existing, unmodified CapabilityRegistry.register_approved() check —
    no softer failure mode is introduced."""
    registry = CapabilityRegistry()
    plan = _plan([_step(target_executable="/isolated/bin/python")])

    with pytest.raises(ValueError, match="provenance"):
        register_setup_step_targets(
            plan, tmp_path,
            engineering_council_ref="council-1", chairman_approval_ref="",
            human_approval_ref="setup-approval:plan-unit:approved",
            capability_registry=registry,
        )
    assert registry.get("python", tmp_path) is None


def test_missing_engineering_council_ref_is_rejected(tmp_path):
    registry = CapabilityRegistry()
    plan = _plan([_step(target_executable="/isolated/bin/python")])

    with pytest.raises(ValueError, match="provenance"):
        register_setup_step_targets(
            plan, tmp_path,
            engineering_council_ref="", chairman_approval_ref="variant-1",
            human_approval_ref="setup-approval:plan-unit:approved",
            capability_registry=registry,
        )


def test_missing_human_approval_ref_is_rejected(tmp_path):
    registry = CapabilityRegistry()
    plan = _plan([_step(target_executable="/isolated/bin/python")])

    with pytest.raises(ValueError, match="provenance"):
        register_setup_step_targets(
            plan, tmp_path,
            engineering_council_ref="council-1", chairman_approval_ref="variant-1",
            human_approval_ref="",
            capability_registry=registry,
        )


def test_conflicting_second_registration_for_same_scope_is_rejected(tmp_path):
    """Once a capability is registered for a project scope, a DIFFERENT
    registration for the same (capability, project scope) is rejected —
    the existing CapabilityRegistry.register_approved() behavior,
    unmodified, still applies through this function."""
    registry = CapabilityRegistry()
    plan_a = _plan([_step(target_executable="/isolated/bin/python")])
    register_setup_step_targets(
        plan_a, tmp_path,
        engineering_council_ref="council-1", chairman_approval_ref="variant-1",
        human_approval_ref="setup-approval:plan-unit:approved",
        capability_registry=registry,
    )

    plan_b = _plan([_step(target_executable="/a/different/python")])
    with pytest.raises(ValueError, match="already registered"):
        register_setup_step_targets(
            plan_b, tmp_path,
            engineering_council_ref="council-1", chairman_approval_ref="variant-2",
            human_approval_ref="setup-approval:plan-unit-2:approved",
            capability_registry=registry,
        )


# ---------------------------------------------------------------------------
# register_setup_step_targets — project-scope isolation
# ---------------------------------------------------------------------------

def test_registration_for_project_a_is_not_visible_to_project_b(tmp_path):
    registry = CapabilityRegistry()
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()
    plan = _plan([_step(target_executable="/opt/toolchain-a/bin/python")])

    register_setup_step_targets(
        plan, project_a,
        engineering_council_ref="council-1", chairman_approval_ref="variant-1",
        human_approval_ref="setup-approval:plan-unit:approved",
        capability_registry=registry,
    )

    assert registry.get("python", project_a) is not None
    assert registry.get("python", project_b) is None


# ---------------------------------------------------------------------------
# WorkflowPlanStore council-reference persistence (serialization)
# ---------------------------------------------------------------------------

def test_save_and_load_council_reference_round_trips(tmp_path):
    store = WorkflowPlanStore(tmp_path / "plans")
    store.save_council_reference("proj-1", "plan-1", "council-1", "variant-1")

    result = store.load_council_reference("proj-1", "plan-1")

    assert result == ("council-1", "variant-1")


def test_load_council_reference_returns_none_when_never_saved(tmp_path):
    store = WorkflowPlanStore(tmp_path / "plans")

    assert store.load_council_reference("proj-1", "plan-1") is None


def test_load_council_reference_returns_none_for_malformed_file(tmp_path):
    store = WorkflowPlanStore(tmp_path / "plans")
    directory = tmp_path / "plans" / "proj-1"
    directory.mkdir(parents=True)
    (directory / "plan-1._council_reference.json").write_text("{not-json")

    assert store.load_council_reference("proj-1", "plan-1") is None


def test_save_council_reference_rejects_empty_engineering_council_ref(tmp_path):
    store = WorkflowPlanStore(tmp_path / "plans")

    with pytest.raises(WorkflowPlanStoreError):
        store.save_council_reference("proj-1", "plan-1", "", "variant-1")


def test_save_council_reference_rejects_empty_chairman_approval_ref(tmp_path):
    store = WorkflowPlanStore(tmp_path / "plans")

    with pytest.raises(WorkflowPlanStoreError):
        store.save_council_reference("proj-1", "plan-1", "council-1", "")


def test_council_reference_is_isolated_per_plan(tmp_path):
    """Two plans in the same project must not share or overwrite each
    other's council reference."""
    store = WorkflowPlanStore(tmp_path / "plans")
    store.save_council_reference("proj-1", "plan-1", "council-1", "variant-1")
    store.save_council_reference("proj-1", "plan-2", "council-2", "variant-2")

    assert store.load_council_reference("proj-1", "plan-1") == ("council-1", "variant-1")
    assert store.load_council_reference("proj-1", "plan-2") == ("council-2", "variant-2")
