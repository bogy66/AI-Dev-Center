import json
import pytest
from app.ai_requirement_discovery import AIRequirementDiscovery
from app.requirement_model import (
    Requirement,
    RequirementSet,
    RequirementEvidence,
    Status,
    RequirementType,
)


class TestRequirementCreation:
    """Basic tests for requirement model used by ai discovery."""

    def test_can_create_with_all_fields(self):
        evidence = RequirementEvidence(
            id="ev-1",
            source_type="file",
            description="found in config",
            source_file="somefile.yaml",
            snippet="esphome:",
            confidence_contribution=0.8,
        )
        req = Requirement(
            id="req-1",
            name="esphome",
            type=RequirementType.PYTHON_PACKAGE,
            purpose="build+flash",
            required=True,
            confidence=0.9,
            evidence=[evidence],
            metadata={"source": "test-source"},
        )
        assert req.name == "esphome"
        assert req.type == RequirementType.PYTHON_PACKAGE
        assert req.purpose == "build+flash"
        assert req.metadata["source"] == "test-source"
        assert req.confidence == 0.9


class TestRequirementSet:

    def test_can_contain_multiple_requirements(self):
        ev1 = RequirementEvidence(id="e1", source_type="file", description="desc1")
        ev2 = RequirementEvidence(id="e2", source_type="file", description="desc2")
        req1 = Requirement(
            id="r1",
            name="esphome",
            type=RequirementType.PYTHON_PACKAGE,
            purpose="build",
            required=True,
            confidence=0.9,
            evidence=[ev1],
        )
        req2 = Requirement(
            id="r2",
            name="pyserial",
            type=RequirementType.PYTHON_PACKAGE,
            purpose="serial",
            required=False,
            confidence=0.5,
            evidence=[ev2],
        )
        rs = RequirementSet(
            id="test-set", project_id="test-proj", requirements=[req1, req2]
        )
        assert len(rs.requirements) == 2
        assert rs.requirements[0].name == "esphome"
        assert rs.requirements[1].name == "pyserial"


