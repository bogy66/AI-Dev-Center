"""Durable project definitions and provenance-preserving project context."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import uuid
from typing import Any

from app.ai_config import AIConfig
from app.project_intelligence import ProjectIntelligence
from app.state_lock import get_state_lock

ACTIVE = "active"
SUPERSEDED = "superseded"
REVOKED = "revoked"


class ProjectDefinitionError(Exception):
    pass


@dataclass(frozen=True)
class ProjectDefinition:
    id: str
    project_id: str
    key: str
    value: Any
    category: str
    scope: str
    status: str
    source: str
    created_at: str
    updated_at: str
    supersedes: str | None = None


@dataclass(frozen=True)
class ProjectContextConflict:
    key: str
    sources: tuple[str, ...]
    values: tuple[Any, ...]
    reason: str


@dataclass(frozen=True)
class ProjectContext:
    project_id: str
    project_root: str
    intelligence: ProjectIntelligence
    definitions: tuple[ProjectDefinition, ...]
    technical_config: AIConfig
    conflicts: tuple[ProjectContextConflict, ...]


class ProjectDefinitionStore:
    """Atomic JSON history store; records are transitioned, never deleted."""
    def __init__(self, path: str | Path = ".project-definitions/definitions.json"):
        self.path = Path(path)
        self._lock = get_state_lock(self.path)

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ProjectDefinitionError("Project definition store is unreadable") from error
        if not isinstance(data, list):
            raise ProjectDefinitionError("Project definition store must contain a list")
        return data

    def _save(self, records: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=self.path.parent, prefix=".definitions-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(records, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except Exception:
            if os.path.exists(temporary):
                os.remove(temporary)
            raise

    @staticmethod
    def _model(record: dict) -> ProjectDefinition:
        return ProjectDefinition(**record)

    @staticmethod
    def _validate_fields(project_id, key, category, scope, source, value) -> None:
        if not all(isinstance(item, str) and item.strip() for item in (project_id, key, category, scope, source)):
            raise ProjectDefinitionError("Definition identity fields must be non-empty strings")
        if source.strip().lower() in {"raw_chat", "chat_history", "conversation_history"}:
            raise ProjectDefinitionError("Raw conversation history is not a Project Definition source")
        try:
            json.dumps(value)
        except (TypeError, ValueError) as error:
            raise ProjectDefinitionError("Definition value must be structured JSON data") from error

    def create(self, project_id, key, value, category, scope, source, *, definition_id=None, supersedes=None):
        self._validate_fields(project_id, key, category, scope, source, value)
        now = datetime.now(timezone.utc).isoformat()
        new_id = definition_id or f"definition-{uuid.uuid4().hex}"
        with self._lock:
            records = self._load()
            if any(record.get("id") == new_id for record in records):
                raise ProjectDefinitionError("Definition id already exists")
            if supersedes is not None:
                previous = next((record for record in records if record.get("id") == supersedes), None)
                if previous is None:
                    raise ProjectDefinitionError("Superseded definition does not exist")
                if previous.get("project_id") != project_id:
                    raise ProjectDefinitionError("Cross-project supersession is forbidden")
                if previous.get("status") != ACTIVE:
                    raise ProjectDefinitionError("Only an active definition may be superseded")
                previous["status"] = SUPERSEDED
                previous["updated_at"] = now
            definition = ProjectDefinition(
                new_id, project_id, key, value, category, scope, ACTIVE,
                source, now, now, supersedes,
            )
            records.append(asdict(definition))
            self._save(records)
        return definition

    def get(self, definition_id: str) -> ProjectDefinition:
        record = next((record for record in self._load() if record.get("id") == definition_id), None)
        if record is None:
            raise ProjectDefinitionError("Definition does not exist")
        return self._model(record)

    def list(self, project_id: str) -> tuple[ProjectDefinition, ...]:
        return tuple(self._model(record) for record in self._load() if record.get("project_id") == project_id)

    def active(self, project_id: str) -> tuple[ProjectDefinition, ...]:
        return tuple(item for item in self.list(project_id) if item.status == ACTIVE)

    def supersede(self, definition_id, value, source, *, definition_id_new=None):
        previous = self.get(definition_id)
        return self.create(
            previous.project_id, previous.key, value, previous.category,
            previous.scope, source, definition_id=definition_id_new,
            supersedes=definition_id,
        )

    def revoke(self, definition_id: str) -> ProjectDefinition:
        with self._lock:
            records = self._load()
            record = next((item for item in records if item.get("id") == definition_id), None)
            if record is None:
                raise ProjectDefinitionError("Definition does not exist")
            if record.get("status") != ACTIVE:
                raise ProjectDefinitionError("Only an active definition may be revoked")
            record["status"] = REVOKED
            record["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save(records)
            return self._model(record)


_INTELLIGENCE_KEYS = {
    "languages": lambda value: tuple(value.language_names),
    "frameworks": lambda value: tuple(value.framework_names),
    "package_systems": lambda value: tuple(value.package_system_names),
    "build_systems": lambda value: tuple(value.build_system_names),
    "test_systems": lambda value: tuple(value.test_system_names),
    "project_kind": lambda value: value.project_kind,
}
_CONFIG_KEYS = {
    "ai.provider": lambda value: value.provider,
    "ai.model": lambda value: value.model,
    "ai.endpoint": lambda value: value.endpoint,
    "ai.timeout_seconds": lambda value: value.timeout_seconds,
}


def compose_project_context(project_id, intelligence, definitions, technical_config):
    active = tuple(item for item in definitions if item.status == ACTIVE)
    conflicts: list[ProjectContextConflict] = []
    grouped: dict[tuple[str, str], list[ProjectDefinition]] = {}
    for definition in active:
        grouped.setdefault((definition.key, definition.scope), []).append(definition)
    for (key, _scope), items in grouped.items():
        distinct = {json.dumps(item.value, sort_keys=True) for item in items}
        if len(distinct) > 1:
            conflicts.append(ProjectContextConflict(
                key, ("project_definition",) * len(items),
                tuple(item.value for item in items),
                "Multiple incompatible active definitions",
            ))
        for item in items:
            if item.category == "intended_state" and key in _INTELLIGENCE_KEYS:
                observed = _INTELLIGENCE_KEYS[key](intelligence)
                intended = tuple(item.value) if isinstance(item.value, list) else item.value
                if intended != observed:
                    conflicts.append(ProjectContextConflict(
                        key, ("project_definition", "project_intelligence"),
                        (item.value, observed), "Intended state differs from observed reality",
                    ))
            if item.category == "technical_config" and key in _CONFIG_KEYS:
                configured = _CONFIG_KEYS[key](technical_config)
                if item.value != configured:
                    conflicts.append(ProjectContextConflict(
                        key, ("project_definition", "config.yml"),
                        (item.value, configured), "Definition differs from owned technical configuration",
                    ))
    return ProjectContext(
        project_id, str(Path(intelligence.project_root).resolve()), intelligence,
        active, technical_config, tuple(conflicts),
    )
