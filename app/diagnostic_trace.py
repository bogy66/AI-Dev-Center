"""Central, structured and persistent workflow diagnostic trace."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import re
import threading
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional


# Existing developer/provider trace contract retained for compatibility.
SENSITIVE_KEYS = {"api_key", "apikey", "secret", "token", "password", "credential", "bearer"}


class TraceLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


_TRACE_LEVEL_RANK = {
    TraceLevel.DEBUG: 0, TraceLevel.INFO: 1,
    TraceLevel.WARNING: 2, TraceLevel.ERROR: 3,
}


def _is_sensitive_key(key: str) -> bool:
    return any(sensitive in key.lower() for sensitive in SENSITIVE_KEYS)


def _redact_text(text: str) -> str:
    pattern = re.compile(r"(?i)(api_key|apikey|secret|token|password|credential|bearer)\s*[=:]\s*[^\s,;]+")
    return pattern.sub(r"\1=[REDACTED]", text)


def sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: ("[REDACTED]" if _is_sensitive_key(str(key)) else sanitize_value(val)) for key, val in value.items()}
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_value(item) for item in value)
    if isinstance(value, set):
        return {sanitize_value(item) for item in value}
    if isinstance(value, str):
        return _redact_text(value)
    return value


@dataclass
class TraceEvent:
    timestamp: datetime
    run_id: str
    level: TraceLevel
    component: str
    event: str
    action: str
    status: str
    duration_ms: Optional[float] = None
    arguments: Optional[Dict[str, Any]] = None
    result_summary: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class DiagnosticTraceRecorder:
    """Existing in-memory developer trace; distinct from the audit store below."""
    def __init__(self, run_id: str, trace_level: TraceLevel = TraceLevel.INFO, persist_path: Optional[Path] = None):
        self.run_id, self.trace_level, self.persist_path = run_id, trace_level, persist_path
        self.events: List[TraceEvent] = []

    def enabled(self, level: TraceLevel) -> bool:
        return _TRACE_LEVEL_RANK[level] >= _TRACE_LEVEL_RANK[self.trace_level]

    def record(self, level, component, event, action, status, duration_ms=None, arguments=None, result_summary=None, metadata=None):
        if not self.enabled(level):
            return None
        trace_event = TraceEvent(
            datetime.now(timezone.utc), self.run_id, level, component, event,
            action, status, duration_ms,
            sanitize_value(arguments) if arguments is not None else None,
            str(sanitize_value(result_summary)) if result_summary is not None else None,
            sanitize_value(metadata) if metadata is not None else None,
        )
        self.events.append(trace_event)
        if self.persist_path is not None:
            self._persist(trace_event)
        return trace_event

    def _persist(self, trace_event):
        try:
            with self.persist_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(self._serialize_event(trace_event), ensure_ascii=False) + "\n")
        except Exception:
            pass

    @staticmethod
    def _serialize_event(trace_event):
        return {
            "timestamp": trace_event.timestamp.isoformat(), "run_id": trace_event.run_id,
            "level": trace_event.level.value, "component": trace_event.component,
            "event": trace_event.event, "action": trace_event.action,
            "status": trace_event.status, "duration_ms": trace_event.duration_ms,
            "arguments": trace_event.arguments, "result_summary": trace_event.result_summary,
            "metadata": trace_event.metadata,
        }

    def export(self):
        return {"run_id": self.run_id, "trace_level": self.trace_level.value, "events": [self._serialize_event(event) for event in self.events]}

    def export_json(self):
        return json.dumps(self.export(), indent=2, ensure_ascii=False)


def new_run_id() -> str:
    return uuid.uuid4().hex


PHASES = frozenset({
    "common_request", "project_inspection", "requirement_discovery",
    "requirement_validation", "preflight", "engineering_council",
    "toolchain_materialization", "setup_plan", "setup_approval",
    "setup_execution", "development", "test_generation", "testing",
    "diagnosis_review", "controlled_rework", "final_approval",
    "change_provenance", "controlled_git", "publish_approval",
    "controlled_publish", "workflow_end",
})
EVENT_TYPES = frozenset({
    "started", "completed", "pending", "approved", "rejected", "blocked",
    "failed", "timeout", "rework_required", "committed", "published",
    "already_published", "nothing_to_commit", "requested",
})
STATUSES = EVENT_TYPES | frozenset({"accepted", "passed", "success", "incomplete", "review_failed", "ready_for_git", "ready_for_publish"})
DETAIL_KEYS = frozenset({
    "project_id", "project_type_count", "file_count", "warning_count",
    "requirement_count", "error_count", "missing_count", "result_count",
    "variant_count", "recommendation", "council_complete", "plan_id",
    "step_count", "controlled_path_count", "applied_path_count",
    "skipped_path_count", "runner", "passed", "timed_out", "return_code",
    "passed_count", "failed_count", "skipped_count", "duration_seconds",
    "rework_executed", "cycle", "commit_hash", "remote", "remote_ref",
    "published_commit_hash", "blockers", "failure_summary", "end_state",
})

_locks_guard = threading.Lock()
_locks: dict[str, threading.RLock] = {}
_SENSITIVE = re.compile(
    r"(?i)(bearer\s+)[^\s,;]+|"
    r"((?:api[_-]?key|token|password|authorization|cookie)\s*[:=]\s*)[^\n,;]+|"
    r"([a-z][a-z0-9+.-]*://)[^/@\s]+@|"
    r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----",
    re.DOTALL,
)


class DiagnosticTraceError(RuntimeError):
    pass


def _redact(value: str) -> str:
    def replacement(match):
        if match.group(1):
            return f"{match.group(1)}[REDACTED]"
        if match.group(2):
            return f"{match.group(2)}[REDACTED]"
        if match.group(3):
            return f"{match.group(3)}[REDACTED]@"
        return "[REDACTED PRIVATE KEY]"
    return _SENSITIVE.sub(replacement, value)


@dataclass(frozen=True)
class DiagnosticTraceEvent:
    event_id: str
    run_id: str
    sequence: int
    timestamp: str
    phase: str
    event_type: str
    status: str
    summary: str
    source: str
    details: dict
    related_result_id: str | None = None

    @classmethod
    def from_record(cls, record: dict) -> "DiagnosticTraceEvent":
        return cls(**record)


class DiagnosticTraceStore:
    """Append-only JSONL persistence with process/thread consistency."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        key = str(self.path.resolve())
        with _locks_guard:
            self._lock = _locks.setdefault(key, threading.RLock())

    def append(self, event_data: dict) -> DiagnosticTraceEvent:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock, self.path.open("a+", encoding="utf-8") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                handle.seek(0)
                events = self._parse(handle.read())
                run_events = [event for event in events if event.run_id == event_data["run_id"]]
                related = event_data.get("related_result_id")
                if related:
                    for existing in run_events:
                        if (
                            existing.related_result_id == related
                            and existing.phase == event_data["phase"]
                            and existing.event_type == event_data["event_type"]
                            and existing.status == event_data["status"]
                        ):
                            return existing
                event = DiagnosticTraceEvent(
                    event_id=str(uuid.uuid4()),
                    sequence=max((item.sequence for item in run_events), default=0) + 1,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    **event_data,
                )
                handle.seek(0, 2)
                handle.write(json.dumps(asdict(event), ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                __import__("os").fsync(handle.fileno())
                return event
        except DiagnosticTraceError:
            raise
        except (OSError, TypeError, ValueError) as error:
            raise DiagnosticTraceError(f"Diagnostic trace append failed: {type(error).__name__}") from error

    def read(self, run_id: str) -> tuple[DiagnosticTraceEvent, ...]:
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id must be a non-empty string")
        if not self.path.exists():
            return ()
        try:
            with self._lock, self.path.open("r", encoding="utf-8") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
                events = self._parse(handle.read())
            return tuple(event for event in events if event.run_id == run_id)
        except DiagnosticTraceError:
            raise
        except OSError as error:
            raise DiagnosticTraceError(f"Diagnostic trace read failed: {type(error).__name__}") from error

    @staticmethod
    def _parse(raw: str) -> list[DiagnosticTraceEvent]:
        events = []
        for number, line in enumerate(raw.splitlines(), 1):
            if not line.strip():
                continue
            try:
                events.append(DiagnosticTraceEvent.from_record(json.loads(line)))
            except (json.JSONDecodeError, TypeError, KeyError) as error:
                raise DiagnosticTraceError(f"Invalid diagnostic trace record at line {number}") from error
        return events


class DiagnosticTrace:
    """Validated application-facing trace writer and reader."""

    def __init__(self, store: DiagnosticTraceStore):
        self.store = store

    def record(
        self, run_id: str, phase: str, event_type: str, status: str,
        summary: str, *, source: str = "application", details: dict | None = None,
        related_result_id: str | None = None,
    ) -> DiagnosticTraceEvent:
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id must be a non-empty string")
        if phase not in PHASES:
            raise ValueError("Unsupported diagnostic trace phase")
        if event_type not in EVENT_TYPES or status not in STATUSES:
            raise ValueError("Unsupported diagnostic trace event/status")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("summary must be a non-empty string")
        safe_details = {}
        for key, value in (details or {}).items():
            if key not in DETAIL_KEYS:
                continue
            safe_details[key] = self._safe_value(value)
        return self.store.append({
            "run_id": run_id,
            "phase": phase,
            "event_type": event_type,
            "status": status,
            "summary": _redact(summary)[:500],
            "source": _redact(str(source))[:100],
            "details": safe_details,
            "related_result_id": _redact(related_result_id)[:200] if related_result_id else None,
        })

    def get_trace(self, run_id: str) -> tuple[DiagnosticTraceEvent, ...]:
        return self.store.read(run_id)

    @staticmethod
    def _safe_value(value):
        if isinstance(value, str):
            return _redact(value)[:500]
        if isinstance(value, (bool, int, float)) or value is None:
            return value
        if isinstance(value, (list, tuple)):
            return [DiagnosticTrace._safe_value(item) for item in value[:50] if isinstance(item, (str, bool, int, float)) or item is None]
        return "[UNSUPPORTED]"
