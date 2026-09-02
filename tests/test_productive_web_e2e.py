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
        self.prompts = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError("deterministic provider failure")
        if self.role == "discovery":
            return json.dumps({"requirements": [{
                "id": "req-esphome", "name": "esphome",
                "type": "executable", "purpose": "validate project configuration",
                "required": True, "confidence": "high",
                "evidence": ["esphome.yaml"],
            }]})
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
                    "feasibility": "high",
                    "verification": "unsafe-chairman-check --run && next-command",
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
            "verification": "unsafe-agent-check --run && next-command",
            "agent_reasoning": "Test fixture",
        }]})


@pytest.fixture
def disposable_productive_web(tmp_path, monkeypatch, request):
    owned_root = tmp_path / f"adc-e2e-{request.node.name}"
    owned_root.mkdir()
    project = owned_root / "project"
    project.mkdir()
    (project / "README.md").write_text("# Disposable E2E project\n", encoding="utf-8")
    (project / "esphome.yaml").write_text("esphome:\n  name: disposable\n", encoding="utf-8")
    config_dir = owned_root / "config"
    config_dir.mkdir()
    config_path = config_dir / "ai-dev-center.yml"
    shutil.copy2(Path(__file__).parents[1] / "config" / "ai-dev-center.yml", config_path)
    original_cwd = Path.cwd()
    monkeypatch.chdir(owned_root)

    def compose(fail_discovery=False, fail_council_role=None):
        discovery_provider = DeterministicProvider(fail=fail_discovery)
        monkeypatch.setattr(
            "app.canonical_composition.create_llm_provider",
            lambda *_args, **_kwargs: discovery_provider,
        )
        monkeypatch.setattr(
            "app.engineering_council.create_council_provider",
            lambda config, *_args, **_kwargs: DeterministicProvider(
                config.role, fail=config.role == fail_council_role,
            ),
        )
        components = build_canonical_components(str(config_path))
        web_components = WebSetupComponents(
            components.service, components.plan_store, components.approval,
            components.development_workflow,
        )
        web_components.discovery_provider = discovery_provider
        return web_components

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
    interface_events = [
        event for event in state["central_trace"]
        if event.get("metadata", {}).get("interface_data")
    ]
    interface_stages = {
        event["metadata"].get("interface_stage") or event["action"]
        for event in interface_events
    }
    assert {"common_request", "project_inspection", "requirement_discovery",
            "requirement_validation", "preflight", "engineering_council",
            "toolchain_materialization"} <= interface_stages
    expected_entities = {
        "common_request": "common_request",
        "project_inspection": "project_inspection",
        "requirement_discovery": "requirement_discovery",
        "requirement_validation": "requirement_validation",
        "preflight": "preflight",
        "engineering_council": "engineering_council",
        "toolchain_materialization": "toolchain_materializer",
    }
    for stage, entity in expected_entities.items():
        interface = next(
            event["metadata"]["interface_data"] for event in interface_events
            if event["metadata"].get("interface_stage") == stage
        )
        assert interface["info"]["f"]["entity"] == entity
        assert interface["info"]["f"]["entity_version"] == 1
        assert interface["info"]["f"]["implementation_version"] == "adc-python-1"
        for endpoint in ("x", "y"):
            assert {"type", "interface", "source", "destination", "data"} <= set(
                interface["very_verbose"][endpoint]
            )
    common_interface = next(
        event["metadata"]["interface_data"] for event in interface_events
        if event["metadata"].get("interface_stage") == "common_request"
    )
    assert common_interface["very_verbose"]["x"]["interface"] == "web"
    assert common_interface["very_verbose"]["x"]["source"] == "web"
    assert common_interface["very_verbose"]["x"]["data"]["task_description"] == (
        "Inspect and plan this existing project."
    )
    assert common_interface["very_verbose"]["y"]["interface"] == "internal"
    discovery_interface = next(
        event["metadata"]["interface_data"] for event in interface_events
        if event["action"] == "requirement_discovery"
    )
    assert discovery_interface["verbose"]["x"]["data"]["user_request_present"] is True
    assert discovery_interface["verbose"]["f"]["entity"] == "requirement_discovery"
    assert discovery_interface["verbose"]["f"]["entity_version"] == 1
    assert discovery_interface["verbose"]["f"]["implementation_version"] == "adc-python-1"
    assert "model_version" not in discovery_interface["very_verbose"]["f"]
    assert discovery_interface["verbose"]["x"]["interface"] == "internal"
    assert discovery_interface["verbose"]["x"]["source"] == "project_inspection"
    assert discovery_interface["verbose"]["x"]["destination"] == "requirement_discovery"
    assert discovery_interface["verbose"]["x"]["data"]["user_request"] == (
        "Inspect and plan this existing project."
    )
    assert any(
        "Inspect and plan this existing project." in prompt
        for prompt in components.discovery_provider.prompts
    )
    assert discovery_interface["verbose"]["y"]["data"]["requirements"][0]["name"] == "esphome"
    validation_interface = next(
        event["metadata"]["interface_data"] for event in interface_events
        if event["action"] == "requirement_validation"
    )
    assert validation_interface["verbose"]["x"]["data"]["requirements"] == (
        discovery_interface["verbose"]["y"]["data"]["requirements"]
    )
    assert validation_interface["verbose"]["x"]["type"] == "requirement_set"
    assert validation_interface["verbose"]["y"]["type"] == "validation_result"
    preflight_interface = next(
        event["metadata"]["interface_data"] for event in interface_events
        if event["metadata"].get("interface_stage") == "preflight"
    )
    assert preflight_interface["verbose"]["x"]["type"] == "requirement_set"
    assert preflight_interface["verbose"]["y"]["type"] == "preflight_result"
    council_interface = next(
        event["metadata"]["interface_data"] for event in interface_events
        if event["metadata"].get("interface_stage") == "engineering_council"
    )
    assert council_interface["verbose"]["x"]["type"] == "council_input"
    assert council_interface["verbose"]["y"]["type"] == "council_result"
    materializer_interface = next(
        event["metadata"]["interface_data"] for event in interface_events
        if event["metadata"].get("interface_stage") == "toolchain_materialization"
    )
    assert materializer_interface["verbose"]["x"]["type"] == "council_result"
    assert materializer_interface["verbose"]["y"]["type"] == "setup_plan"
    council_outputs = [
        event for event in state["central_trace"]
        if event.get("metadata", {}).get("council_output")
    ]
    assert any(event["metadata"]["result_kind"] == "proposal" for event in council_outputs)
    assert any(event["metadata"]["result_kind"] == "review" for event in council_outputs)
    assert any(event["metadata"]["result_kind"] == "chairman_decision" for event in council_outputs)
    assert all(
        {"info", "verbose", "very_verbose"}
        <= set(event["metadata"]["council_output"])
        for event in council_outputs
    )
    proposal_output = next(
        event["metadata"] for event in council_outputs
        if event["metadata"]["result_kind"] == "proposal"
        and event["metadata"]["actor"] == "Agent A1"
    )
    assert "environment" not in proposal_output["council_output"]["info"]
    assert "environment" in proposal_output["council_output"]["verbose"]
    assert "confidence" in proposal_output["council_output"]["very_verbose"]
    assert proposal_output["provider"] and proposal_output["model"]
    assert proposal_output["interface_data"]["verbose"]["x"]["type"] == "council_input"
    assert proposal_output["interface_data"]["verbose"]["x"]["data"]["requirements"][0]["name"] == "esphome"
    assert proposal_output["interface_data"]["verbose"]["y"]["type"] == "proposal"
    assert proposal_output["interface_data"]["verbose"]["y"]["data"]["name"]
    assert proposal_output["interface_data"]["verbose"]["x"]["source"] == "engineering_council"
    assert proposal_output["interface_data"]["verbose"]["y"]["destination"] == "engineering_council"
    assert proposal_output["interface_data"]["verbose"]["f"]["entity"] == "council_agent_a1_proposal"
    assert proposal_output["interface_data"]["verbose"]["f"]["provider"]
    assert proposal_output["interface_data"]["verbose"]["f"]["model"]
    proposal_entities = {
        event["metadata"]["interface_data"]["verbose"]["f"]["entity"]
        for event in council_outputs
        if event["metadata"]["result_kind"] == "proposal"
    }
    assert proposal_entities == {
        "council_agent_a1_proposal", "council_agent_a2_proposal",
        "council_agent_a3_proposal",
    }
    review_output = next(
        event["metadata"] for event in council_outputs
        if event["metadata"]["result_kind"] == "review"
        and event["metadata"]["actor"] == "Agent A3"
    )
    assert review_output["interface_data"]["verbose"]["x"]["type"] == "proposal_set"
    assert review_output["interface_data"]["verbose"]["x"]["data"]["proposals"]
    assert review_output["interface_data"]["verbose"]["y"]["type"] == "review_set"
    assert review_output["interface_data"]["verbose"]["y"]["data"]["reviews"]
    assert review_output["interface_data"]["verbose"]["x"]["interface"] == "internal"
    review_entities = {
        event["metadata"]["interface_data"]["verbose"]["f"]["entity"]
        for event in council_outputs
        if event["metadata"]["result_kind"] == "review"
    }
    assert review_entities == {
        "council_agent_a1_review", "council_agent_a2_review",
        "council_agent_a3_review",
    }
    chairman_output = next(
        event["metadata"] for event in council_outputs
        if event["metadata"]["result_kind"] == "chairman_decision"
    )
    assert chairman_output["interface_data"]["info"]["x"]["type"] == "council_review_set"
    assert chairman_output["interface_data"]["info"]["x"]["data"]["proposal_count"]
    assert chairman_output["interface_data"]["info"]["y"]["type"] == "chairman_decision"
    assert chairman_output["interface_data"]["info"]["y"]["data"]["council_complete"] is True
    assert chairman_output["interface_data"]["info"]["x"]["destination"] == "chairman"
    assert chairman_output["interface_data"]["info"]["y"]["source"] == "chairman"
    assert chairman_output["interface_data"]["info"]["f"]["entity"] == "chairman"
    assert chairman_output["interface_data"]["info"]["f"]["entity_version"] == 1
    serialized_interfaces = json.dumps(interface_events)
    assert "Inspect and plan this existing project." in serialized_interfaces
    assert "Inspect and plan this existing project." in json.dumps(discovery_interface)
    assert "not available at this boundary" not in serialized_interfaces
    serialized_council_outputs = json.dumps(council_outputs)
    assert "unsafe-agent-check" not in serialized_council_outputs
    assert "unsafe-chairman-check" not in serialized_council_outputs
    assert "next-command" not in serialized_council_outputs
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
    assert any(
        event.get("metadata", {}).get("result_kind") == "proposal"
        and event.get("metadata", {}).get("actor") == "Agent A3"
        and event.get("metadata", {}).get("council_output", {}).get("info", {}).get("name")
        for event in state["central_trace"]
    )
    assert any(
        event.get("metadata", {}).get("result_kind") == "review"
        and event.get("metadata", {}).get("actor") == "Agent A3"
        and event.get("metadata", {}).get("council_output", {}).get("info", {}).get("reviews")
        for event in state["central_trace"]
    )
    partial_proposal = next(
        event["metadata"] for event in state["central_trace"]
        if event.get("metadata", {}).get("result_kind") == "proposal"
        and event.get("metadata", {}).get("actor") == "Agent A3"
    )
    assert partial_proposal["interface_data"]["verbose"]["x"]["data"]["requirements"]
    assert partial_proposal["interface_data"]["verbose"]["y"]["data"]["name"]
    missing_proposal = next(
        event["metadata"] for event in state["central_trace"]
        if event.get("metadata", {}).get("result_kind") == "proposal"
        and event.get("metadata", {}).get("actor") == "Agent A2"
    )
    assert missing_proposal["interface_data"]["verbose"]["y"]["data"]["available"] is False
    assert missing_proposal["interface_data"]["verbose"]["x"]["type"] == "council_input"
    assert missing_proposal["interface_data"]["verbose"]["y"]["type"] == "proposal"
    assert missing_proposal["interface_data"]["verbose"]["f"]["entity"] == "council_agent_a2_proposal"
    assert missing_proposal["interface_data"]["verbose"]["f"]["provider"]
    assert missing_proposal["interface_data"]["verbose"]["f"]["model"]
    workflow_end_statuses = [
        event["status"] for event in state["central_trace"]
        if event["action"] == "workflow_end"
    ]
    assert workflow_end_statuses
    assert set(workflow_end_statuses) == {"blocked"}
    serialized = json.dumps(state)
    assert "deterministic provider failure" not in serialized
    assert "unsafe-agent-check" not in serialized
    assert "unsafe-chairman-check" not in serialized
    assert "next-command" not in serialized
    assert not any(path for path in owned_root.parent.iterdir() if path != owned_root)
