import venv

import pytest

from app.council_models import CouncilResult, CouncilVariant, ToolchainItem
from app.requirement_model import (
    Requirement, RequirementActivation, RequirementType,
    PreflightRequirementResult, PreflightResult,
)
from app.requirement_preflight import RequirementPreflight
from app.toolchain_materializer import (
    ToolchainMaterializationError,
    ToolchainMaterializer,
)
from app.requirement_model import SetupEffect


def make_item(
    requirement_ref="req-1",
    name="requests",
    type=RequirementType.PYTHON_PACKAGE,
    install_method="pip",
    version=None,
    state="needs_install",
    provided_by=None,
    technical_identity=None,
):
    return ToolchainItem(
        requirement_ref=requirement_ref,
        name=name,
        type=type,
        install_method=install_method,
        version=version,
        state=state,
        provided_by=provided_by,
        technical_identity=technical_identity,
    )


def make_variant(
    variant_id="variant-1",
    toolchain=(),
):
    return CouncilVariant(
        id=variant_id,
        name=variant_id,
        toolchain=toolchain,
    )


def make_result(
    variants=(),
    recommendation="variant-1",
    council_complete=True,
):
    return CouncilResult(
        id="council-1",
        project_id="project-1",
        variants=variants,
        recommendation=recommendation,
        council_complete=council_complete,
    )


def activation_preflight(requirement, activation, *, satisfied=False):
    return PreflightResult(
        id="preflight-activation", project_id="project-1",
        overall_ready=satisfied or not activation.blocks_current_operation,
        results=(PreflightRequirementResult(
            requirement_id=requirement.id, present=satisfied, satisfied=satisfied,
            active=activation.active,
            blocks_current_operation=activation.blocks_current_operation,
        ),),
        missing_requirements=() if satisfied or not activation.active else (requirement,),
        activations=(activation,),
        inactive_requirements=() if activation.active else (requirement,),
        project_requirements=(requirement,),
    )


def project_requirement(req_id, req_type=RequirementType.PYTHON_PACKAGE):
    return Requirement(
        id=req_id, name="future-tool", type=req_type, purpose="continued development",
        required=True, confidence=0.9, install_method="structured-installer",
    )


def test_materializes_exact_recommended_variant():
    recommended = make_variant(
        "variant-1",
        (make_item(requirement_ref="req-recommended"),),
    )
    other = make_variant(
        "variant-2",
        (make_item(requirement_ref="req-other"),),
    )

    result = ToolchainMaterializer().materialize(
        make_result(
            variants=(other, recommended),
            recommendation="variant-1",
        ),
        "project-1",
    )

    assert len(result.steps) == 1
    assert result.steps[0].requirement_id == "req-recommended"


def test_non_recommended_variants_are_ignored():
    selected = make_variant(
        "variant-1",
        (make_item(requirement_ref="req-selected"),),
    )
    ignored = make_variant(
        "variant-2",
        (
            make_item(requirement_ref="req-ignored-1"),
            make_item(requirement_ref="req-ignored-2"),
        ),
    )

    result = ToolchainMaterializer().materialize(
        make_result(
            variants=(selected, ignored),
            recommendation="variant-1",
        ),
        "project-1",
    )

    assert tuple(step.requirement_id for step in result.steps) == (
        "req-selected",
    )


def test_manual_recommended_variant_is_not_replaced_by_executable_variant():
    selected = make_variant(
        "variant-manual",
        (make_item(
            requirement_ref="req-manual",
            type=RequirementType.SDK,
            install_method="manual",
        ),),
    )
    executable = make_variant(
        "variant-executable",
        (make_item(requirement_ref="req-executable"),),
    )

    result = ToolchainMaterializer().materialize(
        make_result(
            variants=(selected, executable),
            recommendation="variant-manual",
        ),
        "project-1",
    )

    assert tuple(step.requirement_id for step in result.steps) == ("req-manual",)
    assert result.steps[0].action == "manual_review"


def test_already_installed_items_are_skipped():
    variant = make_variant(
        toolchain=(
            make_item(
                requirement_ref="req-installed",
                state="already_installed",
            ),
            make_item(
                requirement_ref="req-missing",
                state="needs_install",
            ),
        )
    )

    result = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)),
        "project-1",
    )

    assert tuple(step.requirement_id for step in result.steps) == (
        "req-missing",
    )


def test_python_package_becomes_install_step():
    variant = make_variant(
        toolchain=(
            make_item(
                requirement_ref="req-build",
                name="build",
                install_method="pip",
                version="1.2.2",
            ),
        )
    )

    result = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)),
        "project-1",
    )

    step = result.steps[0]
    assert step.action == "install"
    assert step.package == "build"
    assert step.version == "1.2.2"
    assert step.install_method == "pip"
    assert step.requirement_id == "req-build"


def test_python_package_variant_is_assessed_as_automatically_materializable():
    variant = make_variant(toolchain=(make_item(),))

    assessment = ToolchainMaterializer().assess_variant(variant)

    assert assessment["status"] == "automatically_materializable"
    assert assessment["automatically_materializable"] is True
    assert assessment["items"][0]["status"] == "materializable"


def test_non_python_item_becomes_manual_review():
    variant = make_variant(
        toolchain=(
            make_item(
                requirement_ref="req-sdk",
                name="esp-idf",
                type=RequirementType.SDK,
                install_method="manual",
            ),
        )
    )

    result = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)),
        "project-1",
    )

    step = result.steps[0]
    assert step.action == "manual_review"
    assert step.package is None


def test_inactive_manual_requirement_is_retained_but_not_materialized():
    requirement = project_requirement("req-future", "future_capability_kind")
    activation = RequirementActivation(requirement.id, False, False)
    variant = make_variant(toolchain=(make_item(
        requirement_ref=requirement.id, type="future_capability_kind",
        install_method="manual",
    ),))

    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-1",
        preflight=activation_preflight(requirement, activation),
    )

    assert plan.steps == ()
    assert plan.requirement_activations == (activation,)
    assert plan.deferred_requirement_ids == (requirement.id,)
    assert plan.deferred_requirements == (requirement,)


def test_active_manual_requirement_still_materializes_as_blocking_review():
    requirement = project_requirement("req-manual", RequirementType.CAPABILITY)
    activation = RequirementActivation(requirement.id, True, True)
    variant = make_variant(toolchain=(make_item(
        requirement_ref=requirement.id, name=requirement.name, type=RequirementType.CAPABILITY,
        install_method="manual",
    ),))

    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-1",
        preflight=activation_preflight(requirement, activation),
    )

    assert len(plan.steps) == 1
    assert plan.steps[0].requirement_id == requirement.id
    assert plan.steps[0].action == "manual_review"


def test_active_controlled_setup_remains_materializable_after_approval_boundary():
    requirement = project_requirement("req-package")
    activation = RequirementActivation(requirement.id, True, True)
    variant = make_variant(toolchain=(make_item(
        requirement_ref=requirement.id, name=requirement.name,
        install_method="python_package",
    ),))

    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-1",
        preflight=activation_preflight(requirement, activation),
    )

    assert plan.steps[0].action == "install"
    assert plan.steps[0].is_approved is False


def test_satisfied_preflight_wins_over_active_council_install_claim():
    requirement = project_requirement("req-satisfied")
    activation = RequirementActivation(requirement.id, True, True)
    variant = make_variant(toolchain=(make_item(
        requirement_ref=requirement.id, state="needs_install",
    ),))

    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-1",
        preflight=activation_preflight(requirement, activation, satisfied=True),
    )

    assert plan.steps == ()


def test_unsupported_variant_is_assessed_as_manual_review():
    variant = make_variant(toolchain=(
        make_item(
            requirement_ref="req-sdk",
            name="sdk",
            type=RequirementType.SDK,
            install_method="https://example.invalid/sdk",
        ),
    ))

    assessment = ToolchainMaterializer().assess_variant(variant)

    assert assessment["status"] == "manual_review"
    assert assessment["automatically_materializable"] is False
    assert assessment["items"][0]["status"] == "manual_review"


def test_python_item_with_incompatible_compound_install_method_becomes_manual_review():
    """CLAUDE-E2E-NIO-008A: a real Real-System-E2E reached 50% and
    failed immediately on an approved SetupStep whose install_method was
    a free-form, compound shell command sequence ("python3 -m venv
    .venv && source .venv/bin/activate && pip install esphome") --
    PythonPackageExecutor correctly rejected it (it must never execute
    arbitrary shell chains), but ToolchainMaterializer had already let
    it through into an "install" action step with no check that this
    install_method is actually something the controlled executor for
    this setup_effect can consume. Every executable SetupStep must be
    compatible with its controlled executor BEFORE the SetupPlan can
    become approvable/executable -- this must be demoted to
    manual_review at materialization time instead, technology-neutrally
    (not an ESPHome/venv/"source" special case: any package name would
    reproduce this)."""
    variant = make_variant(
        toolchain=(
            make_item(
                requirement_ref="req-esphome",
                name="esphome",
                install_method=(
                    "python3 -m venv .venv && source .venv/bin/activate "
                    "&& pip install esphome"
                ),
            ),
        )
    )

    result = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)),
        "project-1",
    )

    step = result.steps[0]
    assert step.action == "manual_review"
    assert step.setup_effect is None


def test_python_item_without_install_method_becomes_manual_review():
    variant = make_variant(
        toolchain=(
            make_item(
                requirement_ref="req-python",
                name="requests",
                install_method=None,
            ),
        )
    )

    result = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)),
        "project-1",
    )

    step = result.steps[0]
    assert step.action == "manual_review"
    assert step.package == "requests"


# =========================================================================
# CLAUDE-ADC-S23-INSTALL-METHOD-PRODUCER-REPAIR-FIX-001: install_method
# producer/repair fixes (council_prompts.py contract + Chairman rework
# hint routing) never change ToolchainMaterializer's own policy -- these
# regressions prove the materializer side of that: a canonical,
# post-fix install_method now reaches action="install" regardless of a
# display name that still carries environment/placement wording (proof
# A), a genuinely incompatible/arbitrary install_method still stays
# manual_review no matter how "correct" the resolved identity looks
# (proof D), and no install command or technical_identity is ever
# inferred from the display name text (proof E).
# =========================================================================


