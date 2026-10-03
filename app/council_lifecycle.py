"""Council lifecycle infrastructure (SUB_REQ_033 through SUB_REQ_040).

CLAUDE-ADC-COUNCIL-APPROVED-ARCHITECTURE-027. This module holds the parts of
the approved Council lifecycle contract that are independent of Council
deliberation itself:

* CouncilOperatingProfile -- the finite time/resource profile an evaluate()
  declares before admission (SUB_REQ_039). All values are PROVISIONAL
  development/synthetic values; none is an approved operating profile.
* HandoverGate / gated_session -- the actual request handover boundary of
  the supported HTTP provider bindings (SUB_REQ_033): the first request byte
  written to the provider-bound socket, decided atomically with closure.
* CouncilDiagnosisRegistry -- bounded, callback-independent volatile
  retrieval of critical Council diagnosis with reservation before admission
  (SUB_REQ_035, SUB_REQ_036, SUB_REQ_038).
* PersistenceWriter -- confirmed durable storage (fsync) that never extends
  the public deadline; storage state is reported separately (SUB_REQ_036).
"""

from __future__ import annotations

import copy
import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import requests
import urllib3.connection
import urllib3.connectionpool
from requests.adapters import HTTPAdapter

from app.council_error import CouncilFailedError

_MIB = 1024 * 1024


class CouncilResourceError(CouncilFailedError):
    """Admission refused: a finite Council resource is exhausted. No
    provider work was started (SUB_REQ_036, SUB_REQ_038)."""


class HandoverRefused(requests.exceptions.ConnectionError):
    """The gate refused an actual request handover: the invocation is
    closed or its request budget is spent. Nothing left local preparation."""


class TransportBoundaryUnsupported(requests.exceptions.ConnectionError):
    """The transport cannot expose the documented handover boundary, so the
    request is refused instead of being sent without the guarantee."""


# ---------------------------------------------------------------------------
# Operating profile (SUB_REQ_039)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CouncilOperatingProfile:
    """PROVISIONAL, configurable Council operating profile.

    Development and synthetic-validation values only; the numeric profile
    requires separate approval. Contributor/chairman call budgets are not
    fixed here: they derive from each agent's configured timeout and the
    attempt count (see engineering_council._outer_deadline)."""

    preparation_seconds: float = 5.0
    finalization_seconds: float = 5.0
    # Only for judging measurements; never added to any work budget.
    measurement_tolerance_seconds: float = 1.0
    # Chairman calls a phase-3 budget covers: synthesis, one bounded repair,
    # one admissibility rework (SUB_REQ_004 / existing Council flow).
    phase3_chairman_calls: int = 3
    # Actual request handovers per contributor call, automatic transport
    # retries included (SUB_REQ_033). Equals the Council attempt count.
    handovers_per_call: int = 2
    # Bound for the one socket write that makes a handover; the closure of
    # an invocation waits at most this long for a handover in progress.
    handover_send_timeout_seconds: float = 1.0
    worker_capacity: int = 16
    notifier_capacity: int = 64
    subscription_pending_limit: int = 32
    delivery_stall_seconds: float = 0.1
    diagnosis_pool_bytes: int = 64 * _MIB
    # One envelope holds a Council's critical record AND its service-held
    # call records (SUB_REQ_036). Measured (029, 132 synthetic Councils):
    # record <=5.1 KB, retained call records <=7.6 KB, together <=12.3 KB,
    # i.e. >5x headroom. The byte worst case (27 records with 4-byte UTF-8
    # texts, ~227 KB) does not fit; instead of exceeding the reservation the
    # retained record texts are then visibly compacted (see
    # EngineeringCouncil._fit_retained). 64 MiB / 64 KiB = 1024 Councils per
    # retention hour. PROVISIONAL.
    diagnosis_envelope_bytes: int = 64 * 1024
    volatile_retention_seconds: float = 3600.0
    persistence_slots: int = 8

    def declare(self, call_budgets: dict[str, float]) -> dict[str, Any]:
        """The finite profile of one evaluate(), declared before admission.
        `call_budgets`: per-phase single-call budget in seconds."""
        phases = {
            "phase1": call_budgets["phase1"],
            "phase2": call_budgets["phase2"],
            "phase3": call_budgets["phase3"] * self.phase3_chairman_calls,
        }
        total = (self.preparation_seconds + sum(phases.values())
                 + self.finalization_seconds)
        return {
            "provisional": True,
            "preparation_seconds": self.preparation_seconds,
            "phase_seconds": phases,
            "finalization_seconds": self.finalization_seconds,
            "public_total_seconds": total,
            "measurement_tolerance_seconds": self.measurement_tolerance_seconds,
            "handovers_per_call": self.handovers_per_call,
            # 3 contributors in phases 1 and 2, the phase-3 chairman calls.
            "max_handovers": self.handovers_per_call * (3 + 3 + self.phase3_chairman_calls),
            "worker_capacity": self.worker_capacity,
            "notifier_capacity": self.notifier_capacity,
            "subscription_pending_limit": self.subscription_pending_limit,
            "diagnosis_envelope_bytes": self.diagnosis_envelope_bytes,
            "diagnosis_pool_bytes": self.diagnosis_pool_bytes,
            "volatile_retention_seconds": self.volatile_retention_seconds,
            "persistence_slots": self.persistence_slots,
        }


