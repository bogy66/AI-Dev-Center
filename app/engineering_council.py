"""Multi-KI Engineering Council — Orchestrator.

Runs three phases with a total of 7 separate LLM calls:
  Phase 1: A1, A2, A3 in parallel → AgentProposals (3 calls, isolated)
  Phase 2: A1, A2, A3 in parallel → AgentVoteSets    (3 calls, isolated votes)
  Phase 3: Chairman sequentially → CouncilResult      (1 call)

The Council is platform-neutral.  It contains no ESP32-, ESPHome-, or
any other stack-specific logic.  All stack awareness comes from the
CouncilInput provided by the caller.
"""

from __future__ import annotations

import json
import re
import threading
import uuid
import weakref
import time
from collections import deque
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from app.ai_config import CouncilAgentConfig, CouncilConfig
from app.ai_requirement_discovery import LLMProvider
from app.council_error import (
    AgentParseError,
    CouncilChairmanError,
    CouncilFailedError,
)
from app.council_models import (
    AgentCallRecord,
    AgentProposal,
    AgentVote,
    AgentVoteSet,
    CouncilInput,
    CouncilResult,
    CouncilTrace,
    CouncilVariant,
    MergeDecision,
    ProposalSet,
    ToolchainItem,
    VerificationCoverage,
    project_identity_error,
)
from app.council_prompts import (
    AGENT_ROLE_ENV_ARCHITECT,
    AGENT_ROLE_ENV_ARCHITECT_REVIEW,
    AGENT_ROLE_RISK,
    AGENT_ROLE_RISK_REVIEW,
    AGENT_ROLE_TOOLCHAIN,
    AGENT_ROLE_TOOLCHAIN_REVIEW,
    build_phase1_prompt,
    build_phase2_review_prompt,
    build_chairman_prompt,
)
from app.llm_provider_factory import create_council_provider
from app.council_lifecycle import (
    DEFAULT_PROFILE, HANDOVER_BOUNDARY, UNVERIFIED_BOUNDARY,
    CouncilDiagnosisRegistry, CouncilResourceError, HandoverGate,
    PersistenceWriter, _redact_tree, _size, bind_handover_gate,
)
from app.logger import get_logger
from app.secret_resolver import SecretResolver
from app.execution_identity import execution_identity
from app.diagnostic_trace import _redact_bounded
from app.engineering_decision import (
    EngineeringReworkRequest,
    categorize_admissibility_reasons,
    validate_variants,
)
from app.engineering_decision import _format_candidate_evidence
from app.toolchain_materializer import ToolchainMaterializer
from app.verification import all_trusted_verification_groups

logger = get_logger("council")

AGENT_ROLES = {
    "A1": "environment_architect",
    "A2": "toolchain_integrator",
    "A3": "risk_assessor",
}

PHASE1_ROLE_PROMPTS = {
    "environment_architect": AGENT_ROLE_ENV_ARCHITECT,
    "toolchain_integrator": AGENT_ROLE_TOOLCHAIN,
    "risk_assessor": AGENT_ROLE_RISK,
}

PHASE2_ROLE_PROMPTS = {
    "environment_architect": AGENT_ROLE_ENV_ARCHITECT_REVIEW,
    "toolchain_integrator": AGENT_ROLE_TOOLCHAIN_REVIEW,
    "risk_assessor": AGENT_ROLE_RISK_REVIEW,
}

_AGENT_ID_TO_CONFIG_KEY = {
    "A1": "environment_architect",
    "A2": "toolchain_integrator",
    "A3": "risk_assessor",
}

_MAX_RETRIES = 1  # 1 initial try + 1 retry = 2 total
_CAPACITY_EXHAUSTED = "Council worker capacity {} exhausted"

# CLAUDE-ADC-E2E-VERIFICATION-EVIDENCE-FIX-001: sentinel distinguishing
# "this candidate text failed to parse" from a genuinely parsed JSON
# value of `None` (a bare `null` document) -- `is not _JSON_PARSE_FAILED`
# must be used instead of `is not None` so a legitimately parsed null
# is never mistaken for a parse failure and retried against the next
# candidate/fallback.
_JSON_PARSE_FAILED = object()
_TOTAL_RETRY_MULTIPLIER = _MAX_RETRIES + 1
_TIMEOUT_GRACE_SECONDS = 15


# CLAUDE-ADC-COUNCIL-ABANDONMENT-TRACE-HARDENING-012: a provider call that
# outlives its outer deadline cannot be interrupted, so its worker thread
# lives on until the provider returns. The pool below makes that a real,
# process-wide resource bound (an EngineeringCouncil is created per
# workflow, so a per-instance bound would not hold in a long-lived ADC
# process):
#   * at most _COUNCIL_WORKER_CAPACITY live Council worker threads exist at
#     any time -- in-flight and abandoned together;
#   * an agent slot (agent, provider, model) runs at most ONE provider call
#     at a time across all EngineeringCouncil instances of the process, so
#     concurrent instances cannot stack up several abandoned workers behind
#     the same hung provider path.
# Capacity admission is refused immediately (never waits), and so is a slot
# whose previous call was abandoned and is still running (quarantine); the
# refusal is an ordinary, observable agent failure (failure category
# "provider_quarantined"), so normal Council degradation applies.
# A slot that is merely busy with a healthy in-flight call does NOT refuse:
# the new worker waits for the slot, and that wait is bounded by its
# invocation's outer deadline -- the coordinator finalizes the invocation at
# that deadline, which ends the wait -- and ends in the quarantine refusal as
# soon as the call it waits for is abandoned.
#
# CLAUDE-ADC-COUNCIL-APPROVED-ARCHITECTURE-027 (SUB_REQ_038, SUB_REQ_040):
# accounting is exact and ownership-based. A worker is registered before its
# thread starts and is removed only by its own final release when it has
# actually ended -- there is no liveness heuristic (the former prune treated
# a thread still bootstrapping as ended and dropped an admitted worker).
# Quarantined work stays counted until it really ends; capacity refusals use
# the distinct failure category "resource_exhausted".
_COUNCIL_WORKER_CAPACITY = DEFAULT_PROFILE.worker_capacity
_SLOT_WAIT_POLL_SECONDS = 0.05
_TERMINAL_ACTIVITY_STATES = frozenset({"completed", "failed"})
_REDUNDANT_PROGRESS_STATES = frozenset({"waiting", "preparing", "reviewing"})
# Retained call records are structurally bounded (SUB_REQ_036): redacted
# error text is capped like the response snippet.
_CALL_RECORD_ERROR_CHARS = 1000
# Bound for awaiting a slot waiter that never started provider work.
_WAITER_EXIT_SECONDS = 0.05
_SLOT_QUARANTINED = "previous abandoned call of this agent is still running"


class _CouncilWorkerPool:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self._cond = threading.Condition(threading.Lock())
        self._live: dict[threading.Thread, tuple] = {}
        # Slot -> the worker whose provider call currently owns it (in
        # flight or abandoned-but-still-running).
        self._slots: dict[tuple, threading.Thread] = {}
        self._abandoned: set[threading.Thread] = set()

    def _release_locked(self, thread: threading.Thread) -> None:
        slot = self._live.pop(thread, None)
        if slot is not None and self._slots.get(slot) is thread:
            del self._slots[slot]
        self._abandoned.discard(thread)
        self._cond.notify_all()

    def admit(self, slot: tuple, thread: threading.Thread) -> str | None:
        """Reserve capacity for `thread`, or return the refusal reason."""
        with self._cond:
            if self._slots.get(slot) in self._abandoned:
                return _SLOT_QUARANTINED
            if len(self._live) >= self.capacity:
                return _CAPACITY_EXHAUSTED.format(self.capacity)
            self._live[thread] = slot
            return None

    def acquire_slot(
        self, thread: threading.Thread, cancelled: Callable[[], bool],
    ) -> str | None:
        """Worker: wait until `thread` owns its slot. Returns None once owned,
        or why it never will: the holder was abandoned (quarantine), or the
        invocation was finalized while waiting (`cancelled()`)."""
        with self._cond:
            slot = self._live[thread]
            while True:
                holder = self._slots.get(slot)
                if holder is None or holder is thread:
                    if cancelled():
                        return "invocation finalized while waiting for its agent slot"
                    self._slots[slot] = thread
                    return None
                if holder in self._abandoned:
                    return _SLOT_QUARANTINED
                if cancelled():
                    return "invocation finalized while waiting for its agent slot"
                self._cond.wait(_SLOT_WAIT_POLL_SECONDS)

    def release(self, thread: threading.Thread) -> None:
        with self._cond:
            self._release_locked(thread)

    def abandon(self, thread: threading.Thread) -> None:
        with self._cond:
            if thread in self._live:
                self._abandoned.add(thread)
            self._cond.notify_all()

    def stats(self) -> dict[str, int]:
        with self._cond:
            return {"live": len(self._live), "abandoned": len(self._abandoned),
                    "capacity": self.capacity}


_WORKER_POOL = _CouncilWorkerPool(_COUNCIL_WORKER_CAPACITY)


def council_worker_stats() -> dict[str, int]:
    """Process-wide Council worker usage: live, abandoned, capacity."""
    return _WORKER_POOL.stats()


# External notification (activity/result callbacks) -- SUB_REQ_037.
# CLAUDE-ADC-COUNCIL-APPROVED-ARCHITECTURE-027 replaces the per-task
# progress/terminal lanes of FIX018 (whose terminal lane could overtake a
# stalled progress delivery, i.e. run the same callback concurrently).
#   * One subscription = one registered callback = one _DeliveryLane. A lane
#     runs at most one callback execution at a time, in decision order, on
#     its own thread: never on the provider worker or the coordinator.
#   * A lane's pending queue is bounded. Redundant progress of one
#     invocation (waiting/preparing/reviewing) is coalesced to its newest
#     pending entry and dropped once that invocation's terminal notification
#     is queued; progress with new information is kept. Beyond the bound,
#     notifications are skipped. Skipped, failed, delivered and still
#     unconfirmed notifications are counted separately; queueing is never
#     reported as delivery.
#   * Delivery threads are bounded process-wide (_NOTIFIER_CAPACITY). A
#     blocked callback keeps its thread -- and that capacity -- until it
#     returns; without capacity, notifications are skipped and counted.
#   * Callers that await delivery stop waiting for a lane stalled in one
#     delivery for _DELIVERY_STALL_SECONDS; the delivery itself goes on.
#     Critical diagnosis never depends on delivery: it is kept in the
#     callback-independent CouncilDiagnosisRegistry.
#   * Every queued or in-flight notification owns its payload (e.g. an
#     effective prompt) and is charged for it to the diagnosis pool from
#     queueing until its delivery ends or it is skipped/discarded -- also
#     while a blocked receiver keeps it in flight. Without capacity the
#     notification is skipped and counted, never held uncharged (FIX-031).
_DELIVERY_STALL_SECONDS = DEFAULT_PROFILE.delivery_stall_seconds
_DELIVERY_SETTLE_LIMIT_SECONDS = DEFAULT_PROFILE.finalization_seconds
_NOTIFIER_CAPACITY = DEFAULT_PROFILE.notifier_capacity


class _NotifierBudget:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self._lock = threading.Lock()
        self._live = 0
        self._dropped = 0

    def try_acquire(self) -> bool:
        with self._lock:
            if self._live >= self.capacity:
                return False
            self._live += 1
            return True

    def release(self) -> None:
        with self._lock:
            self._live -= 1

    def dropped(self, count: int) -> None:
        with self._lock:
            self._dropped += count

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"live": self._live, "dropped": self._dropped,
                    "capacity": self.capacity}


_NOTIFIERS = _NotifierBudget(_NOTIFIER_CAPACITY)


def council_notifier_stats() -> dict[str, int]:
    """Process-wide Council notification delivery: live delivery threads,
    notifications dropped for lack of delivery capacity, capacity."""
    return _NOTIFIERS.stats()


class _DeliveryLane:
    """Serial, bounded, asynchronous delivery to one receiver.

    `post()` never waits for the receiver. At most one delivery thread
    serves the lane; it exits as soon as the queue is empty."""

    def __init__(self, name: str, pending_limit: int | None = None):
        self.name = name
        self.pending_limit = (
            DEFAULT_PROFILE.subscription_pending_limit
            if pending_limit is None else pending_limit
        )
        self._cond = threading.Condition(threading.Lock())
        self._queue: deque = deque()
        self._thread: threading.Thread | None = None
        self._exiting: threading.Thread | None = None  # last thread, ending
        self._inflight_since: float | None = None
        self._closed = False
        self.counters = {"delivered": 0, "failed": 0, "skipped": 0, "queued": 0}

    def post(
        self, deliver: Callable[[], None],
        prepare: Callable[[], None] | None = None, *,
        key: Any = None, supersedes: Callable[[Any], bool] | None = None,
        payload_bytes: int = 0,
    ) -> bool:
        """Queue `deliver`. `key` coalesces: a pending entry with the same
        key is replaced. `supersedes(key)` drops matching pending entries
        (e.g. an invocation's progress once its terminal state is queued).
        `payload_bytes` is charged to the diagnosis pool while the entry is
        queued or in flight. Returns False when this notification is
        skipped."""
        with self._cond:
            if self._closed:
                self.counters["skipped"] += 1
                return False
            skipped = 0
            if supersedes is not None or key is not None:
                kept = deque()
                for entry in self._queue:
                    if (key is not None and entry[0] == key) or (
                            supersedes is not None and supersedes(entry[0])):
                        skipped += 1
                        _release_entry(entry)
                    else:
                        kept.append(entry)
                self._queue = kept
            self.counters["skipped"] += skipped
            if len(self._queue) >= self.pending_limit:
                self.counters["skipped"] += 1
                return False
            charge = _charge_payload(payload_bytes)
            if charge is False:
                self.counters["skipped"] += 1
                logger.warning(
                    f"Council notification lane {self.name}: notification skipped, "
                    f"payload of {payload_bytes} bytes cannot be charged (storage capacity)"
                )
                return False
            self._queue.append((key, prepare, deliver, charge))
            self.counters["queued"] += 1
            if self._thread is not None:
                return True
            thread = threading.Thread(
                target=self._serve, name=f"council-notify-{self.name}", daemon=True,
            )
            if _NOTIFIERS.try_acquire():
                self._thread = thread
                try:
                    thread.start()
                    return True
                except BaseException:
                    self._thread = None
                    _NOTIFIERS.release()
            dropped = len(self._queue)
            for entry in self._queue:
                _release_entry(entry)
            self._queue.clear()
            self.counters["skipped"] += dropped
        _NOTIFIERS.dropped(dropped)
        logger.warning(
            f"Council notification lane {self.name}: {dropped} notification(s) "
            f"skipped, delivery capacity exhausted ({council_notifier_stats()})"
        )
        return False

    def _serve(self) -> None:
        current = threading.current_thread()
        try:
            while True:
                with self._cond:
                    if not self._queue:
                        # Decided under the same lock `post()` checks, so a
                        # notification queued from now on starts a new thread.
                        self._thread, self._exiting = None, current
                        self._cond.notify_all()
                        return
                    entry = self._queue.popleft()
                outcome = "failed"
                try:
                    _, prepare, deliver, _ = entry
                    if prepare is not None:
                        prepare()
                    with self._cond:
                        self._inflight_since = time.monotonic()
                        self._cond.notify_all()
                    deliver()
                    outcome = "delivered"
                except Exception:
                    # Observability must never change Council decisions.
                    logger.debug("Council notification delivery failed", exc_info=True)
                finally:
                    # The payload is held until here (in flight); drop every
                    # reference to it before its charge is released.
                    charge = entry[3]
                    entry = prepare = deliver = None
                    if charge is not None:
                        charge()
                    with self._cond:
                        self.counters[outcome] += 1
                        self._inflight_since = None
                        self._cond.notify_all()
        except BaseException:
            with self._cond:
                stranded = len(self._queue)
                for entry in self._queue:
                    _release_entry(entry)
                self._queue.clear()
                self.counters["skipped"] += stranded
                self._thread, self._exiting = None, current
                self._cond.notify_all()
            _NOTIFIERS.dropped(stranded)
            raise
        finally:
            _NOTIFIERS.release()

    def close(self) -> int:
        """Accept no further notifications and discard queued ones that have
        not started. Returns how many were discarded."""
        with self._cond:
            self._closed = True
            discarded = len(self._queue)
            for entry in self._queue:
                _release_entry(entry)
            self._queue.clear()
            self.counters["skipped"] += discarded
            self._cond.notify_all()
            return discarded

    def delivery_counts(self) -> dict[str, int]:
        """delivered, failed, skipped, and unconfirmed (queued or in flight,
        neither delivered nor failed yet)."""
        with self._cond:
            in_flight = 1 if self._inflight_since is not None else 0
            return {
                "delivered": self.counters["delivered"],
                "failed": self.counters["failed"],
                "skipped": self.counters["skipped"],
                "unconfirmed": len(self._queue) + in_flight,
            }

    def settle(self, until: float) -> bool:
        """Wait until every notification is delivered (True), or the lane is
        stalled in a delivery / `until` passed (False)."""
        with self._cond:
            while True:
                if self._thread is None:
                    exiting = self._exiting
                    break
                now = time.monotonic()
                if now >= until:
                    return False
                if (self._inflight_since is not None
                        and now - self._inflight_since >= _DELIVERY_STALL_SECONDS):
                    return False
                wake = until
                if self._inflight_since is not None:
                    wake = min(wake, self._inflight_since + _DELIVERY_STALL_SECONDS)
                self._cond.wait(max(0.001, wake - now))
        # Everything is delivered; let the last delivery thread finish ending
        # so a settled lane leaves no thread behind.
        if exiting is not None and exiting is not threading.current_thread():
            exiting.join(max(0.0, until - time.monotonic()))
        return True


def _charge_payload(nbytes: int) -> Callable[[], None] | None | bool:
    """Charge a notification payload to the diagnosis pool. Returns its
    idempotent release, None if nothing needs charging, False if the pool
    cannot take it."""
    if nbytes <= 0:
        return None
    registry = _DIAGNOSIS
    if not registry.reserve_extra(nbytes):
        return False
    released = [False]

    def release() -> None:
        if not released[0]:
            released[0] = True
            registry.release_extra(nbytes)

    return release


def _release_entry(entry: tuple) -> None:
    if entry[3] is not None:
        entry[3]()


def _payload_bytes(payload: dict) -> int:
    """Charged size of a notification payload: its exact serialized UTF-8
    bytes (the registry's unit), never below the raw string bytes held."""
    return _size(payload)


def _settle_deliveries(lanes: list[_DeliveryLane], until: float | None = None) -> None:
    """Await pending notifications, bounded: a stalled receiver is left to
    its delivery thread, never waited for beyond the stall threshold."""
    if until is None:
        until = time.monotonic() + _DELIVERY_SETTLE_LIMIT_SECONDS
    unsettled = [lane.name for lane in lanes if lane is not None and not lane.settle(until)]
    if unsettled:
        logger.warning(
            "Council notification receiver stalled; continuing without "
            f"awaiting delivery on: {', '.join(unsettled)}"
        )


# Lane of tasks without an activity subscription: never posted to.
_NO_SUBSCRIPTION = _DeliveryLane("no-subscription")

# Callback-independent critical diagnosis and confirmed persistence
# (SUB_REQ_035, SUB_REQ_036), process-wide and bounded.
_DIAGNOSIS = CouncilDiagnosisRegistry(
    DEFAULT_PROFILE.diagnosis_pool_bytes, DEFAULT_PROFILE.diagnosis_envelope_bytes,
    DEFAULT_PROFILE.volatile_retention_seconds,
)
_PERSISTENCE = PersistenceWriter(DEFAULT_PROFILE.persistence_slots)


def council_diagnosis(key: str) -> dict[str, Any] | None:
    """Critical diagnosis of a Council run by run id or result id, without
    any callback: volatile, bounded, retained while the service runs
    (restart retrieval only from confirmed persistence)."""
    return _DIAGNOSIS.get(key)


