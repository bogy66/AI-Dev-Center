"""Subsystem/integration test for Environment & Setup.

Boundary under test:

    Engineering Decision → Selected Toolchain
    → ToolchainMaterializer → SetupPlan

Exercises real production objects across the Selected Toolchain →
ToolchainMaterializer → SetupPlan state transition using deterministic
fixtures for upstream state (requirements, activation, preflight evidence).

No real LLM providers, no setup commands, no package installations.
"""

from app.council_models import CouncilResult, CouncilVariant, ToolchainItem
from app.requirement_model import (
    PreflightRequirementResult,
    PreflightResult,
    Requirement,
    RequirementActivation,
    RequirementType,
    SetupEffect,
)
from app.setup_planner import SetupPlanner
from app.toolchain_materializer import ToolchainMaterializer


# ---------------------------------------------------------------------------
# Deterministic fixture builders
# ---------------------------------------------------------------------------

def _requirement(req_id, req_type=RequirementType.PYTHON_PACKAGE, **kwargs):
    """Build a deterministic Requirement fixture."""
    base = {
        "id": req_id,
        "name": req_id.replace("-", " ").title(),
        "type": req_type,
        "purpose": f"purpose of {req_id}",
        "required": True,
        "confidence": 1.0,
    }
    if req_type == RequirementType.PYTHON_PACKAGE:
        base.setdefault("install_method", "pip")
    base.update(kwargs)
    accepted = {f.name for f in Requirement.__dataclass_fields__.values()}
    return Requirement(**{k: v for k, v in base.items() if k in accepted})


def _activation(req_id, active=True, blocks=True):
    return RequirementActivation(
        requirement_id=req_id, active=active,
        blocks_current_operation=blocks, reason="test",
    )


def _preflight_req(req_id, *, satisfied=False, active=True, blocks=True):
    return PreflightRequirementResult(
        requirement_id=req_id, present=satisfied, satisfied=satisfied,
        active=active, blocks_current_operation=blocks,
    )


def _preflight(requirements, activations, *, project_id="test-project",
               satisfied_ids=frozenset()):
    """Build a deterministic PreflightResult from requirements and activations."""
    preflight_results = tuple(
        _preflight_req(
            r.id,
            satisfied=r.id in satisfied_ids,
            active=a.active,
            blocks=a.blocks_current_operation,
        )
        for r, a in zip(requirements, activations)
    )
    missing = tuple(
        r for r, a in zip(requirements, activations)
        if a.active and r.id not in satisfied_ids
    )
    inactive = tuple(
        r for r, a in zip(requirements, activations)
        if not a.active
    )
    return PreflightResult(
        id=f"pre-{project_id}",
        project_id=project_id,
        overall_ready=len(missing) == 0,
        results=preflight_results,
        missing_requirements=missing,
        already_installed=tuple(
            r for r in requirements if r.id in satisfied_ids
        ),
        activations=activations,
        inactive_requirements=inactive,
        project_requirements=requirements,
    )


def _toolchain_item(req_ref, *,
                    name=None,
                    type_=RequirementType.PYTHON_PACKAGE,
                    install_method="pip",
                    state="needs_install",
                    version=None,
                    provided_by=None):
    return ToolchainItem(
        requirement_ref=req_ref,
        name=name if name is not None else req_ref.replace("-", " ").title(),
        type=type_,
        install_method=install_method,
        version=version,
        state=state,
        provided_by=provided_by,
    )


def _variant(variant_id="variant-selected", toolchain=()):
    return CouncilVariant(
        id=variant_id,
        name=variant_id.replace("-", " ").title(),
        toolchain=tuple(toolchain),
    )


def _council_result(variant, *, project_id="test-project",
                    recommendation="variant-selected"):
    return CouncilResult(
        id=f"council-{project_id}",
        project_id=project_id,
        variants=(variant,),
        recommendation=recommendation,
        council_complete=True,
    )


def _materialize(variant, preflight=None, *, project_id="test-project"):
    return ToolchainMaterializer().materialize(
        _council_result(variant, project_id=project_id),
        project_id,
        preflight=preflight,
    )


# ---------------------------------------------------------------------------
# S01 — Direct controlled setup
# ---------------------------------------------------------------------------