DEFAULT_PROFILE = CouncilOperatingProfile()


# ---------------------------------------------------------------------------
# Actual request handover (SUB_REQ_033, SUB_REQ_034)
# ---------------------------------------------------------------------------

# The documented boundary of the gated HTTP bindings (OpenRouter, Ollama):
HANDOVER_BOUNDARY = (
    "first byte of an HTTP request written to the provider-bound socket "
    "(OS send buffer); connection setup, TLS handshake and proxy CONNECT "
    "are not a handover; every request on the wire, automatic transport "
    "retries included, passes the gate"
)
UNVERIFIED_BOUNDARY = "unverified: provider binding exposes no handover boundary"


class HandoverGate:
    """Decides every actual request handover of one contributor invocation.

    `lock` is the invocation's lifecycle lock: closing the invocation takes
    the same lock, so "closed?" + "first request byte leaves" is atomic with
    respect to closure. The lock is held only for that one socket write,
    whose timeout never reaches past the invocation's deadline (see
    send_timeout): closure at the deadline therefore never waits beyond it.
    After closure no handover begins; a handover that began before closure
    may still be transmitted and processed remotely.

    Remote state per handover (SUB_REQ_034): "uncertain" until a response
    arrives; then "accepted" for a 2xx status, "rejected" for any other
    status. A transport response is never itself counted as acceptance."""

    def __init__(
        self, lock: threading.Lock, is_closed: Callable[[], bool], budget: int,
        deadline: Callable[[], float] | None = None,
    ):
        self._lock = lock
        self._is_closed = is_closed
        self._deadline = deadline
        self.budget = budget
        self.handovers: list[dict[str, Any]] = []
        self.refused: list[str] = []

    def send_timeout(self, configured: float) -> float | None:
        """Timeout for the gated first write: the configured bound, cut to
        the time left before the invocation's deadline. None if no time is
        left (the caller then refuses without writing)."""
        if self._deadline is None:
            return configured
        remaining = self._deadline() - time.monotonic()
        if remaining <= 0:
            return None
        return min(configured, remaining)

    def hand_over(self, send_first: Callable[[], None]) -> None:
        with self._lock:
            if self._is_closed() or (
                    self._deadline is not None and time.monotonic() >= self._deadline()):
                self.refused.append("closed")
                raise HandoverRefused("invocation closed: no new request handover")
            if len(self.handovers) >= self.budget:
                self.refused.append("budget")
                raise HandoverRefused("request handover budget exhausted")
            record = {"at": time.monotonic(), "remote": "uncertain"}
            try:
                send_first()
            except HandoverRefused:
                self.refused.append("closed")  # nothing was written
                raise
            except BaseException:
                # Nothing or an unknown part left: still counted, uncertain.
                record["send"] = "failed"
                self.handovers.append(record)
                raise
            self.handovers.append(record)

    def response_received(self, status: int) -> None:
        """Record the transport response of the latest handover. Only a 2xx
        status is provider acceptance; any other status (e.g. 401, 429,
        503, possibly from a proxy) is an explicit rejection."""
        with self._lock:
            if self.handovers:
                self.handovers[-1]["status"] = int(status)
                self.handovers[-1]["remote"] = "accepted" if 200 <= int(status) < 300 else "rejected"

    def summary(self) -> dict[str, Any]:
        """Caller holds the invocation lock."""
        remote = [h["remote"] for h in self.handovers]
        return {
            "boundary": "transport",
            "handovers": len(self.handovers),
            "transport_responses": sum(1 for h in self.handovers if "status" in h),
            "remote_confirmed": remote.count("accepted"),
            "remote_rejected": remote.count("rejected"),
            "remote_uncertain": remote.count("uncertain"),
            "refused_after_close": self.refused.count("closed"),
            "refused_budget": self.refused.count("budget"),
        }