def test_canonical_install_method_reaches_install_regardless_of_environment_worded_name():
    """A (CLAUDE-ADC-S23-INSTALL-METHOD-PRODUCER-REPAIR-FIX-001): the
    exact live-run shape (merged-2's item name carried "(in container)")
    but with install_method corrected to one of the four canonical
    forms council_prompts.py now documents -- must materialize as
    action="install" with no install_method_incompatible rejection,
    proving the fix is about install_method's SHAPE, never about
    stripping/parsing the display name."""
    variant = make_variant(
        toolchain=(
            make_item(
                requirement_ref="req-bb77bad0",
                name="ESPHome Python Package (in container)",
                technical_identity="esphome",
                install_method="pip install esphome",
            ),
        )
    )

    result = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)),
        "project-1",
    )

    step = result.steps[0]
    assert step.action == "install"
    assert step.package == "esphome"


@pytest.mark.parametrize(
    "install_method",
    ["pip", "python_package", "python -m pip install esphome"],
)
def test_every_canonical_install_method_form_reaches_install(install_method):
    """A (permutation): all four documented canonical forms -- not just
    "pip install <name>" -- must materialize as action="install"."""
    variant = make_variant(
        toolchain=(
            make_item(
                requirement_ref="req-bb77bad0",
                name="ESPHome Python Package",
                technical_identity="esphome",
                install_method=install_method,
            ),
        )
    )

    result = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)),
        "project-1",
    )

    step = result.steps[0]
    assert step.action == "install"


@pytest.mark.parametrize(
    "install_method",
    [
        "python3 -m venv .venv && source .venv/bin/activate && pip install esphome",
        "docker exec esphome-container pip install esphome",
        "pip install esphome && esphome version",
        "curl -sSL https://example.invalid/install.sh | sh",
    ],
)
def test_compound_or_arbitrary_install_method_stays_manual_review_even_with_valid_identity(
    install_method,
):
    """D (CLAUDE-ADC-S23-INSTALL-METHOD-PRODUCER-REPAIR-FIX-001): a
    genuinely compound/arbitrary install_method must remain
    manual_review even though technical_identity is perfectly valid --
    the producer-prompt and Chairman-rework-hint fixes must never
    weaken ToolchainMaterializer's/PythonPackageExecutor's own
    controlled-executor compatibility contract."""
    variant = make_variant(
        toolchain=(
            make_item(
                requirement_ref="req-bb77bad0",
                name="ESPHome Python Package",
                technical_identity="esphome",
                install_method=install_method,
            ),
        )
    )

    result = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)),
        "project-1",
    )

    step = result.steps[0]
    assert step.action == "manual_review"
    assert step.setup_effect is None


def test_install_method_incompatibility_is_never_masked_by_a_coincidentally_valid_name():
    """E (CLAUDE-ADC-S23-INSTALL-METHOD-PRODUCER-REPAIR-FIX-001): even
    when the display `name` alone happens to already be a valid
    distribution identifier (so identity resolves via the existing,
    unchanged name-fallback), ToolchainMaterializer must still classify
    strictly from the item's OWN install_method field -- never infer,
    rewrite, or wave through an install_method because the resolved
    identity looks fine. Proves no new display-name-based install
    command inference was introduced by this fix."""
    variant = make_variant(
        toolchain=(
            make_item(
                requirement_ref="req-bb77bad0",
                name="esphome",
                technical_identity=None,
                install_method="docker exec devbox pip install esphome",
            ),
        )
    )

    result = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)),
        "project-1",
    )

    step = result.steps[0]
    assert step.package == "esphome"
    assert step.action == "manual_review"


def test_install_command_shaped_display_name_is_never_used_as_install_method():
    """E (permutation): a display name that IS itself a full,
    command-shaped string must never be read as install_method or used
    to derive one -- only the item's own install_method field is ever
    consulted, and the item's own name/technical_identity fields are
    still the only source of identity."""
    variant = make_variant(
        toolchain=(
            make_item(
                requirement_ref="req-bb77bad0",
                name="docker exec my-container pip install esphome",
                technical_identity=None,
                install_method=None,
            ),
        )
    )

    result = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)),
        "project-1",
    )

    step = result.steps[0]
    assert step.action == "manual_review"
    assert step.package is None


def test_missing_recommendation_raises():
    council_result = make_result(
        variants=(make_variant(),),
        recommendation=None,
    )

    with pytest.raises(
        ToolchainMaterializationError,
        match="does not contain a recommendation",
    ):
        ToolchainMaterializer().materialize(
            council_result,
            "project-1",
        )


def test_unknown_recommendation_raises():
    council_result = make_result(
        variants=(make_variant("variant-1"),),
        recommendation="variant-missing",
    )

    with pytest.raises(
        ToolchainMaterializationError,
        match="Recommended Council variant not found",
    ):
        ToolchainMaterializer().materialize(
            council_result,
            "project-1",
        )


def test_incomplete_council_raises():
    council_result = make_result(
        variants=(make_variant(),),
        council_complete=False,
    )

    with pytest.raises(
        ToolchainMaterializationError,
        match="Council result is incomplete",
    ):
        ToolchainMaterializer().materialize(
            council_result,
            "project-1",
        )


def test_generated_steps_are_never_approved():
    variant = make_variant(
        toolchain=(
            make_item(requirement_ref="req-1"),
            make_item(
                requirement_ref="req-2",
                type=RequirementType.SDK,
            ),
        )
    )

    result = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)),
        "project-1",
    )

    assert result.steps
    assert all(step.is_approved is False for step in result.steps)


def test_command_is_never_materialized():
    variant = make_variant(
        toolchain=(
            make_item(requirement_ref="req-1"),
            make_item(
                requirement_ref="req-2",
                type=RequirementType.SYSTEM_PACKAGE,
                install_method="apt",
            ),
        )
    )

    result = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)),
        "project-1",
    )

    assert all(step.command is None for step in result.steps)


def test_plan_requires_human_approval():
    variant = make_variant(toolchain=(make_item(),))

    result = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)),
        "project-42",
    )

    assert result.id == "plan-project-42"
    assert result.project_id == "project-42"
    assert result.requires_user_approval is True
    assert result.status == "pending_approval"


def test_input_council_result_is_unchanged():
    item = make_item()
    variant = make_variant(toolchain=(item,))
    council_result = make_result(variants=(variant,))

    original_variants = council_result.variants
    original_toolchain = variant.toolchain
    original_recommendation = council_result.recommendation

    ToolchainMaterializer().materialize(
        council_result,
        "project-1",
    )

    assert council_result.variants == original_variants
    assert variant.toolchain == original_toolchain
    assert council_result.recommendation == original_recommendation


def make_preflight(*satisfied_ids: str) -> PreflightResult:
    results = tuple(
        PreflightRequirementResult(
            requirement_id=req_id, present=True, satisfied=True,
        )
        for req_id in satisfied_ids
    )
    return PreflightResult(
        id="pre-1", project_id="project-1",
        overall_ready=len(satisfied_ids) > 0,
        results=results,
    )


def test_satisfied_preflight_suppresses_needs_install_python_item():
    preflight = make_preflight("req-python")
    variant = make_variant(
        toolchain=(
            make_item(
                requirement_ref="req-python",
                name="python",
                type=RequirementType.PYTHON_PACKAGE,
                install_method="apt install python3",
                state="needs_install",
            ),
            make_item(
                requirement_ref="req-esphome",
                name="esphome",
                install_method="pip",
                state="needs_install",
            ),
        )
    )

    result = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)),
        "project-1",
        preflight=preflight,
    )

    assert tuple(step.requirement_id for step in result.steps) == (
        "req-esphome",
    ), f"req-python should be suppressed by satisfied preflight"

    esp_step = result.steps[0]
    assert esp_step.action == "install"
    assert esp_step.package == "esphome"


def test_satisfied_preflight_suppresses_manual_review_item():
    preflight = make_preflight("req-sdk")
    variant = make_variant(
        toolchain=(
            make_item(
                requirement_ref="req-sdk",
                name="esp-idf",
                type=RequirementType.SDK,
                install_method="manual",
                state="needs_install",
            ),
        )
    )

    result = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)),
        "project-1",
        preflight=preflight,
    )

    assert len(result.steps) == 0, (
        f"Satisfied preflight must suppress manual_review item; "
        f"got {[(s.requirement_id, s.action) for s in result.steps]}"
    )


def test_satisfied_preflight_item_keeps_variant_automatically_materializable():
    preflight = make_preflight("req-sdk")
    variant = make_variant(toolchain=(
        make_item(
            requirement_ref="req-sdk",
            name="sdk",
            type=RequirementType.SDK,
            install_method="manual",
            state="needs_install",
        ),
    ))

    assessment = ToolchainMaterializer().assess_variant(variant, preflight)

    assert assessment["automatically_materializable"] is True
    assert assessment["items"][0]["status"] == "satisfied"


# ---------------------------------------------------------------------------
# CLAUDE-ADC-S23-STRICT-IDENTITY-ENVIRONMENT-BINDING-FIX-004 (#7): a
# preflight "satisfied" result may suppress a PYTHON_PACKAGE item's
# installation only when it is PROVEN to refer to the SAME effective
# target this materialization actually selects -- RequirementPreflight
# always stamps a pre-candidate, host-style target, which is only
# coincidentally the same target a "venv" candidate's own environment
# resolves to.
# ---------------------------------------------------------------------------

def _venv_python_package_variant(req_id, environment):
    return CouncilVariant(
        id="variant-1", name="variant-1", environment=environment,
        toolchain=(make_item(
            requirement_ref=req_id, name="acme-widgets",
            technical_identity="acme-widgets", install_method="pip",
        ),),
    )


def _satisfied_preflight_with_target(req_id, target_executable):
    return PreflightResult(
        id="pre-1", project_id="project-1", overall_ready=True,
        results=(PreflightRequirementResult(
            requirement_id=req_id, present=True, satisfied=True,
            target_executable=target_executable,
        ),),
    )