def test_direct_controlled_setup_produces_install_step():
    """An active, materializable requirement produces a controlled SetupStep
    and is NOT treated as provided."""
    req = _requirement("req-package", RequirementType.PYTHON_PACKAGE)
    activation = _activation(req.id)
    preflight = _preflight((req,), (activation,))
    variant = _variant(toolchain=[
        _toolchain_item(req.id, type_=RequirementType.PYTHON_PACKAGE),
    ])

    plan = _materialize(variant, preflight, project_id="proj-direct")

    assert plan.project_id == "proj-direct"
    assert plan.id == "plan-proj-direct"
    assert len(plan.steps) == 1
    step = plan.steps[0]
    assert step.requirement_id == req.id
    assert step.id == f"step-{req.id}"
    assert step.action == "install"
    assert step.package is not None
    assert step.is_approved is False
    assert step.command is None
    assert step.install_method == "pip"
    assert plan.provided_requirement_ids == ()
    assert plan.deferred_requirement_ids == ()
    assert plan.requires_user_approval is True
    assert plan.status == "pending_approval"
    assert plan.requirement_activations == (activation,)
    # No orphan references
    step_refs = {s.requirement_id for s in plan.steps}
    assert req.id in step_refs


# ---------------------------------------------------------------------------
# S02 — Already satisfied requirement
# ---------------------------------------------------------------------------

def test_already_satisfied_produces_no_step():
    """Preflight reports requirement satisfied → no SetupStep, not in
    provided_requirement_ids, not treated as missing."""
    req = _requirement("req-satisfied", RequirementType.PYTHON_PACKAGE)
    activation = _activation(req.id)
    preflight = _preflight(
        (req,), (activation,), satisfied_ids=frozenset({req.id}),
    )
    variant = _variant(toolchain=[
        _toolchain_item(req.id, type_=RequirementType.PYTHON_PACKAGE),
    ])

    plan = _materialize(variant, preflight, project_id="proj-sat")

    assert plan.project_id == "proj-sat"
    assert plan.steps == ()
    assert plan.provided_requirement_ids == ()
    # Internal consistency: no requirement appears in multiple categories
    assert req.id not in plan.provided_requirement_ids
    assert req.id not in plan.deferred_requirement_ids
    assert plan.requirement_activations == (activation,)


# ---------------------------------------------------------------------------
# S03 — Valid provided relationship
# ---------------------------------------------------------------------------

def test_valid_provided_relationship():
    """Provider A is independently materializable.  Requirement B has
    provided_by = A.  A gets a controlled step; B appears in
    provided_requirement_ids and receives no independent step."""
    provider_req = _requirement("req-provider", RequirementType.PYTHON_PACKAGE)
    dependent_req = _requirement("req-dependent", RequirementType.SDK,
                                 install_method="manual-setup")
    activations = (_activation(provider_req.id), _activation(dependent_req.id))
    preflight = _preflight(
        (provider_req, dependent_req), activations,
    )
    variant = _variant(toolchain=[
        _toolchain_item(provider_req.id, type_=RequirementType.PYTHON_PACKAGE),
        _toolchain_item(dependent_req.id, type_=RequirementType.SDK,
                        install_method="manual-setup",
                        provided_by=provider_req.id),
    ])

    plan = _materialize(variant, preflight, project_id="proj-provided")

    assert plan.project_id == "proj-provided"
    step_ids = {s.requirement_id for s in plan.steps}
    assert provider_req.id in step_ids, "Provider must produce its own step"
    assert dependent_req.id not in step_ids, (
        "Provided requirement must not produce an independent step"
    )
    provider_step = next(s for s in plan.steps if s.requirement_id == provider_req.id)
    assert provider_step.action == "install"
    assert dependent_req.id in plan.provided_requirement_ids
    # Activation preservation
    dep_act = next(a for a in plan.requirement_activations
                   if a.requirement_id == dependent_req.id)
    assert dep_act.active is True
    assert dep_act.blocks_current_operation is True
    # No duplicate responsibility
    assert len(plan.steps) == 1
    # Every step requirement_id resolves to input
    for step in plan.steps:
        assert step.requirement_id in {provider_req.id, dependent_req.id}


# ---------------------------------------------------------------------------
# S04 — Valid multi-hop provisioning
# ---------------------------------------------------------------------------

