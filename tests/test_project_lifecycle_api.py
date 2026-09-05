"""API tests for the CLAUDE-003 project lifecycle endpoints in app.web_api.

Uses the same TestClient + dependency_overrides pattern as the rest of the
productive web test suite (see tests/test_web_gui.py), with a real,
tmp_path-backed ProjectRegistry so these tests exercise the actual
persistence contract, not a mock.
"""
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.project_context import ProjectDefinitionStore, ProjectRegistry
from app.web_api import (
    app, sessions, get_project_registry, get_web_setup_components,
)


@pytest.fixture(autouse=True)
def clear_sessions():
    sessions.clear()
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def registry(tmp_path):
    reg = ProjectRegistry(ProjectDefinitionStore(tmp_path / "definitions.json"))
    app.dependency_overrides[get_project_registry] = lambda: reg
    return reg


def _set_workflow_override():
    components = MagicMock()
    plan = MagicMock(id="plan-123", status="pending_approval")
    result = MagicMock(setup_plan=plan)
    components.service.plan_project_setup.return_value = result
    components.plan_store = MagicMock()
    components.approval = MagicMock()
    components.development_workflow = MagicMock()
    app.dependency_overrides[get_web_setup_components] = lambda: components
    return components


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------
def test_active_listing_is_empty_initially(client, registry):
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    assert resp.json() == {"active": [], "archived": []}


def test_active_listing_shows_registered_project(client, registry, tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    registry.register(str(project), display_name="My Project")

    resp = client.get("/api/projects")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["active"]) == 1
    assert data["active"][0]["display_name"] == "My Project"
    assert data["archived"] == []