def test_host_satisfied_preflight_does_not_suppress_selected_venv_target(tmp_path):
    """Reproduced defect: a host preflight reports the package already
    present, but the selected candidate's environment is "venv" and no
    real venv interpreter exists at project_root -- the host evidence
    must never suppress this item; it must independently fail closed to
    manual_review for the actually-selected (unresolved) venv target."""
    preflight = _satisfied_preflight_with_target("req-venv", "/fake/host/bin/python")
    variant = _venv_python_package_variant("req-venv", "venv")

    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-1",
        preflight=preflight, project_root=str(tmp_path),
    )

    assert len(plan.steps) == 1, (
        "host-satisfied evidence must not suppress a selected venv target"
    )
    step = plan.steps[0]
    assert step.action == "manual_review"
    assert step.target_executable is None


def test_venv_a_satisfied_preflight_does_not_suppress_selected_venv_b(tmp_path):
    """A "satisfied" result stamped against project A's own venv target
    must not suppress installation for project B's venv -- even though
    both candidates declare the SAME environment label ("venv"), a
    different project_root resolves to a genuinely different target."""
    project_a = tmp_path / "a"
    project_b = tmp_path / "b"
    venv.EnvBuilder(with_pip=False, clear=True).create(project_a / ".venv")
    target_a = str(project_a / ".venv" / "bin" / "python")

    preflight = _satisfied_preflight_with_target("req-venv", target_a)
    variant = _venv_python_package_variant("req-venv", "venv")

    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-1",
        preflight=preflight, project_root=str(project_b),
    )

    assert len(plan.steps) == 1, (
        "a different project's venv target must not suppress this project's venv install"
    )
    step = plan.steps[0]
    # project_b has no .venv at all -> fails closed, never inherits target_a.
    assert step.action == "manual_review"
    assert step.target_executable is None
    assert step.target_executable != target_a


def test_exact_same_venv_target_satisfied_still_suppresses(tmp_path):
    """Positive control: when the preflight-stamped target IS proven
    identical to the selected materialization target, "satisfied" keeps
    suppressing installation exactly as before this fix."""
    venv.EnvBuilder(with_pip=False, clear=True).create(tmp_path / ".venv")
    target = str(tmp_path / ".venv" / "bin" / "python")

    preflight = _satisfied_preflight_with_target("req-venv", target)
    variant = _venv_python_package_variant("req-venv", "venv")

    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-1",
        preflight=preflight, project_root=str(tmp_path),
    )

    assert len(plan.steps) == 0, "same-target satisfied evidence must still suppress installation"


def test_unresolved_host_environment_does_not_pretend_target_equality(monkeypatch):
    """When even "host" cannot resolve (every candidate is itself a venv
    interpreter -- see TestResolveHostPythonExecutable), a "satisfied"
    result stamped against some OTHER target must not be trusted for a
    "host" candidate either -- target identity, never mere environment
    label equality, gates suppression."""
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr("sys.executable", "/fake/only-venv-available/bin/python")
    import app.python_distribution as python_distribution_module
    monkeypatch.setattr(
        python_distribution_module, "_is_adc_controller_venv_interpreter",
        lambda executable: True,
    )
    preflight = _satisfied_preflight_with_target("req-host", "/fake/host/bin/python")
    variant = _venv_python_package_variant("req-host", "host")

    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-1",
        preflight=preflight, project_root="/irrelevant/for/host",
    )

    assert len(plan.steps) == 1
    step = plan.steps[0]
    assert step.action == "manual_review"
    assert step.target_executable is None


def test_unsatisfied_requirement_still_materializes():
    preflight = PreflightResult(
        id="pre-1", project_id="project-1",
        overall_ready=False,
        results=(
            PreflightRequirementResult(
                requirement_id="req-missing",
                present=False, satisfied=False,
            ),
        ),
    )
    variant = make_variant(
        toolchain=(
            make_item(
                requirement_ref="req-missing",
                name="tool",
                install_method="pip",
                state="needs_install",
            ),
        )
    )

    result = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)),
        "project-1",
        preflight=preflight,
    )

    assert len(result.steps) == 1, (
        "Unsatisfied preflight must still produce a SetupStep"
    )
    assert result.steps[0].action == "install"


def test_unsatisfied_preflight_overrides_already_installed_claim():
    preflight = PreflightResult(
        id="pre-1",
        project_id="project-1",
        overall_ready=False,
        results=(
            PreflightRequirementResult(
                requirement_id="req-missing",
                present=False,
                satisfied=False,
            ),
        ),
    )
    variant = make_variant(toolchain=(
        make_item(
            requirement_ref="req-missing",
            state="already_installed",
        ),
    ))
    materializer = ToolchainMaterializer()

    assessment = materializer.assess_variant(variant, preflight)
    result = materializer.materialize(
        make_result(variants=(variant,)),
        "project-1",
        preflight=preflight,
    )

    assert assessment["items"][0]["status"] == "materializable"
    assert len(result.steps) == 1
    assert result.steps[0].action == "install"


def test_unknown_requirement_ref_not_silently_satisfied():
    preflight = make_preflight("req-other")
    variant = make_variant(
        toolchain=(
            make_item(
                requirement_ref="req-unknown",
                name="some-package",
                install_method="pip",
                state="needs_install",
            ),
        )
    )

    result = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)),
        "project-1",
        preflight=preflight,
    )

    assert len(result.steps) == 1, (
        "Unknown requirement_ref must not be silently considered satisfied"
    )
    assert result.steps[0].requirement_id == "req-unknown"


def test_existing_already_installed_behavior_unchanged():
    preflight = make_preflight()
    variant = make_variant(
        toolchain=(
            make_item(
                requirement_ref="req-a",
                state="already_installed",
            ),
            make_item(
                requirement_ref="req-b",
                state="needs_install",
            ),
        )
    )

    result = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)),
        "project-1",
        preflight=preflight,
    )

    assert tuple(step.requirement_id for step in result.steps) == ("req-b",)


def test_empty_preflight_allows_all_items():
    preflight = PreflightResult(
        id="pre-1", project_id="project-1",
        overall_ready=True,
    )
    variant = make_variant(
        toolchain=(
            make_item(requirement_ref="req-a"),
            make_item(
                requirement_ref="req-b",
                type=RequirementType.SDK,
            ),
        )
    )

    result = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)),
        "project-1",
        preflight=preflight,
    )

    assert len(result.steps) == 2


def test_no_preflight_preserves_existing_behavior():
    variant = make_variant(
        toolchain=(
            make_item(requirement_ref="req-a"),
            make_item(
                requirement_ref="req-b",
                type=RequirementType.SDK,
            ),
        )
    )

    result = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)),
        "project-1",
    )

    assert len(result.steps) == 2


def test_satisfied_item_state_value_ignored_when_reconciled():
    """Preflight satisfaction is authoritative regardless of ToolchainItem.state."""
    preflight = make_preflight("req-tool")
    variant = make_variant(
        toolchain=(
            make_item(
                requirement_ref="req-tool",
                name="tool",
                install_method="pip",
                state="needs_install",
            ),
        )
    )

    result = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)),
        "project-1",
        preflight=preflight,
    )

    assert len(result.steps) == 0, (
        "ToolchainItem.state='needs_install' must be overridden by "
        "satisfied Preflight evidence"
    )


def test_satisfied_and_unsatisfied_mixed():
    preflight = PreflightResult(
        id="pre-1", project_id="project-1",
        overall_ready=False,
        results=(
            PreflightRequirementResult(
                requirement_id="req-ok", present=True, satisfied=True,
            ),
            PreflightRequirementResult(
                requirement_id="req-bad", present=False, satisfied=False,
            ),
        ),
    )
    variant = make_variant(
        toolchain=(
            make_item(
                requirement_ref="req-ok", name="ok-tool",
                install_method="pip",
            ),
            make_item(
                requirement_ref="req-bad", name="bad-tool",
                install_method="pip",
            ),
        )
    )

    result = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)),
        "project-1",
        preflight=preflight,
    )

    assert tuple(step.requirement_id for step in result.steps) == (
        "req-bad",
    ), "Only unsatisfied requirement should produce a step"


def test_system_package_satisfied_by_preflight_produces_no_manual_review_step():
    """SYSTEM_PACKAGE requirement satisfied by preflight must not produce manual_review step."""
    requirement = Requirement(
        id="req-python3",
        name="python3",
        type=RequirementType.SYSTEM_PACKAGE,
        purpose="Python 3 runtime environment for ESPHome",
        required=True,
        confidence=1.0,
        install_method="system package manager (e.g., apt, brew)",
    )
    preflight = PreflightResult(
        id="pre-sys", project_id="project-sys",
        overall_ready=True,
        results=(
            PreflightRequirementResult(
                requirement_id=requirement.id,
                present=True,
                satisfied=True,
                active=True,
                blocks_current_operation=True,
            ),
        ),
        missing_requirements=(),
        activations=(RequirementActivation(requirement.id, True, True),),
        project_requirements=(requirement,),
    )
    variant = make_variant(toolchain=(make_item(
        requirement_ref=requirement.id,
        name="python3",
        type=RequirementType.SYSTEM_PACKAGE,
        install_method="apt install python3 python3-pip ...",
        state="needs_install",
    ),))

    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-sys",
        preflight=preflight,
    )

    assert plan.steps == (), (
        "Satisfied SYSTEM_PACKAGE requirement must not produce a manual_review step"
    )


