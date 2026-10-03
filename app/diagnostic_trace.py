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


SHARED_ADC_CONTEXT = (
    "AI-Dev-Center is a controlled engineering system for developing and "
    "maintaining software, firmware, and hardware-related projects."
)


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
    # The central value redaction (see _redact below) is applied too.
    return _redact(pattern.sub(r"\1=[REDACTED]", text))


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
    "human_engineering_authority",
    "toolchain_materialization", "setup_plan", "setup_approval",
    "setup_execution", "development", "test_generation", "testing",
    "diagnosis_review", "controlled_rework", "final_approval",
    "change_provenance", "controlled_git", "publish_approval",
    "controlled_publish", "workflow_end",
    "verification_plan_created", "verification_step_started",
    "verification_step_completed", "verification_step_failed",
    "verification_completed",
})
EVENT_TYPES = frozenset({
    "started", "completed", "pending", "approved", "rejected", "blocked",
    "failed", "timeout", "rework_required", "committed", "published",
    "already_published", "nothing_to_commit", "requested",
})
STATUSES = EVENT_TYPES | frozenset({"accepted", "passed", "success", "incomplete", "review_failed", "ready_for_git", "ready_for_publish", "recovery_required", "unsupported", "tool_unavailable", "execution_error", "invalid_plan", "not_applicable"})
DETAIL_KEYS = frozenset({
    "project_id", "project_type_count", "file_count", "warning_count",
    "requirement_count", "error_count", "missing_count", "result_count",
    "variant_count", "recommendation", "council_complete", "council_degraded",
    "plan_id",
    "step_count", "controlled_path_count", "applied_path_count",
    "skipped_path_count", "runner", "passed", "timed_out", "return_code",
    "passed_count", "failed_count", "skipped_count", "duration_seconds",
    "rework_executed", "cycle", "commit_hash", "remote", "remote_ref",
    "published_commit_hash", "blockers", "failure_summary", "end_state",
    "execution_stage",
    "project_kind", "language_count", "framework_count", "area_count",
    "git_repository_present", "truncated",
    "aggregate_status", "verification_step_count", "truncated_output",
    "error_category", "diagnostics",
    "actor", "actor_role", "runtime_state", "council_phase", "provider",
    "model", "failure_category", "diagnostic_level", "result_kind", "duration_ms",
    "council_output",
    "interface_data", "interface_stage", "upstream_stage", "downstream_stage",
    "execution_identity",
    # SUB_REQ_035/036: callback-independent critical Council diagnosis.
    "council_lifecycle",
    # SUB_REQ_035: identifies one Council contributor invocation, so the
    # public current state can stay monotone per invocation.
    "invocation_id",
    "effective_prompt",
    "admissible_variant_ids", "human_selected_variant_id",
    "selected_variant_id", "selection_authority",
    # CLAUDE-ADC-RSE033-DEVELOPMENT-EMPTY-REPAIR-009: redacted S4.1
    # generation evidence and the S4 stage that ended a cycle before S5
    # -- counts, booleans and fixed ADC classification tokens only,
    # never provider text, file paths or contents.
    "generated_change_count", "apply_attempted", "repair_attempted",
    "initial_parse_error_class", "failure_stage",
    # CLAUDE-ADC-DIAGNOSTIC-TRACE-TRUTHFULNESS-REDACTION-FIX-010: marks a
    # lifecycle event recorded after execution ("post_hoc"), so it can
    # never be read as the live timing of that phase.
    "timing",
})

