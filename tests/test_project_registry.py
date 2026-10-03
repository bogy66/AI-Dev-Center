"""Model/persistence tests for the CLAUDE-003 project lifecycle registry.

ProjectRegistry is a central extension of the existing, productive
ProjectDefinitionStore — not a second persistence mechanism. These tests
verify the lifecycle contract (active -> archived -> restore/delete)
directly against that store, including persistence across a freshly
constructed store instance (simulating a backend restart, since nothing
here is cached in memory).
"""
from pathlib import Path

import pytest

from app.project_context import (
    ProjectDefinitionStore,
    ProjectRegistry,
    ProjectRegistryError,
    derive_project_id,
    ACTIVE_STATUS,
    ARCHIVED_STATUS,
    REMOVED_STATUS,
)


@pytest.fixture
def store_path(tmp_path):
    return tmp_path / "definitions.json"


@pytest.fixture
def registry(store_path):
    return ProjectRegistry(ProjectDefinitionStore(store_path))


def reopened_registry(store_path):
    """A fresh ProjectRegistry over the same file, simulating backend restart."""
    return ProjectRegistry(ProjectDefinitionStore(store_path))


def test_derive_project_id_is_stable_for_the_same_path(tmp_path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    assert derive_project_id(str(project_dir)) == derive_project_id(str(project_dir))


def test_derive_project_id_differs_for_different_paths(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert derive_project_id(str(a)) != derive_project_id(str(b))


def test_new_project_is_registered_active(registry, tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    record = registry.register(str(root), display_name="My Project")
    assert record.lifecycle_status == ACTIVE_STATUS
    assert record.display_name == "My Project"
    assert record.project_root == str(root.resolve())
    active_ids = {r.project_id for r in registry.list_by_status(ACTIVE_STATUS)}
    assert record.project_id in active_ids


def test_register_is_idempotent_and_does_not_duplicate(registry, tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    first = registry.register(str(root), display_name="My Project")
    second = registry.register(str(root), display_name="Ignored Second Name")
    assert first == second
    assert len(registry.list_by_status(ACTIVE_STATUS)) == 1


def test_archive_persists_and_removes_from_active_listing(registry, store_path, tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    record = registry.register(str(root))

    registry.archive(record.project_id)

    reopened = reopened_registry(store_path)
    active_ids = {r.project_id for r in reopened.list_by_status(ACTIVE_STATUS)}
    archived_ids = {r.project_id for r in reopened.list_by_status(ARCHIVED_STATUS)}
    assert record.project_id not in active_ids
    assert record.project_id in archived_ids


def test_restore_persists_and_moves_back_to_active(registry, store_path, tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    record = registry.register(str(root))
    registry.archive(record.project_id)

    registry.restore(record.project_id)

    reopened = reopened_registry(store_path)
    active_ids = {r.project_id for r in reopened.list_by_status(ACTIVE_STATUS)}
    archived_ids = {r.project_id for r in reopened.list_by_status(ARCHIVED_STATUS)}
    assert record.project_id in active_ids
    assert record.project_id not in archived_ids


def test_rename_persists_across_reload(registry, store_path, tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    record = registry.register(str(root), display_name="Old Name")

    registry.rename(record.project_id, "New Name")

    reopened = reopened_registry(store_path)
    reloaded = reopened.get(record.project_id)
    assert reloaded.display_name == "New Name"


def test_rename_does_not_alter_filesystem_path(registry, tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    record = registry.register(str(root), display_name="Old Name")

    renamed = registry.rename(record.project_id, "New Name")

    assert renamed.project_root == str(root.resolve())
    assert root.exists()


def test_rename_works_while_archived(registry, tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    record = registry.register(str(root), display_name="Old Name")
    registry.archive(record.project_id)

    renamed = registry.rename(record.project_id, "New Name While Archived")

    assert renamed.display_name == "New Name While Archived"
    assert renamed.lifecycle_status == ARCHIVED_STATUS


def test_archive_does_not_move_project_directory(registry, tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "marker.txt").write_text("hello")
    record = registry.register(str(root))

    registry.archive(record.project_id)

    assert root.exists()
    assert (root / "marker.txt").read_text() == "hello"
    assert Path(registry.get(record.project_id).project_root) == root.resolve()


def test_active_project_cannot_be_deleted(registry, tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    record = registry.register(str(root))

    with pytest.raises(ProjectRegistryError):
        registry.remove(record.project_id)

    # still active, not silently removed
    assert registry.get(record.project_id).lifecycle_status == ACTIVE_STATUS


def test_archived_project_can_be_removed_from_adc_management(registry, tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    record = registry.register(str(root))
    registry.archive(record.project_id)

    removed = registry.remove(record.project_id)

    assert removed.lifecycle_status == REMOVED_STATUS
    assert record.project_id not in {r.project_id for r in registry.list_by_status(ACTIVE_STATUS)}
    assert record.project_id not in {r.project_id for r in registry.list_by_status(ARCHIVED_STATUS)}


def test_underlying_directory_survives_delete_from_adc(registry, tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "keep.txt").write_text("still here")
    record = registry.register(str(root))
    registry.archive(record.project_id)

    registry.remove(record.project_id)

    assert root.exists()
    assert (root / "keep.txt").read_text() == "still here"


def test_invalid_transitions_fail_safely(registry, tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    record = registry.register(str(root))

    with pytest.raises(ProjectRegistryError):
        registry.restore(record.project_id)  # not archived

    registry.archive(record.project_id)
    with pytest.raises(ProjectRegistryError):
        registry.archive(record.project_id)  # already archived

    registry.remove(record.project_id)
    with pytest.raises(ProjectRegistryError):
        registry.restore(record.project_id)  # removed, not archived
    with pytest.raises(ProjectRegistryError):
        registry.remove(record.project_id)  # already removed
    with pytest.raises(ProjectRegistryError):
        registry.rename(record.project_id, "new name")  # removed


def test_unknown_project_id_fails_safely(registry):
    with pytest.raises(ProjectRegistryError):
        registry.get("project-does-not-exist")
    with pytest.raises(ProjectRegistryError):
        registry.archive("project-does-not-exist")
    with pytest.raises(ProjectRegistryError):
        registry.rename("project-does-not-exist", "x")


@pytest.mark.parametrize("bad_name", ["", "   ", "\t\n"])
def test_empty_or_whitespace_names_fail_safely(registry, tmp_path, bad_name):
    root = tmp_path / "proj"
    root.mkdir()
    record = registry.register(str(root))

    with pytest.raises(ProjectRegistryError):
        registry.rename(record.project_id, bad_name)


def test_duplicate_name_fails_safely(registry, tmp_path):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    registry.register(str(root_a), display_name="Alpha")
    beta = registry.register(str(root_b), display_name="Beta")

    with pytest.raises(ProjectRegistryError):
        registry.rename(beta.project_id, "Alpha")

    with pytest.raises(ProjectRegistryError):
        registry.rename(beta.project_id, "alpha")  # case-insensitive conflict


def test_renaming_to_its_own_current_name_is_allowed(registry, tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    record = registry.register(str(root), display_name="Same Name")

    result = registry.rename(record.project_id, "Same Name")

    assert result.display_name == "Same Name"


def test_lifecycle_survives_persistence_reload_end_to_end(registry, store_path, tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    record = registry.register(str(root), display_name="Round Trip")
    registry.archive(record.project_id)
    registry.rename(record.project_id, "Round Trip Renamed")
    registry.restore(record.project_id)

    reopened = reopened_registry(store_path)
    final = reopened.get(record.project_id)
    assert final.display_name == "Round Trip Renamed"
    assert final.lifecycle_status == ACTIVE_STATUS
    assert final.project_root == str(root.resolve())
