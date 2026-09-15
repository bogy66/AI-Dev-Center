"""Shared structured-JSON generate+repair mechanism for 3.1/3.2.

`DeveloperAgent` (3.1 Development Change Generation) and
`TestChangeGenerator` (3.2 Test Change Generation) are distinct role
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


def _repair_instructions(item_description: str) -> str:
    return (
        "Your previous response violated the required output format. "
        "Return ONLY a valid JSON object with exactly this structure: "
        '{"changes": [{"file": "relative/path", "action": "create|update|delete", '
        '"content": "complete file content"}], "tests": ["test"]}. '
        f"Include all previously identified {item_description}. "
        "No markdown, no commentary outside the JSON."
    )


def generate_structured_changes(
    executor, role: str, task: str, item_description: str = "changes",
) -> dict[str, Any]:
    """Invoke `role` once; parse structured JSON; repair-retry exactly once.

    On a malformed first response, sends one repair prompt (parameterized
    by `item_description`, e.g. "changes" or "test-file changes") and
    parses that response too. If the repaired response is ALSO
    malformed, the original parse error is re-raised -- never a silent
    fallback to prose or a partially parsed structure, and never more
    than two provider calls.
    """
    response = executor.run(role, task, "", role)
    try:
        return DeveloperChanges.parse_structured(response)
    except ValueError as structured_error:
        repair_response = executor.run(role, _repair_instructions(item_description), "", role)
        try:
            return DeveloperChanges.parse_structured(repair_response)
        except ValueError:
            raise structured_error
