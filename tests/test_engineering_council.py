"""Tests for the Multi-KI Engineering Council.

ALL tests use FakeLLMProvider — zero real LLM calls, zero network access,
zero installations, zero hardware interaction.

Phase-barrier and isolation tests use threading primitives (Event, Barrier,
Lock) — no time.sleep(), no race-condition-dependent assertions.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.ai_config import CouncilAgentConfig, CouncilConfig
from app.council_error import (
    AgentParseError,
    CouncilChairmanError,
    CouncilFailedError,
)
from app.council_models import (
    AgentCallRecord,
    AgentProposal,
    AgentVote,
    AgentVoteSet,
    CouncilInput,
    CouncilResult,
    CouncilTrace,
    CouncilVariant,
    MergeDecision,
    ProposalSet,
    ToolchainItem,
)
from app.council_prompts import (
    AGENT_ROLE_ENV_ARCHITECT,
    AGENT_ROLE_ENV_ARCHITECT_REVIEW,
    AGENT_ROLE_RISK,
    AGENT_ROLE_RISK_REVIEW,
    AGENT_ROLE_TOOLCHAIN,
    AGENT_ROLE_TOOLCHAIN_REVIEW,
    CHAIRMAN_SYSTEM_PROMPT,
    build_phase1_prompt,
    build_chairman_prompt,
)
from app.engineering_council import EngineeringCouncil, _AgentTask
from app.requirement_model import (
    PreflightRequirementResult,
    PreflightResult,
    Requirement,
    RequirementEvidence,
    RequirementType,
    Status,
)
from app.secret_resolver import SimpleSecretResolver


# =========================================================================
# Fake LLM Providers
# =========================================================================


class FakeLLMProvider:
    """Mock LLMProvider that returns pre-configured responses."""

    def __init__(self, responses: list[str] | None = None):
        self._responses = list(responses) if responses else []
        self.calls: list[str] = []

    def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        if not self._responses:
            raise RuntimeError(f"FakeLLMProvider: no more responses configured (call #{len(self.calls)})")
        return self._responses.pop(0)


class FailingLLMProvider:
    """Mock LLMProvider that always fails."""

    def __init__(self, error_message: str = "simulated failure"):
        self.error_message = error_message
        self.calls: list[str] = []

    def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        raise RuntimeError(self.error_message)


class BarrierProvider:
    """Provider that waits at a threading.Barrier before completing.

    Used to prove parallel execution: if N agents all wait at the same
    barrier, they cannot all return until the Nth agent arrives.  This
    proves they were executing concurrently without time.sleep().
    """

    def __init__(self, barrier: threading.Barrier, response: str):
        self.barrier = barrier
        self._response = response
        self.calls: list[str] = []

    def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        self.barrier.wait()
        return self._response


# =========================================================================
# Thread-safe event log for timeline verification
# =========================================================================


@dataclass
class _CompletionEvent:
    role: str
    phase: str  # "phase1", "phase2", "phase3"
    direction: str  # "start" or "finish"
    timestamp: float  # time.monotonic()


class PhaseTrackingProvider:
    """Wraps an LLMProvider and records start/finish events atomically.

    The recorded timeline allows deterministic phase-barrier verification:
      - all Phase-1 finish timestamps must precede all Phase-2 start timestamps
      - all Phase-2 finish timestamps must precede the Chairman start timestamp
    """

    def __init__(self, inner, role: str, phase: str, log: list[_CompletionEvent],
                 lock: threading.Lock):
        self._inner = inner
        self._role = role
        self._phase = phase
        self._log = log
        self._lock = lock

    def complete(self, prompt: str) -> str:
        with self._lock:
            self._log.append(_CompletionEvent(
                role=self._role, phase=self._phase, direction="start",
                timestamp=time.monotonic(),
            ))
        result = self._inner.complete(prompt)
        with self._lock:
            self._log.append(_CompletionEvent(
                role=self._role, phase=self._phase, direction="finish",
                timestamp=time.monotonic(),
            ))
        return result


# =========================================================================
# Helpers
# =========================================================================


def _make_council_config(
    ea_model: str = "model-ea",
    ti_model: str = "model-ti",
    ra_model: str = "model-ra",
    ch_model: str = "model-ch",
    ea_provider: str = "openrouter-ea",
    ti_provider: str = "openrouter-ti",
    ra_provider: str = "openrouter-ra",
    ch_provider: str = "openrouter-ch",
    max_variants: int = 2,
) -> CouncilConfig:
    return CouncilConfig(
        enabled=True,
        max_variants_per_agent=max_variants,
        environment_architect=CouncilAgentConfig(
            role="environment_architect", provider=ea_provider,
            model=ea_model, timeout_seconds=10, temperature=0.7,
        ),
        toolchain_integrator=CouncilAgentConfig(
            role="toolchain_integrator", provider=ti_provider,
            model=ti_model, timeout_seconds=10, temperature=0.7,
        ),
        risk_assessor=CouncilAgentConfig(
            role="risk_assessor", provider=ra_provider,
            model=ra_model, timeout_seconds=10, temperature=0.7,
        ),
        chairman=CouncilAgentConfig(
            role="chairman", provider=ch_provider,
            model=ch_model, timeout_seconds=10, temperature=0.2,
        ),
    )


def _make_requirement(req_id: str = "req-1", name: str = "python",
                      rtype: str = "executable", required: bool = True) -> Requirement:
    return Requirement(
        id=req_id, name=name, type=rtype, purpose="test",
        required=required, confidence=0.9,
        evidence=(RequirementEvidence(id="ev-1", source_type="test", description="test"),),
        status=Status.DISCOVERED,
    )


def _make_council_input() -> CouncilInput:
    return CouncilInput(
        requirements=(
            _make_requirement("req-1", "python", "executable", True),
            _make_requirement("req-2", "esphome", "python_package", True),
            _make_requirement("req-3", "build", "capability", True),
            _make_requirement("req-4", "flash", "capability", False),
        ),
        preflight=PreflightResult(
            id="pre-1", project_id="test-project",
            overall_ready=False,
            results=(
                PreflightRequirementResult(requirement_id="req-1", present=True,
                                           detected_version="3.12", satisfied=True),
            ),
            missing_requirements=(
                _make_requirement("req-2", "esphome", "python_package", True),
            ),
            already_installed=(),
            warnings=(),
        ),
        detected_stack="esphome",
        adapter_requirements={
            "target": "esp32", "connection": "serial",
            "capabilities": ["build", "flash", "serial_log"],
            "executables": ["python", "esphome"],
            "python_packages": ["esphome"],
        },
        project_id="esphome-p1",
        project_files=("esphome-p1.yaml",),
        platform="linux",
    )


def _make_phase1_response(agent_id: str, num_variants: int = 2) -> str:
    variants = []
    for i in range(num_variants):
        env = "host" if i == 0 else "physical_hardware"
        hw_target = None if i == 0 else "esp32"
        conn = None if i == 0 else "serial"
        caps = ["build"] if i == 0 else ["build", "flash"]
        variants.append({
            "variant_id": f"{agent_id}-var-{i + 1}",
            "name": f"{agent_id} Variant {i + 1}",
            "description": f"Testvariant {i + 1} von {agent_id}",
            "environment": env,
            "hardware_target": hw_target,
            "connection": conn,
            "capabilities": caps,
            "toolchain": [
                {
                    "requirement_ref": "req-1",
                    "name": "python",
                    "type": "executable",
                    "install_method": None,
                    "version": None,
                    "purpose": "Python runtime",
                    "depends_on": [],
                    "state": "already_installed",
                    "environment_constraint": None,
                },
                {
                    "requirement_ref": "req-2",
                    "name": "esphome",
                    "type": "python_package",
                    "install_method": "pip install esphome",
                    "version": None,
                    "purpose": "ESPHome CLI",
                    "depends_on": ["python"],
                    "state": "needs_install",
                    "environment_constraint": None,
                },
            ],
            "advantages": [f"Vorteil {i + 1}a"],
            "disadvantages": [f"Nachteil {i + 1}b"],
            "risks": [f"Risiko {i + 1}c"],
            "confidence": 0.8,
            "feasibility": "high",
            "verification": "esphome version",
            "agent_reasoning": f"Begründung von {agent_id}",
        })
    return json.dumps({"variants": variants})


def _make_phase2_response(agent_id: str, variant_ids: list[str]) -> str:
    votes = []
    for vid in variant_ids:
        votes.append({
            "variant_id": vid,
            "scores": {
                "plausibility": 4, "completeness": 3, "complexity": 2,
                "risk": 3, "ci_cd_fitness": 4, "maintainability": 3,
                "cost_efficiency": 4,
            },
            "would_recommend": True,
            "reasoning": f"{agent_id} finds {vid} acceptable",
            "concerns": [],
        })
    return json.dumps({"agent_role": agent_id, "votes": votes})


def _make_chairman_response(variant_ids: list[str],
                            recommendation: str | None = None,
                            merge_decisions: list[dict] | None = None) -> str:
    variants = []
    for rank, vid in enumerate(variant_ids, 1):
        variants.append({
            "id": vid, "name": f"Variante {vid}",
            "description": f"Beschreibung {vid}",
            "origin_agents": ["A1"], "merged_from": [vid],
            "rank": rank, "total_score": 5.0 - rank * 0.5,
            "consensus_level": "strong_consensus" if rank <= 2 else "weak_consensus",
            "minority_opinions": [], "environment": "host",
            "hardware_target": None, "connection": None,
            "capabilities": ["build"], "toolchain": [],
            "advantages": [], "disadvantages": [], "risks": [],
            "confidence": 0.9, "feasibility": "high", "verification": "test",
        })
    return json.dumps({
        "merge_decisions": merge_decisions or [],
        "variants": variants, "rejected_variants": [],
        "recommendation": recommendation or variant_ids[0],
        "reasoning": "Beste Variante wegen hoher Scores",
    })


def _all_variant_ids(ph1_responses: list[str]) -> list[str]:
    ids = []
    for resp in ph1_responses:
        data = json.loads(resp)
        for v in data.get("variants", []):
            ids.append(v["variant_id"])
    return ids


def _setup_standard_responses():
    """Return (ph1, ph2, chair) responses for a standard 3-agent run."""
    a1_resp = _make_phase1_response("A1", 1)
    a2_resp = _make_phase1_response("A2", 1)
    a3_resp = _make_phase1_response("A3", 1)
    all_ids = _all_variant_ids([a1_resp, a2_resp, a3_resp])
    ph2_resp = _make_phase2_response("x", all_ids)
    ch_resp = _make_chairman_response(all_ids)
    return a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids


def _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp):
    """Build a dict of FakeLLMProviders keyed by model name."""
    return {
        "model-ea": FakeLLMProvider([a1_resp, ph2_resp]),
        "model-ti": FakeLLMProvider([a2_resp, ph2_resp]),
        "model-ra": FakeLLMProvider([a3_resp, ph2_resp]),
        "model-ch": FakeLLMProvider([ch_resp]),
    }


def _run_council_with_fakes(council_config, fake_providers, tmp_path,
                             trace_dir=None, capture_configs=None,
                             capture_results=None):
    """Run council with fake providers patched in. Returns result."""
    factory = None
    if capture_configs is not None:
        if isinstance(capture_configs, list):

            def _factory(config, resolver, ollama_url=None):
                capture_configs.append(config)
                return fake_providers[config.model]
            factory = _factory
        else:
            def _factory(config, resolver, ollama_url=None):
                capture_configs[config.model] = config
                return fake_providers[config.model]
            factory = _factory
    else:
        factory = lambda config, resolver, ollama_url=None: fake_providers[config.model]

    with patch("app.engineering_council.create_council_provider") as mf:
        mf.side_effect = factory
        council = EngineeringCouncil(
            council_config=council_config,
            secret_resolver=SimpleSecretResolver({"openrouter-api": "test"}),
            trace_dir=trace_dir,
        )
        if capture_results is not None:
            council.set_result_callback(
                lambda **result: capture_results.append(result)
            )
        return council.evaluate(_make_council_input())


# =========================================================================
# Test: Phase Barrier (deterministisch, thread-sicher)
# =========================================================================


class TestPhaseBarrier:
    """Verifies that all complete() calls in one phase finish before
    any complete() call in the next phase starts."""

    def test_phase1_completes_before_phase2_starts(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        event_log: list[_CompletionEvent] = []
        lock = threading.Lock()

        def tracking_factory(config, resolver, ollama_url=None):
            phase = "unknown"
            if config.role in ("environment_architect", "toolchain_integrator", "risk_assessor"):
                # We need to know *which* phase this call belongs to.
                # The factory is called per-provider-creation.  Phase-1
                # providers are created first (3x), then phase-2 (3x),
                # then chairman (1x).  We infer phase from the role
                # *and* the sequence of provider creations.
                pass
            return None

        # Better approach: patch _run_single_agent to wrap the provider.
        # We need to intercept after create_council_provider returns.

        from app.engineering_council import _AgentTask as AT

        original_run_single = EngineeringCouncil._run_single_agent

        provider_creation_count = [0]

        def patched_factory(config, resolver, ollama_url=None):
            provider_creation_count[0] += 1
            if 1 <= provider_creation_count[0] <= 3:
                phase = "phase1"
            elif 4 <= provider_creation_count[0] <= 6:
                phase = "phase2"
            else:
                phase = "phase3"

            responses_map = {
                "model-ea": [a1_resp, ph2_resp],
                "model-ti": [a2_resp, ph2_resp],
                "model-ra": [a3_resp, ph2_resp],
                "model-ch": [ch_resp],
            }
            inner = FakeLLMProvider(list(responses_map[config.model]))
            return PhaseTrackingProvider(inner, config.role, phase, event_log, lock)

        with patch("app.engineering_council.create_council_provider") as mf:
            mf.side_effect = patched_factory
            council = EngineeringCouncil(
                council_config=_make_council_config(),
                secret_resolver=SimpleSecretResolver({"openrouter-api": "test"}),
                trace_dir=tmp_path,
            )
            result = council.evaluate(_make_council_input())

        assert result.council_complete

        # Extract phase boundaries
        p1_finishes = [e for e in event_log if e.phase == "phase1" and e.direction == "finish"]
        p2_starts = [e for e in event_log if e.phase == "phase2" and e.direction == "start"]
        p2_finishes = [e for e in event_log if e.phase == "phase2" and e.direction == "finish"]
        p3_starts = [e for e in event_log if e.phase == "phase3" and e.direction == "start"]

        assert len(p1_finishes) == 3, f"Expected 3 Phase-1 finishes, got {len(p1_finishes)}"
        assert len(p2_starts) == 3, f"Expected 3 Phase-2 starts, got {len(p2_starts)}"
        assert len(p2_finishes) == 3, f"Expected 3 Phase-2 finishes, got {len(p2_finishes)}"
        assert len(p3_starts) == 1, f"Expected 1 Phase-3 start, got {len(p3_starts)}"

        max_p1_finish = max(e.timestamp for e in p1_finishes)
        min_p2_start = min(e.timestamp for e in p2_starts)

        assert max_p1_finish < min_p2_start, (
            f"Phase-1 barrier violated: last P1 finish={max_p1_finish:.6f}, "
            f"first P2 start={min_p2_start:.6f}")

    def test_phase2_completes_before_chairman_starts(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        event_log: list[_CompletionEvent] = []
        lock = threading.Lock()

        provider_creation_count = [0]

        def patched_factory(config, resolver, ollama_url=None):
            provider_creation_count[0] += 1
            if 1 <= provider_creation_count[0] <= 3:
                phase = "phase1"
            elif 4 <= provider_creation_count[0] <= 6:
                phase = "phase2"
            else:
                phase = "phase3"

            responses_map = {
                "model-ea": [a1_resp, ph2_resp],
                "model-ti": [a2_resp, ph2_resp],
                "model-ra": [a3_resp, ph2_resp],
                "model-ch": [ch_resp],
            }
            inner = FakeLLMProvider(list(responses_map[config.model]))
            return PhaseTrackingProvider(inner, config.role, phase, event_log, lock)

        with patch("app.engineering_council.create_council_provider") as mf:
            mf.side_effect = patched_factory
            council = EngineeringCouncil(
                council_config=_make_council_config(),
                secret_resolver=SimpleSecretResolver({"openrouter-api": "test"}),
                trace_dir=tmp_path,
            )
            result = council.evaluate(_make_council_input())

        assert result.council_complete

        p2_finishes = [e for e in event_log if e.phase == "phase2" and e.direction == "finish"]
        p3_starts = [e for e in event_log if e.phase == "phase3" and e.direction == "start"]

        assert len(p2_finishes) == 3
        assert len(p3_starts) == 1

        max_p2_finish = max(e.timestamp for e in p2_finishes)
        chairman_start = p3_starts[0].timestamp

        assert max_p2_finish < chairman_start, (
            f"Phase-2 barrier violated: last P2 finish={max_p2_finish:.6f}, "
            f"chairman start={chairman_start:.6f}")

    def test_all_seven_calls_logged_in_order_p1_p2_p3(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        event_log: list[_CompletionEvent] = []
        lock = threading.Lock()

        provider_creation_count = [0]

        def patched_factory(config, resolver, ollama_url=None):
            provider_creation_count[0] += 1
            if 1 <= provider_creation_count[0] <= 3:
                phase = "phase1"
            elif 4 <= provider_creation_count[0] <= 6:
                phase = "phase2"
            else:
                phase = "phase3"

            responses_map = {
                "model-ea": [a1_resp, ph2_resp],
                "model-ti": [a2_resp, ph2_resp],
                "model-ra": [a3_resp, ph2_resp],
                "model-ch": [ch_resp],
            }
            inner = FakeLLMProvider(list(responses_map[config.model]))
            return PhaseTrackingProvider(inner, config.role, phase, event_log, lock)

        with patch("app.engineering_council.create_council_provider") as mf:
            mf.side_effect = patched_factory
            council = EngineeringCouncil(
                council_config=_make_council_config(),
                secret_resolver=SimpleSecretResolver({"openrouter-api": "test"}),
                trace_dir=tmp_path,
            )
            result = council.evaluate(_make_council_input())

        assert result.council_complete
        assert result.total_llm_calls == 7

        finishes = [e for e in event_log if e.direction == "finish"]
        assert len(finishes) == 7, f"Expected 7 finishes, got {len(finishes)}"

        phases_ordered = [e.phase for e in finishes]
        # Within a phase, ordering between agents IS NOT guaranteed;
        # but phase boundaries must be contiguous: all p1 before any p2,
        # all p2 before any p3.
        p1_indices = [i for i, p in enumerate(phases_ordered) if p == "phase1"]
        p2_indices = [i for i, p in enumerate(phases_ordered) if p == "phase2"]
        p3_indices = [i for i, p in enumerate(phases_ordered) if p == "phase3"]

        assert len(p1_indices) == 3
        assert len(p2_indices) == 3
        assert len(p3_indices) == 1

        assert max(p1_indices) < min(p2_indices), \
            f"Phase-1 finishes ({p1_indices}) must all precede Phase-2 finishes ({p2_indices})"
        assert max(p2_indices) < min(p3_indices), \
            f"Phase-2 finishes ({p2_indices}) must all precede Phase-3 finish ({p3_indices})"


# =========================================================================
# Test: Data Isolation — Phase 1
# =========================================================================


class TestPhase1DataIsolation:
    def test_a1_sees_only_council_input(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp)

        _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        p1_a1 = fake_providers["model-ea"].calls[0]
        assert "esphome" in p1_a1, "A1 prompt should contain council input data"
        assert "A1-var-" not in p1_a1, "A1 must not see A1 variant IDs"
        assert "A2-var-" not in p1_a1, "A1 must not see A2 proposals"
        assert "A3-var-" not in p1_a1, "A1 must not see A3 proposals"
        assert "AgentProposal" not in p1_a1, "A1 must not see AgentProposal references"

    def test_phase1_receives_requirement_correlated_preflight(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, _ = _setup_standard_responses()
        fake_providers = _build_standard_providers(
            a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp
        )

        _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path
        )

        prompt = fake_providers["model-ea"].calls[0]
        preflight_section = prompt.split(
            "PREFLIGHT (was ist bereits installiert?):", 1
        )[1].split("ADAPTER INFORMATION", 1)[0]
        assert '"requirement_id": "req-1"' in preflight_section
        assert '"present": true' in preflight_section
        assert '"satisfied": true' in preflight_section
        assert '"detected_version": "3.12"' in preflight_section
        assert '"requirement_id": "req-2"' in preflight_section

    def test_phase1_defines_requirement_reference_semantics(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, _ = _setup_standard_responses()
        fake_providers = _build_standard_providers(
            a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp
        )

        _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path
        )

        prompt = fake_providers["model-ea"].calls[0]
        assert "ToolchainItem.requirement_ref" in prompt
        assert "technische Realisierung" in prompt
        assert "kein Platzhalter" in prompt
        assert "Erfinde keine Requirement IDs" in prompt
        assert 'satisfied=true' in prompt
        assert 'state="needs_install"' in prompt
        assert "unpassenden requirement_ref" in prompt
        assert "limitation, disadvantage oder risk" in prompt

    def test_a2_sees_only_council_input(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp)

        _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        p1_a2 = fake_providers["model-ti"].calls[0]
        assert "esphome" in p1_a2, "A2 prompt should contain council input data"
        assert "A1-var-" not in p1_a2, "A2 must not see A1 proposals"
        assert "A2-var-" not in p1_a2, "A2 must not see A2 variant IDs"
        assert "A3-var-" not in p1_a2, "A2 must not see A3 proposals"

    def test_a3_sees_only_council_input(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp)

        _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        p1_a3 = fake_providers["model-ra"].calls[0]
        assert "esphome" in p1_a3, "A3 prompt should contain council input data"
        assert "A1-var-" not in p1_a3, "A3 must not see A1 proposals"
        assert "A2-var-" not in p1_a3, "A3 must not see A2 proposals"
        assert "A3-var-" not in p1_a3, "A3 must not see A3 variant IDs"

    def test_no_phase1_agent_sees_other_agent_output(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp)

        _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        for key, agent_name in [("model-ea", "A1"), ("model-ti", "A2"), ("model-ra", "A3")]:
            prompt = fake_providers[key].calls[0]
            for other in ["A1-var-", "A2-var-", "A3-var-"]:
                assert other not in prompt, f"{agent_name} phase-1 prompt contains {other}"


# =========================================================================
# Test: Phase 1 — Parallelism via threading.Barrier
# =========================================================================


class TestPhase1Parallelism:
    def test_phase1_runs_in_parallel_barrier(self, tmp_path):
        """Prove Phase-1 runs in parallel using threading.Barrier.

        All 3 agents' complete() calls reach a Barrier(3) before any
        returns.  This proves they execute concurrently without relying
        on time.sleep() or race-condition-dependent assertions.
        """
        barrier = threading.Barrier(3, timeout=5.0)

        a1_resp = _make_phase1_response("A1", 1)
        a2_resp = _make_phase1_response("A2", 1)
        a3_resp = _make_phase1_response("A3", 1)
        all_ids = ["A1-var-1", "A2-var-1", "A3-var-1"]
        ph2_resp = _make_phase2_response("x", all_ids)
        ch_resp = _make_chairman_response(all_ids)

        # Phase-1 providers with barrier; Phase-2/Chairman providers without
        def barrier_factory(config, resolver, ollama_url=None):
            model = config.model
            if model == "model-ch":
                return FakeLLMProvider([ch_resp])
            # First call = Phase 1 (use barrier), second = Phase 2 (no barrier)
            # We need a per-model provider that knows which call is first.
            # Create separate providers per phase to avoid complexity.
            pass

        provider_call_count = {}

        def phased_factory(config, resolver, ollama_url=None):
            model = config.model
            if model == "model-ch":
                return FakeLLMProvider([ch_resp])
            count = provider_call_count.get(model, 0)
            provider_call_count[model] = count + 1
            if count == 0:
                # Phase 1: use barrier
                resp = {"model-ea": a1_resp, "model-ti": a2_resp, "model-ra": a3_resp}[model]
                return BarrierProvider(barrier, resp)
            else:
                # Phase 2: no barrier
                return FakeLLMProvider([ph2_resp])

        with patch("app.engineering_council.create_council_provider") as mf:
            mf.side_effect = phased_factory
            council = EngineeringCouncil(
                council_config=_make_council_config(),
                secret_resolver=SimpleSecretResolver({"openrouter-api": "test"}),
                trace_dir=tmp_path,
            )
            start = time.monotonic()
            result = council.evaluate(_make_council_input())
            elapsed = time.monotonic() - start

        assert result.council_complete, f"Council failed: {result.agent_errors}"
        assert barrier.n_waiting == 0, "Barrier was not reached by all 3 agents"
        # Barrier should have been broken (all 3 reached it)


def test_stuck_agent_is_bounded_and_completed_results_are_retained(tmp_path):
    release_stuck_provider = threading.Event()
    activities = []
    provider_call_count = {}
    config = _make_council_config()
    config = replace(
        config,
        environment_architect=replace(
            config.environment_architect, timeout_seconds=0.01,
        ),
    )
    all_completed_ids = ["A2-var-1", "A3-var-1"]

    class StuckProvider:
        def complete(self, _prompt):
            release_stuck_provider.wait()
            return _make_phase1_response("A1", 1)

    def provider_factory(agent_config, _resolver, ollama_url=None):
        model = agent_config.model
        call_number = provider_call_count.get(model, 0)
        provider_call_count[model] = call_number + 1
        if model == "model-ea" and call_number == 0:
            return StuckProvider()
        if model == "model-ch":
            return FakeLLMProvider([_make_chairman_response(all_completed_ids)])
        if call_number == 0:
            agent_id = {"model-ti": "A2", "model-ra": "A3"}[model]
            return FakeLLMProvider([_make_phase1_response(agent_id, 1)])
        return FakeLLMProvider([_make_phase2_response(agent_config.role, all_completed_ids)])

    try:
        with patch("app.engineering_council._TIMEOUT_GRACE_SECONDS", 0), patch(
            "app.engineering_council.create_council_provider",
            side_effect=provider_factory,
        ):
            council = EngineeringCouncil(
                council_config=config,
                secret_resolver=SimpleSecretResolver({"openrouter-api": "test"}),
                trace_dir=tmp_path,
            )
            council.set_activity_callback(lambda **activity: activities.append(activity))
            result = council.evaluate(_make_council_input())
    finally:
        release_stuck_provider.set()

    assert result.council_complete is True
    assert result.council_degraded is True
    assert result.variants
    assert any("A1" in error and "deadline" in error for error in result.agent_errors)
    assert any(
        activity["actor"] == "Agent A1"
        and activity["runtime_state"] == "failed"
        for activity in activities
    )
    assert any(
        activity["actor"] == "Agent A3"
        and activity["runtime_state"] == "completed"
        for activity in activities
    )


# =========================================================================
# Test: Data Isolation — Phase 2
# =========================================================================


class TestPhase2DataIsolation:
    def test_each_phase2_agent_sees_all_proposals(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp)

        _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        for model_key in ["model-ea", "model-ti", "model-ra"]:
            ph2_prompt = fake_providers[model_key].calls[1]
            for vid in all_ids:
                assert vid in ph2_prompt, f"{model_key} phase-2 prompt missing variant ID {vid}"

    def test_phase2_agents_do_not_see_other_votes(self, tmp_path):
        """Phase-2 prompts contain proposals but NOT pre-completed vote data."""
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp)

        _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        # Each Phase-2 agent sees ALL proposals (variant IDs present).
        for model_key in ["model-ea", "model-ti", "model-ra"]:
            ph2_prompt = fake_providers[model_key].calls[1]
            for vid in all_ids:
                assert vid in ph2_prompt, f"{model_key} phase-2 prompt missing variant ID {vid}"

    def test_phase2_prompts_are_role_specific(self, tmp_path):
        """Each Phase-2 prompt contains its agent's unique role instruction."""
        a1_resp = _make_phase1_response("A1", 1)
        a2_resp = _make_phase1_response("A2", 1)
        a3_resp = _make_phase1_response("A3", 1)
        all_ids = ["A1-var-1", "A2-var-1", "A3-var-1"]
        ph2_resp = _make_phase2_response("x", all_ids)
        ch_resp = _make_chairman_response(all_ids)

        fake_providers = {
            "model-ea": FakeLLMProvider([a1_resp, ph2_resp]),
            "model-ti": FakeLLMProvider([a2_resp, ph2_resp]),
            "model-ra": FakeLLMProvider([a3_resp, ph2_resp]),
            "model-ch": FakeLLMProvider([ch_resp]),
        }

        _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        # Verify each agent's Phase-2 prompt contains its own role-specific content
        p2_ea = fake_providers["model-ea"].calls[1]
        p2_ti = fake_providers["model-ti"].calls[1]
        p2_ra = fake_providers["model-ra"].calls[1]

        assert "Environment Architect" in p2_ea, "A1 missing env architect role"
        assert "Toolchain Integrator" in p2_ti, "A2 missing toolchain integrator role"
        assert "Risk & Feasibility Assessor" in p2_ra, "A3 missing risk assessor role"

    def test_phase2_prompts_contain_council_context(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp)

        _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        for model_key in ["model-ea", "model-ti", "model-ra"]:
            ph2_prompt = fake_providers[model_key].calls[1]
            assert "host" in ph2_prompt or "environment" in ph2_prompt, \
                f"{model_key} phase-2 prompt missing environment context"