def council_lifecycle_projection(record: dict[str, Any]) -> dict[str, Any]:
    """The critical diagnosis as persisted into the central workflow trace:
    invocation entries as a list (fixed keys), the declared profile left
    out (it is not a cause), failure causes as categories and counts
    (never raw error text). Strings are redacted again by the trace."""
    projection = {key: value for key, value in record.items()
                  if key not in ("profile", "invocations")}
    projection["invocations"] = list((record.get("invocations") or {}).values())
    outcome = dict(projection.get("outcome") or {})
    if outcome:
        # Public projection: causes as categories/counts only -- raw
        # provider/Chairman error text never leaves the internal record.
        outcome["decision_error_count"] = len(outcome.pop("decision_errors", None) or [])
        outcome["chairman_error_present"] = bool(outcome.pop("chairman_error", None))
        projection["outcome"] = outcome
    return projection


def council_resource_stats() -> dict[str, dict[str, int]]:
    """Every finite Council resource in one place (SUB_REQ_038)."""
    return {
        "workers": council_worker_stats(),
        "notifiers": council_notifier_stats(),
        "diagnosis": _DIAGNOSIS.stats(),
        "persistence": _PERSISTENCE.stats(),
        "runs": _RUN_SLOTS.stats(),
    }


@dataclass
class _CouncilRun:
    """One admitted evaluate(): its public deadline starts at entry."""
    run_id: str
    entered_at: float
    public_deadline: float
    profile: dict[str, Any]
    persistence_reserved: bool = False
    phase_limits: dict[str, float] = field(default_factory=dict)
    # Closed when the public deadline for Council work is reached: no phase
    # starts and no handover begins afterwards (SUB_REQ_033/039).
    closed: bool = False
    # Exactly one side finalizes the run: "body" or "public" (timeout).
    finalizer: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    # Booking of the run's working data (see _RunLedger).
    ledger: "_RunLedger | None" = None


class _RunLedger:
    """Booking of the variable-size working data of one admitted run
    (SUB_REQ_036/038/040), CLAUDE-ADC-RESOURCE-CONTRACT-CLOSURE-037.

    Booked, in exact UTF-8 bytes: the admitted input (its repr), every
    invocation prompt handed to a worker (retry prompts included) and every
    provider response received. Data derived inside the run (parsed
    proposals, votes) is covered by the bytes it was derived from; the
    result, retained prompt copies, notification payloads and pending
    writes are charged by their own owners, the critical record and call
    records by the run's envelope.

    Owners are every service-side party that can keep this data: the
    public call, the run body, every invocation (bound to its task object,
    so a quarantined worker keeps it booked until its thread has really
    ended and dropped the task) and every propagated exception of the run
    (bound to the exception object, so also a traceback in a collectable
    cycle). The booking is released only when the last owner is gone.

    A booking is made by a live owner before the data is used for work. If
    the pool cannot take it, that work does not happen: admission is
    refused, an invocation is not started, a response is dropped and its
    invocation fails visibly -- "not chargeable" never lets work go on."""

    def __init__(self, registry: Any):
        self._registry = registry
        self._lock = threading.Lock()
        self._owners = 0
        self.nbytes = 0

    def book(self, nbytes: int) -> bool:
        """Book `nbytes` more; caller must be a live owner. False if the
        pool cannot take it (nothing is booked then)."""
        if nbytes <= 0:
            return True
        if not self._registry.reserve_extra(nbytes):
            return False
        with self._lock:
            self.nbytes += nbytes
        return True

    def owner(self) -> Callable[[], None]:
        """Register one owner; returns its idempotent release."""
        with self._lock:
            self._owners += 1
        released = [False]

        def release() -> None:
            with self._lock:
                if released[0]:
                    return
                released[0] = True
                self._owners -= 1
                if self._owners:
                    return
                nbytes, self.nbytes = self.nbytes, 0
            if nbytes:
                self._registry.release_extra(nbytes)

        return release

    def bind(self, holder: Any) -> None:
        """Keep the booking for as long as `holder` exists. Exceptions take
        no weak references, so an exception carries an owner token whose
        finalizer releases this owner."""
        if isinstance(holder, BaseException):
            token = _ChargeOwner()
            holder.__dict__.setdefault("_council_charge_owners", []).append(token)
            holder = token
        weakref.finalize(holder, self.owner())


class _ChargeOwner:
    """Owner token carried by an exception (see _RunLedger.bind)."""


def _text_bytes(text: str | None) -> int:
    return len(text.encode("utf-8", "surrogatepass")) if text else 0


def _detach_input(error: BaseException, value: Any, stop: Any = None) -> None:
    """Drop an uncharged input from the finished service frames a
    propagated traceback keeps (the first frame is the catching one). Only
    frames that hold the input are cleared; the traceback text, the
    exception and the critical record remain. Walking ends at `stop` (a
    code object whose frames another thread settles itself)."""
    if value is None:
        return
    tb = error.__traceback__
    tb = tb.tb_next if tb is not None else None
    while tb is not None:
        frame = tb.tb_frame
        if frame.f_code is stop:
            return
        try:
            if any(item is value for item in frame.f_locals.values()):
                frame.clear()
                frame.f_locals  # resync the cached locals snapshot
        except RuntimeError:
            pass  # still executing: not a retained frame
        tb = tb.tb_next


class _RunSlots:
    """Bounded Council run threads (SUB_REQ_038/040). A run whose body is
    still busy after its public deadline keeps its slot until it ends."""

    def __init__(self, capacity: int):
        self.capacity = capacity
        self._lock = threading.Lock()
        self._busy = 0

    def reserve(self) -> bool:
        with self._lock:
            if self._busy >= self.capacity:
                return False
            self._busy += 1
            return True

    def release(self) -> None:
        with self._lock:
            self._busy -= 1

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"busy": self._busy, "capacity": self.capacity}


_RUN_SLOTS = _RunSlots(DEFAULT_PROFILE.worker_capacity)


def _call_budget(config: CouncilAgentConfig) -> float:
    """Seconds one contributor call may take: all permitted attempts."""
    return config.timeout_seconds * _TOTAL_RETRY_MULTIPLIER + _TIMEOUT_GRACE_SECONDS


def _outer_deadline(config: CouncilAgentConfig) -> float:
    """Total bounded deadline covering all permitted same-phase provider calls."""
    return time.monotonic() + _call_budget(config)


def _failure_category(error: Exception) -> str:
    """CLAUDE-E2E-NIO-011A: the safe, deterministic category for a
    Chairman-synthesis-validation failure. Prefers CouncilChairmanError's
    own `.category`; falls back to the inline "[category=...]" tag used
    by _validate_toolchain_requirement_refs()'s ValueError (which cannot
    carry a real attribute, since it is a plain ValueError shared with
    other, non-Chairman-specific callers); "unknown" only if neither is
    present."""
    category = getattr(error, "category", None)
    if category:
        return category
    return _failure_category_from_text(str(error))


def _failure_category_from_text(message: str) -> str:
    """Extracts the LAST "[category=...]" tag in a message -- for a
    combined bounded-repair-exhausted message that embeds both attempts'
    tags, the last one is attempt 2's, the decisive/final outcome."""
    marker = "[category="
    start = message.rfind(marker)
    if start != -1:
        end = message.find("]", start)
        if end != -1:
            return message[start + len(marker):end]
    return "unknown"


# CLAUDE-ADC-COUNCIL-DIAGNOSTIC-CAPTURE-001 (corrected by CLAUDE-ADC-
# COUNCIL-DIAGNOSTIC-TRACE-INTEGRATION-FIX-001): bounded, deterministic
# reason vocabulary for a Phase-1 agent result that decoded successfully
# (res.success and res.parsed truthy -- a genuine LLM/parse failure is
# already covered by the existing agent_errors path and is NEVER
# reclassified here) but retained ZERO usable proposals. Every branch
# below is a read-only classification of data _phase1_independent_
# proposals() already computed for its own unchanged control flow --
# this diagnostic layer never feeds back into which proposals are kept,
# how many, or whether the Council is complete/degraded.
#
# CLAUDE-ADC-COUNCIL-DIAGNOSTIC-TRACE-INTEGRATION-FIX-001: the original
# CLAUDE-ADC-COUNCIL-DIAGNOSTIC-CAPTURE-001 task persisted this evidence
# to a NEW, dedicated JSONL file it opened itself
# (.diagnostic-traces/council_zero_proposal_events.jsonl) -- a parallel
# diagnostic subsystem the current task corrects. This evidence is now
# folded into the SAME central app.diagnostic_trace.DiagnosticTrace
# pipeline every other DevelopmentWorkflow/EngineeringCouncil diagnostic
# already uses, through the EXISTING set_result_callback()/self._result()
# composition path (see _emit_structured_results()'s "no usable
# structured proposal" branch) -- EngineeringCouncil never opens a file
# for this itself.
_REASON_EMPTY_OBJECT = "empty_object"
_REASON_MISSING_VARIANTS = "missing_variants"
_REASON_EMPTY_VARIANTS = "empty_variants"
_REASON_ALL_CANDIDATES_REJECTED = "all_candidates_rejected"
_REASON_OTHER_INTERNAL = "other_internal"


def _safe_len(value: Any) -> int | None:
    """len(value) for anything sized (list, dict, string, tuple, set,
    ...), else None -- never raises. Shared by the "how many candidates
    were even present" diagnostic field and by _is_empty_container()
    below, so both agree on exactly what "sized" means."""
    try:
        return len(value)
    except TypeError:
        return None


def _is_empty_container(value: Any) -> bool:
    """True only for a genuinely empty, sized value (list, dict, string,
    tuple, set, ...) -- len(value) == 0. False for anything with no
    meaningful length (an int/float/bool) AND, just as importantly, for
    ANY NONEMPTY value regardless of its type.

    CLAUDE-ADC-COUNCIL-DIAGNOSTIC-HARDENING-FIX-001 (Codex review
    CDX-ADC-COUNCIL-DIAGNOSTIC-TRACE-REVIEW-001, finding F2): a nonempty
    malformed "variants" value (e.g. a dict or a string the LLM emitted
    instead of a list) must never be silently coerced into looking
    "empty" merely because it fails an `isinstance(..., list)` check --
    it genuinely carries content, just not in the expected shape. An
    EMPTY container of any of these types (e.g. "variants": {} or
    "variants": "") carries exactly as little information as an empty
    list and is honestly described the same way."""
    return _safe_len(value) == 0


def _classify_zero_proposal_reason(
    parsed: Any, variants_field: Any, rejected_candidates: list[dict],
) -> str:
    """Pure, deterministic classification of WHY one Phase-1 agent
    result -- already known to have decoded successfully and to have
    retained zero proposals -- ended up empty. Reads only the already-
    parsed structures the caller already has; never re-parses, never
    inspects raw text.

    A root that is not a mapping at all (e.g. the LLM's entire response
    decoded to `null`, a bare number, or an empty list) is neither of
    the two dict-shaped branches below and is never silently coerced
    into "empty_variants" -- it is the one narrowly-scoped, deterministic
    "other_internal" case.

    A present "variants" value is classified by ACTUAL emptiness
    (_is_empty_container()), never by type alone: a nonempty dict/string/
    other malformed shape is never "empty_variants" (F2, above) -- it
    either genuinely reflects rejected per-item processing
    ("all_candidates_rejected", whenever the caller's own loop over it
    -- unchanged -- produced at least one rejection) or falls back to
    the same explicit, deterministic "other_internal" this function
    already used for a non-mapping root."""
    if not isinstance(parsed, dict):
        return _REASON_OTHER_INTERNAL
    if not parsed:
        return _REASON_EMPTY_OBJECT
    if "variants" not in parsed:
        return _REASON_MISSING_VARIANTS
    if _is_empty_container(variants_field):
        return _REASON_EMPTY_VARIANTS
    if rejected_candidates:
        return _REASON_ALL_CANDIDATES_REJECTED
    # Unreachable in practice: the caller only invokes this when zero
    # proposals were retained from a non-empty `variants_field`, and its
    # own loop (unchanged) appends every failed item to
    # rejected_candidates -- a nonempty, iterable `variants_field` with
    # no rejections would already have retained at least one proposal.
    # Kept as an explicit, safe, deterministic fallback rather than a
    # silently-assumed "cannot happen".
    return _REASON_OTHER_INTERNAL


_MAX_CANDIDATE_IDENTIFIER_LENGTH = 200
# CLAUDE-ADC-COUNCIL-DIAGNOSTIC-PRIVACY-HARDENING-FIX-002 (Codex
# rereview CDX-ADC-COUNCIL-DIAGNOSTIC-HARDENING-REREVIEW-002, finding H1
# -- HIGH): a STRICT POSITIVE allowlist, not a "reject known-bad
# characters" denylist. The prior policy only rejected whitespace/
# control characters, which a compact (whitespace-free) JSON fragment
# such as `{"agent_reasoning":"...","credentials":{"secret":"..."}}`
# trivially satisfies while still being a fully structured, nested
# payload. Every real requirement/toolchain identifier in this codebase
# (see tests/*.py, app/*.py -- "req-1", "req-esphome-fw", ...) is a
# short alphanumeric token optionally joined with "-"/"_"/"." ; nothing
# else is ever a legitimate identifier, so nothing else is accepted --
# JSON/structured punctuation (quotes, braces, brackets, colons, equals
# signs, commas, slashes, backslashes) can never pass this regex
# regardless of whitespace.
_SAFE_CANDIDATE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _sanitized_candidate_identifier(value: Any) -> str | None:
    """CLAUDE-ADC-COUNCIL-DIAGNOSTIC-HARDENING-FIX-001/-PRIVACY-
    HARDENING-FIX-002 (Codex review CDX-ADC-COUNCIL-DIAGNOSTIC-TRACE-
    REVIEW-001 finding F1, hardened further by CDX-ADC-COUNCIL-
    DIAGNOSTIC-HARDENING-REREVIEW-002 finding H1 -- both HIGH, privacy
    bypass): a candidate's own requirement_ref/provided_by value is
    untrusted LLM output, read from a variant_data entry that is ALREADY
    being rejected here precisely because something about its shape is
    invalid -- there is no guarantee it is even a string, still less
    that it looks like a real identifier.
    `_candidate_rejection_diagnostic()` used to do `str(value)`
    unconditionally: for a nested object such as
    `{"agent_reasoning": "...", "credentials": {"secret": "sk-..."}}`,
    that flattens the ENTIRE nested structure -- including any forbidden
    key/value it carries -- into what DiagnosticTrace's own recursive
    allowlisting can only ever see as one ordinary, already-scalar
    string value; `_redact()`'s regexes only match an actual
    `key=value`/`key: value` shape in running text, not a Python dict
    repr. An EARLIER fix rejected only whitespace/control characters,
    which a COMPACT (no-whitespace) JSON string --
    `{"agent_reasoning":"...","credentials":{"secret":"..."}}` -- still
    satisfies while carrying exactly the same forbidden nested content.
    Central-trace allowlisting alone cannot catch either shape (it never
    re-parses a string value's own textual content); sanitization MUST
    happen here, at the producer, with a POSITIVE policy for what an
    identifier IS allowed to look like, never a denylist of what it must
    not contain.

    Returns the value UNCHANGED (stripped) only when it is already a
    plain string that, after stripping, consists ENTIRELY of
    `_SAFE_CANDIDATE_IDENTIFIER_RE` characters (letters, digits, `_`,
    `-`, `.`) and is no longer than a real requirement/toolchain
    identifier could reasonably be -- never re-stringified from any
    other type, never accepted merely for lacking whitespace. Returns
    None for anything else (wrong type, empty after stripping, too long,
    or containing ANY character outside that positive set -- including
    but not limited to quotes, braces, brackets, colons, equals signs,
    commas, slashes, backslashes, and all whitespace/control characters)
    so the caller drops it from the identifier list entirely rather than
    ever falling back to `str(value)`. Presence/type information for a
    rejected value is captured separately, by type name only (see
    _candidate_rejection_diagnostic()'s own `*_invalid_types` fields) --
    never by echoing the value or any part of it."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped or len(stripped) > _MAX_CANDIDATE_IDENTIFIER_LENGTH:
        return None
    if not _SAFE_CANDIDATE_IDENTIFIER_RE.match(stripped):
        return None
    return stripped


# CLAUDE-ADC-COUNCIL-DIAGNOSTIC-PRIVACY-HARDENING-FIX-002 (Codex
# rereview CDX-ADC-COUNCIL-DIAGNOSTIC-HARDENING-REREVIEW-002, finding H2
# -- HIGH): the ONLY categories app.engineering_council's own,
# hand-written validation code can legitimately raise while building a
# Phase-1 candidate (see _validate_toolchain_requirement_refs()'s own
# tagged ValueError). Every other possible failure inside
# _build_proposal_from_dict() -- a generic ValueError/TypeError from
# `float(data.get("confidence", ...))`, a malformed toolchain entry
# passed to ToolchainItem(...), etc. -- carries no trusted category tag
# of its own, and its exception message may itself echo arbitrary
# LLM-controlled input (e.g. confidence="[category=SOME_CANARY]" makes
# `float()` raise a ValueError whose OWN text embeds exactly that
# string). This CLOSED allowlist is the trust boundary: only a category
# that is a member of this exact, hand-maintained set may ever reach the
# persisted diagnostic; anything else -- however it was produced, and
# regardless of whether it superficially LOOKS like a legitimate tag --
# becomes "unknown", the same deterministic fallback
# _failure_category_from_text() already uses when no tag is present at
# all.
_TRUSTED_CANDIDATE_REJECTION_CATEGORIES = frozenset({"invalid_requirement_ref"})


def _trusted_candidate_rejection_category(exc: Exception) -> str:
    """CLAUDE-ADC-COUNCIL-DIAGNOSTIC-PRIVACY-HARDENING-FIX-002 (H2):
    `_failure_category()`/`_failure_category_from_text()` were designed
    for Chairman-synthesis-validation failures, where the only code that
    ever raises a "[category=...]"-tagged exception is this module's own
    trusted synthesis-repair path -- reusing that same text-extraction
    for a Phase-1 candidate-build failure is unsafe, because
    `_build_proposal_from_dict()` can also raise a completely generic,
    untagged exception whose message text is influenced by untrusted
    LLM-controlled input. This wraps `_failure_category()`'s own
    extraction (kept, unmodified, and still used unchanged for its
    original Chairman-side callers) with one additional check: the
    result must be a member of `_TRUSTED_CANDIDATE_REJECTION_CATEGORIES`
    or it is replaced with "unknown" -- so an attacker-crafted value
    that happens to produce a string matching the `[category=...]`
    pattern can never smuggle arbitrary text into a persisted diagnostic
    field merely by picking a tag this allowlist doesn't recognize."""
    category = _failure_category(exc)
    if category in _TRUSTED_CANDIDATE_REJECTION_CATEGORIES:
        return category
    return "unknown"