def test_valid_multi_hop_to_materializable_root():
    """A → B → C where C is independently materializable.  A and B are
    recorded as provided; only C receives a SetupStep."""
    a_req = _requirement("req-hop-a", RequirementType.SDK,
                         install_method="manual-setup")
    b_req = _requirement("req-hop-b", RequirementType.SDK,
                         install_method="manual-setup")
    c_req = _requirement("req-hop-c", RequirementType.PYTHON_PACKAGE)
    activations = (_activation(a_req.id), _activation(b_req.id), _activation(c_req.id))
    preflight = _preflight((a_req, b_req, c_req), activations)
    variant = _variant(toolchain=[
        _toolchain_item(c_req.id, type_=RequirementType.PYTHON_PACKAGE),
        _toolchain_item(b_req.id, type_=RequirementType.SDK,
                        install_method="manual-setup",
                        provided_by=c_req.id),
        _toolchain_item(a_req.id, type_=RequirementType.SDK,
                        install_method="manual-setup",
                        provided_by=b_req.id),
    ])

    plan = _materialize(variant, preflight, project_id="proj-multihop")

    step_ids = {s.requirement_id for s in plan.steps}
    assert c_req.id in step_ids, "Root must produce its own step"
    assert a_req.id not in step_ids
    assert b_req.id not in step_ids
    assert a_req.id in plan.provided_requirement_ids
    assert b_req.id in plan.provided_requirement_ids
    assert c_req.id not in plan.provided_requirement_ids, (
        "Materializable root must not appear in provided_requirement_ids"
    )
    assert plan.steps[0].action == "install"
    assert plan.steps[0].requirement_id == c_req.id
    # Activation preservation
    assert plan.requirement_activations == activations


def test_valid_multi_hop_to_satisfied_root():
    """A → B → C where C is SATISFIED.  A and B are provided;
    no SetupStep is produced."""
    a_req = _requirement("req-hop-sat-a", RequirementType.SDK,
                         install_method="manual-setup")
    b_req = _requirement("req-hop-sat-b", RequirementType.SDK,
                         install_method="manual-setup")
    c_req = _requirement("req-hop-sat-c", RequirementType.EXECUTABLE,
                         install_method=None)
    activations = (_activation(a_req.id), _activation(b_req.id), _activation(c_req.id))
    preflight = _preflight(
        (a_req, b_req, c_req), activations,
        satisfied_ids=frozenset({c_req.id}),
    )
    variant = _variant(toolchain=[
        _toolchain_item(c_req.id, type_=RequirementType.EXECUTABLE,
                        install_method=None, state="already_installed"),
        _toolchain_item(b_req.id, type_=RequirementType.SDK,
                        install_method="manual-setup",
                        provided_by=c_req.id),
        _toolchain_item(a_req.id, type_=RequirementType.SDK,
                        install_method="manual-setup",
                        provided_by=b_req.id),
    ])

    plan = _materialize(variant, preflight, project_id="proj-multihop-sat")

    assert plan.steps == (), (
        "No steps expected when root is satisfied and dependents are provided"
    )
    assert a_req.id in plan.provided_requirement_ids
    assert b_req.id in plan.provided_requirement_ids
    assert c_req.id not in plan.provided_requirement_ids


# ---------------------------------------------------------------------------
# S05 — Missing provider
# ---------------------------------------------------------------------------

def test_missing_provider_fails_closed():
    """provided_by references a non-existent ToolchainItem → fail closed.
    Requirement is NOT listed as provided."""
    req = _requirement("req-orphan", RequirementType.SDK,
                       install_method="manual-setup")
    activation = _activation(req.id)
    preflight = _preflight((req,), (activation,))
    variant = _variant(toolchain=[
        _toolchain_item(req.id, type_=RequirementType.SDK,
                        install_method="manual-setup",
                        provided_by="req-nonexistent"),
    ])

    plan = _materialize(variant, preflight, project_id="proj-missing-prov")

    assert plan.provided_requirement_ids == (), (
        "Missing provider must not produce PROVIDED classification"
    )
    assert len(plan.steps) == 1
    assert plan.steps[0].requirement_id == req.id
    assert plan.steps[0].action == "manual_review"
    # No orphan references
    for step in plan.steps:
        assert step.requirement_id == req.id
    for pid in plan.provided_requirement_ids:
        assert pid in {req.id}


# ---------------------------------------------------------------------------
# S06 — Self-reference
# ---------------------------------------------------------------------------

def test_self_reference_fails_closed():
    """A.provided_by = A → fail closed.  Not listed as provided."""
    req = _requirement("req-self", RequirementType.SDK,
                       install_method="manual-setup")
    activation = _activation(req.id)
    preflight = _preflight((req,), (activation,))
    variant = _variant(toolchain=[
        _toolchain_item(req.id, type_=RequirementType.SDK,
                        install_method="manual-setup",
                        provided_by=req.id),
    ])

    plan = _materialize(variant, preflight, project_id="proj-self")

    assert plan.provided_requirement_ids == (), (
        "Self-reference must not produce PROVIDED classification"
    )
    assert len(plan.steps) == 1
    assert plan.steps[0].requirement_id == req.id
    assert plan.steps[0].action == "manual_review"
    assert plan.requirement_activations == (activation,)


