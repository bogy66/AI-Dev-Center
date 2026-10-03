"""S2.3 pre-flight test hardening (CLAUDE-ADC-S23-RSE-PREFLIGHT-TEST-
HARDENING-001), Part D: a deterministic "RSE preflight" test.

This is NOT a Real-System-E2E test and is not evidence that a live,
paid Council/LLM run would actually produce an admissible candidate for
this scenario. It is a deterministic GUARD: it drives the exact same
semantic scenario Real-System-E2E task ADC-REAL-SYSTEM-E2E-RETRY-001
used --

    Create an ESPHome project for an ESP32 that logs "Hello World"
    periodically.

-- through the REAL downstream productive workflow contracts

    AIRequirementDiscovery.discover()   (fake LLMProvider only)
    -> RequirementValidator.validate()
    -> RequirementPreflight.check()
    -> CouncilInput(...)
    -> EngineeringCouncil.evaluate()    (fake LLMProviders only, real
                                          3-phase orchestration/quorum)
    -> validate_candidates()            (the real S2.3 authority)
    -> admissible_variants()

using deterministic/fake substitutes ONLY at the provider boundary
(AIRequirementDiscovery's LLMProvider and EngineeringCouncil's per-agent
LLMProvider). No live/paid LLM provider, no network access, no ESPHome/
ESP32-specific code added anywhere in app/ -- the scenario is realistic
flavor for the fake responses only.

Success condition (and the ONLY thing this test asserts pass/fail on):
at least one deliberately well-formed candidate reaches S2.3 as
admissible. As in Part B (test_requirement_lineage.py), the ids used to
build the fake Council's toolchain are read back off the REAL Requirement
objects Discovery/Validation/Preflight produced -- never hardcoded
separately -- so this test would fail exactly the way the real
Real-System-E2E run failed if any stage lost or renamed a binding
requirement id.

What this proves: the downstream planning/validation contracts CAN
accept a semantically correct, well-formed candidate for this scenario,
deterministically and locally, before spending a paid/live Real-System-E2E
attempt on it.

What this explicitly does NOT prove:
  - that a live Council/Chairman LLM call will actually produce a
    well-formed candidate for this scenario (that remains unverified --
    see PREVIOUS_S32_S33_RSE_REPAIR_STATUS=NOT_REACHED_UNVERIFIED);
  - full Real-System-E2E coverage;
  - the still-unproven root cause of ADC-REAL-SYSTEM-E2E-RETRY-001's
    actual live failure.
"""
from __future__ import annotations

import json

from app.ai_requirement_discovery import AIRequirementDiscovery
from app.council_models import CouncilInput
from app.engineering_decision import admissible_variants, validate_candidates
from app.requirement_model import RequirementType
from app.requirement_preflight import RequirementPreflight
from app.requirement_validator import RequirementValidator
from app.verification import PACKAGE_PRESENCE_MECHANISM

from tests.test_engineering_council import (
    FakeLLMProvider,
    FailingLLMProvider,
    _make_council_config,
    _make_phase2_response,
    _run_council_with_fakes,
)
from tests.test_requirement_lineage import _FakeDiscoveryLLMProvider

_ESP32_HELLO_WORLD_USER_REQUEST = (
    'Create an ESPHome project for an ESP32 that logs "Hello World" periodically.'
)

_DISCOVERY_RESPONSE = {
    "requirements": [
        {
            "name": "ESP32 Platform",
            "type": RequirementType.HARDWARE_COMPONENT,
            "purpose": "target hardware platform for the firmware build",
            "required": True,
            "confidence": "high",
            "active_for_current_request": True,
            "blocks_current_operation": True,
        },
        {
            "name": "esphome",
            "type": RequirementType.PYTHON_PACKAGE,
            "technical_identity": "esphome",
            "purpose": "ESPHome CLI to compile/validate the firmware project",
            "required": True,
            "confidence": "high",
            "verification_method": "pip show esphome",
            "active_for_current_request": True,
            "blocks_current_operation": True,
        },
    ],
}


def _run_discovery_validation_preflight():
    """Real Discovery -> Validation -> Preflight, fake provider only."""
    discovery = AIRequirementDiscovery(
        llm_provider=_FakeDiscoveryLLMProvider(_DISCOVERY_RESPONSE),
    )
    discovery_result = discovery.discover(
        project_info={"project_id": "esphome-rse-preflight", "files": ()},
        user_request=_ESP32_HELLO_WORLD_USER_REQUEST,
    )
    assert len(discovery_result.requirements) == 2

    validation_result = RequirementValidator.validate(
        discovery_result.requirements, activations=discovery_result.activations,
    )
    assert validation_result.valid
    assert len(validation_result.required_requirements) == 2

    preflight_result = RequirementPreflight.check(
        validation_result.required_requirements,
        project_id="esphome-rse-preflight",
        activations=validation_result.activations,
    )
    return validation_result, preflight_result


def _requirement_by_name(requirements, name):
    [match] = [r for r in requirements if r.name == name]
    return match


def _well_formed_phase1_response(agent_id, platform_ref, package_ref):
    """A single, deliberately well-formed candidate per agent -- covers
    both real binding requirement ids (read from the caller, never
    hardcoded here), a controlled pip install, and no platform/
    environment conflicts."""
    return json.dumps({"variants": [{
        "variant_id": f"{agent_id}-var-1", "name": f"{agent_id} host build",
        "description": "", "environment": "host",
        "toolchain": [
            {"requirement_ref": platform_ref, "name": "ESP32 Platform",
             "type": RequirementType.HARDWARE_COMPONENT, "state": "already_installed"},
            {"requirement_ref": package_ref, "name": "esphome",
             "technical_identity": "esphome", "type": RequirementType.PYTHON_PACKAGE,
             "install_method": "pip", "state": "needs_install"},
        ],
        "advantages": [], "disadvantages": [], "risks": [],
        "confidence": 0.85, "feasibility": "high",
        "verification": "pip show esphome",
        "agent_reasoning": "",
    }]})