class _GatedConnectionMixin:
    """urllib3 connection whose first request write goes through the gate."""

    _adc_gate: HandoverGate
    _adc_send_timeout: float
    _adc_pending = False

    def request(self, method, url, body=None, headers=None, **kwargs):  # noqa: D401
        if self.sock is None:
            # Connection setup (TCP, TLS, proxy CONNECT) sends no request
            # data; doing it here keeps it outside the gated write.
            self.connect()
        self._adc_pending = True
        try:
            return super().request(method, url, body=body, headers=headers, **kwargs)
        finally:
            self._adc_pending = False

    def send(self, data):
        if not self._adc_pending:
            return super().send(data)
        self._adc_pending = False
        if not isinstance(data, (bytes, bytearray)) or not data:
            raise TransportBoundaryUnsupported("unexpected first request chunk")
        base = super()
        sock = self.sock

        def send_first() -> None:
            timeout = self._adc_gate.send_timeout(self._adc_send_timeout)
            if timeout is None:
                raise HandoverRefused("invocation deadline reached before the first write")
            previous = sock.gettimeout()
            sock.settimeout(timeout)
            try:
                base.send(bytes(data[:1]))
            finally:
                sock.settimeout(previous)

        self._adc_gate.hand_over(send_first)
        if len(data) > 1:
            base.send(bytes(data[1:]))

    def getresponse(self, *args, **kwargs):
        response = super().getresponse(*args, **kwargs)
        self._adc_gate.response_received(response.status)
        return response


class _GatedAdapter(HTTPAdapter):
    def __init__(self, gate: HandoverGate, send_timeout: float):
        attrs = {"_adc_gate": gate, "_adc_send_timeout": send_timeout}
        http_conn = type("GatedHTTPConnection",
                         (_GatedConnectionMixin, urllib3.connection.HTTPConnection), attrs)
        https_conn = type("GatedHTTPSConnection",
                          (_GatedConnectionMixin, urllib3.connection.HTTPSConnection), attrs)
        self._pool_classes = {
            "http": type("GatedHTTPConnectionPool",
                         (urllib3.connectionpool.HTTPConnectionPool,), {"ConnectionCls": http_conn}),
            "https": type("GatedHTTPSConnectionPool",
                          (urllib3.connectionpool.HTTPSConnectionPool,), {"ConnectionCls": https_conn}),
        }
        # No automatic transport retries: each would be a separate handover
        # that must consume the budget; the gate enforces that as well.
        super().__init__(max_retries=0)

    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = dict(self._pool_classes)

    def proxy_manager_for(self, proxy, **proxy_kwargs):
        manager = super().proxy_manager_for(proxy, **proxy_kwargs)
        if proxy.lower().startswith("socks"):
            raise TransportBoundaryUnsupported("SOCKS proxies expose no handover boundary")
        manager.pool_classes_by_scheme = dict(self._pool_classes)
        return manager