# ---------------------------------------------------------------------------
# S07 — Provisioning cycle
# ---------------------------------------------------------------------------

def test_provisioning_cycle_fails_closed():
    """A.provided_by = B, B.provided_by = A → fail closed.
    Neither is listed as provided."""
    a_req = _requirement("req-cycle-a", RequirementType.SDK,
                         install_method="manual-setup")
    b_req = _requirement("req-cycle-b", RequirementType.SDK,
                         install_method="manual-setup")
    activations = (_activation(a_req.id), _activation(b_req.id))
    preflight = _preflight((a_req, b_req), activations)
    variant = _variant(toolchain=[
        _toolchain_item(a_req.id, type_=RequirementType.SDK,
                        install_method="manual-setup",
                        provided_by=b_req.id),
        _toolchain_item(b_req.id, type_=RequirementType.SDK,
                        install_method="manual-setup",
                        provided_by=a_req.id),
    ])

    plan = _materialize(variant, preflight, project_id="proj-cycle")

    assert plan.provided_requirement_ids == (), (
        "Cycle must not produce any PROVIDED classifications"
    )
    step_ids = {s.requirement_id for s in plan.steps}
    assert a_req.id in step_ids, "Both nodes must fall back to own classification"
    assert b_req.id in step_ids, "Both nodes must fall back to own classification"
    assert all(s.action == "manual_review" for s in plan.steps)
    assert plan.requirement_activations == activations


# ---------------------------------------------------------------------------
# S08 — Unmaterializable provider
# ---------------------------------------------------------------------------

def test_unmaterializable_provider_does_not_establish_provided():
    """B.provided_by = A where A resolves to manual_review.
    B must not become PROVIDED merely because A exists."""
    a_req = _requirement("req-manual-provider", RequirementType.SDK,
                         install_method="manual-setup")
    b_req = _requirement("req-provided-by-manual", RequirementType.SDK,
                         install_method="manual-setup")
    activations = (_activation(a_req.id), _activation(b_req.id))
    preflight = _preflight((a_req, b_req), activations)
    variant = _variant(toolchain=[
        _toolchain_item(a_req.id, type_=RequirementType.SDK,
                        install_method="manual-setup"),
        _toolchain_item(b_req.id, type_=RequirementType.SDK,
                        install_method="manual-setup",
                        provided_by=a_req.id),
    ])

    plan = _materialize(variant, preflight, project_id="proj-unmaterializable")

    assert plan.provided_requirement_ids == (), (
        "Unmaterializable provider must not establish PROVIDED"
    )
    step_ids = {s.requirement_id for s in plan.steps}
    assert a_req.id in step_ids
    assert b_req.id in step_ids
    assert len(plan.steps) == 2
    assert all(s.action == "manual_review" for s in plan.steps)


# ---------------------------------------------------------------------------
# S09 — Activation semantics
# ---------------------------------------------------------------------------

def test_inactive_requirement_does_not_block_active_setup():
    """An inactive/nonblocking requirement must not block unrelated active setup.
    Activation semantics from the production path are preserved."""
    active_req = _requirement("req-active", RequirementType.PYTHON_PACKAGE)
    inactive_req = _requirement("req-inactive", RequirementType.CAPABILITY,
                                install_method=None)
    activations = (_activation(active_req.id), _activation(inactive_req.id,
                  active=False, blocks=False))
    preflight = _preflight((active_req, inactive_req), activations,
                           project_id="proj-activation")
    variant = _variant(toolchain=[
        _toolchain_item(active_req.id, type_=RequirementType.PYTHON_PACKAGE),
        _toolchain_item(inactive_req.id, type_=RequirementType.CAPABILITY,
                        install_method=None),
    ])

    plan = _materialize(variant, preflight, project_id="proj-activation")

    assert plan.project_id == "proj-activation"
    step_ids = {s.requirement_id for s in plan.steps}
    assert active_req.id in step_ids, "Active requirement must produce a step"
    assert inactive_req.id not in step_ids, "Inactive requirement must not block"
    assert inactive_req.id in plan.deferred_requirement_ids, (
        "Inactive requirement must appear in deferred_requirement_ids"
    )
    assert plan.deferred_requirement_ids == (inactive_req.id,)
    assert plan.deferred_requirements == (inactive_req,)
    assert plan.requirement_activations == activations
    # No false provisioning
    assert plan.provided_requirement_ids == ()
    # Activation preserved: inactive stays inactive
    inactive_act = next(
        a for a in plan.requirement_activations
        if a.requirement_id == inactive_req.id
    )
    assert inactive_act.active is False
    assert inactive_act.blocks_current_operation is False


