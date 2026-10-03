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

import re
from typing import Any

from app.developer_changes import DeveloperChanges

_ERROR_CLASS_PREFIX = re.compile(r"\AInvalid (?:developer|LLM|tester) response:\s*")


class StructuredChanges(dict):
    """The parsed change-set dict, plus redacted generation evidence.

    A plain dict for every existing consumer (equality, key access,
    S4.3 application); `generation_evidence` only ever carries fixed,
    ADC-authored classification tokens, counts and booleans -- never
    provider text, file paths or file contents.
    """

    def __init__(self, parsed: dict, generation_evidence: dict):
        super().__init__(parsed)
        self.generation_evidence = generation_evidence


def parse_error_class(error: Exception) -> str:
    """Bounded, content-free classification of a structured parse error.

    Keeps only the ADC-authored message head before any ':' (where a
    provider-supplied value such as a path or action may follow), as a
    lowercase token.
    """
    head = _ERROR_CLASS_PREFIX.sub("", str(error)).split(":", 1)[0]
    token = re.sub(r"[^a-z0-9]+", "_", head.lower()).strip("_")
    return token[:64] or "unclassified"


def _repair_instructions(role: str, item_description: str) -> str:
    instructions = (
        "Your previous response to the task above violated the required output format. "
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


def _repair_task(role: str, task: str, item_description: str) -> str:
    """The one repair call's task: the ORIGINAL task followed by the
    format correction -- never a new, context-free task. The malformed
    previous response itself is deliberately not echoed back."""
    return "\n\n".join([
        task,
        "----- OUTPUT FORMAT CORRECTION -----",
        _repair_instructions(role, item_description),
    ])


def generate_structured_changes(
    executor, role: str, task: str, item_description: str = "changes",
) -> dict[str, Any]:
    """Invoke `role` once; parse structured JSON; repair-retry exactly once.

    On a malformed first response (including Markdown-fenced JSON, which
    is deliberately not parsed permissively), sends one repair call that
    retains the original task plus the format correction (parameterized
    by `item_description`, and by `role` for the tester's own additional
    no-op shape) and parses that response too.
    If the repaired response is ALSO malformed, the original parse error
    is re-raised -- never a silent fallback to prose or a partially
    parsed structure, and never more than two provider calls.

    This function only owns structural/JSON-contract repair. It never
    interprets or validates the S4.2 no-op contract itself (disposition/
    reason semantics) -- that authority belongs exclusively to
    TestChangeGenerator, applied only after this function already
    returned a structurally valid result -- and it never judges an empty
    `changes` array: S4.1 emptiness is failed closed by DevelopmentStage.

    Returns a StructuredChanges dict carrying redacted generation
    evidence (repair attempted, parse error classes, generated change
    count).
    """
    evidence = {"repair_attempted": False}
    response = executor.run(role, task, "", role)
    try:
        parsed = DeveloperChanges.parse_structured(response)
    except ValueError as structured_error:
        evidence["repair_attempted"] = True
        evidence["initial_parse_error_class"] = parse_error_class(structured_error)
        repair_response = executor.run(
            role, _repair_task(role, task, item_description), "", role,
        )
        try:
            parsed = DeveloperChanges.parse_structured(repair_response)
        except ValueError as repair_error:
            evidence["repair_parse_error_class"] = parse_error_class(repair_error)
            structured_error.generation_evidence = evidence
            raise structured_error
    evidence["generated_change_count"] = len(parsed.get("changes", []))
    return StructuredChanges(parsed, evidence)