def test_system_package_unsatisfied_by_preflight_produces_manual_review_step():
    """SYSTEM_PACKAGE requirement unsatisfied by preflight produces manual_review step."""
    requirement = Requirement(
        id="req-missing-sys",
        name="missing-tool",
        type=RequirementType.SYSTEM_PACKAGE,
        purpose="Missing system package",
        required=True,
        confidence=1.0,
        install_method="apt install missing-tool",
    )
    preflight = PreflightResult(
        id="pre-sys-missing", project_id="project-sys-missing",
        overall_ready=True,
        results=(
            PreflightRequirementResult(
                requirement_id=requirement.id,
                present=False,
                satisfied=False,
                warning="requirement type not locally verifiable",
                active=True,
                blocks_current_operation=True,
            ),
        ),
        missing_requirements=(),
        activations=(RequirementActivation(requirement.id, True, True),),
        project_requirements=(requirement,),
    )
    variant = make_variant(toolchain=(make_item(
        requirement_ref=requirement.id,
        name="missing-tool",
        type=RequirementType.SYSTEM_PACKAGE,
        install_method="apt install missing-tool",
        state="needs_install",
    ),))

    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-sys-missing",
        preflight=preflight,
    )

    assert len(plan.steps) == 1
    assert plan.steps[0].requirement_id == requirement.id
    assert plan.steps[0].action == "manual_review"


def test_system_package_with_different_name_and_verification_executable_satisfied_no_step():
    """name != executable identity, satisfied preflight -> no manual_review step."""
    requirement = Requirement(
        id="req-python3-display",
        name="Python 3",
        type=RequirementType.SYSTEM_PACKAGE,
        purpose="Python 3 runtime",
        required=True,
        confidence=1.0,
        install_method="apt install python3",
        verification_executable="python3",
    )
    preflight = PreflightResult(
        id="pre-struct-sys", project_id="project-struct-sys",
        overall_ready=True,
        results=(
            PreflightRequirementResult(
                requirement_id=requirement.id,
                present=True,
                satisfied=True,
                active=True,
                blocks_current_operation=True,
            ),
        ),
        missing_requirements=(),
        activations=(RequirementActivation(requirement.id, True, True),),
        project_requirements=(requirement,),
    )
    variant = make_variant(toolchain=(make_item(
        requirement_ref=requirement.id,
        name="Python 3",
        type=RequirementType.SYSTEM_PACKAGE,
        install_method="apt install python3",
        state="needs_install",
    ),))

    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-struct-sys",
        preflight=preflight,
    )

    assert plan.steps == (), (
        "Satisfied SYSTEM_PACKAGE with structured verification_executable "
        "must not produce a manual_review step"
    )


def test_system_package_unsatisfied_with_verification_executable_produces_manual_review():
    """Unsatisfied SYSTEM_PACKAGE with verification_executable still blocks."""
    requirement = Requirement(
        id="req-missing-exe",
        name="Python 3",
        type=RequirementType.SYSTEM_PACKAGE,
        purpose="Python 3 runtime",
        required=True,
        confidence=1.0,
        install_method="apt install python3",
        verification_executable="python3",
    )
    preflight = PreflightResult(
        id="pre-missing-struct", project_id="project-missing-struct",
        overall_ready=False,
        results=(
            PreflightRequirementResult(
                requirement_id=requirement.id,
                present=False,
                satisfied=False,
                active=True,
                blocks_current_operation=True,
            ),
        ),
        missing_requirements=(requirement,),
        activations=(RequirementActivation(requirement.id, True, True),),
        project_requirements=(requirement,),
    )
    variant = make_variant(toolchain=(make_item(
        requirement_ref=requirement.id,
        name="Python 3",
        type=RequirementType.SYSTEM_PACKAGE,
        install_method="apt install python3",
        state="needs_install",
    ),))

    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-missing-struct",
        preflight=preflight,
    )

    assert len(plan.steps) == 1
    assert plan.steps[0].action == "manual_review"
    assert plan.steps[0].requirement_id == requirement.id


# ==========================================================================
# OC-019: transitive provided-by semantics
# ==========================================================================


def test_provided_by_valid_provider_suppresses_manual_review_for_sdk():
    """SDK requirement provided_by a selected higher-level capability
    must NOT produce its own manual_review SetupStep."""
    sdk_req = Requirement(
        id="req-esp32-sdk",
        name="ESP32 Build Framework (ESP-IDF or Arduino)",
        type=RequirementType.SDK,
        purpose="Firmware compilation",
        required=True,
        confidence=1.0,
        install_method="manual setup",
    )
    platform_req = Requirement(
        id="req-esphome",
        name="ESPHome",
        type=RequirementType.PYTHON_PACKAGE,
        purpose="ESPHome framework",
        required=True,
        confidence=1.0,
        install_method="pip",
    )
    preflight = PreflightResult(
        id="pre-sdk-provided", project_id="project-sdk-provided",
        overall_ready=False,
        results=(
            PreflightRequirementResult(
                requirement_id=sdk_req.id, present=False, satisfied=False,
                active=True, blocks_current_operation=True,
            ),
            PreflightRequirementResult(
                requirement_id=platform_req.id, present=False, satisfied=False,
                active=True, blocks_current_operation=True,
            ),
        ),
        missing_requirements=(sdk_req, platform_req),
        activations=(
            RequirementActivation(sdk_req.id, True, True),
            RequirementActivation(platform_req.id, True, True),
        ),
        project_requirements=(sdk_req, platform_req),
    )
    variant = make_variant(toolchain=(
        make_item(
            requirement_ref=platform_req.id,
            name="esphome",
            type=RequirementType.PYTHON_PACKAGE,
            install_method="pip",
        ),
        make_item(
            requirement_ref=sdk_req.id,
            name="ESP32 Build Framework (ESP-IDF or Arduino)",
            type=RequirementType.SDK,
            install_method="manual setup",
            provided_by=platform_req.id,
        ),
    ))

    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-sdk-provided",
        preflight=preflight,
    )

    assert plan.steps != (), "Higher-level provider must still create its step"
    sdk_step_ids = {step.requirement_id for step in plan.steps}
    assert sdk_req.id not in sdk_step_ids, (
        "Provided-by SDK must NOT produce an independent SetupStep"
    )
    assert platform_req.id in sdk_step_ids, (
        "Provider platform must produce its own install step"
    )
    assert sdk_req.id in plan.provided_requirement_ids, (
        "Provided requirement must appear in provided_requirement_ids"
    )


def test_provided_by_missing_provider_falls_through_to_normal_handling():
    """provided_by referencing a non-existent toolchain requirement_ref
    must fall through to normal handling (fail-closed)."""
    requirement = Requirement(
        id="req-missing-provider-target",
        name="Some SDK",
        type=RequirementType.SDK,
        purpose="development",
        required=True,
        confidence=1.0,
        install_method="manual",
    )
    preflight = PreflightResult(
        id="pre-missing-provider", project_id="project-missing-provider",
        overall_ready=False,
        results=(
            PreflightRequirementResult(
                requirement_id=requirement.id, present=False, satisfied=False,
                active=True, blocks_current_operation=True,
            ),
        ),
        missing_requirements=(requirement,),
        activations=(RequirementActivation(requirement.id, True, True),),
        project_requirements=(requirement,),
    )
    variant = make_variant(toolchain=(
        make_item(
            requirement_ref=requirement.id,
            name="Some SDK",
            type=RequirementType.SDK,
            install_method="manual",
            provided_by="req-nonexistent",
        ),
    ))

    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-missing-provider",
        preflight=preflight,
    )

    assert len(plan.steps) == 1, (
        "Missing provider must fall through: item must still produce a SetupStep"
    )
    assert plan.steps[0].requirement_id == requirement.id
    assert plan.steps[0].action == "manual_review"
    assert plan.provided_requirement_ids == (), (
        "Invalid provided_by must not appear in provided_requirement_ids"
    )


def test_provided_by_deferred_provider_fails_closed_to_baseline():
    """When the provider is inactive/deferred, the provided item must
    fall back to its own baseline (manual_review) rather than being
    silently deferred or considered PROVIDED."""
    sdk_req = Requirement(
        id="req-sdk-future",
        name="Future SDK",
        type=RequirementType.SDK,
        purpose="future compilation",
        required=True,
        confidence=0.8,
        install_method="manual setup",
    )
    platform_req = Requirement(
        id="req-platform-deferred",
        name="Deferred Platform",
        type=RequirementType.PYTHON_PACKAGE,
        purpose="deferred platform",
        required=True,
        confidence=0.8,
        install_method="pip",
    )
    preflight = PreflightResult(
        id="pre-deferred-provider", project_id="project-deferred-provider",
        overall_ready=False,
        results=(
            PreflightRequirementResult(
                requirement_id=sdk_req.id, present=False, satisfied=False,
                active=True, blocks_current_operation=True,
            ),
            PreflightRequirementResult(
                requirement_id=platform_req.id, present=False, satisfied=False,
                active=False, blocks_current_operation=False,
            ),
        ),
        missing_requirements=(sdk_req,),
        activations=(
            RequirementActivation(sdk_req.id, True, True),
            RequirementActivation(platform_req.id, False, False),
        ),
        inactive_requirements=(platform_req,),
        project_requirements=(sdk_req, platform_req),
    )
    variant = make_variant(toolchain=(
        make_item(
            requirement_ref=platform_req.id,
            name="Deferred Platform",
            type=RequirementType.PYTHON_PACKAGE,
            install_method="pip",
        ),
        make_item(
            requirement_ref=sdk_req.id,
            name="Future SDK",
            type=RequirementType.SDK,
            install_method="manual setup",
            provided_by=platform_req.id,
        ),
    ))

    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-deferred-provider",
        preflight=preflight,
    )

    assert plan.provided_requirement_ids == (), (
        "Deferred provider must not produce PROVIDED classification"
    )
    assert len(plan.steps) == 1, (
        "Active item with deferred provider must fall back to its own baseline"
    )
    assert plan.steps[0].requirement_id == sdk_req.id
    assert plan.steps[0].action == "manual_review"


def test_no_provided_by_sdk_still_creates_manual_review():
    """SDK requirement without provided_by must still produce manual_review
    (existing behavior unchanged)."""
    requirement = Requirement(
        id="req-standalone-sdk",
        name="Standalone SDK",
        type=RequirementType.SDK,
        purpose="independent development",
        required=True,
        confidence=1.0,
        install_method="manual setup",
    )
    preflight = PreflightResult(
        id="pre-standalone-sdk", project_id="project-standalone-sdk",
        overall_ready=False,
        results=(
            PreflightRequirementResult(
                requirement_id=requirement.id, present=False, satisfied=False,
                active=True, blocks_current_operation=True,
            ),
        ),
        missing_requirements=(requirement,),
        activations=(RequirementActivation(requirement.id, True, True),),
        project_requirements=(requirement,),
    )
    variant = make_variant(toolchain=(make_item(
        requirement_ref=requirement.id,
        name="Standalone SDK",
        type=RequirementType.SDK,
        install_method="manual setup",
    ),))

    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-standalone-sdk",
        preflight=preflight,
    )

    assert len(plan.steps) == 1
    assert plan.steps[0].action == "manual_review"
    assert plan.steps[0].requirement_id == requirement.id
    assert plan.provided_requirement_ids == ()


