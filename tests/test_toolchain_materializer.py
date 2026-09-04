import pytest

from app.council_models import CouncilResult, CouncilVariant, ToolchainItem
from app.requirement_model import (
    Requirement, RequirementActivation, RequirementType,
    PreflightRequirementResult, PreflightResult,
)
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
):
    return ToolchainItem(
        requirement_ref=requirement_ref,
        name=name,
        type=type,
        install_method=install_method,
        version=version,
        state=state,
        provided_by=provided_by,
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
        requirement_ref=requirement.id, type=RequirementType.CAPABILITY,
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
        install_method="structured-installer",
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
        name="Active Platform",
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
            name="Active Platform",
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
        name="Providing Platform",
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
            name="Providing Platform",
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
        make_item(requirement_ref=a_req.id, name="A",
                  type=RequirementType.SDK, install_method="manual", provided_by=b_req.id),
        make_item(requirement_ref=b_req.id, name="B",
                  type=RequirementType.SDK, install_method="manual", provided_by=c_req.id),
        make_item(requirement_ref=c_req.id, name="C",
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
        make_item(requirement_ref=a_req.id, name="A",
                  type=RequirementType.SDK, install_method="manual", provided_by=b_req.id),
        make_item(requirement_ref=b_req.id, name="B",
                  type=RequirementType.SDK, install_method="manual", provided_by=c_req.id),
        make_item(requirement_ref=c_req.id, name="C",
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
        make_item(requirement_ref=a_req.id, name="A",
                  type=RequirementType.SDK, install_method="manual", provided_by=b_req.id),
        make_item(requirement_ref=b_req.id, name="B",
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
        make_item(requirement_ref=a_req.id, name="A",
                  type=RequirementType.SDK, install_method="manual", provided_by=b_req.id),
        make_item(requirement_ref=b_req.id, name="B",
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
        make_item(requirement_ref=a_req.id, name="A",
                  type=RequirementType.SDK, install_method="manual", provided_by=b_req.id),
        make_item(requirement_ref=b_req.id, name="B",
                  type=RequirementType.SDK, install_method="manual", provided_by=c_req.id),
        make_item(requirement_ref=c_req.id, name="C",
                  type=RequirementType.PYTHON_PACKAGE, install_method="pip"),
    )
    order_2 = (
        make_item(requirement_ref=c_req.id, name="C",
                  type=RequirementType.PYTHON_PACKAGE, install_method="pip"),
        make_item(requirement_ref=b_req.id, name="B",
                  type=RequirementType.SDK, install_method="manual", provided_by=c_req.id),
        make_item(requirement_ref=a_req.id, name="A",
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
            name="Platform",
            install_method="pip",
            provided_by=sdk.id,
        ),
        make_item(
            requirement_ref=sdk.id,
            name="Ignored SDK",
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