def test_nonblocking_requirement_is_deferred_not_provided():
    """An active but non-blocking requirement is DEFERRED, not PROVIDED or
    blocking setup."""
    blocking_req = _requirement("req-blocking", RequirementType.PYTHON_PACKAGE)
    nonblocking_req = _requirement("req-nonblocking", RequirementType.SDK,
                                   install_method="manual-setup")
    activations = (
        _activation(blocking_req.id, active=True, blocks=True),
        _activation(nonblocking_req.id, active=True, blocks=False),
    )
    preflight = _preflight(
        (blocking_req, nonblocking_req), activations,
        project_id="proj-nonblocking",
    )
    variant = _variant(toolchain=[
        _toolchain_item(blocking_req.id, type_=RequirementType.PYTHON_PACKAGE),
        _toolchain_item(nonblocking_req.id, type_=RequirementType.SDK,
                        install_method="manual-setup"),
    ])

    plan = _materialize(variant, preflight, project_id="proj-nonblocking")

    step_ids = {s.requirement_id for s in plan.steps}
    assert blocking_req.id in step_ids, "Blocking requirement must produce a step"
    assert nonblocking_req.id in plan.deferred_requirement_ids, (
        "Non-blocking non-install item must be deferred"
    )
    assert nonblocking_req.id not in step_ids
    assert plan.provided_requirement_ids == ()


# ---------------------------------------------------------------------------
# S10 — Order independence
# ---------------------------------------------------------------------------

def test_order_independence_semantic_equivalence():
    """Equivalent Selected Toolchain inputs with different item ordering
    must produce semantically equivalent SetupPlans."""

    a_req = _requirement("req-ord-a", RequirementType.SDK,
                         install_method="manual-setup")
    b_req = _requirement("req-ord-b", RequirementType.SDK,
                         install_method="manual-setup")
    c_req = _requirement("req-ord-c", RequirementType.PYTHON_PACKAGE)
    activations = (_activation(a_req.id), _activation(b_req.id), _activation(c_req.id))
    preflight = _preflight((a_req, b_req, c_req), activations)

    def _v(items):
        return _variant(toolchain=items)

    item_a = _toolchain_item(a_req.id, type_=RequirementType.SDK,
                             install_method="manual-setup",
                             provided_by=b_req.id)
    item_b = _toolchain_item(b_req.id, type_=RequirementType.SDK,
                             install_method="manual-setup",
                             provided_by=c_req.id)
    item_c = _toolchain_item(c_req.id, type_=RequirementType.PYTHON_PACKAGE)

    plan_abc = _materialize(_v([item_a, item_b, item_c]), preflight,
                            project_id="proj-ord-abc")
    plan_cba = _materialize(_v([item_c, item_b, item_a]), preflight,
                            project_id="proj-ord-cba")

    assert set(plan_abc.provided_requirement_ids) == set(plan_cba.provided_requirement_ids)
    assert {s.requirement_id for s in plan_abc.steps} == {
        s.requirement_id for s in plan_cba.steps
    }
    assert set(plan_abc.deferred_requirement_ids) == set(plan_cba.deferred_requirement_ids)

    for plan in (plan_abc, plan_cba):
        assert plan.project_id.startswith("proj-ord-")
        assert c_req.id in {s.requirement_id for s in plan.steps}
        assert a_req.id in plan.provided_requirement_ids
        assert b_req.id in plan.provided_requirement_ids
        assert plan.requirement_activations == activations


# ---------------------------------------------------------------------------
# State-contract assertions — cross-cutting
# ---------------------------------------------------------------------------

