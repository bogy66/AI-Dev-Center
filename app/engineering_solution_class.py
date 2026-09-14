"""Technology-neutral, deterministic classification of an Engineering
Council CouncilVariant into stable, decision-relevant properties
(CLAUDE-PRE-E2E-009A).

Context: the Engineering Council's Chairman synthesis is a real LLM
call (app/engineering_council.py), and its exact prose, variant id,
variant name, ordering, and wording are legitimately non-deterministic
across runs -- this module never attempts to make any of that
byte-deterministic. What MUST remain stable for the same relevant
engineering input is the underlying, technology-neutral SOLUTION CLASS:
whether the Chairman is materially recommending, say, a host/PlatformIO
toolchain versus a Python-venv toolchain versus a Docker-based
environment versus a VM-based one for the same project. Two proposals
that only differ in wording, variant id, presentation order, vote
tallies, or free-text advantages/disadvantages are the SAME Engineering
Solution Class; two proposals that differ in environment model,
toolchain composition, or execution class are genuinely DIFFERENT
classes.

classify_engineering_solution() derives this class purely from a
CouncilVariant's own structured fields -- never from its prose (name,
description, advantages/disadvantages/risks, votes, minority_opinions)
and never from its id -- so that two structurally-equivalent variants
compare equal regardless of how differently an LLM run happened to word
or order them.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.council_models import CouncilVariant
from app.requirement_model import classify_setup_effect


@dataclass(frozen=True)
class EngineeringSolutionClass:
    """A technology-neutral, structurally-derived summary of what kind
    of engineering solution a CouncilVariant actually represents.

    environment_model: the variant's own structured environment field
        (e.g. "host", "docker", "vm") -- never inferred from prose.
    toolchain_types: the set of RequirementType values present in the
        toolchain (the technology/toolchain CLASS, e.g.
        {"python_package"} vs {"container_runtime"}), order-independent.
    execution_classes: the set of controlled/manual SetupEffect
        identities the toolchain would actually produce (the EXECUTION
        class ADC would use to carry it out), order-independent.
    requires_environment_mutation: whether the variant's own toolchain
        claims any item still needs installing (state != "already_installed",
        ToolchainItem's own real sentinel for "no action needed" -- see
        ToolchainMaterializer._classify_item_baseline()), as opposed to
        a solution that only uses already-available capabilities.
    """

    environment_model: str
    toolchain_types: frozenset[str]
    execution_classes: frozenset[str]
    requires_environment_mutation: bool


def classify_engineering_solution(variant: CouncilVariant) -> EngineeringSolutionClass:
    """Pure, deterministic function of a CouncilVariant's structured
    fields alone. Never reads variant.id, variant.name,
    variant.description, advantages/disadvantages/risks, votes,
    consensus_level, or minority_opinions -- none of those are
    decision-relevant to what CLASS of solution this is."""
    toolchain_types = frozenset(item.type for item in variant.toolchain)
    execution_classes = frozenset(
        effect
        for item in variant.toolchain
        if (effect := classify_setup_effect(item.type, item.name, item.install_method))
        and effect != "manual"
    )
    requires_environment_mutation = any(
        item.state != "already_installed" for item in variant.toolchain
    )
    return EngineeringSolutionClass(
        environment_model=variant.environment,
        toolchain_types=toolchain_types,
        execution_classes=execution_classes,
        requires_environment_mutation=requires_environment_mutation,
    )