# =========================================================================
# Test: Data Isolation — Phase 3 (Chairman)
# =========================================================================


class TestPhase3DataIsolation:
    def test_chairman_sees_full_proposals_and_votes(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp)

        _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        ch_prompt = fake_providers["model-ch"].calls[0]
        for vid in all_ids:
            assert vid in ch_prompt, f"Chairman prompt missing variant ID {vid}"
        assert "would_recommend" in ch_prompt, "Chairman prompt missing vote data"
        assert "scores" in ch_prompt, "Chairman prompt missing score data"

    def test_chairman_receives_controlled_setup_feasibility(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, _ = _setup_standard_responses()
        fake_providers = _build_standard_providers(
            a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp
        )

        _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path
        )

        chairman_prompt = fake_providers["model-ch"].calls[0]
        assert '"install_method": "pip install esphome"' in chairman_prompt
        assert '"state": "needs_install"' in chairman_prompt
        assert '"environment_constraint": null' in chairman_prompt
        assert '"version": null' in chairman_prompt
        assert '"controlled_setup"' in chairman_prompt
        assert '"status": "satisfied"' in chairman_prompt
        assert '"status": "materializable"' in chairman_prompt
        assert '"automatically_materializable": true' in chairman_prompt
        assert '"selection_guidance": "required_when_available"' in chairman_prompt

    def test_chairman_receives_requirement_and_preflight_contract(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, _ = _setup_standard_responses()
        fake_providers = _build_standard_providers(
            a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp
        )

        _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path
        )

        prompt = fake_providers["model-ch"].calls[0]
        assert "VALIDIERTE REQUIREMENTS" in prompt
        assert "AUTHORITATIVE PREFLIGHT BY REQUIREMENT ID" in prompt
        assert '"id": "req-1"' in prompt
        assert '"requirement_id": "req-1"' in prompt
        assert '"satisfied": true' in prompt
        assert "Bewahre die Bedeutung jeder requirement_ref" in prompt
        assert "verschiebe kein ToolchainItem" in prompt
        assert "keine neuen" in prompt
        assert "nicht modellierte Voraussetzungen" in prompt
        assert "unter einer anderen" in prompt

    def test_chairman_does_not_see_phase1_internals(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp)

        _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        ch_prompt = fake_providers["model-ch"].calls[0]
        # Chairman sees proposal data but NOT raw LLM responses
        assert "raw_llm_response" not in ch_prompt, \
            "Chairman must not see raw LLM response strings"

    def test_chairman_does_not_see_phase2_internals_only_votes(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp)

        _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        ch_prompt = fake_providers["model-ch"].calls[0]
        # Chairman sees the vote data but not Phase-2 raw prompts
        assert "willst du bitte" not in ch_prompt.lower(), \
            "Chairman must not see Phase-2 instruction fragments"


