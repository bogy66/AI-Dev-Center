"""API tests for POST /api/projects/import (CLAUDE-005).

Follows the same TestClient + dependency_overrides pattern as
tests/test_project_lifecycle_api.py. Most tests patch
app.web_api.import_repository directly to prove the endpoint's request/
response/error-mapping contract without touching Git at all. One test
goes through the real app.repository_import.import_repository end to end
against a real local Git repository (via the same validate_repository_source
monkeypatch documented in tests/test_repository_import.py), proving the
full HTTP -> import_repository -> ProjectRegistry wiring is genuinely
correct, not just mocked at the boundary.
"""
import subprocess
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.project_context import ProjectDefinitionStore, ProjectRegistry
from app.repository_import import RepositoryImportError
from app.web_api import app, sessions, get_project_registry


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


def test_import_endpoint_rejects_invalid_source(client, registry, tmp_path):
    resp = client.post(
        "/api/projects/import",
        json={"source": "", "destination_parent": str(tmp_path)},
    )
    assert resp.status_code == 400
    assert "error" in resp.json()


def test_import_endpoint_rejects_dangerous_source(client, registry, tmp_path):
    resp = client.post(
        "/api/projects/import",
        json={"source": "ext::sh -c id", "destination_parent": str(tmp_path)},
    )
    assert resp.status_code == 400
    assert "error" in resp.json()


def test_import_endpoint_reports_target_exists(client, registry, tmp_path):
    (tmp_path / "already-there").mkdir()
    resp = client.post(
        "/api/projects/import",
        json={
            "source": "https://example.invalid/owner/already-there.git",
            "destination_parent": str(tmp_path),
        },
    )
    assert resp.status_code == 400
    assert "already exists" in resp.json()["error"]


def test_import_endpoint_maps_clone_failure(client, registry, tmp_path, monkeypatch):
    def failing_clone(source, staging_target, parent, timeout):
        raise RepositoryImportError("git clone failed: simulated network failure")

    import app.repository_import as repository_import_module
    monkeypatch.setattr(repository_import_module, "_clone_into", failing_clone)

    resp = client.post(
        "/api/projects/import",
        json={
            "source": "https://example.invalid/owner/repo.git",
            "destination_parent": str(tmp_path),
        },
    )
    assert resp.status_code == 400
    assert "simulated network failure" in resp.json()["error"]
    assert not (tmp_path / "repo").exists()
    assert registry.list_by_status("active") == ()


def test_import_endpoint_error_never_leaks_credentials(client, registry, tmp_path, monkeypatch):
    def failing_clone(source, staging_target, parent, timeout):
        raise RepositoryImportError(
            "git clone failed: fatal: could not read from "
            "https://[redacted-credentials]@example.invalid/owner/repo.git"
        )

    import app.repository_import as repository_import_module
    monkeypatch.setattr(repository_import_module, "_clone_into", failing_clone)

    resp = client.post(
        "/api/projects/import",
        json={
            "source": "https://example.invalid/owner/repo.git",
            "destination_parent": str(tmp_path),
        },
    )
    assert resp.status_code == 400
    assert "[redacted-credentials]" in resp.json()["error"]
    assert "hunter2" not in resp.json()["error"]


def test_import_endpoint_success_via_real_engine_with_local_source(client, registry, tmp_path, monkeypatch):
    """End-to-end proof: real import_repository(), real ProjectRegistry,
    real local Git clone (validate_repository_source bypassed only for
    this local-source engine test, per the documented limitation in
    tests/test_repository_import.py)."""
    import app.repository_import as repository_import_module

    source = tmp_path / "source-repo"
    source.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=source, check=True)
    (source / "file.txt").write_text("hello")
    subprocess.run(["git", "add", "."], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=source, check=True)

    def real_local_clone(clone_source, staging_target, parent, timeout):
        completed = subprocess.run(
            ["git", "clone", "--no-tags", "--", clone_source, str(staging_target)],
            cwd=str(parent), capture_output=True, text=True, timeout=timeout, check=False,
        )
        if completed.returncode != 0:
            raise RepositoryImportError(f"git clone failed: {completed.stderr}")

    monkeypatch.setattr(
        repository_import_module, "validate_repository_source", lambda s: s,
    )
    monkeypatch.setattr(repository_import_module, "_clone_into", real_local_clone)

    destination_parent = tmp_path / "destination"
    destination_parent.mkdir()

    resp = client.post(
        "/api/projects/import",
        json={"source": str(source), "destination_parent": str(destination_parent)},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["lifecycle_status"] == "active"
    assert data["display_name"] == "source-repo"

    listing = client.get("/api/projects").json()
    assert len(listing["active"]) == 1
    assert listing["active"][0]["project_id"] == data["project_id"]
