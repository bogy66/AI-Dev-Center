"""Disposable productive Web-to-central-workflow E2E coverage.

Only the external LLM provider factories are replaced.  The Web adapter,
application service, Project Intelligence, workflow, Council, materializer,
plan store, approval boundary, workflow state and central trace are real.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest
from fastapi.testclient import TestClient

from app.canonical_composition import build_canonical_components
from app.web_api import (
    WebSetupComponents, app, get_web_setup_components, planning_tasks, sessions,
)


class DeterministicProvider:
    def __init__(self, role: str = "discovery", fail: bool = False):
        self.role = role
        self.fail = fail

    def complete(self, prompt: str) -> str:
        if self.fail:
            raise RuntimeError("deterministic provider failure")
        if self.role == "discovery":
            return json.dumps({"requirements": []})
        if "AUFGABE: Synthetisiere" in prompt:
            return json.dumps({
                "merge_decisions": [],
                "variants": [{
                    "id": "approved-variant", "name": "No setup required",
                    "description": "Existing project tools are sufficient.",
                    "origin_agents": ["A1", "A2", "A3"],
                    "merged_from": ["A1-var-1", "A2-var-1", "A3-var-1"],
                    "rank": 1, "total_score": 4.5,
                    "consensus_level": "strong_consensus",
                    "minority_opinions": [], "environment": "host",
                    "hardware_target": None, "connection": None,
                    "capabilities": [], "toolchain": [], "advantages": [],
                    "disadvantages": [], "risks": [], "confidence": 0.9,
                    "feasibility": "high", "verification": "none required",
                }],
                "rejected_variants": [], "recommendation": "approved-variant",
                "reasoning": "Deterministic test decision.",
            })
        if '"votes"' in prompt:
            return json.dumps({
                "agent_role": self.role,
                "votes": [{
                    "variant_id": f"{agent}-var-1", "scores": {
                        "plausibility": 5, "completeness": 5, "complexity": 5,
                        "risk": 5, "ci_cd_fitness": 5,
                        "maintainability": 5, "cost_efficiency": 5,
                    }, "would_recommend": True,
                    "reasoning": "Deterministic review.", "concerns": [],
                } for agent in ("A1", "A2", "A3")],
            })
        agent = {
            "environment_architect": "A1", "toolchain_integrator": "A2",
            "risk_assessor": "A3",
        }.get(self.role, "A1")
        return json.dumps({"variants": [{
            "variant_id": f"{agent}-var-1", "name": "Existing environment",
            "description": "Use the isolated project as inspected.",
            "environment": "host", "hardware_target": None,
            "connection": None, "capabilities": [], "toolchain": [],
            "advantages": ["No setup"], "disadvantages": [], "risks": [],
            "confidence": 0.9, "feasibility": "high",
            "verification": "none required", "agent_reasoning": "Test fixture",
        }]})


@pytest.fixture
def disposable_productive_web(tmp_path, monkeypatch, request):
    owned_root = tmp_path / f"adc-e2e-{request.node.name}"
    owned_root.mkdir()
    project = owned_root / "project"
    project.mkdir()
    (project / "README.md").write_text("# Disposable E2E project\n", encoding="utf-8")
    config_dir = owned_root / "config"
    config_dir.mkdir()
    config_path = config_dir / "ai-dev-center.yml"
    shutil.copy2(Path(__file__).parents[1] / "config" / "ai-dev-center.yml", config_path)
    original_cwd = Path.cwd()
    monkeypatch.chdir(owned_root)

    def compose(fail_discovery=False, fail_council_role=None):
        monkeypatch.setattr(
            "app.canonical_composition.create_llm_provider",
            lambda *_args, **_kwargs: DeterministicProvider(fail=fail_discovery),
        )
        monkeypatch.setattr(
            "app.engineering_council.create_council_provider",
            lambda config, *_args, **_kwargs: DeterministicProvider(
                config.role, fail=config.role == fail_council_role,
            ),
        )
        components = build_canonical_components(str(config_path))
        return WebSetupComponents(
            components.service, components.plan_store, components.approval,
            components.development_workflow,
        )

    try:
        yield owned_root, project, compose
    finally:
        for task in tuple(planning_tasks.values()):
            task.result(timeout=5)
        sessions.clear()
        app.dependency_overrides.clear()
        monkeypatch.chdir(original_cwd)
        shutil.rmtree(owned_root)
        assert not owned_root.exists()


def test_productive_web_planning_reaches_real_approval_boundary(
    disposable_productive_web,
):
    owned_root, project, compose = disposable_productive_web
    components = compose()
    app.dependency_overrides[get_web_setup_components] = lambda: components

    with TestClient(app) as client:
        response = client.post("/api/workflow/start", json={
            "project_name": "disposable-success",
            "project_directory": str(project),
            "task_description": "Inspect and plan this existing project.",
        })
        assert response.status_code == 202
        session_id = response.json()["session_id"]
        immediate = client.get(f"/api/state/{session_id}").json()
        assert immediate["workflow_status"] in {"planning", "pending_approval"}
        planning_task = planning_tasks.get(session_id)
        if planning_task is not None:
            planning_task.result(timeout=5)
        state = client.get(f"/api/state/{session_id}").json()

    assert state["workflow_status"] == "pending_approval"
    assert state["approval_required"] is True
    assert state["approval_status"] == "pending_approval"
    phases = {event["action"] for event in state["central_trace"]}
    assert {"project_inspection", "requirement_discovery", "preflight",
            "engineering_council", "toolchain_materialization",
            "setup_approval"} <= phases
    assert any(
        event.get("metadata", {}).get("actor") == "Agent A2"
        and event.get("metadata", {}).get("runtime_state") == "thinking"
        for event in state["central_trace"]
    )
    assert any(
        event.get("metadata", {}).get("actor") == "Chairman"
        and event.get("metadata", {}).get("runtime_state") == "completed"
        for event in state["central_trace"]
    )
    assert state["current_activity"] is not None
    assert components.service._workflow_manager.storage.resolve() == (
        owned_root / "workflow_state.json"
    ).resolve()
    assert (owned_root / ".diagnostic-traces" / "events.jsonl").exists()
    assert (owned_root / ".workflow-plans").exists()


def test_productive_incomplete_council_retains_blocked_inspectable_session(
    disposable_productive_web,
):
    owned_root, project, compose = disposable_productive_web
    components = compose(fail_council_role="toolchain_integrator")
    app.dependency_overrides[get_web_setup_components] = lambda: components

    with TestClient(app) as client:
        response = client.post("/api/workflow/start", json={
            "project_name": "disposable-failure",
            "project_directory": str(project),
            "task_description": "Exercise deterministic failure.",
        })
        assert response.status_code == 202
        session_id = response.json()["session_id"]
        planning_task = planning_tasks.get(session_id)
        if planning_task is not None:
            planning_task.result(timeout=5)
        state = client.get(f"/api/state/{session_id}").json()

    assert state["workflow_status"] == "blocked"
    assert state["blocked"] is True
    assert state["approval_required"] is False
    assert state["plan_id"] is None
    assert state["trace"][-1]["event"] == "workflow_planning_blocked"
    assert state["trace"][-1]["status"] == "blocked"
    assert not any(
        event["event"] == "workflow_start_failed" for event in state["trace"]
    )
    discovery_completed = next(
        index for index, event in enumerate(state["central_trace"])
        if event["action"] == "requirement_discovery"
        and event["event"] == "completed"
        and event["status"] == "completed"
    )
    agent_failed = next(
        index for index, event in enumerate(state["central_trace"])
        if event.get("metadata", {}).get("actor") == "Agent A2"
        and event.get("metadata", {}).get("runtime_state") == "failed"
        and event.get("metadata", {}).get("model")
    )
    council_incomplete = next(
        index for index, event in enumerate(state["central_trace"])
        if event["action"] == "engineering_council"
        and event["event"] == "completed"
        and event["status"] == "incomplete"
    )
    council_blocked = next(
        index for index, event in enumerate(state["central_trace"])
        if event["action"] == "engineering_council"
        and event["event"] == "blocked"
        and event["status"] == "blocked"
    )
    assert discovery_completed < agent_failed < council_incomplete < council_blocked
    assert not any(
        event["action"] == "requirement_discovery"
        and event["status"] in {"failed", "blocked"}
        for event in state["central_trace"]
    )
    assert not any(
        event["action"] == "setup_approval"
        for event in state["central_trace"]
    )
    assert not any(
        event["action"] == "toolchain_materialization"
        for event in state["central_trace"]
    )
    workflow_end_statuses = [
        event["status"] for event in state["central_trace"]
        if event["action"] == "workflow_end"
    ]
    assert workflow_end_statuses
    assert set(workflow_end_statuses) == {"blocked"}
    serialized = json.dumps(state)
    assert "deterministic provider failure" not in serialized
    assert not any(path for path in owned_root.parent.iterdir() if path != owned_root)
