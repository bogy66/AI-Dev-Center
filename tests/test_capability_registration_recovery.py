from unittest.mock import Mock
from types import SimpleNamespace

import pytest

from app.execution import (
    ApprovalProvenance,
    CapabilityRegistration,
    CapabilityRegistry,
    DEFAULT_CAPABILITY_REGISTRY,
    ExecutionRequest,
    validate_request,
)
from app.project_setup_application import ProjectSetupApplicationService
from app.capability_registration import CapabilityRegistrationError
from app.verification import UNSUPPORTED
from app.workflow_manager import WorkflowManager


def _registration(project, capability="cargo"):
    return CapabilityRegistration(
        capability=capability,
        executable_names=(capability,),
        allowed_operations=("build",),
        approval_provenance=ApprovalProvenance(
            str(project), "council", "chairman", "human",
        ),
        project_scope=str(project),
    )


def _approval(manager, request_id, project, status="approved"):
    manager.create_capability_approval(
        request_id, project.name, str(project), "council", "chairman",
        "cargo", ("cargo",), ("build",), str(project),
    )
    if status in {"approved", "rejected"}:
        manager.decide_capability_approval(request_id, status, "Human")


def _service(manager, registry):
    return ProjectSetupApplicationService(
        Mock(), workflow_manager=manager, capability_registry=registry,
        diagnostic_trace=Mock(),
    )


def test_dynamic_registration_cannot_be_unscoped():
    registration = CapabilityRegistration(
        capability="cargo", executable_names=("cargo",),
        allowed_operations=("build",),
        approval_provenance=ApprovalProvenance("pi", "council", "chairman", "human"),
    )
    with pytest.raises(ValueError, match="project scope"):
        CapabilityRegistry().register_approved(registration)


def test_same_capability_can_be_registered_for_two_projects(tmp_path):
    project_a = tmp_path / "a"
    project_b = tmp_path / "b"
    registry = CapabilityRegistry()
    registry.register_approved(_registration(project_a))
    registry.register_approved(_registration(project_b))
    assert registry.get("cargo", project_a).project_scope == str(project_a.resolve())
    assert registry.get("cargo", project_b).project_scope == str(project_b.resolve())


def test_requested_scope_must_match_project_intelligence_root(tmp_path):
    request = SimpleNamespace(
        project_intelligence=SimpleNamespace(project_root=str(tmp_path / "a")),
        project_scope=str(tmp_path / "b"),
    )
    with pytest.raises(CapabilityRegistrationError, match="Project Intelligence root"):
        ProjectSetupApplicationService._normalized_capability_scope(request)


def test_project_a_registration_cannot_execute_for_project_b(tmp_path, monkeypatch):
    project_a = tmp_path / "a"
    project_b = tmp_path / "b"
    project_a.mkdir()
    project_b.mkdir()
    registry = CapabilityRegistry((_registration(project_a),))
    monkeypatch.setattr("app.execution._find_executable", lambda name: "/bin/true")
    request = ExecutionRequest(("cargo", "build"), str(project_b), 10, "cargo", "build")
    assert validate_request(request, project_b, registry).status == UNSUPPORTED.value


def test_approved_registration_is_recovered_and_recovery_is_idempotent(tmp_path):
    project = tmp_path / "project"
    manager = WorkflowManager(tmp_path / "state.json")
    _approval(manager, "approval-1", project)
    first_registry = CapabilityRegistry()
    _service(manager, first_registry)
    assert first_registry.get("cargo", project) is not None

    restarted_registry = CapabilityRegistry()
    restarted_service = _service(manager, restarted_registry)
    recovered = restarted_registry.get("cargo", project)
    assert recovered is not None
    repeated = restarted_service.recover_approved_capabilities()
    assert repeated == (recovered,)
    assert restarted_registry.get("cargo", project) == recovered


@pytest.mark.parametrize("status", ["pending", "rejected"])
def test_nonapproved_registration_is_not_recovered(tmp_path, status):
    project = tmp_path / status
    manager = WorkflowManager(tmp_path / f"{status}.json")
    _approval(manager, f"approval-{status}", project, status)
    registry = CapabilityRegistry()
    _service(manager, registry)
    assert registry.get("cargo", project) is None


def test_bootstrap_registration_remains_global_compatibility(tmp_path):
    assert DEFAULT_CAPABILITY_REGISTRY.get("python", tmp_path).bootstrap_compatibility