COUNCIL_OUTPUT_KEYS = frozenset({
    "info", "verbose", "very_verbose", "summary", "name", "description",
    "recommendation", "selected_approach", "status", "risks", "constraints",
    "concerns", "preferences", "variant_id", "variant_ids", "agent_id",
    "role", "phase", "environment", "hardware_target", "connection",
    "capabilities", "toolchain", "requirement_ref", "type", "version",
    "purpose", "depends_on", "state", "environment_constraint", "advantages",
    "disadvantages", "confidence", "feasibility", "scores",
    "would_recommend", "reviews", "rejected_variants", "preferred_variants",
    "merge_decisions", "merged_variant_ids", "resulting_variant_id", "reason",
    "council_complete", "council_degraded", "error_count", "total_llm_calls",
    "result_id",
    "chairman_error", "chairman_failure_category", "chairman_attempts",
    "chairman_failure_subsystem",
    "plausibility", "completeness", "complexity", "risk", "ci_cd_fitness",
    "maintainability", "cost_efficiency",
    "admissible", "reasons", "rank", "total_score", "consensus_level",
    "requirement_coverage",
    "normal", "x", "y", "input", "output", "intent", "user_request",
    "user_request_present", "project", "project_id", "project_root", "project_kind",
    "file_count", "area_count", "languages", "frameworks", "package_systems",
    "build_systems", "test_systems", "requirements", "requirement_count",
    "required", "valid", "errors", "warnings", "warning_count", "error_count",
    "normalized_requirements", "missing_requirements", "missing_count",
    "overall_ready", "preflight_results", "present", "satisfied",
    "detected_version", "stack", "project_files", "validation_warnings",
    "proposal_count", "review_count", "proposals", "proposal", "review",
    "chairman_decision", "available", "source", "destination",
    "id", "requirement_id", "result_count", "required_version",
    "evidence_count", "error_category", "firmware_indicators", "git_repository_present",
    "truncated", "total_files_traversed", "f", "entity", "entity_version",
    "implementation_version", "provider", "model", "model_version",
    "actor", "actor_role", "phase", "council_phase", "dependencies",
    "interface", "data", "task_description",
    "effective_prompt",
    # CLAUDE-ARCH-S2-014D: ProjectIntelligence.to_summary()'s per-area
    # scope breakdown (see there) -- "path" is the ProjectArea.path each
    # nested area entry carries; the sibling "test_systems"/
    # "build_systems"/"firmware_indicators"/"name" keys are already
    # allowed above.
    "areas", "path", "has_untrusted_hooks",
    # CLAUDE-ADC-COUNCIL-DIAGNOSTIC-TRACE-INTEGRATION-FIX-001: the
    # minimal, bounded, non-sensitive fields app.engineering_council's
    # zero-retained-Phase-1-proposal branch classification needs --
    # structural type/count/id metadata only, exactly like the existing
    # "*_count"/"type"/"requirement_id" keys already above; "attempt" is
    # a small integer (which retry attempt), "rejected_candidates" is a
    # bounded list of {category, rejected_requirement_refs,
    # rejected_provided_by} dicts (each of those three keys individually
    # allowed here too) -- never free text, never a raw exception message.
    "root_parsed_type", "variants_field_present", "variants_field_type",
    "variants_field_count", "requirement_ids", "rejected_candidates",
    "category", "rejected_requirement_refs", "rejected_provided_by",
    "attempt",
    # CLAUDE-ADC-COUNCIL-DIAGNOSTIC-HARDENING-FIX-001 (Codex review
    # CDX-ADC-COUNCIL-DIAGNOSTIC-TRACE-REVIEW-001, F1): presence/type-only
    # evidence for a rejected candidate's own requirement_ref/provided_by
    # value when it was NOT a safe, bounded, single-token string (see
    # app.engineering_council._sanitized_candidate_identifier()) -- a
    # bounded list of Python type names only (e.g. "dict", "list"),
    # never the value's content. Defense in depth: even if this key were
    # ever misused to carry more than a type name, the recursive
    # allowlisting above still applies to it exactly like any other
    # council_output value.
    "rejected_requirement_ref_invalid_types", "rejected_provided_by_invalid_types",
    # CLAUDE-ADC-S23-MATERIALIZER-DIAGNOSTICS-001: the S2.3 binding-item/
    # materializer boundary diagnostic (app.engineering_decision.
    # binding_materializer_diagnostics()) -- bounded booleans, Python type
    # names, and fixed classification labels only. "safe_identifier" is
    # included ONLY when already policy-valid (never a raw, possibly-
    # invalid identifier); "install_method_classification" is a closed set
    # of shape labels, never install_method's own text. "variant_id",
    # "requirement_ref", "type", and "name" reuse the same existing keys
    # already allowed above for the identical concepts elsewhere in this
    # allowlist.
    "technical_identity_present", "technical_identity_python_type",
    "technical_identity_check_applicable", "technical_identity_valid",
    "name_valid_as_identifier", "safe_identifier",
    "install_method_python_type", "install_method_classification",
    "install_method_compatible", "materializer_action",
    "materializer_rejection_category",
})
# CLAUDE-ADC-COUNCIL-CONTRACT-CORRECTIONS-029 (SUB_REQ_035/036): keys of
# the critical Council lifecycle diagnosis ("council_lifecycle" detail):
# identities, causes, counters and states only; every string is redacted
# and bounded by the structured projection like all Council output.
COUNCIL_OUTPUT_KEYS = COUNCIL_OUTPUT_KEYS | frozenset({
    "run_id", "invocations", "invocation_id", "contributor", "terminal_state",
    "failure_category", "degraded", "timeout_scope", "handover", "boundary",
    "handovers", "transport_responses", "remote_confirmed", "remote_rejected",
    "remote_uncertain", "refused_after_close", "refused_budget", "start_claimed",
    "persistence", "error", "detail", "outcome", "accepted_contributors",
    "phase1", "phase2", "decision_errors", "late_additions", "kind",
    "event_time", "received_time", "success", "notifications", "activity",
    "results", "delivered", "failed", "skipped", "unconfirmed",
    "resource_errors", "omitted", "size_exceeded", "retained_call_record_bytes",
    "decision_error_count", "chairman_error_present",
})