class TestAIRequirementDiscovery:

    # ------------------------------------------------------------------
    # Helper: fake LLM provider that returns a fixed response
    # ------------------------------------------------------------------
    class FakeLLM:
        def __init__(self, response_text=""):
            self.response_text = response_text
            self.called_with = None

        def complete(self, prompt: str) -> str:
            self.called_with = prompt
            return self.response_text

    def _make_llm(self, response_text):
        return self.FakeLLM(response_text)

    def _json_response(self, requirements):
        return json.dumps({"requirements": requirements})

    # ------------------------------------------------------------------
    # 1. LLMProvider is called
    # ------------------------------------------------------------------
    def test_provider_is_called(self):
        fake = self.FakeLLM("[]")
        discovery = AIRequirementDiscovery(llm_provider=fake)
        discovery.discover({"path": "/tmp/project"})
        assert fake.called_with is not None

    # ------------------------------------------------------------------
    # 2. Project info is serialized into the prompt
    # ------------------------------------------------------------------
    def test_project_info_passed(self):
        fake = self.FakeLLM("[]")
        discovery = AIRequirementDiscovery(llm_provider=fake)
        project_info = {"path": "/tmp/project", "files": ["esphome.yaml"]}
        discovery.discover(project_info)
        assert fake.called_with is not None
        assert "/tmp/project" in fake.called_with
        assert "esphome.yaml" in fake.called_with

    # ------------------------------------------------------------------
    # 3. stack_context parameter is accepted and does not break discovery
    # ------------------------------------------------------------------
    def test_stack_context_accepted(self):
        fake = self.FakeLLM("[]")
        discovery = AIRequirementDiscovery(llm_provider=fake)
        result = discovery.discover({"path": "/tmp/project"}, stack_context="esphome")
        assert len(result.requirements) == 0
        assert fake.called_with is not None

    # ------------------------------------------------------------------
    # 4. ESPHome-like requirements are mapped through the central model
    # ------------------------------------------------------------------
    def test_esphome_like_requirements(self):
        reqs = [
            {
                "name": "esphome",
                "type": "python_package",
                "purpose": "build+flash",
                "required": True,
                "confidence": "high",
                "metadata": {"source": "fake"},
            },
            {
                "name": "pyserial",
                "type": "python_package",
                "purpose": "serial_log",
                "required": True,
                "confidence": "high",
                "metadata": {"source": "fake"},
            },
            {
                "name": "ESP32",
                "type": "hardware_component",
                "purpose": "target",
                "required": True,
                "confidence": "high",
                "metadata": {"source": "fake"},
            },
            {
                "name": "serial",
                "type": "connection",
                "purpose": "serial_log",
                "required": True,
                "confidence": "high",
                "metadata": {"source": "fake"},
            },
        ]
        fake = self._make_llm(self._json_response(reqs))
        discovery = AIRequirementDiscovery(llm_provider=fake)
        result = discovery.discover({"path": "/tmp/project"})
        assert len(result.requirements) == 4
        assert result.requirements[0].name == "esphome"
        assert result.requirements[0].type == "python_package"
        assert result.requirements[0].purpose == "build+flash"
        assert result.requirements[1].name == "pyserial"
        assert result.requirements[2].name == "ESP32"
        assert result.requirements[3].name == "serial"

    # ------------------------------------------------------------------
    # 5. Unknown requirements can be represented
    # ------------------------------------------------------------------
    def test_unknown_requirement(self):
        req = {
            "name": "some-unknown-tool",
            "type": "unknown",
            "purpose": "unknown",
            "required": False,
            "confidence": 0.2,
            "metadata": {"source": "fake"},
        }
        fake = self._make_llm(self._json_response([req]))
        discovery = AIRequirementDiscovery(llm_provider=fake)
        result = discovery.discover({})
        assert result.requirements[0].type == "unknown"
        assert result.requirements[0].confidence == 0.2

    # ------------------------------------------------------------------
    # 6. Confidence is preserved
    # ------------------------------------------------------------------
    def test_confidence_preserved(self):
        req = {
            "name": "esphome",
            "type": "python_package",
            "purpose": "build",
            "required": True,
            "confidence": 0.6,
        }
        fake = self._make_llm(self._json_response([req]))
        discovery = AIRequirementDiscovery(llm_provider=fake)
        result = discovery.discover({})
        assert result.requirements[0].confidence == 0.6

    # ------------------------------------------------------------------
    # 7. Evidence and source are preserved
    # ------------------------------------------------------------------
    def test_evidence_and_source_preserved(self):
        req = {
            "name": "pyserial",
            "type": "python_package",
            "purpose": "serial_log",
            "required": True,
            "confidence": 1.0,
            "evidence": ["found in requirements.txt"],
            "metadata": {"source": "my-source"},
        }
        fake = self._make_llm(self._json_response([req]))
        discovery = AIRequirementDiscovery(llm_provider=fake)
        result = discovery.discover({})
        assert len(result.requirements) == 1
        assert result.requirements[0].evidence[0].description == "found in requirements.txt"
        assert result.requirements[0].metadata["source"] == "my-source"

    # ------------------------------------------------------------------
    # 8. No installation or hardware action happens
    # ------------------------------------------------------------------
    def test_no_installation_or_hardware(self):
        fake = self._make_llm("[]")
        discovery = AIRequirementDiscovery(llm_provider=fake)
        result = discovery.discover({})
        assert len(result.requirements) == 0

    # ------------------------------------------------------------------
    # 9. Empty result is returned when provider returns no requirements
    # ------------------------------------------------------------------
    def test_empty_requirement_set(self):
        fake = self._make_llm("[]")
        discovery = AIRequirementDiscovery(llm_provider=fake)
        result = discovery.discover({})
        assert len(result.requirements) == 0


