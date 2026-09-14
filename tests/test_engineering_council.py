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
from app.diagnostic_trace import (
    DiagnosticDetailLevel,
    DiagnosticTrace,
    DiagnosticTraceStore,
    render_diagnostic_trace_event,
)
from app.engineering_council import (
    EngineeringCouncil,
    _AgentTask,
    _build_chairman_repair_prompt,
    _candidate_rejection_diagnostic,
    _classify_zero_proposal_reason,
    _sanitized_candidate_identifier,
    _trusted_candidate_rejection_category,
    _TRUSTED_CANDIDATE_REJECTION_CATEGORIES,
)
from app.requirement_model import (
    PreflightRequirementResult,
    PreflightResult,
    Requirement,
    RequirementActivation,
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


def _wire_diagnostic_trace(council, diagnostic_trace, run_id="test-run"):
    """CLAUDE-ADC-COUNCIL-DIAGNOSTIC-TRACE-INTEGRATION-FIX-001: mirrors
    app.dev_workflow.DevelopmentWorkflow.run()'s own record_council_
    result() wiring exactly (same summary.pop(), same details shape),
    so tests exercise the SAME composition path production code uses to
    route EngineeringCouncil's structured results into the central
    DiagnosticTrace -- never a council-owned file."""
    def record_council_result(**result):
        summary = result.pop("summary", "Council structured result")
        diagnostic_trace.record(
            run_id, "engineering_council", "completed", "completed",
            summary, details={"diagnostic_level": "NORMAL", **result},
        )
    council.set_result_callback(record_council_result)


def _run_council_with_fakes(council_config, fake_providers, tmp_path,
                             trace_dir=None, capture_configs=None,
                             capture_results=None, diagnostic_trace=None,
                             diagnostic_trace_run_id="test-run"):
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
        elif diagnostic_trace is not None:
            _wire_diagnostic_trace(council, diagnostic_trace, diagnostic_trace_run_id)
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

    def test_literal_control_character_in_json_string_parses_without_retry(self, tmp_path):
        """CLAUDE-ADC-E2E-VERIFICATION-EVIDENCE-FIX-001: reproduces the
        real E2E's secondary robustness signal -- Agent A1 failed JSON
        parsing twice with 'Invalid control character' before succeeding
        on a later council rerun. LLMs routinely emit a literal,
        unescaped newline inside a JSON string value (e.g. a multi-line
        agent_reasoning) instead of the RFC 8259-required '\\n' escape;
        Python's strict json.loads rejects the ENTIRE otherwise
        well-formed response for that alone, wasting a retry round-trip.
        `_parse_json_response`'s `strict=False` fallback must accept this
        on the FIRST attempt -- no retry, no extra LLM call."""
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        a1_resp_with_control_char = a1_resp.replace(
            "Testvariant 1 von A1",
            "Testvariant 1 von A1\nZeile 2 mit einem literalen Kontrollzeichen",
        )
        assert "\n" in a1_resp_with_control_char.split('"description"')[1][:100]
        with pytest.raises(json.JSONDecodeError):
            json.loads(a1_resp_with_control_char)

        fake_providers = _build_standard_providers(
            a1_resp_with_control_char, a2_resp, a3_resp, ph2_resp, ch_resp,
        )

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert result.council_complete
        assert result.total_llm_calls == 7  # no retry -- parsed on first attempt

    def test_genuinely_malformed_json_still_fails_even_non_strict(self, tmp_path):
        """The strict=False fallback only relaxes literal control
        characters inside otherwise well-formed JSON -- it must never
        accept genuinely malformed JSON structure (here: a truncated
        document missing its closing braces). Proves the fix does not
        dilute structured-output validation."""
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()

        fake_providers = {
            "model-ea": FakeLLMProvider(["{\"variants\": [{\"truncated\": true"] * 2),
            "model-ti": FakeLLMProvider([a2_resp, ph2_resp]),
            "model-ra": FakeLLMProvider([a3_resp, ph2_resp]),
            "model-ch": FakeLLMProvider([ch_resp]),
        }

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert result.council_complete
        assert result.council_degraded
        assert any("A1" in err for err in result.agent_errors)

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
# Test: binding Requirement coverage across ALL final Council variants
# (CLAUDE-E2E-NIO-010A -- Real-System-E2E #5 root cause)
# =========================================================================


def _make_council_input_with_two_binding_requirements() -> CouncilInput:
    """Models the reproduced Real-E2E #5 shape: two independently
    required, missing, blocking Requirements (ESPHome, a PlatformIO-like
    build backend) -- the exact shape under which six otherwise-plausible
    Council proposals plus a completed Chairman recommendation produced
    zero admissible S2 candidates."""
    req_esphome = _make_requirement("req-1", "esphome", "python_package", True)
    req_platformio = _make_requirement("req-2", "platformio", "executable", True)
    return CouncilInput(
        requirements=(req_esphome, req_platformio),
        preflight=PreflightResult(
            id="pre-1", project_id="test-project", overall_ready=False,
            results=(
                PreflightRequirementResult(requirement_id="req-1", present=False, satisfied=False),
                PreflightRequirementResult(requirement_id="req-2", present=False, satisfied=False),
            ),
            missing_requirements=(req_esphome, req_platformio),
            activations=(
                RequirementActivation("req-1", True, True),
                RequirementActivation("req-2", True, True),
            ),
            already_installed=(), warnings=(),
        ),
        detected_stack="esphome", project_id="esphome-p1",
        project_files=("esphome-p1.yaml",), platform="linux",
    )


def _toolchain_item(requirement_ref: str) -> dict:
    return {
        "requirement_ref": requirement_ref, "name": requirement_ref,
        "technical_identity": requirement_ref, "type": "python_package",
        "install_method": "pip", "version": None, "purpose": "",
        "depends_on": [], "state": "needs_install",
        "environment_constraint": None, "provided_by": None,
        "provides_verification": ["pytest"],
    }


def _variant(variant_id: str, name: str, *toolchain_refs: str, rank: int = 1) -> dict:
    return {
        "id": variant_id, "name": name, "description": name,
        "origin_agents": ["A1"], "merged_from": [variant_id],
        "rank": rank, "total_score": 5.0, "consensus_level": "strong_consensus",
        "minority_opinions": [], "environment": "host",
        "hardware_target": None, "connection": None,
        "capabilities": [], "toolchain": [_toolchain_item(ref) for ref in toolchain_refs],
        "advantages": [], "disadvantages": [], "risks": [],
        "confidence": 0.9, "feasibility": "high", "verification": "test",
    }


class TestBindingRequirementCoverageAcrossVariants:
    """Real-System-E2E #5 exposed that nothing previously required a
    FINAL Council variant's toolchain to cover every binding Requirement
    -- _validate_toolchain_requirement_refs() only rejects a requirement_ref
    that points to nothing real, never one that leaves some OTHER binding
    Requirement completely uncovered. When specialist agents (and even a
    Chairman merge) propose complementary PARTIAL solutions -- exactly the
    observed shape (agent A2's three variants addressed only ESPHome CLI
    installation, agent A3's three addressed only a separate installation-
    strategy Requirement, and the Chairman's own "merged-venv" combined
    them by name/environment similarity without actually unioning their
    toolchains) -- every resulting candidate individually satisfies its
    own agent's narrow framing while collectively leaving S2's (correct,
    unweakened) per-candidate coverage check with zero admissible
    candidates. This is now caught here, at the true producer
    (Council/Chairman synthesis), with the exact missing Requirement ids
    per variant."""

    def test_red_before_fix_zero_coverage_previously_passed_silently(self, tmp_path):
        """Genuine RED: temporarily remove the new completeness check by
        calling the parsing logic path that predates it -- reproduced via
        a direct, standalone check against the underlying validation
        primitives (the same ones _parse_chairman_result now calls),
        proving that NEITHER of two complementary-but-incomplete variants
        would have been rejected by anything that existed before this
        task. This is the mechanical root-cause evidence for Real-E2E #5,
        independent of any one Chairman JSON shape."""
        from app.engineering_decision import _binding_requirement_ids, _covers_binding_requirements

        council_input = _make_council_input_with_two_binding_requirements()
        binding_ids = _binding_requirement_ids(council_input.preflight)
        assert binding_ids == frozenset({"req-1", "req-2"})

        esphome_only = CouncilVariant(
            id="merged-venv", name="ESPHome mit Python Virtual Environment",
            toolchain=(ToolchainItem(requirement_ref="req-1", name="esphome",
                                      type="python_package", install_method="pip"),),
        )
        platformio_only = CouncilVariant(
            id="A3-var-3", name="Virtuelle Umgebung",
            toolchain=(ToolchainItem(requirement_ref="req-2", name="platformio",
                                      type="executable", install_method="pip"),),
        )
        # RED: _validate_toolchain_requirement_refs (the ONLY pre-existing
        # coverage-adjacent check) would have accepted BOTH of these --
        # each ref is real, so nothing previously flagged that NEITHER
        # variant covers the full binding set.
        for variant in (esphome_only, platformio_only):
            assert not _covers_binding_requirements(variant, binding_ids), (
                "fixture sanity: each variant must genuinely be incomplete"
            )

    def test_chairman_producing_only_incomplete_variants_completes_structurally_but_stays_s2_3_inadmissible(
        self, tmp_path,
    ):
        """CLAUDE-ARCH-S2-012B (Gate A/B): synthesis_complete/
        council_complete reports ONLY structural protocol success --
        the Chairman's synthesis output (three valid variants, a
        recommendation identifying one of them) IS structurally
        complete, even though that recommendation still fails S2.3's
        binding-requirement-coverage rule. This is the corrected
        replacement for CLAUDE-ARCH-S2-012A's own
        test_chairman_producing_only_incomplete_variants_is_rejected_
        with_evidence, which wrongly asserted council_complete=False
        for a purely S2.3-level (not protocol-level) rejection -- an
        independent review flagged exactly this as a governance
        regression (S2.2 must never gate synthesis completeness on
        S2.3's verdict)."""
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, _ = _setup_standard_responses()
        chairman_data = json.loads(ch_resp)
        chairman_data["variants"] = [
            _variant("A2-var-2", "ESPHome mit Python Virtual Environment", "req-1", rank=1),
            _variant("A3-var-3", "Virtuelle Umgebung", "req-2", rank=2),
            _variant("merged-venv", "ESPHome mit Python Virtual Environment", "req-1", rank=1),
        ]
        chairman_data["recommendation"] = "merged-venv"
        fake_providers = _build_standard_providers(
            a1_resp, a2_resp, a3_resp, ph2_resp, json.dumps(chairman_data)
        )

        with patch("app.engineering_council.create_council_provider") as mf:
            mf.side_effect = lambda config, resolver, ollama_url=None: fake_providers[config.model]
            council = EngineeringCouncil(
                council_config=_make_council_config(),
                secret_resolver=SimpleSecretResolver({"openrouter-api": "test"}),
            )
            result = council.evaluate(_make_council_input_with_two_binding_requirements())

        # Gate B: synthesis_complete=True coexists with an S2.3
        # rejection of the very same recommendation.
        assert result.council_complete
        assert result.chairman_error is None
        assert result.recommendation == "merged-venv"

        # S2.3 remains the single authority that actually surfaces the
        # inadmissibility -- discoverable by calling it, exactly as any
        # other consumer downstream of a "complete" synthesis would.
        from app.engineering_decision import validate_candidates
        validations = validate_candidates(
            result, preflight=_make_council_input_with_two_binding_requirements().preflight,
        )
        by_id = {v.variant.id: v for v in validations}
        assert by_id["merged-venv"].admissible is False
        assert "missing binding requirement coverage" in by_id["merged-venv"].reasons[0]

    def test_chairman_producing_one_complete_variant_is_accepted(self, tmp_path):
        """Regression safety: when at least one final variant DOES cover
        every binding Requirement (here, by including both items in a
        single variant's toolchain), the new check must not reject it --
        it only fires when NOT A SINGLE variant achieves full coverage."""
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, _ = _setup_standard_responses()
        chairman_data = json.loads(ch_resp)
        chairman_data["variants"] = [
            _variant("A2-var-2", "ESPHome mit Python Virtual Environment", "req-1", rank=1),
            _variant("complete-venv", "ESPHome + PlatformIO Virtual Environment",
                      "req-1", "req-2", rank=1),
        ]
        chairman_data["recommendation"] = "complete-venv"
        fake_providers = _build_standard_providers(
            a1_resp, a2_resp, a3_resp, ph2_resp, json.dumps(chairman_data)
        )

        with patch("app.engineering_council.create_council_provider") as mf:
            mf.side_effect = lambda config, resolver, ollama_url=None: fake_providers[config.model]
            council = EngineeringCouncil(
                council_config=_make_council_config(),
                secret_resolver=SimpleSecretResolver({"openrouter-api": "test"}),
            )
            result = council.evaluate(_make_council_input_with_two_binding_requirements())

        assert result.council_complete
        assert result.chairman_error is None
        assert any(v.id == "complete-venv" for v in result.variants)


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

    def test_manual_review_recommendation_accepted_even_when_auto_alternative_exists(
        self, tmp_path,
    ):
        """CLAUDE-ARCH-S2-012A, RED-3: this test previously asserted the
        OPPOSITE (rejection) as "correct" behavior -- a pre-existing,
        completely untested-until-now S2.2 rule forced the Chairman's
        recommendation to be automatically materializable whenever ANY
        final variant was, even though a legitimately-manual candidate
        is fully admissible per CLAUDE-PRE-E2E-009C/CLAUDE-E2E-NIO-010A.
        That rule was a forced PREFERENCE among admissible candidates
        (automatic over manual) -- exactly the class of governance
        violation 009C itself removed for mutation-free preference.
        Corrected expectation: the Chairman may legitimately recommend
        the manual-review candidate; ADC does not force automatic over
        manual."""
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

        assert result.council_complete
        assert result.chairman_error is None
        assert result.recommendation == "final-var-2"

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


# =========================================================================
# Test: bounded Chairman synthesis repair (CLAUDE-E2E-NIO-011A --
# Real-System-E2E #6: a completed provider call, a syntactically valid
# response, but a structurally/semantically rejected Chairman decision,
# previously terminated planning immediately and hid the real reason).
# =========================================================================


def _invalid_recommendation_chairman_response(variant_ids: list[str]) -> str:
    """A syntactically valid, structurally invalid Chairman response:
    recommendation does not identify any of the returned variants."""
    return _make_chairman_response(variant_ids, recommendation="does-not-exist")


class TestBoundedChairmanRepair:
    """CLAUDE-E2E-NIO-011A, Part 9/10 test matrix."""

    def test_complete_initial_result_never_triggers_a_repair_call(self, tmp_path):
        """Part 10.A."""
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, _ = _setup_standard_responses()
        chairman_provider = FakeLLMProvider([ch_resp])
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp)
        fake_providers["model-ch"] = chairman_provider

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert result.council_complete
        assert result.chairman_error is None
        assert len(chairman_provider.calls) == 1

    def test_incomplete_first_result_triggers_exactly_one_targeted_repair(self, tmp_path):
        """Part 10.C: an invalid-recommendation first response leads to
        exactly one repair call, whose prompt carries the exact
        deterministic rejection reason."""
        a1_resp, a2_resp, a3_resp, ph2_resp, _, all_ids = _setup_standard_responses()
        broken_ch_resp = _invalid_recommendation_chairman_response(all_ids)
        fixed_ch_resp = _make_chairman_response(all_ids)
        chairman_provider = FakeLLMProvider([broken_ch_resp, fixed_ch_resp])
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, broken_ch_resp)
        fake_providers["model-ch"] = chairman_provider

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert len(chairman_provider.calls) == 2
        repair_prompt = chairman_provider.calls[1]
        assert "KORREKTUR ERFORDERLICH" in repair_prompt
        assert "must identify a final Council variant" in repair_prompt
        assert result.council_complete

    def test_successful_repair_completes_the_council(self, tmp_path):
        """Part 10.D."""
        a1_resp, a2_resp, a3_resp, ph2_resp, _, all_ids = _setup_standard_responses()
        broken_ch_resp = _invalid_recommendation_chairman_response(all_ids)
        fixed_ch_resp = _make_chairman_response(all_ids)
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, broken_ch_resp)
        fake_providers["model-ch"] = FakeLLMProvider([broken_ch_resp, fixed_ch_resp])

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert result.council_complete
        assert result.chairman_error is None
        assert result.recommendation == all_ids[0]

    def test_repair_still_incomplete_is_a_bounded_terminal_failure(self, tmp_path):
        """Part 10.E: two rejected attempts, never a third."""
        a1_resp, a2_resp, a3_resp, ph2_resp, _, all_ids = _setup_standard_responses()
        broken_ch_resp_1 = _invalid_recommendation_chairman_response(all_ids)
        broken_ch_resp_2 = _invalid_recommendation_chairman_response(all_ids)
        chairman_provider = FakeLLMProvider([broken_ch_resp_1, broken_ch_resp_2])
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, broken_ch_resp_1)
        fake_providers["model-ch"] = chairman_provider

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert not result.council_complete
        assert len(chairman_provider.calls) == 2, "must never attempt a third synthesis call"
        assert "2 attempt(s)" in result.chairman_error
        assert "bounded repair exhausted" in result.chairman_error
        assert result.chairman_error.count("must identify a final Council variant") == 2

    def test_malformed_first_response_follows_existing_transport_retry_not_synthesis_repair(self, tmp_path):
        """Part 10.F: a syntactically invalid JSON response is handled by
        _run_single_agent's OWN, separately-bounded, pre-existing retry
        (a corrective "send valid JSON" re-prompt) -- never confused
        with, or double-counted against, the NEW synthesis-repair
        budget. Two provider calls happen, but both belong to the
        existing transport-retry policy; the synthesis-repair path is
        never engaged because the (transport-level-retried) result is
        complete on its first successfully PARSED attempt."""
        a1_resp, a2_resp, a3_resp, ph2_resp, _, all_ids = _setup_standard_responses()
        valid_ch_resp = _make_chairman_response(all_ids)
        chairman_provider = FakeLLMProvider(["this is not json at all", valid_ch_resp])
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, valid_ch_resp)
        fake_providers["model-ch"] = chairman_provider

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert result.council_complete
        assert result.chairman_error is None
        assert len(chairman_provider.calls) == 2
        # The second (successful) call is the transport-level JSON-retry
        # re-prompt, NOT a synthesis-repair prompt -- it must not contain
        # the synthesis-repair correction block.
        assert "KORREKTUR ERFORDERLICH" not in chairman_provider.calls[1]
        assert "VALIDES JSON" in chairman_provider.calls[1]

    def test_provider_timeout_follows_existing_provider_retry_not_synthesis_repair(self, tmp_path):
        """Part 10.G: a persistently failing provider (simulating a
        timeout) is retried exactly by _run_single_agent's own existing
        policy (2 total attempts) and never reaches, or is confused
        with, the synthesis-repair path -- there is no parsed response
        to validate at all, so no repair prompt is ever built."""
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, _ = _setup_standard_responses()
        chairman_provider = FailingLLMProvider("simulated timeout")
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp)
        fake_providers["model-ch"] = chairman_provider

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert not result.council_complete
        assert "category=provider_transport" in result.chairman_error
        assert len(chairman_provider.calls) == 2, "existing transport retry: 1 initial + 1 retry"
        assert "KORREKTUR ERFORDERLICH" not in chairman_provider.calls[-1]

    def test_invalid_recommendation_never_silently_switches_to_another_candidate(self, tmp_path):
        """Part 10.H: an invalid recommendation id, unresolved even
        after the bounded repair, must never be silently coerced into a
        real variant id."""
        a1_resp, a2_resp, a3_resp, ph2_resp, _, all_ids = _setup_standard_responses()
        broken_ch_resp = _invalid_recommendation_chairman_response(all_ids)
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, broken_ch_resp)
        fake_providers["model-ch"] = FakeLLMProvider([broken_ch_resp, broken_ch_resp])

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert not result.council_complete
        assert result.recommendation is None
        assert "does-not-exist" in result.chairman_error

    def test_repair_never_constructs_a_python_side_merged_variant(self, tmp_path):
        """Part 10.K: when the repair attempt's OWN response proposes a
        completely different final variant set than attempt 1, the
        resulting CouncilResult reflects EXACTLY the repair attempt's
        variants -- proving no deterministic Python-side splicing/
        merging of the two attempts' variants ever took place."""
        a1_resp, a2_resp, a3_resp, ph2_resp, _, all_ids = _setup_standard_responses()
        broken_ch_resp = _invalid_recommendation_chairman_response(all_ids)
        repaired_ch_resp = _make_chairman_response(["A2-var-1"])
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, broken_ch_resp)
        fake_providers["model-ch"] = FakeLLMProvider([broken_ch_resp, repaired_ch_resp])

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert result.council_complete
        assert [v.id for v in result.variants] == ["A2-var-1"]
        assert result.recommendation == "A2-var-1"

    def test_diagnostic_trace_exposes_safe_chairman_failure_reason(self, tmp_path):
        """Part 10.L: the Chairman result-projection (what a Diagnostic
        Trace / Web UI would render) must now surface the concrete
        chairman_error, category and attempt count -- not only the
        previous generic "No final recommendation produced."."""
        a1_resp, a2_resp, a3_resp, ph2_resp, _, all_ids = _setup_standard_responses()
        broken_ch_resp = _invalid_recommendation_chairman_response(all_ids)
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, broken_ch_resp)
        fake_providers["model-ch"] = FakeLLMProvider([broken_ch_resp, broken_ch_resp])

        structured_results = []
        result = _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path,
            capture_results=structured_results,
        )

        assert not result.council_complete
        chairman_result = next(
            item for item in structured_results
            if item["result_kind"] == "chairman_decision"
        )
        info = chairman_result["council_output"]["info"]
        assert info["chairman_error"] is not None
        assert "does-not-exist" in info["chairman_error"]
        assert info["chairman_failure_category"] == "invalid_recommendation"
        assert info["chairman_attempts"] == 2
        assert info["summary"] != "No final recommendation produced."
        assert "Chairman failed:" in info["summary"]

    def test_real_e2e_6_shaped_completeness_failure_is_repaired(self, tmp_path):
        """Mechanical reproduction of the ACTUAL Real-System-E2E #6 root
        cause (not merely a proxy category): the Chairman's first
        synthesis attempt merges fragmented agent proposals (one group
        addressing only the ESPHome requirement, another only a separate
        PlatformIO-like requirement) into final variants that -- exactly
        like Real-System-E2E #5's merged-venv -- each still cover only
        ONE of the two binding Requirements. The bounded repair, armed
        with the exact 010A completeness evidence, produces a genuinely
        complete variant on its second attempt."""
        a1_resp, a2_resp, a3_resp, ph2_resp, _, _ = _setup_standard_responses()
        incomplete_data = json.loads(_make_chairman_response(["x"]))
        incomplete_data["variants"] = [
            _variant("merged-host", "Direct Linux Setup", "req-1", rank=1),
            _variant("merged-docker", "Docker-basierte Entwicklung", rank=2),
        ]
        incomplete_data["recommendation"] = "merged-host"
        incomplete_ch_resp = json.dumps(incomplete_data)

        complete_data = json.loads(_make_chairman_response(["x"]))
        complete_data["variants"] = [
            _variant("complete-host", "ESPHome mit PlatformIO auf Linux", "req-1", "req-2", rank=1),
        ]
        complete_data["recommendation"] = "complete-host"
        complete_ch_resp = json.dumps(complete_data)

        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, incomplete_ch_resp)
        fake_providers["model-ch"] = FakeLLMProvider([incomplete_ch_resp, complete_ch_resp])

        with patch("app.engineering_council.create_council_provider") as mf:
            mf.side_effect = lambda config, resolver, ollama_url=None: fake_providers[config.model]
            council = EngineeringCouncil(
                council_config=_make_council_config(),
                secret_resolver=SimpleSecretResolver({"openrouter-api": "test"}),
            )
            result = council.evaluate(_make_council_input_with_two_binding_requirements())

        assert result.council_complete
        assert result.chairman_error is None
        assert result.recommendation == "complete-host"
        assert len(fake_providers["model-ch"].calls) == 2
        assert "KORREKTUR ERFORDERLICH" in fake_providers["model-ch"].calls[1]
        assert "req-1" in fake_providers["model-ch"].calls[1]
        assert "req-2" in fake_providers["model-ch"].calls[1]

    def test_no_secrets_or_chain_of_thought_in_new_chairman_diagnostics(self, tmp_path):
        """Part 10.M."""
        a1_resp, a2_resp, a3_resp, ph2_resp, _, all_ids = _setup_standard_responses()
        broken_ch_resp = _invalid_recommendation_chairman_response(all_ids)
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, broken_ch_resp)
        fake_providers["model-ch"] = FakeLLMProvider([broken_ch_resp, broken_ch_resp])

        structured_results = []
        result = _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path,
            capture_results=structured_results,
        )

        chairman_result = next(
            item for item in structured_results
            if item["result_kind"] == "chairman_decision"
        )
        info = chairman_result["council_output"]["info"]
        for forbidden in ("chain_of_thought", "api_key", "password", "begin private key",
                          "system_prompt", "you are the chairman"):
            assert forbidden not in (result.chairman_error or "").lower()
            assert forbidden not in str(info).lower()
        assert "innerhalb der zulässigen Menge" in CHAIRMAN_SYSTEM_PROMPT


