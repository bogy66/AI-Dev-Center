"""Durable project definitions and provenance-preserving project context."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
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

    def all(self) -> tuple[ProjectDefinition, ...]:
        """Return every definition for every project, active or not.

        Used by ProjectRegistry to enumerate known projects without
        requiring a separate index of project ids.
        """
        return tuple(self._model(record) for record in self._load())

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


# ---------------------------------------------------------------------------
# Project lifecycle registry (CLAUDE-003): rename / archive / restore / delete
#
# This is a central extension of ProjectDefinitionStore, not a second
# persistence mechanism. A project's stable identity is derived
# deterministically from its normalized filesystem path (independent of the
# ad-hoc, mutable project_name used by an individual DevelopmentWorkflow
# session); its display name and lifecycle status are ordinary
# ProjectDefinition records under that identity, mutated only through the
# store's existing create/supersede history model. No record is ever
# deleted: "removing" a project from ADC management supersedes its
# lifecycle status to REMOVED_STATUS, which simply excludes it from both
# the active and archived listings while preserving full history.
# ---------------------------------------------------------------------------

_REGISTRY_CATEGORY = "project_registration"
_REGISTRY_SCOPE = "project_lifecycle"
_REGISTRY_SOURCE = "project_registry"

_PROJECT_ROOT_KEY = "project_root"
_DISPLAY_NAME_KEY = "display_name"
_LIFECYCLE_KEY = "lifecycle_status"

ACTIVE_STATUS = "active"
ARCHIVED_STATUS = "archived"
REMOVED_STATUS = "removed"


class ProjectRegistryError(Exception):
    """Raised for unknown projects, invalid transitions, or invalid names."""


def derive_project_id(project_root: str) -> str:
    """Derive a stable project identity from a normalized filesystem path.

    The same path always yields the same id, independent of any display
    name, so renaming a project can never orphan its registration or its
    accumulated project history.
    """
    resolved = str(Path(project_root).expanduser().resolve(strict=False))
    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:24]
    return f"project-{digest}"


@dataclass(frozen=True)
class ProjectRecord:
    project_id: str
    display_name: str
    project_root: str
    lifecycle_status: str


class ProjectRegistry:
    """Explicit ADC project lifecycle operations over ProjectDefinitionStore."""

    def __init__(self, store: ProjectDefinitionStore):
        self._store = store

    # -- internal helpers ---------------------------------------------------

    def _current(self, project_id: str, key: str) -> ProjectDefinition | None:
        matches = [item for item in self._store.active(project_id) if item.key == key]
        return matches[0] if matches else None

    def _record(self, project_id: str) -> ProjectRecord:
        root = self._current(project_id, _PROJECT_ROOT_KEY)
        name = self._current(project_id, _DISPLAY_NAME_KEY)
        status = self._current(project_id, _LIFECYCLE_KEY)
        if root is None or name is None or status is None:
            raise ProjectRegistryError(f"Unknown project '{project_id}'")
        return ProjectRecord(project_id, name.value, root.value, status.value)

    def _known_project_ids(self) -> set[str]:
        return {
            definition.project_id
            for definition in self._store.all()
            if definition.status == ACTIVE and definition.key == _LIFECYCLE_KEY
        }

    def _assert_name_available(self, new_name: str, *, excluding: str) -> None:
        for record in self.list_by_status(ACTIVE_STATUS) + self.list_by_status(ARCHIVED_STATUS):
            if record.project_id != excluding and record.display_name.casefold() == new_name.casefold():
                raise ProjectRegistryError(
                    f"A project named '{new_name}' already exists."
                )

    # -- public operations ---------------------------------------------------

    def register(self, project_root: str, display_name: str | None = None) -> ProjectRecord:
        """Idempotently register a known project root as an active project.

        Returns the existing record unchanged if this path is already
        known, at whatever lifecycle status it currently has — this never
        silently reactivates an archived or removed project.
        """
        project_id = derive_project_id(project_root)
        if self._current(project_id, _PROJECT_ROOT_KEY) is not None:
            return self._record(project_id)

        resolved_root = str(Path(project_root).expanduser().resolve(strict=False))
        name = (display_name or Path(resolved_root).name or project_id).strip() or project_id
        self._store.create(
            project_id, _PROJECT_ROOT_KEY, resolved_root,
            _REGISTRY_CATEGORY, _REGISTRY_SCOPE, _REGISTRY_SOURCE,
        )
        self._store.create(
            project_id, _DISPLAY_NAME_KEY, name,
            _REGISTRY_CATEGORY, _REGISTRY_SCOPE, _REGISTRY_SOURCE,
        )
        self._store.create(
            project_id, _LIFECYCLE_KEY, ACTIVE_STATUS,
            _REGISTRY_CATEGORY, _REGISTRY_SCOPE, _REGISTRY_SOURCE,
        )
        return self._record(project_id)

    def get(self, project_id: str) -> ProjectRecord:
        return self._record(project_id)

    def status_of(self, project_root: str) -> str | None:
        """Return the lifecycle status for a path, or None if unregistered."""
        project_id = derive_project_id(project_root)
        if self._current(project_id, _PROJECT_ROOT_KEY) is None:
            return None
        return self._record(project_id).lifecycle_status

    def list_by_status(self, status: str) -> tuple[ProjectRecord, ...]:
        records = tuple(self._record(pid) for pid in self._known_project_ids())
        return tuple(sorted(
            (record for record in records if record.lifecycle_status == status),
            key=lambda record: record.display_name.casefold(),
        ))

    def rename(self, project_id: str, new_name: str) -> ProjectRecord:
        new_name = (new_name or "").strip()
        if not new_name:
            raise ProjectRegistryError("Project name must not be empty.")
        current = self._record(project_id)  # raises ProjectRegistryError if unknown
        if current.lifecycle_status == REMOVED_STATUS:
            raise ProjectRegistryError("A removed project cannot be renamed.")
        self._assert_name_available(new_name, excluding=project_id)
        name_definition = self._current(project_id, _DISPLAY_NAME_KEY)
        self._store.supersede(name_definition.id, new_name, _REGISTRY_SOURCE)
        return self._record(project_id)

    def archive(self, project_id: str) -> ProjectRecord:
        current = self._record(project_id)
        if current.lifecycle_status != ACTIVE_STATUS:
            raise ProjectRegistryError(
                f"Only an active project can be archived (current status: "
                f"'{current.lifecycle_status}')."
            )
        status_definition = self._current(project_id, _LIFECYCLE_KEY)
        self._store.supersede(status_definition.id, ARCHIVED_STATUS, _REGISTRY_SOURCE)
        return self._record(project_id)

    def restore(self, project_id: str) -> ProjectRecord:
        current = self._record(project_id)
        if current.lifecycle_status != ARCHIVED_STATUS:
            raise ProjectRegistryError(
                f"Only an archived project can be restored (current status: "
                f"'{current.lifecycle_status}')."
            )
        status_definition = self._current(project_id, _LIFECYCLE_KEY)
        self._store.supersede(status_definition.id, ACTIVE_STATUS, _REGISTRY_SOURCE)
        return self._record(project_id)

    def remove(self, project_id: str) -> ProjectRecord:
        """Remove an archived project from ADC management.

        This only supersedes the project's lifecycle-status definition to
        REMOVED_STATUS inside the existing definition-history store; it
        never touches the filesystem, Git, or any project directory.
        """
        current = self._record(project_id)
        if current.lifecycle_status != ARCHIVED_STATUS:
            raise ProjectRegistryError(
                "Only an archived project can be removed from ADC management "
                f"(current status: '{current.lifecycle_status}')."
            )
        status_definition = self._current(project_id, _LIFECYCLE_KEY)
        self._store.supersede(status_definition.id, REMOVED_STATUS, _REGISTRY_SOURCE)
        return self._record(project_id)


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