def test_no_duplicate_setup_responsibility():
    """No requirement may appear as both a step and provided."""
    provider_req = _requirement("req-dup-provider", RequirementType.PYTHON_PACKAGE)
    dependent_req = _requirement("req-dup-dependent", RequirementType.SDK,
                                 install_method="manual-setup")
    activations = (_activation(provider_req.id), _activation(dependent_req.id))
    preflight = _preflight((provider_req, dependent_req), activations)
    variant = _variant(toolchain=[
        _toolchain_item(provider_req.id, type_=RequirementType.PYTHON_PACKAGE),
        _toolchain_item(dependent_req.id, type_=RequirementType.SDK,
                        install_method="manual-setup",
                        provided_by=provider_req.id),
    ])

    plan = _materialize(variant, preflight, project_id="proj-dup")

    step_ids = {s.requirement_id for s in plan.steps}
    for pid in plan.provided_requirement_ids:
        assert pid not in step_ids, (
            f"Requirement {pid} is both a step and provided"
        )
    for sid in step_ids:
        assert sid not in plan.provided_requirement_ids, (
            f"Requirement {sid} is both a step and provided"
        )
    # No duplicate steps
    assert len(plan.steps) == len(step_ids)


def test_combined_scenario_state_contracts():
    """Full multi-requirement boundary: some satisfied, some materializable,
    some provided, some deferred, some active.  Exercise all SetupPlan
    output facets simultaneously."""
    r_pkg = _requirement("req-sc-pkg", RequirementType.PYTHON_PACKAGE)
    r_sat = _requirement("req-sc-sat", RequirementType.EXECUTABLE,
                         install_method=None)
    r_sdk = _requirement("req-sc-sdk", RequirementType.SDK,
                         install_method="manual-setup")
    r_inact = _requirement("req-sc-inact", RequirementType.CAPABILITY,
                           install_method=None)
    r_man = _requirement("req-sc-man", RequirementType.SDK,
                         install_method="manual-setup")
    r_prov = _requirement("req-sc-prov", RequirementType.SDK,
                          install_method="manual-setup")
    r_sat_prov = _requirement("req-sc-satprov", RequirementType.SDK,
                              install_method="manual-setup")

    activations = (
        _activation(r_pkg.id, active=True, blocks=True),
        _activation(r_sat.id, active=True, blocks=True),
        _activation(r_sdk.id, active=True, blocks=True),
        _activation(r_inact.id, active=False, blocks=False),
        _activation(r_man.id, active=True, blocks=True),
        _activation(r_prov.id, active=True, blocks=True),
        _activation(r_sat_prov.id, active=True, blocks=True),
    )
    preflight = _preflight(
        (r_pkg, r_sat, r_sdk, r_inact, r_man, r_prov, r_sat_prov),
        activations,
        project_id="proj-combined",
        satisfied_ids=frozenset({r_sat.id}),
    )
    variant = _variant(toolchain=[
        _toolchain_item(r_pkg.id, type_=RequirementType.PYTHON_PACKAGE),
        _toolchain_item(r_sat.id, type_=RequirementType.EXECUTABLE,
                        install_method=None, state="already_installed"),
        _toolchain_item(r_sdk.id, type_=RequirementType.SDK,
                        install_method="manual-setup"),
        _toolchain_item(r_inact.id, type_=RequirementType.CAPABILITY,
                        install_method=None),
        _toolchain_item(r_man.id, type_=RequirementType.SDK,
                        install_method="manual-setup"),
        _toolchain_item(r_prov.id, type_=RequirementType.SDK,
                        install_method="manual-setup",
                        provided_by=r_pkg.id),
        _toolchain_item(r_sat_prov.id, type_=RequirementType.SDK,
                        install_method="manual-setup",
                        provided_by=r_sat.id),
    ])

    plan = _materialize(variant, preflight, project_id="proj-combined")

    # project_id
    assert plan.project_id == "proj-combined"
    assert plan.id == "plan-proj-combined"

    # Steps: only materializable active items
    step_ids = {s.requirement_id for s in plan.steps}
    assert r_pkg.id in step_ids, "Materializable package must produce install step"
    assert r_sdk.id in step_ids, "Active SDK manual_review must produce step"
    assert r_man.id in step_ids, "Active SDK without provider must produce step"
    assert r_sat.id not in step_ids, "Satisfied item must not produce step"
    assert r_inact.id not in step_ids, "Inactive item must not produce step"
    assert r_prov.id not in step_ids, "Provided item must not produce step"
    assert r_sat_prov.id not in step_ids, "Satisfied-provided item must not produce step"

    # Step actions
    pkg_step = next(s for s in plan.steps if s.requirement_id == r_pkg.id)
    assert pkg_step.action == "install"
    sdk_step = next(s for s in plan.steps if s.requirement_id == r_sdk.id)
    assert sdk_step.action == "manual_review"
    man_step = next(s for s in plan.steps if s.requirement_id == r_man.id)
    assert man_step.action == "manual_review"

    # provided_requirement_ids
    assert r_prov.id in plan.provided_requirement_ids, (
        "Item with materializable provider must be provided"
    )
    assert r_sat_prov.id in plan.provided_requirement_ids, (
        "Item with satisfied provider must be provided"
    )
    assert r_pkg.id not in plan.provided_requirement_ids, (
        "Materializable root must not be in provided_requirement_ids"
    )
    assert r_sat.id not in plan.provided_requirement_ids, (
        "Satisfied root must not be in provided_requirement_ids"
    )
    assert r_sdk.id not in plan.provided_requirement_ids
    assert r_man.id not in plan.provided_requirement_ids
    assert r_inact.id not in plan.provided_requirement_ids

    # deferred_requirement_ids
    assert r_inact.id in plan.deferred_requirement_ids, (
        "Inactive requirement must be in deferred_requirement_ids"
    )
    deferred_set = set(plan.deferred_requirement_ids)
    assert r_pkg.id not in deferred_set
    assert r_sdk.id not in deferred_set
    assert r_man.id not in deferred_set

    # deferred_requirements alignment
    deferred_req_ids = {r.id for r in plan.deferred_requirements}
    assert deferred_req_ids == deferred_set

    # activation preservation
    assert plan.requirement_activations == activations
    activation_by_id = {a.requirement_id: a for a in plan.requirement_activations}
    assert activation_by_id[r_inact.id].state == "inactive"

    # No duplicate responsibility
    for pid in plan.provided_requirement_ids:
        assert pid not in step_ids, f"{pid} is both provided and has a step"

    # Every exposed requirement_id resolves to input
    all_requirement_ids = {r_pkg.id, r_sat.id, r_sdk.id, r_inact.id,
                           r_man.id, r_prov.id, r_sat_prov.id}
    for step in plan.steps:
        assert step.requirement_id in all_requirement_ids
    for pid in plan.provided_requirement_ids:
        assert pid in all_requirement_ids
    for did in plan.deferred_requirement_ids:
        assert did in all_requirement_ids

    # No orphan references
    assert all(s.is_approved is False for s in plan.steps)

    # Plan-level contracts
    assert plan.requires_user_approval is True
    assert plan.status == "pending_approval"