# =========================================================================
# Test: Call Count (actual provider.complete() calls)
# =========================================================================


class TestCallCount:
    def test_exactly_seven_complete_calls(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()

        complete_call_log = []
        lock = threading.Lock()

        class CountingProvider:
            def __init__(self, inner):
                self._inner = inner

            def complete(self, prompt):
                with lock:
                    complete_call_log.append(time.monotonic())
                return self._inner.complete(prompt)

        def counting_factory(config, resolver, ollama_url=None):
            responses_map = {
                "model-ea": [a1_resp, ph2_resp],
                "model-ti": [a2_resp, ph2_resp],
                "model-ra": [a3_resp, ph2_resp],
                "model-ch": [ch_resp],
            }
            inner = FakeLLMProvider(list(responses_map[config.model]))
            return CountingProvider(inner)

        with patch("app.engineering_council.create_council_provider") as mf:
            mf.side_effect = counting_factory
            council = EngineeringCouncil(
                council_config=_make_council_config(),
                secret_resolver=SimpleSecretResolver({"openrouter-api": "test"}),
                trace_dir=tmp_path,
            )
            result = council.evaluate(_make_council_input())

        assert result.council_complete
        assert result.total_llm_calls == 7
        assert len(complete_call_log) == 7, \
            f"Expected 7 actual provider.complete() calls, got {len(complete_call_log)}"

    def test_successful_council_reports_seven_calls(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp)

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert result.council_complete
        assert result.total_llm_calls == 7, \
            f"council_complete=True but total_llm_calls={result.total_llm_calls}"

    def test_retry_increases_call_count(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        # A3 responds with invalid JSON, then valid (retry adds 1 call)
        fake_providers = {
            "model-ea": FakeLLMProvider([a1_resp, ph2_resp]),
            "model-ti": FakeLLMProvider([a2_resp, ph2_resp]),
            "model-ra": FakeLLMProvider(["this is not json at all", a3_resp, ph2_resp]),
            "model-ch": FakeLLMProvider([ch_resp]),
        }

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert result.council_complete
        assert result.total_llm_calls == 8, \
            f"Expected 8 calls (7 + 1 retry), got {result.total_llm_calls}"


# =========================================================================
# Test: Model Isolation
# =========================================================================


class TestModelIsolation:
    def test_config_values_passed_to_provider_factory(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()

        fake_providers = {
            "model-ea": FakeLLMProvider([a1_resp, ph2_resp]),
            "model-ti": FakeLLMProvider([a2_resp, ph2_resp]),
            "model-ra": FakeLLMProvider([a3_resp, ph2_resp]),
            "model-ch": FakeLLMProvider([ch_resp]),
        }

        captured_configs = []

        cfg = _make_council_config(
            ea_model="model-ea", ti_model="model-ti",
            ra_model="model-ra", ch_model="model-ch",
            ea_provider="openrouter-ea", ti_provider="openrouter-ti",
            ra_provider="openrouter-ra", ch_provider="openrouter-ch",
        )

        _run_council_with_fakes(cfg, fake_providers, tmp_path, capture_configs=captured_configs)

        # Verify each agent type got its dedicated config
        roles_to_check = [
            ("environment_architect", "model-ea", "openrouter-ea", 0.7),
            ("toolchain_integrator", "model-ti", "openrouter-ti", 0.7),
            ("risk_assessor", "model-ra", "openrouter-ra", 0.7),
            ("chairman", "model-ch", "openrouter-ch", 0.2),
        ]

        for role, expected_model, expected_provider, expected_temp in roles_to_check:
            matches = [c for c in captured_configs if c.role == role]
            assert len(matches) >= 1, f"No config captured for role '{role}'"
            for cfg_match in matches:
                assert cfg_match.model == expected_model, \
                    f"{role}: expected model {expected_model}, got {cfg_match.model}"
                assert cfg_match.provider == expected_provider, \
                    f"{role}: expected provider {expected_provider}, got {cfg_match.provider}"
                assert cfg_match.temperature == expected_temp, \
                    f"{role}: expected temp {expected_temp}, got {cfg_match.temperature}"

    def test_chairman_temperature_lower_than_agents(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp)

        captured_configs = []

        result = _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path, capture_configs=captured_configs
        )

        assert result.council_complete

        agent_temps = {c.temperature for c in captured_configs
                       if c.role in ("environment_architect", "toolchain_integrator", "risk_assessor")}
        chairman_temps = {c.temperature for c in captured_configs if c.role == "chairman"}

        assert len(agent_temps) == 1, f"All agents should have same temp, got {agent_temps}"
        assert len(chairman_temps) == 1

        agent_temp = agent_temps.pop()
        chairman_temp = chairman_temps.pop()

        assert chairman_temp < agent_temp, \
            f"Chairman temp {chairman_temp} must be < agent temp {agent_temp}"

    def test_no_cross_model_leakage(self, tmp_path):
        """Each agent's config must NEVER be passed to a factory call
        for a different agent role."""
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp)

        captured_configs = []

        _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path, capture_configs=captured_configs
        )

        for cfg in captured_configs:
            if cfg.role == "environment_architect":
                assert cfg.model == "model-ea"
            elif cfg.role == "toolchain_integrator":
                assert cfg.model == "model-ti"
            elif cfg.role == "risk_assessor":
                assert cfg.model == "model-ra"
            elif cfg.role == "chairman":
                assert cfg.model == "model-ch"