FORBIDDEN_COUNCIL_OUTPUT_KEYS = frozenset({
    "prompt", "system_prompt", "raw_response", "raw_llm_response",
    "agent_reasoning", "reasoning", "chain_of_thought", "credentials",
    "authorization", "api_key", "secret", "token",
    "verification", "command", "shell_command", "argv", "executable",
})

_locks_guard = threading.Lock()
_locks: dict[str, threading.RLock] = {}
# Central value redaction, applied to every persisted string (summary,
# source, related ids and every allowed detail value, recursively) BEFORE
# it reaches events.jsonl, and again at rendering. It is value-based so it
# does not depend on which detail key or diagnostic level carries the
# text: a secret is never "safe" merely because it is rendered only at a
# higher DiagnosticDetailLevel.
#
# 1. Name-based: a credential-like NAME (api_key, AWS_ACCESS_KEY_ID,
#    OPENROUTER_API_KEY, client_secret, x-auth-token, password, cookie,
#    session id, private key ...) followed by = or : -- in env/header
#    ("NAME=value", "Authorization: Basic x") or quoted mapping form
#    ('"api_key": "value"', "'token': 'value'") -- keeps the name and
#    redacts the value.
_SECRET_NAME = (
    r"[A-Za-z0-9_.-]{0,40}?(?:"
    r"api[_-]?key|access[_-]?key(?:[_-]?id)?|secret(?:[_-]?access)?(?:[_-]?key)?|"
    r"client[_-]?secret|private[_-]?key|auth[_-]?token|access[_-]?token|"
    r"refresh[_-]?token|id[_-]?token|session(?:[_-]?(?:id|token|key|secret))?|"
    r"token|passw(?:or)?d|pwd|passphrase|credentials?|authorization|bearer|jwt|"
    r"cookie|set-cookie|x-api-key|signing[_-]?key|encryption[_-]?key"
    r")[A-Za-z0-9_.-]{0,40}"
)
#
# Every value recognizer below is TERMINATOR-INDEPENDENT: a quoted value
# whose closing quote lies beyond the scanned text (and likewise a PEM key
# without its END line or URL userinfo without its "@", see _SENSITIVE) is
# redacted up to the end of the text instead of being left alone. A scan or
# truncation window can therefore never turn a recognizable secret into an
# unrecognized one -- redaction fails closed at every boundary position.
_QUOTED_SECRET_PAIR = re.compile(
    r"""(?i)((["'])(?:key|""" + _SECRET_NAME + r""")\2\s*:\s*)(["'])(?!\[REDACTED)"""
    r"""(?:\\.|(?!\3).)*(?:\3|\Z)""",
    re.DOTALL,
)
# The same pair written as escaped JSON inside a string: \"api_key\": \"v\".
_ESCAPED_QUOTED_SECRET_PAIR = re.compile(
    r"""(?i)(\\{1,2}(["'])(?:key|""" + _SECRET_NAME + r""")\\{1,2}\2\s*:\s*(\\{1,2}))(["'])(?!\[REDACTED)"""
    r"""(?:(?!\\{1,2}\4).)*(?:\\{1,2}\4|\Z)""",
    re.DOTALL,
)
_SECRET_VALUE = (
    r"(?:(?:bearer|basic|token|digest)\s+)?"
    r"""(?:"(?:[^"\\\n]|\\.)*"?|'(?:[^'\\\n]|\\.)*'?"""
    r"""|\\{1,2}"(?:(?!\\{1,2}").)*(?:\\{1,2}"|$)|\\{1,2}'(?:(?!\\{1,2}').)*(?:\\{1,2}'|$)"""
    r"""|[^\s,;&"'}\]\\]+)"""
)
_NAMED_SECRET = re.compile(
    r"(?im)(\b" + _SECRET_NAME + r"""\b(?:\\{0,2}["'])?\s*[:=]\s*)(?!\\{0,2}["']?\[REDACTED)"""
    + _SECRET_VALUE,
)
# Environment-variable form: an UPPER_CASE name ending in a credential
# suffix (STATUS_KEY=..., DB_PASS=...) is always treated as a secret.
_ENV_SECRET = re.compile(
    r"(?m)(\b[A-Z][A-Z0-9_]*_(?:KEY|SECRET|TOKEN|PASSWORD|PASS|PWD|CREDENTIALS?|SESSION|BEARER|JWT|COOKIE)"
    r"""\s*=\s*)(?!\\{0,2}["']?\[REDACTED)""" + _SECRET_VALUE,
)
# 2. Shape-based: well-known credential formats, wherever they appear.
_SECRET_SHAPES = re.compile(
    r"(?:"
    r"(?<![A-Za-z0-9])sk-(?:or-v1-|ant-(?:api\d+-)?|proj-)?[A-Za-z0-9_-]{16,}|"   # OpenAI / OpenRouter / Anthropic
    r"(?<![A-Za-z0-9])(?:AKIA|ASIA|AGPA|AIDA|AROA|ANPA|ANVA)[A-Z0-9_]{8,}|"          # AWS access key ids
    r"(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{20,}|(?<![A-Za-z0-9])github_pat_[A-Za-z0-9_]{20,}|"
    r"(?<![A-Za-z0-9])xox[abprs]-[A-Za-z0-9-]{10,}|"                                 # Slack
    r"(?<![A-Za-z0-9])AIza[0-9A-Za-z_-]{30,}|"                                       # Google API key
    r"(?<![A-Za-z0-9])eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}" # JWT
    r")"
)
_SENSITIVE = re.compile(
    r"(?i)(bearer\s+)[^\s,;]+|"
    r"((?:api[_-]?key|token|password|authorization|cookie)\s*[:=]\s*)[^\n,;]+|"
    # URL userinfo; "user:pass" cut off before its "@" (text end) as well.
    # Possessive quantifiers: any userinfo length, linear, no backtracking.
    r"([a-z][a-z0-9+.-]{0,30}://)(?:[^/@\s]++@|[^/@\s:]*+:[^/@\s]*+\Z)|"
    r"-----BEGIN [^-]*PRIVATE KEY-----.*?(?:-----END [^-]*PRIVATE KEY-----|\Z)",
    re.DOTALL,
)


