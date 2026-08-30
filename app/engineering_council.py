"""Multi-KI Engineering Council — Orchestrator.

Runs three phases with a total of 7 separate LLM calls:
  Phase 1: A1, A2, A3 in parallel → AgentProposals (3 calls, isolated)
  Phase 2: A1, A2, A3 in parallel → AgentVoteSets    (3 calls, isolated votes)
  Phase 3: Chairman sequentially → CouncilResult      (1 call)

The Council is platform-neutral.  It contains no ESP32-, ESPHome-, or
any other stack-specific logic.  All stack awareness comes from the
CouncilInput provided by the caller.
"""

from __future__ import annotations

import json
import uuid
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.ai_config import CouncilAgentConfig, CouncilConfig
from app.ai_requirement_discovery import LLMProvider
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
    build_phase1_prompt,
    build_phase2_review_prompt,
    build_chairman_prompt,
)
from app.llm_provider_factory import create_council_provider
from app.logger import get_logger
from app.secret_resolver import SecretResolver

logger = get_logger("council")

AGENT_ROLES = {
    "A1": "environment_architect",
    "A2": "toolchain_integrator",
    "A3": "risk_assessor",
}

PHASE1_ROLE_PROMPTS = {
    "environment_architect": AGENT_ROLE_ENV_ARCHITECT,
    "toolchain_integrator": AGENT_ROLE_TOOLCHAIN,
    "risk_assessor": AGENT_ROLE_RISK,
}

PHASE2_ROLE_PROMPTS = {
    "environment_architect": AGENT_ROLE_ENV_ARCHITECT_REVIEW,
    "toolchain_integrator": AGENT_ROLE_TOOLCHAIN_REVIEW,
    "risk_assessor": AGENT_ROLE_RISK_REVIEW,
}

_AGENT_ID_TO_CONFIG_KEY = {
    "A1": "environment_architect",
    "A2": "toolchain_integrator",
    "A3": "risk_assessor",
}

_MAX_RETRIES = 1  # 1 initial try + 1 retry = 2 total


@dataclass
class _AgentTask:
    agent_id: str
    role: str
    config: CouncilAgentConfig
    prompt: str
    phase: str
    started_at: datetime


@dataclass
class _AgentResult:
    agent_id: str
    success: bool
    parsed: dict[str, Any] | None = None
    raw_response: str = ""
    error: str | None = None


def _get_agent_config(council_config: CouncilConfig, agent_id: str) -> CouncilAgentConfig:
    role = _AGENT_ID_TO_CONFIG_KEY[agent_id]
    return getattr(council_config, role)