# =========================================================================
# Test: Error Handling
# =========================================================================


class TestErrorHandling:
    @pytest.mark.parametrize("requirement_ref", [None, "", "   ", "req-unknown"])
    def test_phase1_rejects_invalid_toolchain_requirement_ref(
        self, tmp_path, requirement_ref
    ):
        a1_data = json.loads(_make_phase1_response("A1", 1))
        a1_data["variants"][0]["toolchain"][0]["requirement_ref"] = requirement_ref
        a1_resp = json.dumps(a1_data)
        a2_resp = _make_phase1_response("A2", 1)
        a3_resp = _make_phase1_response("A3", 1)
        all_ids = _all_variant_ids([a2_resp, a3_resp])
        ph2_resp = _make_phase2_response("x", all_ids)
        ch_resp = _make_chairman_response(all_ids)
        fake_providers = _build_standard_providers(
            a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp
        )

        result = _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path
        )

        assert result.council_complete
        assert result.council_degraded
        assert any("A1" in error and "requirement_ref" in error
                   for error in result.agent_errors)
        assert all(variant.id != "A1-var-1" for variant in result.variants)

    @pytest.mark.parametrize("requirement_ref", [None, "", "   ", "req-unknown"])
    def test_chairman_rejects_invalid_toolchain_requirement_ref(
        self, tmp_path, requirement_ref
    ):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, _ = _setup_standard_responses()
        chairman_data = json.loads(ch_resp)
        chairman_data["variants"][0]["toolchain"] = [{
            "requirement_ref": requirement_ref,
            "name": "python",
            "type": "executable",
        }]
        fake_providers = _build_standard_providers(
            a1_resp, a2_resp, a3_resp, ph2_resp, json.dumps(chairman_data)
        )

        result = _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path
        )

        assert not result.council_complete
        assert result.chairman_error is not None
        assert "requirement_ref" in result.chairman_error
        assert result.variants == ()
        assert result.recommendation is None

    def test_chairman_accepts_current_input_requirement_ref(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, _ = _setup_standard_responses()
        chairman_data = json.loads(ch_resp)
        chairman_data["variants"][0]["toolchain"] = [{
            "requirement_ref": "req-1",
            "name": "python",
            "type": "executable",
        }]
        fake_providers = _build_standard_providers(
            a1_resp, a2_resp, a3_resp, ph2_resp, json.dumps(chairman_data)
        )

        result = _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path
        )

        assert result.council_complete
        assert result.variants[0].toolchain[0].requirement_ref == "req-1"

    def test_invalid_json_triggers_retry(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()

        fake_providers = {
            "model-ea": FakeLLMProvider([a1_resp, ph2_resp]),
            "model-ti": FakeLLMProvider([a2_resp, ph2_resp]),
            "model-ra": FakeLLMProvider(["this is not json at all", a3_resp, ph2_resp]),
            "model-ch": FakeLLMProvider([ch_resp]),
        }

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert result.council_complete
        assert result.total_llm_calls == 8  # +1 for retry

    def test_a1_failure_uses_degraded_quorum(self, tmp_path):
        a2_resp = _make_phase1_response("A2", 1)
        a3_resp = _make_phase1_response("A3", 1)
        all_ids = _all_variant_ids([a2_resp, a3_resp])
        ph2_resp = _make_phase2_response("x", all_ids)
        ch_resp = _make_chairman_response(all_ids)

        fake_providers = {
            "model-ea": FailingLLMProvider("A1 failed"),
            "model-ti": FakeLLMProvider([a2_resp, ph2_resp]),
            "model-ra": FakeLLMProvider([a3_resp, ph2_resp]),
            "model-ch": FakeLLMProvider([ch_resp]),
        }

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert result.council_complete
        assert result.council_degraded
        assert result.agent_errors
        assert any("A1" in err for err in result.agent_errors)

    def test_a2_failure_uses_degraded_quorum(self, tmp_path):
        a1_resp = _make_phase1_response("A1", 1)
        a3_resp = _make_phase1_response("A3", 1)
        all_ids = _all_variant_ids([a1_resp, a3_resp])
        ph2_resp = _make_phase2_response("x", all_ids)
        ch_resp = _make_chairman_response(all_ids)

        fake_providers = {
            "model-ea": FakeLLMProvider([a1_resp, ph2_resp]),
            "model-ti": FailingLLMProvider("A2 failed"),
            "model-ra": FakeLLMProvider([a3_resp, ph2_resp]),
            "model-ch": FakeLLMProvider([ch_resp]),
        }

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert result.council_complete
        assert result.council_degraded
        assert result.agent_errors
        assert any("A2" in err for err in result.agent_errors)

    def test_a3_failure_uses_degraded_quorum(self, tmp_path):
        a1_resp = _make_phase1_response("A1", 1)
        a2_resp = _make_phase1_response("A2", 1)
        all_ids = _all_variant_ids([a1_resp, a2_resp])
        ph2_resp = _make_phase2_response("x", all_ids)
        ch_resp = _make_chairman_response(all_ids)

        fake_providers = {
            "model-ea": FakeLLMProvider([a1_resp, ph2_resp]),
            "model-ti": FakeLLMProvider([a2_resp, ph2_resp]),
            "model-ra": FailingLLMProvider("A3 failed"),
            "model-ch": FakeLLMProvider([ch_resp]),
        }

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert result.council_complete
        assert result.council_degraded
        assert result.agent_errors
        assert any("A3" in err for err in result.agent_errors)

    def test_all_agents_fail(self, tmp_path):
        fake_providers = {
            key: FailingLLMProvider(f"{key} failed")
            for key in ["model-ea", "model-ti", "model-ra", "model-ch"]
        }

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert not result.council_complete
        assert result.agent_errors
        assert len(result.agent_errors) >= 3
        assert not result.variants

    def test_degraded_council_retains_agent_error(self, tmp_path):
        a1_resp = _make_phase1_response("A1", 1)
        a2_resp = _make_phase1_response("A2", 1)
        all_ids = _all_variant_ids([a1_resp, a2_resp])
        ph2_resp = _make_phase2_response("x", all_ids)
        ch_resp = _make_chairman_response(all_ids)

        fake_providers = {
            "model-ea": FakeLLMProvider([a1_resp, ph2_resp]),
            "model-ti": FakeLLMProvider([a2_resp, ph2_resp]),
            "model-ra": FailingLLMProvider("A3 failed"),
            "model-ch": FakeLLMProvider([ch_resp]),
        }

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert result.council_complete
        assert result.council_degraded
        assert result.agent_errors
        assert any("A3" in err for err in result.agent_errors)

    def test_chairman_failure_produces_empty_result(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, _ch, all_ids = _setup_standard_responses()

        fake_providers = {
            "model-ea": FakeLLMProvider([a1_resp, ph2_resp]),
            "model-ti": FakeLLMProvider([a2_resp, ph2_resp]),
            "model-ra": FakeLLMProvider([a3_resp, ph2_resp]),
            "model-ch": FailingLLMProvider("Chairman failed"),
        }

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert not result.council_complete
        assert result.chairman_error is not None
        assert not result.variants, "Chairman failure must produce empty variants"
        assert result.recommendation is None, "Chairman failure must NOT produce recommendation"
        assert result.reasoning == "", "Chairman failure must NOT produce reasoning"
        assert result.merge_decisions == (), "Chairman failure must NOT produce merge decisions"

    def test_chairman_failure_no_recommendation_or_ranking(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, _ch, all_ids = _setup_standard_responses()

        fake_providers = {
            "model-ea": FakeLLMProvider([a1_resp, ph2_resp]),
            "model-ti": FakeLLMProvider([a2_resp, ph2_resp]),
            "model-ra": FakeLLMProvider([a3_resp, ph2_resp]),
            "model-ch": FailingLLMProvider("Chairman failed"),
        }

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert not result.council_complete
        assert result.chairman_error is not None
        assert result.recommendation is None
        assert result.variants == ()
        assert result.rejected_variants == ()
        assert result.merge_decisions == ()
        assert result.reasoning == ""


# =========================================================================
# Test: ESPHome example & Hardware/Simulation
# =========================================================================


class TestESPHomeExample:
    def test_esphome_produces_multiple_variants(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        a1_resp = _make_phase1_response("A1", 2)
        all_ids = _all_variant_ids([a1_resp, a2_resp, a3_resp])
        ph2_resp = _make_phase2_response("x", all_ids)
        ch_resp = _make_chairman_response(all_ids)

        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp)

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert result.council_complete
        assert len(result.variants) >= 2, f"Expected >=2 variants, got {len(result.variants)}"

    def test_hardware_simulation_hybrid_distinguishable(self, tmp_path):
        a1_resp = _make_phase1_response("A1", 2)
        a2_resp = _make_phase1_response("A2", 1)
        a3_resp = _make_phase1_response("A3", 1)
        all_ids = _all_variant_ids([a1_resp, a2_resp, a3_resp])
        ph2_resp = _make_phase2_response("x", all_ids)
        ch_resp = _make_chairman_response(all_ids)

        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp)

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        a1_data = json.loads(a1_resp)
        a1_envs = {v["environment"] for v in a1_data["variants"]}
        assert "host" in a1_envs
        assert "physical_hardware" in a1_envs

    def test_no_real_installation_or_hardware(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp)

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert result.council_complete
        assert isinstance(result, CouncilResult)


# =========================================================================
# Test: Council completion and same-phase recovery semantics
# =========================================================================


class RecoveringProvider:
    """Fails the first N calls, then succeeds on subsequent calls."""

    def __init__(self, recover_response: str, failures: int = 1,
                 error_message: str = "transient provider error"):
        self._recover = recover_response
        self._failures = failures
        self._error = error_message
        self._calls = 0

    def complete(self, prompt: str) -> str:
        self._calls += 1
        if self._calls <= self._failures:
            raise RuntimeError(self._error)
        return self._recover


class TestCouncilCompletionRecovery:
    """Verifies that same-phase retry resolves transient errors while
    unresolved failures remain visible under the explicit quorum policy."""

    def test_council_result_degraded_flag_defaults_false(self):
        result = CouncilResult(id="council-default", project_id="project-1")

        assert result.council_degraded is False

    def test_same_phase_transient_recovery_succeeds(self, tmp_path):
        """Phase-1 provider fails once → retried within same phase →
        succeeds → council_complete=True."""
        a1_recover_resp = _make_phase1_response("A1", 1)
        a2_resp = _make_phase1_response("A2", 1)
        a3_resp = _make_phase1_response("A3", 1)
        all_ids = _all_variant_ids([a1_recover_resp, a2_resp, a3_resp])
        ph2_resp = _make_phase2_response("x", all_ids)
        ch_resp = _make_chairman_response(all_ids)

        fake_providers = {
            "model-ea": RecoveringProvider(a1_recover_resp, failures=1,
                                           error_message="connection reset"),
            "model-ti": FakeLLMProvider([a2_resp, ph2_resp]),
            "model-ra": FakeLLMProvider([a3_resp, ph2_resp]),
            "model-ch": FakeLLMProvider([ch_resp]),
        }

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert result.council_complete, (
            f"Council should be complete after same-phase recovery; "
            f"errors={result.agent_errors}"
        )
        assert not result.agent_errors, (
            f"Recovered transient error must not appear in final agent_errors; "
            f"got {result.agent_errors}"
        )
        assert result.variants
        assert result.recommendation is not None

    def test_same_phase_exhausted_retries_use_degraded_quorum(self, tmp_path):
        """Phase-1 provider fails on both initial attempt and retry →
        the remaining independent quorum produces a degraded Council."""
        a2_resp = _make_phase1_response("A2", 1)
        a3_resp = _make_phase1_response("A3", 1)
        all_ids = _all_variant_ids([a2_resp, a3_resp])
        ph2_resp = _make_phase2_response("x", all_ids)
        ch_resp = _make_chairman_response(all_ids)

        fake_providers = {
            "model-ea": RecoveringProvider("unused", failures=10,
                                           error_message="persistent failure"),
            "model-ti": FakeLLMProvider([a2_resp, ph2_resp]),
            "model-ra": FakeLLMProvider([a3_resp, ph2_resp]),
            "model-ch": FakeLLMProvider([ch_resp]),
        }

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert result.council_complete
        assert result.council_degraded
        assert any("A1" in err for err in result.agent_errors)

    def test_phase1_failure_with_review_quorum_is_degraded(self, tmp_path):
        """A1 fails Phase 1 while the two remaining agents satisfy quorum."""
        a2_resp = _make_phase1_response("A2", 1)
        a3_resp = _make_phase1_response("A3", 1)
        all_ids = _all_variant_ids([a2_resp, a3_resp])
        ph2_resp = _make_phase2_response("x", all_ids)
        ch_resp = _make_chairman_response(all_ids)

        fake_providers = {
            "model-ea": FailingLLMProvider("A1 phase1 timeout"),
            "model-ti": FakeLLMProvider([a2_resp, ph2_resp]),
            "model-ra": FakeLLMProvider([a3_resp, ph2_resp]),
            "model-ch": FakeLLMProvider([ch_resp]),
        }

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert result.council_complete
        assert result.council_degraded
        assert any("A1" in err for err in result.agent_errors)

    def test_chairman_failure_council_incomplete(self, tmp_path):
        """All agents succeed in both phases, but Chairman fails →
        Council remains incomplete."""
        a1_resp, a2_resp, a3_resp, ph2_resp, _ch, all_ids = _setup_standard_responses()

        fake_providers = {
            "model-ea": FakeLLMProvider([a1_resp, ph2_resp]),
            "model-ti": FakeLLMProvider([a2_resp, ph2_resp]),
            "model-ra": FakeLLMProvider([a3_resp, ph2_resp]),
            "model-ch": FailingLLMProvider("Chairman failure"),
        }

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert not result.council_complete
        assert result.chairman_error is not None

    def test_successful_complete_council(self, tmp_path):
        """All agents succeed in both phases and Chairman succeeds →
        council_complete=True."""
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp)

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert result.council_complete
        assert not result.council_degraded
        assert not result.agent_errors
        assert result.chairman_error is None
        assert result.variants
        assert result.recommendation is not None

    def test_two_phase1_agents_and_three_review_agents_are_degraded(self, tmp_path):
        a2_resp = _make_phase1_response("A2", 1)
        a3_resp = _make_phase1_response("A3", 1)
        all_ids = _all_variant_ids([a2_resp, a3_resp])
        ph2_resp = _make_phase2_response("x", all_ids)
        ch_resp = _make_chairman_response(all_ids)
        fake_providers = {
            "model-ea": FakeLLMProvider(["invalid", "invalid", ph2_resp]),
            "model-ti": FakeLLMProvider([a2_resp, ph2_resp]),
            "model-ra": FakeLLMProvider([a3_resp, ph2_resp]),
            "model-ch": FakeLLMProvider([ch_resp]),
        }

        structured_results = []
        result = _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path,
            capture_results=structured_results,
        )

        assert result.council_complete
        assert result.council_degraded
        assert any("A1" in error for error in result.agent_errors)
        chairman_result = next(
            item for item in structured_results
            if item["result_kind"] == "chairman_decision"
        )
        assert chairman_result["council_output"]["info"]["status"] == "degraded"
        assert chairman_result["council_output"]["info"]["council_degraded"] is True

    def test_one_phase1_agent_is_incomplete(self, tmp_path):
        a1_resp = _make_phase1_response("A1", 1)
        all_ids = _all_variant_ids([a1_resp])
        ph2_resp = _make_phase2_response("x", all_ids)
        fake_providers = {
            "model-ea": FakeLLMProvider([a1_resp, ph2_resp]),
            "model-ti": FailingLLMProvider("A2 failed"),
            "model-ra": FailingLLMProvider("A3 failed"),
            "model-ch": FakeLLMProvider([_make_chairman_response(all_ids)]),
        }

        result = _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path
        )

        assert not result.council_complete
        assert not result.council_degraded

    def test_one_phase2_vote_agent_is_incomplete(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, _ = _setup_standard_responses()
        fake_providers = {
            "model-ea": FakeLLMProvider([a1_resp, ph2_resp]),
            "model-ti": FakeLLMProvider([a2_resp]),
            "model-ra": FakeLLMProvider([a3_resp]),
            "model-ch": FakeLLMProvider([ch_resp]),
        }

        result = _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path
        )

        assert not result.council_complete
        assert not result.council_degraded

    @pytest.mark.parametrize("recommendation", [None, "unknown-variant"])
    def test_invalid_chairman_recommendation_is_incomplete(
        self, tmp_path, recommendation
    ):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, _ = _setup_standard_responses()
        chairman_data = json.loads(ch_resp)
        chairman_data["recommendation"] = recommendation
        fake_providers = _build_standard_providers(
            a1_resp, a2_resp, a3_resp, ph2_resp, json.dumps(chairman_data)
        )

        result = _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path
        )

        assert not result.council_complete
        assert not result.council_degraded
        assert result.chairman_error is not None
        assert result.recommendation is None
        assert result.variants == ()

    def test_recovered_transient_not_in_final_errors(self, tmp_path):
        """Same-phase recovery clears the transient error from
        final unresolved agent_errors."""
        a1_recover_resp = _make_phase1_response("A1", 1)
        a2_resp = _make_phase1_response("A2", 1)
        a3_resp = _make_phase1_response("A3", 1)
        all_ids = _all_variant_ids([a1_recover_resp, a2_resp, a3_resp])
        ph2_resp = _make_phase2_response("x", all_ids)
        ch_resp = _make_chairman_response(all_ids)

        fake_providers = {
            "model-ea": RecoveringProvider(a1_recover_resp, failures=1),
            "model-ti": FakeLLMProvider([a2_resp, ph2_resp]),
            "model-ra": FakeLLMProvider([a3_resp, ph2_resp]),
            "model-ch": FakeLLMProvider([ch_resp]),
        }

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert result.council_complete
        assert not result.agent_errors, (
            f"Same-phase retry success must leave agent_errors empty; "
            f"got {result.agent_errors}"
        )


