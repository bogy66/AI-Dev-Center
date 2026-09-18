"""Validation for the ADC Evidence Contract (schema.json).

Kept deliberately separate from publisher.py so the contract itself can be
imported/tested without pulling in filesystem write logic.
"""
import json
import os

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.json")
_schema_cache = None


def load_schema():
    global _schema_cache
    if _schema_cache is None:
        with open(_SCHEMA_PATH, encoding="utf-8") as f:
            _schema_cache = json.load(f)
    return _schema_cache


class EvidenceValidationError(Exception):
    """Raised (or returned as an error list) when an Evidence event does
    not conform to the contract. Never silently repaired — a malformed
    event must be rejected, not guessed at."""


def validate_event(event):
    """Validate `event` (a dict) against the Evidence Contract.

    Returns a list of human-readable error strings. Empty list means
    valid. Never raises for an ordinary schema violation — callers decide
    whether to raise, log, or reject.
    """
    import jsonschema

    schema = load_schema()
    validator = jsonschema.Draft7Validator(schema)
    errors = sorted(validator.iter_errors(event), key=lambda e: list(e.path))
    return [f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors]


def is_valid_event(event):
    return not validate_event(event)
