from pathlib import Path

import pytest

from app.signal_project_binding import (
    ACTIVE,
    REVOKED,
    SUPERSEDED,
    SignalProjectBindingError,
    SignalProjectBindingService,
    SignalProjectReferenceError,
)
from app.workflow_manager import WorkflowManager


def _service(tmp_path):
    manager = WorkflowManager(tmp_path / "workflow.json")
    return SignalProjectBindingService(manager), manager


def test_create_persist_and_reload_binding(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    service, manager = _service(tmp_path)

    created = service.create("chat-1", "project-1", project)
    reloaded = SignalProjectBindingService(
        WorkflowManager(manager.storage)
    ).resolve("chat-1")

    assert created.status == ACTIVE
    assert reloaded == created
    assert reloaded.project_root == str(project.resolve())
    assert reloaded.created_at
    assert reloaded.updated_at


def test_conversation_has_only_one_active_binding(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    service, _ = _service(tmp_path)
    service.create("chat-1", "project-1", first)

    with pytest.raises(SignalProjectBindingError, match="already has"):
        service.create("chat-1", "project-2", second)


def test_second_conversation_cannot_bind_to_already_bound_project(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    service, _ = _service(tmp_path)

    service.create("chat-1", "project-1", project)

    with pytest.raises(SignalProjectBindingError, match="project already has"):
        service.create("chat-2", "project-1", project)


def test_same_active_pair_is_idempotent_without_duplicate_record(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    service, _ = _service(tmp_path)

    first = service.create("chat-1", "project-1", project)
    repeated = service.create("chat-1", "project-1", project)

    assert repeated == first
    assert service.history("chat-1") == (first,)


def test_explicit_rebind_changes_project_and_retains_history(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    service, _ = _service(tmp_path)
    original = service.create("chat-1", "project-1", first)

    rebound = service.rebind("chat-1", "project-2", second)
    history = service.history("chat-1")

    assert service.resolve("chat-1") == rebound
    assert rebound.supersedes == original.id
    assert [item.status for item in history] == [SUPERSEDED, ACTIVE]

    replacement = service.create("chat-2", "project-1", first)
    assert replacement.status == ACTIVE


def test_rebind_to_project_bound_to_other_conversation_is_rejected(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    service, _ = _service(tmp_path)
    original = service.create("chat-1", "project-1", first)
    service.create("chat-2", "project-2", second)

    with pytest.raises(SignalProjectBindingError, match="project already has"):
        service.rebind("chat-1", "project-2", second)

    assert service.resolve("chat-1") == original
    assert service.resolve("chat-2").project_id == "project-2"


def test_rebind_to_same_active_pair_is_idempotent(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    service, _ = _service(tmp_path)
    original = service.create("chat-1", "project-1", project)

    repeated = service.rebind("chat-1", "project-1", project)

    assert repeated == original
    assert service.history("chat-1") == (original,)


def test_revoked_binding_is_inactive_and_history_is_retained(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    service, _ = _service(tmp_path)
    service.create("chat-1", "project-1", project)

    revoked = service.revoke("chat-1")

    assert revoked.status == REVOKED
    assert service.history("chat-1") == (revoked,)
    with pytest.raises(SignalProjectReferenceError, match="inactive"):
        service.resolve("chat-1")


def test_missing_project_reference_never_falls_back(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    service, _ = _service(tmp_path)
    service.create("chat-1", "project-1", project)
    project.rmdir()

    with pytest.raises(SignalProjectReferenceError, match="cannot be resolved"):
        service.resolve("chat-1")


def test_binding_state_is_not_project_definition_state(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    service, manager = _service(tmp_path)

    service.create("chat-1", "project-1", project)
    state = manager.load()

    assert state["signal_project_bindings"]
    assert "project_definitions" not in state