class DiagnosticTraceError(RuntimeError):
    pass


def _redact(value: str) -> str:
    # Every pattern above uses bounded quantifiers, so redaction stays
    # linear in the input length even for very large prompts/responses.
    def replacement(match):
        if match.group(1):
            return f"{match.group(1)}[REDACTED]"
        if match.group(2):
            return f"{match.group(2)}[REDACTED]"
        if match.group(3):
            return f"{match.group(3)}[REDACTED]" + ("@" if match.group(0).endswith("@") else "")
        return "[REDACTED PRIVATE KEY]"
    value = _SENSITIVE.sub(replacement, value)
    value = _QUOTED_SECRET_PAIR.sub(lambda m: f"{m.group(1)}{m.group(3)}[REDACTED]{m.group(3)}", value)
    value = _ESCAPED_QUOTED_SECRET_PAIR.sub(
        lambda m: f"{m.group(1)}{m.group(4)}[REDACTED]{m.group(3)}{m.group(4)}", value,
    )
    value = _NAMED_SECRET.sub(lambda m: f"{m.group(1)}[REDACTED]", value)
    value = _ENV_SECRET.sub(lambda m: f"{m.group(1)}[REDACTED]", value)
    return _SECRET_SHAPES.sub("[REDACTED]", value)


# A secret-named command-line option whose value follows as the NEXT argv
# element (`--password VALUE`, `--api-key VALUE`).
_SECRET_OPTION = re.compile(r"(?i)-{1,2}" + _SECRET_NAME)


