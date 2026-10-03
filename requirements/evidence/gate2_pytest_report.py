"""pytest plugin used only by the authoritative Gate-2 runner
(requirements/evidence/gate2_proof.py): writes the CURRENT session's
collected nodeids and per-node outcomes to a temporary JSON file.

Outcomes are not re-derived here -- they are the same per-node record
the root conftest already keeps for every session
(requirements/evidence/current_run_completion.py: setup/call/teardown
phases, skips, xfails and pytest_deselected). This plugin only exports
that in-memory record for one run; it is never a persisted Evidence
store and never reads historical results.
"""
from __future__ import annotations

import json

import pytest

from . import current_run_completion

REPORT_SCHEMA = "adc-gate2-current-run/1"

_COLLECTED: list[str] = []


def pytest_addoption(parser):
    parser.addoption(
        "--adc-gate2-report", default=None,
        help="Write this session's collected nodeids and outcomes as JSON (Gate-2 runner only).",
    )


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(session, config, items):
    # tryfirst: record every collected item before any -k/-m deselection.
    _COLLECTED.extend(item.nodeid for item in items)


def pytest_sessionfinish(session, exitstatus):
    path = session.config.getoption("--adc-gate2-report")
    if not path:
        return
    outcomes = current_run_completion.current_run_outcomes()
    collected = sorted(set(_COLLECTED) | set(outcomes))
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "schema": REPORT_SCHEMA,
            "collect_only": bool(session.config.getoption("collectonly")),
            "exitstatus": int(exitstatus),
            "collected": collected,
            "outcomes": {nodeid: outcomes[nodeid] for nodeid in sorted(outcomes)},
        }, f, indent=1, sort_keys=True)
