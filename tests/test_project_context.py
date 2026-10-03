from types import SimpleNamespace

import pytest

from app.project_context import (
    ACTIVE, REVOKED, SUPERSEDED,
    ProjectDefinitionError, ProjectDefinitionStore, compose_project_context,
)
from app.project_intelligence import ProjectIntelligence


def _intelligence(root, languages=()):
    language_items = tuple(SimpleNamespace(name=name) for name in languages)
    return ProjectIntelligence(
        project_root=str(root), project_kind="existing", areas=(),
        languages=language_items, frameworks=(), package_systems=(),
        build_systems=(), test_systems=(), firmware_indicators=(),
        ci_indicators=(), doc_indicators=(), git_repository_present=False,
        sensitive_configuration_present=False, warnings=(), truncated=False,
        total_files_traversed=0, total_files_excluded=0,
        inspection_limit_exceeded=False,
    )


def _config(**overrides):
    values = {
        "provider": "openrouter", "model": "model-a",
        "endpoint": "https://example.invalid", "timeout_seconds": 30.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_create_active_definition_and_reload(tmp_path):
    path = tmp_path / "definitions.json"
    created = ProjectDefinitionStore(path).create(
        "project", "terminology.service", {"preferred": "worker"},
        "terminology", "project", "human",
    )
    assert created.status == ACTIVE
    assert ProjectDefinitionStore(path).get(created.id) == created


def test_supersession_retains_history(tmp_path):
    store = ProjectDefinitionStore(tmp_path / "definitions.json")
    old = store.create("project", "runtime", "python", "decision", "project", "human")
    new = store.supersede(old.id, "rust", "human")
    history = store.list("project")
    assert store.get(old.id).status == SUPERSEDED
    assert new.supersedes == old.id
    assert len(history) == 2
    assert store.active("project") == (new,)


def test_revocation_remains_in_history(tmp_path):
    store = ProjectDefinitionStore(tmp_path / "definitions.json")
    item = store.create("project", "rule", True, "policy", "project", "human")
    assert store.revoke(item.id).status == REVOKED
    assert store.active("project") == ()
    assert store.get(item.id).status == REVOKED


def test_cross_project_supersession_is_rejected(tmp_path):
    store = ProjectDefinitionStore(tmp_path / "definitions.json")
    old = store.create("a", "runtime", "python", "decision", "project", "human")
    with pytest.raises(ProjectDefinitionError, match="Cross-project"):
        store.create("b", "runtime", "rust", "decision", "project", "human", supersedes=old.id)


def test_multiple_active_values_are_reported_as_conflict(tmp_path):
    store = ProjectDefinitionStore(tmp_path / "definitions.json")
    store.create("project", "runtime", "python", "decision", "project", "human")
    store.create("project", "runtime", "rust", "decision", "project", "human")
    context = compose_project_context("project", _intelligence(tmp_path), store.active("project"), _config())
    assert any(conflict.reason == "Multiple incompatible active definitions" for conflict in context.conflicts)


def test_intended_state_conflict_does_not_overwrite_intelligence(tmp_path):
    store = ProjectDefinitionStore(tmp_path / "definitions.json")
    store.create("project", "languages", ["rust"], "intended_state", "project", "human")
    intelligence = _intelligence(tmp_path, ("python",))
    context = compose_project_context("project", intelligence, store.active("project"), _config())
    assert context.intelligence is intelligence
    assert context.intelligence.language_names == ("python",)
    assert any(conflict.sources == ("project_definition", "project_intelligence") for conflict in context.conflicts)


def test_config_conflict_preserves_typed_config(tmp_path):
    store = ProjectDefinitionStore(tmp_path / "definitions.json")
    store.create("project", "ai.model", "model-b", "technical_config", "project", "human")
    config = _config(model="model-a")
    context = compose_project_context("project", _intelligence(tmp_path), store.active("project"), config)
    assert context.technical_config is config
    assert any(conflict.sources == ("project_definition", "config.yml") for conflict in context.conflicts)


def test_allow_definition_grants_no_automatic_authority(tmp_path):
    store = ProjectDefinitionStore(tmp_path / "definitions.json")
    definition = store.create(
        "project", "allow.install", True, "policy", "project", "human",
    )
    assert definition.status == ACTIVE
    assert not hasattr(definition, "is_approved")
    assert not hasattr(definition, "execution_authority")


def test_raw_chat_history_is_not_accepted_as_memory(tmp_path):
    store = ProjectDefinitionStore(tmp_path / "definitions.json")
    with pytest.raises(ProjectDefinitionError, match="Raw conversation"):
        store.create(
            "project", "chat", "complete transcript", "memory", "project",
            "chat_history",
        )