def redact_argv(argv) -> tuple[str, ...]:
    """Element-wise redaction of a command's argv, BEFORE it is joined.

    A credential passed as the separate argument after a secret-named
    option carries no name of its own, so text redaction of the joined
    command line cannot recognize it; the value is replaced here. The
    `--option=value` form stays a single element and is covered by the
    text redaction (redact_secrets) every consumer applies afterwards."""
    redacted: list[str] = []
    redact_next = False
    for part in argv or ():
        text = str(part)
        if redact_next:
            redacted.append("[REDACTED]")
            redact_next = False
            continue
        redacted.append(text)
        redact_next = "=" not in text and _SECRET_OPTION.fullmatch(text) is not None
    return tuple(redacted)


def redact_secrets(text: str) -> str:
    """Public entry point of the central value redaction (whole text, no
    truncation) for any component that hands text to an LLM, log or
    report outside the DiagnosticTrace store."""
    return _redact(text)


def _redact_bounded(value: str, limit: int) -> str:
    """Redact FIRST, then keep at most `limit` characters.

    Only a window of limit + 512 characters is scanned -- the rest is
    discarded anyway. Safety at every cut position rests on two facts:
    a secret that can survive into the first `limit` characters has its
    name/prefix inside the window (the margin covers the longest name),
    and every recognizer is terminator-independent (see _SECRET_VALUE), so
    a value whose end lies beyond the window is redacted to the window
    end. Truncating already redacted text can only remove characters."""
    if limit <= 0:
        return ""
    return _redact(value[:limit + 512])[:limit]


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


class DiagnosticDetailLevel(str, Enum):
    """Presentation depth for safe central DiagnosticTrace projections.

    NONE suppresses diagnostic presentation without affecting required
    business/audit trace collection. Workflow behaviour is unchanged.
    """

    NONE = "NONE"
    NORMAL = "NORMAL"
    INFO = "INFO"
    VERBOSE = "VERBOSE"
    VERY_VERBOSE = "VERY_VERBOSE"