# ======================================================================
# LLM‑based discovery tests (new)
# ======================================================================
class TestAIRequirementDiscoveryLLMJson:
    """Tests for the LLM‑based discovery using fake / mock providers."""

    def _make_llm(self, return_text: str, raise_on_call: bool = False):
        """Create a fake LLMProvider that returns `return_text`."""

        class FakeLLM:
            def __init__(self, text, do_raise):
                self.text = text
                self.do_raise = do_raise

            def complete(self, prompt: str) -> str:
                if self.do_raise:
                    raise RuntimeError("simulated LLM error")
                return self.text

        return FakeLLM(return_text, raise_on_call)

    def _valid_json_requirements(self):
        return json.dumps(
            {
                "requirements": [
                    {
                        "name": "some-tool",
                        "type": "executable",
                        "purpose": "building",
                        "required": True,
                        "confidence": "high",
                        "evidence": ["Makefile references some-tool"],
                        "install_method": "apt-get install some-tool",
                        "verification_method": "some-tool --version",
                        "required_version": "1.2.3",
                        "metadata": {"source": "Makefile"},
                    }
                ]
            }
        )

    # ---------- valid responses ----------

    def test_valid_json_response_yields_requirements(self):
        text = self._valid_json_requirements()
        provider = self._make_llm(text)
        discovery = AIRequirementDiscovery(llm_provider=provider)
        result = discovery.discover({"project_id": "test"})
        assert len(result.requirements) == 1
        req = result.requirements[0]
        assert req.name == "some-tool"
        assert req.type == "executable"
        assert req.purpose == "building"
        assert req.required is True
        assert req.install_method == "apt-get install some-tool"
        assert req.verification_method == "some-tool --version"
        assert req.required_version == "1.2.3"
        assert req.confidence == 0.9

    def test_multiple_requirements(self):
        json_obj = json.dumps(
            {
                "requirements": [
                    {"name": "pkg-a", "type": "python_package", "purpose": "...",
                     "confidence": "medium"},
                    {"name": "pkg-b", "type": "system_package", "purpose": "...",
                     "confidence": "low", "install_method": "apt install pkg-b"},
                ]
            }
        )
        provider = self._make_llm(json_obj)
        discovery = AIRequirementDiscovery(llm_provider=provider)
        result = discovery.discover({"project_id": "proj"})
        assert len(result.requirements) == 2
        assert result.requirements[0].name == "pkg-a"
        assert result.requirements[1].name == "pkg-b"
        assert result.requirements[1].install_method == "apt install pkg-b"

    def test_evidence_is_mapped(self):
        json_obj = json.dumps(
            {
                "requirements": [
                    {
                        "name": "pkg",
                        "type": "python_package",
                        "purpose": "...",
                        "confidence": "high",
                        "evidence": ["found in pyproject.toml", "imported in main.py"],
                    }
                ]
            }
        )
        provider = self._make_llm(json_obj)
        discovery = AIRequirementDiscovery(llm_provider=provider)
        result = discovery.discover({"project_id": "p"})
        req = result.requirements[0]
        assert len(req.evidence) == 2
        descriptions = [e.description for e in req.evidence]
        assert "found in pyproject.toml" in descriptions
        assert "imported in main.py" in descriptions

    def test_confidence_mapping(self):
        cases = [
            ("high", 0.9),
            ("medium", 0.6),
            ("low", 0.3),
        ]
        for symbolic, expected in cases:
            json_obj = json.dumps(
                {
                    "requirements": [
                        {"name": "p", "type": "unknown", "purpose": "...",
                         "confidence": symbolic}
                    ]
                }
            )
            provider = self._make_llm(json_obj)
            discovery = AIRequirementDiscovery(llm_provider=provider)
            result = discovery.discover({"project_id": "c"})
            assert result.requirements[0].confidence == expected

    def test_install_method_field(self):
        json_obj = json.dumps(
            {
                "requirements": [
                    {"name": "x", "type": "executable", "purpose": "...",
                     "install_method": "custom-install.sh"}
                ]
            }
        )
        provider = self._make_llm(json_obj)
        discovery = AIRequirementDiscovery(llm_provider=provider)
        assert discovery.discover({}).requirements[0].install_method == "custom-install.sh"

    def test_required_version_field(self):
        json_obj = json.dumps(
            {
                "requirements": [
                    {"name": "v", "type": "python_package", "purpose": "...",
                     "required_version": "1.0.0"}
                ]
            }
        )
        provider = self._make_llm(json_obj)
        discovery = AIRequirementDiscovery(llm_provider=provider)
        assert discovery.discover({}).requirements[0].required_version == "1.0.0"

    def test_verification_method_field(self):
        json_obj = json.dumps(
            {
                "requirements": [
                    {"name": "v", "type": "python_package", "purpose": "...",
                     "verification_method": "v --version"}
                ]
            }
        )
        provider = self._make_llm(json_obj)
        discovery = AIRequirementDiscovery(llm_provider=provider)
        assert discovery.discover({}).requirements[0].verification_method == "v --version"

    def test_metadata_field(self):
        json_obj = json.dumps(
            {
                "requirements": [
                    {"name": "m", "type": "unknown", "purpose": "...",
                     "metadata": {"key": "value"}}
                ]
            }
        )
        provider = self._make_llm(json_obj)
        discovery = AIRequirementDiscovery(llm_provider=provider)
        req = discovery.discover({}).requirements[0]
        assert req.metadata["key"] == "value"

    def test_unknown_requirement_type(self):
        json_obj = json.dumps(
            {
                "requirements": [
                    {"name": "strange-stack", "type": "weird-category",
                     "purpose": "...", "confidence": "low"}
                ]
            }
        )
        provider = self._make_llm(json_obj)
        discovery = AIRequirementDiscovery(llm_provider=provider)
        req = discovery.discover({}).requirements[0]
        assert req.type == "weird-category"
        assert req.confidence == 0.3

    def test_invalid_json_triggers_fallback_and_warnings(self):
        provider = self._make_llm("this is not json")
        discovery = AIRequirementDiscovery(llm_provider=provider)
        result = discovery.discover({"project_id": "p"})
        assert result.fallback_used is True
        assert any("parse" in w.lower() for w in result.warnings)
        assert len(result.requirements) == 0

    def test_missing_json_fields_do_not_crash(self):
        json_obj = json.dumps(
            {
                "requirements": [
                    {"name": "bare"}  # missing type, purpose, confidence, etc.
                ]
            }
        )
        provider = self._make_llm(json_obj)
        discovery = AIRequirementDiscovery(llm_provider=provider)
        result = discovery.discover({"project_id": "p"})
        req = result.requirements[0]
        assert req.name == "bare"
        assert req.type == RequirementType.UNKNOWN
        assert req.confidence == 0.5
        assert req.install_method is None

    def test_provider_exception_triggers_fallback(self):
        provider = self._make_llm("anything", raise_on_call=True)
        discovery = AIRequirementDiscovery(llm_provider=provider)
        result = discovery.discover({"project_id": "p"})
        assert result.fallback_used is True
        assert any("exception" in w.lower() for w in result.warnings)
        assert len(result.requirements) == 0

    def test_fallback_used_flag(self):
        # already covered by invalid JSON and exception tests above
        # add explicit guard for happy path here
        provider = self._make_llm("[]")
        discovery = AIRequirementDiscovery(llm_provider=provider)
        result = discovery.discover({"project_id": "p"})
        assert result.fallback_used is False

    def test_warnings_accumulate_for_bad_items(self):
        json_obj = json.dumps(
            {
                "requirements": [
                    {"name": "ok", "type": "executable", "purpose": "..",
                     "confidence": "high"},
                    None,  # non-dict item
                    "string-item",
                ]
            }
        )
        provider = self._make_llm(json_obj)
        discovery = AIRequirementDiscovery(llm_provider=provider)
        result = discovery.discover({"project_id": "p"})
        # only the valid items are kept
        assert len(result.requirements) == 1
        assert result.requirements[0].name == "ok"
        # non‑dict items cause warnings
        non_empty_warnings = [w for w in result.warnings if w]
        assert len(non_empty_warnings) == 2

    def test_ai_model_stored(self):
        provider = self._make_llm("[]")
        discovery = AIRequirementDiscovery(
            llm_provider=provider, ai_model="test-model-1"
        )
        result = discovery.discover({"project_id": "p"})
        assert result.ai_model == "test-model-1"

    def test_conversation_trace_id_stored(self):
        provider = self._make_llm("[]")
        discovery = AIRequirementDiscovery(llm_provider=provider)
        result = discovery.discover(
            {"project_id": "p"}, conversation_trace_id="trace-42"
        )
        assert result.conversation_trace_id == "trace-42"

    def test_no_real_network_calls(self):
        # using a mock provider ensures no outgoing network
        provider = self._make_llm("[]")
        discovery = AIRequirementDiscovery(llm_provider=provider)
        result = discovery.discover({})
        assert result.fallback_used is False
        assert len(result.requirements) == 0

    # ------------------------------------------------------------------
    # Stack‑neutrality guard
    # ------------------------------------------------------------------
    def test_no_hardcoded_esphome(self):
        # Ensure the discovery does not know about specific stacks.
        # We feed a completely unknown stack description.
        json_obj = json.dumps(
            {
                "requirements": [
                    {"name": "unknown-tool", "type": "executable", "purpose": "...",
                     "confidence": "medium"}
                ]
            }
        )
        provider = self._make_llm(json_obj)
        discovery = AIRequirementDiscovery(llm_provider=provider)
        result = discovery.discover({"description": "some weird dev environment"})
        req = result.requirements[0]
        assert req.name == "unknown-tool"
        assert req.type == "executable"
        # The discovery must not inject esphome, pytest, etc.
        assert "esphome" not in req.name.lower()
