"""CLAUDE-PRE-E2E-009A: S2 Engineering-Decision stability contracts.

Proves the technology-neutral Engineering Solution Class classifier is:
(D) stable for structurally-identical input regardless of prose/id/order
    ("identical relevant input yields the same or technically equivalent
    Engineering Solution Class"),
(E) unaffected by proposal wording/order variation alone, and
genuinely capable of detecting a materially different class (never
trivially always-equal) -- directly modeling the Host/PlatformIO vs.
Python-venv vs. Docker vs. VM class of oscillation risk named in the task.
"""
from app.council_models import CouncilVariant, ToolchainItem
from app.engineering_solution_class import (
    EngineeringSolutionClass,
    classify_engineering_solution,
)
from app.requirement_model import RequirementType


def _venv_variant(**overrides):
    defaults = dict(
        id="variant-a", name="Python venv toolchain",
        description="Use a local Python virtual environment.",
        environment="host",
        toolchain=(
            ToolchainItem(
                requirement_ref="req-esphome", name="ESPHome CLI",
                type=RequirementType.PYTHON_PACKAGE,
                technical_identity="esphome", install_method="pip",
                state="needs_install",
            ),
        ),
        advantages=("simple", "fast setup"),
        votes=(),
        consensus_level="unanimous",
    )
    defaults.update(overrides)
    return CouncilVariant(**defaults)


def test_equivalent_variants_with_different_prose_and_id_share_the_same_class():
    """Part 6.D/6.E: different id, name, description, advantages, and
    consensus wording alone must not change the binding Engineering
    Solution Class."""
    variant_a = _venv_variant(id="variant-1", name="Approach A")
    variant_b = _venv_variant(
        id="variant-2", name="A completely differently worded proposal",
        description="An entirely different prose description.",
        advantages=("well understood", "low risk", "team familiarity"),
        disadvantages=("requires network access",),
        consensus_level="majority",
    )

    assert classify_engineering_solution(variant_a) == classify_engineering_solution(variant_b)


def test_toolchain_item_order_does_not_affect_the_class():
    """Part 6.E: presentation order of toolchain items is not
    decision-relevant."""
    item_a = ToolchainItem(
        requirement_ref="req-a", name="A", type=RequirementType.PYTHON_PACKAGE,
        install_method="pip",
    )
    item_b = ToolchainItem(
        requirement_ref="req-b", name="B", type=RequirementType.EXECUTABLE,
        install_method="manual",
    )
    forward = CouncilVariant(id="v1", name="v1", environment="host", toolchain=(item_a, item_b))
    reversed_ = CouncilVariant(id="v2", name="v2", environment="host", toolchain=(item_b, item_a))

    assert classify_engineering_solution(forward) == classify_engineering_solution(reversed_)


def test_different_environment_model_is_a_materially_different_class():
    """The classifier must genuinely be able to detect a real
    difference -- never trivially always-equal. Directly models the
    Host vs. Docker oscillation risk named in the task."""
    host_variant = _venv_variant(environment="host")
    docker_variant = _venv_variant(environment="docker")

    assert classify_engineering_solution(host_variant) != classify_engineering_solution(docker_variant)


def test_different_toolchain_type_is_a_materially_different_class():
    """Host/PlatformIO (an EXECUTABLE toolchain item) vs. a Python-venv
    toolchain (a PYTHON_PACKAGE item) for materially the same underlying
    engineering need must be classified as genuinely different
    Engineering Solution Classes."""
    python_venv_variant = _venv_variant()
    platformio_variant = _venv_variant(
        toolchain=(
            ToolchainItem(
                requirement_ref="req-esphome", name="PlatformIO",
                type=RequirementType.EXECUTABLE,
                technical_identity="platformio", install_method="pip",
                state="needs_install",
            ),
        ),
    )

    assert classify_engineering_solution(python_venv_variant) != classify_engineering_solution(platformio_variant)


def test_requires_environment_mutation_reflects_already_provided_state():
    """A solution whose toolchain is entirely already-installed requires
    no environment mutation; one that still needs installing does."""
    already_available = _venv_variant(
        toolchain=(
            ToolchainItem(
                requirement_ref="req-esphome", name="ESPHome CLI",
                type=RequirementType.PYTHON_PACKAGE,
                technical_identity="esphome", install_method="pip",
                state="already_installed",
            ),
        ),
    )
    needs_install = _venv_variant()

    assert classify_engineering_solution(already_available).requires_environment_mutation is False
    assert classify_engineering_solution(needs_install).requires_environment_mutation is True


def test_classification_ignores_prose_and_identity_fields_by_construction():
    """Structural proof that the returned class object never carries
    id/name/description/votes -- only the technology-neutral,
    decision-relevant properties named in the task."""
    result = classify_engineering_solution(_venv_variant())
    assert isinstance(result, EngineeringSolutionClass)
    field_names = set(result.__dataclass_fields__.keys())
    assert field_names == {
        "environment_model", "toolchain_types", "execution_classes",
        "requires_environment_mutation",
    }