def _candidate_rejection_diagnostic(variant_data: Any, exc: Exception) -> dict:
    """Bounded, deterministic per-candidate rejection evidence for one
    Phase-1 variant_data entry that failed to build into an
    AgentProposal: a category drawn ONLY from
    `_TRUSTED_CANDIDATE_REJECTION_CATEGORIES`
    (_trusted_candidate_rejection_category(), CLAUDE-ADC-COUNCIL-
    DIAGNOSTIC-PRIVACY-HARDENING-FIX-002 finding H2 -- never
    `_failure_category()`'s raw, text-extracted result, which a
    generic/untagged exception's own message could be made to echo
    arbitrary LLM-controlled text through), plus -- only when present on
    this exact candidate's own toolchain entries, never the full
    candidate payload -- the offending requirement_ref/provided_by
    values, SANITIZED by _sanitized_candidate_identifier() (finding F1/
    H1): a value that is not already a safe, bounded, positively-
    allowlisted identifier string is NEVER stringified into the
    identifier lists -- only its Python type name is recorded, in a
    separate, explicitly-named field, so "something invalid was here,
    and what kind" remains visible without ever persisting its content.
    Carries no free-text exception message, no prompt, no raw
    response."""
    toolchain = variant_data.get("toolchain") if isinstance(variant_data, dict) else None
    if not isinstance(toolchain, list):
        toolchain = []

    requirement_refs: set[str] = set()
    requirement_ref_invalid_types: set[str] = set()
    provided_by: set[str] = set()
    provided_by_invalid_types: set[str] = set()

    for item in toolchain:
        if not isinstance(item, dict):
            continue
        raw_ref = item.get("requirement_ref")
        if raw_ref not in (None, ""):
            sanitized = _sanitized_candidate_identifier(raw_ref)
            if sanitized is not None:
                requirement_refs.add(sanitized)
            else:
                requirement_ref_invalid_types.add(type(raw_ref).__name__)
        raw_provided_by = item.get("provided_by")
        if raw_provided_by not in (None, ""):
            sanitized = _sanitized_candidate_identifier(raw_provided_by)
            if sanitized is not None:
                provided_by.add(sanitized)
            else:
                provided_by_invalid_types.add(type(raw_provided_by).__name__)

    return {
        "category": _trusted_candidate_rejection_category(exc),
        "rejected_requirement_refs": sorted(requirement_refs),
        "rejected_provided_by": sorted(provided_by),
        "rejected_requirement_ref_invalid_types": sorted(requirement_ref_invalid_types),
        "rejected_provided_by_invalid_types": sorted(provided_by_invalid_types),
    }


_FAILURE_SUBSYSTEM_BY_CATEGORY = {
    "provider_transport": "S2.2",
    "no_valid_variant": "S2.2",
    "invalid_recommendation": "S2.2",
    "invalid_requirement_ref": "S2.2",
    "completeness_validation": "S2.3",
    "platform_constraint": "S2.3",
    "materializability_conflict": "S2.3",
    "verification_coverage": "S2.3",
    "admissibility_validation": "S2.3",
}


def _failure_subsystem(category: str) -> str:
    """CLAUDE-ARCH-S2-012A, Part 28: maps a safe failure category to the
    S2 Subsubsystem that actually OWNS the corresponding rule, for
    Diagnostic Trace fault localization (e.g. a future failure
    classifiable approximately as "S2.2 PASS / S2.3 NIO:
    platform_constraint / S2.4 NOT REACHED / S2.5 NOT REACHED / S3 NOT
    REACHED"). Protocol-only failures (malformed/missing/invalid
    recommendation, transport) are S2.2's own; every engineering-
    admissibility category is S2.3's, since S2.2's own early check only
    ever calls INTO S2.3's validate_variants() rather than owning any
    admissibility rule itself."""
    return _FAILURE_SUBSYSTEM_BY_CATEGORY.get(category, "S2.2")


def _build_chairman_repair_prompt(original_prompt: str, error: Exception) -> str:
    """CLAUDE-E2E-NIO-011A, Part 5: the smallest targeted repair request
    -- reuses the ORIGINAL Chairman prompt verbatim (which already
    contains every proposal, cross-review, and binding-Requirement/
    Constraint fact the Chairman needs) and appends only the exact,
    already-safe, deterministic rejection reason (never raw prompts,
    credentials, or Chain-of-Thought -- `error` is always one of this
    module's own short, structured messages, the same ones already
    proven safe for diagnostics in CLAUDE-PRE-E2E-009C/CLAUDE-E2E-
    NIO-010A). Asks the Chairman to correct ONLY that deficiency rather
    than re-deriving a solution from scratch, and never invents,
    merges, or repairs a variant on ADC's own authority -- the Chairman
    remains the sole synthesizer (Part 7/8).

    CLAUDE-ARCH-S2-012D: when `error` is an EngineeringReworkRequest
    carrying an identity conflict, one additional static, technology-
    neutral hint sentence is appended, naming the exact offending item(s)
    already computed by S2.3 (identity_conflict_detail) and pointing at
    the ALREADY-DOCUMENTED technical_identity contract every synthesis
    prompt already states (see app.council_prompts). Root cause of
    Real-System-E2E #8: the prior repair prompt exposed only a bare
    `materializability_conflict=True` boolean, giving the Chairman no way
    to know WHICH toolchain item needed a technical_identity correction,
    so its one bounded repair attempt could not target the actual defect.
    This hint is itself deterministic, structured evidence -- it
    identifies the offending item, it never invents a fix or a value on
    ADC's own authority.

    CLAUDE-ADC-S23-INSTALL-METHOD-PRODUCER-REPAIR-FIX-001: an
    EngineeringReworkRequest carrying an install_method conflict
    (identity already resolved, but install_method itself does not match
    the controlled executor's fixed compatibility contract -- see
    app.engineering_decision._binding_item_rejection_category()) instead
    gets its OWN, distinct hint naming the exact offending item(s)
    (install_method_conflict_detail) and restating the closed
    install_method shape contract app.council_prompts already documents
    for Phase-1/Chairman synthesis, never the technical_identity hint --
    identity was never the problem for this category, so repeating that
    hint would misdirect the Chairman's one bounded repair attempt at a
    field that is already correct (root cause: a real Real-System-E2E run
    reached this exact defect with a genuinely valid technical_identity
    and a repair attempt that only ever knew how to suggest fixing
    technical_identity). The two hints are independent and both may be
    emitted when a variant genuinely carries both kinds of offending
    items."""
    hint = ""
    if (
        isinstance(error, EngineeringReworkRequest)
        and error.identity_conflict
        and error.identity_conflict_detail
    ):
        hint = (
            "\nHinweis zum Materialisierbarkeits-Mangel (fehlende/ungueltige "
            "technische Identitaet): die folgenden Toolchain-Items sind "
            "betroffen: "
            f"{', '.join(error.identity_conflict_detail)}. "
            "Falls es sich um ein python_package-Item handelt, setze "
            "technical_identity auf die exakte installierbare "
            "Distributionskennung (z.B. \"esphome\"), wenn der "
            "Anzeigename dafuer nicht bereits geeignet ist -- exakt wie "
            "oben im Schema bereits gefordert."
        )
    if (
        isinstance(error, EngineeringReworkRequest)
        and error.install_method_conflict
        and error.install_method_conflict_detail
    ):
        hint = hint + (
            "\nHinweis zum Materialisierbarkeits-Mangel (install_method): "
            "die folgenden Toolchain-Items sind betroffen: "
            f"{', '.join(error.install_method_conflict_detail)}. Die "
            "technische Identitaet dieser Items ist bereits gueltig -- "
            "korrigiere AUSSCHLIESSLICH install_method, niemals "
            "technical_identity oder name. install_method muss fuer ein "
            "python_package-Item exakt eine der folgenden Formen haben: "
            "\"pip\", \"python_package\", \"pip install <technical_identity>\" "
            "oder \"python -m pip install <technical_identity>\" -- kein "
            "zusammengesetzter Shell-Befehl, keine venv-Aktivierung, kein "
            "Docker-Kommando. Eine venv-, Container- oder Host-Platzierung "
            "gehoert ausschliesslich in \"environment\"/\"purpose\"/"
            "\"description\", niemals in install_method oder name."
        )
    if (
        isinstance(error, EngineeringReworkRequest)
        and error.verification_feasibility_conflict
        and error.verification_feasibility_conflict_detail
    ):
        # CLAUDE-ARCH-S2-013F: name the exact mechanism/evidence pair and
        # the precise compatibility/control reason S2.3 computed (see
        # app.engineering_decision._verification_feasibility_gap_diagnostics()),
        # the same "name the exact field at fault" precedent 012D
        # established for materializability, applied to verification
        # feasibility so a bounded repair can target the real defect.
        hint = hint + (
            "\nHinweis zum Verifikations-Mangel (S2.3 Verification "
            "Feasibility): "
            f"{'; '.join(error.verification_feasibility_conflict_detail)}. "
            "Korrigiere entweder den mechanism-Wert auf einen, den das "
            "referenzierte ToolchainItem tatsaechlich in seinem eigenen "
            "provides_verification deklariert, oder die evidence auf ein "
            "ToolchainItem DERSELBEN Variante, das den bereits gewaehlten "
            "mechanism deklariert -- exakt wie oben im Schema unter "
            "VERIFICATION_COVERAGE gefordert. Bei kind=\"manual_review\" "
            "setze zusaetzlich \"human_governed\": true."
        )
    return (
        f"{original_prompt}\n\n"
        "---\n"
        "KORREKTUR ERFORDERLICH: Deine vorherige Antwort wurde von der "
        "deterministischen Validierung abgelehnt:\n"
        f"{error}\n"
        f"{hint}\n\n"
        "Behebe AUSSCHLIESSLICH diesen konkreten Mangel. Nutze weiterhin "
        "ausschliesslich die oben aufgefuehrten Requirements, "
        "Agenten-Vorschlaege und Bewertungen -- erfinde keine neuen "
        "Requirements oder Vorschlaege. Gib erneut eine vollstaendige, "
        "valide JSON-Antwort im exakt gleichen Schema zurueck."
    )


@dataclass
class _AgentTask:
    """One contributor invocation (SUB_REQ_033-035).

    Ownership: the worker thread only writes task-local buffers and claims a
    terminal state; the coordinator commits buffers to shared Council state
    only for a terminal state claimed in time. `lock` makes every lifecycle
    decision atomic: terminal claim/finalization, closure, and each actual
    request handover of the gated transport (see HandoverGate)."""
    agent_id: str
    role: str
    config: CouncilAgentConfig
    prompt: str
    phase: str
    started_at: datetime
    activity_closed: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    # Exactly one terminal lifecycle state per invocation, decided under
    # `lock` by the worker (only before `deadline`) or by the coordinator
    # finalizing a timeout/refusal. `terminal_state` (state, category) is
    # the authoritative internal diagnosis, independent of any delivery.
    terminal: bool = False
    terminal_state: tuple | None = None
    # Monotonic deadline of this contributor call. A worker result claimed
    # after it is never accepted (late coordinator execution included).
    deadline: float = float("inf")
    # The worker's final outcome (_AgentResult or exception), published
    # together with its terminal claim.
    outcome: Any = None
    # Start decision for provider bindings WITHOUT a handover boundary
    # (UNVERIFIED_BOUNDARY): claimed under `lock` before complete(). It is
    # not a proof of actual handover; gated bindings decide in the transport.
    provider_started: bool = False
    finalized_after_start: bool = False
    gate: HandoverGate | None = None
    handover_boundary: str = UNVERIFIED_BOUNDARY
    invocation_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    # Set when the terminal state is decided; wakes the coordinator.
    changed: threading.Event | None = None
    # The activity subscription lane this task notifies through (shared by
    # all tasks of the subscription; kept under both historic names).
    progress_lane: "_DeliveryLane | None" = None
    terminal_lane: "_DeliveryLane | None" = None
    call_records: list = field(default_factory=list)
    effective_prompt: str | None = None
    worker: threading.Thread | None = None
    run_id: str = ""
    # Whether the worker already reported its final outcome (claim or late
    # addition), so its thread wrapper never reports a second time.
    worker_reported: bool = False
    # "waiting" while the worker waits for its agent slot, then "owned" or
    # "refused"; a waiting worker has not started any provider work.
    slot_state: str = "admitted"
    # The run's ledger; this task is one of its owners once started (its
    # prompt and responses are booked there). None outside an admitted run.
    ledger: "_RunLedger | None" = None


@dataclass
class _AgentResult:
    agent_id: str
    success: bool
    parsed: dict[str, Any] | None = None
    raw_response: str = ""
    error: str | None = None


@dataclass(frozen=True)
class _CouncilQuorum:
    complete: bool
    degraded: bool
    phase1_agents: int
    phase2_agents: int


def _get_agent_config(council_config: CouncilConfig, agent_id: str) -> CouncilAgentConfig:
    role = _AGENT_ID_TO_CONFIG_KEY[agent_id]
    return getattr(council_config, role)


def _parse_verification_coverage(data: list) -> tuple[VerificationCoverage, ...]:
    """CLAUDE-ARCH-S2-013E: parses the (optional, additive) structured
    verification_coverage array an agent/Chairman JSON response may
    supply, exactly mirroring the toolchain-item parsing style already
    established for technical_identity -- never invents a mechanism/kind/
    evidence value the response itself did not provide."""
    return tuple(
        VerificationCoverage(
            requirement_refs=tuple(vc.get("requirement_refs", []) or []),
            kind=vc.get("kind", ""),
            mechanism=vc.get("mechanism", ""),
            evidence=vc.get("evidence", ""),
            human_governed=bool(vc.get("human_governed", False)),
        )
        for vc in (data or [])
    )