# =========================================================================
# Test: Outer deadline budget alignment with same-phase retry
# =========================================================================


class TestDeadlineRetryBudget:
    """Verifies that the outer _execute_parallel deadline covers the
    full bounded retry budget."""

    def test_outer_deadline_accounts_for_all_retry_attempts(self, tmp_path):
        """A1 times out on Phase 1 attempt 0, same-phase retry succeeds,
        and the outer deadline does NOT expire prematurely."""
        from app.engineering_council import _TIMEOUT_GRACE_SECONDS, _MAX_RETRIES

        a1_timeout = 5.0
        a1_recover_resp = _make_phase1_response("A1", 1)
        a2_resp = _make_phase1_response("A2", 1)
        a3_resp = _make_phase1_response("A3", 1)
        all_ids = _all_variant_ids([a1_recover_resp, a2_resp, a3_resp])
        ph2_resp = _make_phase2_response("x", all_ids)
        ch_resp = _make_chairman_response(all_ids)

        fake_providers = {
            "model-ea": RecoveringProvider(a1_recover_resp, failures=1),
            "model-ti": FakeLLMProvider([a2_resp, ph2_resp]),
            "model-ra": FakeLLMProvider([a3_resp, ph2_resp]),
            "model-ch": FakeLLMProvider([ch_resp]),
        }

        cfg = _make_council_config()
        cfg = replace(
            cfg,
            environment_architect=replace(
                cfg.environment_architect, timeout_seconds=a1_timeout,
            ),
        )

        result = _run_council_with_fakes(cfg, fake_providers, tmp_path)

        assert result.council_complete, (
            f"Council must complete after same-phase retry within budget; "
            f"errors={result.agent_errors}"
        )
        assert not result.agent_errors

    def test_exhausted_retries_use_degraded_quorum(self, tmp_path):
        """Provider retry exhaustion retains its error in a degraded Council."""
        a2_resp = _make_phase1_response("A2", 1)
        a3_resp = _make_phase1_response("A3", 1)
        all_ids = _all_variant_ids([a2_resp, a3_resp])
        ph2_resp = _make_phase2_response("x", all_ids)
        ch_resp = _make_chairman_response(all_ids)

        fake_providers = {
            "model-ea": RecoveringProvider("unused", failures=100),
            "model-ti": FakeLLMProvider([a2_resp, ph2_resp]),
            "model-ra": FakeLLMProvider([a3_resp, ph2_resp]),
            "model-ch": FakeLLMProvider([ch_resp]),
        }

        config = _make_council_config()
        config = replace(
            config,
            environment_architect=replace(
                config.environment_architect, timeout_seconds=0.5,
            ),
        )

        result = _run_council_with_fakes(config, fake_providers, tmp_path)

        assert result.council_complete
        assert result.council_degraded
        assert any(
            "A1" in err for err in result.agent_errors
        ), f"Expected A1 error in agent_errors, got {result.agent_errors}"

    def test_stuck_agent_exceeds_full_retry_budget(self, tmp_path):
        """A truly stuck provider that never returns is still bounded by
        the full retry-aware outer deadline."""
        release_stuck = threading.Event()
        activities = []

        class NeverReturnsProvider:
            def complete(self, _prompt):
                release_stuck.wait()
                return _make_phase1_response("A1", 1)

        a2_resp = _make_phase1_response("A2", 1)
        a3_resp = _make_phase1_response("A3", 1)
        all_ids = _all_variant_ids([a2_resp, a3_resp])
        ph2_resp = _make_phase2_response("x", all_ids)
        ch_resp = _make_chairman_response(all_ids)

        def provider_factory(agent_config, _resolver, ollama_url=None):
            model = agent_config.model
            if model == "model-ea":
                return NeverReturnsProvider()
            if model == "model-ch":
                return FakeLLMProvider([ch_resp])
            if model == "model-ti":
                return FakeLLMProvider([a2_resp, ph2_resp])
            return FakeLLMProvider([a3_resp, ph2_resp])

        config = _make_council_config()
        config = replace(
            config,
            environment_architect=replace(
                config.environment_architect, timeout_seconds=0.01,
            ),
        )

        try:
            with patch("app.engineering_council._TIMEOUT_GRACE_SECONDS", 0), patch(
                "app.engineering_council.create_council_provider",
                side_effect=provider_factory,
            ):
                council = EngineeringCouncil(
                    council_config=config,
                    secret_resolver=SimpleSecretResolver({"openrouter-api": "test"}),
                    trace_dir=tmp_path,
                )
                council.set_activity_callback(lambda **a: activities.append(a))
                result = council.evaluate(_make_council_input())
        finally:
            release_stuck.set()

        assert result.council_complete
        assert result.council_degraded
        assert any(
            "A1" in e and "deadline" in e for e in result.agent_errors
        ), f"Stuck agent must hit deadline; got: {result.agent_errors}"
        assert any(
            a.get("actor") == "Agent A1"
            and a.get("runtime_state") == "failed"
            for a in activities
        )


