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

    def test_user_request_and_project_intelligence_are_distinct_prompt_inputs(self):
        fake = self.FakeLLM("[]")
        discovery = AIRequirementDiscovery(llm_provider=fake)

        discovery.discover(
            {"project_kind": "existing", "languages": ["Python"]},
            user_request="Add a status endpoint",
        )

        assert "Add a status endpoint" in fake.called_with
        assert '"project_kind": "existing"' in fake.called_with
        assert '"languages": [' in fake.called_with

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

    def test_forward_requirement_has_separate_current_request_activation(self):
        provider = self._make_llm(json.dumps({"requirements": [{
            "id": "future-capability",
            "name": "future-capability",
            "type": "capability",
            "purpose": "continued project development",
            "required": True,
            "active_for_current_request": False,
            "blocks_current_operation": False,
            "activation_reason": "not used by this operation",
            "confidence": "high",
            "evidence": ["project target metadata"],
        }]}))

        result = AIRequirementDiscovery(llm_provider=provider).discover(
            {"project_id": "future-project"},
            user_request="perform the current operation",
        )

        assert result.requirements[0].required is True
        assert result.activations[0].requirement_id == result.requirements[0].id
        assert result.activations[0].active is False
        assert result.activations[0].blocks_current_operation is False

    def test_discovery_prompt_defines_type_by_required_kind_not_install_mechanism(self):
        discovery = AIRequirementDiscovery(llm_provider=self._make_llm("[]"))

        prompt = discovery._build_prompt({}, "current operation")

        assert "describes what kind of thing is required, not how it is installed" in prompt
        assert "merely because one installation option" in prompt
        assert "active_for_current_request" in prompt

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

    def test_provider_exception_sets_fallback_and_warning(self):
        provider = self._make_llm(
            "",
            raise_on_call=True,
        )

        discovery = AIRequirementDiscovery(
            llm_provider=provider,
            ai_model="deepseek/deepseek-v4-pro",
        )

        result = discovery.discover(
            {"project_id": "workflow-demo"}
        )

        assert result.fallback_used is True
        assert len(result.requirements) == 0
        assert result.warnings
        assert "LLM provider raised an exception" in result.warnings[0]

    def test_invalid_json_sets_fallback_and_warning(self):
        provider = self._make_llm(
            "this is not valid json"
        )

        discovery = AIRequirementDiscovery(
            llm_provider=provider,
            ai_model="deepseek/deepseek-v4-pro",
        )

        result = discovery.discover(
            {"project_id": "workflow-demo"}
        )

        assert result.fallback_used is True
        assert len(result.requirements) == 0
        assert result.warnings
        assert "Failed to parse LLM response" in result.warnings[0]

    def test_empty_requirements_is_not_treated_as_provider_fallback(self):
        provider = self._make_llm(
            '{"requirements": []}'
        )

        discovery = AIRequirementDiscovery(
            llm_provider=provider,
            ai_model="deepseek/deepseek-v4-pro",
        )

        result = discovery.discover(
            {"project_id": "workflow-demo"}
        )

        assert result.fallback_used is False
        assert result.requirements == ()
        assert result.warnings == ()