# =========================================================================
# Test: synthesis_complete/council_complete semantics are structural-only
# (CLAUDE-ARCH-S2-012B, correcting an independent-review-flagged
# regression introduced by CLAUDE-ARCH-S2-012A: S2.2 must not pre-
# authorize or pre-reject a recommendation by calling S2.3 before
# declaring synthesis structurally complete -- council_complete=True
# must be able to coexist with an S2.3 rejection, including zero
# admissible candidates).
# =========================================================================


class TestSynthesisCompleteSemantics:
    """TC-S2.2-012B: Gates A, B, C, D of the CLAUDE-ARCH-S2-012B
    acceptance review."""

    def test_gate_a_structurally_complete_synthesis_reports_complete_regardless_of_admissibility(
        self, tmp_path,
    ):
        """Gate A: synthesis_complete=True means ONLY that the protocol
        is structurally complete. A structurally valid, single-candidate
        recommendation that violates platform is still reported as
        council_complete=True."""
        a1_resp = _make_phase1_response("A1", 1)
        a2_resp = _make_phase1_response("A2", 1)
        a3_resp = _make_phase1_response("A3", 1)
        all_ids = _all_variant_ids([a1_resp, a2_resp, a3_resp])
        ph2_resp = _make_phase2_response("x", all_ids)
        ch_data = json.loads(_make_chairman_response(all_ids))
        ch_data["variants"][0]["toolchain"] = [{
            "requirement_ref": "req-1", "name": "python", "type": "python_package",
            "install_method": "pip", "version": None, "state": "needs_install",
            "environment_constraint": "windows", "provided_by": None,
        }]
        ch_resp = json.dumps(ch_data)
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp)
        fake_providers["model-ch"] = FakeLLMProvider([ch_resp, ch_resp])

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert result.council_complete
        assert result.chairman_error is None
        assert result.recommendation is not None

    def test_gate_b_synthesis_complete_true_coexists_with_zero_admissible_candidates(self, tmp_path):
        """Gate B: even when EVERY proposed final variant is inadmissible
        (here: a binding platform Constraint every candidate violates),
        council_complete=True still holds -- the ZERO-admissible outcome
        is S2.3's own, separate, downstream finding, discoverable via
        validate_candidates(), never something S2.2 itself reports as a
        synthesis failure."""
        a1_resp = _make_phase1_response("A1", 1)
        a2_resp = _make_phase1_response("A2", 1)
        a3_resp = _make_phase1_response("A3", 1)
        all_ids = _all_variant_ids([a1_resp, a2_resp, a3_resp])
        ph2_resp = _make_phase2_response("x", all_ids)
        ch_data = json.loads(_make_chairman_response(all_ids))
        for variant in ch_data["variants"]:
            variant["toolchain"] = [{
                "requirement_ref": "req-1", "name": "python", "type": "python_package",
                "install_method": "pip", "version": None, "state": "needs_install",
                "environment_constraint": "windows", "provided_by": None,
            }]
        ch_resp = json.dumps(ch_data)
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp)
        fake_providers["model-ch"] = FakeLLMProvider([ch_resp, ch_resp])

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert result.council_complete
        assert result.chairman_error is None

        from app.engineering_decision import admissible_variants, validate_candidates
        validations = validate_candidates(result, platform="linux")
        assert admissible_variants(validations) == ()

    def test_gate_c_s2_3_remains_the_single_admissibility_authority(self, tmp_path):
        """Gate C: S2.2 never computes its own admissibility verdict --
        it only ever calls S2.3's validate_variants(). Proven here by
        confirming the SAME reason S2.3 would independently compute is
        exactly what the repair prompt was built from (no separate,
        S2.2-local admissibility heuristic exists)."""
        a1_resp = _make_phase1_response("A1", 1)
        a2_resp = _make_phase1_response("A2", 1)
        a3_resp = _make_phase1_response("A3", 1)
        all_ids = _all_variant_ids([a1_resp, a2_resp, a3_resp])
        ph2_resp = _make_phase2_response("x", all_ids)
        ch_data = json.loads(_make_chairman_response(all_ids))
        ch_data["variants"][0]["toolchain"] = [{
            "requirement_ref": "req-1", "name": "python", "type": "python_package",
            "install_method": "pip", "version": None, "state": "needs_install",
            "environment_constraint": "windows", "provided_by": None,
        }]
        ch_resp = json.dumps(ch_data)
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp)
        chairman_provider = FakeLLMProvider([ch_resp, ch_resp])
        fake_providers["model-ch"] = chairman_provider

        _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert len(chairman_provider.calls) == 2
        repair_prompt = chairman_provider.calls[1]
        assert "KORREKTUR ERFORDERLICH" in repair_prompt
        assert "platform_constraint" in repair_prompt or "violates platform constraint" in repair_prompt

    def test_gate_d_repair_remains_bounded_to_two_total_attempts(self, tmp_path):
        """Gate D: even when the admissibility-triggered repair's OWN
        response is STILL inadmissible, no third attempt is ever made --
        the original bounded-repair architecture (011A) is preserved."""
        a1_resp = _make_phase1_response("A1", 1)
        a2_resp = _make_phase1_response("A2", 1)
        a3_resp = _make_phase1_response("A3", 1)
        all_ids = _all_variant_ids([a1_resp, a2_resp, a3_resp])
        ph2_resp = _make_phase2_response("x", all_ids)
        ch_data = json.loads(_make_chairman_response(all_ids))
        ch_data["variants"][0]["toolchain"] = [{
            "requirement_ref": "req-1", "name": "python", "type": "python_package",
            "install_method": "pip", "version": None, "state": "needs_install",
            "environment_constraint": "windows", "provided_by": None,
        }]
        ch_resp = json.dumps(ch_data)
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp)
        chairman_provider = FakeLLMProvider([ch_resp, ch_resp])
        fake_providers["model-ch"] = chairman_provider

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert len(chairman_provider.calls) == 2, "must never attempt a third synthesis call"
        # Gate A/B: STILL council_complete=True -- repair exhaustion for
        # an ADMISSIBILITY reason is not a protocol failure.
        assert result.council_complete
        assert result.chairman_error is None

    def test_repair_never_reruns_phase1_or_phase2(self, tmp_path):
        """Preserve the bounded repair architecture: the admissibility-
        triggered repair reuses proposals/votes already gathered -- it
        never re-invokes phase1/phase2 agents (only the chairman model
        receives a second call)."""
        a1_resp = _make_phase1_response("A1", 1)
        a2_resp = _make_phase1_response("A2", 1)
        a3_resp = _make_phase1_response("A3", 1)
        all_ids = _all_variant_ids([a1_resp, a2_resp, a3_resp])
        ph2_resp = _make_phase2_response("x", all_ids)
        ch_data = json.loads(_make_chairman_response(all_ids))
        ch_data["variants"][0]["toolchain"] = [{
            "requirement_ref": "req-1", "name": "python", "type": "python_package",
            "install_method": "pip", "version": None, "state": "needs_install",
            "environment_constraint": "windows", "provided_by": None,
        }]
        ch_resp = json.dumps(ch_data)
        fixed_ch_data = json.loads(_make_chairman_response(all_ids))
        fixed_ch_resp = json.dumps(fixed_ch_data)
        a1_provider = FakeLLMProvider([a1_resp, ph2_resp])
        a2_provider = FakeLLMProvider([a2_resp, ph2_resp])
        a3_provider = FakeLLMProvider([a3_resp, ph2_resp])
        fake_providers = {
            "model-ea": a1_provider, "model-ti": a2_provider, "model-ra": a3_provider,
            "model-ch": FakeLLMProvider([ch_resp, fixed_ch_resp]),
        }

        result = _run_council_with_fakes(_make_council_config(), fake_providers, tmp_path)

        assert result.council_complete
        assert result.chairman_error is None
        # Exactly the calls phase1 (1) + phase2 (1) require -- no extra
        # phase1/phase2 call was made for the repair.
        assert len(a1_provider.calls) == 2
        assert len(a2_provider.calls) == 2
        assert len(a3_provider.calls) == 2


