import pytest

from app.council_models import CouncilResult, CouncilVariant, ToolchainItem
from app.requirement_model import RequirementType
from app.toolchain_materializer import (
    ToolchainMaterializationError,
    ToolchainMaterializer,
)


def make_item(
    requirement_ref="req-1",
    name="requests",
    type=RequirementType.PYTHON_PACKAGE,
    install_method="pip",
    version=None,
    state="needs_install",
):
    return ToolchainItem(
        requirement_ref=requirement_ref,
        name=name,
        type=type,
        install_method=install_method,
        version=version,
        state=state,
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