class EngineeringCouncil:
    """Multi-Agent Engineering Council with 3 phases and 7 LLM calls.

    Phase 1: 3 independent agents propose variants (parallel, isolated).
    Phase 2: 3 agents cross-review all proposals (parallel, votes isolated).
    Phase 3: Chairman synthesises CouncilResult (1 call).

    The Council NEVER performs installations, activates hardware, or
    executes destructive actions.  It ONLY produces data.
    """

    def __init__(
        self,
        council_config: CouncilConfig,
        secret_resolver: SecretResolver,
        trace_dir: Path | None = None,
    ):
        if not council_config.enabled:
            raise ValueError("CouncilConfig.enabled must be True")
        self._config = council_config
        self._secret_resolver = secret_resolver
        self._trace_dir = trace_dir
        self._call_records: list[AgentCallRecord] = []
        self._run_id: str = ""
        self._activity_callback: Callable[..., None] | None = None
        self._result_callback: Callable[..., None] | None = None
        self._result_lane: _DeliveryLane | None = None
        self._activity_lane: _DeliveryLane | None = None
        self._result_subscription: _DeliveryLane | None = None
        self._run: _CouncilRun | None = None
        self._body_thread: threading.Thread | None = None
        # Service-held retained data charged to the diagnosis pool:
        # (kind, release). Released when dropped or on collection. Kinds:
        # "prompt" (effective-prompt copies) and "call_records" (the hold on
        # the run envelope that charges this instance's call records).
        self._held_charges: list[tuple[str, Callable[[], None]]] = []
        # Atomic per-instance admission (SUB_REQ_038): number of parties of
        # the current run still using this instance's run state -- the
        # public call and the run body. Admission requires zero.
        self._admission = threading.Lock()
        self._occupants = 0
        weakref.finalize(self, EngineeringCouncil._release_charges, self._held_charges, None)
        self._effective_prompts: dict[str, str] = {}
        # CLAUDE-E2E-NIO-011A: bounded Chairman-synthesis-repair
        # bookkeeping for THIS evaluate() run only -- reset at the start
        # of _phase3_chairman_synthesis(), read back by
        # _emit_structured_results() to expose safe failure diagnostics
        # (never a new CouncilResult field, to avoid an unrelated schema
        # change for what is purely observability bookkeeping).
        self._chairman_attempts: int = 0
        self._chairman_repair_used: bool = False
        # CLAUDE-ADC-COUNCIL-DIAGNOSTIC-TRACE-INTEGRATION-FIX-001: SAME
        # kind of per-evaluate()-run-only bookkeeping as
        # _chairman_attempts above -- reset at the start of
        # _phase1_independent_proposals(), read back by
        # _emit_structured_results() to fold bounded zero-retained-
        # proposal branch evidence into the existing central
        # DiagnosticTrace event for that agent. Never a new CouncilResult
        # field, never persisted by this class itself.
        self._zero_proposal_diagnostics: dict[str, dict] = {}

    def set_activity_callback(self, callback: Callable[..., None] | None) -> None:
        """Project safe Council runtime activity into the central trace.
        Each registration is one best-effort subscription (SUB_REQ_037)."""
        self._activity_callback = callback
        self._activity_lane = (
            _DeliveryLane(f"activity-{uuid.uuid4().hex[:8]}") if callback is not None else None
        )

    def set_result_callback(self, callback: Callable[..., None] | None) -> None:
        """Project safe structured Council work products into the central trace.
        Each registration is one best-effort subscription (SUB_REQ_037)."""
        self._result_callback = callback
        self._result_subscription = (
            _DeliveryLane(f"results-{uuid.uuid4().hex[:8]}") if callback is not None else None
        )

    def notification_state(self) -> dict[str, dict[str, int]]:
        """Delivery counters per subscription: delivered, failed, skipped and
        unconfirmed are reported separately; queueing is not delivery."""
        state = {}
        if self._activity_lane is not None:
            state["activity"] = self._activity_lane.delivery_counts()
        if self._result_subscription is not None:
            state["results"] = self._result_subscription.delivery_counts()
        return state

    def _result(self, **result) -> None:
        """Queue one structured result for its receiver; never waits for it."""
        callback = self._result_callback
        lane = self._result_lane or self._result_subscription
        if callback is None or lane is None:
            return
        lane.post(lambda: callback(**result), payload_bytes=_payload_bytes(result))

    def _activity(
        self, task: _AgentTask, state: str, *, force: bool = False,
        failure_category: str | None = None, worker: bool = False,
    ) -> None:
        """Decide an activity state under `lock` and queue its notification.

        A terminal state claimed by the worker (`worker=True`) counts only
        before the task's deadline; otherwise the coordinator finalizes it.
        Progress of one invocation is coalesced; its terminal notification
        supersedes progress still pending, so a receiver never gets an older
        state of the invocation after its terminal one."""
        callback = self._activity_callback
        lane = self._activity_lane
        # Snapshot at decision time: delivery may happen after a retry has
        # already changed the task (e.g. its prompt).
        details = (
            self._activity_details(task, state, failure_category)
            if callback is not None else None
        )
        terminal = state in _TERMINAL_ACTIVITY_STATES
        with task.lock:
            if task.activity_closed.is_set() and not force:
                return
            if task.terminal:
                return  # a terminal state is final: never a second one
            if terminal:
                if worker and time.monotonic() > task.deadline:
                    return  # too late: never accepted, the coordinator finalizes
                task.terminal = True
                task.terminal_state = (state, failure_category)
            if details is not None and lane is not None:
                self._post_activity(lane, callback, details, task.invocation_id, terminal)
        if terminal and task.changed is not None:
            task.changed.set()

    @staticmethod
    def _post_activity(
        lane: _DeliveryLane, callback: Callable[..., None], details: dict,
        invocation_id: str, terminal: bool,
    ) -> None:
        # The lane is FIFO, so nothing older than a terminal notification is
        # ever delivered after it. Only REDUNDANT progress (pure state
        # markers) is coalesced to the newest pending one per invocation
        # and dropped once the terminal state is queued; "thinking" carries
        # new information (the effective prompt of an attempt) and is kept.
        progress_key = ("progress", invocation_id)
        nbytes = _payload_bytes(details)
        if terminal:
            lane.post(
                lambda: callback(**details), key=("terminal", invocation_id),
                supersedes=lambda key: key == progress_key, payload_bytes=nbytes,
            )
        elif details.get("runtime_state") in _REDUNDANT_PROGRESS_STATES:
            lane.post(lambda: callback(**details), key=progress_key, payload_bytes=nbytes)
        else:
            lane.post(lambda: callback(**details), payload_bytes=nbytes)

    def _worker_terminal(
        self, task: _AgentTask, state: str, outcome: Any,
        failure_category: str | None = None,
    ) -> None:
        """Worker: publish the final outcome, then claim the terminal state.
        If the coordinator already finalized the task, or the deadline has
        passed, the claim is ignored and the outcome is recorded only as a
        late diagnosis addition."""
        with task.lock:
            task.worker_reported = True
            if not task.terminal:
                task.outcome = outcome
        self._activity(task, state, failure_category=failure_category, worker=True)
        with task.lock:
            late = task.terminal_state != (state, failure_category) or task.outcome is not outcome
        if late:
            self._late_addition(task, state, outcome)

    def _late_addition(self, task: _AgentTask, state: str, outcome: Any) -> None:
        """SUB_REQ_034: a later fact is appended as a labelled diagnosis
        addition; the final snapshot and its original cause stay unchanged."""
        run_id = task.run_id
        if not run_id:
            return
        received = time.time()
        error = str(getattr(outcome, "error", "") or "")
        kind = (
            "worker_ended_after_closure"
            if error.startswith("provider call abandoned") else f"late_{state}"
        )
        addition = {
            "invocation_id": task.invocation_id, "contributor": task.agent_id,
            "phase": task.phase, "kind": kind,
            "event_time": received, "received_time": received,
            "success": bool(getattr(outcome, "success", False)),
        }
        _DIAGNOSIS.update(run_id, lambda record: record["late_additions"].append(addition))

    @staticmethod
    def _begin_provider_call(task: _AgentTask) -> bool:
        """Worker: confirm the invocation is still live before it prepares a
        provider call. After closure no provider call (first attempt or
        retry) is prepared; the binding decision for gated bindings is the
        transport handover gate."""
        with task.lock:
            return not task.activity_closed.is_set()

    @staticmethod
    def _invoke_provider(task: _AgentTask, provider: LLMProvider) -> str | None:
        """Worker: call the provider unless the invocation was closed.

        For gated bindings (handover_boundary == HANDOVER_BOUNDARY) the
        binding guarantee is the transport gate: no request byte is handed
        over after closure, whatever happens between this check and the
        socket. For other bindings this claim is only a start decision --
        entry into complete() is neither observable nor preventable there,
        so no handover guarantee is claimed (UNVERIFIED_BOUNDARY)."""
        with task.lock:
            if task.activity_closed.is_set():
                return None
            task.provider_started = True
        return provider.complete(task.prompt)

    def _finalize(self, task: _AgentTask, failure_category: str) -> bool:
        """Coordinator: close `task` and make it finally failed, unless it
        already reached a terminal state (then that state and its published
        outcome stand). Returns whether this call finalized the task.

        Closure takes the task lock, which a gated handover holds only for
        one socket write bounded by the handover send timeout."""
        callback = self._activity_callback
        lane = self._activity_lane
        details = (
            self._activity_details(task, "failed", failure_category)
            if callback is not None else None
        )
        with task.lock:
            if task.terminal:
                return False
            task.activity_closed.set()
            task.terminal = True
            task.terminal_state = ("failed", failure_category)
            task.finalized_after_start = (
                bool(task.gate.handovers) if task.gate is not None else task.provider_started
            )
            if details is not None and lane is not None:
                self._post_activity(lane, callback, details, task.invocation_id, True)
        if task.changed is not None:
            task.changed.set()
        return True

    def _activity_details(
        self, task: _AgentTask, state: str, failure_category: str | None,
    ) -> dict | None:
        try:
            details = self._build_activity_details(task, state, failure_category)
        except Exception:
            # Observability must never change Council decisions or execution.
            logger.debug("Central Council activity projection failed", exc_info=True)
            return None
        details["invocation_id"] = task.invocation_id
        return details

    @staticmethod
    def _build_activity_details(
        task: _AgentTask, state: str, failure_category: str | None,
    ) -> dict:
        operation = {"phase1": "proposal", "phase2": "review"}.get(
            task.phase, task.phase,
        )
        details = dict(
            actor=f"Agent {task.agent_id}" if task.agent_id != "C" else "Chairman",
            actor_role=task.role,
            runtime_state=state,
            council_phase=task.phase,
            provider=task.config.provider,
            model=task.config.model,
            execution_identity=execution_identity(
                "chairman" if task.agent_id == "C" else f"council_agent_{task.agent_id.lower()}_{operation}",
                provider=task.config.provider, model=task.config.model,
                actor=task.agent_id, phase=task.phase,
            ),
        )
        if failure_category:
            details["failure_category"] = failure_category
        if state == "thinking" and task.prompt:
            details["effective_prompt"] = task.prompt
        return details

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def critical_diagnosis(self) -> dict[str, Any] | None:
        """Critical diagnosis of this instance's latest run, independent of
        any callback (SUB_REQ_035): volatile registry while retained."""
        return _DIAGNOSIS.get(self._run_id) if self._run_id else None

    def operating_profile(self) -> dict[str, Any]:
        """The finite time/resource profile of one evaluate(), declared
        before admission (SUB_REQ_039). PROVISIONAL values."""
        members = [_get_agent_config(self._config, agent) for agent in ("A1", "A2", "A3")]
        contributor = max(_call_budget(config) for config in members)
        return DEFAULT_PROFILE.declare({
            "phase1": contributor, "phase2": contributor,
            "phase3": _call_budget(self._config.chairman),
        })

    def evaluate(self, council_input: CouncilInput) -> CouncilResult:
        """Run the full multi-agent council and return the synthesised result.

        The public deadline starts here, before admission (SUB_REQ_039).
        Admission reserves the diagnosis envelope and, with a trace store, a
        persistence slot; if either is exhausted it raises
        CouncilResourceError before any provider handover (SUB_REQ_036/038).
        Admission is atomic per instance: an overlapping call on the same
        instance is refused with CouncilResourceError (SUB_REQ_038).

        The admitted input is booked in the run's ledger at admission; if
        the pool cannot take it, admission is refused like any other
        exhausted capacity. An unsupported project identity is refused with
        a fail-closed result (SUB_REQ_036).

        An admission refusal is a new CouncilResourceError raised outside
        any handler: it carries only its message, no traceback frame or
        exception context of the service that could keep the input.

        Raises:
            CouncilResourceError: Admission refused (no provider work).
            CouncilFailedError: If too few agents succeeded to produce
                a meaningful result.
        """
        call: dict[str, Any] = {}
        refusal: str | None = None
        try:
            return self._evaluate_public(council_input, call)
        except CouncilResourceError as error:
            if "ledger" in call:
                call["ledger"].bind(error)
                raise
            refusal = str(error)
        except BaseException as error:
            ledger = call.get("ledger")
            if ledger is not None:
                # The traceback keeps the run's data: it stays booked as
                # long as the exception exists.
                ledger.bind(error)
            else:
                # Never admitted (e.g. the run thread could not start): the
                # service keeps no reference to the input in its frames.
                _detach_input(error, council_input, stop=self._run_body.__code__)
                council_input = None
            raise
        finally:
            release = call.pop("release_public", None)
            if release is not None:
                release()
        council_input = None
        raise CouncilResourceError(refusal)

    def _evaluate_public(self, council_input: CouncilInput, call: dict[str, Any]) -> CouncilResult:
        entered = time.monotonic()
        # One instance carries the state of one run (identity, call records,
        # subscriptions). An overlapping call on the SAME instance --
        # concurrent, or while an earlier body is still busy past its
        # deadline -- is refused atomically before anything is reserved.
        # This is no service-wide limit: other instances are admitted
        # concurrently up to the process-wide capacities.
        with self._admission:
            if self._occupants:
                raise CouncilResourceError(
                    "Council instance busy with another run (overlapping call or an "
                    "earlier run past its deadline): admission refused before any "
                    "provider handover"
                )
            self._occupants = 2  # the public call and the run body
        try:
            run, done, box = self._admit_and_start(council_input, entered, call)
        except BaseException:
            self._vacate(2)
            raise
        registry = _DIAGNOSIS
        profile = run.profile
        try:
            work_limit = run.public_deadline - profile["finalization_seconds"]
            done.wait(max(0.0, work_limit - time.monotonic()))
            with run.lock:
                if not done.is_set() and run.finalizer is None:
                    run.finalizer = "public"
                    run.closed = True
            if run.finalizer == "public":
                return self._finalize_public_timeout(council_input, run)
            done.wait(max(0.0, run.public_deadline - time.monotonic()))
            if "error" in box:
                raise box["error"]
            if "result" in box:
                return box["result"]
            # Finalization itself overran the public deadline: fail closed.
            with run.lock:
                run.closed = True
            return self._bind_to_envelope(self._timeout_result(council_input, run), run.run_id)
        finally:
            if run.persistence_reserved:
                _PERSISTENCE.release()
                run.persistence_reserved = False
            registry.update(run.run_id, lambda record: record.update(
                notifications=self.notification_state(),
            ))
            registry.complete(run.run_id)
            self._vacate(1)

    def _vacate(self, parties: int = 1) -> None:
        with self._admission:
            self._occupants -= parties

    def _admit_and_start(
        self, council_input: CouncilInput, entered: float, call: dict[str, Any],
    ) -> tuple[_CouncilRun, threading.Event, dict[str, Any]]:
        """Admission and run-thread start, all or nothing: every reservation
        taken here is returned if a later step -- including the start of the
        run thread -- fails (SUB_REQ_036/038)."""
        self._run_id = f"council-{uuid.uuid4().hex[:12]}"
        # The previous run's data is dropped first, then its charges.
        self._call_records.clear()
        self._effective_prompts.clear()
        self._release_held()
        profile = self.operating_profile()
        run = _CouncilRun(
            run_id=self._run_id, entered_at=entered,
            public_deadline=entered + profile["public_total_seconds"], profile=profile,
        )
        registry = _DIAGNOSIS
        acquired: list[Callable[[], None]] = []

        def undo() -> None:
            for release in reversed(acquired):
                release()
            acquired.clear()

        def refuse(what: str) -> CouncilResourceError:
            undo()
            return CouncilResourceError(
                f"Council {what} capacity exhausted: admission refused before any provider handover"
            )

        def release_persistence() -> None:
            if run.persistence_reserved:
                run.persistence_reserved = False
                _PERSISTENCE.release()

        if not _RUN_SLOTS.reserve():
            raise refuse("run")
        acquired.append(_RUN_SLOTS.release)
        if self._trace_dir:
            if not _PERSISTENCE.reserve():
                raise refuse("persistence")
            run.persistence_reserved = True
            acquired.append(release_persistence)
        try:
            registry.admit(run.run_id, profile)
        except CouncilResourceError:
            raise refuse("diagnosis") from None
        acquired.append(lambda: registry.discard(run.run_id))
        # This instance keeps the run's call records until its next run or
        # its collection; they are charged inside the run's envelope, which
        # therefore stays booked past retention while they are held.
        hold = registry.hold(run.run_id)
        if hold is not None:
            self._held_charges.append(("call_records", hold))
            acquired.append(lambda: self._release_held("call_records"))
        # The input is held by the public call and the run body from here
        # on: both own the run's ledger, which books it first. An input the
        # pool cannot take refuses admission -- no run, no provider work.
        ledger = _RunLedger(registry)
        release_public = ledger.owner()
        release_body = ledger.owner()
        acquired.append(release_public)
        acquired.append(release_body)
        nbytes = _text_bytes(repr(council_input))
        if not ledger.book(nbytes):
            raise refuse(f"storage (input of {nbytes} bytes)")
        run.ledger = ledger
        call["ledger"] = ledger
        call["release_public"] = release_public
        self._run = run

        done = threading.Event()
        box: dict[str, Any] = {}
        # The body takes the input out of this holder: no closure cell or
        # frame of the starting side keeps it beyond the run.
        holder = [council_input]
        thread = threading.Thread(
            target=self._run_body, args=(holder, box, done, ledger, release_body),
            name=f"council-run-{run.run_id}", daemon=True,
        )
        self._body_thread = thread
        try:
            thread.start()
        except BaseException:
            # Nothing ran: return the run slot, the persistence slot, the
            # diagnosis envelope and the input booking instead of losing them.
            self._body_thread = None
            self._run = None
            call.pop("ledger", None)
            call.pop("release_public", None)
            holder.clear()
            undo()
            raise
        return run, done, box

    def _run_body(
        self, holder: list, box: dict[str, Any], done: threading.Event,
        ledger: _RunLedger, release_body: Callable[[], None],
    ) -> None:
        """Run thread. A body exception is handed to the public caller (or,
        after the public deadline, dropped with the box); its traceback keeps
        the run's data, so the ledger is bound to the exception."""
        try:
            box["result"] = self._evaluate_admitted(holder.pop())
        except BaseException as exc:
            ledger.bind(exc)
            box["error"] = exc
        finally:
            done.set()
            _RUN_SLOTS.release()
            self._vacate(1)
            release_body()

    def _hold_charge(self, kind: str, registry: Any, nbytes: int) -> None:
        released = [False]

        def release() -> None:
            if not released[0]:
                released[0] = True
                registry.release_extra(nbytes)

        self._held_charges.append((kind, release))

    def _release_held(self, kind: str | None = None) -> None:
        EngineeringCouncil._release_charges(self._held_charges, kind)

    @staticmethod
    def _release_charges(charges: list, kind: str | None) -> None:
        keep = []
        for entry in charges:
            if kind is None or entry[0] == kind:
                entry[1]()
            else:
                keep.append(entry)
        charges[:] = keep

    # A result's persistence_state is set after its charge was taken; the
    # longest state ("not_configured") bounds that growth.
    _RESULT_STATE_MARGIN = len("not_configured")

    def _charge_result(self, result: CouncilResult) -> Callable[[], None] | None:
        """Charge a result the service hands out (and e.g. a Web session
        keeps across requests) to the pool for as long as it exists. Returns
        the release, or None if the pool cannot take it."""
        nbytes = len(repr(result).encode("utf-8")) + self._RESULT_STATE_MARGIN
        registry = _DIAGNOSIS
        if not registry.reserve_extra(nbytes):
            message = f"result of {nbytes} bytes not retainable: storage capacity exhausted"
            registry.update(self._run_id, lambda record: record["resource_errors"].append(message))
            return None
        released = [False]

        def release() -> None:
            if not released[0]:
                released[0] = True
                registry.release_extra(nbytes)

        return release

    @staticmethod
    def _bind_result(result: CouncilResult, release: Callable[[], None]) -> CouncilResult:
        """The charge lives exactly as long as the result object: whoever
        keeps it (workflow, Web session, caller) keeps it charged."""
        weakref.finalize(result, release)
        return result

    def _bind_to_envelope(self, result: CouncilResult, run_id: str) -> CouncilResult:
        """A fail-closed result is charged inside its run's reserved
        envelope (no new reservation that could fail): the envelope is held
        while the result exists and the record is fitted around it."""
        registry = _DIAGNOSIS
        hold = registry.hold(run_id)
        nbytes = len(repr(result).encode("utf-8"))
        if hold is None:
            # The envelope is gone (no holder kept it): the bounded result
            # is charged on its own instead of being held uncharged.
            release = self._charge_result(result)
            if release is None:
                logger.warning(f"Council run {run_id}: fail-closed result of {nbytes} "
                               "bytes returned without a charge (storage capacity exhausted)")
                return result
            return self._bind_result(result, release)
        registry.update(run_id, lambda record: record.update(
            _retained_result_bytes=record.get("_retained_result_bytes", 0) + nbytes))
        return self._bind_result(result, hold)

    def _storage_refused_result(
        self, council_input: CouncilInput, refused: CouncilResult,
    ) -> CouncilResult:
        """Fail closed when a deliberated result cannot be charged: the
        service keeps nothing uncharged (SUB_REQ_036/038). The replacement
        is built within its envelope share, so the refused large data is not
        kept anyway."""
        return self._envelope_result(
            self._run_id, council_input.detected_stack or "",
            id=refused.id or self._run_id, project_id=council_input.project_id,
            agent_errors=("Council: result retention capacity exhausted; "
                          "result not retained (scope storage)",),
            chairman_error=None, council_complete=False, council_degraded=False,
            total_llm_calls=len(self._call_records),
        )

    # A fail-closed result lives inside its run's reserved envelope (no new
    # reservation that could fail). Each one is bounded to this share, so
    # even two of them (public timeout plus a late body result) beside the
    # call-record share leave room for the critical record.
    _ENVELOPE_RESULT_BYTES = 8 * 1024
    _STACK_CUT_MARK = "...[truncated: diagnosis reservation]"

    def _envelope_result(self, run_id: str, stack: str, **fields: Any) -> CouncilResult:
        """Build a fail-closed result that fits its envelope share: a long
        detected stack is cut in UTF-8 bytes with a visible marker and the
        cut is recorded, never silently (SUB_REQ_036)."""
        registry = _DIAGNOSIS
        share = min(self._ENVELOPE_RESULT_BYTES, registry.envelope_bytes // 8)
        share -= self._RESULT_STATE_MARGIN
        result = CouncilResult(stack=stack, **fields)
        size = len(repr(result).encode("utf-8"))
        if size <= share:
            return result
        data = stack.encode("utf-8")
        cap = len(data)
        while size > share and cap > 0:
            cap = max(0, cap - (size - share))
            kept = data[:cap].decode("utf-8", "ignore") + self._STACK_CUT_MARK if cap else ""
            result = CouncilResult(stack=kept, **fields)
            size = len(repr(result).encode("utf-8"))
        message = (f"fail-closed result: detected stack cut from {len(data)} to "
                   f"{len(result.stack.encode('utf-8'))} bytes to fit the diagnosis reservation")
        if size > share:
            message += f"; result of {size} bytes still exceeds its share of {share} bytes"
        registry.update(run_id, lambda record: record["resource_errors"].append(message))
        return result

    def _retain_prompt(self, key: str, prompt: str) -> None:
        """Keep an effective-prompt copy for the result projection only if
        its bytes can be charged to the finite pool (SUB_REQ_036/038);
        otherwise the omission is recorded visibly."""
        nbytes = len(prompt.encode("utf-8"))
        registry = _DIAGNOSIS
        if registry.reserve_extra(nbytes):
            self._hold_charge("prompt", registry, nbytes)
            self._effective_prompts[key] = prompt
            return
        message = f"effective prompt copy of {key} not retained: storage capacity exhausted"
        registry.update(self._run_id, lambda record: record["resource_errors"].append(message))

    _RECORD_SHARE_BYTES = 24 * 1024  # kept free for the critical record

    def _fit_retained(self, summary: dict[str, Any]) -> bool:
        """Keep retained call records within the envelope share left beside
        the critical record: texts are cut in UTF-8 bytes with a visible
        marker, never silently. Returns whether anything was compacted."""
        share = DEFAULT_PROFILE.diagnosis_envelope_bytes - self._RECORD_SHARE_BYTES
        registry = _DIAGNOSIS
        share = min(share, registry.envelope_bytes - self._RECORD_SHARE_BYTES)

        def size() -> int:
            return sum(len(repr(item).encode("utf-8")) for item in self._call_records)

        if size() <= share:
            return False
        mark = "...[truncated: diagnosis reservation]"
        for cap in (300, 100, 0):
            def cut(text: str | None) -> str | None:
                if not text:
                    return text
                data = text.encode("utf-8")
                if len(data) <= cap:
                    return text
                return data[:cap].decode("utf-8", "ignore") + mark
            self._call_records = [
                replace(item, error=cut(item.error),
                        raw_response_snippet=cut(item.raw_response_snippet) or "",
                        structured_output_summary=cut(item.structured_output_summary) or "")
                for item in self._call_records
            ]
            if size() <= share:
                break
        return True

    def _claim_finalization(self) -> bool:
        """Body: finalize only if the public side has not taken over."""
        run = self._run
        if run is None:
            return True
        with run.lock:
            if run.finalizer is None:
                run.finalizer = "body"
                return True
            return False

    def _timeout_result(self, council_input: CouncilInput, run: _CouncilRun) -> CouncilResult:
        error = "Council: public deadline reached before completion (scope council)"
        # An unsupported identity is refused by the body, never carried.
        project_id = ("" if project_identity_error(council_input.project_id)
                      else council_input.project_id)
        return self._envelope_result(
            run.run_id, council_input.detected_stack or "",
            id=run.run_id, project_id=project_id,
            agent_errors=(error,), chairman_error=None,
            council_complete=False, council_degraded=False,
            total_llm_calls=len(self._call_records),
        )

    def _finalize_public_timeout(self, council_input: CouncilInput, run: _CouncilRun) -> CouncilResult:
        """Public deadline for Council work reached while the body is still
        busy (e.g. in synchronous preparation): the run is closed, a
        fail-closed result is returned in time and recorded; the body can
        no longer start phases, hand over requests or finalize."""
        result = self._bind_to_envelope(self._timeout_result(council_input, run), run.run_id)
        _DIAGNOSIS.update(run.run_id, lambda record: record["resource_errors"].append(
            "public deadline reached before completion; run closed"))
        self._record_outcome(ProposalSet(), (), result)
        return result

    def _refuse_input(self, reason: str) -> CouncilResult:
        """Fail closed on an unsupported input before any provider handover:
        the refusal is recorded and returned visibly; the refused identity is
        neither kept nor shortened (the result carries none) (SUB_REQ_036)."""
        message = f"Council: {reason} before any provider handover (scope input)"
        _DIAGNOSIS.update(self._run_id, lambda record: record["resource_errors"].append(message))
        result = self._bind_to_envelope(self._envelope_result(
            self._run_id, "", id=self._run_id, project_id="", agent_errors=(message,),
            chairman_error=None, council_complete=False, council_degraded=False,
            total_llm_calls=0,
        ), self._run_id)
        if self._claim_finalization():
            self._record_outcome(ProposalSet(), (), result)
        return result

    def _evaluate_admitted(self, council_input: CouncilInput) -> CouncilResult:
        refusal = project_identity_error(council_input.project_id)
        if refusal is not None:
            return self._refuse_input(refusal)
        started = datetime.now()

        phase1_start = time.monotonic()
        proposal_set = self._phase1_independent_proposals(council_input)
        phase1_ms = (time.monotonic() - phase1_start) * 1000
        proposal_set = ProposalSet(
            proposals=proposal_set.proposals,
            phase_duration_ms=phase1_ms,
            agent_errors=proposal_set.agent_errors,
        )

        vote_sets: tuple[AgentVoteSet, ...] = ()
        vote_errors: tuple[str, ...] = ()
        if proposal_set.proposals:
            vote_sets, vote_errors = self._phase2_cross_review(proposal_set)

        chairman_error: str | None = None
        council_result: CouncilResult

        if not proposal_set.proposals:
            chairman_error = "Keine Variantenvorschläge aus Phase 1 — keine Agenten erfolgreich."
            council_result = self._build_empty_result(council_input, chairman_error)
        else:
            try:
                council_result = self._phase3_chairman_synthesis(
                    proposal_set, vote_sets, council_input
                )
            except Exception as exc:
                chairman_error = str(exc)
                council_result = self._build_empty_result(council_input, chairman_error)

        total_errors = list(proposal_set.agent_errors)
        total_errors.extend(vote_errors)
        if chairman_error:
            total_errors.append(f"Chairman: {chairman_error}")

        quorum = self._evaluate_quorum(
            proposal_set,
            vote_sets,
            council_result,
            chairman_error,
            tuple(total_errors),
        )

        if not council_result.variants and not proposal_set.agent_errors:
            council_result = CouncilResult(
                id=self._run_id,
                project_id=council_input.project_id,
                stack=council_input.detected_stack or "",
                agent_errors=tuple(total_errors),
                chairman_error=chairman_error,
                council_complete=False,
                council_degraded=False,
                total_llm_calls=len(self._call_records),
            )

        council_result = CouncilResult(
            id=council_result.id or self._run_id,
            project_id=council_result.project_id or council_input.project_id,
            stack=council_result.stack or council_input.detected_stack or "",
            variants=council_result.variants,
            rejected_variants=council_result.rejected_variants,
            recommendation=council_result.recommendation,
            reasoning=council_result.reasoning,
            merge_decisions=council_result.merge_decisions,
            agent_errors=tuple(total_errors),
            chairman_error=chairman_error,
            council_complete=quorum.complete,
            council_degraded=quorum.degraded,
            total_llm_calls=len(self._call_records),
        )

        # The result will be service-held (returned, kept by the workflow
        # or a Web session): charge it before it becomes final. If it cannot
        # be charged the run fails closed with a result inside its envelope.
        release_result = self._charge_result(council_result)
        if release_result is None:
            council_result = self._storage_refused_result(council_input, council_result)

        if not self._claim_finalization():
            # The public deadline already closed this run; its fail-closed
            # result stands and this late outcome changes nothing. The late
            # result stays charged for as long as it still exists.
            if release_result is not None:
                council_result = self._bind_result(council_result, release_result)
            else:
                council_result = self._bind_to_envelope(council_result, self._run_id)
            return council_result

        try:
            self._emit_structured_results(
                council_input, proposal_set, vote_sets, council_result,
            )

            # The critical diagnosis is recorded BEFORE persisting, so the
            # confirmed file carries the lifecycle causes (SUB_REQ_036 reload).
            self._record_outcome(proposal_set, vote_sets, council_result)
            persistence_state = "not_configured"
            if self._trace_dir:
                persistence_state = self._persist_trace(
                    council_input, proposal_set, vote_sets, council_result, started,
                )
            council_result = replace(council_result, persistence_state=persistence_state)
            if release_result is not None:
                council_result = self._bind_result(council_result, release_result)
            else:
                council_result = self._bind_to_envelope(council_result, self._run_id)
            self._record_outcome(proposal_set, vote_sets, council_result)
        except BaseException:
            # No result is handed out, but the propagated traceback (frame
            # locals) keeps it alive: its charge lives exactly as long as the
            # result object, never shorter (SUB_REQ_036).
            if release_result is not None:
                self._bind_result(council_result, release_result)
            else:
                self._bind_to_envelope(council_result, self._run_id)
            raise
        return council_result

    def _record_outcome(
        self, proposal_set: ProposalSet, vote_sets: tuple[AgentVoteSet, ...],
        council_result: CouncilResult,
    ) -> None:
        """Critical final snapshot summary (SUB_REQ_034/035), bounded."""
        summary = {
            "result_id": council_result.id,
            "council_complete": council_result.council_complete,
            "council_degraded": council_result.council_degraded,
            "accepted_contributors": {
                "phase1": sorted({p.agent_id for p in proposal_set.proposals}),
                "phase2": sorted({v.agent_id for v in vote_sets}),
            },
            "variant_ids": [v.id for v in council_result.variants][:50],
            "recommendation": council_result.recommendation,
            "chairman_error": (council_result.chairman_error or "")[:500] or None,
            "decision_errors": [error[:500] for error in council_result.agent_errors[:20]],
        }

        # Service-held call records of this run are charged to the run's
        # own reserved envelope together with its critical record.
        compacted = self._fit_retained(summary)
        retained = sum(len(repr(item).encode("utf-8")) for item in self._call_records)

        def change(record: dict[str, Any]) -> None:
            record["result_id"] = council_result.id
            record["outcome"] = summary
            record["retained_call_record_bytes"] = retained
            record["_retained_bytes"] = retained
            if compacted and "truncated:call_record_texts" not in record["omitted"]:
                record["omitted"].append("truncated:call_record_texts")
                record["size_exceeded"] = True
            record["persistence"].setdefault("state", council_result.persistence_state)
            if record["persistence"].get("state") == "not_requested":
                record["persistence"]["state"] = council_result.persistence_state

        _DIAGNOSIS.update(self._run_id, change)

    @staticmethod
    def _evaluate_quorum(
        proposal_set: ProposalSet,
        vote_sets: tuple[AgentVoteSet, ...],
        council_result: CouncilResult,
        chairman_error: str | None,
        unresolved_errors: tuple[str, ...],
    ) -> _CouncilQuorum:
        """Evaluate the single authoritative Council completion policy."""
        phase1_agents = len({proposal.agent_id for proposal in proposal_set.proposals})
        phase2_agents = len({vote_set.agent_id for vote_set in vote_sets})
        variant_ids = {variant.id for variant in council_result.variants}
        chairman_valid = (
            chairman_error is None
            and bool(variant_ids)
            and council_result.recommendation in variant_ids
        )
        complete = (
            phase1_agents >= 2
            and phase2_agents >= 2
            and chairman_valid
        )
        normal = (
            complete
            and phase1_agents == 3
            and phase2_agents == 3
            and not unresolved_errors
        )
        return _CouncilQuorum(
            complete=complete,
            degraded=complete and not normal,
            phase1_agents=phase1_agents,
            phase2_agents=phase2_agents,
        )

    def _emit_structured_results(
        self, council_input: CouncilInput, proposal_set: ProposalSet,
        vote_sets: tuple[AgentVoteSet, ...], council_result: CouncilResult,
    ) -> None:
        """Emit bounded projections only; never raw responses or reasoning fields.

        Results go to their subscription's serial, bounded delivery lane and
        are awaited only while the receiver makes progress and only inside
        the Council's budget: a blocked result receiver cannot hold
        evaluate() (SUB_REQ_037)."""
        self._result_lane = self._result_subscription
        try:
            self._project_structured_results(
                council_input, proposal_set, vote_sets, council_result,
            )
        finally:
            # The prompt copies served only this projection: drop them and
            # their charges, so nothing uncharged stays service-held.
            self._effective_prompts.clear()
            self._release_held("prompt")
            lane, self._result_lane = self._result_lane, None
            until = time.monotonic() + _DELIVERY_SETTLE_LIMIT_SECONDS
            if self._run is not None:
                until = min(until, self._run.public_deadline - self._run.profile["finalization_seconds"])
            _settle_deliveries([lane], until=until)

    def _project_structured_results(
        self, council_input: CouncilInput, proposal_set: ProposalSet,
        vote_sets: tuple[AgentVoteSet, ...], council_result: CouncilResult,
    ) -> None:
        def duration_for(agent_id, phase):
            return sum(
                record.duration_ms for record in self._call_records
                if record.agent_id == agent_id and record.phase == phase
            )

        def typed(data, data_type, source, destination):
            return {
                "type": data_type, "interface": "internal",
                "source": source, "destination": destination, "data": data,
            }

        requirements = [{
            "id": item.id, "name": item.name, "type": item.type,
            "purpose": item.purpose, "required": item.required,
        } for item in council_input.requirements]
        phase1_x_info = {
            "requirement_count": len(requirements),
            "stack": council_input.detected_stack or "",
        }
        phase1_x_verbose = {
            **phase1_x_info, "requirements": requirements,
            "project_files": list(council_input.project_files),
            "validation_warnings": list(council_input.validation_warnings),
        }

        proposal_agents = {proposal.agent_id for proposal in proposal_set.proposals}
        for proposal in proposal_set.proposals:
            tools = [{
                "requirement_ref": tool.requirement_ref, "name": tool.name,
                "type": tool.type, "version": tool.version,
                "purpose": tool.purpose, "depends_on": list(tool.depends_on),
                "state": tool.state,
                "environment_constraint": tool.environment_constraint,
            } for tool in proposal.toolchain]
            info = {
                "summary": proposal.description or proposal.name,
                "name": proposal.name, "risks": list(proposal.risks[:3]),
                "constraints": list(proposal.disadvantages[:3]),
            }
            verbose = {**info,
                "variant_id": proposal.variant_id,
                "environment": proposal.environment,
                "capabilities": list(proposal.capabilities),
                "toolchain": [{"name": item["name"], "type": item["type"],
                               "state": item["state"], "purpose": item["purpose"]}
                              for item in tools],
                "advantages": list(proposal.advantages),
                "feasibility": proposal.feasibility,
            }
            very_verbose = {**verbose,
                "hardware_target": proposal.hardware_target,
                "connection": proposal.connection,
                "confidence": proposal.confidence,
                "toolchain": tools,
                "disadvantages": list(proposal.disadvantages),
            }
            prompt_key = f"{proposal.agent_id}:phase1"
            if prompt_key in self._effective_prompts:
                very_verbose["effective_prompt"] = self._effective_prompts[prompt_key]
            config = _get_agent_config(self._config, proposal.agent_id)
            self._result(
                actor=f"Agent {proposal.agent_id}", actor_role=proposal.agent_role,
                council_phase="phase1", result_kind="proposal",
                provider=config.provider, model=config.model,
                duration_ms=duration_for(proposal.agent_id, "phase1"),
                summary=f"{proposal.agent_id} proposal: {proposal.name}",
                council_output={"info": info, "verbose": verbose,
                                "very_verbose": very_verbose},
                interface_data={
                    "normal": {"summary": "Proposal input produced a structured proposal."},
                    "info": {"x": typed(phase1_x_info, "council_input", "engineering_council", f"council_agent_{proposal.agent_id.lower()}_proposal"),
                             "f": execution_identity(f"council_agent_{proposal.agent_id.lower()}_proposal", provider=config.provider, model=config.model, actor=proposal.agent_id, phase="phase1"),
                             "y": typed({"available": True, "name": proposal.name}, "proposal", f"council_agent_{proposal.agent_id.lower()}_proposal", "engineering_council")},
                    "verbose": {"x": typed(phase1_x_verbose, "council_input", "engineering_council", f"council_agent_{proposal.agent_id.lower()}_proposal"), "f": execution_identity(f"council_agent_{proposal.agent_id.lower()}_proposal", provider=config.provider, model=config.model, actor=proposal.agent_id, phase="phase1"), "y": typed(verbose, "proposal", f"council_agent_{proposal.agent_id.lower()}_proposal", "engineering_council")},
                    "very_verbose": {"x": typed(phase1_x_verbose, "council_input", "engineering_council", f"council_agent_{proposal.agent_id.lower()}_proposal"), "f": execution_identity(f"council_agent_{proposal.agent_id.lower()}_proposal", provider=config.provider, model=config.model, actor=proposal.agent_id, phase="phase1"), "y": typed(very_verbose, "proposal", f"council_agent_{proposal.agent_id.lower()}_proposal", "engineering_council")},
                },
            )
        for agent_id in sorted(set(AGENT_ROLES) - proposal_agents):
            config = _get_agent_config(self._config, agent_id)
            empty = {"summary": "No usable structured proposal produced."}
            # CLAUDE-ADC-COUNCIL-DIAGNOSTIC-TRACE-INTEGRATION-FIX-001:
            # fold the bounded zero-retained-proposal branch evidence
            # (see _phase1_independent_proposals()/_build_zero_proposal_
            # diagnostic()) into this SAME, already-existing central
            # DiagnosticTrace event -- never a second, parallel
            # diagnostic sink. Present ONLY in the "verbose"/
            # "very_verbose" projections (DiagnosticDetailLevel.VERBOSE
            # and above); "info" stays the existing minimal summary so
            # NORMAL/INFO never expose it (render_diagnostic_trace_
            # event()'s own level-gated _terminal_projection() picks
            # "info" at INFO and "verbose" at VERBOSE+ -- see that
            # function's own preference order).
            diagnostic = self._zero_proposal_diagnostics.get(agent_id)
            verbose_output = {**empty, **diagnostic} if diagnostic else dict(empty)
            self._result(
                actor=f"Agent {agent_id}", actor_role=AGENT_ROLES[agent_id],
                council_phase="phase1", result_kind="proposal",
                provider=config.provider, model=config.model,
                duration_ms=duration_for(agent_id, "phase1"),
                summary=empty["summary"],
                council_output={"info": empty, "verbose": verbose_output,
                                "very_verbose": verbose_output},
                interface_data={
                    "normal": {"summary": "Proposal input produced no usable structured proposal."},
                    "info": {"x": typed(phase1_x_info, "council_input", "engineering_council", f"council_agent_{agent_id.lower()}_proposal"), "f": execution_identity(f"council_agent_{agent_id.lower()}_proposal", provider=config.provider, model=config.model, actor=agent_id, phase="phase1"), "y": typed({"available": False}, "proposal", f"council_agent_{agent_id.lower()}_proposal", "engineering_council")},
                    "verbose": {"x": typed(phase1_x_verbose, "council_input", "engineering_council", f"council_agent_{agent_id.lower()}_proposal"), "f": execution_identity(f"council_agent_{agent_id.lower()}_proposal", provider=config.provider, model=config.model, actor=agent_id, phase="phase1"), "y": typed({"available": False}, "proposal", f"council_agent_{agent_id.lower()}_proposal", "engineering_council")},
                    "very_verbose": {"x": typed(phase1_x_verbose, "council_input", "engineering_council", f"council_agent_{agent_id.lower()}_proposal"), "f": execution_identity(f"council_agent_{agent_id.lower()}_proposal", provider=config.provider, model=config.model, actor=agent_id, phase="phase1"), "y": typed({"available": False}, "proposal", f"council_agent_{agent_id.lower()}_proposal", "engineering_council")},
                },
            )

        review_agents = {vote_set.agent_id for vote_set in vote_sets}
        proposals_for_review = [{
            "variant_id": item.variant_id, "name": item.name,
            "description": item.description, "environment": item.environment,
            "capabilities": list(item.capabilities), "risks": list(item.risks),
        } for item in proposal_set.proposals]
        for vote_set in vote_sets:
            reviews = [{
                "variant_id": vote.variant_id,
                "would_recommend": vote.would_recommend,
                "concerns": list(vote.concerns), "scores": vote.scores,
            } for vote in vote_set.votes]
            info_reviews = [{
                "variant_id": item["variant_id"],
                "would_recommend": item["would_recommend"],
                "concerns": item["concerns"][:3],
            } for item in reviews]
            config = _get_agent_config(self._config, vote_set.agent_id)
            review_very_verbose = {
                "summary": f"Reviewed {len(reviews)} variants",
                "reviews": reviews,
            }
            prompt_key = f"{vote_set.agent_id}:phase2"
            if prompt_key in self._effective_prompts:
                review_very_verbose["effective_prompt"] = self._effective_prompts[prompt_key]
            self._result(
                actor=f"Agent {vote_set.agent_id}", actor_role=vote_set.agent_role,
                council_phase="phase2", result_kind="review",
                provider=config.provider, model=config.model,
                duration_ms=duration_for(vote_set.agent_id, "phase2"),
                summary=f"{vote_set.agent_id} reviewed {len(reviews)} variants",
                council_output={
                    "info": {"summary": f"Reviewed {len(reviews)} variants",
                             "reviews": info_reviews},
                    "verbose": {"summary": f"Reviewed {len(reviews)} variants",
                                "reviews": reviews},
                    "very_verbose": review_very_verbose,
                },
                interface_data={
                    "normal": {"summary": "Proposal variants produced a structured review."},
                    "info": {"x": typed({"proposal_count": len(proposals_for_review)}, "proposal_set", "engineering_council", f"council_agent_{vote_set.agent_id.lower()}_review"),
                             "f": execution_identity(f"council_agent_{vote_set.agent_id.lower()}_review", provider=config.provider, model=config.model, actor=vote_set.agent_id, phase="phase2"),
                             "y": typed({"review_count": len(reviews)}, "review_set", f"council_agent_{vote_set.agent_id.lower()}_review", "engineering_council")},
                    "verbose": {"x": typed({"proposals": proposals_for_review}, "proposal_set", "engineering_council", f"council_agent_{vote_set.agent_id.lower()}_review"),
                                "f": execution_identity(f"council_agent_{vote_set.agent_id.lower()}_review", provider=config.provider, model=config.model, actor=vote_set.agent_id, phase="phase2"),
                                "y": typed({"reviews": info_reviews}, "review_set", f"council_agent_{vote_set.agent_id.lower()}_review", "engineering_council")},
                    "very_verbose": {"x": typed({"proposals": proposals_for_review}, "proposal_set", "engineering_council", f"council_agent_{vote_set.agent_id.lower()}_review"),
                                     "f": execution_identity(f"council_agent_{vote_set.agent_id.lower()}_review", provider=config.provider, model=config.model, actor=vote_set.agent_id, phase="phase2"),
                                     "y": typed({"reviews": reviews}, "review_set", f"council_agent_{vote_set.agent_id.lower()}_review", "engineering_council")},
                },
            )
        for agent_id in sorted(set(AGENT_ROLES) - review_agents):
            config = _get_agent_config(self._config, agent_id)
            empty = {"summary": "No usable structured review produced."}
            self._result(
                actor=f"Agent {agent_id}", actor_role=AGENT_ROLES[agent_id],
                council_phase="phase2", result_kind="review",
                provider=config.provider, model=config.model,
                duration_ms=duration_for(agent_id, "phase2"),
                summary=empty["summary"],
                council_output={"info": empty, "verbose": empty,
                                "very_verbose": empty},
                interface_data={
                    "normal": {"summary": "Proposal variants produced no usable structured review."},
                    "info": {"x": typed({"proposal_count": len(proposals_for_review)}, "proposal_set", "engineering_council", f"council_agent_{agent_id.lower()}_review"),
                             "f": execution_identity(f"council_agent_{agent_id.lower()}_review", provider=config.provider, model=config.model, actor=agent_id, phase="phase2"),
                             "y": typed({"available": False}, "review_set", f"council_agent_{agent_id.lower()}_review", "engineering_council")},
                    "verbose": {"x": typed({"proposals": proposals_for_review}, "proposal_set", "engineering_council", f"council_agent_{agent_id.lower()}_review"),
                                "f": execution_identity(f"council_agent_{agent_id.lower()}_review", provider=config.provider, model=config.model, actor=agent_id, phase="phase2"),
                                "y": typed({"available": False}, "review_set", f"council_agent_{agent_id.lower()}_review", "engineering_council")},
                    "very_verbose": {"x": typed({"proposals": proposals_for_review}, "proposal_set", "engineering_council", f"council_agent_{agent_id.lower()}_review"),
                                     "f": execution_identity(f"council_agent_{agent_id.lower()}_review", provider=config.provider, model=config.model, actor=agent_id, phase="phase2"),
                                     "y": typed({"available": False}, "review_set", f"council_agent_{agent_id.lower()}_review", "engineering_council")},
                },
            )

        selected = next(
            (variant for variant in council_result.variants
             if variant.id == council_result.recommendation), None,
        )
        selected_name = selected.name if selected else None
        council_status = (
            "degraded" if council_result.council_degraded
            else "complete" if council_result.council_complete
            else "incomplete"
        )
        # CLAUDE-E2E-NIO-011A, Part 3: Real-System-E2E #6 exposed that a
        # concrete, already-computed council_result.chairman_error was
        # silently never surfaced here -- the human only ever saw the
        # generic "No final recommendation produced." fallback below,
        # even though a rich, safe, per-variant rejection reason already
        # existed internally (see the 010A completeness check and the
        # other _parse_chairman_result()/_phase3_chairman_synthesis()
        # CouncilChairmanError sites, all of which raise only our own
        # short, structured, already-redaction-safe messages -- never
        # raw prompts, Chain-of-Thought, or credentials).
        chairman_info = {
            "summary": (
                f"Selected {selected_name or council_result.recommendation}"
                if council_result.recommendation
                else (
                    f"Chairman failed: {council_result.chairman_error[:500]}"
                    if council_result.chairman_error
                    else "No final recommendation produced."
                )
            ),
            "recommendation": council_result.recommendation,
            "selected_approach": selected_name,
            "status": council_status,
            "council_complete": council_result.council_complete,
            "council_degraded": council_result.council_degraded,
            "chairman_error": (
                council_result.chairman_error[:1000] if council_result.chairman_error else None
            ),
            "chairman_failure_category": (
                _failure_category_from_text(council_result.chairman_error)
                if council_result.chairman_error else None
            ),
            "chairman_failure_subsystem": (
                _failure_subsystem(_failure_category_from_text(council_result.chairman_error))
                if council_result.chairman_error else None
            ),
            "chairman_attempts": self._chairman_attempts or None,
        }
        chairman_verbose = {**chairman_info,
            "preferred_variants": [variant.name for variant in council_result.variants],
            "rejected_variants": [variant.name for variant in council_result.rejected_variants],
            "merge_decisions": [{
                "merged_variant_ids": list(item.merged_variant_ids),
                "resulting_variant_id": item.resulting_variant_id,
                "reason": item.reason,
            } for item in council_result.merge_decisions],
        }
        chairman_very_verbose = {**chairman_verbose,
            "result_id": council_result.id,
            "council_complete": council_result.council_complete,
            "council_degraded": council_result.council_degraded,
            "error_count": len(council_result.agent_errors) + bool(council_result.chairman_error),
            "total_llm_calls": council_result.total_llm_calls,
            "variant_ids": [variant.id for variant in council_result.variants],
        }
        if "C:phase3" in self._effective_prompts:
            chairman_very_verbose["effective_prompt"] = self._effective_prompts["C:phase3"]
        self._result(
            actor="Chairman", actor_role="chairman", council_phase="phase3",
            result_kind="chairman_decision", provider=self._config.chairman.provider,
            model=self._config.chairman.model,
            duration_ms=duration_for("C", "phase3"),
            summary=chairman_info["summary"],
            council_output={"info": chairman_info, "verbose": chairman_verbose,
                            "very_verbose": chairman_very_verbose},
            interface_data={
                "normal": {"summary": "Council proposals and reviews produced a Chairman decision."},
                "info": {
                    "x": typed({"proposal_count": len(proposal_set.proposals),
                                "review_count": len(vote_sets)}, "council_review_set",
                               "engineering_council", "chairman"),
                    "f": execution_identity("chairman", provider=self._config.chairman.provider, model=self._config.chairman.model, actor="C", phase="phase3"),
                    "y": typed({"recommendation": council_result.recommendation,
                                "council_complete": council_result.council_complete,
                                "council_degraded": council_result.council_degraded},
                               "chairman_decision", "chairman", "engineering_council"),
                },
                "verbose": {
                    "x": typed({"proposals": proposals_for_review,
                          "reviews": [{"agent_id": item.agent_id,
                                       "review_count": len(item.votes)}
                                      for item in vote_sets]}, "council_review_set",
                               "engineering_council", "chairman"),
                    "f": execution_identity("chairman", provider=self._config.chairman.provider, model=self._config.chairman.model, actor="C", phase="phase3"),
                    "y": typed(chairman_verbose, "chairman_decision",
                               "chairman", "engineering_council"),
                },
                "very_verbose": {
                    "x": typed({"proposals": proposals_for_review,
                          "reviews": [{"agent_id": item.agent_id,
                                       "reviews": [{"variant_id": vote.variant_id,
                                                    "would_recommend": vote.would_recommend,
                                                    "concerns": list(vote.concerns),
                                                    "scores": vote.scores}
                                                   for vote in item.votes]}
                                      for item in vote_sets]}, "council_review_set",
                               "engineering_council", "chairman"),
                    "f": execution_identity("chairman", provider=self._config.chairman.provider, model=self._config.chairman.model, actor="C", phase="phase3"),
                    "y": typed(chairman_very_verbose, "chairman_decision",
                               "chairman", "engineering_council"),
                },
            },
        )

    # ------------------------------------------------------------------
    # Phase 1 — Independent Proposals
    # ------------------------------------------------------------------

    def _phase1_independent_proposals(self, council_input: CouncilInput) -> ProposalSet:
        # CLAUDE-ADC-COUNCIL-DIAGNOSTIC-TRACE-INTEGRATION-FIX-001: reset
        # for THIS evaluate() run only -- read back by
        # _emit_structured_results() (same lifecycle as
        # self._chairman_attempts/_chairman_repair_used above).
        self._zero_proposal_diagnostics = {}
        tasks = [
            _AgentTask(
                agent_id=aid,
                role=AGENT_ROLES[aid],
                config=_get_agent_config(self._config, aid),
                prompt=build_phase1_prompt(
                    council_input,
                    PHASE1_ROLE_PROMPTS[AGENT_ROLES[aid]],
                    self._config.max_variants_per_agent,
                ),
                phase="phase1",
                started_at=datetime.now(),
            )
            for aid in ("A1", "A2", "A3")
        ]

        results = self._execute_parallel(tasks, "phase1")

        all_proposals: list[AgentProposal] = []
        agent_errors: list[str] = []

        for res in results:
            if res.success and res.parsed:
                # CLAUDE-ADC-COUNCIL-DIAGNOSTIC-CAPTURE-001: `variants_field`
                # is read via the SAME, unchanged `res.parsed.get("variants",
                # [])` call the loop below already used -- diagnostics only
                # ever observe data this method already computed, never a
                # second parse/lookup, and the loop's own control flow
                # (what gets appended to all_proposals/agent_errors) is
                # byte-for-byte unchanged.
                variants_field = res.parsed.get("variants", [])
                retained_before = len(all_proposals)
                rejected_candidates: list[dict] = []
                for variant_data in variants_field:
                    try:
                        proposal = self._build_proposal_from_dict(
                            res.agent_id,
                            AGENT_ROLES.get(res.agent_id, ""),
                            variant_data,
                            res.raw_response,
                            council_input,
                        )
                        all_proposals.append(proposal)
                    except Exception as exc:
                        agent_errors.append(f"{res.agent_id}: build proposal failed — {exc}")
                        rejected_candidates.append(
                            _candidate_rejection_diagnostic(variant_data, exc)
                        )
                if len(all_proposals) == retained_before:
                    self._zero_proposal_diagnostics[res.agent_id] = (
                        self._build_zero_proposal_diagnostic(
                            council_input, res, variants_field, rejected_candidates,
                        )
                    )
            else:
                agent_errors.append(f"{res.agent_id}: {res.error or 'unknown error'}")
                if res.success:
                    # CLAUDE-ADC-COUNCIL-DIAGNOSTIC-CAPTURE-001: reached
                    # only when `res.success` is True but `res.parsed`
                    # is itself falsy (e.g. the LLM's entire response
                    # decoded to `{}` or `null`) -- decoded successfully,
                    # zero usable proposals, exactly the same diagnostic
                    # class as the branches above, just never reaching
                    # the `.get("variants", ...)` lookup at all. The
                    # `agent_errors` line above is completely unchanged
                    # by this -- this only ADDS the bounded diagnostic
                    # record alongside it.
                    self._zero_proposal_diagnostics[res.agent_id] = (
                        self._build_zero_proposal_diagnostic(
                            council_input, res, None, [],
                        )
                    )

        return ProposalSet(
            proposals=tuple(all_proposals),
            agent_errors=tuple(agent_errors),
        )

    def _phase1_attempt_count(self, agent_id: str) -> int:
        """How many Phase-1 LLM call attempts self._call_records already
        recorded for this agent -- read from the existing per-attempt
        AgentCallRecord bookkeeping _run_single_agent() already appends
        to; never a new capture surface. actor/phase/provider/model are
        NOT re-derived here: _emit_structured_results()'s existing
        self._result(actor=..., provider=..., model=..., council_phase=
        "phase1", ...) call already carries them for this same event."""
        return sum(
            1 for record in self._call_records
            if record.agent_id == agent_id and record.phase == "phase1"
        )

    def _build_zero_proposal_diagnostic(
        self, council_input: CouncilInput, res: "_AgentResult",
        variants_field: Any, rejected_candidates: list[dict],
    ) -> dict:
        """CLAUDE-ADC-COUNCIL-DIAGNOSTIC-TRACE-INTEGRATION-FIX-001: bounded,
        allowlisted-fields-only branch-classification evidence for a
        Phase-1 agent result that decoded successfully but retained zero
        proposals -- never raw prompts/responses/reasoning, never
        unbounded text. Pure data only: this method never persists
        anything itself. The caller stores the result in
        self._zero_proposal_diagnostics; _emit_structured_results() folds
        it into the SAME central DiagnosticTrace event this agent's
        "no usable structured proposal" outcome already produces via the
        existing set_result_callback()/self._result() composition path
        -- never a second, parallel diagnostic sink."""
        parsed = res.parsed
        return {
            "reason": _classify_zero_proposal_reason(
                parsed, variants_field, rejected_candidates,
            ),
            "root_parsed_type": type(parsed).__name__,
            "variants_field_present": (
                isinstance(parsed, dict) and "variants" in parsed
            ),
            "variants_field_type": (
                type(variants_field).__name__ if variants_field is not None else None
            ),
            "variants_field_count": _safe_len(variants_field),
            "requirement_ids": sorted(
                requirement.id for requirement in council_input.requirements
            ),
            "rejected_candidates": rejected_candidates,
            "attempt": self._phase1_attempt_count(res.agent_id),
        }

    def _build_proposal_from_dict(
        self,
        agent_id: str,
        agent_role: str,
        data: dict,
        raw_response: str,
        council_input: CouncilInput,
    ) -> AgentProposal:
        self._validate_toolchain_requirement_refs(
            data.get("toolchain", []), council_input
        )
        toolchain = tuple(
            ToolchainItem(
                requirement_ref=t.get("requirement_ref", ""),
                name=t.get("name", ""),
                technical_identity=t.get("technical_identity"),
                type=t.get("type", ""),
                install_method=t.get("install_method"),
                version=t.get("version"),
                purpose=t.get("purpose", ""),
                depends_on=tuple(t.get("depends_on", []) or []),
                state=t.get("state", "needs_install"),
                environment_constraint=t.get("environment_constraint"),
                provided_by=t.get("provided_by"),
                provides_verification=tuple(t.get("provides_verification", []) or []),
            )
            for t in data.get("toolchain", [])
        )

        return AgentProposal(
            variant_id=data.get("variant_id", f"{agent_id}-var-{uuid.uuid4().hex[:6]}"),
            agent_id=agent_id,
            agent_role=agent_role,
            name=data.get("name", f"{agent_id} Vorschlag"),
            description=data.get("description", ""),
            environment=data.get("environment", "host"),
            hardware_target=data.get("hardware_target"),
            connection=data.get("connection"),
            capabilities=tuple(data.get("capabilities", []) or []),
            toolchain=toolchain,
            advantages=tuple(data.get("advantages", []) or []),
            disadvantages=tuple(data.get("disadvantages", []) or []),
            risks=tuple(data.get("risks", []) or []),
            confidence=float(data.get("confidence", 0.5)),
            feasibility=data.get("feasibility", "medium"),
            verification=data.get("verification", ""),
            verification_coverage=_parse_verification_coverage(data.get("verification_coverage", [])),
            test_strategy=data.get("test_strategy"),
            agent_reasoning=data.get("agent_reasoning", ""),
            raw_llm_response=raw_response,
        )

    @staticmethod
    def _validate_toolchain_requirement_refs(
        toolchain: list[dict[str, Any]], council_input: CouncilInput
    ) -> None:
        """Require every toolchain item to reference this Council input."""
        requirement_ids = {requirement.id for requirement in council_input.requirements}
        for item in toolchain:
            requirement_ref = item.get("requirement_ref")
            if (
                not isinstance(requirement_ref, str)
                or not requirement_ref.strip()
                or requirement_ref not in requirement_ids
            ):
                raise ValueError(
                    "toolchain requirement_ref must exactly reference a current "
                    "CouncilInput requirement [category=invalid_requirement_ref]"
                )
            provided_by = item.get("provided_by")
            if provided_by is not None and (
                not isinstance(provided_by, str)
                or not provided_by.strip()
                or provided_by not in requirement_ids
            ):
                raise ValueError(
                    "toolchain provided_by must reference a current CouncilInput requirement"
                )

    # ------------------------------------------------------------------
    # Phase 2 — Cross-Review
    # ------------------------------------------------------------------

    def _phase2_cross_review(self, proposal_set: ProposalSet) -> tuple[tuple[AgentVoteSet, ...], tuple[str, ...]]:
        variants_json = json.dumps(
            [
                {
                    "variant_id": p.variant_id,
                    "agent_id": p.agent_id,
                    "agent_role": p.agent_role,
                    "name": p.name,
                    "description": p.description,
                    "environment": p.environment,
                    "hardware_target": p.hardware_target,
                    "connection": p.connection,
                    "capabilities": list(p.capabilities),
                    "toolchain": [
                        {
                            "requirement_ref": t.requirement_ref,
                            "name": t.name,
                            "technical_identity": t.technical_identity,
                            "type": t.type,
                            "install_method": t.install_method,
                            "version": t.version,
                            "purpose": t.purpose,
                            "depends_on": list(t.depends_on),
                            "state": t.state,
                            "environment_constraint": t.environment_constraint,
                            "provided_by": t.provided_by,
                            "provides_verification": list(t.provides_verification),
                        }
                        for t in p.toolchain
                    ],
                    "advantages": list(p.advantages),
                    "disadvantages": list(p.disadvantages),
                    "risks": list(p.risks),
                    "confidence": p.confidence,
                    "feasibility": p.feasibility,
                    "verification": p.verification,
                    "agent_reasoning": p.agent_reasoning,
                }
                for p in proposal_set.proposals
            ],
            indent=2,
            ensure_ascii=False,
        )

        tasks = [
            _AgentTask(
                agent_id=aid,
                role=AGENT_ROLES[aid],
                config=_get_agent_config(self._config, aid),
                prompt=build_phase2_review_prompt(
                    variants_json, PHASE2_ROLE_PROMPTS[AGENT_ROLES[aid]]
                ),
                phase="phase2",
                started_at=datetime.now(),
            )
            for aid in ("A1", "A2", "A3")
        ]

        results = self._execute_parallel(tasks, "phase2")

        vote_sets: list[AgentVoteSet] = []
        vote_errors: list[str] = []
        for res in results:
            if res.success and res.parsed:
                votes = tuple(
                    AgentVote(
                        agent_id=res.agent_id,
                        variant_id=v.get("variant_id", ""),
                        scores=v.get("scores", {}),
                        would_recommend=bool(v.get("would_recommend", False)),
                        reasoning=v.get("reasoning", ""),
                        concerns=tuple(v.get("concerns", []) or []),
                    )
                    for v in res.parsed.get("votes", [])
                )
                vote_sets.append(AgentVoteSet(
                    agent_id=res.agent_id,
                    agent_role=res.parsed.get("agent_role", ""),
                    votes=votes,
                ))
            else:
                vote_errors.append(f"{res.agent_id}: {res.error or 'unknown error'}")

        return tuple(vote_sets), tuple(vote_errors)

    # ------------------------------------------------------------------
    # Phase 3 — Chairman Synthesis
    # ------------------------------------------------------------------

    def _phase3_chairman_synthesis(
        self,
        proposal_set: ProposalSet,
        vote_sets: tuple[AgentVoteSet, ...],
        council_input: CouncilInput,
    ) -> CouncilResult:
        proposals_json = json.dumps(
            [
                {
                    "variant_id": p.variant_id,
                    "agent_id": p.agent_id,
                    "name": p.name,
                    "description": p.description,
                    "environment": p.environment,
                    "hardware_target": p.hardware_target,
                    "connection": p.connection,
                    "capabilities": list(p.capabilities),
                    "toolchain": [
                        {
                            "requirement_ref": t.requirement_ref,
                            "name": t.name,
                            "technical_identity": t.technical_identity,
                            "type": t.type,
                            "install_method": t.install_method,
                            "version": t.version,
                            "state": t.state,
                            "environment_constraint": t.environment_constraint,
                            "provided_by": t.provided_by,
                            "provides_verification": list(t.provides_verification),
                        }
                        for t in p.toolchain
                    ],
                    "controlled_setup": {
                        **ToolchainMaterializer().assess_variant(
                            CouncilVariant(
                                id=p.variant_id,
                                name=p.name,
                                toolchain=p.toolchain,
                            ),
                            council_input.preflight,
                        ),
                        "selection_guidance": (
                            "required_when_available"
                        ),
                    },
                    "advantages": list(p.advantages),
                    "disadvantages": list(p.disadvantages),
                    "risks": list(p.risks),
                }
                for p in proposal_set.proposals
            ],
            indent=2,
            ensure_ascii=False,
        )

        votes_json = json.dumps(
            [
                {
                    "agent_id": vs.agent_id,
                    "agent_role": vs.agent_role,
                    "votes": [
                        {
                            "variant_id": v.variant_id,
                            "scores": v.scores,
                            "would_recommend": v.would_recommend,
                            "reasoning": v.reasoning,
                            "concerns": list(v.concerns),
                        }
                        for v in vs.votes
                    ],
                }
                for vs in vote_sets
            ],
            indent=2,
            ensure_ascii=False,
        )

        prompt = build_chairman_prompt(proposals_json, votes_json, council_input)
        chairman_config = self._config.chairman

        task = _AgentTask(
            agent_id="C", role="chairman",
            config=chairman_config, prompt=prompt,
            phase="phase3", started_at=datetime.now(),
        )

        result = self._execute_parallel([task], "phase3")[0]

        if not result.success or not result.parsed:
            # CLAUDE-E2E-NIO-011A, Part 9.G: the Chairman provider call
            # already went through its OWN existing, separately-bounded
            # transport-level retry (_run_single_agent: 1 initial + 1
            # retry for both timeouts and malformed JSON, unchanged).
            # Reaching here means THAT policy is exhausted -- this is a
            # transport failure, never Engineering-synthesis-repairable,
            # and must never be confused with the bounded repair below
            # (which only ever runs once _parse_chairman_result() has
            # received a genuinely parsed response and rejected its
            # CONTENT, not its transport).
            self._chairman_attempts = 1
            raise CouncilChairmanError(
                f"Chairman failed: {result.error or 'no parsed output'}",
                category="provider_transport",
            )

        self._chairman_attempts = 1
        try:
            council_result = self._parse_chairman_result(result.parsed, council_input)
        except (CouncilChairmanError, ValueError) as first_error:
            # CLAUDE-E2E-NIO-011A, Part 5/6: the Chairman's own synthesis
            # PROTOCOL output was structurally rejected (transport
            # already succeeded -- this is categorically NOT a provider
            # failure). Rather than terminating planning immediately
            # (010A's own prior behaviour) or re-running the entire
            # Council, give the Chairman exactly ONE targeted repair
            # attempt armed with the exact deterministic rejection
            # reason, reusing the SAME proposals/votes/binding-
            # Requirement context already in `prompt` -- never a second,
            # independent Engineering Council run, and never a Python-
            # side merge of two Engineering solutions (Part 7/8: only
            # the Chairman synthesizes; deterministic code only
            # validates). This repair budget is shared with the
            # admissibility-triggered repair below -- at most ONE repair
            # attempt total, whichever fires first.
            self._chairman_repair_used = True
            repair_prompt = _build_chairman_repair_prompt(prompt, first_error)
            repair_task = _AgentTask(
                agent_id="C", role="chairman",
                config=chairman_config, prompt=repair_prompt,
                phase="phase3", started_at=datetime.now(),
            )
            repair_result = self._execute_parallel([repair_task], "phase3")[0]
            self._chairman_attempts = 2

            if not repair_result.success or not repair_result.parsed:
                raise CouncilChairmanError(
                    "Chairman synthesis failed after 2 attempt(s) (bounded "
                    f"repair exhausted); attempt 1: {first_error}; "
                    "attempt 2: Chairman failed: "
                    f"{repair_result.error or 'no parsed output'}",
                    category="provider_transport",
                ) from first_error

            try:
                council_result = self._parse_chairman_result(repair_result.parsed, council_input)
            except (CouncilChairmanError, ValueError) as second_error:
                raise CouncilChairmanError(
                    "Chairman synthesis failed after 2 attempt(s) (bounded "
                    f"repair exhausted); attempt 1: {first_error}; "
                    f"attempt 2: {second_error}",
                    category=_failure_category(second_error),
                ) from second_error
            # CLAUDE-ADC-RSE033-CHAIRMAN-REWORK-FIX-001: a structural/
            # protocol repair uses its OWN, independent repair budget
            # (MAX_STRUCTURAL_REPAIR_ATTEMPTS=1) -- it must never
            # silently bypass the SEPARATE, independent admissibility/
            # content rework opportunity (MAX_ADMISSIBILITY_REWORK_
            # ATTEMPTS=1) every structurally-valid result is entitled
            # to, merely because a structural repair happened to fire
            # first and already consumed its own budget. Root cause of
            # a Real-System-E2E failure: a first Chairman attempt whose
            # PROTOCOL output was rejected and then successfully
            # repaired went straight to `return council_result` here,
            # so a repaired-but-still-inadmissible result (missing
            # binding-requirement coverage) never got its one bounded
            # admissibility rework chance before S2.3 correctly, but
            # too late, rejected it. Both convergence points now share
            # ONE common post-parse decision path via
            # _consult_admissibility_and_rework() -- see that method
            # and CLAUDE-ARCH-S2-012B below for why this consultation
            # never changes whether this function returns normally.
            return self._consult_admissibility_and_rework(
                council_result, council_input, prompt, chairman_config,
                attempts_so_far=self._chairman_attempts,
            )

        # CLAUDE-ARCH-S2-012B: the synthesis protocol succeeded on the
        # FIRST attempt -- reaches the SAME shared post-parse
        # admissibility consultation as the structural-repair-success
        # path above (CLAUDE-ADC-RSE033-CHAIRMAN-REWORK-FIX-001).
        return self._consult_admissibility_and_rework(
            council_result, council_input, prompt, chairman_config,
            attempts_so_far=self._chairman_attempts,
        )

    def _consult_admissibility_and_rework(
        self,
        council_result: CouncilResult,
        council_input: CouncilInput,
        prompt: str,
        chairman_config: CouncilAgentConfig,
        attempts_so_far: int,
    ) -> CouncilResult:
        """CLAUDE-ADC-RSE033-CHAIRMAN-REWORK-FIX-001: the single, shared
        post-parse admissibility decision point every structurally
        valid Chairman result reaches exactly once per evaluate() run --
        whether that structurally valid result came from the first
        attempt or from the one bounded structural/protocol repair.
        Consults S2.3's own validate_variants() (via
        _admissibility_rework_evidence(); never a duplicated/weaker
        admissibility algorithm) ONLY to decide whether a bonus, still-
        independently-bounded (MAX_ADMISSIBILITY_REWORK_ATTEMPTS=1)
        repair attempt is worth trying -- this consultation NEVER
        changes whether the caller returns normally, and
        council_result.council_complete is ALREADY True at this point
        regardless of the outcome here (CLAUDE-ARCH-S2-012B). If a
        repair is attempted and STILL does not satisfy S2.3, or the
        repair call itself fails at the transport level or breaks the
        synthesis protocol, the ORIGINAL structurally-valid
        council_result is kept and returned -- council_complete=True
        can therefore coexist with an S2.3 rejection (including zero
        admissible candidates), exactly as the documented governance
        requires. Never raises; never loops beyond this one bounded
        call regardless of the outcome."""
        rework = self._admissibility_rework_evidence(council_result, council_input)
        if rework is None:
            return council_result
        self._chairman_repair_used = True
        repair_prompt = _build_chairman_repair_prompt(prompt, rework)
        repair_task = _AgentTask(
            agent_id="C", role="chairman",
            config=chairman_config, prompt=repair_prompt,
            phase="phase3", started_at=datetime.now(),
        )
        repair_result = self._execute_parallel([repair_task], "phase3")[0]
        self._chairman_attempts = attempts_so_far + 1
        if repair_result.success and repair_result.parsed:
            try:
                return self._parse_chairman_result(repair_result.parsed, council_input)
            except (CouncilChairmanError, ValueError):
                # The repair attempt itself broke the protocol -- keep
                # the ORIGINAL, structurally-valid result rather than
                # failing a synthesis that already succeeded.
                pass
        # A repair_result transport failure is likewise not a reason to
        # fail an already-structurally-complete synthesis -- keep the
        # original council_result.
        return council_result

    def _admissibility_rework_evidence(
        self, council_result: CouncilResult, council_input: CouncilInput,
    ) -> "EngineeringReworkRequest | None":
        """CLAUDE-ARCH-S2-012B: consults S2.3's own validate_variants()
        (never a duplicated rule) to decide whether the Chairman's
        recommendation is worth a bonus repair attempt. Returns None
        when admissible (or when the recommendation cannot be resolved
        to a real variant, which _parse_chairman_result() already
        guarantees cannot happen for a structurally valid result) --
        never raises, never affects council_complete."""
        recommended_variant = next(
            (v for v in council_result.variants if v.id == council_result.recommendation), None,
        )
        if recommended_variant is None:
            return None
        admissibility = validate_variants(
            (recommended_variant,), council_input.preflight, council_input.platform,
            all_trusted_verification_groups(council_input.project_intelligence),
        )[0]
        if admissibility.admissible:
            return None
        return EngineeringReworkRequest.from_validation(
            admissibility, platform=council_input.platform,
        )

    def _parse_chairman_result(self, parsed: dict, council_input: CouncilInput) -> CouncilResult:
        variants: list[CouncilVariant] = []
        for v in parsed.get("variants", []):
            self._validate_toolchain_requirement_refs(
                v.get("toolchain", []), council_input
            )
            variants.append(CouncilVariant(
                id=v.get("id", ""),
                name=v.get("name", ""),
                description=v.get("description", ""),
                origin_agents=tuple(v.get("origin_agents", []) or []),
                merged_from=tuple(v.get("merged_from", []) or []),
                rank=v.get("rank", 0),
                total_score=float(v.get("total_score", 0.0)),
                consensus_level=v.get("consensus_level", "unknown"),
                minority_opinions=tuple(v.get("minority_opinions", []) or []),
                environment=v.get("environment", "host"),
                hardware_target=v.get("hardware_target"),
                connection=v.get("connection"),
                capabilities=tuple(v.get("capabilities", []) or []),
                toolchain=tuple(
                    ToolchainItem(
                        requirement_ref=t.get("requirement_ref", ""),
                        name=t.get("name", ""),
                        technical_identity=t.get("technical_identity"),
                        type=t.get("type", ""),
                        install_method=t.get("install_method"),
                        version=t.get("version"),
                        purpose=t.get("purpose", ""),
                        depends_on=tuple(t.get("depends_on", []) or []),
                        state=t.get("state", "needs_install"),
                        environment_constraint=t.get("environment_constraint"),
                        provided_by=t.get("provided_by"),
                        provides_verification=tuple(t.get("provides_verification", []) or []),
                    )
                    for t in v.get("toolchain", [])
                ),
                advantages=tuple(v.get("advantages", []) or []),
                disadvantages=tuple(v.get("disadvantages", []) or []),
                risks=tuple(v.get("risks", []) or []),
                confidence=float(v.get("confidence", 0.5)),
                feasibility=v.get("feasibility", "medium"),
                verification=v.get("verification", ""),
                verification_coverage=_parse_verification_coverage(v.get("verification_coverage", [])),
                test_strategy=v.get("test_strategy"),
            ))

        rejected = tuple(
            CouncilVariant(
                id=rv.get("id", ""),
                name=rv.get("name", ""),
                description=rv.get("description", ""),
                origin_agents=tuple(rv.get("origin_agents", []) or []),
                merged_from=tuple(rv.get("merged_from", []) or []),
                rank=rv.get("rank", 99),
                total_score=float(rv.get("total_score", 0.0)),
                consensus_level=rv.get("consensus_level", "unknown"),
            )
            for rv in parsed.get("rejected_variants", [])
        )

        merges = tuple(
            MergeDecision(
                merged_variant_ids=tuple(md.get("merged_variant_ids", []) or []),
                resulting_variant_id=md.get("resulting_variant_id", ""),
                reason=md.get("reason", ""),
            )
            for md in parsed.get("merge_decisions", [])
        )

        recommendation = parsed.get("recommendation")
        variant_ids = {variant.id for variant in variants}
        if not variants:
            raise CouncilChairmanError(
                "Chairman produced no valid final variant",
                category="no_valid_variant",
            )
        # CLAUDE-ARCH-S2-014C (F3): a variant id must be unique and stable
        # across Council output -> S2.3 -> displayed engineering selection
        # -> human POST accept/select -> S2.5 EngineeringDecision -> S3
        # handoff. `variant_ids` above is a SET -- it silently collapses
        # duplicate ids, which let two DIFFERENT CouncilVariant objects
        # (different toolchain/verification_coverage/name) share one id.
        # Downstream code that resolves "the variant with id X" by
        # `next(v for v in variants if v.id == X)` (first match) and code
        # that instead builds a `{v.id: v for v in variants}` dict (last
        # match wins) would then silently resolve to TWO DIFFERENT
        # objects for the SAME id -- exactly the "human sees variant A,
        # submits its id, selector resolves variant B" defect
        # CDX-REVIEW-S2-014A reproduced. Structural protocol integrity
        # (this function's own, unchanged scope) is exactly where this
        # ambiguity must be rejected -- before S2.3, S2.4 or a human ever
        # sees it. Never silently renamed, never resolved by picking
        # first/last -- an ambiguous identity is a synthesis-protocol
        # defect, reported the same way every other structural violation
        # here is.
        if len(variants) != len(variant_ids):
            seen: set[str] = set()
            duplicate_ids = sorted({
                variant.id for variant in variants
                if variant.id in seen or seen.add(variant.id)
            })
            raise CouncilChairmanError(
                "Chairman produced two or more final variants sharing the "
                f"same id -- variant identity must be unique: {duplicate_ids!r}",
                category="duplicate_variant_id",
            )
        if not recommendation or recommendation not in variant_ids:
            raise CouncilChairmanError(
                "Chairman recommendation must identify a final Council "
                f"variant; got {recommendation!r}, known final variant ids: "
                f"{sorted(variant_ids)}",
                category="invalid_recommendation",
            )

        # CLAUDE-ARCH-S2-012B: _parse_chairman_result() is S2.2's own
        # SYNTHESIS PROTOCOL parser -- it validates only structural/
        # protocol integrity (valid requirement_ref references, at least
        # one final variant, a recommendation that identifies one of
        # them) and NEVER calls into S2.3's admissibility authority.
        # CLAUDE-ARCH-S2-012A previously added an S2.3 admissibility
        # check right here, which made `council_complete` conflate
        # "synthesis protocol succeeded" with "S2.3 considers the
        # recommendation admissible" -- an independent review correctly
        # rejected that: council_complete=True must be able to coexist
        # with an S2.3 rejection of the very same recommendation (see
        # _phase3_chairman_synthesis()'s _admissibility_rework_evidence()
        # for where that consultation now happens instead, WITHOUT
        # gating this function's return value). See the module/class
        # docstring update and the completion report for the full
        # RED-before-fix evidence.
        return CouncilResult(
            id=self._run_id,
            project_id=council_input.project_id,
            stack=council_input.detected_stack or "",
            variants=tuple(sorted(variants, key=lambda v: v.rank)),
            rejected_variants=rejected,
            recommendation=recommendation,
            reasoning=parsed.get("reasoning", ""),
            merge_decisions=merges,
            council_complete=True,
        )

    # ------------------------------------------------------------------
    # Parallel execution
    # ------------------------------------------------------------------

    def _start_agent_call(self, task: _AgentTask) -> str | None:
        """Run one agent call on its own DAEMON thread, or refuse admission.

        A provider call that outlives its deadline cannot be interrupted; a
        daemon thread never blocks process exit (SUB_REQ_040), and the
        process-wide _WORKER_POOL bounds how many such threads exist. The
        worker is registered BEFORE its thread starts and released only by
        its own final step, so accounting never depends on thread liveness.
        Returns the refusal reason when the pool refuses admission (no
        thread, no provider work)."""
        def run():
            outcome: Any = None
            try:
                outcome = self._run_admitted_agent(task)
            except BaseException as exc:
                outcome = exc
            finally:
                try:
                    with task.lock:
                        reported = task.worker_reported
                    if not reported:
                        success = isinstance(outcome, _AgentResult) and outcome.success
                        self._worker_terminal(
                            task, "completed" if success else "failed", outcome,
                            failure_category=None if success else "provider_failure",
                        )
                finally:
                    _WORKER_POOL.release(threading.current_thread())

        thread = threading.Thread(
            target=run, name=f"council-{task.agent_id}-{task.phase}", daemon=True,
        )
        refusal = _WORKER_POOL.admit(
            (task.agent_id, task.config.provider, task.config.model), thread,
        )
        if refusal is not None:
            return refusal
        task.worker = thread
        try:
            thread.start()
        except BaseException:
            _WORKER_POOL.release(thread)
            raise
        return None

    def _run_admitted_agent(self, task: _AgentTask) -> _AgentResult:
        """Worker: own the agent slot (bounded wait, see _CouncilWorkerPool),
        then run the call."""
        task.slot_state = "waiting"
        refusal = _WORKER_POOL.acquire_slot(
            threading.current_thread(), task.activity_closed.is_set,
        )
        task.slot_state = "owned" if refusal is None else "refused"
        if refusal is None:
            return self._run_single_agent(task)
        result = _AgentResult(
            agent_id=task.agent_id, success=False,
            error=f"provider call refused: {refusal}",
        )
        if not task.activity_closed.is_set():
            task.call_records.append(self._failure_record(task, task.phase, result.error, 0))
            self._worker_terminal(task, "failed", result, failure_category="provider_quarantined")
        return result

    def _commit_task_state(self, task: _AgentTask) -> None:
        """Coordinator only: publish a completed invocation's buffered state."""
        with task.lock:
            if task.activity_closed.is_set():
                return
            self._call_records.extend(task.call_records)
            if task.effective_prompt is not None:
                self._retain_prompt(f"{task.agent_id}:{task.phase}", task.effective_prompt)

    @staticmethod
    def _failure_record(
        task: _AgentTask, phase: str, error: str, duration_ms: float,
    ) -> AgentCallRecord:
        return AgentCallRecord(
            agent_id=task.agent_id,
            role=task.role,
            provider=task.config.provider,
            model=task.config.model,
            temperature=task.config.temperature,
            phase=phase,
            started_at=task.started_at,
            duration_ms=duration_ms,
            success=False,
            error=_redact_bounded(error, _CALL_RECORD_ERROR_CHARS),
        )

    def _phase_limit(self, phase: str) -> tuple[float, str]:
        """The absolute limit a phase imposes on its calls, and its scope
        label (SUB_REQ_033/039). A phase deadline is fixed when the phase
        first starts -- repair and rework calls of phase 3 share it, so a
        retry or repair never resets it -- and never passes the public
        deadline minus the finalization budget."""
        run = self._run
        if run is None:
            return float("inf"), "contributor_call"
        if run.closed:
            return time.monotonic(), "council"
        if phase not in run.phase_limits:
            budget = run.profile["phase_seconds"].get(phase, 0.0)
            run.phase_limits[phase] = time.monotonic() + budget
        council_limit = run.public_deadline - run.profile["finalization_seconds"]
        phase_limit = run.phase_limits[phase]
        if council_limit <= phase_limit:
            return council_limit, "council"
        return phase_limit, "phase"

    def _execute_parallel(self, tasks: list[_AgentTask], phase: str) -> list[_AgentResult]:
        """Coordinator of one phase step (SUB_REQ_033-035, 037-040).

        Every task gets one absolute deadline: its contributor-call budget,
        capped by the phase and public deadlines. A task ends exactly once:
        its worker claims a terminal state before that deadline, or the
        coordinator finalizes it -- which closes the invocation so that no
        further actual request handover can begin. The coordinator waits on
        terminal decisions, never on a worker thread or a receiver."""
        results_by_agent: dict[str, _AgentResult] = {}
        changed = threading.Event()
        limit, limit_scope = self._phase_limit(phase)
        scopes: dict[str, str] = {}
        for task in tasks:
            task.changed = changed
            task.run_id = self._run_id
            task.progress_lane = task.terminal_lane = self._activity_lane or _NO_SUBSCRIPTION
            call_deadline = _outer_deadline(task.config)
            task.deadline = min(call_deadline, limit)
            scopes[task.invocation_id] = (
                "contributor_call" if call_deadline <= limit else limit_scope
            )
            self._activity(task, "waiting")
        pending: list[_AgentTask] = []
        ledger = self._run.ledger if self._run is not None else None
        for task in tasks:
            if time.monotonic() >= task.deadline:
                # Its scope closed before the call could start: no provider work.
                self._finalize(task, "timeout")
                self._record_timeout(task, phase, results_by_agent)
                continue
            refusal = None
            if ledger is not None:
                # The task owns the run's ledger for its whole lifetime (a
                # quarantined worker included); its prompt is booked before
                # any worker exists. Without capacity it does not start.
                ledger.bind(task)
                task.ledger = ledger
                nbytes = _text_bytes(task.prompt)
                if not ledger.book(nbytes):
                    refusal = (f"prompt of {nbytes} bytes not chargeable: "
                               "storage capacity exhausted")
            if refusal is None:
                refusal = self._start_agent_call(task)
            if refusal is None:
                pending.append(task)
                continue
            # Fail closed, immediately and observably: no thread, no wait.
            category = (
                "provider_quarantined" if refusal == _SLOT_QUARANTINED else "resource_exhausted"
            )
            error = f"provider call refused: {refusal}"
            self._finalize(task, category)
            logger.warning(
                f"Council agent {task.agent_id}: {error} ({council_worker_stats()})"
            )
            results_by_agent[task.agent_id] = _AgentResult(
                agent_id=task.agent_id, success=False, error=error,
            )
            self._call_records.append(self._failure_record(task, phase, error, 0))

        while pending:
            changed.clear()
            now = time.monotonic()
            for task in list(pending):
                if task.terminal and not task.activity_closed.is_set():
                    # Claimed by its worker before the deadline: accepted.
                    pending.remove(task)
                    self._deliver_outcome(task, phase, task.outcome, results_by_agent)
                    task.activity_closed.set()  # closed: no further handover
                elif task.deadline <= now:
                    pending.remove(task)
                    if self._finalize(task, "timeout"):
                        if task.worker is not None:
                            _WORKER_POOL.abandon(task.worker)
                            if task.slot_state == "waiting":
                                # Never started provider work: it ends as soon
                                # as it sees the closure; await that briefly so
                                # the returned accounting is exact.
                                task.worker.join(_WAITER_EXIT_SECONDS)
                        self._record_timeout(task, phase, results_by_agent)
                    else:
                        # The worker's in-time claim won the race.
                        self._deliver_outcome(task, phase, task.outcome, results_by_agent)
                        task.activity_closed.set()
            if pending:
                changed.wait(max(0.0, min(t.deadline for t in pending) - time.monotonic()))

        self._record_invocations(tasks, phase, scopes)
        # Notifications are awaited only inside the phase's own budget and
        # only while the receiver makes progress (SUB_REQ_037, SUB_REQ_039).
        _settle_deliveries(
            [self._activity_lane],
            until=min(time.monotonic() + _DELIVERY_SETTLE_LIMIT_SECONDS, limit),
        )
        return [results_by_agent[task.agent_id] for task in tasks]

    def _record_timeout(
        self, task: _AgentTask, phase: str, results_by_agent: dict[str, _AgentResult],
    ) -> None:
        # Whether a handover had begun before closure (SUB_REQ_034): the
        # remote side may still process it; local closure does not end it.
        error = (
            "provider call exceeded its configured deadline"
            if task.finalized_after_start else
            "provider call exceeded its configured deadline before it started; it will not start"
        )
        results_by_agent[task.agent_id] = _AgentResult(
            agent_id=task.agent_id, success=False, error=error,
        )
        self._call_records.append(self._failure_record(
            task, phase, error,
            (task.config.timeout_seconds * _TOTAL_RETRY_MULTIPLIER + _TIMEOUT_GRACE_SECONDS) * 1000,
        ))

    def _record_invocations(
        self, tasks: list[_AgentTask], phase: str, scopes: dict[str, str],
    ) -> None:
        """Critical, callback-independent diagnosis of each invocation
        (SUB_REQ_035): contributor, cause, degradation, timeout scope and
        handover status. Written to the reserved registry record."""
        if not self._run_id:
            return
        entries = {}
        for task in tasks:
            with task.lock:
                state, category = task.terminal_state or ("failed", "unknown")
                if task.gate is not None:
                    handover = dict(task.gate.summary(), boundary=task.handover_boundary)
                else:
                    handover = {"boundary": task.handover_boundary,
                                "start_claimed": task.provider_started}
                entries[task.invocation_id] = {
                    "invocation_id": task.invocation_id,
                    "contributor": task.agent_id, "role": task.role, "phase": phase,
                    "provider": task.config.provider, "model": task.config.model,
                    "terminal_state": state, "failure_category": category,
                    "degraded": state != "completed",
                    "timeout_scope": scopes.get(task.invocation_id) if category == "timeout" else None,
                    "handover": handover,
                }
        _DIAGNOSIS.update(self._run_id, lambda record: record["invocations"].update(entries))

    def _deliver_outcome(
        self, task: _AgentTask, phase: str, outcome: Any,
        results_by_agent: dict[str, _AgentResult],
    ) -> None:
        """Coordinator: commit a worker-owned invocation and record its outcome."""
        self._commit_task_state(task)
        if isinstance(outcome, _AgentResult):
            results_by_agent[task.agent_id] = outcome
            return
        if outcome is None:
            # Terminal state claimed without a published outcome (only a
            # replaced/foreign worker body can do that): fail closed.
            outcome = RuntimeError("agent outcome was not delivered before its deadline")
        self._activity(task, "failed", failure_category="provider_failure")
        logger.warning(f"Council agent {task.agent_id} failed: {outcome}")
        results_by_agent[task.agent_id] = _AgentResult(
            agent_id=task.agent_id, success=False, error=str(outcome),
        )
        self._call_records.append(self._failure_record(task, phase, str(outcome), 0))

    # ------------------------------------------------------------------
    # Single agent call with retry
    # ------------------------------------------------------------------

    def _run_single_agent(self, task: _AgentTask) -> _AgentResult:
        self._activity(task, "preparing")
        try:
            provider = create_council_provider(
                task.config,
                self._secret_resolver,
                self._config.ollama_url,
            )
        except Exception as exc:
            self._worker_terminal(task, "failed", exc, failure_category="provider_configuration")
            raise
        # SUB_REQ_033: every actual request handover of a supported binding
        # passes the invocation's gate; other bindings get no guarantee.
        gate = HandoverGate(
            task.lock, task.activity_closed.is_set, DEFAULT_PROFILE.handovers_per_call,
            deadline=lambda: task.deadline,
        )
        if bind_handover_gate(provider, gate, DEFAULT_PROFILE.handover_send_timeout_seconds):
            task.gate, task.handover_boundary = gate, HANDOVER_BOUNDARY

        last_raw = ""
        for attempt in range(_MAX_RETRIES + 1):
            if task.activity_closed.is_set():
                # The outer deadline already expired and the Council moved
                # on without this agent: never start another provider call.
                return _AgentResult(
                    agent_id=task.agent_id, success=False,
                    error="provider call abandoned after its outer deadline",
                    raw_response=last_raw,
                )
            started = datetime.now()
            try:
                self._activity(task, "thinking")
                if not self._begin_provider_call(task):
                    return _AgentResult(
                        agent_id=task.agent_id, success=False,
                        error="provider call abandoned after its outer deadline",
                        raw_response=last_raw,
                    )
                task.effective_prompt = task.prompt
                raw = self._invoke_provider(task, provider)
                if raw is None:
                    return _AgentResult(
                        agent_id=task.agent_id, success=False,
                        error="provider call abandoned after its outer deadline",
                        raw_response=last_raw,
                    )
                if not self._book_working(task, raw):
                    # The response cannot be booked: it is dropped at once
                    # and the invocation fails visibly; nothing builds on it.
                    return self._unbookable(task, f"provider response of {_text_bytes(raw)} bytes")
                last_raw = raw
                self._activity(task, "reviewing")
                duration_ms = (datetime.now() - started).total_seconds() * 1000
                parsed = self._parse_json_response(raw, task.agent_id)

                task.call_records.append(AgentCallRecord(
                    agent_id=task.agent_id,
                    role=task.role,
                    provider=task.config.provider,
                    model=task.config.model,
                    temperature=task.config.temperature,
                    phase=task.phase,
                    started_at=task.started_at,
                    duration_ms=duration_ms,
                    success=True,
                    # Redact BEFORE bounding: the cut must never leave a
                    # secret fragment that redaction no longer recognizes.
                    raw_response_snippet=_redact_bounded(raw, 500),
                    structured_output_summary=str(list(parsed.keys()))[:500],
                ))

                result = _AgentResult(
                    agent_id=task.agent_id,
                    success=True,
                    parsed=parsed,
                    raw_response=raw,
                )
                self._worker_terminal(task, "completed", result)
                return result

            except Exception as exc:
                duration_ms = (datetime.now() - started).total_seconds() * 1000
                is_parse = isinstance(exc, AgentParseError)
                error_msg = (
                    f"JSON parse error (attempt {attempt + 1})"
                    if is_parse else f"{type(exc).__name__}: {exc}"
                )
                task.call_records.append(AgentCallRecord(
                    agent_id=task.agent_id,
                    role=task.role,
                    provider=task.config.provider,
                    model=task.config.model,
                    temperature=task.config.temperature,
                    phase=task.phase,
                    started_at=task.started_at,
                    duration_ms=duration_ms,
                    success=False,
                    error=_redact_bounded(error_msg, _CALL_RECORD_ERROR_CHARS),
                    raw_response_snippet=_redact_bounded(last_raw, 500) if last_raw else "",
                ))
                if attempt >= _MAX_RETRIES:
                    failure_cat = "invalid_json" if is_parse else "provider_failure"
                    logger.warning(f"Agent {task.agent_id}: failed after {attempt + 1} attempts — {exc}")
                    result = _AgentResult(
                        agent_id=task.agent_id,
                        success=False,
                        error=f"{'JSON parse' if is_parse else 'Provider'} error after {attempt + 1} attempts: {exc}",
                        raw_response=last_raw,
                    )
                    self._worker_terminal(task, "failed", result, failure_category=failure_cat)
                    return result
                if is_parse:
                    retry_prompt = (
                        f"{task.prompt}\n\n"
                        f"DEINE VORHERIGE ANTWORT WAR KEIN VALIDES JSON. "
                        f"BITTE NUR VALIDES JSON ZURÜCKGEBEN — KEIN BEGLEITTEXT."
                    )
                    if not self._book_working(task, retry_prompt):
                        return self._unbookable(
                            task, f"retry prompt of {_text_bytes(retry_prompt)} bytes")
                    task.prompt = retry_prompt
                    retry_prompt = None

        return _AgentResult(
            agent_id=task.agent_id,
            success=False,
            error="Max retries exceeded",
            raw_response=last_raw,
        )

    @staticmethod
    def _book_working(task: _AgentTask, text: str) -> bool:
        """Worker: book data the invocation keeps in the run's ledger."""
        return task.ledger is None or task.ledger.book(_text_bytes(text))

    def _unbookable(self, task: _AgentTask, what: str) -> _AgentResult:
        """Worker: fail the invocation visibly because `what` cannot be
        booked (SUB_REQ_036/038); the unbooked data is not kept."""
        error = f"{what} not chargeable: storage capacity exhausted; not retained"
        result = _AgentResult(agent_id=task.agent_id, success=False, error=error)
        task.call_records.append(self._failure_record(task, task.phase, error, 0))
        self._worker_terminal(task, "failed", result, failure_category="resource_exhausted")
        return result

    def _parse_json_response(self, raw: str, agent_id: str) -> dict[str, Any]:
        """CLAUDE-ADC-E2E-VERIFICATION-EVIDENCE-FIX-001: each candidate
        text below is now tried with strict JSON first and, only if that
        fails, once more with `json.loads(..., strict=False)` before
        being treated as unparseable. LLMs routinely emit a literal,
        unescaped newline/tab inside a JSON string value (a multi-line
        shell command, a diagnostic message) instead of the RFC 8259-
        required \\n/\\t escape; Python's strict-mode parser rejects the
        ENTIRE response for that alone ("Invalid control character..."),
        forcing a wasted retry round-trip even though the JSON is
        otherwise well-formed. `strict=False` relaxes only that one
        literal-control-character-inside-a-string restriction -- it
        still requires genuinely valid JSON syntax (matching braces,
        quoted keys, valid escapes, no trailing commas, ...), so a
        response that is actually malformed still fails both attempts
        and still triggers the existing retry-then-fail path unchanged;
        structured-output validation is not diluted."""
        text = raw.strip()
        exceptions = []

        def _parse(candidate: str, label: str):
            try:
                return json.loads(candidate)
            except json.JSONDecodeError as e:
                exceptions.append(f"{label}{e}")
            try:
                return json.loads(candidate, strict=False)
            except json.JSONDecodeError as e:
                exceptions.append(f"{label}non-strict: {e}")
                return _JSON_PARSE_FAILED

        # Versuch 1: direktes JSON
        result = _parse(text, "")
        if result is not _JSON_PARSE_FAILED:
            return result

        # Versuch 2: JSON in Markdown-Codeblock
        import re
        m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if m:
            result = _parse(m.group(1).strip(), "codeblock: ")
            if result is not _JSON_PARSE_FAILED:
                return result

        # Versuch 3: erste { … } im Text
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            result = _parse(m.group(0), "brace-extraction: ")
            if result is not _JSON_PARSE_FAILED:
                return result

        raise AgentParseError(
            agent_id,
            f"Could not parse JSON: {'; '.join(exceptions)}",
            raw_response=raw,
        )

    # ------------------------------------------------------------------
    # Degraded / empty results
    # ------------------------------------------------------------------

    def _build_empty_result(self, council_input: CouncilInput, chairman_error: str) -> CouncilResult:
        return CouncilResult(
            id=self._run_id,
            project_id=council_input.project_id,
            stack=council_input.detected_stack or "",
            chairman_error=chairman_error,
            council_complete=False,
        )

    # ------------------------------------------------------------------
    # Trace persistence
    # ------------------------------------------------------------------

    def _persist_trace(
        self,
        council_input: CouncilInput,
        proposal_set: ProposalSet,
        vote_sets: tuple[AgentVoteSet, ...],
        council_result: CouncilResult,
        started_at: datetime,
    ) -> str:
        trace = CouncilTrace(
            id=self._run_id,
            project_id=council_input.project_id,
            council_result_id=council_result.id,
            council_input_summary={
                "project_id": council_input.project_id,
                "detected_stack": council_input.detected_stack,
                "platform": council_input.platform,
                "requirement_count": len(council_input.requirements),
                "requirements": [
                    {"id": r.id, "name": r.name, "type": r.type, "required": r.required}
                    for r in council_input.requirements
                ],
                "preflight_ready": (
                    council_input.preflight.overall_ready
                    if council_input.preflight else False
                ),
            },
            agent_call_records=tuple(self._call_records),
            raw_proposals=proposal_set.proposals,
            vote_sets=vote_sets,
            merge_decisions=council_result.merge_decisions,
            total_duration_ms=(datetime.now() - started_at).total_seconds() * 1000,
            errors=tuple(
                list(proposal_set.agent_errors)
                + ([f"Chairman: {council_result.chairman_error}"]
                   if council_result.chairman_error else [])
            ),
            started_at=started_at,
        )

        # SUB_REQ_036: the durable write runs on the persistence slot
        # reserved at admission; the public result never waits beyond the
        # finalization budget. Business result, storage state and
        # notification state stay separate: a blocked or failed store yields
        # an explicitly unconfirmed/failed persistence state, and a later
        # confirmation changes only that state, never the snapshot.
        run = self._run
        run_id = self._run_id
        try:
            path = self._trace_dir / council_input.project_id / f"{run_id}.json"
            serialized = self._serialize_trace(trace)
            # Restart retrieval (SUB_REQ_036): the confirmed file carries the
            # critical lifecycle diagnosis; its presence after the atomic,
            # fsync'ed write is the confirmation itself.
            lifecycle = _DIAGNOSIS.get(run_id) or {"run_id": run_id, "omitted": ["lifecycle"]}
            lifecycle["persistence"] = {
                "state": "durable_when_present",
                "detail": "written atomically and fsync'ed before confirmation",
            }
            serialized["lifecycle"] = lifecycle
            # Central secret redaction for everything stored (errors included).
            payload = json.dumps(
                _redact_tree(serialized), indent=2, ensure_ascii=False, default=str,
            ).encode("utf-8")
        except Exception as exc:
            logger.warning(f"Failed to persist CouncilTrace: {exc}")
            self._set_persistence(run_id, "failed", type(exc).__name__)
            return "failed"
        # The pending payload is charged until the writer has dropped it; the
        # writer takes it over (`pending`), this frame keeps no reference.
        serialized = None
        nbytes = len(payload)
        pending = [payload]
        payload = None
        if not _DIAGNOSIS.reserve_extra(nbytes):
            logger.warning("CouncilTrace not persisted: storage capacity exhausted")
            self._set_persistence(run_id, "failed", "storage capacity exhausted")
            return "failed"
        done = threading.Event()
        outcome: dict[str, Any] = {}

        def on_done(state: str, error: str | None) -> None:
            _DIAGNOSIS.release_extra(nbytes)
            self._set_persistence(run_id, state, error)
            outcome["state"] = state
            if state == "confirmed":
                logger.info(f"CouncilTrace persisted: {path}")
            else:
                logger.warning(f"Failed to persist CouncilTrace: {error}")
            done.set()

        if run is not None and run.persistence_reserved:
            run.persistence_reserved = False  # the writer now owns the slot
        elif not _PERSISTENCE.reserve():
            pending.clear()
            _DIAGNOSIS.release_extra(nbytes)
            self._set_persistence(run_id, "failed", "persistence capacity exhausted")
            return "failed"
        self._set_persistence(run_id, "pending", None)
        start_error: str | None = None
        try:
            _PERSISTENCE.write(path, pending, on_done)
        except Exception as exc:
            start_error = type(exc).__name__
        if start_error is not None:
            # Released only after the failed start (and its traceback, which
            # may keep the payload) is gone.
            pending.clear()
            _PERSISTENCE.release()
            _DIAGNOSIS.release_extra(nbytes)
            self._set_persistence(run_id, "failed", start_error)
            return "failed"
        until = time.monotonic() + DEFAULT_PROFILE.finalization_seconds
        if run is not None:
            until = min(until, run.public_deadline)
        if done.wait(max(0.0, until - time.monotonic())):
            return outcome["state"]
        self._set_persistence(run_id, "unconfirmed", "storage confirmation still pending")
        return "unconfirmed"

    @staticmethod
    def _set_persistence(run_id: str, state: str, error: str | None) -> None:
        def change(record: dict[str, Any]) -> None:
            current = record["persistence"].get("state")
            if current in ("confirmed", "failed") and state == "unconfirmed":
                return  # the write already ended; keep its real outcome
            record["persistence"] = {"state": state, "error": error}
        _DIAGNOSIS.update(run_id, change)

    @staticmethod
    def _serialize_trace(trace: CouncilTrace) -> dict[str, Any]:
        return {
            "id": trace.id,
            "project_id": trace.project_id,
            "council_result_id": trace.council_result_id,
            "council_input_summary": trace.council_input_summary,
            "agent_call_records": [
                {
                    "agent_id": r.agent_id,
                    "role": r.role,
                    "provider": r.provider,
                    "model": r.model,
                    "temperature": r.temperature,
                    "phase": r.phase,
                    "started_at": r.started_at.isoformat(),
                    "duration_ms": r.duration_ms,
                    "success": r.success,
                    "error": r.error,
                    "raw_response_snippet": r.raw_response_snippet,
                    "structured_output_summary": r.structured_output_summary,
                }
                for r in trace.agent_call_records
            ],
            "raw_proposal_count": len(trace.raw_proposals),
            "vote_set_count": len(trace.vote_sets),
            "merge_decision_count": len(trace.merge_decisions),
            "total_duration_ms": trace.total_duration_ms,
            "errors": list(trace.errors),
            "started_at": trace.started_at.isoformat(),
            "completed_at": trace.completed_at.isoformat(),
        }