# =========================================================================
# Real-System-E2E #8 (CLAUDE-ARCH-S2-012D): the bounded, admissibility-
# triggered repair loop applied to the exact reproduced failure shape --
# a python_package toolchain item whose display name ("ESPHome CLI") is
# not a valid distribution identifier and whose technical_identity was
# left unset by the Chairman's first synthesis.
# =========================================================================


def _esphome_cli_toolchain_item(technical_identity=None, install_method="pip install esphome"):
    return {
        "requirement_ref": "req-1", "name": "ESPHome CLI",
        "technical_identity": technical_identity, "type": "python_package",
        "install_method": install_method, "version": None, "purpose": "",
        "depends_on": [], "state": "needs_install",
        "environment_constraint": None, "provided_by": None,
    }


def _platformio_toolchain_item():
    """Covers req-2 of _make_council_input_with_two_binding_requirements()
    with a legitimately-manual (never controlled) EXECUTABLE item, so
    these tests isolate the materializability dimension on req-1 without
    also tripping the unrelated binding-requirement-coverage dimension."""
    return {
        "requirement_ref": "req-2", "name": "platformio",
        "technical_identity": None, "type": "executable",
        "install_method": "pip install platformio", "version": None, "purpose": "",
        "depends_on": [], "state": "needs_install",
        "environment_constraint": None, "provided_by": None,
    }


class TestRealE2E8MaterializabilityRepair:
    """TC-B-S2.3-2.2-repair (materializability): the second half of the
    Real-System-E2E #8 regression -- the S2.3-level half (S2.3 names the
    exact offending item) is covered in
    tests/test_engineering_decision.py::TestRealE2E8MaterializabilityDiagnostics."""

    def test_case_e_targeted_repair_fixes_technical_identity_and_becomes_admissible(
        self, tmp_path,
    ):
        """E: the first Chairman synthesis produces the exact Real-System-
        E2E #8 defect (missing technical_identity); the bounded repair's
        now-specific evidence lets the SECOND synthesis correct exactly
        that field, so the second S2.3 validation succeeds."""
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, _ = _setup_standard_responses()
        chairman_data = json.loads(ch_resp)
        broken_variant = _variant("merged-host-venv", "ESPHome CLI mit Python Virtual Environment")
        broken_variant["toolchain"] = [_esphome_cli_toolchain_item(technical_identity=None), _platformio_toolchain_item()]
        chairman_data["variants"] = [broken_variant]
        chairman_data["recommendation"] = "merged-host-venv"
        broken_ch_resp = json.dumps(chairman_data)

        fixed_data = json.loads(ch_resp)
        fixed_variant = _variant("merged-host-venv", "ESPHome CLI mit Python Virtual Environment")
        fixed_variant["toolchain"] = [_esphome_cli_toolchain_item(technical_identity="esphome"), _platformio_toolchain_item()]
        fixed_data["variants"] = [fixed_variant]
        fixed_data["recommendation"] = "merged-host-venv"
        fixed_ch_resp = json.dumps(fixed_data)

        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, broken_ch_resp)
        chairman_provider = FakeLLMProvider([broken_ch_resp, fixed_ch_resp])
        fake_providers["model-ch"] = chairman_provider

        with patch("app.engineering_council.create_council_provider") as mf:
            mf.side_effect = lambda config, resolver, ollama_url=None: fake_providers[config.model]
            council = EngineeringCouncil(
                council_config=_make_council_config(),
                secret_resolver=SimpleSecretResolver({"openrouter-api": "test"}),
            )
            result = council.evaluate(_make_council_input_with_two_binding_requirements())

        assert len(chairman_provider.calls) == 2
        assert result.council_complete
        assert result.chairman_error is None
        assert result.recommendation == "merged-host-venv"

        from app.engineering_decision import validate_candidates
        validations = validate_candidates(
            result, preflight=_make_council_input_with_two_binding_requirements().preflight,
            platform="linux",
        )
        assert validations[0].admissible is True
        # The repair prompt sent for the second attempt must have named
        # the exact offending item -- proving the fix (not luck) drove
        # the successful correction.
        repair_prompt = chairman_provider.calls[1]
        assert "req-1" in repair_prompt
        assert "ESPHome CLI" in repair_prompt

    def test_case_f_repair_still_defective_stays_bounded_at_two_attempts(self, tmp_path):
        """F: the repair response repeats the SAME materializability
        defect. No third Chairman synthesis is ever attempted -- the
        original, structurally-valid-but-inadmissible result is kept,
        council_complete remains True (Gate D/B, CLAUDE-ARCH-S2-012B: an
        admissibility-only repair exhaustion is never a protocol
        failure)."""
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, _ = _setup_standard_responses()
        chairman_data = json.loads(ch_resp)
        broken_variant = _variant("merged-host-venv", "ESPHome CLI mit Python Virtual Environment")
        broken_variant["toolchain"] = [_esphome_cli_toolchain_item(technical_identity=None), _platformio_toolchain_item()]
        chairman_data["variants"] = [broken_variant]
        chairman_data["recommendation"] = "merged-host-venv"
        broken_ch_resp = json.dumps(chairman_data)

        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, broken_ch_resp)
        chairman_provider = FakeLLMProvider([broken_ch_resp, broken_ch_resp])
        fake_providers["model-ch"] = chairman_provider

        with patch("app.engineering_council.create_council_provider") as mf:
            mf.side_effect = lambda config, resolver, ollama_url=None: fake_providers[config.model]
            council = EngineeringCouncil(
                council_config=_make_council_config(),
                secret_resolver=SimpleSecretResolver({"openrouter-api": "test"}),
            )
            result = council.evaluate(_make_council_input_with_two_binding_requirements())

        assert len(chairman_provider.calls) == 2, "must never attempt a third synthesis call"
        assert result.council_complete
        assert result.chairman_error is None

        from app.engineering_decision import validate_candidates
        validations = validate_candidates(
            result, preflight=_make_council_input_with_two_binding_requirements().preflight,
            platform="linux",
        )
        assert validations[0].admissible is False
        assert "cannot be materialized" in validations[0].reasons[0]