class EngineeringCouncil:
    """Multi-Agent Engineering Council with 3 phases and 7 LLM calls.

    Phase 1: 3 independent agents propose variants (parallel, isolated).
    Phase 2: 3 agents cross-review all proposals (parallel, votes isolated).
    Phase 3: Chairman synthesises CouncilResult (1 call).

    The Council NEVER performs installations, activates hardware, or
    executes destructive actions.  It ONLY produces data.
    """

    def __init__(
        self,
        council_config: CouncilConfig,
        secret_resolver: SecretResolver,
        trace_dir: Path | None = None,
    ):
        if not council_config.enabled:
            raise ValueError("CouncilConfig.enabled must be True")
        self._config = council_config
        self._secret_resolver = secret_resolver
        self._trace_dir = trace_dir
        self._call_records: list[AgentCallRecord] = []
        self._run_id: str = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(self, council_input: CouncilInput) -> CouncilResult:
        """Run the full multi-agent council and return the synthesised result.

        Raises:
            CouncilFailedError: If too few agents succeeded to produce
                a meaningful result.
        """
        self._run_id = f"council-{uuid.uuid4().hex[:12]}"
        self._call_records.clear()
        started = datetime.now()

        phase1_start = time.monotonic()
        proposal_set = self._phase1_independent_proposals(council_input)
        phase1_ms = (time.monotonic() - phase1_start) * 1000
        proposal_set = ProposalSet(
            proposals=proposal_set.proposals,
            phase_duration_ms=phase1_ms,
            agent_errors=proposal_set.agent_errors,
        )

        vote_sets: tuple[AgentVoteSet, ...] = ()
        vote_errors: tuple[str, ...] = ()
        if proposal_set.proposals:
            vote_sets, vote_errors = self._phase2_cross_review(proposal_set)

        chairman_error: str | None = None
        council_result: CouncilResult

        if not proposal_set.proposals:
            chairman_error = "Keine Variantenvorschläge aus Phase 1 — keine Agenten erfolgreich."
            council_result = self._build_empty_result(council_input, chairman_error)
        else:
            try:
                council_result = self._phase3_chairman_synthesis(
                    proposal_set, vote_sets, council_input
                )
            except Exception as exc:
                chairman_error = str(exc)
                council_result = self._build_empty_result(council_input, chairman_error)

        total_errors = list(proposal_set.agent_errors)
        total_errors.extend(vote_errors)
        if chairman_error:
            total_errors.append(f"Chairman: {chairman_error}")

        council_complete = (
            not proposal_set.agent_errors
            and not vote_errors
            and chairman_error is None
            and len(vote_sets) == 3
            and bool(council_result.variants)
        )

        if not council_result.variants and not proposal_set.agent_errors:
            council_result = CouncilResult(
                id=self._run_id,
                project_id=council_input.project_id,
                stack=council_input.detected_stack or "",
                agent_errors=tuple(total_errors),
                chairman_error=chairman_error,
                council_complete=False,
                total_llm_calls=len(self._call_records),
            )

        council_result = CouncilResult(
            id=council_result.id or self._run_id,
            project_id=council_result.project_id or council_input.project_id,
            stack=council_result.stack or council_input.detected_stack or "",
            variants=council_result.variants,
            rejected_variants=council_result.rejected_variants,
            recommendation=council_result.recommendation,
            reasoning=council_result.reasoning,
            merge_decisions=council_result.merge_decisions,
            agent_errors=tuple(total_errors),
            chairman_error=chairman_error,
            council_complete=council_complete,
            total_llm_calls=len(self._call_records),
        )

        if self._trace_dir:
            self._persist_trace(council_input, proposal_set, vote_sets, council_result, started)

        return council_result

    # ------------------------------------------------------------------
    # Phase 1 — Independent Proposals
    # ------------------------------------------------------------------

    def _phase1_independent_proposals(self, council_input: CouncilInput) -> ProposalSet:
        tasks = [
            _AgentTask(
                agent_id=aid,
                role=AGENT_ROLES[aid],
                config=_get_agent_config(self._config, aid),
                prompt=build_phase1_prompt(
                    council_input,
                    PHASE1_ROLE_PROMPTS[AGENT_ROLES[aid]],
                    self._config.max_variants_per_agent,
                ),
                phase="phase1",
                started_at=datetime.now(),
            )
            for aid in ("A1", "A2", "A3")
        ]

        results = self._execute_parallel(tasks, "phase1")

        all_proposals: list[AgentProposal] = []
        agent_errors: list[str] = []

        for res in results:
            if res.success and res.parsed:
                for variant_data in res.parsed.get("variants", []):
                    try:
                        proposal = self._build_proposal_from_dict(
                            res.agent_id, AGENT_ROLES.get(res.agent_id, ""), variant_data, res.raw_response
                        )
                        all_proposals.append(proposal)
                    except Exception as exc:
                        agent_errors.append(f"{res.agent_id}: build proposal failed — {exc}")
            else:
                agent_errors.append(f"{res.agent_id}: {res.error or 'unknown error'}")

        return ProposalSet(
            proposals=tuple(all_proposals),
            agent_errors=tuple(agent_errors),
        )

    def _build_proposal_from_dict(
        self, agent_id: str, agent_role: str, data: dict, raw_response: str
    ) -> AgentProposal:
        toolchain = tuple(
            ToolchainItem(
                requirement_ref=t.get("requirement_ref", ""),
                name=t.get("name", ""),
                type=t.get("type", ""),
                install_method=t.get("install_method"),
                version=t.get("version"),
                purpose=t.get("purpose", ""),
                depends_on=tuple(t.get("depends_on", []) or []),
                state=t.get("state", "needs_install"),
                environment_constraint=t.get("environment_constraint"),
            )
            for t in data.get("toolchain", [])
        )

        return AgentProposal(
            variant_id=data.get("variant_id", f"{agent_id}-var-{uuid.uuid4().hex[:6]}"),
            agent_id=agent_id,
            agent_role=agent_role,
            name=data.get("name", f"{agent_id} Vorschlag"),
            description=data.get("description", ""),
            environment=data.get("environment", "host"),
            hardware_target=data.get("hardware_target"),
            connection=data.get("connection"),
            capabilities=tuple(data.get("capabilities", []) or []),
            toolchain=toolchain,
            advantages=tuple(data.get("advantages", []) or []),
            disadvantages=tuple(data.get("disadvantages", []) or []),
            risks=tuple(data.get("risks", []) or []),
            confidence=float(data.get("confidence", 0.5)),
            feasibility=data.get("feasibility", "medium"),
            verification=data.get("verification", ""),
            test_strategy=data.get("test_strategy"),
            agent_reasoning=data.get("agent_reasoning", ""),
            raw_llm_response=raw_response,
        )

    # ------------------------------------------------------------------
    # Phase 2 — Cross-Review
    # ------------------------------------------------------------------

    def _phase2_cross_review(self, proposal_set: ProposalSet) -> tuple[tuple[AgentVoteSet, ...], tuple[str, ...]]:
        variants_json = json.dumps(
            [
                {
                    "variant_id": p.variant_id,
                    "agent_id": p.agent_id,
                    "agent_role": p.agent_role,
                    "name": p.name,
                    "description": p.description,
                    "environment": p.environment,
                    "hardware_target": p.hardware_target,
                    "connection": p.connection,
                    "capabilities": list(p.capabilities),
                    "toolchain": [
                        {
                            "requirement_ref": t.requirement_ref,
                            "name": t.name,
                            "type": t.type,
                            "install_method": t.install_method,
                            "version": t.version,
                            "purpose": t.purpose,
                            "depends_on": list(t.depends_on),
                            "state": t.state,
                            "environment_constraint": t.environment_constraint,
                        }
                        for t in p.toolchain
                    ],
                    "advantages": list(p.advantages),
                    "disadvantages": list(p.disadvantages),
                    "risks": list(p.risks),
                    "confidence": p.confidence,
                    "feasibility": p.feasibility,
                    "verification": p.verification,
                    "agent_reasoning": p.agent_reasoning,
                }
                for p in proposal_set.proposals
            ],
            indent=2,
            ensure_ascii=False,
        )

        tasks = [
            _AgentTask(
                agent_id=aid,
                role=AGENT_ROLES[aid],
                config=_get_agent_config(self._config, aid),
                prompt=build_phase2_review_prompt(
                    variants_json, PHASE2_ROLE_PROMPTS[AGENT_ROLES[aid]]
                ),
                phase="phase2",
                started_at=datetime.now(),
            )
            for aid in ("A1", "A2", "A3")
        ]

        results = self._execute_parallel(tasks, "phase2")

        vote_sets: list[AgentVoteSet] = []
        vote_errors: list[str] = []
        for res in results:
            if res.success and res.parsed:
                votes = tuple(
                    AgentVote(
                        agent_id=res.agent_id,
                        variant_id=v.get("variant_id", ""),
                        scores=v.get("scores", {}),
                        would_recommend=bool(v.get("would_recommend", False)),
                        reasoning=v.get("reasoning", ""),
                        concerns=tuple(v.get("concerns", []) or []),
                    )
                    for v in res.parsed.get("votes", [])
                )
                vote_sets.append(AgentVoteSet(
                    agent_id=res.agent_id,
                    agent_role=res.parsed.get("agent_role", ""),
                    votes=votes,
                ))
            else:
                vote_errors.append(f"{res.agent_id}: {res.error or 'unknown error'}")

        return tuple(vote_sets), tuple(vote_errors)

    # ------------------------------------------------------------------
    # Phase 3 — Chairman Synthesis
    # ------------------------------------------------------------------

    def _phase3_chairman_synthesis(
        self,
        proposal_set: ProposalSet,
        vote_sets: tuple[AgentVoteSet, ...],
        council_input: CouncilInput,
    ) -> CouncilResult:
        proposals_json = json.dumps(
            [
                {
                    "variant_id": p.variant_id,
                    "agent_id": p.agent_id,
                    "name": p.name,
                    "description": p.description,
                    "environment": p.environment,
                    "hardware_target": p.hardware_target,
                    "connection": p.connection,
                    "capabilities": list(p.capabilities),
                    "toolchain": [
                        {
                            "requirement_ref": t.requirement_ref,
                            "name": t.name,
                            "type": t.type,
                        }
                        for t in p.toolchain
                    ],
                    "advantages": list(p.advantages),
                    "disadvantages": list(p.disadvantages),
                    "risks": list(p.risks),
                }
                for p in proposal_set.proposals
            ],
            indent=2,
            ensure_ascii=False,
        )

        votes_json = json.dumps(
            [
                {
                    "agent_id": vs.agent_id,
                    "agent_role": vs.agent_role,
                    "votes": [
                        {
                            "variant_id": v.variant_id,
                            "scores": v.scores,
                            "would_recommend": v.would_recommend,
                            "reasoning": v.reasoning,
                            "concerns": list(v.concerns),
                        }
                        for v in vs.votes
                    ],
                }
                for vs in vote_sets
            ],
            indent=2,
            ensure_ascii=False,
        )

        prompt = build_chairman_prompt(proposals_json, votes_json, council_input)
        chairman_config = self._config.chairman

        task = _AgentTask(
            agent_id="C", role="chairman",
            config=chairman_config, prompt=prompt,
            phase="phase3", started_at=datetime.now(),
        )

        result = self._run_single_agent(task)

        if not result.success or not result.parsed:
            raise CouncilChairmanError(
                f"Chairman failed: {result.error or 'no parsed output'}"
            )

        return self._parse_chairman_result(result.parsed, council_input)

    def _parse_chairman_result(self, parsed: dict, council_input: CouncilInput) -> CouncilResult:
        variants: list[CouncilVariant] = []
        for v in parsed.get("variants", []):
            variants.append(CouncilVariant(
                id=v.get("id", ""),
                name=v.get("name", ""),
                description=v.get("description", ""),
                origin_agents=tuple(v.get("origin_agents", []) or []),
                merged_from=tuple(v.get("merged_from", []) or []),
                rank=v.get("rank", 0),
                total_score=float(v.get("total_score", 0.0)),
                consensus_level=v.get("consensus_level", "unknown"),
                minority_opinions=tuple(v.get("minority_opinions", []) or []),
                environment=v.get("environment", "host"),
                hardware_target=v.get("hardware_target"),
                connection=v.get("connection"),
                capabilities=tuple(v.get("capabilities", []) or []),
                toolchain=tuple(
                    ToolchainItem(
                        requirement_ref=t.get("requirement_ref", ""),
                        name=t.get("name", ""),
                        type=t.get("type", ""),
                        install_method=t.get("install_method"),
                        version=t.get("version"),
                        purpose=t.get("purpose", ""),
                        depends_on=tuple(t.get("depends_on", []) or []),
                        state=t.get("state", "needs_install"),
                        environment_constraint=t.get("environment_constraint"),
                    )
                    for t in v.get("toolchain", [])
                ),
                advantages=tuple(v.get("advantages", []) or []),
                disadvantages=tuple(v.get("disadvantages", []) or []),
                risks=tuple(v.get("risks", []) or []),
                confidence=float(v.get("confidence", 0.5)),
                feasibility=v.get("feasibility", "medium"),
                verification=v.get("verification", ""),
                test_strategy=v.get("test_strategy"),
            ))

        rejected = tuple(
            CouncilVariant(
                id=rv.get("id", ""),
                name=rv.get("name", ""),
                description=rv.get("description", ""),
                origin_agents=tuple(rv.get("origin_agents", []) or []),
                merged_from=tuple(rv.get("merged_from", []) or []),
                rank=rv.get("rank", 99),
                total_score=float(rv.get("total_score", 0.0)),
                consensus_level=rv.get("consensus_level", "unknown"),
            )
            for rv in parsed.get("rejected_variants", [])
        )

        merges = tuple(
            MergeDecision(
                merged_variant_ids=tuple(md.get("merged_variant_ids", []) or []),
                resulting_variant_id=md.get("resulting_variant_id", ""),
                reason=md.get("reason", ""),
            )
            for md in parsed.get("merge_decisions", [])
        )

        return CouncilResult(
            id=self._run_id,
            project_id=council_input.project_id,
            stack=council_input.detected_stack or "",
            variants=tuple(sorted(variants, key=lambda v: v.rank)),
            rejected_variants=rejected,
            recommendation=parsed.get("recommendation"),
            reasoning=parsed.get("reasoning", ""),
            merge_decisions=merges,
            council_complete=True,
        )

    # ------------------------------------------------------------------
    # Parallel execution
    # ------------------------------------------------------------------

    def _execute_parallel(self, tasks: list[_AgentTask], phase: str) -> list[_AgentResult]:
        results: list[_AgentResult] = []

        with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
            futures = {executor.submit(self._run_single_agent, t): t for t in tasks}

            for future in as_completed(futures):
                task = futures[future]
                try:
                    result = future.result(timeout=task.config.timeout_seconds + 15)
                    results.append(result)
                except Exception as exc:
                    logger.warning(f"Council agent {task.agent_id} failed: {exc}")
                    results.append(_AgentResult(
                        agent_id=task.agent_id,
                        success=False,
                        error=str(exc),
                    ))
                    self._call_records.append(AgentCallRecord(
                        agent_id=task.agent_id,
                        role=task.role,
                        provider=task.config.provider,
                        model=task.config.model,
                        temperature=task.config.temperature,
                        phase=phase,
                        started_at=task.started_at,
                        duration_ms=0,
                        success=False,
                        error=str(exc),
                    ))

        return results

    # ------------------------------------------------------------------
    # Single agent call with retry
    # ------------------------------------------------------------------

    def _run_single_agent(self, task: _AgentTask) -> _AgentResult:
        provider = create_council_provider(
            task.config,
            self._secret_resolver,
            self._config.ollama_url,
        )

        last_raw = ""
        for attempt in range(_MAX_RETRIES + 1):
            started = datetime.now()
            try:
                raw = provider.complete(task.prompt)
                last_raw = raw
                duration_ms = (datetime.now() - started).total_seconds() * 1000
                parsed = self._parse_json_response(raw, task.agent_id)

                self._call_records.append(AgentCallRecord(
                    agent_id=task.agent_id,
                    role=task.role,
                    provider=task.config.provider,
                    model=task.config.model,
                    temperature=task.config.temperature,
                    phase=task.phase,
                    started_at=task.started_at,
                    duration_ms=duration_ms,
                    success=True,
                    raw_response_snippet=raw[:500],
                    structured_output_summary=str(list(parsed.keys()))[:500],
                ))

                return _AgentResult(
                    agent_id=task.agent_id,
                    success=True,
                    parsed=parsed,
                    raw_response=raw,
                )

            except AgentParseError:
                duration_ms = (datetime.now() - started).total_seconds() * 1000
                self._call_records.append(AgentCallRecord(
                    agent_id=task.agent_id,
                    role=task.role,
                    provider=task.config.provider,
                    model=task.config.model,
                    temperature=task.config.temperature,
                    phase=task.phase,
                    started_at=task.started_at,
                    duration_ms=duration_ms,
                    success=False,
                    error=f"JSON parse error (attempt {attempt + 1})",
                    raw_response_snippet=last_raw[:500],
                ))
                if attempt >= _MAX_RETRIES:
                    logger.warning(f"Agent {task.agent_id}: JSON parse failed after retry")
                    return _AgentResult(
                        agent_id=task.agent_id,
                        success=False,
                        error=f"JSON parse error after {attempt + 1} attempts",
                        raw_response=last_raw,
                    )
                task.prompt = (
                    f"{task.prompt}\n\n"
                    f"DEINE VORHERIGE ANTWORT WAR KEIN VALIDES JSON. "
                    f"BITTE NUR VALIDES JSON ZURÜCKGEBEN — KEIN BEGLEITTEXT."
                )

            except Exception as exc:
                logger.warning(f"Agent {task.agent_id}: {exc}")
                return _AgentResult(
                    agent_id=task.agent_id,
                    success=False,
                    error=str(exc),
                    raw_response=last_raw,
                )

        return _AgentResult(
            agent_id=task.agent_id,
            success=False,
            error="Max retries exceeded",
            raw_response=last_raw,
        )

    def _parse_json_response(self, raw: str, agent_id: str) -> dict[str, Any]:
        text = raw.strip()
        exceptions = []

        # Versuch 1: direktes JSON
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            exceptions.append(str(e))

        # Versuch 2: JSON in Markdown-Codeblock
        import re
        m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1).strip())
            except json.JSONDecodeError as e:
                exceptions.append(f"codeblock: {e}")

        # Versuch 3: erste { … } im Text
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError as e:
                exceptions.append(f"brace-extraction: {e}")

        raise AgentParseError(
            agent_id,
            f"Could not parse JSON: {'; '.join(exceptions)}",
            raw_response=raw,
        )

    # ------------------------------------------------------------------
    # Degraded / empty results
    # ------------------------------------------------------------------

    def _build_empty_result(self, council_input: CouncilInput, chairman_error: str) -> CouncilResult:
        return CouncilResult(
            id=self._run_id,
            project_id=council_input.project_id,
            stack=council_input.detected_stack or "",
            chairman_error=chairman_error,
            council_complete=False,
        )

    # ------------------------------------------------------------------
    # Trace persistence
    # ------------------------------------------------------------------

    def _persist_trace(
        self,
        council_input: CouncilInput,
        proposal_set: ProposalSet,
        vote_sets: tuple[AgentVoteSet, ...],
        council_result: CouncilResult,
        started_at: datetime,
    ) -> None:
        trace = CouncilTrace(
            id=self._run_id,
            project_id=council_input.project_id,
            council_result_id=council_result.id,
            council_input_summary={
                "project_id": council_input.project_id,
                "detected_stack": council_input.detected_stack,
                "platform": council_input.platform,
                "requirement_count": len(council_input.requirements),
                "requirements": [
                    {"id": r.id, "name": r.name, "type": r.type, "required": r.required}
                    for r in council_input.requirements
                ],
                "preflight_ready": (
                    council_input.preflight.overall_ready
                    if council_input.preflight else False
                ),
            },
            agent_call_records=tuple(self._call_records),
            raw_proposals=proposal_set.proposals,
            vote_sets=vote_sets,
            merge_decisions=council_result.merge_decisions,
            total_duration_ms=(datetime.now() - started_at).total_seconds() * 1000,
            errors=tuple(
                list(proposal_set.agent_errors)
                + ([f"Chairman: {council_result.chairman_error}"]
                   if council_result.chairman_error else [])
            ),
            started_at=started_at,
        )

        try:
            trace_subdir = self._trace_dir / council_input.project_id
            trace_subdir.mkdir(parents=True, exist_ok=True)

            path = trace_subdir / f"{self._run_id}.json"
            serialized = self._serialize_trace(trace)
            with path.open("w", encoding="utf-8") as f:
                json.dump(serialized, f, indent=2, ensure_ascii=False, default=str)

            logger.info(f"CouncilTrace persisted: {path}")
        except Exception as exc:
            logger.warning(f"Failed to persist CouncilTrace: {exc}")

    @staticmethod
    def _serialize_trace(trace: CouncilTrace) -> dict[str, Any]:
        return {
            "id": trace.id,
            "project_id": trace.project_id,
            "council_result_id": trace.council_result_id,
            "council_input_summary": trace.council_input_summary,
            "agent_call_records": [
                {
                    "agent_id": r.agent_id,
                    "role": r.role,
                    "provider": r.provider,
                    "model": r.model,
                    "temperature": r.temperature,
                    "phase": r.phase,
                    "started_at": r.started_at.isoformat(),
                    "duration_ms": r.duration_ms,
                    "success": r.success,
                    "error": r.error,
                    "raw_response_snippet": r.raw_response_snippet,
                    "structured_output_summary": r.structured_output_summary,
                }
                for r in trace.agent_call_records
            ],
            "raw_proposal_count": len(trace.raw_proposals),
            "vote_set_count": len(trace.vote_sets),
            "merge_decision_count": len(trace.merge_decisions),
            "total_duration_ms": trace.total_duration_ms,
            "errors": list(trace.errors),
            "started_at": trace.started_at.isoformat(),
            "completed_at": trace.completed_at.isoformat(),
        }