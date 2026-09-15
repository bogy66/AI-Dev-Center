"""FIX-005: explicit discovery identity through the zero-file S2.3 boundary."""
from dataclasses import replace
import json
from unittest.mock import Mock

import pytest

from app.ai_requirement_discovery import AIRequirementDiscovery
from app.council_models import CouncilInput, CouncilResult
from app.council_prompts import build_phase1_prompt, build_chairman_prompt, _serialize_requirement
from app.dev_workflow import DevelopmentWorkflow
from app.engineering_decision import validate_candidates
from app.python_distribution import DistributionCheckResult
from app.requirement_model import Requirement
from app.requirement_preflight import RequirementPreflight
from app.requirement_validator import RequirementValidator
from app.verification import all_trusted_verification_groups
from tests.test_verification_evidence_package_presence import _package_variant, _binding_preflight


def requirement(**changes):
    return replace(Requirement(
        id="dynamic-req-123", name="ESPHome CLI", technical_identity="esphome",
        type="python_package", purpose="firmware tooling", required=True,
        confidence=0.9, install_method="pip", verification_method="pip show esphome",
    ), **changes)


def admissibility(req, tmp_path, *, identity="esphome", mechanism="pip_show", preflight=None):
    variant = _package_variant(req.id, identity, mechanism=mechanism)
    result = CouncilResult(id="c", project_id="proj", variants=(variant,),
                           recommendation=variant.id, council_complete=True)
    return validate_candidates(
        result, preflight=preflight or _binding_preflight(req),
        project_root=str(tmp_path), trusted_verification_groups=all_trusted_verification_groups(None),
    )[0]


def test_discovery_validation_preflight_zero_file_host(monkeypatch, tmp_path):
    provider = Mock()
    provider.complete_structured.return_value = json.dumps({"requirements": [{
        "id": "dynamic-req-123", "name": "ESPHome CLI", "technical_identity": "esphome",
        "type": "python_package", "purpose": "firmware tooling", "required": True,
        "confidence": "high", "install_method": "pip", "verification_method": "pip show esphome",
    }]})
    discovery = AIRequirementDiscovery(provider).discover({"project_id": "proj", "file_count": 0})
    req, = discovery.requirements
    validation = RequirementValidator.validate(discovery.requirements)
    assert validation.valid
    assert validation.normalized_requirements == (req,)
    check = Mock(return_value=DistributionCheckResult(False, None, True))
    monkeypatch.setattr("app.requirement_preflight.check_distribution_installed", check)
    preflight = RequirementPreflight.check((req,), "proj", project_root=str(tmp_path),
                                         target_executable="/usr/bin/python3")
    check.assert_called_once_with("esphome", "/usr/bin/python3", project_root=str(tmp_path))
    assert not preflight.results[0].present
    assert not preflight.results[0].satisfied
    assert list(tmp_path.iterdir()) == []
    verdict = admissibility(req, tmp_path, preflight=preflight)
    assert verdict.admissible, verdict.reasons
    assert req.name == "ESPHome CLI"
    assert _serialize_requirement(req)["technical_identity"] == "esphome"


@pytest.mark.parametrize("identity", [None, "", "ESPHome CLI", ["esphome", "requests"], {"name": "esphome"}, 7])
@pytest.mark.parametrize("display", ["ESPHome CLI", "esphome"])
def test_unknown_identity_never_inferred_or_dropped(identity, display, monkeypatch, tmp_path):
    req = requirement(technical_identity=identity, name=display)
    validation = RequirementValidator.validate((req,))
    assert validation.normalized_requirements == (req,)  # remains binding
    assert any("identity indeterminate" in w for w in validation.warnings)
    check = Mock(side_effect=AssertionError("No presence query without identity"))
    monkeypatch.setattr("app.requirement_preflight.check_distribution_installed", check)
    preflight = RequirementPreflight.check((req,), "proj", project_root=str(tmp_path))
    assert not preflight.results[0].satisfied
    check.assert_not_called()
    assert not admissibility(req, tmp_path).admissible


@pytest.mark.parametrize("identity,expected", [("esphome", True), ("ESPHome", True), ("requests", False)])
def test_structured_identity_matching(identity, expected, tmp_path):
    assert admissibility(requirement(), tmp_path, identity=identity).admissible is expected


def test_pep503_only_distribution_identity(tmp_path):
    req = requirement(technical_identity="Acme_Widgets", verification_method="pip show acme.widgets")
    assert admissibility(req, tmp_path, identity="acme-widgets").admissible


@pytest.mark.parametrize("command", [
    "pip show requests", "pip show esphome && true", "pip show esphome | cat",
    "sh -c 'pip show esphome'", "python -m pip show esphome", "pip show esphome requests",
    "arbitrary check", "pip show --verbose esphome",
])
def test_package_contract_is_exact_and_closed(command, tmp_path):
    assert not admissibility(requirement(verification_method=command), tmp_path).admissible


@pytest.mark.parametrize("mechanism", ["esphome_validate", "esphome_compile"])
def test_project_mechanisms_without_independent_evidence_cannot_cover_package(mechanism, tmp_path):
    assert not admissibility(requirement(), tmp_path, mechanism=mechanism).admissible


def test_producer_contracts_preserve_identity_and_presence():
    req = requirement()
    ci = CouncilInput(project_id="proj", requirements=(req,))
    prompts = [build_phase1_prompt(ci, "test role"), build_chairman_prompt("[]", "[]", ci)]
    for prompt in prompts:
        assert '"technical_identity": "esphome"' in prompt
        assert '"name": "ESPHome CLI"' in prompt
        assert 'mechanism="pip_show"' in prompt
        assert '"pip show <technical_identity>"' in prompt
        assert 'never derive distribution identity from name' in prompt
    discovery = AIRequirementDiscovery()
    for prompt in (discovery._build_prompt({}), discovery._build_repair_prompt({})):
        assert "technical_identity" in prompt
        assert 'pip show <technical_identity>' in prompt


def test_diagnostics_preserve_valid_identity_without_raw_malformed_values():
    view = DevelopmentWorkflow._requirement_view(requirement())
    assert view["name"] == "ESPHome CLI"
    assert view["safe_identifier"] == "esphome"
    view = DevelopmentWorkflow._requirement_view(requirement(technical_identity={"bad": "value"}))
    assert not view["technical_identity_valid"]
    assert "safe_identifier" not in view


@pytest.mark.parametrize("display", ["ESPHome CLI", "esphome"])
def test_discovery_never_infers_identity_even_from_verification_command(display):
    req = AIRequirementDiscovery()._build_requirement({
        "name": display, "type": "python_package", "purpose": "tooling",
        "verification_method": "pip show esphome", "install_method": "pip install esphome",
    })
    assert req.name == display
    assert req.technical_identity is None