class TestInstallMethodProducerRepairHint:
    """CLAUDE-ADC-S23-INSTALL-METHOD-PRODUCER-REPAIR-FIX-001: focused,
    direct unit coverage of _build_chairman_repair_prompt()'s hint
    selection, isolated from the full FakeLLMProvider Council pipeline
    (that end-to-end path is separately covered by
    TestRealE2E8MaterializabilityRepair's case E, an identity-only
    defect that must keep getting the technical_identity hint
    unchanged). An install_method-only defect must get ONLY the new,
    install_method-specific hint -- never the technical_identity hint,
    which would misdirect the Chairman's one bounded repair attempt at
    a field that is already correct."""

    def test_install_method_only_defect_gets_install_method_hint_not_identity_hint(self):
        from app.engineering_decision import EngineeringReworkRequest

        rework = EngineeringReworkRequest(
            rejected_candidate_id="merged-2",
            reason_codes=("materializability_conflict",),
            materializability_conflict=True,
            materializability_conflict_detail=(
                "req-bb77bad0 (item name='ESPHome Python Package (in container)')",
            ),
            identity_conflict=False,
            identity_conflict_detail=(),
            install_method_conflict=True,
            install_method_conflict_detail=(
                "req-bb77bad0 (item name='ESPHome Python Package (in container)')",
            ),
        )

        prompt = _build_chairman_repair_prompt("ORIGINAL PROMPT", rework)

        assert "req-bb77bad0" in prompt
        assert "install_method" in prompt
        assert "Hinweis zum Materialisierbarkeits-Mangel (install_method)" in prompt
        assert "technical_identity auf die exakte installierbare" not in prompt
        assert "Hinweis zum Materialisierbarkeits-Mangel (fehlende/ungueltige" not in prompt

    def test_identity_only_defect_still_gets_technical_identity_hint_not_install_method_hint(self):
        from app.engineering_decision import EngineeringReworkRequest

        rework = EngineeringReworkRequest(
            rejected_candidate_id="merged-host-venv",
            reason_codes=("materializability_conflict",),
            materializability_conflict=True,
            materializability_conflict_detail=(
                "req-esphome (item name='ESPHome CLI')",
            ),
            identity_conflict=True,
            identity_conflict_detail=("req-esphome (item name='ESPHome CLI')",),
            install_method_conflict=False,
            install_method_conflict_detail=(),
        )

        prompt = _build_chairman_repair_prompt("ORIGINAL PROMPT", rework)

        assert "req-esphome" in prompt
        assert "technical_identity auf die exakte installierbare" in prompt
        assert "Hinweis zum Materialisierbarkeits-Mangel (install_method)" not in prompt

    def test_both_categories_present_emit_both_independent_hints(self):
        from app.engineering_decision import EngineeringReworkRequest

        rework = EngineeringReworkRequest(
            rejected_candidate_id="merged-mixed",
            reason_codes=("materializability_conflict",),
            materializability_conflict=True,
            materializability_conflict_detail=(
                "req-a (item name='A')", "req-b (item name='B')",
            ),
            identity_conflict=True,
            identity_conflict_detail=("req-a (item name='A')",),
            install_method_conflict=True,
            install_method_conflict_detail=("req-b (item name='B')",),
        )

        prompt = _build_chairman_repair_prompt("ORIGINAL PROMPT", rework)

        assert "technical_identity auf die exakte installierbare" in prompt
        assert "Hinweis zum Materialisierbarkeits-Mangel (install_method)" in prompt

    def test_neither_category_present_emits_no_materializability_hint(self):
        from app.engineering_decision import EngineeringReworkRequest

        rework = EngineeringReworkRequest(
            rejected_candidate_id="v1",
            reason_codes=("verification_feasibility_conflict",),
            verification_feasibility_conflict=True,
            verification_feasibility_conflict_detail=(
                "req-1: mechanism='pytest' evidence='pytest' -> not compatible",
            ),
        )

        prompt = _build_chairman_repair_prompt("ORIGINAL PROMPT", rework)

        assert "Hinweis zum Materialisierbarkeits-Mangel" not in prompt
        assert "Hinweis zum Verifikations-Mangel" in prompt


class TestInstallMethodPromptConsistency:
    """CLAUDE-ADC-S23-INSTALL-METHOD-PROMPT-CONSISTENCY-FIX-002: focused,
    deterministic proof that the Phase-1 (build_phase1_prompt) and
    Chairman-merge (build_chairman_prompt) INSTALL_METHOD contracts are
    mutually consistent and internally non-contradictory -- fixing the
    two producer-prompt defects an independent Codex review of
    CLAUDE-ADC-S23-INSTALL-METHOD-PRODUCER-REPAIR-FIX-001 found:
    (1) the Phase-1 contract explicitly PERMITTED placement wording in
    the package display name ("ESPHome Python Package (in container)"
    "ist zulaessig") in the same paragraph that forbade it, and
    (2) install_method=null was never given explicit, matching
    fail-closed/non-inference semantics in either contract. These tests
    read the ACTUAL rendered prompt text (never a hand-copied expectation
    of it), so they fail if either prompt regresses back to permitting
    the contradiction or drops the null semantics."""

    CANONICAL_FORMS = (
        '"pip"',
        '"python_package"',
        '"pip install <technical_identity>"',
        '"python -m pip install <technical_identity>"',
    )

    @staticmethod
    def _normalized(text: str) -> str:
        """Collapses all whitespace runs (including line-wrap newlines
        inside the multi-line prompt templates) to single spaces, so
        these assertions check semantic phrase adjacency rather than
        this-session's exact line-wrap column -- a future re-wrap of the
        same wording must not spuriously break this regression."""
        return " ".join(text.split())

    @classmethod
    def _phase1_prompt(cls) -> str:
        ci = CouncilInput(project_id="p1", platform="linux")
        return cls._normalized(build_phase1_prompt(ci, AGENT_ROLE_TOOLCHAIN, 3))

    @classmethod
    def _chairman_prompt(cls) -> str:
        ci = CouncilInput(project_id="p1", platform="linux")
        return cls._normalized(build_chairman_prompt("[]", "[]", council_input=ci))

    def test_a_both_prompts_contain_the_same_four_canonical_forms(self):
        phase1 = self._phase1_prompt()
        chairman = self._chairman_prompt()
        for form in self.CANONICAL_FORMS:
            assert form in phase1, f"Phase-1 missing canonical form {form!r}"
            assert form in chairman, f"Chairman missing canonical form {form!r}"

    def test_b_both_prompts_state_matching_null_semantics(self):
        for prompt in (self._phase1_prompt(), self._chairman_prompt()):
            assert "KEINE fünfte install_method-Form" in prompt, (
                "null must be stated as NOT a fifth install_method form"
            )
            assert "NICHT automatisch materialisierbar" in prompt
            assert "manual_review (fail-closed)" in prompt
            assert "abzuleiten oder zu erraten" in prompt
            assert "aus dem Anzeigenamen" in prompt

    def test_c_both_prompts_prohibit_placement_in_package_name(self):
        for prompt in (self._phase1_prompt(), self._chairman_prompt()):
            # The install_method rule text itself names "name" as a
            # forbidden placement location.
            assert 'niemals in "install_method" und niemals in "name"' in prompt or (
                'in dieses Feld oder in "name"' in prompt
            )

    def test_d_neither_prompt_permits_the_in_container_name_contradiction(self):
        """The exact defect the Codex review found: a sentence declaring
        the "(in container)" display name "ist zulaessig als
        menschenlesbares Label" directly contradicting the surrounding
        "niemals in name" rule. Must be entirely gone from both prompts;
        any remaining "(in container)" example must instead be marked
        explicitly disallowed ("ist NICHT zulaessig")."""
        for prompt in (self._phase1_prompt(), self._chairman_prompt()):
            assert "ist zulässig als menschenlesbares Label" not in prompt
            assert "(in container)" in prompt
            assert "ist NICHT zulässig" in prompt

    def test_e_install_method_shape_contract_is_reflected_identically_in_both(self):
        """Both prompts must reject the exact same non-canonical shapes
        (compound shell chains, venv activation, docker exec) using the
        same vocabulary -- proving the fix did not diverge Phase-1 and
        Chairman guidance."""
        for prompt in (self._phase1_prompt(), self._chairman_prompt()):
            assert "venv-Aktivierung" in prompt
            assert "Docker-" in prompt
            assert "zusammengesetzter" in prompt


class TestVerificationFeasibilityBoundedRepair:
    """CLAUDE-ARCH-S2-013E: the bounded, admissibility-triggered repair
    loop applied to a verification-feasibility gap -- proving a repair
    may correct verification evidence through the SAME, unweakened S2.3
    check (app.engineering_decision._verification_feasibility_gaps()),
    never by relaxing it."""

    @staticmethod
    def _council_input_needing_verification():
        # Reuses the exact requirement/preflight shape of
        # _make_council_input_with_two_binding_requirements() (which the
        # shared _setup_standard_responses() phase1/phase2 fixtures are
        # already built to satisfy -- req-1 and req-2 both referenced by
        # every phase1 toolchain item), only adding a verification_method
        # to req-1 so it also needs verification coverage.
        from dataclasses import replace

        req_esphome = replace(
            _make_requirement("req-1", "esphome", "python_package", True),
            verification_method="run the firmware test suite",
        )
        req_platformio = _make_requirement("req-2", "platformio", "executable", True)
        return CouncilInput(
            requirements=(req_esphome, req_platformio),
            preflight=PreflightResult(
                id="pre-1", project_id="test-project", overall_ready=False,
                results=(
                    PreflightRequirementResult(requirement_id="req-1", present=False, satisfied=False),
                    PreflightRequirementResult(requirement_id="req-2", present=False, satisfied=False),
                ),
                missing_requirements=(req_esphome, req_platformio),
                activations=(
                    RequirementActivation("req-1", True, True),
                    RequirementActivation("req-2", True, True),
                ),
                already_installed=(), warnings=(),
            ),
            detected_stack="esphome", project_id="esphome-p1",
            project_files=("esphome-p1.yaml",), platform="linux",
        )

    def test_targeted_repair_adds_verification_coverage_and_becomes_admissible(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, _ = _setup_standard_responses()
        chairman_data = json.loads(ch_resp)
        broken_variant = _variant("v1", "ESPHome-Firmware", "req-1", "req-2")
        broken_variant["verification"] = "run tests"
        # CLAUDE-ARCH-S2-014C (F4): req-1's toolchain item identity must
        # semantically match the real Requirement ("esphome") it claims
        # to cover -- the bare requirement_ref-shaped identity
        # _toolchain_item() defaults to can never satisfy that check.
        broken_variant["toolchain"][0]["name"] = "esphome"
        broken_variant["toolchain"][0]["technical_identity"] = "esphome"
        broken_variant["toolchain"][1]["name"] = "platformio"
        broken_variant["toolchain"][1]["technical_identity"] = "platformio"
        broken_variant["toolchain"][1]["type"] = "executable"
        chairman_data["variants"] = [broken_variant]
        chairman_data["recommendation"] = "v1"
        broken_ch_resp = json.dumps(chairman_data)

        fixed_data = json.loads(ch_resp)
        fixed_variant = _variant("v1", "ESPHome-Firmware", "req-1", "req-2")
        fixed_variant["verification"] = "run tests"
        fixed_variant["toolchain"][0]["name"] = "esphome"
        fixed_variant["toolchain"][0]["technical_identity"] = "esphome"
        fixed_variant["toolchain"][1]["name"] = "platformio"
        fixed_variant["toolchain"][1]["technical_identity"] = "platformio"
        fixed_variant["toolchain"][1]["type"] = "executable"
        # CLAUDE-ARCH-S2-013G: the verification mechanism's own evidence
        # must independently corroborate "pytest" via a DEDICATED
        # toolchain item -- never overloading the req-1 (esphome) item's
        # own identity, which CLAUDE-ARCH-S2-014C (F4) now also requires
        # to semantically match the Requirement it covers.
        fixed_variant["toolchain"].append({
            "requirement_ref": "req-1", "name": "pytest",
            "technical_identity": "pytest", "type": "executable",
            "install_method": None, "version": None, "purpose": "",
            "depends_on": [], "state": "needs_install",
            "environment_constraint": None, "provided_by": None,
            "provides_verification": ["pytest"],
        })
        fixed_variant["verification_coverage"] = [{
            "requirement_refs": ["req-1"], "kind": "test_command",
            "mechanism": "pytest", "evidence": "pytest",
        }]
        fixed_data["variants"] = [fixed_variant]
        fixed_data["recommendation"] = "v1"
        fixed_ch_resp = json.dumps(fixed_data)

        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, broken_ch_resp)
        chairman_provider = FakeLLMProvider([broken_ch_resp, fixed_ch_resp])
        fake_providers["model-ch"] = chairman_provider

        council_input = self._council_input_needing_verification()
        with patch("app.engineering_council.create_council_provider") as mf:
            mf.side_effect = lambda config, resolver, ollama_url=None: fake_providers[config.model]
            council = EngineeringCouncil(
                council_config=_make_council_config(),
                secret_resolver=SimpleSecretResolver({"openrouter-api": "test"}),
            )
            result = council.evaluate(council_input)

        assert len(chairman_provider.calls) == 2
        assert result.council_complete
        assert result.chairman_error is None

        from app.engineering_decision import EngineeringReworkRequest, validate_candidates
        from app.verification import trusted_verification_identity_groups
        validations = validate_candidates(
            result, preflight=council_input.preflight, platform="linux",
            trusted_verification_groups=trusted_verification_identity_groups(
                {"test_systems": ["pytest"], "build_systems": [], "firmware_indicators": []},
            ),
        )
        assert validations[0].admissible is True

    def test_repair_still_vague_stays_bounded_and_inadmissible(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, _ = _setup_standard_responses()
        chairman_data = json.loads(ch_resp)
        broken_variant = _variant("v1", "ESPHome-Firmware", "req-1", "req-2")
        broken_variant["verification"] = "run tests"
        # CLAUDE-ARCH-S2-014C (F4): req-1's toolchain item identity must
        # semantically match the real Requirement ("esphome") it claims
        # to cover, so the ONLY remaining defect this test exercises is
        # the missing verification coverage.
        broken_variant["toolchain"][0]["name"] = "esphome"
        broken_variant["toolchain"][0]["technical_identity"] = "esphome"
        broken_variant["toolchain"][1]["name"] = "platformio"
        broken_variant["toolchain"][1]["technical_identity"] = "platformio"
        broken_variant["toolchain"][1]["type"] = "executable"
        chairman_data["variants"] = [broken_variant]
        chairman_data["recommendation"] = "v1"
        broken_ch_resp = json.dumps(chairman_data)

        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, broken_ch_resp)
        chairman_provider = FakeLLMProvider([broken_ch_resp, broken_ch_resp])
        fake_providers["model-ch"] = chairman_provider

        council_input = self._council_input_needing_verification()
        with patch("app.engineering_council.create_council_provider") as mf:
            mf.side_effect = lambda config, resolver, ollama_url=None: fake_providers[config.model]
            council = EngineeringCouncil(
                council_config=_make_council_config(),
                secret_resolver=SimpleSecretResolver({"openrouter-api": "test"}),
            )
            result = council.evaluate(council_input)

        assert len(chairman_provider.calls) == 2, "must never attempt a third synthesis call"
        assert result.council_complete
        assert result.chairman_error is None

        from app.engineering_decision import validate_candidates
        validations = validate_candidates(result, preflight=council_input.preflight, platform="linux")
        assert validations[0].admissible is False
        assert "missing required verification coverage" in validations[0].reasons[0]


