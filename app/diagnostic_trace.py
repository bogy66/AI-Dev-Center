from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "secret",
    "token",
    "password",
    "credential",
    "bearer",
}


class TraceLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


_TRACE_LEVEL_RANK = {
    TraceLevel.DEBUG: 0,
    TraceLevel.INFO: 1,
    TraceLevel.WARNING: 2,
    TraceLevel.ERROR: 3,
}


def _is_sensitive_key(key: str) -> bool:
    return any(sensitive in key.lower() for sensitive in SENSITIVE_KEYS)


def _redact_text(text: str) -> str:
    """Redact common ``key=value`` / ``key: value`` secret patterns."""
    pattern = re.compile(
        r'(?i)(api_key|apikey|secret|token|password|credential|bearer)\s*[=:]\s*[^\s,;]+'
    )
    return pattern.sub(r"\1=[REDACTED]", text)


def sanitize_value(value: Any) -> Any:
    """Return a sanitized copy of *value*.

    Dictionaries are traversed recursively.  Keys that look secret are
    replaced with ``[REDACTED]``.  Strings are passed through the light
    text redactor.
    """
    if isinstance(value, dict):
        return {
            key: ("[REDACTED]" if _is_sensitive_key(str(key)) else sanitize_value(val))
            for key, val in value.items()
        }
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
    """Centralized diagnostic trace facility.

    The selected trace level controls which events are recorded for the
    current run.  Category filters are purely a display-layer concern and
    are not implemented here.
    """

    def __init__(
        self,
        run_id: str,
        trace_level: TraceLevel = TraceLevel.INFO,
        persist_path: Optional[Path] = None,
    ) -> None:
        self.run_id = run_id
        self.trace_level = trace_level
        self.persist_path = persist_path
        self.events: List[TraceEvent] = []

    def enabled(self, level: TraceLevel) -> bool:
        return _TRACE_LEVEL_RANK[level] >= _TRACE_LEVEL_RANK[self.trace_level]

    def record(
        self,
        level: TraceLevel,
        component: str,
        event: str,
        action: str,
        status: str,
        duration_ms: Optional[float] = None,
        arguments: Optional[Dict[str, Any]] = None,
        result_summary: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[TraceEvent]:
        if not self.enabled(level):
            return None

        safe_arguments = sanitize_value(arguments) if arguments is not None else None
        safe_result = (
            sanitize_value(result_summary) if result_summary is not None else None
        )
        safe_metadata = sanitize_value(metadata) if metadata is not None else None

        trace_event = TraceEvent(
            timestamp=datetime.now(timezone.utc),
            run_id=self.run_id,
            level=level,
            component=component,
            event=event,
            action=action,
            status=status,
            duration_ms=duration_ms,
            arguments=safe_arguments,
            result_summary=str(safe_result) if safe_result is not None else None,
            metadata=safe_metadata,
        )

        self.events.append(trace_event)

        if self.persist_path is not None:
            self._persist(trace_event)

        return trace_event

    def _persist(self, trace_event: TraceEvent) -> None:
        try:
            with self.persist_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(self._serialize_event(trace_event), ensure_ascii=False)
                    + "\n"
                )
        except Exception:
            # Persistence must never break the workflow itself.
            pass

    @staticmethod
    def _serialize_event(trace_event: TraceEvent) -> Dict[str, Any]:
        return {
            "timestamp": trace_event.timestamp.isoformat(),
            "run_id": trace_event.run_id,
            "level": trace_event.level.value,
            "component": trace_event.component,
            "event": trace_event.event,
            "action": trace_event.action,
            "status": trace_event.status,
            "duration_ms": trace_event.duration_ms,
            "arguments": trace_event.arguments,
            "result_summary": trace_event.result_summary,
            "metadata": trace_event.metadata,
        }

    def export(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "trace_level": self.trace_level.value,
            "events": [self._serialize_event(event) for event in self.events],
        }

    def export_json(self) -> str:
        return json.dumps(self.export(), indent=2, ensure_ascii=False)


def new_run_id() -> str:
    return uuid.uuid4().hex