def gated_session(gate: HandoverGate, send_timeout: float) -> requests.Session:
    """A requests session whose every HTTP(S) request passes `gate`."""
    session = requests.Session()
    adapter = _GatedAdapter(gate, send_timeout)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def bind_handover_gate(provider: Any, gate: HandoverGate, send_timeout: float) -> bool:
    """Route every request of a supported provider binding through `gate`.

    Supported: exactly the HTTP bindings the Council factory creates --
    OpenRouterLLMProvider (requests session) and OllamaAdapter (its
    OllamaClient session). Exact type match, so a subclass or test double
    with a different transport never gets a guarantee it does not have.
    Returns False for any other binding (UNVERIFIED_BOUNDARY)."""
    from app.ollama_adapter import OllamaAdapter
    from app.openrouter_llm_provider import OpenRouterLLMProvider

    if type(provider) is OpenRouterLLMProvider:
        previous = provider._session
        provider._session = gated_session(gate, send_timeout)
        previous.close()
        return True
    if type(provider) is OllamaAdapter:
        provider._client.session = gated_session(gate, send_timeout)
        return True
    return False


# ---------------------------------------------------------------------------
# Callback-independent critical diagnosis (SUB_REQ_035, SUB_REQ_036)
# ---------------------------------------------------------------------------


def _size(value: Any) -> int:
    """Exact UTF-8 byte size of the serialized record (the unit the
    reservation is accounted in)."""
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8"))