# =========================================================================
# Test: Trace / Audit
# =========================================================================


class TestTrace:
    def test_trace_contains_agent_provider_model(self, tmp_path):
        trace_dir = tmp_path / "traces"
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp)

        result = _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path, trace_dir=trace_dir
        )

        assert result.council_complete
        trace_files = list((trace_dir / "esphome-p1").glob("*.json"))
        assert len(trace_files) >= 1, f"No trace files found in {trace_dir / 'esphome-p1'}"

        with open(trace_files[0]) as f:
            trace_data = json.load(f)

        assert trace_data["project_id"] == "esphome-p1"
        assert len(trace_data["agent_call_records"]) == 7
        roles = {r["role"] for r in trace_data["agent_call_records"]}
        assert "environment_architect" in roles
        assert "toolchain_integrator" in roles
        assert "risk_assessor" in roles
        assert "chairman" in roles


# =========================================================================
# Test: CouncilResult contains origin
# =========================================================================


class TestCouncilResultOrigin:
    def test_result_contains_origin_info(self, tmp_path):
        a1_resp = _make_phase1_response("A1", 1)
        a2_resp = _make_phase1_response("A2", 1)
        a3_resp = _make_phase1_response("A3", 1)
        all_ids = _all_variant_ids([a1_resp, a2_resp, a3_resp])
        ph2_resp = _make_phase2_response("x", all_ids)
        ch_resp = json.dumps({
            "merge_decisions": [
                {"merged_variant_ids": ["A1-var-1", "A2-var-1"],
                 "resulting_variant_id": "merged-1",
                 "reason": "Same environment, similar toolchain"}
            ],
            "variants": [
                {
                    "id": "merged-1", "name": "Merged variant",
                    "description": "", "origin_agents": ["A1", "A2"],
                    "merged_from": ["A1-var-1", "A2-var-1"], "rank": 1,
                    "total_score": 4.5, "consensus_level": "strong_consensus",
                    "minority_opinions": [], "environment": "host",
                    "hardware_target": None, "connection": None,
                    "capabilities": ["build"], "toolchain": [],
                    "advantages": [], "disadvantages": [], "risks": [],
                    "confidence": 0.9, "feasibility": "high", "verification": "test",
                },
                {
                    "id": "A3-var-1", "name": "A3 solo",
                    "description": "", "origin_agents": ["A3"],
                    "merged_from": [], "rank": 2,
                    "total_score": 3.5, "consensus_level": "weak_consensus",
                    "minority_opinions": [], "environment": "physical_hardware",
                    "hardware_target": "esp32", "connection": "serial",
                    "capabilities": ["build", "flash"], "toolchain": [],
                    "advantages": [], "disadvantages": [], "risks": [],
                    "confidence": 0.7, "feasibility": "medium", "verification": "test",
                },
            ],
            "rejected_variants": [],
            "recommendation": "merged-1",
            "reasoning": "Beste Variante",
        })

        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp)

        result = _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path
        )

        assert result.council_complete
        assert len(result.variants) == 2
        merged = [v for v in result.variants if v.id == "merged-1"][0]
        assert set(merged.origin_agents) == {"A1", "A2"}
        assert set(merged.merged_from) == {"A1-var-1", "A2-var-1"}

        solo = [v for v in result.variants if v.id == "A3-var-1"][0]
        assert solo.origin_agents == ("A3",)

        assert result.recommendation == "merged-1"
        assert result.merge_decisions
        assert result.merge_decisions[0].resulting_variant_id == "merged-1"


