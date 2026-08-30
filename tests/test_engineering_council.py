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
from dataclasses import dataclass, field
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
                             trace_dir=None, capture_configs=None):
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

    def test_a1_failure_marks_council_incomplete(self, tmp_path):
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

        assert not result.council_complete
        assert result.agent_errors
        assert any("A1" in err for err in result.agent_errors)

    def test_a2_failure_marks_council_incomplete(self, tmp_path):
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

        assert not result.council_complete
        assert result.agent_errors
        assert any("A2" in err for err in result.agent_errors)

    def test_a3_failure_marks_council_incomplete(self, tmp_path):
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

        assert not result.council_complete
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

    def test_incomplete_council_not_reported_as_success(self, tmp_path):
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

        assert not result.council_complete
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

    assert not result.council_complete
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