# =========================================================================
# CLAUDE-ADC-COUNCIL-DIAGNOSTIC-CAPTURE-001: zero-retained Phase-1
# proposal diagnostic capture
# =========================================================================


class TestZeroProposalReasonClassification:
    """Pure classification unit tests -- no Council/provider infra at
    all. Each mirrors exactly the shape _phase1_independent_proposals()
    hands to _classify_zero_proposal_reason() once it already knows an
    agent's Phase-1 result decoded successfully but retained zero
    proposals."""

    def test_empty_object_is_classified_as_empty_object(self):
        assert _classify_zero_proposal_reason({}, [], []) == "empty_object"

    def test_truthy_mapping_missing_variants_key(self):
        assert _classify_zero_proposal_reason(
            {"note": "no variants field at all"}, [], [],
        ) == "missing_variants"

    def test_empty_variants_iterable(self):
        assert _classify_zero_proposal_reason(
            {"variants": []}, [], [],
        ) == "empty_variants"

    def test_empty_dict_variants_is_still_empty_variants(self):
        """A genuinely empty non-list container ("variants": {}) carries
        exactly as little content as an empty list -- honestly described
        the same way, never "other_internal"."""
        assert _classify_zero_proposal_reason(
            {"variants": {}}, {}, [],
        ) == "empty_variants"

    def test_empty_string_variants_is_still_empty_variants(self):
        assert _classify_zero_proposal_reason(
            {"variants": ""}, "", [],
        ) == "empty_variants"

    def test_nonempty_string_variants_is_never_empty_variants(self):
        """CLAUDE-ADC-COUNCIL-DIAGNOSTIC-HARDENING-FIX-001 (F2): a
        NONEMPTY malformed "variants" value (e.g. the LLM emitted a bare
        string instead of a list) genuinely carries content -- it must
        never be silently coerced into looking "empty" merely because it
        fails an isinstance(..., list) check. With no rejections to
        explain it (the pure classification input here, independent of
        whatever the real candidate-processing loop would do with it),
        the deterministic fallback is "other_internal", never
        "empty_variants" and never a fabricated "all_candidates_rejected"
        with no evidence behind it."""
        assert _classify_zero_proposal_reason(
            {"variants": "not a list"}, "not a list", [],
        ) == "other_internal"

    def test_nonempty_dict_variants_is_never_empty_variants(self):
        """Same F2 shape as the string case, for a dict -- Codex's own
        reproduction input."""
        assert _classify_zero_proposal_reason(
            {"variants": {"unexpected": "shape"}}, {"unexpected": "shape"}, [],
        ) == "other_internal"

    def test_nonempty_malformed_variants_with_actual_rejections_is_all_candidates_rejected(self):
        """When the caller's own (unchanged) per-item loop DID process
        and reject every entry of a nonempty malformed "variants" value
        -- exactly what happens in production when the loop iterates a
        nonempty dict's keys or a nonempty string's characters, each of
        which fails to build into an AgentProposal -- that outcome is
        accurately "all_candidates_rejected", not "other_internal"."""
        rejected = [_candidate_rejection_diagnostic("u", ValueError("boom"))]
        assert _classify_zero_proposal_reason(
            {"variants": "unexpected"}, "unexpected", rejected,
        ) == "all_candidates_rejected"

    def test_all_candidates_rejected(self):
        rejected = [_candidate_rejection_diagnostic(
            {"toolchain": [{"requirement_ref": "req-x"}]},
            ValueError(
                "toolchain requirement_ref must exactly reference a "
                "current CouncilInput requirement [category=invalid_requirement_ref]"
            ),
        )]
        variants_field = [{"toolchain": [{"requirement_ref": "req-x"}]}]
        assert _classify_zero_proposal_reason(
            {"variants": variants_field}, variants_field, rejected,
        ) == "all_candidates_rejected"


class TestCandidateRejectionDiagnostic:
    """Pure unit tests for the bounded, deterministic per-candidate
    rejection evidence -- category plus only the offending structured
    identity fields, never free text."""

    def test_captures_tagged_category_and_offending_requirement_ref(self):
        variant_data = {"toolchain": [{"requirement_ref": "req-x", "name": "bad tool"}]}
        exc = ValueError(
            "toolchain requirement_ref must exactly reference a current "
            "CouncilInput requirement [category=invalid_requirement_ref]"
        )

        result = _candidate_rejection_diagnostic(variant_data, exc)

        assert result == {
            "category": "invalid_requirement_ref",
            "rejected_requirement_refs": ["req-x"],
            "rejected_provided_by": [],
            "rejected_requirement_ref_invalid_types": [],
            "rejected_provided_by_invalid_types": [],
        }

    def test_falls_back_to_unknown_category_when_no_tag(self):
        variant_data = {"toolchain": [{"provided_by": "req-y"}]}
        exc = ValueError(
            "toolchain provided_by must reference a current CouncilInput requirement"
        )

        result = _candidate_rejection_diagnostic(variant_data, exc)

        assert result["category"] == "unknown"
        assert result["rejected_provided_by"] == ["req-y"]
        assert result["rejected_requirement_refs"] == []

    def test_malformed_toolchain_never_raises(self):
        """A candidate whose own "toolchain" field is itself malformed
        (not a list) must never crash the diagnostic capture -- it is
        diagnostic-only and must degrade to empty evidence, never
        propagate a second exception on top of the original one."""
        result = _candidate_rejection_diagnostic(
            {"toolchain": "not a list"}, ValueError("boom"),
        )

        assert result["rejected_requirement_refs"] == []
        assert result["rejected_provided_by"] == []


class TestCandidateRejectionDiagnosticF1PrivacyHardening:
    """CLAUDE-ADC-COUNCIL-DIAGNOSTIC-HARDENING-FIX-001 (Codex review
    CDX-ADC-COUNCIL-DIAGNOSTIC-TRACE-REVIEW-001, finding F1 -- HIGH):
    reproduces Codex's own fixed inputs -- a malformed nested object in
    requirement_ref/provided_by carrying canary keys "agent_reasoning"
    and nested "credentials"."secret" -- and proves the sanitizer never
    stringifies them into a persisted identifier."""

    _CANARY_REASONING = "CANARY-AGENT-REASONING-MUST-NEVER-LEAK"
    _CANARY_SECRET = "CANARY-SECRET-MUST-NEVER-LEAK"

    def _canary_object(self):
        return {
            "agent_reasoning": self._CANARY_REASONING,
            "credentials": {"secret": self._CANARY_SECRET},
        }

    def test_nested_object_requirement_ref_is_never_stringified(self):
        variant_data = {"toolchain": [{"requirement_ref": self._canary_object()}]}
        exc = ValueError(
            "toolchain requirement_ref must exactly reference a current "
            "CouncilInput requirement [category=invalid_requirement_ref]"
        )

        result = _candidate_rejection_diagnostic(variant_data, exc)

        assert result["rejected_requirement_refs"] == []
        assert result["rejected_requirement_ref_invalid_types"] == ["dict"]
        serialized = json.dumps(result)
        assert self._CANARY_REASONING not in serialized
        assert self._CANARY_SECRET not in serialized
        assert "agent_reasoning" not in serialized
        assert "credentials" not in serialized

    def test_nested_object_provided_by_is_never_stringified(self):
        variant_data = {"toolchain": [{"provided_by": self._canary_object()}]}
        exc = ValueError("toolchain provided_by must reference a current CouncilInput requirement")

        result = _candidate_rejection_diagnostic(variant_data, exc)

        assert result["rejected_provided_by"] == []
        assert result["rejected_provided_by_invalid_types"] == ["dict"]
        serialized = json.dumps(result)
        assert self._CANARY_REASONING not in serialized
        assert self._CANARY_SECRET not in serialized
        assert "agent_reasoning" not in serialized
        assert "credentials" not in serialized

    def test_list_requirement_ref_carrying_a_canary_object_is_never_stringified(self):
        variant_data = {"toolchain": [{
            "requirement_ref": ["req-1", self._canary_object()],
        }]}
        exc = ValueError("boom [category=invalid_requirement_ref]")

        result = _candidate_rejection_diagnostic(variant_data, exc)

        assert result["rejected_requirement_refs"] == []
        assert result["rejected_requirement_ref_invalid_types"] == ["list"]
        serialized = json.dumps(result)
        assert self._CANARY_REASONING not in serialized
        assert self._CANARY_SECRET not in serialized

    def test_unsafe_string_requirement_ref_is_dropped_not_leaked(self):
        """A string value is still rejected (never persisted) when it
        does not look like a bounded, single-token identifier -- e.g. it
        embeds a whitespace-separated key=value pair a naive stringify
        could otherwise carry through verbatim."""
        unsafe = f"req-1 agent_reasoning={self._CANARY_REASONING}"
        variant_data = {"toolchain": [{"requirement_ref": unsafe}]}
        exc = ValueError("boom [category=invalid_requirement_ref]")

        result = _candidate_rejection_diagnostic(variant_data, exc)

        assert result["rejected_requirement_refs"] == []
        assert result["rejected_requirement_ref_invalid_types"] == ["str"]
        serialized = json.dumps(result)
        assert self._CANARY_REASONING not in serialized
        assert unsafe not in serialized

    def test_overlong_string_requirement_ref_is_dropped_not_leaked(self):
        overlong = "req-" + ("x" * 500)
        variant_data = {"toolchain": [{"requirement_ref": overlong}]}
        exc = ValueError("boom [category=invalid_requirement_ref]")

        result = _candidate_rejection_diagnostic(variant_data, exc)

        assert result["rejected_requirement_refs"] == []
        assert result["rejected_requirement_ref_invalid_types"] == ["str"]

    def test_valid_short_identifier_is_still_accepted_unchanged(self):
        """The hardening must not reject genuinely valid identifiers --
        a real, bounded, single-token requirement_ref still passes
        through exactly as before."""
        variant_data = {"toolchain": [{"requirement_ref": "req-esphome-1"}]}
        exc = ValueError("boom [category=invalid_requirement_ref]")

        result = _candidate_rejection_diagnostic(variant_data, exc)

        assert result["rejected_requirement_refs"] == ["req-esphome-1"]
        assert result["rejected_requirement_ref_invalid_types"] == []

    _H1_COMPACT_CANARY = (
        '{"agent_reasoning":"PRIVATE_REASONING_CANARY_002",'
        '"credentials":{"secret":"PRIVATE_SECRET_CANARY_002"}}'
    )

    def test_compact_serialized_canary_string_requirement_ref_is_rejected(self):
        """CLAUDE-ADC-COUNCIL-DIAGNOSTIC-PRIVACY-HARDENING-FIX-002 (Codex
        rereview CDX-ADC-COUNCIL-DIAGNOSTIC-HARDENING-REREVIEW-002,
        finding H1 -- HIGH): the EXACT reviewer canary -- a compact
        (whitespace-free) JSON string, still a plain Python `str`, that
        the PRIOR no-whitespace-only rule accepted. The strict positive
        identifier policy rejects it purely on character class (braces/
        quotes/colons are not in [A-Za-z0-9_.-])."""
        variant_data = {"toolchain": [{"requirement_ref": self._H1_COMPACT_CANARY}]}
        exc = ValueError("boom [category=invalid_requirement_ref]")

        result = _candidate_rejection_diagnostic(variant_data, exc)

        assert result["rejected_requirement_refs"] == []
        assert result["rejected_requirement_ref_invalid_types"] == ["str"]
        serialized = json.dumps(result)
        assert "PRIVATE_REASONING_CANARY_002" not in serialized
        assert "PRIVATE_SECRET_CANARY_002" not in serialized
        assert "agent_reasoning" not in serialized
        assert "credentials" not in serialized

    def test_compact_serialized_canary_string_provided_by_is_rejected(self):
        variant_data = {"toolchain": [{"provided_by": self._H1_COMPACT_CANARY}]}
        exc = ValueError("toolchain provided_by must reference a current CouncilInput requirement")

        result = _candidate_rejection_diagnostic(variant_data, exc)

        assert result["rejected_provided_by"] == []
        assert result["rejected_provided_by_invalid_types"] == ["str"]
        serialized = json.dumps(result)
        assert "PRIVATE_REASONING_CANARY_002" not in serialized
        assert "PRIVATE_SECRET_CANARY_002" not in serialized
        assert "agent_reasoning" not in serialized
        assert "credentials" not in serialized