_DIAGNOSTIC_DETAIL_RANK = {
    DiagnosticDetailLevel.NONE: -1,
    DiagnosticDetailLevel.NORMAL: 0,
    DiagnosticDetailLevel.INFO: 1,
    DiagnosticDetailLevel.VERBOSE: 2,
    DiagnosticDetailLevel.VERY_VERBOSE: 3,
}

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
        safe_details = _safe_details(details or {})
        return self.store.append({
            "run_id": run_id,
            "phase": phase,
            "event_type": event_type,
            "status": status,
            "summary": _redact_bounded(summary, 500),
            "source": _redact_bounded(str(source), 100),
            "details": safe_details,
            "related_result_id": _redact_bounded(related_result_id, 200) if related_result_id else None,
        })

    def get_trace(self, run_id: str) -> tuple[DiagnosticTraceEvent, ...]:
        return self.store.read(run_id)

    @staticmethod
    def _safe_value(value, budget=None):
        """Redacted, bounded simple detail value (scalar or flat list)."""
        if budget is None:
            budget = _Budget(_STRUCTURED_DETAIL_BUDGET)
        if isinstance(value, (list, tuple)):
            safe = []
            budget.spend(2)
            for item in value[:50]:
                if not (isinstance(item, (str, bool, int, float)) or item is None):
                    continue
                if budget.exhausted:
                    safe.append(budget.marker())
                    break
                if safe:
                    budget.spend(2)  # ", "
                safe.append(DiagnosticTrace._safe_scalar(item, budget, 3000))
            return safe
        if isinstance(value, (str, bool, int, float)) or value is None:
            return DiagnosticTrace._safe_scalar(value, budget, 3000)
        return budget.charge("[UNSUPPORTED]")

    @staticmethod
    def _safe_scalar(value, budget, string_cap):
        """One leaf, charged at its serialized JSON size (strings, numbers,
        booleans and nulls alike). Strings are redacted BEFORE they are cut
        to the remaining budget."""
        if isinstance(value, str):
            room = min(string_cap, budget.remaining - 2)
            if room <= 0:
                return budget.marker()
            text = _redact_bounded(value, room)
            cost = _json_size(text)
            while cost > budget.remaining and text:
                # JSON escaping can make text longer than its character count.
                text = text[:max(0, len(text) - (cost - budget.remaining) - 1)]
                cost = _json_size(text)
            budget.spend(cost)
            return text
        if isinstance(value, bool) or value is None:
            return budget.charge(value)
        if isinstance(value, int) and value.bit_length() > 64:
            return budget.marker()
        if isinstance(value, (int, float)):
            return budget.charge(value)
        return budget.charge("[UNSUPPORTED]")

    @staticmethod
    def _safe_council_output(value, depth=0, budget=None):
        """Recursively allowlisted, redacted and bounded structured detail.

        Projection-level keys (normal/info/verbose/very_verbose) must
        hold a structured mapping -- free text directly at a level is
        dropped, never persisted as an unreviewed response/source blob.
        Every string is value-redacted before it is bounded. One structured
        detail value has a TOTAL budget of _STRUCTURED_DETAIL_BUDGET
        serialized JSON characters: every key, every container, and every
        leaf -- string, number, boolean or null -- is charged, so a
        numeric/boolean/key-heavy fan-out is bounded exactly like text.
        """
        if budget is None:
            budget = _Budget(_STRUCTURED_DETAIL_BUDGET)
        if budget.exhausted:
            return budget.marker()
        if depth > 10:
            # Only this branch is cut; the remaining budget stays available.
            return budget.charge(_Budget._MARKER)
        if isinstance(value, dict):
            safe = {}
            budget.spend(2)
            for key, item in list(value.items())[:80]:
                key = str(key)
                if key not in COUNCIL_OUTPUT_KEYS or key in FORBIDDEN_COUNCIL_OUTPUT_KEYS:
                    continue
                if key in _PROJECTION_LEVEL_KEYS and not isinstance(item, dict):
                    continue
                if budget.exhausted:
                    safe["truncated"] = budget.marker()
                    break
                budget.spend(_json_size(key) + 2 + (2 if safe else 0))  # key ": " and ", "
                safe[key] = DiagnosticTrace._safe_council_output(item, depth + 1, budget)
            return safe
        if isinstance(value, (list, tuple)):
            safe = []
            budget.spend(2)
            for item in value[:50]:
                if budget.exhausted:
                    safe.append(budget.marker())
                    break
                if safe:
                    budget.spend(2)  # ", "
                safe.append(DiagnosticTrace._safe_council_output(item, depth + 1, budget))
            return safe
        if isinstance(value, (str, bool, int, float)) or value is None:
            return DiagnosticTrace._safe_scalar(value, budget, 3000)
        return budget.charge("[UNSUPPORTED]")


def _json_size(value) -> int:
    return len(json.dumps(value, ensure_ascii=False))


class _Budget:
    """Remaining serialized-JSON characters for one bounded detail value."""

    _MARKER = "[TRUNCATED]"

    def __init__(self, total: int):
        self.total = total
        self.remaining = total

    @property
    def exhausted(self) -> bool:
        return self.remaining <= 0

    @property
    def used(self) -> int:
        return self.total - self.remaining

    def spend(self, cost: int) -> None:
        self.remaining -= cost

    def charge(self, value):
        """Keep `value` if it fits the remaining budget, else the marker."""
        cost = _json_size(value)
        if cost > self.remaining:
            return self.marker()
        self.remaining -= cost
        return value

    def marker(self) -> str:
        # One marker per exhausted container: small, fixed overhead.
        self.remaining = min(self.remaining, 0)
        return self._MARKER