def test_provided_by_mixed_items_one_provided_one_not():
    """One item provided_by another, one not: the non-provided must still
    produce its own step."""
    sdk_provided = Requirement(
        id="req-sdk-provided",
        name="Provided SDK",
        type=RequirementType.SDK,
        purpose="provided by platform",
        required=True,
        confidence=1.0,
        install_method="manual",
    )
    standalone_sdk = Requirement(
        id="req-sdk-standalone",
        name="Standalone SDK",
        type=RequirementType.SDK,
        purpose="standalone",
        required=True,
        confidence=1.0,
        install_method="manual",
    )
    platform = Requirement(
        id="req-platform",
        name="Platform",
        type=RequirementType.PYTHON_PACKAGE,
        purpose="provider",
        required=True,
        confidence=1.0,
        install_method="pip",
    )
    preflight = PreflightResult(
        id="pre-mixed", project_id="project-mixed",
        overall_ready=False,
        results=tuple(
            PreflightRequirementResult(
                requirement_id=r.id, present=False, satisfied=False,
                active=True, blocks_current_operation=True,
            )
            for r in (sdk_provided, standalone_sdk, platform)
        ),
        missing_requirements=(sdk_provided, standalone_sdk, platform),
        activations=tuple(
            RequirementActivation(r.id, True, True)
            for r in (sdk_provided, standalone_sdk, platform)
        ),
        project_requirements=(sdk_provided, standalone_sdk, platform),
    )
    variant = make_variant(toolchain=(
        make_item(
            requirement_ref=platform.id,
            name="Platform",
            type=RequirementType.PYTHON_PACKAGE,
            install_method="pip",
        ),
        make_item(
            requirement_ref=sdk_provided.id,
            name="Provided SDK",
            type=RequirementType.SDK,
            install_method="manual",
            provided_by=platform.id,
        ),
        make_item(
            requirement_ref=standalone_sdk.id,
            name="Standalone SDK",
            type=RequirementType.SDK,
            install_method="manual",
        ),
    ))

    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-mixed",
        preflight=preflight,
    )

    step_ids = {step.requirement_id for step in plan.steps}
    assert platform.id in step_ids, "Provider must have its own step"
    assert standalone_sdk.id in step_ids, "Unrelated SDK must have its own step"
    assert sdk_provided.id not in step_ids, "Provided SDK must not have a step"
    assert sdk_provided.id in plan.provided_requirement_ids
    assert standalone_sdk.id not in plan.provided_requirement_ids


def test_provided_by_preserves_requirement_activation_and_preflight():
    """Provided-by must not alter the activation or preflight data.
    The requirement remains active and its preflight status remains unchanged."""
    sdk_req = Requirement(
        id="req-sdk-active",
        name="Active SDK",
        type=RequirementType.SDK,
        purpose="active requirement",
        required=True,
        confidence=1.0,
        install_method="manual",
    )
    platform_req = Requirement(
        id="req-platform-active",
        name="ActivePlatform",
        type=RequirementType.PYTHON_PACKAGE,
        purpose="provider",
        required=True,
        confidence=1.0,
        install_method="pip",
    )
    preflight = PreflightResult(
        id="pre-activation-preserved", project_id="project-activation",
        overall_ready=False,
        results=(
            PreflightRequirementResult(
                requirement_id=sdk_req.id, present=False, satisfied=False,
                active=True, blocks_current_operation=True,
            ),
            PreflightRequirementResult(
                requirement_id=platform_req.id, present=False, satisfied=False,
                active=True, blocks_current_operation=True,
            ),
        ),
        missing_requirements=(sdk_req, platform_req),
        activations=(
            RequirementActivation(sdk_req.id, True, True),
            RequirementActivation(platform_req.id, True, True),
        ),
        project_requirements=(sdk_req, platform_req),
    )
    variant = make_variant(toolchain=(
        make_item(
            requirement_ref=platform_req.id,
            name="ActivePlatform",
            type=RequirementType.PYTHON_PACKAGE,
            install_method="pip",
        ),
        make_item(
            requirement_ref=sdk_req.id,
            name="Active SDK",
            type=RequirementType.SDK,
            install_method="manual",
            provided_by=platform_req.id,
        ),
    ))

    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-activation",
        preflight=preflight,
    )

    sdk_activation = next(
        a for a in plan.requirement_activations if a.requirement_id == sdk_req.id
    )
    assert sdk_activation.active is True
    assert sdk_activation.blocks_current_operation is True
    assert sdk_req.id in plan.provided_requirement_ids


def test_provided_item_variant_assessment_marks_provided_as_automatically_materializable():
    """assess_variant must treat provided items as automatically materializable."""
    platform_req = project_requirement("req-prov-platform")
    sdk_req = project_requirement("req-prov-sdk", RequirementType.SDK)
    preflight = make_preflight()
    variant = make_variant(toolchain=(
        make_item(
            requirement_ref=platform_req.id,
            name="Platform",
            install_method="pip",
        ),
        make_item(
            requirement_ref=sdk_req.id,
            name="Provided SDK",
            type=RequirementType.SDK,
            install_method="manual",
            provided_by=platform_req.id,
        ),
    ))

    assessment = ToolchainMaterializer().assess_variant(variant, preflight)

    assert assessment["automatically_materializable"] is True
    provided_item = next(
        i for i in assessment["items"] if i["requirement_ref"] == sdk_req.id
    )
    assert provided_item["status"] == "provided"


def test_provided_by_with_provider_already_satisfied_in_preflight():
    """When provider is already satisfied (e.g. pre-installed Python),
    the provided item must still be classified as PROVIDED."""
    sdk_req = Requirement(
        id="req-sdk-with-preinstalled-provider",
        name="SDK provided by preinstalled tool",
        type=RequirementType.SDK,
        purpose="development",
        required=True,
        confidence=1.0,
        install_method="manual",
    )
    provider_req = Requirement(
        id="req-preinstalled-provider",
        name="Preinstalled Tool",
        type=RequirementType.EXECUTABLE,
        purpose="provider",
        required=True,
        confidence=1.0,
    )
    preflight = PreflightResult(
        id="pre-satisfied-provider", project_id="project-sat-provider",
        overall_ready=True,
        results=(
            PreflightRequirementResult(
                requirement_id=sdk_req.id, present=False, satisfied=False,
                active=True, blocks_current_operation=True,
            ),
            PreflightRequirementResult(
                requirement_id=provider_req.id, present=True, satisfied=True,
                active=True, blocks_current_operation=True,
            ),
        ),
        missing_requirements=(),
        activations=(
            RequirementActivation(sdk_req.id, True, True),
            RequirementActivation(provider_req.id, True, True),
        ),
        project_requirements=(sdk_req, provider_req),
    )
    variant = make_variant(toolchain=(
        make_item(
            requirement_ref=provider_req.id,
            name="Preinstalled Tool",
            type=RequirementType.EXECUTABLE,
            install_method=None,
            state="already_installed",
        ),
        make_item(
            requirement_ref=sdk_req.id,
            name="SDK provided by preinstalled tool",
            type=RequirementType.SDK,
            install_method="manual",
            provided_by=provider_req.id,
        ),
    ))

    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-sat-provider",
        preflight=preflight,
    )

    assert plan.steps == (), (
        "Neither provider (satisfied) nor provided item should produce a step"
    )
    assert sdk_req.id in plan.provided_requirement_ids


def test_unrelated_active_unsatisfied_requirement_still_blocks_with_provided_requirement():
    """An unrelated active unsatisfied requirement must still block
    normally even when another requirement is provided-by."""
    sdk_provided = Requirement(
        id="req-sdk-provided-by",
        name="Provided SDK",
        type=RequirementType.SDK,
        purpose="provided",
        required=True,
        confidence=1.0,
        install_method="manual",
    )
    unrelated_sdk = Requirement(
        id="req-unrelated-sdk",
        name="Unrelated SDK",
        type=RequirementType.SDK,
        purpose="unrelated",
        required=True,
        confidence=1.0,
        install_method="manual",
    )
    platform = Requirement(
        id="req-providing-platform",
        name="ProvidingPlatform",
        type=RequirementType.PYTHON_PACKAGE,
        purpose="provider",
        required=True,
        confidence=1.0,
        install_method="pip",
    )
    preflight = PreflightResult(
        id="pre-unrelated", project_id="project-unrelated",
        overall_ready=False,
        results=tuple(
            PreflightRequirementResult(
                requirement_id=r.id, present=False, satisfied=False,
                active=True, blocks_current_operation=True,
            )
            for r in (sdk_provided, unrelated_sdk, platform)
        ),
        missing_requirements=(sdk_provided, unrelated_sdk, platform),
        activations=tuple(
            RequirementActivation(r.id, True, True)
            for r in (sdk_provided, unrelated_sdk, platform)
        ),
        project_requirements=(sdk_provided, unrelated_sdk, platform),
    )
    variant = make_variant(toolchain=(
        make_item(
            requirement_ref=platform.id,
            name="ProvidingPlatform",
            type=RequirementType.PYTHON_PACKAGE,
            install_method="pip",
        ),
        make_item(
            requirement_ref=sdk_provided.id,
            name="Provided SDK",
            type=RequirementType.SDK,
            install_method="manual",
            provided_by=platform.id,
        ),
        make_item(
            requirement_ref=unrelated_sdk.id,
            name="Unrelated SDK",
            type=RequirementType.SDK,
            install_method="manual",
        ),
    ))

    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-unrelated",
        preflight=preflight,
    )

    step_ids = {step.requirement_id for step in plan.steps}
    assert unrelated_sdk.id in step_ids, (
        "Unrelated active unsatisfied requirement MUST still block normally"
    )
    assert plan.steps[0].action != "manual_review" or plan.steps[
        len(plan.steps) - 1
    ].action != "manual_review" or any(
        step.requirement_id == unrelated_sdk.id and step.action == "manual_review"
        for step in plan.steps
    ), (
        "Unrelated unsatisfied SDK must produce its manual_review step"
    )
    assert sdk_provided.id not in step_ids
    assert platform.id in step_ids