class TestStructuredDiscoveryResponses:
    class StructuredFake:
        def __init__(self, response):
            self.response = response
            self.ordinary_calls = 0
            self.structured_calls = 0

        def complete(self, _prompt):
            self.ordinary_calls += 1
            return self.response

        def complete_structured(self, _prompt):
            self.structured_calls += 1
            return self.response

    @staticmethod
    def requirement(name="tool"):
        return {"name": name, "type": "executable", "purpose": "test"}

    def test_require_json_true_uses_structured_provider_capability(self):
        provider = self.StructuredFake('{"requirements": []}')
        result = AIRequirementDiscovery(
            llm_provider=provider, require_json=True,
        ).discover({})

        assert result.fallback_used is False
        assert provider.structured_calls == 1
        assert provider.ordinary_calls == 0

    def test_require_json_false_preserves_ordinary_completion(self):
        provider = self.StructuredFake('{"requirements": []}')
        AIRequirementDiscovery(
            llm_provider=provider, require_json=False,
        ).discover({})

        assert provider.ordinary_calls == 1
        assert provider.structured_calls == 0

    @pytest.mark.parametrize("payload", [
        lambda item: json.dumps([item]),
        lambda item: json.dumps({"requirements": [item]}),
        lambda item: json.dumps(item),
        lambda item: f"```json\n{json.dumps({'requirements': [item]})}\n```",
    ])
    def test_supported_json_shapes_and_json_fence(self, payload):
        provider = self.StructuredFake(payload(self.requirement()))
        result = AIRequirementDiscovery(llm_provider=provider).discover({})

        assert result.fallback_used is False
        assert [requirement.name for requirement in result.requirements] == ["tool"]

    @pytest.mark.parametrize("response", [
        'Here is the result: {"requirements": []}',
        '```json\n{"requirements": [}\n```',
    ])
    def test_prose_and_malformed_json_remain_controlled_failures(self, response):
        provider = self.StructuredFake(response)
        activity = []
        discovery = AIRequirementDiscovery(llm_provider=provider)
        discovery.set_activity_callback(lambda **details: activity.append(details))

        result = discovery.discover({})

        assert result.fallback_used is True
        assert result.requirements == ()
        assert activity[-1]["runtime_state"] == "failed"
        assert activity[-1]["error_category"] == "invalid_json"
        assert response not in str(activity)

    def test_invalid_response_structure_has_safe_distinct_category(self):
        provider = self.StructuredFake('{"unexpected": []}')
        activity = []
        discovery = AIRequirementDiscovery(llm_provider=provider)
        discovery.set_activity_callback(lambda **details: activity.append(details))

        result = discovery.discover({})

        assert result.fallback_used is True
        assert activity[-1]["error_category"] == "invalid_response_structure"

    def test_legacy_deterministic_provider_needs_no_structured_method(self):
        provider = TestAIRequirementDiscovery.FakeLLM('{"requirements": []}')

        result = AIRequirementDiscovery(
            llm_provider=provider, require_json=True,
        ).discover({})

        assert result.fallback_used is False
        assert provider.called_with is not None


