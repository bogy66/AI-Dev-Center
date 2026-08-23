import dataclasses
import pytest
from datetime import datetime
from types import MappingProxyType

from app.requirement_model import (
    RequirementEvidence,
    Requirement,
    RequirementSet,
    DiscoveryResult,
    ValidationResult,
    PreflightRequirementResult,
    PreflightResult,
    SetupStep,
    SetupPlan,
    Status,
    RequirementType,
)


def test_requirement_evidence_creation():
    ev = RequirementEvidence(
        id="ev-1",
        source_type="file_content",
        description="Found requirement",
        source_file="tool.yaml",
        snippet="tool:",
        confidence_contribution=0.5,
    )
    assert ev.id == "ev-1"
    assert ev.source_type == "file_content"
    assert ev.description == "Found requirement"
    assert ev.source_file == "tool.yaml"
    assert ev.snippet == "tool:"
    assert ev.confidence_contribution == 0.5
    assert ev.url is None


def test_requirement_creation_and_evidence_to_tuple():
    ev1 = RequirementEvidence(id="ev-1", source_type="file", description="evidence")
    ev2 = RequirementEvidence(id="ev-2", source_type="config", description="other")
    req = Requirement(
        id="req-1",
        name="some_executable",
        type=RequirementType.EXECUTABLE,
        purpose="build",
        required=True,
        confidence=0.9,
        evidence=[ev1, ev2],
        status=Status.DISCOVERED,
    )
    assert isinstance(req.evidence, tuple)
    assert req.evidence == (ev1, ev2)
    assert req.metadata == MappingProxyType({})
    assert req.name == "some_executable"
    assert req.type == RequirementType.EXECUTABLE
    assert req.required is True
    assert req.confidence == 0.9
    assert req.source_file is None
    assert req.detected_version is None
    assert req.required_version is None
    assert req.install_method is None
    assert req.verification_method is None


def test_requirement_metadata_immutable():
    req = Requirement(
        id="r1",
        name="x",
        type=RequirementType.UNKNOWN,
        purpose="test",
        required=False,
        confidence=0.1,
        metadata={"project_id": "proj"},
    )
    assert isinstance(req.metadata, MappingProxyType)
    with pytest.raises(TypeError):
        req.metadata["new_key"] = "value"