def _well_formed_chairman_response(variant_id, platform_ref, package_ref):
    return json.dumps({
        "merge_decisions": [],
        "variants": [{
            "id": variant_id, "name": "ESPHome host build", "description": "",
            "origin_agents": ["A1", "A2", "A3"], "merged_from": [variant_id],
            "rank": 1, "total_score": 5.0, "consensus_level": "strong_consensus",
            "minority_opinions": [], "environment": "host",
            "hardware_target": "esp32", "connection": None,
            "capabilities": ["build"],
            "toolchain": [
                {"requirement_ref": platform_ref, "name": "ESP32 Platform",
                 "type": RequirementType.HARDWARE_COMPONENT, "state": "already_installed"},
                {"requirement_ref": package_ref, "name": "esphome",
                 "technical_identity": "esphome", "type": RequirementType.PYTHON_PACKAGE,
                 "install_method": "pip", "state": "needs_install",
                 "provides_verification": [PACKAGE_PRESENCE_MECHANISM]},
            ],
            "advantages": [], "disadvantages": [], "risks": [],
            "confidence": 0.9, "feasibility": "high", "verification": "pip show esphome",
            "verification_coverage": [{
                "requirement_refs": [package_ref], "kind": "smoke_test",
                "mechanism": PACKAGE_PRESENCE_MECHANISM, "evidence": "esphome",
            }],
        }],
        "rejected_variants": [],
        "recommendation": variant_id,
        "reasoning": "Single well-formed ESPHome host build candidate",
    })


class TestDeterministicRSEPreflightGuard:
    """A deterministic guard, NOT a Real-System-E2E test and NOT
    evidence of live Council correctness (see module docstring)."""

    def test_well_formed_esp32_hello_world_candidate_reaches_s23_as_admissible(self, tmp_path):
        validation_result, preflight_result = _run_discovery_validation_preflight()
        platform_req = _requirement_by_name(validation_result.required_requirements, "ESP32 Platform")
        package_req = _requirement_by_name(validation_result.required_requirements, "esphome")

        council_input = CouncilInput(
            requirements=validation_result.required_requirements,
            preflight=preflight_result,
            detected_stack="esphome",
            project_id="esphome-rse-preflight",
            platform="linux",
            requirement_activations=validation_result.activations,
        )

        a1_resp = _well_formed_phase1_response("A1", platform_req.id, package_req.id)
        a2_resp = _well_formed_phase1_response("A2", platform_req.id, package_req.id)
        a3_resp = _well_formed_phase1_response("A3", platform_req.id, package_req.id)
        all_ids = ["A1-var-1", "A2-var-1", "A3-var-1"]
        ph2_resp = _make_phase2_response("x", all_ids)
        ch_resp = _well_formed_chairman_response("esphome-host-1", platform_req.id, package_req.id)

        fake_providers = {
            "model-ea": FakeLLMProvider([a1_resp, ph2_resp]),
            "model-ti": FakeLLMProvider([a2_resp, ph2_resp]),
            "model-ra": FakeLLMProvider([a3_resp, ph2_resp]),
            "model-ch": FakeLLMProvider([ch_resp]),
        }

        council_result = _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path, council_input=council_input,
        )
        assert council_result.council_complete
        assert not council_result.council_degraded

        validations = validate_candidates(
            council_result, preflight=preflight_result, platform=council_input.platform,
        )
        admissible = admissible_variants(validations)
        assert len(admissible) >= 1
        assert admissible[0].id == "esphome-host-1"

    def test_degraded_provider_boundary_still_reaches_an_admissible_candidate(self, tmp_path):
        """The same scenario, but one provider fails (simulating the RSE's
        own observed provider timeouts) -- proving the deterministic
        guard is not fragile to a single simulated provider failure, and
        that degraded completion alone does not prevent an otherwise
        well-formed candidate from being admissible (see also Part F,
        tests/test_engineering_council.py::TestDegradedCouncilFeedsIntoS23Admissibility)."""
        validation_result, preflight_result = _run_discovery_validation_preflight()
        platform_req = _requirement_by_name(validation_result.required_requirements, "ESP32 Platform")
        package_req = _requirement_by_name(validation_result.required_requirements, "esphome")

        council_input = CouncilInput(
            requirements=validation_result.required_requirements,
            preflight=preflight_result,
            detected_stack="esphome",
            project_id="esphome-rse-preflight",
            platform="linux",
            requirement_activations=validation_result.activations,
        )

        a1_resp = _well_formed_phase1_response("A1", platform_req.id, package_req.id)
        a2_resp = _well_formed_phase1_response("A2", platform_req.id, package_req.id)
        ph2_resp = _make_phase2_response("x", ["A1-var-1", "A2-var-1"])
        ch_resp = _well_formed_chairman_response("esphome-host-2", platform_req.id, package_req.id)

        fake_providers = {
            "model-ea": FakeLLMProvider([a1_resp, ph2_resp]),
            "model-ti": FakeLLMProvider([a2_resp, ph2_resp]),
            "model-ra": FailingLLMProvider("simulated provider timeout"),
            "model-ch": FakeLLMProvider([ch_resp]),
        }

        council_result = _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path, council_input=council_input,
        )
        assert council_result.council_complete
        assert council_result.council_degraded

        validations = validate_candidates(
            council_result, preflight=preflight_result, platform=council_input.platform,
        )
        admissible = admissible_variants(validations)
        assert len(admissible) >= 1
        assert admissible[0].id == "esphome-host-2"