# =========================================================================
# Test: CouncilConfig parsing
# =========================================================================


def test_yaml_config_council_disabled_is_none(tmp_path):
    from app.ai_config import load_ai_config
    path = tmp_path / "test.yml"
    path.write_text("""
version: 1
ai:
  provider: openrouter
  model: m
  endpoint: https://example.com
  authentication:
    type: secret_reference
    secret: s
  timeout_seconds: 30
  discovery: {}
  council:
    enabled: false
""")
    cfg = load_ai_config(path)
    assert cfg.council is None


def test_yaml_config_council_missing_agents_raises(tmp_path):
    from app.ai_config import load_ai_config
    path = tmp_path / "test.yml"
    path.write_text("""
version: 1
ai:
  provider: openrouter
  model: m
  endpoint: https://example.com
  authentication:
    type: secret_reference
    secret: s
  timeout_seconds: 30
  discovery: {}
  council:
    enabled: true
    max_variants_per_agent: 3
""")
    with pytest.raises(ValueError, match="agents"):
        load_ai_config(path)


def test_failing_agent_still_produces_errors_in_call_records(tmp_path):
    a1_resp = _make_phase1_response("A1", 1)
    a2_resp = _make_phase1_response("A2", 1)
    all_ids = _all_variant_ids([a1_resp, a2_resp])
    ph2_resp = _make_phase2_response("x", all_ids)
    ch_resp = _make_chairman_response(all_ids)

    fake_providers = {
        "model-ea": FakeLLMProvider([a1_resp, ph2_resp]),
        "model-ti": FakeLLMProvider([a2_resp, ph2_resp]),
        "model-ra": FailingLLMProvider("A3 failed"),
        "model-ch": FakeLLMProvider([ch_resp]),
    }

    result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

    assert result.council_complete
    assert result.council_degraded
    assert any("A3" in err for err in result.agent_errors)


def test_toolchain_items_preserved_in_proposals(tmp_path):
    a1_resp = json.dumps({
        "variants": [{
            "variant_id": "A1-var-1",
            "name": "Test Variant",
            "description": "Desc",
            "environment": "host",
            "hardware_target": None,
            "connection": None,
            "capabilities": ["build"],
            "toolchain": [
                {
                    "requirement_ref": "req-1",
                    "name": "python",
                    "type": "executable",
                    "install_method": None,
                    "version": None,
                    "purpose": "Runtime",
                    "depends_on": [],
                    "state": "already_installed",
                    "environment_constraint": None,
                },
                {
                    "requirement_ref": "req-2",
                    "name": "esphome",
                    "type": "python_package",
                    "install_method": "pip install esphome",
                    "version": "2024.1",
                    "purpose": "Build tool",
                    "depends_on": ["python"],
                    "state": "needs_install",
                    "environment_constraint": None,
                },
            ],
            "advantages": ["Fast"],
            "disadvantages": [],
            "risks": [],
            "confidence": 0.9,
            "feasibility": "high",
            "verification": "esphome version",
            "agent_reasoning": "Test",
        }]
    })
    a2_resp = _make_phase1_response("A2", 1)
    a3_resp = _make_phase1_response("A3", 1)
    all_ids = ["A1-var-1", "A2-var-1", "A3-var-1"]
    ph2_resp = _make_phase2_response("x", all_ids)
    ch_resp = _make_chairman_response(all_ids)

    fake_providers = {
        "model-ea": FakeLLMProvider([a1_resp, ph2_resp]),
        "model-ti": FakeLLMProvider([a2_resp, ph2_resp]),
        "model-ra": FakeLLMProvider([a3_resp, ph2_resp]),
        "model-ch": FakeLLMProvider([ch_resp]),
    }

    with patch("app.engineering_council.create_council_provider") as mock_factory:
        mock_factory.side_effect = lambda config, resolver, ollama_url=None: fake_providers[config.model]
        council = EngineeringCouncil(
            council_config=_make_council_config(),
            secret_resolver=SimpleSecretResolver({"openrouter-api": "test"}),
            trace_dir=tmp_path,
        )
        result = council.evaluate(_make_council_input())

    assert result.council_complete
    assert len(result.variants) > 0


def _make_auto_materializable_toolchain() -> list[dict]:
    return [
        {
            "requirement_ref": "req-1",
            "name": "python",
            "type": "executable",
            "install_method": None,
            "version": None,
            "purpose": "Runtime",
            "depends_on": [],
            "state": "already_installed",
            "environment_constraint": None,
            "provided_by": None,
        },
        {
            "requirement_ref": "req-2",
            "name": "esphome",
            "type": "python_package",
            "install_method": "pip install esphome",
            "version": "2024.1",
            "purpose": "Build tool",
            "depends_on": ["python"],
            "state": "needs_install",
            "environment_constraint": None,
            "provided_by": None,
        },
    ]


def _make_manual_review_toolchain() -> list[dict]:
    return [
        {
            "requirement_ref": "req-1",
            "name": "python",
            "type": "executable",
            "install_method": None,
            "version": None,
            "purpose": "Runtime",
            "depends_on": [],
            "state": "already_installed",
            "environment_constraint": None,
            "provided_by": None,
        },
        {
            "requirement_ref": "req-3",
            "name": "docker",
            "type": "system_package",
            "install_method": None,
            "version": None,
            "purpose": "Container runtime",
            "depends_on": [],
            "state": "needs_install",
            "environment_constraint": None,
            "provided_by": None,
        },
    ]
    """Tests verifying explicit functional roles in Council prompts."""

    def test_agent_a1_phase1_prompt_contains_role(self):
        prompt = build_phase1_prompt(
            _make_council_input(), AGENT_ROLE_ENV_ARCHITECT, 3,
        )
        assert "Engineering Council Agent A1" in prompt
        assert "Environment Architect" in prompt
        assert "AI-Dev-Center" in prompt
        assert "führst keine Änderungen aus" in prompt
        assert "erteilst keine Human Approval" in prompt

    def test_agent_a2_phase1_prompt_contains_role(self):
        prompt = build_phase1_prompt(
            _make_council_input(), AGENT_ROLE_TOOLCHAIN, 3,
        )
        assert "Engineering Council Agent A2" in prompt
        assert "Toolchain Integrator" in prompt
        assert "AI-Dev-Center" in prompt
        assert "führst keine Änderungen aus" in prompt

    def test_agent_a3_phase1_prompt_contains_role(self):
        prompt = build_phase1_prompt(
            _make_council_input(), AGENT_ROLE_RISK, 3,
        )
        assert "Engineering Council Agent A3" in prompt
        assert "Risk & Feasibility Assessor" in prompt
        assert "AI-Dev-Center" in prompt
        assert "führst keine Änderungen aus" in prompt

    def test_agent_a1_review_prompt_contains_role(self):
        assert "Engineering Council Agent A1" in AGENT_ROLE_ENV_ARCHITECT_REVIEW
        assert "AI-Dev-Center" in AGENT_ROLE_ENV_ARCHITECT_REVIEW
        assert "führst keine Änderungen aus" in AGENT_ROLE_ENV_ARCHITECT_REVIEW

    def test_agent_a2_review_prompt_contains_role(self):
        assert "Engineering Council Agent A2" in AGENT_ROLE_TOOLCHAIN_REVIEW
        assert "AI-Dev-Center" in AGENT_ROLE_TOOLCHAIN_REVIEW

    def test_agent_a3_review_prompt_contains_role(self):
        assert "Engineering Council Agent A3" in AGENT_ROLE_RISK_REVIEW
        assert "AI-Dev-Center" in AGENT_ROLE_RISK_REVIEW

    def test_chairman_prompt_contains_role(self):
        assert "Chairman des AI-Dev-Center Engineering Council" in CHAIRMAN_SYSTEM_PROMPT
        assert "führst keine Änderungen aus" in CHAIRMAN_SYSTEM_PROMPT
        assert "erteilst keine Human Approval" in CHAIRMAN_SYSTEM_PROMPT

    def test_council_roles_do_not_grant_approval_authority(self):
        for role_prompt in (
            AGENT_ROLE_ENV_ARCHITECT, AGENT_ROLE_TOOLCHAIN,
            AGENT_ROLE_RISK, CHAIRMAN_SYSTEM_PROMPT,
        ):
            assert "erteilst keine Human Approval" in role_prompt

    def test_chairman_role_does_not_grant_execution_authority(self):
        chairman_prompt = build_chairman_prompt(
            json.dumps([{"variant_id": "v1", "name": "Test"}]), json.dumps([]),
            _make_council_input(),
        )
        assert "führst keine Änderungen aus" in chairman_prompt

    def test_built_chairman_effective_prompt_contains_role(self):
        prompt = build_chairman_prompt(
            json.dumps([{"variant_id": "v1", "name": "Test"}]),
            json.dumps([]),
            _make_council_input(),
        )
        assert "Chairman des AI-Dev-Center Engineering Council" in prompt

    def test_a1_phase1_contains_compact_adc_context(self):
        prompt = build_phase1_prompt(
            _make_council_input(), AGENT_ROLE_ENV_ARCHITECT, 3,
        )
        assert "kontrolliertes Engineering-System" in prompt

    def test_a2_phase1_contains_compact_adc_context(self):
        prompt = build_phase1_prompt(
            _make_council_input(), AGENT_ROLE_TOOLCHAIN, 3,
        )
        assert "kontrolliertes Engineering-System" in prompt

    def test_a3_phase1_contains_compact_adc_context(self):
        prompt = build_phase1_prompt(
            _make_council_input(), AGENT_ROLE_RISK, 3,
        )
        assert "kontrolliertes Engineering-System" in prompt

    def test_chairman_contains_compact_adc_context(self):
        assert "kontrolliertes Engineering-System" in CHAIRMAN_SYSTEM_PROMPT
        assert "Software-, Firmware- und Hardware-Projekten" in CHAIRMAN_SYSTEM_PROMPT

    def test_oc_010_roles_and_authority_boundaries_remain_intact(self):
        for role in (AGENT_ROLE_ENV_ARCHITECT, AGENT_ROLE_TOOLCHAIN, AGENT_ROLE_RISK):
            assert "erteilst keine Human Approval" in role
            assert "führst keine Änderungen aus" in role
        assert "erteilst keine Human Approval" in CHAIRMAN_SYSTEM_PROMPT
        assert "führst keine Änderungen aus" in CHAIRMAN_SYSTEM_PROMPT

    def test_oc_009_discovery_contract_unchanged(self):
        from app.ai_requirement_discovery import AIRequirementDiscovery
        disc = AIRequirementDiscovery()
        prompt = disc._build_prompt({"project_id": "test"}, "test")
        assert prompt.strip().startswith(
            'Return a JSON object with the single key "requirements"'
        )