def test_variant_assessment_matches_materialization_policy():
    """assess_variant output must be consistent with materialize for the
    same input state."""
    r_prov = _requirement("req-asm-prov", RequirementType.PYTHON_PACKAGE)
    r_sdk = _requirement("req-asm-sdk", RequirementType.SDK,
                         install_method="manual-setup")
    r_sat = _requirement("req-asm-sat", RequirementType.EXECUTABLE,
                         install_method=None)
    activations = (_activation(r_prov.id), _activation(r_sdk.id), _activation(r_sat.id))
    preflight = _preflight(
        (r_prov, r_sdk, r_sat), activations,
        satisfied_ids=frozenset({r_sat.id}),
    )
    variant = _variant(toolchain=[
        _toolchain_item(r_prov.id, type_=RequirementType.PYTHON_PACKAGE),
        _toolchain_item(r_sdk.id, type_=RequirementType.SDK,
                        install_method="manual-setup",
                        provided_by=r_prov.id),
        _toolchain_item(r_sat.id, type_=RequirementType.EXECUTABLE,
                        install_method=None, state="already_installed"),
    ])

    plan = _materialize(variant, preflight, project_id="proj-asm")
    assessment = ToolchainMaterializer().assess_variant(variant, preflight)

    assert assessment["automatically_materializable"] is True

    item_status = {i["requirement_ref"]: i["status"] for i in assessment["items"]}
    assert item_status[r_prov.id] == "materializable"
    assert item_status[r_sdk.id] == "provided"
    assert item_status[r_sat.id] == "satisfied"

    # Consistency: provided in assessment ↔ in plan
    for i in assessment["items"]:
        ref = i["requirement_ref"]
        if i["status"] == "provided":
            assert ref in plan.provided_requirement_ids
    plan_provided = set(plan.provided_requirement_ids)
    for i in assessment["items"]:
        ref = i["requirement_ref"]
        if i["status"] == "provided":
            assert ref in plan_provided

    # No step for provided or satisfied
    step_ids = {s.requirement_id for s in plan.steps}
    for i in assessment["items"]:
        ref = i["requirement_ref"]
        if i["status"] in ("provided", "satisfied"):
            assert ref not in step_ids, (
                f"{ref} with status {i['status']} must not produce a SetupStep"
            )