def test_archive_listing_shows_archived_project(client, registry, tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    record = registry.register(str(project), display_name="My Project")
    registry.archive(record.project_id)

    resp = client.get("/api/projects")

    data = resp.json()
    assert data["active"] == []
    assert len(data["archived"]) == 1
    assert data["archived"][0]["project_id"] == record.project_id


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------
def test_register_endpoint_creates_an_active_project(client, registry, tmp_path):
    project = tmp_path / "proj"
    project.mkdir()

    resp = client.post(
        "/api/projects/register",
        json={"project_path": str(project), "display_name": "New One"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["display_name"] == "New One"
    assert data["lifecycle_status"] == "active"


def test_register_endpoint_rejects_nonexistent_path(client, registry, tmp_path):
    resp = client.post(
        "/api/projects/register",
        json={"project_path": str(tmp_path / "does-not-exist")},
    )
    assert resp.status_code == 400
    assert "error" in resp.json()


# ---------------------------------------------------------------------------
# Rename
# ---------------------------------------------------------------------------
def test_rename_endpoint_changes_display_name(client, registry, tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    record = registry.register(str(project), display_name="Old")

    resp = client.post(
        f"/api/projects/{record.project_id}/rename",
        json={"new_name": "New"},
    )

    assert resp.status_code == 200
    assert resp.json()["display_name"] == "New"


def test_rename_endpoint_rejects_empty_name(client, registry, tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    record = registry.register(str(project))

    resp = client.post(
        f"/api/projects/{record.project_id}/rename",
        json={"new_name": "   "},
    )

    assert resp.status_code == 400
    assert "error" in resp.json()


def test_rename_endpoint_rejects_duplicate_name(client, registry, tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    registry.register(str(a), display_name="Alpha")
    beta = registry.register(str(b), display_name="Beta")

    resp = client.post(
        f"/api/projects/{beta.project_id}/rename",
        json={"new_name": "Alpha"},
    )

    assert resp.status_code == 400
    assert "error" in resp.json()


def test_rename_endpoint_unknown_project_returns_useful_error(client, registry):
    resp = client.post(
        "/api/projects/project-unknown/rename",
        json={"new_name": "X"},
    )
    assert resp.status_code == 400
    assert "Unknown project" in resp.json()["error"]


# ---------------------------------------------------------------------------
# Archive / Restore
# ---------------------------------------------------------------------------
def test_archive_endpoint_moves_project_to_archived(client, registry, tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    record = registry.register(str(project))

    resp = client.post(f"/api/projects/{record.project_id}/archive")

    assert resp.status_code == 200
    assert resp.json()["lifecycle_status"] == "archived"


def test_archive_endpoint_rejects_already_archived_project(client, registry, tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    record = registry.register(str(project))
    registry.archive(record.project_id)

    resp = client.post(f"/api/projects/{record.project_id}/archive")

    assert resp.status_code == 400
    assert "error" in resp.json()


def test_restore_endpoint_moves_project_back_to_active(client, registry, tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    record = registry.register(str(project))
    registry.archive(record.project_id)

    resp = client.post(f"/api/projects/{record.project_id}/restore")

    assert resp.status_code == 200
    assert resp.json()["lifecycle_status"] == "active"


def test_restore_endpoint_rejects_active_project(client, registry, tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    record = registry.register(str(project))

    resp = client.post(f"/api/projects/{record.project_id}/restore")

    assert resp.status_code == 400
    assert "error" in resp.json()


# ---------------------------------------------------------------------------
# Delete (remove from ADC management)
# ---------------------------------------------------------------------------
def test_remove_endpoint_rejects_active_project(client, registry, tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    record = registry.register(str(project))

    resp = client.post(f"/api/projects/{record.project_id}/remove")

    assert resp.status_code == 400
    assert "error" in resp.json()


def test_remove_endpoint_removes_archived_project_and_directory_survives(client, registry, tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "keep.txt").write_text("still here")
    record = registry.register(str(project))
    registry.archive(record.project_id)

    resp = client.post(f"/api/projects/{record.project_id}/remove")

    assert resp.status_code == 200
    assert resp.json()["lifecycle_status"] == "removed"
    # confirm it disappears from both listings
    listing = client.get("/api/projects").json()
    all_ids = {p["project_id"] for p in listing["active"] + listing["archived"]}
    assert record.project_id not in all_ids
    # the underlying directory and its contents are untouched
    assert project.exists()
    assert (project / "keep.txt").read_text() == "still here"


def test_remove_endpoint_unknown_project_returns_useful_error(client, registry):
    resp = client.post("/api/projects/project-unknown/remove")
    assert resp.status_code == 400
    assert "error" in resp.json()


# ---------------------------------------------------------------------------
# Archived-project development gate on /api/workflow/start
# ---------------------------------------------------------------------------
def test_workflow_start_is_blocked_for_an_archived_project(client, registry, tmp_path):
    _set_workflow_override()
    project = tmp_path / "proj"
    project.mkdir()
    record = registry.register(str(project), display_name="proj")
    registry.archive(record.project_id)

    resp = client.post(
        "/api/workflow/start",
        json={
            "project_name": "proj",
            "project_directory": str(project),
            "task_description": "do something",
        },
    )

    assert resp.status_code == 409
    data = resp.json()
    assert "archived" in data["error"].lower()
    assert data["session_id"] in sessions
    assert sessions[data["session_id"]].blocked is True


def test_workflow_start_succeeds_and_registers_an_unknown_project(client, registry, tmp_path):
    components = _set_workflow_override()
    project = tmp_path / "proj"
    project.mkdir()

    resp = client.post(
        "/api/workflow/start",
        json={
            "project_name": "proj",
            "project_directory": str(project),
            "task_description": "do something",
        },
    )

    assert resp.status_code == 202
    listing = client.get("/api/projects").json()
    assert len(listing["active"]) == 1
    assert listing["active"][0]["project_root"] == str(project.resolve())


def test_workflow_start_succeeds_for_an_active_registered_project(client, registry, tmp_path):
    _set_workflow_override()
    project = tmp_path / "proj"
    project.mkdir()
    registry.register(str(project), display_name="proj")

    resp = client.post(
        "/api/workflow/start",
        json={
            "project_name": "proj",
            "project_directory": str(project),
            "task_description": "do something",
        },
    )

    assert resp.status_code == 202