_STRUCTURED_DETAIL_KEYS = frozenset({"council_output", "interface_data", "execution_identity", "council_lifecycle"})


def _bounded_detail(key: str, value, room: int):
    """One allowlisted detail value whose serialized JSON size is MEASURED
    to be at most `room` characters, or None if that is impossible. The
    budget accounting is only the construction heuristic; the bound itself
    rests on the exact measurement (rebuild with a smaller budget on
    overrun)."""
    budget_size = room
    for _ in range(6):
        if budget_size < 16:
            return None
        budget = _Budget(budget_size)
        safe = (
            DiagnosticTrace._safe_council_output(value, budget=budget)
            if key in _STRUCTURED_DETAIL_KEYS
            else DiagnosticTrace._safe_value(value, budget=budget)
        )
        size = _json_size(safe)
        if size <= room:
            return safe
        budget_size -= (size - room) + 64
    return None


# Serialized size of the event-level marker added when details were dropped.
_TRUNCATED_FLAG_COST = len(', "truncated": true')


def _safe_details(details: dict) -> dict:
    """Allowlisted, redacted details with a real TOTAL size bound per event.

    The returned mapping serializes (json.dumps, default separators,
    ensure_ascii=False -- exactly as persisted) to at most
    _EVENT_DETAIL_BUDGET characters, whatever its leaves are (strings,
    numbers, booleans, nulls, keys, nesting). Simple values come first
    (counters, identities, error metadata -- the most useful and the
    cheapest), then structured projections. Each value is additionally
    capped (3000 characters per string, _STRUCTURED_DETAIL_BUDGET per
    value); a value that no longer fits is dropped and the event is marked
    `truncated`.
    """
    ordered = sorted(
        (key for key in details if key in DETAIL_KEYS),
        key=lambda key: (key in _STRUCTURED_DETAIL_KEYS, key == "effective_prompt"),
    )
    limit = _EVENT_DETAIL_BUDGET - _TRUNCATED_FLAG_COST
    safe, used, truncated = {}, 2, False  # 2 = "{}"
    for key in ordered:
        overhead = _json_size(key) + 2 + (2 if safe else 0)  # key ": " and ", "
        room = min(_STRUCTURED_DETAIL_BUDGET, limit - used - overhead)
        value = _bounded_detail(key, details[key], room) if room >= 16 else None
        if value is None:
            truncated = True
            continue
        safe[key] = value
        used += overhead + _json_size(value)
    if truncated:
        safe["truncated"] = True
    return safe


# Structured detail projections: which keys denote a presentation level,
# and the total string budget of one structured detail value.
_PROJECTION_LEVEL_KEYS = frozenset({"normal", "info", "verbose", "very_verbose"})
_STRUCTURED_DETAIL_BUDGET = 20000
# Total serialized size of all details of one event (see _safe_details).
_EVENT_DETAIL_BUDGET = 40000


_COUNCIL_PHASE_LABELS = {
    "phase1": "Phase 1 — Proposals",
    "phase2": "Phase 2 — Reviews",
    "phase3": "Phase 3 — Chairman",
}


def _terminal_safe_details(details: dict) -> dict:
    """Reapply the central allowlists, redaction and budgets; never
    serialize an unrestricted mapping (rendering can only show less than
    was persisted, never more)."""
    return _safe_details(details)


def _terminal_projection(mapping: dict, level: DiagnosticDetailLevel) -> dict:
    preferred = {
        DiagnosticDetailLevel.INFO: ("info", "normal"),
        DiagnosticDetailLevel.VERBOSE: ("verbose", "info", "normal"),
        DiagnosticDetailLevel.VERY_VERBOSE: (
            "very_verbose", "verbose", "info", "normal",
        ),
    }.get(level, ())
    for key in preferred:
        value = mapping.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _terminal_fields(mapping: dict, keys: tuple[str, ...]) -> str:
    parts = []
    for key in keys:
        if key not in mapping or mapping[key] is None or mapping[key] == "":
            continue
        value = mapping[key]
        if isinstance(value, (dict, list)):
            rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
        else:
            rendered = str(value)
        parts.append(f"{key}={rendered}")
    return " ".join(parts)