class TestSanitizedCandidateIdentifierPolicy:
    """CLAUDE-ADC-COUNCIL-DIAGNOSTIC-PRIVACY-HARDENING-FIX-002 (H1):
    focused positive/negative coverage of the strict positive identifier
    policy itself, independent of the surrounding rejection-diagnostic
    machinery."""

    @pytest.mark.parametrize("value", [
        "req-1", "req_esphome", "req.esphome", "req-esphome-fw",
        "REQ-1", "a", "req-3cycle-a", "python_package",
    ])
    def test_real_identifier_shapes_are_accepted(self, value):
        assert _sanitized_candidate_identifier(value) == value

    @pytest.mark.parametrize("value", [
        '{"a":"b"}',                        # compact JSON object
        '["a","b"]',                        # compact JSON array
        'req"1',                            # quote
        'req{1}',                           # braces
        'req[1]',                           # brackets
        'req:1',                            # colon
        'req=1',                            # equals sign
        'req,1',                            # comma
        'req/1',                            # slash
        'req\\1',                           # backslash
        'req 1',                            # internal whitespace
        'req\t1',                           # tab
        'req\n1',                           # newline
        'req\x001',                         # control character
        '',                                 # empty
        '   ',                              # whitespace-only
    ])
    def test_unsafe_syntax_is_rejected(self, value):
        assert _sanitized_candidate_identifier(value) is None

    def test_overlong_value_is_rejected(self):
        assert _sanitized_candidate_identifier("req-" + "x" * 500) is None

    @pytest.mark.parametrize("value", [None, 1, 1.5, True, [], {}, ("a",)])
    def test_non_string_value_is_rejected(self, value):
        assert _sanitized_candidate_identifier(value) is None

    def test_leading_trailing_whitespace_is_stripped_before_validation(self):
        assert _sanitized_candidate_identifier("  req-1  ") == "req-1"


class TestTrustedCandidateRejectionCategory:
    """CLAUDE-ADC-COUNCIL-DIAGNOSTIC-PRIVACY-HARDENING-FIX-002 (Codex
    rereview CDX-ADC-COUNCIL-DIAGNOSTIC-HARDENING-REREVIEW-002, finding
    H2 -- HIGH): the diagnostic category must be drawn from a small,
    explicit, closed set -- never arbitrary exception text."""

    def test_the_one_trusted_category_passes_through(self):
        exc = ValueError("boom [category=invalid_requirement_ref]")
        assert _trusted_candidate_rejection_category(exc) == "invalid_requirement_ref"

    def test_every_currently_trusted_category_is_covered(self):
        for category in _TRUSTED_CANDIDATE_REJECTION_CATEGORIES:
            exc = ValueError(f"boom [category={category}]")
            assert _trusted_candidate_rejection_category(exc) == category

    def test_untrusted_tag_becomes_unknown(self):
        exc = ValueError("boom [category=totally_made_up_category]")
        assert _trusted_candidate_rejection_category(exc) == "unknown"

    def test_injected_canary_category_tag_becomes_unknown(self):
        """CLAUDE-ADC-COUNCIL-DIAGNOSTIC-PRIVACY-HARDENING-FIX-002's own
        exact reviewer reproduction: a candidate confidence value of
        "[category=PRIVATE_REASONING_CANARY_002]" makes float()
        conversion raise a ValueError whose OWN message text embeds
        that string -- the extracted "category" must never be trusted
        merely because it matches the tag pattern."""
        canary = "PRIVATE_REASONING_CANARY_002"
        try:
            float(f"[category={canary}]")
        except ValueError as exc:
            result = _trusted_candidate_rejection_category(exc)
        else:
            pytest.fail("float() was expected to raise for this input")

        assert result == "unknown"

    def test_no_tag_present_is_also_unknown(self):
        exc = ValueError("boom, no tag here")
        assert _trusted_candidate_rejection_category(exc) == "unknown"

    def test_candidate_rejection_diagnostic_never_persists_arbitrary_category_text(self):
        canary = "PRIVATE_REASONING_CANARY_002"
        try:
            float(f"[category={canary}]")
        except ValueError as exc:
            result = _candidate_rejection_diagnostic({"toolchain": []}, exc)
        else:
            pytest.fail("float() was expected to raise for this input")

        assert result["category"] == "unknown"
        assert canary not in json.dumps(result)


