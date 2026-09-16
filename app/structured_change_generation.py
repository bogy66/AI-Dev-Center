"""Shared structured-JSON generate+repair mechanism for change generation.

`DeveloperAgent` (Development Change Generation) and
`TestChangeGenerator` (Test Change Generation) are distinct role
boundaries -- they must stay separate classes with an explicit,
distinct role identity ("developer" vs "tester") -- but the MECHANICS
of "call the role once, parse the structured JSON contract, and on a
malformed response issue exactly one repair call before failing
closed" are identical between them. This module is the one place that
policy lives, so a future change to the repair mechanism (its retry
count, its fail-closed guarantee) cannot drift between the two role
wrappers.
"""
from __future__ import annotations

from typing import Any

from app.developer_changes import DeveloperChanges


def _repair_instructions(role: str, item_description: str) -> str:
    instructions = (
        "Your previous response violated the required output format. "
        "Return ONLY a valid JSON object with exactly this structure: "
        '{"changes": [{"file": "relative/path", "action": "create|update|delete", '
        '"content": "complete file content"}], "tests": ["test"]}. '
        f"Include all previously identified {item_description}. "
        "No markdown, no commentary outside the JSON."
    )
    if role == "tester":
        # The smallest role-aware addition to the one shared repair
        # mechanism -- the tester alone has a second valid shape (the
        # S4.2 no-op contract), and the repair attempt must not force it
        # to fabricate a change it does not have merely to satisfy the
        # generic structural contract above.
        instructions += (
            ' If no test-file mutation is actually required, you may '
            'instead return exactly {"disposition": "no_changes_required", '
            '"reason": "<concise, non-empty explanation>", "changes": [], '
            '"tests": []} -- but an empty "changes" array alone is never '
            'sufficient to say that.'
        )
    return instructions


def generate_structured_changes(
    executor, role: str, task: str, item_description: str = "changes",
) -> dict[str, Any]:
    """Invoke `role` once; parse structured JSON; repair-retry exactly once.

    On a malformed first response, sends one repair prompt (parameterized
    by `item_description`, e.g. "changes" or "test-file changes", and by
    `role` for the tester's own additional no-op shape) and parses that
    response too. If the repaired response is ALSO malformed, the
    original parse error is re-raised -- never a silent fallback to
    prose or a partially parsed structure, and never more than two
    provider calls.

    This function only owns structural/JSON-contract repair. It never
    interprets or validates the S4.2 no-op contract itself (disposition/
    reason semantics) -- that authority belongs exclusively to
    TestChangeGenerator, applied only after this function already
    returned a structurally valid result.
    """
    response = executor.run(role, task, "", role)
    try:
        return DeveloperChanges.parse_structured(response)
    except ValueError as structured_error:
        repair_response = executor.run(role, _repair_instructions(role, item_description), "", role)
        try:
            return DeveloperChanges.parse_structured(repair_response)
        except ValueError:
            raise structured_error