def test_requirement_is_frozen():
    req = Requirement(
        id="1",
        name="x",
        type=RequirementType.UNKNOWN,
        purpose="p",
        required=True,
        confidence=0.5,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        req.name = "y"


def test_requirement_supports_discovery_fields():
    ev = RequirementEvidence(
        id="ev-1",
        source_type="file_content",
        description="found",
        source_file="config.yaml",
        snippet="config:",
    )
    req = Requirement(
        id="req-1",
        name="some_tool",
        type=RequirementType.PYTHON_PACKAGE,
        purpose="build+flash",
        required=True,
        confidence=0.8,
        evidence=[ev],
        source_file="config.yaml",
        detected_version="1.2.3",
        required_version=">=1.0",
        install_method="pip",
        verification_method="some_tool --version",
        status=Status.DISCOVERED,
        metadata={"board": "generic"},
    )
    assert req.source_file == "config.yaml"
    assert req.detected_version == "1.2.3"
    assert req.required_version == ">=1.0"
    assert req.install_method == "pip"
    assert req.verification_method == "some_tool --version"
    assert req.status == Status.DISCOVERED


def test_requirement_set_creation_and_immutability():
    req1 = Requirement(
        id="1",
        name="a",
        type=RequirementType.UNKNOWN,
        purpose="p",
        required=True,
        confidence=0.8,
    )
    req2 = Requirement(
        id="2",
        name="b",
        type=RequirementType.UNKNOWN,
        purpose="p",
        required=False,
        confidence=0.3,
    )
    rs = RequirementSet(
        id="set-1",
        project_id="proj-1",
        requirements=[req1, req2],
        source="ai",
        overall_status=Status.DISCOVERED,
    )
    assert isinstance(rs.requirements, tuple)
    assert rs.requirements == (req1, req2)
    assert rs.source == "ai"
    assert rs.overall_status == Status.DISCOVERED
    assert isinstance(rs.created_at, datetime)

    with pytest.raises(dataclasses.FrozenInstanceError):
        rs.project_id = "other"


def test_discovery_result():
    req = Requirement(
        id="r1",
        name="x",
        type=RequirementType.TOOLCHAIN,
        purpose="test",
        required=True,
        confidence=0.7,
        status=Status.SUSPECTED,
    )
    dr = DiscoveryResult(
        id="disc-1",
        source="ai",
        project_id="proj",
        requirements=[req],
        warnings=["low confidence"],
    )
    assert isinstance(dr.requirements, tuple)
    assert dr.requirements == (req,)
    assert dr.warnings == ("low confidence",)
    assert dr.fallback_used is False
    assert isinstance(dr.generated_at, datetime)


def test_validation_result_fields():
    req1 = Requirement(
        id="1",
        name="x",
        type=RequirementType.UNKNOWN,
        purpose="p",
        required=True,
        confidence=0.9,
        status=Status.REQUIRED,
    )
    req2 = Requirement(
        id="2",
        name="y",
        type=RequirementType.UNKNOWN,
        purpose="p",
        required=False,
        confidence=0.2,
        status=Status.REJECTED,
    )
    vr = ValidationResult(
        id="val-1",
        valid=True,
        requirements=[req1, req2],
        errors=[],
        warnings=[],
        normalized_requirements=[req1],
        required_requirements=[req1],
        optional_requirements=[],
        rejected_requirements=[req2],
    )
    assert vr.valid is True
    assert vr.required_requirements == (req1,)
    assert vr.rejected_requirements == (req2,)
    assert vr.errors == ()
    assert vr.warnings == ()


def test_preflight_requirement_result():
    result = PreflightRequirementResult(
        requirement_id="r1",
        present=False,
        detected_version=None,
        satisfied=False,
        warning="not found",
    )
    assert result.requirement_id == "r1"
    assert result.present is False
    assert result.detected_version is None
    assert result.satisfied is False
    assert result.warning == "not found"


def test_preflight_result_generic():
    r1 = Requirement(
        id="1",
        name="x",
        type=RequirementType.UNKNOWN,
        purpose="p",
        required=True,
        confidence=0.5,
        status=Status.MISSING,
    )
    r2 = Requirement(
        id="2",
        name="y",
        type=RequirementType.UNKNOWN,
        purpose="p",
        required=True,
        confidence=0.5,
        status=Status.INSTALLED,
    )
    results = [
        PreflightRequirementResult(
            requirement_id="1",
            present=False,
            detected_version=None,
            satisfied=False,
            warning="not found",
        ),
        PreflightRequirementResult(
            requirement_id="2",
            present=True,
            detected_version="1.0",
            satisfied=True,
        ),
    ]
    pr = PreflightResult(
        id="pre-1",
        project_id="proj",
        overall_ready=False,
        results=results,
        missing_requirements=[r1],
        already_installed=[r2],
        warnings=("only warning",),
    )
    assert pr.overall_ready is False
    assert isinstance(pr.results, tuple)
    assert len(pr.results) == 2
    assert pr.results[0].present is False
    assert pr.results[1].detected_version == "1.0"
    assert pr.missing_requirements == (r1,)
    assert pr.already_installed == (r2,)
    assert pr.warnings == ("only warning",)


def test_preflight_result_has_no_stack_specific_fields():
    pr = PreflightResult(
        id="pre-1",
        project_id="proj",
        overall_ready=True,
        results=[],
    )
    assert not hasattr(pr, "serial_ports")
    assert not hasattr(pr, "esphome_available")
    assert not hasattr(pr, "python_available")


def test_setup_step_and_plan():
    step = SetupStep(
        id="step-1",
        requirement_id="1",
        action="install",
        install_method="pip",
        package="somepkg",
        version=">=1.0",
        command="pip install somepkg>=1.0",
        verification_after="somepkg --version",
        is_approved=False,
    )
    assert step.action == "install"
    assert step.is_approved is False

    plan = SetupPlan(
        id="plan-1",
        project_id="proj",
        steps=[step],
        requires_user_approval=True,
        rollback_steps=[],
        warnings=[],
        status="pending_approval",
    )
    assert isinstance(plan.steps, tuple)
    assert plan.steps == (step,)
    assert plan.requires_user_approval is True
    assert plan.rollback_steps == ()
    assert plan.warnings == ()
    assert plan.status == "pending_approval"
    assert isinstance(plan.created_at, datetime)


def test_setup_plan_is_frozen():
    plan = SetupPlan(id="plan-1", project_id="proj")
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.project_id = "other"


def test_status_constants_cover_required_statuses():
    for status_name in [
        "DISCOVERED",
        "SUSPECTED",
        "REQUIRED",
        "INSTALLED",
        "VERIFIED",
        "REJECTED",
    ]:
        assert hasattr(Status, status_name)
        assert isinstance(getattr(Status, status_name), str)


def test_requirement_type_constants_are_strings():
    for type_name in [
        "EXECUTABLE",
        "PYTHON_PACKAGE",
        "SYSTEM_PACKAGE",
        "SDK",
        "TOOLCHAIN",
        "FLASHER",
        "HARDWARE_COMPONENT",
        "CONNECTION",
        "BUILD_COMMAND",
        "TEST_COMMAND",
        "CONFIG_FILE",
        "VERSION_CONSTRAINT",
        "CAPABILITY",
        "UNKNOWN",
    ]:
        assert hasattr(RequirementType, type_name)
        assert isinstance(getattr(RequirementType, type_name), str)