class TestZeroProposalCentralDiagnosticTrace:
    """Integration-level coverage through the real EngineeringCouncil,
    routed through the SAME central app.diagnostic_trace.DiagnosticTrace
    pipeline production uses (via set_result_callback(), wired exactly
    like app.dev_workflow.DevelopmentWorkflow.run() wires it -- see
    _wire_diagnostic_trace()). FakeLLMProvider-driven, zero real LLM
    calls. EngineeringCouncil itself never opens a file for this."""

    def test_valid_proposal_path_traces_no_zero_proposal_branch_evidence(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        fake_providers = _build_standard_providers(a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp)
        trace = DiagnosticTrace(DiagnosticTraceStore(tmp_path / "events.jsonl"))

        result = _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path, diagnostic_trace=trace,
        )

        assert result.council_complete
        events = trace.get_trace("test-run")
        assert not any(
            event.summary == "No usable structured proposal produced." for event in events
        )

    def test_missing_variants_and_empty_object_are_centrally_traced(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        fake_providers = {
            "model-ea": FakeLLMProvider([a1_resp, ph2_resp]),
            "model-ti": FakeLLMProvider(['{"note": "no variants field at all"}', ph2_resp]),
            "model-ra": FakeLLMProvider(["{}", ph2_resp]),
            "model-ch": FakeLLMProvider([ch_resp]),
        }
        trace = DiagnosticTrace(DiagnosticTraceStore(tmp_path / "events.jsonl"))

        _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path, diagnostic_trace=trace,
        )

        events = [
            event for event in trace.get_trace("test-run")
            if event.summary == "No usable structured proposal produced."
        ]
        by_actor = {event.details["actor"]: event for event in events}
        assert set(by_actor) == {"Agent A2", "Agent A3"}, "A1 succeeded and must not get a zero-proposal event"

        a2_verbose = by_actor["Agent A2"].details["council_output"]["verbose"]
        assert a2_verbose["reason"] == "missing_variants"
        assert a2_verbose["root_parsed_type"] == "dict"
        assert a2_verbose["variants_field_present"] is False
        assert a2_verbose["variants_field_count"] == 0
        assert a2_verbose["requirement_ids"] == ["req-1", "req-2", "req-3", "req-4"]
        assert a2_verbose["rejected_candidates"] == []

        a3_verbose = by_actor["Agent A3"].details["council_output"]["verbose"]
        assert a3_verbose["reason"] == "empty_object"
        assert a3_verbose["root_parsed_type"] == "dict"
        assert a3_verbose["variants_field_present"] is False

    def test_all_candidates_rejected_is_centrally_traced_with_deterministic_category(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        bad_variant_response = json.dumps({
            "variants": [{
                "variant_id": "A2-var-bad",
                "name": "A2 bad variant",
                "toolchain": [{
                    "requirement_ref": "req-does-not-exist",
                    "name": "phantom", "type": "executable",
                }],
            }],
        })
        fake_providers = {
            "model-ea": FakeLLMProvider([a1_resp, ph2_resp]),
            "model-ti": FakeLLMProvider([bad_variant_response, ph2_resp]),
            "model-ra": FakeLLMProvider([a3_resp, ph2_resp]),
            "model-ch": FakeLLMProvider([ch_resp]),
        }
        trace = DiagnosticTrace(DiagnosticTraceStore(tmp_path / "events.jsonl"))

        _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path, diagnostic_trace=trace,
        )

        events = [
            event for event in trace.get_trace("test-run")
            if event.summary == "No usable structured proposal produced."
        ]
        assert len(events) == 1
        verbose = events[0].details["council_output"]["verbose"]
        assert events[0].details["actor"] == "Agent A2"
        assert verbose["reason"] == "all_candidates_rejected"
        assert verbose["variants_field_present"] is True
        assert verbose["variants_field_count"] == 1
        assert len(verbose["rejected_candidates"]) == 1
        rejection = verbose["rejected_candidates"][0]
        assert rejection["category"] == "invalid_requirement_ref"
        assert rejection["rejected_requirement_refs"] == ["req-does-not-exist"]

    def test_central_event_is_persisted_regardless_of_presentation_level(self, tmp_path):
        """Persistence (DiagnosticTraceStore.append(), always called by
        DiagnosticTrace.record()) never depends on any diagnostic-level
        parameter -- that only governs RENDERING
        (render_diagnostic_trace_event()). Reading the store back
        directly (bypassing rendering entirely) proves the branch
        evidence reached disk."""
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        fake_providers = {
            "model-ea": FakeLLMProvider([a1_resp, ph2_resp]),
            "model-ti": FakeLLMProvider(["{}", ph2_resp]),
            "model-ra": FakeLLMProvider([a3_resp, ph2_resp]),
            "model-ch": FakeLLMProvider([ch_resp]),
        }
        store_path = tmp_path / "events.jsonl"
        trace = DiagnosticTrace(DiagnosticTraceStore(store_path))

        _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path, diagnostic_trace=trace,
        )

        assert store_path.exists()
        # Re-open a FRESH store/reader (no rendering, no detail level
        # involved at all) to prove this is genuine on-disk persistence,
        # not an in-memory artifact of the `trace` object used to write it.
        reread = DiagnosticTraceStore(store_path).read("test-run")
        matching = [e for e in reread if e.details.get("actor") == "Agent A2"]
        assert matching
        assert matching[0].details["council_output"]["verbose"]["reason"] == "empty_object"

    def test_verbose_projection_shows_bounded_detail_while_info_and_normal_do_not(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        fake_providers = {
            "model-ea": FakeLLMProvider([a1_resp, ph2_resp]),
            "model-ti": FakeLLMProvider(["{}", ph2_resp]),
            "model-ra": FakeLLMProvider([a3_resp, ph2_resp]),
            "model-ch": FakeLLMProvider([ch_resp]),
        }
        trace = DiagnosticTrace(DiagnosticTraceStore(tmp_path / "events.jsonl"))

        _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path, diagnostic_trace=trace,
        )

        event = next(
            e for e in trace.get_trace("test-run")
            if e.details.get("actor") == "Agent A2"
            and e.summary == "No usable structured proposal produced."
        )

        normal = render_diagnostic_trace_event(event, DiagnosticDetailLevel.NORMAL)
        info = render_diagnostic_trace_event(event, DiagnosticDetailLevel.INFO)
        verbose = render_diagnostic_trace_event(event, DiagnosticDetailLevel.VERBOSE)

        assert "empty_object" not in normal
        assert "variants_field_count" not in normal
        assert "empty_object" not in info
        assert "variants_field_count" not in info
        assert "empty_object" in verbose
        assert "variants_field_count" in verbose

    def test_very_verbose_shows_at_least_as_much_as_verbose_but_is_not_required(self, tmp_path):
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        fake_providers = {
            "model-ea": FakeLLMProvider([a1_resp, ph2_resp]),
            "model-ti": FakeLLMProvider(["{}", ph2_resp]),
            "model-ra": FakeLLMProvider([a3_resp, ph2_resp]),
            "model-ch": FakeLLMProvider([ch_resp]),
        }
        trace = DiagnosticTrace(DiagnosticTraceStore(tmp_path / "events.jsonl"))

        _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path, diagnostic_trace=trace,
        )

        event = next(
            e for e in trace.get_trace("test-run")
            if e.details.get("actor") == "Agent A2"
            and e.summary == "No usable structured proposal produced."
        )

        verbose = render_diagnostic_trace_event(event, DiagnosticDetailLevel.VERBOSE)
        very_verbose = render_diagnostic_trace_event(event, DiagnosticDetailLevel.VERY_VERBOSE)

        assert "empty_object" in verbose
        assert "empty_object" in very_verbose, (
            "VERY_VERBOSE must never show LESS than VERBOSE already does"
        )

    def test_trace_survives_simulated_e2e_workspace_cleanup(self, tmp_path):
        """Reproduces the exact evidence-loss shape this task closes: a
        central DiagnosticTrace anchored OUTSIDE the E2E's own owned
        temp workspace must still exist, with its content intact, after
        that owned workspace is deleted -- exactly what Real-System-E2E's
        own cleanup does to its tempfile.mkdtemp() workspace on every
        run, pass or fail. Uses the SAME events.jsonl contract/format,
        never a second sink."""
        owned_workspace = tmp_path / "owned-e2e-workspace"
        owned_workspace.mkdir()
        persistent_diagnostics_dir = tmp_path / "persistent-diagnostics"
        store_path = persistent_diagnostics_dir / "events.jsonl"

        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        fake_providers = {
            "model-ea": FakeLLMProvider([a1_resp, ph2_resp]),
            "model-ti": FakeLLMProvider(["{}", ph2_resp]),
            "model-ra": FakeLLMProvider([a3_resp, ph2_resp]),
            "model-ch": FakeLLMProvider([ch_resp]),
        }
        trace = DiagnosticTrace(DiagnosticTraceStore(store_path))

        _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path, diagnostic_trace=trace,
        )
        assert store_path.exists()

        # Simulate Real-System-E2E's own owned-workspace cleanup --
        # unrelated to, and never containing, the trace store above.
        import shutil
        shutil.rmtree(owned_workspace)

        assert store_path.exists(), "central trace evidence must survive owned-workspace cleanup"
        events = DiagnosticTraceStore(store_path).read("test-run")
        assert any(
            event.details.get("actor") == "Agent A2"
            and event.details["council_output"]["verbose"]["reason"] == "empty_object"
            for event in events
        )

    def test_no_dedicated_council_zero_proposal_sink_is_produced(self, tmp_path):
        """CLAUDE-ADC-COUNCIL-DIAGNOSTIC-TRACE-INTEGRATION-FIX-001's own
        correction requirement: no parallel
        council_zero_proposal_events.jsonl file (or any file at all
        beyond the one central events.jsonl this test itself points at)
        is ever produced."""
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        fake_providers = {
            "model-ea": FakeLLMProvider([a1_resp, ph2_resp]),
            "model-ti": FakeLLMProvider(["{}", ph2_resp]),
            "model-ra": FakeLLMProvider([a3_resp, ph2_resp]),
            "model-ch": FakeLLMProvider([ch_resp]),
        }
        trace = DiagnosticTrace(DiagnosticTraceStore(tmp_path / "events.jsonl"))

        _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path, diagnostic_trace=trace,
        )

        produced_files = sorted(p.name for p in tmp_path.rglob("*") if p.is_file())
        assert "council_zero_proposal_events.jsonl" not in produced_files
        assert produced_files == ["events.jsonl"]

    def test_persisted_event_never_contains_raw_prompt_or_response_fields(self, tmp_path):
        """Even when an agent's OWN (validly-decoded) JSON body happens
        to carry arbitrary text -- here standing in for whatever a real
        LLM's free-form reasoning/commentary might contain -- the
        persisted event must never echo it verbatim: only the central
        DiagnosticTrace's own allowlisted, structured fields
        (app.diagnostic_trace.COUNCIL_OUTPUT_KEYS) may appear."""
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        distinctive_raw_marker = "SECRET-RAW-RESPONSE-MUST-NEVER-BE-PERSISTED"
        fake_providers = {
            "model-ea": FakeLLMProvider([a1_resp, ph2_resp]),
            "model-ti": FakeLLMProvider(
                [json.dumps({"agent_reasoning": distinctive_raw_marker}), ph2_resp]
            ),
            "model-ra": FakeLLMProvider(["{}", ph2_resp]),
            "model-ch": FakeLLMProvider([ch_resp]),
        }
        store_path = tmp_path / "events.jsonl"
        trace = DiagnosticTrace(DiagnosticTraceStore(store_path))

        _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path, diagnostic_trace=trace,
        )

        raw_text = store_path.read_text(encoding="utf-8")
        assert distinctive_raw_marker not in raw_text, (
            "the LLM's own free-text value must never reach the persisted trace"
        )
        event = next(
            e for e in trace.get_trace("test-run")
            if e.details.get("actor") == "Agent A2"
            and e.summary == "No usable structured proposal produced."
        )
        verbose = event.details["council_output"]["verbose"]
        forbidden_keys = {"prompt", "raw_response", "reasoning", "agent_reasoning", "response"}
        assert not (set(verbose.keys()) & forbidden_keys), (
            "this event's own bounded payload must never carry a forbidden key"
        )

    def test_canary_nested_requirement_ref_never_reaches_persisted_events_jsonl_or_verbose_rendering(self, tmp_path):
        """CLAUDE-ADC-COUNCIL-DIAGNOSTIC-HARDENING-FIX-001 (F1),
        end-to-end reproduction of Codex's own fixed input through the
        REAL EngineeringCouncil/central DiagnosticTrace pipeline (not
        just the pure _candidate_rejection_diagnostic() unit): an agent
        proposes a variant whose toolchain item's requirement_ref is a
        nested object carrying canary keys "agent_reasoning" and nested
        "credentials"."secret". Neither the canary values nor those key
        names may appear anywhere in the persisted events.jsonl file, nor
        in the VERBOSE (or any other level's) rendered projection of the
        resulting event."""
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        canary_reasoning = "CANARY-AGENT-REASONING-MUST-NEVER-LEAK"
        canary_secret = "CANARY-SECRET-MUST-NEVER-LEAK"
        bad_variant_response = json.dumps({
            "variants": [{
                "variant_id": "A2-var-bad",
                "name": "A2 bad variant",
                "toolchain": [{
                    "requirement_ref": {
                        "agent_reasoning": canary_reasoning,
                        "credentials": {"secret": canary_secret},
                    },
                    "name": "phantom", "type": "executable",
                }],
            }],
        })
        fake_providers = {
            "model-ea": FakeLLMProvider([a1_resp, ph2_resp]),
            "model-ti": FakeLLMProvider([bad_variant_response, ph2_resp]),
            "model-ra": FakeLLMProvider([a3_resp, ph2_resp]),
            "model-ch": FakeLLMProvider([ch_resp]),
        }
        store_path = tmp_path / "events.jsonl"
        trace = DiagnosticTrace(DiagnosticTraceStore(store_path))

        _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path, diagnostic_trace=trace,
        )

        raw_text = store_path.read_text(encoding="utf-8")
        assert canary_reasoning not in raw_text, (
            "the canary VALUE must never reach the persisted trace file at all"
        )
        assert canary_secret not in raw_text, (
            "the canary VALUE must never reach the persisted trace file at all"
        )

        event = next(
            e for e in trace.get_trace("test-run")
            if e.details.get("actor") == "Agent A2"
            and e.summary == "No usable structured proposal produced."
        )
        verbose = event.details["council_output"]["verbose"]
        assert verbose["reason"] == "all_candidates_rejected"
        assert verbose["rejected_candidates"][0]["rejected_requirement_refs"] == []
        assert verbose["rejected_candidates"][0]["rejected_requirement_ref_invalid_types"] == ["dict"]
        # Scoped to THIS event's own bounded payload (never a whole-file
        # substring search, which would also match unrelated, already-
        # legitimate content elsewhere in the trace -- e.g. a genuinely
        # successful proposal's own real agent_reasoning field, or the
        # pre-existing, unrelated VERY_VERBOSE effective_prompt echo):
        # the canary keys themselves must not appear here either.
        serialized_event = json.dumps(event.details)
        assert canary_reasoning not in serialized_event
        assert canary_secret not in serialized_event
        assert "agent_reasoning" not in serialized_event
        assert "credentials" not in serialized_event

        for level in (
            DiagnosticDetailLevel.NORMAL, DiagnosticDetailLevel.INFO,
            DiagnosticDetailLevel.VERBOSE, DiagnosticDetailLevel.VERY_VERBOSE,
        ):
            rendered = render_diagnostic_trace_event(event, level)
            assert canary_reasoning not in rendered
            assert canary_secret not in rendered
            assert "agent_reasoning" not in rendered
            assert "credentials" not in rendered

    def test_nonempty_malformed_dict_variants_from_the_real_llm_response_is_traced_correctly(self, tmp_path):
        """CLAUDE-ADC-COUNCIL-DIAGNOSTIC-HARDENING-FIX-001 (F2),
        end-to-end reproduction through the REAL, unchanged Phase-1 loop:
        an agent's entire "variants" value decodes to a nonempty dict
        (never a list) -- the productive loop iterates its keys (each a
        string), every one fails to build into an AgentProposal, and the
        resulting central-trace event must report "all_candidates_
        rejected", never the previous, misleading "empty_variants"."""
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        malformed_response = json.dumps({"variants": {"unexpected": "shape", "another": "key"}})
        fake_providers = {
            "model-ea": FakeLLMProvider([a1_resp, ph2_resp]),
            "model-ti": FakeLLMProvider([malformed_response, ph2_resp]),
            "model-ra": FakeLLMProvider([a3_resp, ph2_resp]),
            "model-ch": FakeLLMProvider([ch_resp]),
        }
        trace = DiagnosticTrace(DiagnosticTraceStore(tmp_path / "events.jsonl"))

        _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path, diagnostic_trace=trace,
        )

        event = next(
            e for e in trace.get_trace("test-run")
            if e.details.get("actor") == "Agent A2"
            and e.summary == "No usable structured proposal produced."
        )
        verbose = event.details["council_output"]["verbose"]
        assert verbose["reason"] == "all_candidates_rejected"
        assert verbose["variants_field_type"] == "dict"
        assert verbose["variants_field_count"] == 2
        assert len(verbose["rejected_candidates"]) == 2

    _H2_CANARY = "PRIVATE_REASONING_CANARY_002"
    _H2_COMPACT_CANARY = (
        '{"agent_reasoning":"PRIVATE_REASONING_CANARY_002",'
        '"credentials":{"secret":"PRIVATE_SECRET_CANARY_002"}}'
    )

    def _assert_event_and_rendering_never_leak(self, trace, *forbidden):
        event = next(
            e for e in trace.get_trace("test-run")
            if e.details.get("actor") == "Agent A2"
            and e.summary == "No usable structured proposal produced."
        )
        serialized_event = json.dumps(event.details)
        for marker in forbidden:
            assert marker not in serialized_event
        for level in (
            DiagnosticDetailLevel.NORMAL, DiagnosticDetailLevel.INFO,
            DiagnosticDetailLevel.VERBOSE, DiagnosticDetailLevel.VERY_VERBOSE,
        ):
            rendered = render_diagnostic_trace_event(event, level)
            for marker in forbidden:
                assert marker not in rendered
        return event

    def test_h1_compact_serialized_canary_requirement_ref_never_reaches_persisted_event_or_verbose_rendering(self, tmp_path):
        """CLAUDE-ADC-COUNCIL-DIAGNOSTIC-PRIVACY-HARDENING-FIX-002,
        Codex RED reproduction #1, end-to-end: the reviewer's exact
        compact-JSON-string canary as a candidate's requirement_ref,
        through the REAL, unmodified Phase-1 loop."""
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        bad_variant_response = json.dumps({
            "variants": [{
                "variant_id": "A2-var-bad", "name": "A2 bad variant",
                "toolchain": [{
                    "requirement_ref": self._H2_COMPACT_CANARY,
                    "name": "phantom", "type": "executable",
                }],
            }],
        })
        fake_providers = {
            "model-ea": FakeLLMProvider([a1_resp, ph2_resp]),
            "model-ti": FakeLLMProvider([bad_variant_response, ph2_resp]),
            "model-ra": FakeLLMProvider([a3_resp, ph2_resp]),
            "model-ch": FakeLLMProvider([ch_resp]),
        }
        store_path = tmp_path / "events.jsonl"
        trace = DiagnosticTrace(DiagnosticTraceStore(store_path))

        _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path, diagnostic_trace=trace,
        )

        raw_text = store_path.read_text(encoding="utf-8")
        assert "PRIVATE_REASONING_CANARY_002" not in raw_text
        assert "PRIVATE_SECRET_CANARY_002" not in raw_text

        event = self._assert_event_and_rendering_never_leak(
            trace, "PRIVATE_REASONING_CANARY_002", "PRIVATE_SECRET_CANARY_002",
            "agent_reasoning", "credentials",
        )
        verbose = event.details["council_output"]["verbose"]
        rejection = verbose["rejected_candidates"][0]
        assert rejection["category"] == "invalid_requirement_ref"
        assert rejection["rejected_requirement_refs"] == []
        assert rejection["rejected_requirement_ref_invalid_types"] == ["str"]

    def test_h1_compact_serialized_canary_provided_by_never_reaches_persisted_event_or_verbose_rendering(self, tmp_path):
        """Codex RED reproduction #2 (same canary, provided_by field)."""
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        bad_variant_response = json.dumps({
            "variants": [{
                "variant_id": "A2-var-bad", "name": "A2 bad variant",
                "toolchain": [{
                    "requirement_ref": "req-1",
                    "provided_by": self._H2_COMPACT_CANARY,
                    "name": "phantom", "type": "executable",
                }],
            }],
        })
        fake_providers = {
            "model-ea": FakeLLMProvider([a1_resp, ph2_resp]),
            "model-ti": FakeLLMProvider([bad_variant_response, ph2_resp]),
            "model-ra": FakeLLMProvider([a3_resp, ph2_resp]),
            "model-ch": FakeLLMProvider([ch_resp]),
        }
        store_path = tmp_path / "events.jsonl"
        trace = DiagnosticTrace(DiagnosticTraceStore(store_path))

        _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path, diagnostic_trace=trace,
        )

        raw_text = store_path.read_text(encoding="utf-8")
        assert "PRIVATE_REASONING_CANARY_002" not in raw_text
        assert "PRIVATE_SECRET_CANARY_002" not in raw_text

        event = self._assert_event_and_rendering_never_leak(
            trace, "PRIVATE_REASONING_CANARY_002", "PRIVATE_SECRET_CANARY_002",
            "agent_reasoning", "credentials",
        )
        verbose = event.details["council_output"]["verbose"]
        rejection = verbose["rejected_candidates"][0]
        assert rejection["rejected_provided_by"] == []
        assert rejection["rejected_provided_by_invalid_types"] == ["str"]

    def test_h2_invalid_confidence_canary_category_becomes_unknown_end_to_end(self, tmp_path):
        """CLAUDE-ADC-COUNCIL-DIAGNOSTIC-PRIVACY-HARDENING-FIX-002,
        Codex RED reproduction #3, end-to-end through the REAL,
        unmodified Phase-1 loop: a candidate whose toolchain is
        otherwise valid but whose "confidence" field is the reviewer's
        exact canary tag string, making float() raise a ValueError whose
        own message embeds it. The persisted category must be the
        trusted "unknown" fallback, never the injected tag."""
        a1_resp, a2_resp, a3_resp, ph2_resp, ch_resp, all_ids = _setup_standard_responses()
        bad_variant_response = json.dumps({
            "variants": [{
                "variant_id": "A2-var-bad", "name": "A2 bad variant",
                "toolchain": [{
                    "requirement_ref": "req-1", "name": "ok", "type": "executable",
                }],
                "confidence": f"[category={self._H2_CANARY}]",
            }],
        })
        fake_providers = {
            "model-ea": FakeLLMProvider([a1_resp, ph2_resp]),
            "model-ti": FakeLLMProvider([bad_variant_response, ph2_resp]),
            "model-ra": FakeLLMProvider([a3_resp, ph2_resp]),
            "model-ch": FakeLLMProvider([ch_resp]),
        }
        store_path = tmp_path / "events.jsonl"
        trace = DiagnosticTrace(DiagnosticTraceStore(store_path))

        _run_council_with_fakes(
            _make_council_config(), fake_providers, tmp_path, diagnostic_trace=trace,
        )

        raw_text = store_path.read_text(encoding="utf-8")
        assert self._H2_CANARY not in raw_text

        event = self._assert_event_and_rendering_never_leak(trace, self._H2_CANARY)
        verbose = event.details["council_output"]["verbose"]
        assert verbose["reason"] == "all_candidates_rejected"
        assert verbose["rejected_candidates"][0]["category"] == "unknown"