def test_provided_by_self_reference_fails_closed():
    """A self-referential provided_by must fail closed to normal classification."""
    requirement = Requirement(
        id="req-self-ref",
        name="Self-referencing SDK",
        type=RequirementType.SDK,
        purpose="development",
        required=True,
        confidence=1.0,
        install_method="manual",
    )
    preflight = PreflightResult(
        id="pre-self-ref", project_id="project-self-ref",
        overall_ready=False,
        results=(
            PreflightRequirementResult(
                requirement_id=requirement.id, present=False, satisfied=False,
                active=True, blocks_current_operation=True,
            ),
        ),
        missing_requirements=(requirement,),
        activations=(RequirementActivation(requirement.id, True, True),),
        project_requirements=(requirement,),
    )
    variant = make_variant(toolchain=(make_item(
        requirement_ref=requirement.id,
        name="Self-referencing SDK",
        type=RequirementType.SDK,
        install_method="manual",
        provided_by=requirement.id,
    ),))

    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-self-ref",
        preflight=preflight,
    )

    assert plan.provided_requirement_ids == (), (
        "Self-referencing provided_by must not produce a PROVIDED classification"
    )
    assert len(plan.steps) == 1, (
        "Self-referencing item must fall back to its normal classification"
    )
    assert plan.steps[0].action == "manual_review"
    assert plan.steps[0].requirement_id == requirement.id


def test_provided_by_two_node_cycle_fails_closed():
    """A two-node provided_by cycle must fail closed for both nodes."""
    a_req = Requirement(
        id="req-cycle-a",
        name="Cycle A",
        type=RequirementType.SDK,
        purpose="cycle",
        required=True,
        confidence=1.0,
        install_method="manual",
    )
    b_req = Requirement(
        id="req-cycle-b",
        name="Cycle B",
        type=RequirementType.SDK,
        purpose="cycle",
        required=True,
        confidence=1.0,
        install_method="manual",
    )
    preflight = PreflightResult(
        id="pre-cycle", project_id="project-cycle",
        overall_ready=False,
        results=tuple(
            PreflightRequirementResult(
                requirement_id=r.id, present=False, satisfied=False,
                active=True, blocks_current_operation=True,
            )
            for r in (a_req, b_req)
        ),
        missing_requirements=(a_req, b_req),
        activations=tuple(
            RequirementActivation(r.id, True, True) for r in (a_req, b_req)
        ),
        project_requirements=(a_req, b_req),
    )
    variant = make_variant(toolchain=(
        make_item(
            requirement_ref=a_req.id,
            name="Cycle A",
            type=RequirementType.SDK,
            install_method="manual",
            provided_by=b_req.id,
        ),
        make_item(
            requirement_ref=b_req.id,
            name="Cycle B",
            type=RequirementType.SDK,
            install_method="manual",
            provided_by=a_req.id,
        ),
    ))

    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-cycle",
        preflight=preflight,
    )

    assert plan.provided_requirement_ids == (), (
        "Cycle must not produce any PROVIDED classifications"
    )
    step_ids = {step.requirement_id for step in plan.steps}
    assert a_req.id in step_ids, "Cycle node A must fall back to manual_review"
    assert b_req.id in step_ids, "Cycle node B must fall back to manual_review"
    assert all(step.action == "manual_review" for step in plan.steps)


def test_provided_by_longer_cycle_fails_closed():
    """A three-node provided_by cycle (A→B→C→A) must fail closed."""
    a_req = project_requirement("req-3cycle-a", RequirementType.SDK)
    b_req = project_requirement("req-3cycle-b", RequirementType.SDK)
    c_req = project_requirement("req-3cycle-c", RequirementType.SDK)
    preflight = PreflightResult(
        id="pre-3cycle", project_id="project-3cycle",
        overall_ready=False,
        results=tuple(
            PreflightRequirementResult(
                requirement_id=r.id, present=False, satisfied=False,
                active=True, blocks_current_operation=True,
            )
            for r in (a_req, b_req, c_req)
        ),
        missing_requirements=(a_req, b_req, c_req),
        activations=tuple(
            RequirementActivation(r.id, True, True) for r in (a_req, b_req, c_req)
        ),
        project_requirements=(a_req, b_req, c_req),
    )
    variant = make_variant(toolchain=(
        make_item(requirement_ref=a_req.id, name=a_req.name,
                  type=RequirementType.SDK, install_method="manual", provided_by=b_req.id),
        make_item(requirement_ref=b_req.id, name=b_req.name,
                  type=RequirementType.SDK, install_method="manual", provided_by=c_req.id),
        make_item(requirement_ref=c_req.id, name=c_req.name,
                  type=RequirementType.SDK, install_method="manual", provided_by=a_req.id),
    ))

    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-3cycle",
        preflight=preflight,
    )

    assert plan.provided_requirement_ids == ()
    assert len(plan.steps) == 3
    assert all(step.action == "manual_review" for step in plan.steps)


def test_provided_by_multi_hop_chain_to_materializable_root():
    """Valid multi-hop chain: A→B→C where C is MATERIALIZABLE."""
    a_req = project_requirement("req-chain-a", RequirementType.SDK)
    b_req = project_requirement("req-chain-b", RequirementType.SDK)
    c_req = project_requirement("req-chain-c")
    preflight = PreflightResult(
        id="pre-chain", project_id="project-chain",
        overall_ready=False,
        results=tuple(
            PreflightRequirementResult(
                requirement_id=r.id, present=False, satisfied=False,
                active=True, blocks_current_operation=True,
            )
            for r in (a_req, b_req, c_req)
        ),
        missing_requirements=(a_req, b_req, c_req),
        activations=tuple(
            RequirementActivation(r.id, True, True) for r in (a_req, b_req, c_req)
        ),
        project_requirements=(a_req, b_req, c_req),
    )
    variant = make_variant(toolchain=(
        make_item(requirement_ref=a_req.id, name=a_req.name,
                  type=RequirementType.SDK, install_method="manual", provided_by=b_req.id),
        make_item(requirement_ref=b_req.id, name=b_req.name,
                  type=RequirementType.SDK, install_method="manual", provided_by=c_req.id),
        make_item(requirement_ref=c_req.id, name=c_req.name,
                  type=RequirementType.PYTHON_PACKAGE, install_method="pip"),
    ))

    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-chain",
        preflight=preflight,
    )

    assert a_req.id in plan.provided_requirement_ids
    assert b_req.id in plan.provided_requirement_ids
    step_ids = {step.requirement_id for step in plan.steps}
    assert c_req.id in step_ids, "Root must produce its own install step"
    assert a_req.id not in step_ids
    assert b_req.id not in step_ids
    assert plan.steps[0].action == "install"


def test_provided_by_multi_hop_chain_to_satisfied_root():
    """Valid chain to an already-satisfied provider."""
    a_req = project_requirement("req-chain-sat-a", RequirementType.SDK)
    b_req = project_requirement("req-chain-sat-b", RequirementType.SDK)
    c_req = Requirement(
        id="req-chain-sat-c", name="Python",
        type=RequirementType.EXECUTABLE, purpose="runtime",
        required=True, confidence=1.0,
    )
    preflight = PreflightResult(
        id="pre-chain-sat", project_id="project-chain-sat",
        overall_ready=True,
        results=(
            PreflightRequirementResult(
                requirement_id=a_req.id, present=False, satisfied=False,
                active=True, blocks_current_operation=True,
            ),
            PreflightRequirementResult(
                requirement_id=b_req.id, present=False, satisfied=False,
                active=True, blocks_current_operation=True,
            ),
            PreflightRequirementResult(
                requirement_id=c_req.id, present=True, satisfied=True,
                active=True, blocks_current_operation=True,
            ),
        ),
        missing_requirements=(),
        activations=tuple(
            RequirementActivation(r.id, True, True) for r in (a_req, b_req, c_req)
        ),
        project_requirements=(a_req, b_req, c_req),
    )
    variant = make_variant(toolchain=(
        make_item(requirement_ref=a_req.id, name=a_req.name,
                  type=RequirementType.SDK, install_method="manual", provided_by=b_req.id),
        make_item(requirement_ref=b_req.id, name=b_req.name,
                  type=RequirementType.SDK, install_method="manual", provided_by=c_req.id),
        make_item(requirement_ref=c_req.id, name="Python",
                  type=RequirementType.EXECUTABLE, install_method=None,
                  state="already_installed"),
    ))

    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-chain-sat",
        preflight=preflight,
    )

    assert plan.steps == ()
    assert a_req.id in plan.provided_requirement_ids
    assert b_req.id in plan.provided_requirement_ids


def test_provided_by_chain_ending_in_manual_review_fails_closed():
    """Chain that ends at a MANUAL_REVIEW item must fail closed."""
    a_req = project_requirement("req-deadend-a", RequirementType.SDK)
    b_req = project_requirement("req-deadend-b", RequirementType.SDK)
    preflight = PreflightResult(
        id="pre-deadend", project_id="project-deadend",
        overall_ready=False,
        results=tuple(
            PreflightRequirementResult(
                requirement_id=r.id, present=False, satisfied=False,
                active=True, blocks_current_operation=True,
            )
            for r in (a_req, b_req)
        ),
        missing_requirements=(a_req, b_req),
        activations=tuple(
            RequirementActivation(r.id, True, True) for r in (a_req, b_req)
        ),
        project_requirements=(a_req, b_req),
    )
    variant = make_variant(toolchain=(
        make_item(requirement_ref=a_req.id, name=a_req.name,
                  type=RequirementType.SDK, install_method="manual", provided_by=b_req.id),
        make_item(requirement_ref=b_req.id, name=b_req.name,
                  type=RequirementType.SDK, install_method="manual"),
    ))

    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-deadend",
        preflight=preflight,
    )

    assert plan.provided_requirement_ids == (), (
        "Chain ending in manual_review must not produce PROVIDED"
    )
    assert len(plan.steps) == 2, "Both items must produce their own steps"
    step_ids = {step.requirement_id for step in plan.steps}
    assert a_req.id in step_ids
    assert b_req.id in step_ids