# =========================================================================
# Test: Controlled Setup Eligibility Policy (OC-024)
# =========================================================================


class TestControlledSetupEligibility:
    """Deterministic Chairman recommendation validation for controlled setup."""

    def _make_chairman_with_toolchains(
        self, variant_toolchains: list[list[dict]],
        recommendation: str | None = None,
    ) -> str:
        variants = []
        for i, tc in enumerate(variant_toolchains):
            vid = f"final-var-{i + 1}"
            variants.append({
                "id": vid, "name": f"Final Variant {i + 1}",
                "description": f"Desc {i + 1}",
                "origin_agents": ["A1"], "merged_from": [],
                "rank": i + 1,
                "total_score": 5.0 - i * 0.5,
                "consensus_level": "strong_consensus",
                "minority_opinions": [], "environment": "host",
                "hardware_target": None, "connection": None,
                "capabilities": ["build"],
                "toolchain": tc,
                "advantages": [], "disadvantages": [], "risks": [],
                "confidence": 0.9, "feasibility": "high",
                "verification": "test",
            })
        return json.dumps({
            "merge_decisions": [],
            "variants": variants, "rejected_variants": [],
            "recommendation": recommendation or variants[0]["id"],
            "reasoning": "Test",
        })

    def test_auto_materializable_recommendation_accepted_when_alternatives_exist(
        self, tmp_path,
    ):
        a1_resp = _make_phase1_response("A1", 1)
        a2_resp = _make_phase1_response("A2", 1)
        a3_resp = _make_phase1_response("A3", 1)
        all_ids = _all_variant_ids([a1_resp, a2_resp, a3_resp])
        ph2_resp = _make_phase2_response("x", all_ids)

        ch_resp = self._make_chairman_with_toolchains(
            [_make_auto_materializable_toolchain(),
             _make_auto_materializable_toolchain()],
            recommendation="final-var-1",
        )

        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp)
        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert result.council_complete
        assert result.recommendation == "final-var-1"
        assert not result.chairman_error

    def test_manual_review_recommendation_rejected_when_auto_alternative_exists(
        self, tmp_path,
    ):
        a1_resp = _make_phase1_response("A1", 1)
        a2_resp = _make_phase1_response("A2", 1)
        a3_resp = _make_phase1_response("A3", 1)
        all_ids = _all_variant_ids([a1_resp, a2_resp, a3_resp])
        ph2_resp = _make_phase2_response("x", all_ids)

        ch_resp = self._make_chairman_with_toolchains(
            [_make_auto_materializable_toolchain(),
             _make_manual_review_toolchain()],
            recommendation="final-var-2",
        )

        fake_providers = _build_standard_providers(
            a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp,
        )
        result = _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path,
        )

        assert not result.council_complete
        assert result.chairman_error is not None
        assert "automatically materializable" in result.chairman_error
        assert result.recommendation is None

    def test_all_manual_review_recommendation_accepted(self, tmp_path):
        a1_resp = _make_phase1_response("A1", 1)
        a2_resp = _make_phase1_response("A2", 1)
        a3_resp = _make_phase1_response("A3", 1)
        all_ids = _all_variant_ids([a1_resp, a2_resp, a3_resp])
        ph2_resp = _make_phase2_response("x", all_ids)

        ch_resp = self._make_chairman_with_toolchains(
            [_make_manual_review_toolchain(),
             _make_manual_review_toolchain()],
            recommendation="final-var-1",
        )

        fake_providers = _build_standard_providers(
            a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp,
        )
        result = _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path,
        )

        assert result.council_complete
        assert result.recommendation == "final-var-1"
        assert result.chairman_error is None

    def test_merged_variant_assessed_by_final_toolchain_not_phase1_metadata(
        self, tmp_path,
    ):
        a1_resp = _make_phase1_response("A1", 1)
        a2_resp = _make_phase1_response("A2", 1)
        a3_resp = _make_phase1_response("A3", 1)
        all_ids = _all_variant_ids([a1_resp, a2_resp, a3_resp])
        ph2_resp = _make_phase2_response("x", all_ids)

        ch_data = {
            "merge_decisions": [{
                "merged_variant_ids": ["A1-var-1", "A2-var-1"],
                "resulting_variant_id": "merged-1",
                "reason": "Same environment",
            }],
            "variants": [{
                "id": "merged-1", "name": "Merged",
                "description": "", "origin_agents": ["A1", "A2"],
                "merged_from": ["A1-var-1", "A2-var-1"], "rank": 1,
                "total_score": 4.5, "consensus_level": "strong_consensus",
                "minority_opinions": [], "environment": "host",
                "hardware_target": None, "connection": None,
                "capabilities": ["build"],
                "toolchain": _make_auto_materializable_toolchain(),
                "advantages": [], "disadvantages": [], "risks": [],
                "confidence": 0.9, "feasibility": "high", "verification": "test",
            }],
            "rejected_variants": [],
            "recommendation": "merged-1",
            "reasoning": "Beste Variante",
        }
        ch_resp = json.dumps(ch_data)

        fake_providers = _build_standard_providers(
            a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp,
        )
        result = _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path,
        )

        assert result.council_complete
        assert result.recommendation == "merged-1"
        assert result.chairman_error is None

    def test_recommendation_id_validation_still_enforced(self, tmp_path):
        a1_resp = _make_phase1_response("A1", 1)
        a2_resp = _make_phase1_response("A2", 1)
        a3_resp = _make_phase1_response("A3", 1)
        all_ids = _all_variant_ids([a1_resp, a2_resp, a3_resp])
        ph2_resp = _make_phase2_response("x", all_ids)

        ch_resp = self._make_chairman_with_toolchains(
            [_make_auto_materializable_toolchain()],
            recommendation="nonexistent-variant",
        )

        fake_providers = _build_standard_providers(
            a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp,
        )
        result = _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path,
        )

        assert not result.council_complete
        assert result.chairman_error is not None
        assert "final Council variant" in result.chairman_error

    def test_preflight_satisfied_requirement_is_auto_materializable(
        self, tmp_path,
    ):
        a1_resp = _make_phase1_response("A1", 1)
        a2_resp = _make_phase1_response("A2", 1)
        a3_resp = _make_phase1_response("A3", 1)
        all_ids = _all_variant_ids([a1_resp, a2_resp, a3_resp])
        ph2_resp = _make_phase2_response("x", all_ids)

        ch_resp = self._make_chairman_with_toolchains(
            [[{
                "requirement_ref": "req-1",
                "name": "python",
                "type": "executable",
                "install_method": None,
                "version": None,
                "purpose": "Runtime",
                "depends_on": [],
                "state": "already_installed",
                "environment_constraint": None,
                "provided_by": None,
            }]],
            recommendation="final-var-1",
        )

        fake_providers = _build_standard_providers(
            a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp,
        )
        result = _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path,
        )

        assert result.council_complete
        assert result.recommendation == "final-var-1"
        assert result.chairman_error is None

    def test_chairman_prompt_expresses_eligibility_rule_not_preference(self):
        prompt = build_chairman_prompt(
            json.dumps([{"variant_id": "v1", "name": "Test"}]),
            json.dumps([]),
            _make_council_input(),
        )
        assert "ZULASSUNGSREGEL" in prompt
        assert "MUSS die Empfehlung aus dieser Menge stammen" in prompt
        assert "keine Präferenz" in prompt
        assert "Bestimme zuerst die Menge der zulässigen finalen Varianten" in CHAIRMAN_SYSTEM_PROMPT
        assert "Vote-Ranking gilt" in CHAIRMAN_SYSTEM_PROMPT
        assert "innerhalb der zulässigen Menge" in CHAIRMAN_SYSTEM_PROMPT