def _redact_tree(value: Any) -> Any:
    """Apply the central secret redaction to every string of a record."""
    from app.diagnostic_trace import redact_secrets

    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, dict):
        return {key: _redact_tree(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_tree(item) for item in value]
    return value


_CORE_FIELDS = ("run_id", "result_id", "state", "persistence", "omitted", "size_exceeded")
_TRUNCATION_MARK = "...[truncated: exceeds diagnosis reservation]"


def _shorten_strings(value: Any, limit: int, path: str, cut: list[str]) -> Any:
    """Cut strings longer than `limit`, each visibly marked and named."""
    if isinstance(value, str):
        if len(value) > limit:
            cut.append(path)
            return value[:limit] + _TRUNCATION_MARK
        return value
    if isinstance(value, dict):
        return {k: _shorten_strings(v, limit, f"{path}.{k}", cut) for k, v in value.items()}
    if isinstance(value, list):
        return [_shorten_strings(v, limit, f"{path}[]", cut) for v in value]
    return value


class CouncilDiagnosisRegistry:
    """Process-wide, bounded volatile retrieval of critical Council diagnosis.

    Admission reserves a fixed envelope per Council before any provider
    handover. A record never grows beyond its envelope: an overflow keeps
    the mandatory core and names what was not retained. Records are kept
    for the retention period after completion while the service runs and
    are never evicted early; when the pool is exhausted, new admissions are
    refused. Pending persistence payloads are charged to the same pool.

    Ownership (CLAUDE-ADC-RESOURCE-OWNERSHIP-ADMISSION-FIX-031): the end of
    the retention period ends public retrieval of a record, not the charge
    of data the service still holds in the run's envelope. Every holder of
    envelope data (the Council instance for its call records, a fail-closed
    result) takes a hold; an expired record whose envelope is still held
    stays charged until its last hold is released. Data outside the
    envelope is charged with reserve_extra() by its own owner and released
    by that owner when the data is dropped."""

    def __init__(self, pool_bytes: int, envelope_bytes: int, retention_seconds: float):
        self.pool_bytes = pool_bytes
        self.envelope_bytes = envelope_bytes
        self.retention_seconds = retention_seconds
        self._lock = threading.Lock()
        self._records: dict[str, dict[str, Any]] = {}
        self._aliases: dict[str, str] = {}
        self._extra = 0
        # run id -> number of live holds on its envelope.
        self._holds: dict[str, int] = {}
        # Envelopes whose record expired while still held: still charged.
        self._detached: set[str] = set()

    def _expire_locked(self, now: float) -> None:
        for run_id, record in list(self._records.items()):
            expires = record.get("_expires_at")
            if expires is not None and expires <= now:
                del self._records[run_id]
                for alias in [a for a, r in self._aliases.items() if r == run_id]:
                    del self._aliases[alias]
                if self._holds.get(run_id):
                    self._detached.add(run_id)

    def _used_locked(self) -> int:
        envelopes = len(self._records) + len(self._detached)
        return envelopes * self.envelope_bytes + self._extra

    def hold(self, run_id: str) -> Callable[[], None] | None:
        """Take a hold on the envelope of `run_id` for data its caller keeps
        service-held. Returns the idempotent release, or None if the record
        is unknown (nothing is charged then, so nothing may be kept)."""
        with self._lock:
            if run_id not in self._records and run_id not in self._detached:
                return None
            self._holds[run_id] = self._holds.get(run_id, 0) + 1
        released = [False]

        def release() -> None:
            with self._lock:
                if released[0]:
                    return
                released[0] = True
                remaining = self._holds.get(run_id, 0) - 1
                if remaining > 0:
                    self._holds[run_id] = remaining
                    return
                self._holds.pop(run_id, None)
                self._detached.discard(run_id)

        return release

    def discard(self, run_id: str) -> None:
        """Undo an admission whose run never started (e.g. the run thread
        could not be created): nothing was recorded or handed over, so the
        reservation is returned instead of being kept for retention."""
        with self._lock:
            if self._holds.get(run_id):
                return  # still held: stays charged until released
            self._records.pop(run_id, None)
            for alias in [a for a, r in self._aliases.items() if r == run_id]:
                del self._aliases[alias]

    def admit(self, run_id: str, profile: dict[str, Any]) -> None:
        with self._lock:
            self._expire_locked(time.monotonic())
            if self._used_locked() + self.envelope_bytes > self.pool_bytes:
                raise CouncilResourceError(
                    "Council diagnosis capacity exhausted: admission refused "
                    "before any provider handover"
                )
            self._records[run_id] = {
                "run_id": run_id, "result_id": None, "state": "running",
                "profile": profile, "invocations": {}, "late_additions": [],
                "omitted": [], "persistence": {"state": "not_requested"},
                "notifications": {}, "resource_errors": [],
            }

    def reserve_extra(self, nbytes: int) -> bool:
        with self._lock:
            if self._used_locked() + nbytes > self.pool_bytes:
                return False
            self._extra += nbytes
            return True

    def release_extra(self, nbytes: int) -> None:
        with self._lock:
            self._extra -= nbytes

    def update(self, run_id: str, change: Callable[[dict[str, Any]], None]) -> None:
        with self._lock:
            record = self._records.get(run_id)
            if record is None:
                return
            change(record)
            redacted = _redact_tree({k: v for k, v in record.items() if not k.startswith("_")})
            record.update(redacted)
            self._fit_locked(record)
            if record.get("result_id"):
                self._aliases[record["result_id"]] = run_id

    def complete(self, run_id: str) -> None:
        with self._lock:
            record = self._records.get(run_id)
            if record is not None:
                record["state"] = "completed"
                record["_expires_at"] = time.monotonic() + self.retention_seconds

    def _fit_locked(self, record: dict[str, Any]) -> None:
        """Keep the record within its reserved envelope, measured in exact
        UTF-8 bytes, without silent loss: every reduction is named in
        `omitted` and marks the record `size_exceeded`. Reduction order:
        optional data first, then visibly marked cuts of long strings, then
        whole non-core fields. The core (run and result identity, state,
        persistence, the omission list) always remains."""
        # Service-held retained data of the run (its call records) is charged
        # to the same envelope; the critical record gets the rest.
        retained = record.get("_retained_bytes", 0) + record.get("_retained_result_bytes", 0)
        limit = self.envelope_bytes - retained
        if retained > self.envelope_bytes:
            record["resource_errors"].append(
                f"retained run data ({retained} bytes) exceeds the diagnosis reservation")

        def note(name: str) -> None:
            if name not in record["omitted"]:
                record["omitted"].append(name)
            record["size_exceeded"] = True

        if _size(record) <= limit:
            return
        while record["late_additions"] and _size(record) > limit:
            record["late_additions"].pop()
            note("late_additions")
        for field in ("notifications", "profile"):
            if _size(record) > limit and record.get(field):
                record[field] = {}
                note(field)
        for cap in (2000, 500, 100):
            if _size(record) <= limit:
                break
            for field in ("outcome", "resource_errors", "invocations"):
                cut: list[str] = []
                record[field] = _shorten_strings(record.get(field), cap, field, cut)
                for path in sorted(set(cut)):
                    note(f"truncated:{path}")
        for field in ("invocations", "resource_errors", "outcome", "late_additions"):
            if _size(record) <= limit:
                break
            record[field] = {} if isinstance(record.get(field), dict) else []
            note(field)
        if _size(record) > limit:
            # Only the omission list itself can still be too long.
            record["omitted"] = record["omitted"][:20] + ["...further omissions not listed"]
        if _size(record) > limit:
            for key in list(record):
                if key not in _CORE_FIELDS:
                    del record[key]
            record["omitted"] = ["all non-core diagnosis"]
            record["size_exceeded"] = True

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            self._expire_locked(time.monotonic())
            record = self._records.get(self._aliases.get(key, key))
            if record is None:
                return None
            snapshot = copy.deepcopy(record)
        for key in [key for key in snapshot if key.startswith("_")]:
            del snapshot[key]
        return snapshot

    def stats(self) -> dict[str, int]:
        with self._lock:
            self._expire_locked(time.monotonic())
            return {"records": len(self._records), "used_bytes": self._used_locked(),
                    "pool_bytes": self.pool_bytes, "envelope_bytes": self.envelope_bytes,
                    "held_after_retention": len(self._detached),
                    "extra_bytes": self._extra}


# ---------------------------------------------------------------------------
# Confirmed persistence (SUB_REQ_036)
# ---------------------------------------------------------------------------


class PersistenceWriter:
    """Durable writes on bounded background slots. A slot is reserved at
    admission, so a blocked store refuses new Councils before any provider
    handover instead of accumulating writers without bound."""

    def __init__(self, slots: int):
        self.slots = slots
        self._lock = threading.Lock()
        self._busy = 0

    def reserve(self) -> bool:
        with self._lock:
            if self._busy >= self.slots:
                return False
            self._busy += 1
            return True

    def release(self) -> None:
        with self._lock:
            self._busy -= 1

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"busy": self._busy, "slots": self.slots}

    def write(self, path: Path, payload: bytes | list, on_done: Callable[[str, str | None], None]) -> None:
        """Write on the caller's reserved slot; `on_done(state, error)` with
        state "confirmed" (fsync'ed file and directory) or "failed". The
        slot is released when the write actually ends.

        `payload` may be handed over in a one-item list, which the writer
        empties: then the writer holds the only service reference and drops
        it before `on_done`, so a caller releasing the payload's charge
        there releases it after its actual last use."""
        if isinstance(payload, list):
            held = [payload.pop()]
        else:
            held = [payload]
        del payload

        def run() -> None:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_name(path.name + ".tmp")
                with tmp.open("wb") as handle:
                    handle.write(held.pop())
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp, path)
                directory = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            except BaseException as exc:  # reported, never raised
                held.clear()
                self.release()
                on_done("failed", type(exc).__name__)
                return
            self.release()
            on_done("confirmed", None)

        threading.Thread(target=run, name="council-persist", daemon=True).start()
