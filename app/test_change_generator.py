"""Generate structured test changes without executing or applying them."""
from enum import Enum

from app.structured_change_generation import generate_structured_changes


class TestChangeDisposition(str, Enum):
    """The two, and only two, S4.2-owned tester dispositions.

    CHANGES is the default whenever a response is silent about
    `disposition` -- every existing valid tester response remains
    valid. NO_CHANGES_REQUIRED is an explicit, evidenced declaration
    that no test-file mutation is needed this cycle -- never inferred
    from an empty `changes` array alone.
    """
    CHANGES = "changes"
    NO_CHANGES_REQUIRED = "no_changes_required"


def _validate_tester_disposition(parsed: dict) -> dict:
    """Enforce the S4.2 no-op contract on an already structurally-valid
    parsed tester response.

    This is deliberately NOT a second repair pass: `generate_structured_
    changes()` already owns the one-repair-then-fail-closed policy for
    structural/JSON malformation. A semantic contradiction discovered
    here (e.g. a claimed no-op that also proposes changes) fails closed
    immediately instead, exactly as a structural violation would have.
    """
    raw_disposition = parsed.get("disposition")
    if raw_disposition is None:
        disposition = TestChangeDisposition.CHANGES
    else:
        try:
            disposition = TestChangeDisposition(raw_disposition)
        except ValueError:
            raise ValueError(
                f"Invalid tester response: unknown disposition {raw_disposition!r}"
            ) from None

    changes = parsed.get("changes") or []
    reason = parsed.get("reason")

    if disposition is TestChangeDisposition.NO_CHANGES_REQUIRED:
        if changes:
            raise ValueError(
                "Invalid tester response: no_changes_required must not include changes"
            )
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(
                "Invalid tester response: no_changes_required requires a non-empty reason"
            )

    return {**parsed, "disposition": disposition.value, "reason": reason}


class TestChangeGenerator:
    """Test Change Generation: generate structured test changes only.

    Never mutates the filesystem or provenance -- that is exclusively
    ChangeApplicationService's responsibility.

    Owns the S4.2 no-op contract exclusively: a tester may explicitly
    declare `disposition: "no_changes_required"` (with a non-empty
    `reason`) when existing repository tests/verification already
    sufficiently cover the task, so ADC never forces a fabricated
    test-file mutation just to satisfy the S4.3 apply contract. No
    other component -- DeveloperAgent, ChangeApplicationService,
    DeveloperFileApplier, TestingStage, or the `tests` metadata array --
    has any authority over this decision.
    """
    __test__ = False
    def __init__(self, executor):
        self._executor = executor

    def generate(self, request):
        parsed = generate_structured_changes(self._executor, "tester", request.task, "test-file changes")
        return _validate_tester_disposition(parsed)