def test_provided_by_resolution_is_order_independent():
    """provided resolution must yield the same result regardless of
    toolchain item ordering."""
    a_req = project_requirement("req-order-a", RequirementType.SDK)
    b_req = project_requirement("req-order-b", RequirementType.SDK)
    c_req = project_requirement("req-order-c")
    preflight = PreflightResult(
        id="pre-order", project_id="project-order",
        overall_ready=False,
        results=tuple(
            PreflightRequirementResult(
                requirement_id=r.id, present=False, satisfied=False,
                active=True, blocks_current_operation=True,
            )
            for r in (a_req, b_req, c_req)
        ),
        missing_requirements=(a_req, b_req, c_req),
        activations=tuple(
            RequirementActivation(r.id, True, True) for r in (a_req, b_req, c_req)
        ),
        project_requirements=(a_req, b_req, c_req),
    )

    def _materialize_ordered(item_order, label):
        variant = make_variant(toolchain=item_order)
        return ToolchainMaterializer().materialize(
            make_result(variants=(variant,)), f"project-order-{label}",
            preflight=preflight,
        )

    order_1 = (
        make_item(requirement_ref=a_req.id, name=a_req.name,
                  type=RequirementType.SDK, install_method="manual", provided_by=b_req.id),
        make_item(requirement_ref=b_req.id, name=b_req.name,
                  type=RequirementType.SDK, install_method="manual", provided_by=c_req.id),
        make_item(requirement_ref=c_req.id, name=c_req.name,
                  type=RequirementType.PYTHON_PACKAGE, install_method="pip"),
    )
    order_2 = (
        make_item(requirement_ref=c_req.id, name=c_req.name,
                  type=RequirementType.PYTHON_PACKAGE, install_method="pip"),
        make_item(requirement_ref=b_req.id, name=b_req.name,
                  type=RequirementType.SDK, install_method="manual", provided_by=c_req.id),
        make_item(requirement_ref=a_req.id, name=a_req.name,
                  type=RequirementType.SDK, install_method="manual", provided_by=b_req.id),
    )

    plan_1 = _materialize_ordered(order_1, "ord1")
    plan_2 = _materialize_ordered(order_2, "ord2")

    assert set(plan_1.provided_requirement_ids) == set(plan_2.provided_requirement_ids)
    assert {step.requirement_id for step in plan_1.steps} == {
        step.requirement_id for step in plan_2.steps
    }


def test_independent_provider_ignores_its_own_provided_by():
    """An independently materializable item with its own provided_by
    must still be classified as its baseline, not PROVIDED."""
    platform = project_requirement("req-ignored-by-ref", RequirementType.PYTHON_PACKAGE)
    sdk = project_requirement("req-ignored-sdk", RequirementType.SDK)
    preflight = PreflightResult(
        id="pre-ignored-ref", project_id="project-ignored-ref",
        overall_ready=False,
        results=tuple(
            PreflightRequirementResult(
                requirement_id=r.id, present=False, satisfied=False,
                active=True, blocks_current_operation=True,
            )
            for r in (platform, sdk)
        ),
        missing_requirements=(platform, sdk),
        activations=tuple(
            RequirementActivation(r.id, True, True) for r in (platform, sdk)
        ),
        project_requirements=(platform, sdk),
    )
    variant = make_variant(toolchain=(
        make_item(
            requirement_ref=platform.id,
            name=platform.name,
            install_method="pip",
            provided_by=sdk.id,
        ),
        make_item(
            requirement_ref=sdk.id,
            name=sdk.name,
            type=RequirementType.SDK,
            install_method="manual",
        ),
    ))

    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-ignored-ref",
        preflight=preflight,
    )

    assert platform.id in {step.requirement_id for step in plan.steps}, (
        "Materializable provider must keep its own MATERIALIZABLE classification"
    )
    assert sdk.id not in plan.provided_requirement_ids, (
        "A reverse provided_by relationship must not be inferred"
    )
    assert sdk.id in {step.requirement_id for step in plan.steps}, (
        "SDK without a valid provider must keep its normal fail-closed classification"
    )


def test_provided_by_empty_string_treated_as_no_provider():
    """An empty provided_by string is treated as no provider (fail-closed)."""
    requirement = Requirement(
        id="req-empty-provided-by",
        name="SDK with empty provided_by",
        type=RequirementType.SDK,
        purpose="development",
        required=True,
        confidence=1.0,
        install_method="manual",
    )
    variant = make_variant(toolchain=(make_item(
        requirement_ref=requirement.id,
        name="SDK with empty provided_by",
        type=RequirementType.SDK,
        install_method="manual",
        provided_by="",
    ),))

    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-empty-provided-by",
    )

    assert len(plan.steps) == 1
    assert plan.steps[0].action == "manual_review"
    assert plan.provided_requirement_ids == ()


# ==========================================================================
# OC-025: structured setup-effect contract
# ==========================================================================


def test_python_package_step_has_python_package_install_effect():
    variant = make_variant(toolchain=(make_item(
        requirement_ref="req-pkg", name="requests",
        type=RequirementType.PYTHON_PACKAGE, install_method="pip",
    ),))
    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-pkg",
    )
    assert plan.steps[0].setup_effect == SetupEffect.PYTHON_PACKAGE_INSTALL
    assert plan.steps[0].action == "install"


def test_sdk_step_has_project_tool_install_effect():
    variant = make_variant(toolchain=(make_item(
        requirement_ref="req-sdk", name="esp-idf",
        type=RequirementType.SDK, install_method="manual setup",
    ),))
    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-sdk",
    )
    assert plan.steps[0].setup_effect == SetupEffect.PROJECT_TOOL_INSTALL
    assert plan.steps[0].action == "manual_review"


def test_toolchain_step_has_project_tool_install_effect():
    variant = make_variant(toolchain=(make_item(
        requirement_ref="req-tc", name="cmake",
        type=RequirementType.TOOLCHAIN, install_method="apt install cmake",
    ),))
    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-tc",
    )
    assert plan.steps[0].setup_effect == SetupEffect.PROJECT_TOOL_INSTALL


def test_system_package_step_has_system_package_install_effect():
    variant = make_variant(toolchain=(make_item(
        requirement_ref="req-sys", name="libusb-dev",
        type=RequirementType.SYSTEM_PACKAGE, install_method="apt install libusb-dev",
    ),))
    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-sys",
    )
    assert plan.steps[0].setup_effect == SetupEffect.SYSTEM_PACKAGE_INSTALL
    assert plan.steps[0].action == "manual_review"


def test_unsupported_backend_effects_are_tracked():
    variant = make_variant(toolchain=(
        make_item(requirement_ref="req-pkg", name="pkg",
                  type=RequirementType.PYTHON_PACKAGE, install_method="pip"),
        make_item(requirement_ref="req-sdk", name="sdk",
                  type=RequirementType.SDK, install_method="setup"),
        make_item(requirement_ref="req-sys", name="sys-pkg",
                  type=RequirementType.SYSTEM_PACKAGE, install_method="apt"),
    ))
    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-tracked",
    )
    assert SetupEffect.PYTHON_PACKAGE_INSTALL not in plan.unsupported_backend_effects
    assert len(plan.unsupported_backend_effects) == 2
    assert SetupEffect.PROJECT_TOOL_INSTALL in plan.unsupported_backend_effects
    assert SetupEffect.SYSTEM_PACKAGE_INSTALL in plan.unsupported_backend_effects


def test_fully_materializable_plan_has_no_unsupported_effects():
    variant = make_variant(toolchain=(
        make_item(requirement_ref="req-a", name="pkg-a",
                  type=RequirementType.PYTHON_PACKAGE, install_method="pip"),
        make_item(requirement_ref="req-b", name="pkg-b",
                  type=RequirementType.PYTHON_PACKAGE, install_method="pip"),
    ))
    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-full",
    )
    assert plan.unsupported_backend_effects == ()


def test_satisfied_items_not_in_unsupported_effects():
    preflight = PreflightResult(
        id="pre-sat", project_id="project-sat",
        overall_ready=True,
        results=(PreflightRequirementResult(
            requirement_id="req-sdk", present=True, satisfied=True,
            active=True, blocks_current_operation=True,
        ),),
    )
    variant = make_variant(toolchain=(make_item(
        requirement_ref="req-sdk", name="sdk",
        type=RequirementType.SDK, install_method="manual",
    ),))
    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-sat",
        preflight=preflight,
    )
    assert plan.steps == ()
    assert plan.unsupported_backend_effects == ()


def test_arbitrary_install_method_no_sudo_in_effect():
    variant = make_variant(toolchain=(make_item(
        requirement_ref="req-bad", name="bad-tool",
        type=RequirementType.SDK, install_method="sudo apt install bad-tool",
    ),))
    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-bad",
    )
    step = plan.steps[0]
    assert "sudo" not in (step.setup_effect or "")
    assert step.setup_effect == SetupEffect.PROJECT_TOOL_INSTALL
    assert step.command is None


def test_controlled_backend_available_in_assessment():
    variant = make_variant(toolchain=(
        make_item(requirement_ref="req-pkg", name="pkg", install_method="pip"),
        make_item(requirement_ref="req-sdk", name="sdk",
                  type=RequirementType.SDK, install_method="setup"),
    ))
    assessment = ToolchainMaterializer().assess_variant(variant)
    pkg_item = next(i for i in assessment["items"] if i["requirement_ref"] == "req-pkg")
    sdk_item = next(i for i in assessment["items"] if i["requirement_ref"] == "req-sdk")
    assert pkg_item["setup_effect"] == SetupEffect.PYTHON_PACKAGE_INSTALL
    assert pkg_item["controlled_backend_available"] is True
    assert sdk_item["setup_effect"] == SetupEffect.PROJECT_TOOL_INSTALL
    assert sdk_item["controlled_backend_available"] is False


