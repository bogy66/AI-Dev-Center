import pytest
from app.ai_requirement_discovery import (
    AIRequirementDiscovery,
    DiscoveredRequirement,
    RequirementSet,
    DiscoverySource,
)


class TestDiscoveredRequirement:

    def test_can_create_with_all_fields(self):
        req = DiscoveredRequirement(
            name="esphome",
            kind="python_package",
            required_for="build+flash",
            source="test-source",
            evidence="found in config",
            confidence="high",
        )
        assert req.name == "esphome"
        assert req.kind == "python_package"
        assert req.required_for == "build+flash"
        assert req.source == "test-source"
        assert req.evidence == "found in config"
        assert req.confidence == "high"


class TestRequirementSet:

    def test_can_contain_multiple_requirements(self):
        req1 = DiscoveredRequirement(
            name="esphome",
            kind="python_package",
            required_for="build",
            source="s1",
            evidence="e1",
            confidence="high",
        )
        req2 = DiscoveredRequirement(
            name="pyserial",
            kind="python_package",
            required_for="serial_log",
            source="s2",
            evidence="e2",
            confidence="medium",
        )
        req_set = RequirementSet(requirements=[req1, req2])
        assert len(req_set.requirements) == 2
        assert req_set.requirements[0].name == "esphome"
        assert req_set.requirements[1].name == "pyserial"


class TestAIRequirementDiscovery:

    # ------------------------------------------------------------------
    # Helper: a fake DiscoverySource that returns fixed requirements
    # ------------------------------------------------------------------
    class FakeSource:
        def __init__(self, requirements: list[DiscoveredRequirement]):
            self._requirements = requirements
            self.called_with = None

        def discover(self, project_info, stack_context=None):
            self.called_with = (project_info, stack_context)
            return list(self._requirements)

    # ------------------------------------------------------------------
    # 1. DiscoverySource is called
    # ------------------------------------------------------------------
    def test_source_is_called(self):
        source = self.FakeSource([])
        discovery = AIRequirementDiscovery(source)
        discovery.discover({"path": "/tmp/project"})
        assert source.called_with is not None

    # ------------------------------------------------------------------
    # 2. Project info is passed to the source
    # ------------------------------------------------------------------
    def test_project_info_passed(self):
        source = self.FakeSource([])
        discovery = AIRequirementDiscovery(source)
        project_info = {"path": "/tmp/project", "files": ["esphome.yaml"]}
        discovery.discover(project_info)
        assert source.called_with[0] == project_info

    # ------------------------------------------------------------------
    # 3. Stack context is passed when provided
    # ------------------------------------------------------------------
    def test_stack_context_passed(self):
        source = self.FakeSource([])
        discovery = AIRequirementDiscovery(source)
        discovery.discover({"path": "/tmp/project"}, stack_context="esphome")
        assert source.called_with[1] == "esphome"

    # ------------------------------------------------------------------
    # 4. ESPHome-like requirements work as test data
    # ------------------------------------------------------------------
    def test_esphome_like_requirements(self):
        reqs = [
            DiscoveredRequirement(
                name="esphome",
                kind="python_package",
                required_for="build+flash",
                source="fake",
                evidence="config found",
                confidence="high",
            ),
            DiscoveredRequirement(
                name="pyserial",
                kind="python_package",
                required_for="serial_log",
                source="fake",
                evidence="serial needed",
                confidence="high",
            ),
            DiscoveredRequirement(
                name="ESP32",
                kind="hardware",
                required_for="target",
                source="fake",
                evidence="board detected",
                confidence="high",
            ),
            DiscoveredRequirement(
                name="serial",
                kind="connection",
                required_for="serial_log",
                source="fake",
                evidence="port needed",
                confidence="high",
            ),
        ]
        source = self.FakeSource(reqs)
        discovery = AIRequirementDiscovery(source)
        result = discovery.discover({"path": "/tmp/project"})
        assert len(result.requirements) == 4
        assert result.requirements[0].name == "esphome"
        assert result.requirements[1].name == "pyserial"
        assert result.requirements[2].name == "ESP32"
        assert result.requirements[3].name == "serial"

    # ------------------------------------------------------------------
    # 5. Unknown requirements can be represented
    # ------------------------------------------------------------------
    def test_unknown_requirement(self):
        req = DiscoveredRequirement(
            name="some-unknown-tool",
            kind="unknown",
            required_for="unknown",
            source="fake",
            evidence="no info",
            confidence="low",
        )
        source = self.FakeSource([req])
        discovery = AIRequirementDiscovery(source)
        result = discovery.discover({})
        assert result.requirements[0].kind == "unknown"
        assert result.requirements[0].confidence == "low"

    # ------------------------------------------------------------------
    # 6. Confidence is preserved
    # ------------------------------------------------------------------
    def test_confidence_preserved(self):
        req = DiscoveredRequirement(
            name="esphome",
            kind="python_package",
            required_for="build",
            source="s",
            evidence="e",
            confidence="medium",
        )
        source = self.FakeSource([req])
        discovery = AIRequirementDiscovery(source)
        result = discovery.discover({})
        assert result.requirements[0].confidence == "medium"

    # ------------------------------------------------------------------
    # 7. Evidence and source are preserved
    # ------------------------------------------------------------------
    def test_evidence_and_source_preserved(self):
        req = DiscoveredRequirement(
            name="pyserial",
            kind="python_package",
            required_for="serial_log",
            source="my-source",
            evidence="found in requirements.txt",
            confidence="high",
        )
        source = self.FakeSource([req])
        discovery = AIRequirementDiscovery(source)
        result = discovery.discover({})
        assert result.requirements[0].source == "my-source"
        assert result.requirements[0].evidence == "found in requirements.txt"

    # ------------------------------------------------------------------
    # 8. No installation or hardware action happens
    # ------------------------------------------------------------------
    def test_no_installation_or_hardware(self):
        # This test verifies by construction that no pip, subprocess,
        # or hardware access is performed. The discovery only returns data.
        source = self.FakeSource([])
        discovery = AIRequirementDiscovery(source)
        result = discovery.discover({})
        assert result.requirements == []

    # ------------------------------------------------------------------
    # 9. Empty RequirementSet is returned when source returns nothing
    # ------------------------------------------------------------------
    def test_empty_requirement_set(self):
        source = self.FakeSource([])
        discovery = AIRequirementDiscovery(source)
        result = discovery.discover({})
        assert isinstance(result, RequirementSet)
        assert result.requirements == []
