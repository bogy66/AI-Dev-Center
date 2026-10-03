"""Tests for CLAUDE-ADC-COUNCIL-DIAGNOSTIC-TRACE-INTEGRATION-FIX-001's
composition-level fix: app.canonical_composition.build_canonical_components()
accepts an optional, explicit `diagnostic_trace_path` so a caller that
temporarily changes its working directory (Real-System-E2E's own owned
temp workspace being the motivating case) can anchor the central
app.diagnostic_trace.DiagnosticTrace's events.jsonl OUTSIDE that
workspace, surviving its cleanup -- without opening a second file/sink
and without changing WorkflowManager's own, separate workflow_state.json
storage semantics.
"""

import shutil
from pathlib import Path

import pytest

from app.canonical_composition import build_canonical_components
from app.diagnostic_trace import DiagnosticTraceStore


@pytest.fixture
def _composed(tmp_path, monkeypatch):
    """Build a real config-backed composition inside an owned, CWD-chdir'd
    workspace -- mirrors Real-System-E2E's/test_productive_web_e2e.py's
    own established fixture pattern."""
    owned_root = tmp_path / "owned-workspace"
    owned_root.mkdir()
    config_path = owned_root / "ai-dev-center.yml"
    shutil.copy2(Path(__file__).parents[1] / "config" / "ai-dev-center.yml", config_path)
    monkeypatch.chdir(owned_root)

    def compose(diagnostic_trace_path=None):
        return build_canonical_components(
            str(config_path), diagnostic_trace_path=diagnostic_trace_path,
        )

    return owned_root, compose


def test_default_composition_is_unchanged_when_no_path_is_given(_composed):
    """Every existing production/test caller omits diagnostic_trace_path
    -- behavior must be byte-for-byte identical to before this task."""
    owned_root, compose = _composed

    components = compose()

    default_path = owned_root / ".diagnostic-traces" / "events.jsonl"
    assert (
        components.service._diagnostic_trace.store.path.resolve() == default_path.resolve()
    )


def test_explicit_diagnostic_trace_path_is_used_instead_of_the_cwd_relative_default(_composed):
    owned_root, compose = _composed
    persistent_path = owned_root.parent / "persistent" / "events.jsonl"

    components = compose(diagnostic_trace_path=persistent_path)

    assert components.service._diagnostic_trace.store.path == persistent_path
    default_path = owned_root / ".diagnostic-traces" / "events.jsonl"
    assert not default_path.exists()


def test_development_workflow_receives_the_same_injected_trace_instance(_composed):
    """set_diagnostic_trace() wiring (ProjectSetupApplicationService.
    __init__, unmodified by this task) must still reach
    DevelopmentWorkflow -- EngineeringCouncil's own set_result_callback()
    ultimately routes through it."""
    owned_root, compose = _composed
    persistent_path = owned_root.parent / "persistent" / "events.jsonl"

    components = compose(diagnostic_trace_path=persistent_path)

    assert components.development_workflow._diagnostic_trace is components.service._diagnostic_trace


def test_injected_trace_evidence_survives_simulated_owned_workspace_cleanup(_composed):
    owned_root, compose = _composed
    persistent_path = owned_root.parent / "persistent" / "events.jsonl"
    components = compose(diagnostic_trace_path=persistent_path)

    components.service._diagnostic_trace.record(
        "run-1", "engineering_council", "completed", "completed",
        "Council structured result",
    )
    assert persistent_path.exists()

    shutil.rmtree(owned_root)

    assert persistent_path.exists(), "trace evidence must survive owned-workspace cleanup"
    events = DiagnosticTraceStore(persistent_path).read("run-1")
    assert len(events) == 1
