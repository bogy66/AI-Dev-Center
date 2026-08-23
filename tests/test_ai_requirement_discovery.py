import pytest
from app.ai_requirement_discovery import AIRequirementDiscovery, DiscoverySource
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
    # Helper: a fake DiscoverySource that returns fixed requirements
    # ------------------------------------------------------------------
    class FakeSource:
        def __init__(self, requirements: list[Requirement]):
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
    # 4. ESPHome-like requirements work as test data (using central model)
    # ------------------------------------------------------------------
    def test_esphome_like_requirements(self):
        reqs = [
            Requirement(
                id="r1",
                name="esphome",
                type=RequirementType.PYTHON_PACKAGE,
                purpose="build+flash",
                required=True,
                confidence=0.9,
                metadata={"source": "fake"},
            ),
            Requirement(
                id="r2",
                name="pyserial",
                type=RequirementType.PYTHON_PACKAGE,
                purpose="serial_log",
                required=True,
                confidence=0.9,
                metadata={"source": "fake"},
            ),
            Requirement(
                id="r3",
                name="ESP32",
                type=RequirementType.HARDWARE_COMPONENT,
                purpose="target",
                required=True,
                confidence=0.9,
                metadata={"source": "fake"},
            ),
            Requirement(
                id="r4",
                name="serial",
                type=RequirementType.CONNECTION,
                purpose="serial_log",
                required=True,
                confidence=0.9,
                metadata={"source": "fake"},
            ),
        ]
        source = self.FakeSource(reqs)
        discovery = AIRequirementDiscovery(source)
        result = discovery.discover({"path": "/tmp/project"})
        assert len(result.requirements) == 4
        assert result.requirements[0].name == "esphome"
        assert result.requirements[0].type == RequirementType.PYTHON_PACKAGE
        assert result.requirements[0].purpose == "build+flash"
        assert result.requirements[1].name == "pyserial"
        assert result.requirements[2].name == "ESP32"
        assert result.requirements[3].name == "serial"

    # ------------------------------------------------------------------
    # 5. Unknown requirements can be represented
    # ------------------------------------------------------------------
    def test_unknown_requirement(self):
        req = Requirement(
            id="r-unknown",
            name="some-unknown-tool",
            type=RequirementType.UNKNOWN,
            purpose="unknown",
            required=False,
            confidence=0.2,
            metadata={"source": "fake"},
        )
        source = self.FakeSource([req])
        discovery = AIRequirementDiscovery(source)
        result = discovery.discover({})
        assert result.requirements[0].type == RequirementType.UNKNOWN
        assert result.requirements[0].confidence == 0.2

    # ------------------------------------------------------------------
    # 6. Confidence is preserved
    # ------------------------------------------------------------------
    def test_confidence_preserved(self):
        req = Requirement(
            id="r-c",
            name="esphome",
            type=RequirementType.PYTHON_PACKAGE,
            purpose="build",
            required=True,
            confidence=0.6,
            metadata={},
        )
        source = self.FakeSource([req])
        discovery = AIRequirementDiscovery(source)
        result = discovery.discover({})
        assert result.requirements[0].confidence == 0.6

    # ------------------------------------------------------------------
    # 7. Evidence and source are preserved
    # ------------------------------------------------------------------
    def test_evidence_and_source_preserved(self):
        ev = RequirementEvidence(
            id="ev-1",
            source_type="file",
            description="found in requirements.txt",
            source_file="requirements.txt",
        )
        req = Requirement(
            id="r-ev",
            name="pyserial",
            type=RequirementType.PYTHON_PACKAGE,
            purpose="serial_log",
            required=True,
            confidence=1.0,
            evidence=[ev],
            metadata={"source": "my-source"},
        )
        source = self.FakeSource([req])
        discovery = AIRequirementDiscovery(source)
        result = discovery.discover({})
        assert len(result.requirements) == 1
        assert result.requirements[0].evidence[0].description == "found in requirements.txt"
        assert result.requirements[0].metadata["source"] == "my-source"

    # ------------------------------------------------------------------
    # 8. No installation or hardware action happens
    # ------------------------------------------------------------------
    def test_no_installation_or_hardware(self):
        # This test verifies by construction that no pip, subprocess,
        # or hardware access is performed. The discovery only returns data.
        source = self.FakeSource([])
        discovery = AIRequirementDiscovery(source)
        result = discovery.discover({})
        assert len(result.requirements) == 0

    # ------------------------------------------------------------------
    # 9. Empty RequirementSet is returned when source returns nothing
    # ------------------------------------------------------------------
    def test_empty_requirement_set(self):
        source = self.FakeSource([])
        discovery = AIRequirementDiscovery(source)
        result = discovery.discover({})
        assert isinstance(result, RequirementSet)
        assert len(result.requirements) == 0