# ==========================================================================
# OC-025: structured setup-effect contract
# ==========================================================================


def test_materializer_sets_correct_setup_effect_for_python_package():
    req = _requirement("req-pkg", RequirementType.PYTHON_PACKAGE)
    activation = _activation(req.id)
    preflight = _preflight((req,), (activation,))
    variant = _variant(toolchain=[
        _toolchain_item(req.id, type_=RequirementType.PYTHON_PACKAGE),
    ])
    plan = _materialize(variant, preflight, project_id="proj-effect")
    assert plan.steps[0].setup_effect == SetupEffect.PYTHON_PACKAGE_INSTALL
    assert plan.steps[0].action == "install"


def test_materializer_sets_correct_setup_effect_for_sdk():
    req = _requirement("req-sdk", RequirementType.SDK, install_method="setup")
    activation = _activation(req.id)
    preflight = _preflight((req,), (activation,))
    variant = _variant(toolchain=[
        _toolchain_item(req.id, type_=RequirementType.SDK, install_method="setup"),
    ])
    plan = _materialize(variant, preflight, project_id="proj-sdk-effect")
    assert plan.steps[0].setup_effect == SetupEffect.PROJECT_TOOL_INSTALL
    assert plan.steps[0].action == "manual_review"


def test_setup_planner_and_materializer_produce_same_classification():
    pkg_req = _requirement("req-same-pkg", RequirementType.PYTHON_PACKAGE)
    sdk_req = _requirement("req-same-sdk", RequirementType.SDK, install_method="setup")
    sys_req = _requirement("req-same-sys", RequirementType.SYSTEM_PACKAGE, install_method="apt")
    cap_req = _requirement("req-same-cap", RequirementType.CAPABILITY, install_method=None)

    activations = (
        _activation(pkg_req.id),
        _activation(sdk_req.id),
        _activation(sys_req.id),
        _activation(cap_req.id),
    )
    preflight = _preflight(
        (pkg_req, sdk_req, sys_req, cap_req),
        activations,
        project_id="proj-class",
    )

    toolchain_variant = _variant(toolchain=[
        _toolchain_item(pkg_req.id, type_=RequirementType.PYTHON_PACKAGE),
        _toolchain_item(sdk_req.id, type_=RequirementType.SDK, install_method="setup"),
        _toolchain_item(sys_req.id, type_=RequirementType.SYSTEM_PACKAGE, install_method="apt"),
        _toolchain_item(cap_req.id, type_=RequirementType.CAPABILITY, install_method=None),
    ])

    materializer_plan = _materialize(toolchain_variant, preflight, project_id="proj-class-m")
    planner_plan = SetupPlanner().plan(
        (pkg_req, sdk_req, sys_req, cap_req),
        preflight, project_id="proj-class-p",
    )

    materializer_effects = {s.requirement_id: s.setup_effect for s in materializer_plan.steps}
    planner_effects = {s.requirement_id: s.setup_effect for s in planner_plan.steps}

    assert materializer_effects == planner_effects
    assert materializer_plan.unsupported_backend_effects == planner_plan.unsupported_backend_effects


def test_plan_unsupported_backend_effects_excludes_controlled_and_satisfied():
    pkg_req = _requirement("req-ctrl-pkg", RequirementType.PYTHON_PACKAGE)
    sdk_req = _requirement("req-ctrl-sdk", RequirementType.SDK, install_method="setup")
    sat_req = _requirement("req-ctrl-sat", RequirementType.PYTHON_PACKAGE)

    activations = (
        _activation(pkg_req.id),
        _activation(sdk_req.id),
        _activation(sat_req.id),
    )
    preflight = _preflight(
        (pkg_req, sdk_req, sat_req),
        activations,
        project_id="proj-eff",
        satisfied_ids=frozenset({sat_req.id}),
    )
    variant = _variant(toolchain=[
        _toolchain_item(pkg_req.id, type_=RequirementType.PYTHON_PACKAGE),
        _toolchain_item(sdk_req.id, type_=RequirementType.SDK, install_method="setup"),
        _toolchain_item(sat_req.id, type_=RequirementType.PYTHON_PACKAGE),
    ])
    plan = _materialize(variant, preflight, project_id="proj-eff")

    assert SetupEffect.PYTHON_PACKAGE_INSTALL not in plan.unsupported_backend_effects
    assert SetupEffect.PROJECT_TOOL_INSTALL in plan.unsupported_backend_effects
    assert sat_req.id not in {s.requirement_id for s in plan.steps}