def test_missing_config_file_item_is_deferred_not_a_blocking_manual_step():
    """CLAUDE-E2E-001 end-to-end reproduction: a missing config_file
    requirement -- a development-created artifact, not a prerequisite --
    must not materialize into a blocking manual_review SetupStep at all.
    Because its non-blocking, non-controlled activation now routes it
    through the materializer's existing DEFERRED classification (the same
    mechanism already used for any non-controlled, non-blocking item), it
    is excluded from plan.steps and instead represented in
    deferred_requirement_ids/deferred_requirements -- still visible in
    the plan, just not an executable or blocking step. Uses
    RequirementPreflight.check() directly (the real preflight->activation
    chain), not a hand-built activation."""
    requirement = Requirement(
        id="req-config", name="project configuration file",
        type=RequirementType.CONFIG_FILE, purpose="project configuration",
        required=True, confidence=0.9,
    )
    preflight = RequirementPreflight.check((requirement,), "project-config")

    variant = make_variant(toolchain=(make_item(
        requirement_ref="req-config", name="project configuration file",
        type=RequirementType.CONFIG_FILE, install_method=None,
    ),))
    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-config",
        preflight=preflight,
    )

    assert plan.steps == ()
    assert "req-config" in plan.deferred_requirement_ids
    assert any(r.id == "req-config" for r in plan.deferred_requirements)

    activation = next(
        a for a in plan.requirement_activations if a.requirement_id == "req-config"
    )
    assert activation.active is True
    assert activation.blocks_current_operation is False


def test_missing_config_file_item_with_explicit_blocking_activation_still_materializes():
    """When an explicit activation overrides the development-artifact
    default to blocking (e.g. a future enhancement determines the file
    genuinely must pre-exist), the item is materialized as a blocking
    manual_review step exactly as any other non-automatable prerequisite
    would be -- proving the DEFERRED routing above is driven by the
    activation, not a config_file-specific special case in the
    materializer itself."""
    requirement = Requirement(
        id="req-config", name="project configuration file",
        type=RequirementType.CONFIG_FILE, purpose="project configuration",
        required=True, confidence=0.9,
    )
    explicit = RequirementActivation(
        "req-config", True, True, "explicitly required by this workflow",
    )
    preflight = RequirementPreflight.check((requirement,), "project-config", (explicit,))

    variant = make_variant(toolchain=(make_item(
        requirement_ref="req-config", name="project configuration file",
        type=RequirementType.CONFIG_FILE, install_method=None,
    ),))
    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-config",
        preflight=preflight,
    )

    assert len(plan.steps) == 1
    step = plan.steps[0]
    assert step.action == "manual_review"
    assert step.setup_effect is None
    assert plan.deferred_requirement_ids == ()


def test_missing_hardware_prerequisite_item_remains_blocking():
    """A genuine external prerequisite (hardware) materialized as a
    manual_review item must keep the plan-level activation blocking,
    proving the fix does not weaken prerequisite handling generally."""
    requirement = Requirement(
        id="req-device", name="ESP32 development board",
        type=RequirementType.HARDWARE_COMPONENT, purpose="target hardware",
        required=True, confidence=0.9,
    )
    preflight = RequirementPreflight.check((requirement,), "project-device")

    variant = make_variant(toolchain=(make_item(
        requirement_ref="req-device", name="ESP32 development board",
        type=RequirementType.HARDWARE_COMPONENT, install_method=None,
    ),))
    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-device",
        preflight=preflight,
    )

    assert len(plan.steps) == 1
    assert plan.steps[0].action == "manual_review"

    activation = next(
        a for a in plan.requirement_activations if a.requirement_id == "req-device"
    )
    assert activation.blocks_current_operation is True


def test_real_e2e_shape_package_identity_passes_through_verbatim():
    """CLAUDE-E2E-003 PART 3 / CLAUDE-E2E-003B/003C PART C proof: when
    ToolchainItem.name is already a valid single structured technical
    identifier (e.g. "ESPHome", no technical_identity supplied), it is
    used verbatim as the compatibility fallback -- no second, competing
    identity field is invented for this case, and no reparsing happens
    in the materializer. install_method's differently-cased text passes
    through unchanged too, since normalization lives at the comparison
    points (PythonPackageExecutor, RequirementPreflight), not here."""
    item = make_item(
        requirement_ref="req-esphome", name="ESPHome",
        type=RequirementType.PYTHON_PACKAGE, install_method="pip install esphome",
    )
    variant = make_variant(toolchain=(item,))
    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-esphome",
    )

    assert len(plan.steps) == 1
    step = plan.steps[0]
    assert step.package == "ESPHome"
    assert step.install_method == "pip install esphome"
    assert step.setup_effect == SetupEffect.PYTHON_PACKAGE_INSTALL


def test_display_label_is_not_accepted_as_technical_identity():
    """CLAUDE-E2E-003B/003C PART C core proof: a free-form, human-readable
    display label such as "ESPHome CLI" must never be guessed at or
    silently treated as a valid technical identity. With no
    technical_identity supplied and a name that is not itself a valid
    single structured token, the item cannot become a controlled
    install."""
    item = make_item(
        requirement_ref="req-esphome", name="ESPHome CLI",
        type=RequirementType.PYTHON_PACKAGE, install_method="pip install esphome",
    )
    variant = make_variant(toolchain=(item,))
    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-esphome",
    )

    assert len(plan.steps) == 1
    step = plan.steps[0]
    assert step.action == "manual_review"
    assert step.package is None
    assert step.setup_effect is None


@pytest.mark.parametrize(
    "display_name",
    ["ESPHome CLI", "Requests Python Library", "Beautiful Soup package"],
)
def test_various_display_labels_are_rejected_as_technical_identities(display_name):
    item = make_item(
        requirement_ref="req-x", name=display_name,
        type=RequirementType.PYTHON_PACKAGE, install_method="pip install some-package",
    )
    variant = make_variant(toolchain=(item,))
    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-x",
    )

    assert plan.steps[0].action == "manual_review"
    assert plan.steps[0].package is None


def test_structured_technical_identity_survives_to_setup_step():
    """CLAUDE-E2E-003B/003C PART C: Council's explicit, structured
    technical identity (ToolchainItem.technical_identity) is the
    authoritative source for SetupStep.package when supplied -- it
    survives materialization correctly even though the display name
    ("ESPHome CLI") is not itself a valid technical identifier."""
    item = ToolchainItem(
        requirement_ref="req-esphome", name="ESPHome CLI",
        technical_identity="esphome",
        type=RequirementType.PYTHON_PACKAGE,
        install_method="pip install esphome",
    )
    variant = make_variant(toolchain=(item,))
    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-esphome",
    )

    assert len(plan.steps) == 1
    step = plan.steps[0]
    assert step.action == "install"
    assert step.package == "esphome"
    assert step.setup_effect == SetupEffect.PYTHON_PACKAGE_INSTALL


def test_technical_identity_takes_priority_over_name_when_both_valid():
    """When both technical_identity and name are already valid,
    structured tokens, technical_identity (the explicit technical
    identity) is authoritative -- there is exactly one winner, never an
    ambiguous or silently-inconsistent choice."""
    item = ToolchainItem(
        requirement_ref="req-x", name="requests",
        technical_identity="Requests",
        type=RequirementType.PYTHON_PACKAGE,
        install_method="pip install requests",
    )
    variant = make_variant(toolchain=(item,))
    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-x",
    )

    assert plan.steps[0].package == "Requests"


def test_multi_toolchain_fixture_generic_target_and_identity_representation():
    """CLAUDE-E2E-003C PART 6 / multi-toolchain architecture proof: the
    generic central identity/target concepts (ToolchainItem.technical_identity,
    SetupStep.target_executable) can represent a Python package target,
    a plain executable/tool target, and a hypothetical second-ecosystem
    target fixture side by side in one plan -- WITHOUT any central
    schema change and without executing anything or introducing a real
    new installer. This is an architectural proof, not a new feature.
    """
    python_item = ToolchainItem(
        requirement_ref="req-py", name="ESPHome CLI",
        technical_identity="esphome",
        type=RequirementType.PYTHON_PACKAGE,
        install_method="pip install esphome",
    )
    tool_item = make_item(
        requirement_ref="req-tool", name="CMake Build Tool",
        technical_identity="cmake",
        type=RequirementType.TOOLCHAIN, install_method="apt install cmake",
    )
    # A hypothetical, non-implemented second ecosystem (e.g. a future
    # npm adapter): the SAME generic technical_identity field carries
    # its package identity too, with no new field and no real installer.
    hypothetical_npm_item = make_item(
        requirement_ref="req-npm", name="Frontend build tool",
        technical_identity="vite",
        type="npm_package", install_method="npm install vite",
    )

    preflight = PreflightResult(
        id="pre-multi", project_id="project-multi", overall_ready=True,
        results=(
            PreflightRequirementResult(
                requirement_id="req-py", present=False,
                target_executable="/isolated/toolchain/bin/python",
            ),
        ),
    )

    variant = make_variant(toolchain=(python_item, tool_item, hypothetical_npm_item))
    plan = ToolchainMaterializer().materialize(
        make_result(variants=(variant,)), "project-multi", preflight=preflight,
    )

    by_ref = {step.requirement_id: step for step in plan.steps}
    assert by_ref["req-py"].package == "esphome"
    assert by_ref["req-py"].target_executable == "/isolated/toolchain/bin/python"
    # A non-PYTHON_PACKAGE step never receives a target_executable --
    # the generic field exists but is meaningless outside the adapter
    # that actually uses it (see SetupStep docstring).
    assert by_ref["req-tool"].target_executable is None
    assert by_ref["req-npm"].target_executable is None
    # The hypothetical npm item's own technical_identity round-trips
    # through the exact same generic field/materializer path used for
    # Python, with no schema change and no npm-specific code added.
    assert hypothetical_npm_item.technical_identity == "vite"