class MultiResponseProvider:
    """Provider that returns a different response for each call."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0
        self.last_prompts = []

    def complete(self, prompt):
        self.last_prompts.append(prompt)
        resp = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return resp

    def complete_structured(self, prompt):
        return self.complete(prompt)


class TestStructuralRepair:
    """Tests for the bounded structural repair path."""

    @staticmethod
    def _requirements_payload():
        return json.dumps({"requirements": [
            {"name": "tool", "type": "executable", "purpose": "build",
             "required": True, "confidence": "high"},
        ]})

    @staticmethod
    def _wrong_structure_payload():
        return json.dumps({"unexpected": []})

    # 1. valid {"requirements": [...]} succeeds without repair
    def test_valid_structure_succeeds_without_repair(self):
        provider = MultiResponseProvider(self._requirements_payload())
        result = AIRequirementDiscovery(
            llm_provider=provider, require_json=True,
        ).discover({"project_id": "p"})

        assert result.fallback_used is False
        assert len(result.requirements) == 1
        assert result.requirements[0].name == "tool"
        assert provider.calls == 1

    # 2. valid JSON with wrong root structure triggers exactly one repair
    def test_wrong_structure_triggers_exactly_one_repair(self):
        provider = MultiResponseProvider(
            self._wrong_structure_payload(),
            self._requirements_payload(),
        )
        result = AIRequirementDiscovery(
            llm_provider=provider, require_json=True,
        ).discover({"project_id": "p"})

        assert result.fallback_used is False
        assert len(result.requirements) == 1
        assert result.requirements[0].name == "tool"
        assert provider.calls == 2

    # 3. successful repair returns normal requirements/activations
    def test_successful_repair_returns_requirements_and_activations(self):
        payload = json.dumps({"requirements": [{
            "name": "repaired-tool",
            "type": "capability",
            "purpose": "repaired",
            "required": True,
            "confidence": "high",
            "active_for_current_request": True,
            "blocks_current_operation": True,
            "activation_reason": "needed now",
        }]})
        provider = MultiResponseProvider(
            json.dumps({}), payload,
        )
        result = AIRequirementDiscovery(
            llm_provider=provider, require_json=True,
        ).discover({"project_id": "p"})

        assert result.fallback_used is False
        assert result.requirements[0].name == "repaired-tool"
        assert result.activations[0].active is True
        assert result.activations[0].blocks_current_operation is True
        assert result.activations[0].reason == "needed now"

    # 4. repair cannot cause an unbounded retry
    def test_repair_is_exactly_one_attempt_not_unbounded(self):
        provider = MultiResponseProvider(
            self._wrong_structure_payload(),
            self._wrong_structure_payload(),
            self._requirements_payload(),
        )
        result = AIRequirementDiscovery(
            llm_provider=provider, require_json=True,
        ).discover({"project_id": "p"})

        assert result.fallback_used is True
        assert provider.calls == 2

    # 5. failed repair preserves fallback/blocking behavior
    def test_failed_repair_preserves_fallback(self):
        provider = MultiResponseProvider(
            self._wrong_structure_payload(),
            self._wrong_structure_payload(),
        )
        result = AIRequirementDiscovery(
            llm_provider=provider, require_json=True,
        ).discover({"project_id": "p"})

        assert result.fallback_used is True
        assert len(result.requirements) == 0
        assert any("parse" in w.lower() for w in result.warnings)
        assert provider.calls == 2

    # 6. arbitrary alternative root keys are not silently accepted by parser
    def test_arbitrary_root_keys_not_silently_accepted(self):
        provider = TestStructuredDiscoveryResponses.StructuredFake(
            json.dumps({"result": [], "data": {"items": []}}),
        )
        activity = []
        discovery = AIRequirementDiscovery(llm_provider=provider)
        discovery.set_activity_callback(
            lambda **details: activity.append(details),
        )

        result = discovery.discover({"project_id": "p"})

        assert result.fallback_used is True
        assert activity[-1]["error_category"] == "invalid_response_structure"

    # 7. raw provider response not exposed
    def test_raw_provider_response_not_in_warnings_or_activity(self):
        raw_content = "some-proprietary-key-abc123"
        provider = MultiResponseProvider(
            json.dumps({"wrong_root": raw_content}),
            json.dumps({"wrong_root": raw_content}),
        )
        activity = []
        discovery = AIRequirementDiscovery(llm_provider=provider)
        discovery.set_activity_callback(
            lambda **details: activity.append(details),
        )

        result = discovery.discover({"project_id": "p"})

        assert result.fallback_used is True
        for warning in result.warnings:
            assert raw_content not in warning
        for entry in activity:
            serialized = str(entry)
            assert raw_content not in serialized

    def test_raw_provider_response_not_exposed_in_activity_details(self):
        provider = MultiResponseProvider(
            json.dumps({"data": "secret-value"}),
            json.dumps({"requirements": []}),
        )
        activity = []
        discovery = AIRequirementDiscovery(llm_provider=provider)
        discovery.set_activity_callback(
            lambda **details: activity.append(details),
        )

        result = discovery.discover({"project_id": "p"})

        assert result.fallback_used is False
        for entry in activity:
            serialized = str(entry)
            assert "secret-value" not in serialized
            assert '"data"' not in serialized

    # 8. successful discovery retains normal completed milestone
    def test_successful_discovery_activity_ends_with_completed(self):
        provider = MultiResponseProvider(self._requirements_payload())
        activity = []
        discovery = AIRequirementDiscovery(llm_provider=provider)
        discovery.set_activity_callback(
            lambda **details: activity.append(details),
        )

        discovery.discover({"project_id": "p"})

        assert activity[-1]["runtime_state"] == "completed"

    # 9. fallback discovery has failure activity state
    def test_fallback_discovery_activity_ends_with_failed(self):
        provider = MultiResponseProvider(
            self._wrong_structure_payload(),
            self._wrong_structure_payload(),
        )
        activity = []
        discovery = AIRequirementDiscovery(llm_provider=provider)
        discovery.set_activity_callback(
            lambda **details: activity.append(details),
        )

        discovery.discover({"project_id": "p"})

        assert activity[-1]["runtime_state"] == "failed"

    # 10. existing RequirementActivation behavior remains intact
    def test_forward_looking_activation_preserved_through_repair(self):
        forward_payload = json.dumps({"requirements": [{
            "name": "future-tool",
            "type": "executable",
            "purpose": "future needs",
            "required": True,
            "confidence": "high",
            "active_for_current_request": False,
            "blocks_current_operation": False,
            "activation_reason": "forward-looking only",
            "evidence": ["project roadmap"],
        }]})
        provider = MultiResponseProvider(
            json.dumps({}), forward_payload,
        )

        result = AIRequirementDiscovery(llm_provider=provider).discover(
            {"project_id": "p"},
            user_request="current operation",
        )

        assert result.fallback_used is False
        assert result.requirements[0].required is True
        assert result.activations[0].active is False
        assert result.activations[0].blocks_current_operation is False
        assert result.activations[0].reason == "forward-looking only"

    def test_provider_exception_during_repair_triggers_fallback(self):
        class RepairExceptionProvider:
            def complete_structured(self, prompt):
                raise RuntimeError("repair failed")

            def complete(self, prompt):
                raise RuntimeError("repair failed")

        provider = MultiResponseProvider(self._wrong_structure_payload())
        # Replace original response list to include our exception provider
        # Actually use the MultiResponseProvider's first response for primary
        # then a failing provider for repair won't work because _attempt_repair
        # uses self._provider directly.
        # Use a separate test approach: simulate repair exception.
        class FailOnSecondCall:
            def __init__(self):
                self.calls = 0

            def complete(self, _prompt):
                self.calls += 1
                return json.dumps({"wrong": "shape"})

            def complete_structured(self, _prompt):
                self.calls += 1
                if self.calls == 1:
                    return json.dumps({"wrong": "shape"})
                raise RuntimeError("repair provider failure")

        provider = FailOnSecondCall()
        activity = []
        discovery = AIRequirementDiscovery(
            llm_provider=provider, require_json=True,
        )
        discovery.set_activity_callback(
            lambda **details: activity.append(details),
        )

        result = discovery.discover({"project_id": "p"})

        assert result.fallback_used is True
        assert len(result.requirements) == 0

    def test_repair_prompt_does_not_contain_raw_response(self):
        payload = json.dumps({"not": "requirements", "secret": "abc123"})
        provider = MultiResponseProvider(
            payload, json.dumps({"requirements": []}),
        )

        AIRequirementDiscovery(
            llm_provider=provider, require_json=True,
        ).discover({"project_id": "p"})

        for prompt_text in provider.last_prompts:
            assert "abc123" not in prompt_text
            assert '"secret"' not in prompt_text

    def test_prompt_leads_with_output_format_instruction(self):
        discovery = AIRequirementDiscovery(
            llm_provider=MultiResponseProvider("[]"),
        )
        prompt = discovery._build_prompt({}, "test request")

        assert prompt.strip().startswith(
            'Return a JSON object with the single key "requirements"'
        )
        assert "No other top-level keys" in prompt
        assert "No commentary outside the JSON" in prompt

    def test_repair_prompt_requires_exact_structure(self):
        discovery = AIRequirementDiscovery(
            llm_provider=MultiResponseProvider("[]"),
        )
        prompt = discovery._build_repair_prompt({}, "test")

        assert '"requirements"' in prompt
        assert "exactly this format" in prompt.lower() or "exact" in prompt.lower()
        assert "Do NOT invent" in prompt
        assert "Preserve every requirement" in prompt

    def test_repair_not_attempted_when_provider_is_none(self):
        discovery = AIRequirementDiscovery(
            llm_provider=None, require_json=True,
        )
        result = discovery.discover({"project_id": "p"})

        assert result.fallback_used is True
        assert len(result.requirements) == 0

    def test_repair_response_empty_requirements_is_not_fallback(self):
        provider = MultiResponseProvider(
            json.dumps({"wrong": "key"}),
            json.dumps({"requirements": []}),
        )
        result = AIRequirementDiscovery(
            llm_provider=provider, require_json=True,
        ).discover({"project_id": "p"})

        assert result.fallback_used is False
        assert result.requirements == ()

    def test_repair_response_with_single_requirement_shape_accepted(self):
        provider = MultiResponseProvider(
            json.dumps({}),
            json.dumps({"name": "single-tool", "type": "executable",
                         "purpose": "test"}),
        )
        result = AIRequirementDiscovery(
            llm_provider=provider, require_json=True,
        ).discover({"project_id": "p"})

        assert result.fallback_used is False
        assert result.requirements[0].name == "single-tool"


class TestDiscoveryPromptRoles:
    """Tests verifying the explicit functional role in discovery prompts."""

    def test_discovery_prompt_contains_explicit_role(self):
        discovery = AIRequirementDiscovery(
            llm_provider=MultiResponseProvider("[]"),
        )
        prompt = discovery._build_prompt({"project_id": "p"}, "test request")

        assert "Requirement Discovery Analyst of AI-Dev-Center" in prompt
        assert "not approve or execute changes" in prompt

    def test_repair_prompt_contains_explicit_role(self):
        discovery = AIRequirementDiscovery(
            llm_provider=MultiResponseProvider("[]"),
        )
        prompt = discovery._build_repair_prompt({"project_id": "p"}, "test request")

        assert "Requirement Discovery Analyst of AI-Dev-Center" in prompt
        assert "not approve or execute changes" in prompt

    def test_discovery_prompt_role_does_not_grant_execution_authority(self):
        discovery = AIRequirementDiscovery(
            llm_provider=MultiResponseProvider("[]"),
        )
        prompt = discovery._build_prompt({}, "test")

        assert "not approve or execute changes" in prompt

    def test_effective_prompt_stored_after_discover(self):
        provider = MultiResponseProvider(
            json.dumps({"requirements": [{"name": "x", "type": "executable",
             "purpose": "test", "required": True, "confidence": "high"}]}),
        )
        discovery = AIRequirementDiscovery(
            llm_provider=provider, require_json=True,
        )
        discovery.discover({"project_id": "p"})

        assert discovery.effective_prompt is not None
        assert "Requirement Discovery Analyst" in discovery.effective_prompt

    def test_effective_repair_prompt_stored_after_repair(self):
        provider = MultiResponseProvider(
            json.dumps({"wrong": "shape"}),
            json.dumps({"requirements": [{"name": "x", "type": "executable",
             "purpose": "test", "required": True, "confidence": "high"}]}),
        )
        discovery = AIRequirementDiscovery(
            llm_provider=provider, require_json=True,
        )
        discovery.discover({"project_id": "p"})

        assert discovery.effective_repair_prompt is not None
        assert "Requirement Discovery Analyst" in discovery.effective_repair_prompt

    def test_oc_009_behaviour_remains_intact(self):
        provider = MultiResponseProvider(
            json.dumps({"not_requirements": []}),
            json.dumps({"not_requirements": []}),
        )
        discovery = AIRequirementDiscovery(
            llm_provider=provider, require_json=True,
        )
        result = discovery.discover({"project_id": "p"})

        assert result.fallback_used is True
        assert len(result.requirements) == 0
        assert any("parse" in w.lower() for w in result.warnings)

    def test_discovery_prompt_contains_compact_adc_context(self):
        discovery = AIRequirementDiscovery(
            llm_provider=MultiResponseProvider("[]"),
        )
        prompt = discovery._build_prompt({"project_id": "p"}, "test")

        assert "controlled engineering system" in prompt
        assert "software, firmware, and hardware-related" in prompt

    def test_repair_prompt_contains_compact_adc_context(self):
        discovery = AIRequirementDiscovery(
            llm_provider=MultiResponseProvider("[]"),
        )
        prompt = discovery._build_repair_prompt({"project_id": "p"}, "test")

        assert "controlled engineering system" in prompt
        assert "software, firmware, and hardware-related" in prompt


class TestVerificationExecutableDiscovery:
    """Tests for the structured verification_executable discovery contract."""

    def test_verification_executable_is_preserved(self):
        provider = MultiResponseProvider(
            '{"requirements": [{"name": "Python 3", "type": "system_package", '
            '"purpose": "runtime", "required": true, "confidence": "high", '
            '"verification_executable": "python3"}]}'
        )
        result = AIRequirementDiscovery(
            llm_provider=provider, require_json=True,
        ).discover({"project_id": "p"})

        assert result.fallback_used is False
        assert result.requirements[0].name == "Python 3"
        assert result.requirements[0].verification_executable == "python3"

    def test_verification_executable_omitted_stays_none(self):
        provider = MultiResponseProvider(
            '{"requirements": [{"name": "without-exec", "type": "system_package", '
            '"purpose": "runtime", "required": true, "confidence": "high"}]}'
        )
        result = AIRequirementDiscovery(
            llm_provider=provider, require_json=True,
        ).discover({"project_id": "p"})

        assert result.fallback_used is False
        assert result.requirements[0].verification_executable is None

    def test_verification_executable_null_is_none(self):
        provider = MultiResponseProvider(
            '{"requirements": [{"name": "null-exec", "type": "system_package", '
            '"purpose": "runtime", "required": true, "confidence": "high", '
            '"verification_executable": null}]}'
        )
        result = AIRequirementDiscovery(
            llm_provider=provider, require_json=True,
        ).discover({"project_id": "p"})

        assert result.fallback_used is False
        assert result.requirements[0].verification_executable is None

    def test_prompt_documents_verification_executable_field(self):
        discovery = AIRequirementDiscovery(
            llm_provider=MultiResponseProvider("[]"),
        )
        prompt = discovery._build_prompt({}, "test")

        assert "verification_executable" in prompt

    def test_prompt_still_leads_with_output_contract(self):
        discovery = AIRequirementDiscovery(
            llm_provider=MultiResponseProvider("[]"),
        )
        prompt = discovery._build_prompt({}, "test")

        assert prompt.strip().startswith(
            'Return a JSON object with the single key "requirements"'
        )
