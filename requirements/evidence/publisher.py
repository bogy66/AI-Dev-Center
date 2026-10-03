"""The one reusable ADC Evidence publisher. Every testbed/bench that wants
to publish formal Evidence goes through `publish_test_evidence()` (or the
`adc-evidence publish` CLI in cli.py) -- nothing else writes into the
Evidence store, so there is exactly one place that validates, one place
that writes atomically, and one place that decides what "success" means.

Design rules this module enforces (CLAUDE-ADC-TESTBED-EVIDENCE-
INFRASTRUCTURE-001, section F/L):
  - malformed Evidence is rejected, never silently repaired or coerced
  - an unknown/invalid `result` value is never silently turned into "IO"
  - every write is atomic (temp file + os.replace), so a crash mid-write
    can never leave a half-written event or run.json behind
  - run identity and test identity are preserved exactly as given
  - failure is reported clearly; it is the CALLER's job (e.g. the pytest
    plugin) to make sure a publish failure can never be read downstream
    as a passing/verified test -- this module never fabricates success
"""
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .contract import validate_event

DEFAULT_STORE_ROOT = os.path.join(os.path.dirname(__file__), "..", "_evidence")
_RUN_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "run_schema.json")
_run_schema_cache = None


def _run_schema():
    global _run_schema_cache
    if _run_schema_cache is None:
        with open(_RUN_SCHEMA_PATH, encoding="utf-8") as f:
            _run_schema_cache = json.load(f)
    return _run_schema_cache


def _validate_run_record(record):
    import jsonschema

    validator = jsonschema.Draft7Validator(_run_schema())
    errors = sorted(validator.iter_errors(record), key=lambda e: list(e.path))
    return [f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors]


@dataclass
class PublishResult:
    success: bool
    run_id: str | None = None
    event_id: str | None = None
    event_path: str | None = None
    errors: list = field(default_factory=list)


def _store_root(store_root=None):
    root = store_root or DEFAULT_STORE_ROOT
    return os.path.abspath(root)


def _atomic_write_json(path, data):
    """Write `data` as JSON to `path` atomically: write to a sibling temp
    file in the same directory, then os.replace() it into place. On any
    OS that supports POSIX rename semantics (Linux, the ADC target
    platform) this guarantees readers never observe a partial file."""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def _run_dir(store_root, run_id):
    return os.path.join(_store_root(store_root), "runs", run_id)


def _next_event_id(run_dir, event):
    if event.get("event_id"):
        return event["event_id"]
    events_dir = os.path.join(run_dir, "events")
    existing = 0
    if os.path.isdir(events_dir):
        existing = len([n for n in os.listdir(events_dir) if n.endswith(".json")])
    return f"EVT-{existing + 1:04d}"


def _update_run_manifest(run_dir, event, event_id):
    """Create or update run.json with run-level bookkeeping, kept
    conformant to run_schema.json on every write. Never overwrites the
    run's own identity/started_at/schema_version once set, and never
    regresses a manifest already marked "completed"/"aborted" back to
    "running" just because a late event arrives."""
    manifest_path = os.path.join(run_dir, "run.json")
    manifest = {}
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)
        except (OSError, json.JSONDecodeError):
            manifest = {}

    manifest.setdefault("schema_version", "1.0")
    manifest.setdefault("run_id", event["run_id"])
    manifest.setdefault("producer", event["producer"])
    manifest.setdefault("started_at", event["timestamp_start"])
    manifest.setdefault("repository_identity", event["repository_identity"])
    manifest.setdefault(
        "environment",
        {
            "os": event.get("environment", {}).get("os", "unknown"),
            "platform": event.get("environment", {}).get("platform", "unknown"),
            "testbed": event.get("environment", {}).get("testbed", "unknown"),
            "profile": event.get("environment", {}).get("profile"),
        },
    )
    manifest.setdefault("tool_versions", event.get("tool_versions") or {})
    manifest.setdefault("command_or_procedure", event.get("command_or_procedure", ""))
    manifest.setdefault("run_status", "running")
    manifest.setdefault("completed_at", None)
    manifest.setdefault("event_ids", [])

    if event_id not in manifest["event_ids"]:
        manifest["event_ids"].append(event_id)
    manifest["event_count"] = len(manifest["event_ids"])

    errors = _validate_run_record(manifest)
    if errors:
        raise ValueError(f"run manifest failed schema validation: {errors}")

    _atomic_write_json(manifest_path, manifest)
    return manifest


def finalize_run(run_id, store_root=None, run_status="completed"):
    """Mark a run "completed" (or "aborted") and stamp completed_at.

    Called once at the end of a formal invocation (e.g. pytest's
    pytest_sessionfinish). A run with no run.json yet (e.g. zero tests
    ever reached teardown) is reported as a failure rather than silently
    fabricating one -- there is no real run to finalize.
    """
    if run_status not in ("completed", "aborted"):
        return PublishResult(success=False, run_id=run_id, errors=[f"invalid run_status: {run_status}"])

    run_dir = _run_dir(store_root, run_id)
    manifest_path = os.path.join(run_dir, "run.json")
    if not os.path.exists(manifest_path):
        return PublishResult(success=False, run_id=run_id, errors=["no run.json to finalize -- no event was ever published for this run"])

    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        return PublishResult(success=False, run_id=run_id, errors=[f"unreadable run.json: {exc}"])

    if manifest.get("run_status") in ("completed", "aborted"):
        return PublishResult(success=True, run_id=run_id, event_path=manifest_path)

    manifest["run_status"] = run_status
    manifest["completed_at"] = datetime.now(timezone.utc).isoformat()

    errors = _validate_run_record(manifest)
    if errors:
        return PublishResult(success=False, run_id=run_id, errors=errors)

    try:
        _atomic_write_json(manifest_path, manifest)
    except OSError as exc:
        return PublishResult(success=False, run_id=run_id, errors=[f"failed to finalize run: {exc}"])

    return PublishResult(success=True, run_id=run_id, event_path=manifest_path)


def publish_test_evidence(event, store_root=None):
    """Validate and durably record one Evidence event.

    Returns a PublishResult. Never raises for an ordinary validation
    failure -- callers must check `.success`. A publisher failure (schema
    violation, unwritable store, ...) must never be interpreted downstream
    as a passing/verified test; see status_model.py's leaf-state logic,
    which only ever counts a TEST_* Requirement as GREEN when a
    successfully-ingested IO result AND a linked Evidence object both
    exist -- a failed publish simply produces neither.
    """
    errors = validate_event(event)
    if errors:
        return PublishResult(success=False, run_id=event.get("run_id"), errors=errors)

    run_id = event["run_id"]
    try:
        run_dir = _run_dir(store_root, run_id)
        events_dir = os.path.join(run_dir, "events")
        event_id = _next_event_id(run_dir, event)

        to_write = dict(event)
        to_write["event_id"] = event_id

        event_path = os.path.join(events_dir, f"{event_id}.json")
        _atomic_write_json(event_path, to_write)
        _update_run_manifest(run_dir, to_write, event_id)
    except (OSError, ValueError) as exc:
        return PublishResult(
            success=False, run_id=run_id,
            errors=[f"publish failed: {exc.__class__.__name__}: {exc}"],
        )

    return PublishResult(
        success=True, run_id=run_id, event_id=event_id, event_path=event_path,
    )