def render_diagnostic_trace_event(
    event: DiagnosticTraceEvent,
    detail_level: DiagnosticDetailLevel | str = DiagnosticDetailLevel.NORMAL,
) -> str:
    """Return a non-persisting, human-readable projection of one safe event."""
    try:
        level = (
            detail_level
            if isinstance(detail_level, DiagnosticDetailLevel)
            else DiagnosticDetailLevel(str(detail_level).upper())
        )
    except ValueError as error:
        raise ValueError("Unsupported diagnostic detail level") from error

    if level == DiagnosticDetailLevel.NONE:
        return ""

    details = _terminal_safe_details(event.details or {})
    base = [event.phase]
    council_phase = details.get("council_phase")
    if council_phase in _COUNCIL_PHASE_LABELS:
        base.append(_COUNCIL_PHASE_LABELS[council_phase])
    actor = details.get("actor")
    if actor:
        role = details.get("actor_role")
        base.append(f"{actor} ({role})" if role else str(actor))
    base.append(f"status={event.status}")
    runtime_state = details.get("runtime_state")
    if runtime_state:
        base.append(f"activity={runtime_state}")
    base.append(_redact_bounded(event.summary, 500))
    lines = ["[TRACE] " + " | ".join(base)]

    if _DIAGNOSTIC_DETAIL_RANK[level] >= _DIAGNOSTIC_DETAIL_RANK[DiagnosticDetailLevel.INFO]:
        interface = details.get("interface_data")
        projection = _terminal_projection(interface, level) if isinstance(interface, dict) else {}
        endpoint_keys = ("type", "interface")
        if _DIAGNOSTIC_DETAIL_RANK[level] >= _DIAGNOSTIC_DETAIL_RANK[DiagnosticDetailLevel.VERBOSE]:
            endpoint_keys += ("source", "destination", "data")
        for key, label in (("x", "x — Input"), ("f", "f — Processor"), ("y", "y — Output")):
            value = projection.get(key)
            if not isinstance(value, dict):
                continue
            keys = endpoint_keys if key != "f" else (
                "entity", "entity_version", "implementation_version",
                "provider", "model", "model_version", "actor", "phase",
            )
            rendered = _terminal_fields(value, keys)
            if rendered:
                lines.append(f"[TRACE]   {label}: {rendered}")

    if _DIAGNOSTIC_DETAIL_RANK[level] >= _DIAGNOSTIC_DETAIL_RANK[DiagnosticDetailLevel.VERBOSE]:
        context = _terminal_fields(
            details,
            ("provider", "model", "duration_ms", "actor_role", "council_phase"),
        )
        if context:
            lines.append(f"[TRACE]   Context: {context}")
        identity = details.get("execution_identity")
        if isinstance(identity, dict):
            rendered = _terminal_fields(
                identity,
                ("entity", "entity_version", "implementation_version", "provider",
                 "model", "model_version", "actor", "phase"),
            )
            if rendered:
                lines.append(f"[TRACE]   Execution: {rendered}")

    council_output = details.get("council_output")
    if isinstance(council_output, dict) and level != DiagnosticDetailLevel.NORMAL:
        projection = _terminal_projection(council_output, level)
        if projection:
            lines.append(
                "[TRACE]   Council: "
                + json.dumps(projection, ensure_ascii=False, sort_keys=True)
            )

    if _DIAGNOSTIC_DETAIL_RANK[level] >= _DIAGNOSTIC_DETAIL_RANK[DiagnosticDetailLevel.VERY_VERBOSE]:
        effective_prompt = details.get("effective_prompt")
        if isinstance(effective_prompt, str) and effective_prompt.strip():
            lines.append(
                "[TRACE]   Effective-Prompt: "
                + _redact_bounded(effective_prompt, 3000)
            )

    return "\n".join(lines)