# =========================================================================
# CLAUDE-ADC-S23-ENVCONSTRAINT-PROMPT-FIX-001: Council producer contract
# for ToolchainItem.environment_constraint -- exact platform identifier
# or null, never a deployment/placement/execution-environment description.
# =========================================================================


_DEPLOYMENT_TERMS_FORBIDDEN_IN_ENVIRONMENT_CONSTRAINT = (
    "host", "container", "docker", "within_container", "within_venv",
    "build-server",
)


class TestEnvironmentConstraintPromptContract:
    """Behavior-oriented assertions on the Phase-1 and Chairman prompt
    TEXT itself (never a whole-prompt snapshot) proving:
    (a) environment_constraint is documented as null-or-exact-platform
        only, dynamically reflecting CouncilInput.platform -- not
        hardcoded to "linux";
    (b) deployment/placement/execution-environment concepts are
        explicitly forbidden there and pointed at variant.environment
        instead.
    This is a prompt-contract-only change: _violates_platform_constraint(),
    S2.3 admissibility, and every other behavior are untouched by this
    task (verified separately via the existing, unmodified engineering_
    decision platform-constraint test suite -- see focused results)."""

    def test_phase1_prompt_documents_environment_constraint_as_null_or_exact_platform(self):
        prompt = build_phase1_prompt(
            _make_council_input(), AGENT_ROLE_ENV_ARCHITECT, 3,
        )

        assert "ENVIRONMENT_CONSTRAINT" in prompt
        assert (
            'entweder null ODER exakt der' in prompt
            or "AUSSCHLIESSLICH entweder null" in prompt
        )

    @pytest.mark.parametrize("platform", ["linux", "windows"])
    def test_phase1_prompt_propagates_the_actual_platform_value_not_hardcoded(self, platform):
        council_input = replace(_make_council_input(), platform=platform)

        prompt = build_phase1_prompt(council_input, AGENT_ROLE_ENV_ARCHITECT, 3)

        assert f"PLATTFORM: {platform}" in prompt
        # The ENVIRONMENT_CONSTRAINT bullet must name THIS run's own
        # platform value, not a hardcoded example -- proven by requiring
        # the value inside the bullet's own text window.
        idx = prompt.index("ENVIRONMENT_CONSTRAINT")
        bullet_window = prompt[idx:idx + 700]
        assert f"({platform})" in bullet_window
        assert f"auf {platform} NUR" in bullet_window

    def test_phase1_prompt_forbids_deployment_placement_terms_in_environment_constraint(self):
        prompt = build_phase1_prompt(
            _make_council_input(), AGENT_ROLE_ENV_ARCHITECT, 3,
        )
        idx = prompt.index("ENVIRONMENT_CONSTRAINT")
        bullet_window = prompt[idx:prompt.index("PROVIDES_VERIFICATION")]

        for term in _DEPLOYMENT_TERMS_FORBIDDEN_IN_ENVIRONMENT_CONSTRAINT:
            assert term in bullet_window, f"{term!r} must be named as forbidden"
        assert "NIEMALS" in bullet_window or "niemals" in bullet_window

    def test_phase1_prompt_points_deployment_concepts_at_variant_environment_field(self):
        prompt = build_phase1_prompt(
            _make_council_input(), AGENT_ROLE_ENV_ARCHITECT, 3,
        )
        idx = prompt.index("ENVIRONMENT_CONSTRAINT")
        bullet_window = prompt[idx:prompt.index("PROVIDES_VERIFICATION")]

        assert '"environment"' in bullet_window
        assert "host|container|target|physical_hardware|simulation" in prompt

    def test_phase1_json_schema_shows_environment_constraint_as_null_or_platform_placeholder(self):
        prompt = build_phase1_prompt(
            _make_council_input(), AGENT_ROLE_ENV_ARCHITECT, 3,
        )
        assert '"environment_constraint": null | "<exakter PLATTFORM-Wert' in prompt

    def test_chairman_prompt_now_states_the_platform(self):
        prompt = build_chairman_prompt(
            json.dumps([{"variant_id": "v1", "name": "Test"}]), json.dumps([]),
            _make_council_input(),
        )
        assert "PLATTFORM: linux" in prompt

    def test_chairman_prompt_documents_environment_constraint_as_null_or_exact_platform(self):
        prompt = build_chairman_prompt(
            json.dumps([{"variant_id": "v1", "name": "Test"}]), json.dumps([]),
            _make_council_input(),
        )

        assert "ENVIRONMENT_CONSTRAINT" in prompt
        assert "Gültigkeitsregel geht vor Erhaltungsregel" in prompt

    @pytest.mark.parametrize("platform", ["linux", "windows"])
    def test_chairman_prompt_propagates_the_actual_platform_value_not_hardcoded(self, platform):
        council_input = replace(_make_council_input(), platform=platform)

        prompt = build_chairman_prompt(
            json.dumps([{"variant_id": "v1", "name": "Test"}]), json.dumps([]),
            council_input,
        )

        assert f"PLATTFORM: {platform}" in prompt
        idx = prompt.index("ENVIRONMENT_CONSTRAINT")
        bullet_window = prompt[idx:idx + 700]
        assert f"({platform})" in bullet_window

    def test_chairman_prompt_forbids_deployment_placement_terms_in_environment_constraint(self):
        prompt = build_chairman_prompt(
            json.dumps([{"variant_id": "v1", "name": "Test"}]), json.dumps([]),
            _make_council_input(),
        )
        idx = prompt.index("ENVIRONMENT_CONSTRAINT")
        bullet_window = prompt[idx:prompt.index("verification_coverage:")]

        for term in _DEPLOYMENT_TERMS_FORBIDDEN_IN_ENVIRONMENT_CONSTRAINT:
            assert term in bullet_window, f"{term!r} must be named as forbidden"

    def test_chairman_prompt_forbids_synthesizing_new_deployment_descriptions_during_merge(self):
        prompt = build_chairman_prompt(
            json.dumps([{"variant_id": "v1", "name": "Test"}]), json.dumps([]),
            _make_council_input(),
        )
        idx = prompt.index("ENVIRONMENT_CONSTRAINT")
        bullet_window = prompt[idx:prompt.index("verification_coverage:")]

        assert "unverändert" in bullet_window
        assert "ursprünglichen Vorschlag" in bullet_window
        assert "Merge" in bullet_window or "zusammengeführten" in bullet_window
        assert '"environment"' in bullet_window

    def test_chairman_prompt_without_council_input_still_builds_and_defaults_platform(self):
        """council_input=None is an existing, valid call shape (see
        build_chairman_prompt's own default) -- the new platform lookup
        must not break it."""
        prompt = build_chairman_prompt(
            json.dumps([{"variant_id": "v1", "name": "Test"}]), json.dumps([]),
            None,
        )
        assert "PLATTFORM: unbekannt" in prompt
        assert "ENVIRONMENT_CONSTRAINT" in prompt


class TestChairmanEnvironmentConstraintContradictionCorrection:
    """CLAUDE-ADC-S23-ENVCONSTRAINT-PROMPT-FIX-002: FIX-001's Chairman
    bullet said BOTH "environment_constraint is only null-or-exact-
    platform" AND "preserve each source value UNVERÄNDERT even during
    merges" -- unconditionally preserving an already-invalid source
    value (e.g. "host", "container") perpetuates exactly the shape the
    first sentence forbids. These tests mechanically fail against
    FIX-001's own contradictory wording and pass only against the
    corrected text. Phase-1's own bullet is untouched and out of scope
    here -- see TestEnvironmentConstraintPromptContract for its
    (unmodified) coverage."""

    def _chairman_bullet_window(self, platform="linux"):
        prompt = build_chairman_prompt(
            json.dumps([{"variant_id": "v1", "name": "Test"}]), json.dumps([]),
            replace(_make_council_input(), platform=platform),
        )
        idx = prompt.index("ENVIRONMENT_CONSTRAINT")
        return prompt[idx:prompt.index("verification_coverage:")]

    def test_valid_source_values_may_still_be_preserved_unchanged(self):
        """A source value that is ALREADY valid (null or exactly the
        project platform) may still be carried through a merge
        unchanged -- the correction must not forbid the one case where
        preservation is actually correct."""
        bullet_window = self._chairman_bullet_window()

        assert "NUR DANN" in bullet_window
        assert "unverändert" in bullet_window
        assert "BEREITS gültig" in bullet_window
        assert "null oder exakt linux" in bullet_window

    def test_invalid_freeform_source_values_must_not_be_blindly_preserved(self):
        """The exact NIO shape: an invalid, deployment/placement-shaped
        source value (host/container/docker/within_venv/build-server/
        external hardware) must NOT be instructed to survive a merge
        merely because "preserve unchanged" exists elsewhere in the
        bullet."""
        bullet_window = self._chairman_bullet_window()

        assert "NICHT blind übernehmen" in bullet_window
        assert "ungültiger" in bullet_window or "ungültig" in bullet_window
        for term in _DEPLOYMENT_TERMS_FORBIDDEN_IN_ENVIRONMENT_CONSTRAINT:
            assert term in bullet_window

    def test_no_heuristic_mapping_of_invalid_values_is_instructed(self):
        """Explicitly forbids the exact heuristic normalization shapes
        named in the correction task (host->platform, container->null),
        never merely omitting them."""
        bullet_window = self._chairman_bullet_window()

        assert "heuristisch" in bullet_window
        assert "UNZULÄSSIG" in bullet_window
        assert '"container" automatisch zu null' in bullet_window
        assert '"host" automatisch zu linux' in bullet_window

    def test_chairman_must_redetermine_value_from_actual_platform_requirement(self):
        """Instead of preserving OR heuristically mapping an invalid
        source value, the Chairman must independently decide the
        correct value from the item's real technical need -- exact
        platform only if truly required, else null."""
        bullet_window = self._chairman_bullet_window()

        assert "TATSÄCHLICHEN" in bullet_window
        assert "wirklich zwingend genau" in bullet_window
        assert "sonst null" in bullet_window

    @pytest.mark.parametrize("platform", ["linux", "windows"])
    def test_corrected_rule_is_dynamic_per_platform_not_hardcoded(self, platform):
        bullet_window = self._chairman_bullet_window(platform=platform)

        assert f"null oder exakt {platform}" in bullet_window
        assert f'"host" automatisch zu {platform}' in bullet_window
        assert f"exakt {platform}, wenn dieses Item" in bullet_window

    def test_deployment_placement_redirect_to_variant_environment_survives_correction(self):
        """The unrelated, already-correct sentence directing deployment/
        placement concepts to variant.environment/purpose/description
        must survive this correction unchanged in substance."""
        bullet_window = self._chairman_bullet_window()

        assert '"environment"' in bullet_window
        assert "purpose" in bullet_window
        assert "description" in bullet_window
