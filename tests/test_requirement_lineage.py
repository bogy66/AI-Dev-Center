"""S2.3 pre-flight test hardening (CLAUDE-ADC-S23-RSE-PREFLIGHT-TEST-
HARDENING-001), Part B: a deterministic requirement-IDENTITY-lineage
test.

Context: Real-System-E2E task ADC-REAL-SYSTEM-E2E-RETRY-001 failed at S2.3
("Candidate Admissibility") because all three proposed candidates lacked
binding coverage for a platform requirement
(req-c2efb7b8 -- "ESP32 Platform"). That is exactly the failure MODE this
test is written to catch locally, deterministically, and BEFORE another
paid/live Real-System-E2E attempt: a requirement id that is lost, drifts,
gets re-issued under a different id, or gets duplicated under an
incompatible identity somewhere between Discovery and S2.3.

This test drives the REAL productive chain end to end:

    AIRequirementDiscovery.discover()          (fake LLMProvider only)
    -> RequirementValidator.validate()
    -> RequirementPreflight.check()
    -> CouncilInput(...)                       (assembled from the above)
    -> a CouncilVariant/ToolchainItem standing in for a Council candidate
    -> validate_variants()                     (the real S2.3 authority)

Deliberately never hand-writes the SAME id independently on both the
"producer" and "consumer" side: the id used to build the Council
candidate's ToolchainItem is always read back off the real Requirement
object AIRequirementDiscovery itself generated (a fresh
`req-<uuid4 hex[:8]>`), so a genuine lineage break (typo, truncation, a
freshly re-issued id, ...) is mechanically distinguishable from "the test
just wrote the same literal string twice".

The requirement used is a generic platform/toolchain requirement
(HARDWARE_COMPONENT), analogous to -- but not hardcoded to -- the RSE's
own "ESP32 Platform" / req-c2efb7b8. Nothing here is ESPHome/ESP32-
specific in the central S2.3 contract being exercised; the scenario name
is flavor only.

What this proves: a binding requirement id that genuinely, mechanically
survives Discovery -> Validation -> Preflight -> CouncilInput assembly
-> a Council candidate's ToolchainItem.requirement_ref IS recognized as
covered by validate_variants(); and each of the four listed lineage
defects (lost ref, drifted ref, semantic-duplicate-under-a-different-id,
requirement-duplicated-under-incompatible-identities) is independently,
mechanically caught as a missing binding requirement.

What this does NOT prove: that a live LLM-driven Council will always
echo requirement_ref correctly (it currently has no mechanical
enforcement to do so -- see the module docstring risk this test exists
to catch locally) or that this exact scenario passes a real, live
Real-System-E2E run.
"""
from __future__ import annotations

import json

import pytest

from app.ai_requirement_discovery import AIRequirementDiscovery
from app.council_models import CouncilInput, CouncilVariant, ToolchainItem
from app.engineering_decision import admissible_variants, validate_variants
from app.requirement_model import RequirementType
from app.requirement_preflight import RequirementPreflight
from app.requirement_validator import RequirementValidator


class _FakeDiscoveryLLMProvider:
    """A minimal, deterministic stand-in for AIRequirementDiscovery's
    injectable LLMProvider Protocol (`complete(prompt) -> str`). Carries
    no network access and no live/paid provider of any kind."""

    def __init__(self, response_json: dict):
        self._response = json.dumps(response_json)
        self.calls: list[str] = []

    def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self._response


_PLATFORM_REQUIREMENT_RESPONSE = {
    "requirements": [
        {
            # Deliberately NO "id" key: AIRequirementDiscovery must
            # generate a real id itself (req-<uuid4 hex[:8]>) -- the
            # test never supplies or predicts it.
            "name": "ESP32 Platform",
            "type": RequirementType.HARDWARE_COMPONENT,
            "purpose": "target hardware platform for the firmware build",
            "required": True,
            "confidence": "high",
            "active_for_current_request": True,
            "blocks_current_operation": True,
        },
    ],
}


def _discover_platform_requirement():
    """Runs the real AIRequirementDiscovery with a fake provider and
    returns the single generated Requirement plus its DiscoveryResult."""
    discovery = AIRequirementDiscovery(
        llm_provider=_FakeDiscoveryLLMProvider(_PLATFORM_REQUIREMENT_RESPONSE),
    )
    discovery_result = discovery.discover(
        project_info={"project_id": "esphome-lineage-p1", "files": ()},
        user_request="Create an ESPHome project for an ESP32 that logs "
                     "\"Hello World\" periodically.",
    )
    assert len(discovery_result.requirements) == 1
    requirement = discovery_result.requirements[0]
    # Sanity: this is a REAL generated id, not a literal the test chose.
    assert requirement.id.startswith("req-")
    assert requirement.name == "ESP32 Platform"
    return discovery_result, requirement


def _validate_and_preflight(discovery_result):
    validation_result = RequirementValidator.validate(
        discovery_result.requirements, activations=discovery_result.activations,
    )
    assert validation_result.valid
    assert len(validation_result.required_requirements) == 1

    preflight_result = RequirementPreflight.check(
        validation_result.required_requirements,
        project_id="esphome-lineage-p1",
        activations=validation_result.activations,
    )
    return validation_result, preflight_result


