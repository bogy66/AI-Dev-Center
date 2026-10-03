"""Live S4/S5 lifecycle boundary notifications.

DevelopmentTestingStage and ControlledReworkStage report each real
lifecycle boundary (development, test generation, change provenance,
controlled testing, diagnosis, controlled rework) at the moment it
actually happens. The orchestrating workflow installs an observer for
the duration of one run -- which records the central DiagnosticTrace
events -- so trace timestamps and ordering reflect real execution
instead of a projection made after the whole operation returned.

A context variable (not a stage/request parameter) keeps every existing
stage and request signature unchanged; without an installed observer
every notification is a no-op.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

BOUNDARIES = frozenset({
    "development_started", "development_finished",
    "test_generation_started", "test_generation_finished",
    "change_provenance", "testing_started", "testing_finished",
    "diagnosis_finished", "rework_started", "rework_finished",
})

_observer: ContextVar = ContextVar("adc_development_lifecycle_observer", default=None)


@contextmanager
def observing(observer):
    """Install `observer` (an object with `boundary(name, cycle, **data)`)
    for the enclosed execution only."""
    token = _observer.set(observer)
    try:
        yield observer
    finally:
        _observer.reset(token)


def cycle_of(request) -> str:
    return "rework" if getattr(request, "rework_request", None) else "initial"


def notify(boundary: str, cycle: str, **data) -> None:
    if boundary not in BOUNDARIES:
        raise ValueError(f"Unknown development lifecycle boundary: {boundary!r}")
    observer = _observer.get()
    if observer is not None:
        observer.boundary(boundary, cycle, **data)