def _council_input(validation_result, preflight_result):
    """CouncilInput as a real stage in the chain -- constructed from the
    exact same objects Preflight/Validation produced, never a separate,
    hand-rolled requirement set."""
    return CouncilInput(
        requirements=validation_result.required_requirements,
        preflight=preflight_result,
        detected_stack="esphome",
        project_id="esphome-lineage-p1",
        platform="linux",
        requirement_activations=validation_result.activations,
    )


def _candidate_with_toolchain_ref(requirement_ref: str) -> CouncilVariant:
    """Stands in for a Council candidate whose Chairman synthesis echoed
    (or failed to echo) the binding requirement's id in its own
    toolchain. `requirement_ref` is the only variable dimension -- every
    other field is fixed, realistic flavor."""
    return CouncilVariant(
        id="candidate-1",
        name="Host toolchain candidate",
        environment="host",
        toolchain=(
            ToolchainItem(
                requirement_ref=requirement_ref,
                name="ESP32 Platform",
                type=RequirementType.HARDWARE_COMPONENT,
                install_method=None,
                state="already_installed",
            ),
        ),
    )


class TestRequirementLineageThroughS23:
    """Drives the real id end to end and proves S2.3 both accepts a
    genuinely-preserved id and rejects each independent way it can be
    lost or corrupted in transit."""

    def test_lineage_preserved_id_is_recognized_as_covered(self):
        discovery_result, requirement = _discover_platform_requirement()
        validation_result, preflight_result = _validate_and_preflight(discovery_result)
        council_input = _council_input(validation_result, preflight_result)
        assert council_input.requirements[0].id == requirement.id

        # The "Council candidate" step: its ToolchainItem.requirement_ref
        # is read back off the SAME Requirement object, never re-typed.
        candidate = _candidate_with_toolchain_ref(requirement.id)

        validations = validate_variants(
            (candidate,), preflight=preflight_result, platform=council_input.platform,
        )
        assert len(validations) == 1
        [validation] = validations
        assert requirement.id not in validation.missing_binding_requirement_ids
        assert validation.admissible, validation.reasons
        assert admissible_variants(validations) == (candidate,)

    def test_lineage_lost_requirement_ref_is_caught(self):
        """A candidate whose toolchain item never references the
        requirement at all (requirement_ref left empty) -- the
        "binding coverage lacking entirely" shape from the RSE
        failure."""
        discovery_result, requirement = _discover_platform_requirement()
        _validation_result, preflight_result = _validate_and_preflight(discovery_result)
        candidate = _candidate_with_toolchain_ref("")

        [validation] = validate_variants((candidate,), preflight=preflight_result, platform="linux")
        assert not validation.admissible
        assert requirement.id in validation.missing_binding_requirement_ids

    def test_lineage_id_drift_is_caught(self):
        """A single-character drift (e.g. a truncated/garbled id) must
        never be silently treated as the same requirement."""
        discovery_result, requirement = _discover_platform_requirement()
        _validation_result, preflight_result = _validate_and_preflight(discovery_result)
        drifted_ref = requirement.id + "-drift"
        assert drifted_ref != requirement.id
        candidate = _candidate_with_toolchain_ref(drifted_ref)

        [validation] = validate_variants((candidate,), preflight=preflight_result, platform="linux")
        assert not validation.admissible
        assert requirement.id in validation.missing_binding_requirement_ids

    def test_lineage_semantic_requirement_under_a_different_id_is_caught(self):
        """The Council may invent its OWN fresh id for a toolchain item
        that is semantically "the same" platform requirement (same name/
        type) but is not the id Discovery/Validation/Preflight actually
        bound as the current operation's blocker. Semantic similarity
        must never substitute for identity equality."""
        discovery_result, requirement = _discover_platform_requirement()
        _validation_result, preflight_result = _validate_and_preflight(discovery_result)
        fabricated_id = "req-" + ("0" * 8)
        assert fabricated_id != requirement.id
        candidate = _candidate_with_toolchain_ref(fabricated_id)

        [validation] = validate_variants((candidate,), preflight=preflight_result, platform="linux")
        assert not validation.admissible
        assert requirement.id in validation.missing_binding_requirement_ids

    def test_lineage_requirement_duplicated_under_incompatible_identities_is_caught(self):
        """Two independently-discovered Requirement objects that are
        semantically "the same" platform requirement but were assigned
        two different ids (e.g. discovery ran twice, or two provider
        responses each minted their own id for the same real-world
        platform fact). A candidate that only covers ONE of the two
        ids must still be rejected for the uncovered one -- ADC must
        never silently collapse two distinct ids into a single semantic
        concept on S2.3's behalf."""
        discovery_result_a, requirement_a = _discover_platform_requirement()
        discovery_result_b, requirement_b = _discover_platform_requirement()
        assert requirement_a.id != requirement_b.id
        assert requirement_a.name == requirement_b.name

        combined_requirements = (requirement_a, requirement_b)
        combined_activations = discovery_result_a.activations + discovery_result_b.activations
        validation_result = RequirementValidator.validate(
            combined_requirements, activations=combined_activations,
        )
        preflight_result = RequirementPreflight.check(
            validation_result.required_requirements,
            project_id="esphome-lineage-p1",
            activations=validation_result.activations,
        )

        # The candidate only echoes requirement_a's id.
        candidate = _candidate_with_toolchain_ref(requirement_a.id)

        [validation] = validate_variants((candidate,), preflight=preflight_result, platform="linux")
        assert not validation.admissible
        assert requirement_a.id not in validation.missing_binding_requirement_ids
        assert requirement_b.id in validation.missing_binding_requirement_ids
