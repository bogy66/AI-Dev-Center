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
import threading
import uuid
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any, Callable

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
from app.execution_identity import execution_identity

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
_TIMEOUT_GRACE_SECONDS = 15


@dataclass
class _AgentTask:
    agent_id: str
    role: str
    config: CouncilAgentConfig
    prompt: str
    phase: str
    started_at: datetime
    activity_closed: threading.Event = field(default_factory=threading.Event)


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
        self._activity_callback: Callable[..., None] | None = None
        self._result_callback: Callable[..., None] | None = None

    def set_activity_callback(self, callback: Callable[..., None] | None) -> None:
        """Project safe Council runtime activity into the central trace."""
        self._activity_callback = callback

    def set_result_callback(self, callback: Callable[..., None] | None) -> None:
        """Project safe structured Council work products into the central trace."""
        self._result_callback = callback

    def _result(self, **result) -> None:
        if self._result_callback is None:
            return
        try:
            self._result_callback(**result)
        except Exception:
            logger.debug("Central Council result recording failed", exc_info=True)

    def _activity(
        self, task: _AgentTask, state: str, *, force: bool = False,
        failure_category: str | None = None,
    ) -> None:
        if task.activity_closed.is_set() and not force:
            return
        if self._activity_callback is None:
            return
        try:
            operation = {"phase1": "proposal", "phase2": "review"}.get(
                task.phase, task.phase,
            )
            details = dict(
                actor=f"Agent {task.agent_id}" if task.agent_id != "C" else "Chairman",
                actor_role=task.role,
                runtime_state=state,
                council_phase=task.phase,
                provider=task.config.provider,
                model=task.config.model,
                execution_identity=execution_identity(
                    "chairman" if task.agent_id == "C" else f"council_agent_{task.agent_id.lower()}_{operation}",
                    provider=task.config.provider, model=task.config.model,
                    actor=task.agent_id, phase=task.phase,
                ),
            )
            if failure_category:
                details["failure_category"] = failure_category
            self._activity_callback(**details)
        except Exception:
            # Observability must never change Council decisions or execution.
            logger.debug("Central Council activity recording failed", exc_info=True)

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

        self._emit_structured_results(
            council_input, proposal_set, vote_sets, council_result,
        )

        if self._trace_dir:
            self._persist_trace(council_input, proposal_set, vote_sets, council_result, started)

        return council_result

    def _emit_structured_results(
        self, council_input: CouncilInput, proposal_set: ProposalSet,
        vote_sets: tuple[AgentVoteSet, ...], council_result: CouncilResult,
    ) -> None:
        """Emit bounded projections only; never raw responses or reasoning fields."""
        def duration_for(agent_id, phase):
            return sum(
                record.duration_ms for record in self._call_records
                if record.agent_id == agent_id and record.phase == phase
            )

        def typed(data, data_type, source, destination):
            return {
                "type": data_type, "interface": "internal",
                "source": source, "destination": destination, "data": data,
            }

        requirements = [{
            "id": item.id, "name": item.name, "type": item.type,
            "purpose": item.purpose, "required": item.required,
        } for item in council_input.requirements]
        phase1_x_info = {
            "requirement_count": len(requirements),
            "stack": council_input.detected_stack or "",
        }
        phase1_x_verbose = {
            **phase1_x_info, "requirements": requirements,
            "project_files": list(council_input.project_files),
            "validation_warnings": list(council_input.validation_warnings),
        }

        proposal_agents = {proposal.agent_id for proposal in proposal_set.proposals}
        for proposal in proposal_set.proposals:
            tools = [{
                "requirement_ref": tool.requirement_ref, "name": tool.name,
                "type": tool.type, "version": tool.version,
                "purpose": tool.purpose, "depends_on": list(tool.depends_on),
                "state": tool.state,
                "environment_constraint": tool.environment_constraint,
            } for tool in proposal.toolchain]
            info = {
                "summary": proposal.description or proposal.name,
                "name": proposal.name, "risks": list(proposal.risks[:3]),
                "constraints": list(proposal.disadvantages[:3]),
            }
            verbose = {**info,
                "variant_id": proposal.variant_id,
                "environment": proposal.environment,
                "capabilities": list(proposal.capabilities),
                "toolchain": [{"name": item["name"], "type": item["type"],
                               "state": item["state"], "purpose": item["purpose"]}
                              for item in tools],
                "advantages": list(proposal.advantages),
                "feasibility": proposal.feasibility,
            }
            very_verbose = {**verbose,
                "hardware_target": proposal.hardware_target,
                "connection": proposal.connection,
                "confidence": proposal.confidence,
                "toolchain": tools,
                "disadvantages": list(proposal.disadvantages),
            }
            config = _get_agent_config(self._config, proposal.agent_id)
            self._result(
                actor=f"Agent {proposal.agent_id}", actor_role=proposal.agent_role,
                council_phase="phase1", result_kind="proposal",
                provider=config.provider, model=config.model,
                duration_ms=duration_for(proposal.agent_id, "phase1"),
                summary=f"{proposal.agent_id} proposal: {proposal.name}",
                council_output={"info": info, "verbose": verbose,
                                "very_verbose": very_verbose},
                interface_data={
                    "normal": {"summary": "Proposal input produced a structured proposal."},
                    "info": {"x": typed(phase1_x_info, "council_input", "engineering_council", f"council_agent_{proposal.agent_id.lower()}_proposal"),
                             "f": execution_identity(f"council_agent_{proposal.agent_id.lower()}_proposal", provider=config.provider, model=config.model, actor=proposal.agent_id, phase="phase1"),
                             "y": typed({"available": True, "name": proposal.name}, "proposal", f"council_agent_{proposal.agent_id.lower()}_proposal", "engineering_council")},
                    "verbose": {"x": typed(phase1_x_verbose, "council_input", "engineering_council", f"council_agent_{proposal.agent_id.lower()}_proposal"), "f": execution_identity(f"council_agent_{proposal.agent_id.lower()}_proposal", provider=config.provider, model=config.model, actor=proposal.agent_id, phase="phase1"), "y": typed(verbose, "proposal", f"council_agent_{proposal.agent_id.lower()}_proposal", "engineering_council")},
                    "very_verbose": {"x": typed(phase1_x_verbose, "council_input", "engineering_council", f"council_agent_{proposal.agent_id.lower()}_proposal"), "f": execution_identity(f"council_agent_{proposal.agent_id.lower()}_proposal", provider=config.provider, model=config.model, actor=proposal.agent_id, phase="phase1"), "y": typed(very_verbose, "proposal", f"council_agent_{proposal.agent_id.lower()}_proposal", "engineering_council")},
                },
            )
        for agent_id in sorted(set(AGENT_ROLES) - proposal_agents):
            config = _get_agent_config(self._config, agent_id)
            empty = {"summary": "No usable structured proposal produced."}
            self._result(
                actor=f"Agent {agent_id}", actor_role=AGENT_ROLES[agent_id],
                council_phase="phase1", result_kind="proposal",
                provider=config.provider, model=config.model,
                duration_ms=duration_for(agent_id, "phase1"),
                summary=empty["summary"],
                council_output={"info": empty, "verbose": empty,
                                "very_verbose": empty},
                interface_data={
                    "normal": {"summary": "Proposal input produced no usable structured proposal."},
                    "info": {"x": typed(phase1_x_info, "council_input", "engineering_council", f"council_agent_{agent_id.lower()}_proposal"), "f": execution_identity(f"council_agent_{agent_id.lower()}_proposal", provider=config.provider, model=config.model, actor=agent_id, phase="phase1"), "y": typed({"available": False}, "proposal", f"council_agent_{agent_id.lower()}_proposal", "engineering_council")},
                    "verbose": {"x": typed(phase1_x_verbose, "council_input", "engineering_council", f"council_agent_{agent_id.lower()}_proposal"), "f": execution_identity(f"council_agent_{agent_id.lower()}_proposal", provider=config.provider, model=config.model, actor=agent_id, phase="phase1"), "y": typed({"available": False}, "proposal", f"council_agent_{agent_id.lower()}_proposal", "engineering_council")},
                    "very_verbose": {"x": typed(phase1_x_verbose, "council_input", "engineering_council", f"council_agent_{agent_id.lower()}_proposal"), "f": execution_identity(f"council_agent_{agent_id.lower()}_proposal", provider=config.provider, model=config.model, actor=agent_id, phase="phase1"), "y": typed({"available": False}, "proposal", f"council_agent_{agent_id.lower()}_proposal", "engineering_council")},
                },
            )

        review_agents = {vote_set.agent_id for vote_set in vote_sets}
        proposals_for_review = [{
            "variant_id": item.variant_id, "name": item.name,
            "description": item.description, "environment": item.environment,
            "capabilities": list(item.capabilities), "risks": list(item.risks),
        } for item in proposal_set.proposals]
        for vote_set in vote_sets:
            reviews = [{
                "variant_id": vote.variant_id,
                "would_recommend": vote.would_recommend,
                "concerns": list(vote.concerns), "scores": vote.scores,
            } for vote in vote_set.votes]
            info_reviews = [{
                "variant_id": item["variant_id"],
                "would_recommend": item["would_recommend"],
                "concerns": item["concerns"][:3],
            } for item in reviews]
            config = _get_agent_config(self._config, vote_set.agent_id)
            self._result(
                actor=f"Agent {vote_set.agent_id}", actor_role=vote_set.agent_role,
                council_phase="phase2", result_kind="review",
                provider=config.provider, model=config.model,
                duration_ms=duration_for(vote_set.agent_id, "phase2"),
                summary=f"{vote_set.agent_id} reviewed {len(reviews)} variants",
                council_output={
                    "info": {"summary": f"Reviewed {len(reviews)} variants",
                             "reviews": info_reviews},
                    "verbose": {"summary": f"Reviewed {len(reviews)} variants",
                                "reviews": reviews},
                    "very_verbose": {"summary": f"Reviewed {len(reviews)} variants",
                                     "reviews": reviews},
                },
                interface_data={
                    "normal": {"summary": "Proposal variants produced a structured review."},
                    "info": {"x": typed({"proposal_count": len(proposals_for_review)}, "proposal_set", "engineering_council", f"council_agent_{vote_set.agent_id.lower()}_review"),
                             "f": execution_identity(f"council_agent_{vote_set.agent_id.lower()}_review", provider=config.provider, model=config.model, actor=vote_set.agent_id, phase="phase2"),
                             "y": typed({"review_count": len(reviews)}, "review_set", f"council_agent_{vote_set.agent_id.lower()}_review", "engineering_council")},
                    "verbose": {"x": typed({"proposals": proposals_for_review}, "proposal_set", "engineering_council", f"council_agent_{vote_set.agent_id.lower()}_review"),
                                "f": execution_identity(f"council_agent_{vote_set.agent_id.lower()}_review", provider=config.provider, model=config.model, actor=vote_set.agent_id, phase="phase2"),
                                "y": typed({"reviews": info_reviews}, "review_set", f"council_agent_{vote_set.agent_id.lower()}_review", "engineering_council")},
                    "very_verbose": {"x": typed({"proposals": proposals_for_review}, "proposal_set", "engineering_council", f"council_agent_{vote_set.agent_id.lower()}_review"),
                                     "f": execution_identity(f"council_agent_{vote_set.agent_id.lower()}_review", provider=config.provider, model=config.model, actor=vote_set.agent_id, phase="phase2"),
                                     "y": typed({"reviews": reviews}, "review_set", f"council_agent_{vote_set.agent_id.lower()}_review", "engineering_council")},
                },
            )
        for agent_id in sorted(set(AGENT_ROLES) - review_agents):
            config = _get_agent_config(self._config, agent_id)
            empty = {"summary": "No usable structured review produced."}
            self._result(
                actor=f"Agent {agent_id}", actor_role=AGENT_ROLES[agent_id],
                council_phase="phase2", result_kind="review",
                provider=config.provider, model=config.model,
                duration_ms=duration_for(agent_id, "phase2"),
                summary=empty["summary"],
                council_output={"info": empty, "verbose": empty,
                                "very_verbose": empty},
                interface_data={
                    "normal": {"summary": "Proposal variants produced no usable structured review."},
                    "info": {"x": typed({"proposal_count": len(proposals_for_review)}, "proposal_set", "engineering_council", f"council_agent_{agent_id.lower()}_review"),
                             "f": execution_identity(f"council_agent_{agent_id.lower()}_review", provider=config.provider, model=config.model, actor=agent_id, phase="phase2"),
                             "y": typed({"available": False}, "review_set", f"council_agent_{agent_id.lower()}_review", "engineering_council")},
                    "verbose": {"x": typed({"proposals": proposals_for_review}, "proposal_set", "engineering_council", f"council_agent_{agent_id.lower()}_review"),
                                "f": execution_identity(f"council_agent_{agent_id.lower()}_review", provider=config.provider, model=config.model, actor=agent_id, phase="phase2"),
                                "y": typed({"available": False}, "review_set", f"council_agent_{agent_id.lower()}_review", "engineering_council")},
                    "very_verbose": {"x": typed({"proposals": proposals_for_review}, "proposal_set", "engineering_council", f"council_agent_{agent_id.lower()}_review"),
                                     "f": execution_identity(f"council_agent_{agent_id.lower()}_review", provider=config.provider, model=config.model, actor=agent_id, phase="phase2"),
                                     "y": typed({"available": False}, "review_set", f"council_agent_{agent_id.lower()}_review", "engineering_council")},
                },
            )

        selected = next(
            (variant for variant in council_result.variants
             if variant.id == council_result.recommendation), None,
        )
        selected_name = selected.name if selected else None
        chairman_info = {
            "summary": (
                f"Selected {selected_name or council_result.recommendation}"
                if council_result.recommendation else "No final recommendation produced."
            ),
            "recommendation": council_result.recommendation,
            "selected_approach": selected_name,
            "status": "complete" if council_result.council_complete else "incomplete",
        }
        chairman_verbose = {**chairman_info,
            "preferred_variants": [variant.name for variant in council_result.variants],
            "rejected_variants": [variant.name for variant in council_result.rejected_variants],
            "merge_decisions": [{
                "merged_variant_ids": list(item.merged_variant_ids),
                "resulting_variant_id": item.resulting_variant_id,
                "reason": item.reason,
            } for item in council_result.merge_decisions],
        }
        chairman_very_verbose = {**chairman_verbose,
            "result_id": council_result.id,
            "council_complete": council_result.council_complete,
            "error_count": len(council_result.agent_errors) + bool(council_result.chairman_error),
            "total_llm_calls": council_result.total_llm_calls,
            "variant_ids": [variant.id for variant in council_result.variants],
        }
        self._result(
            actor="Chairman", actor_role="chairman", council_phase="phase3",
            result_kind="chairman_decision", provider=self._config.chairman.provider,
            model=self._config.chairman.model,
            duration_ms=duration_for("C", "phase3"),
            summary=chairman_info["summary"],
            council_output={"info": chairman_info, "verbose": chairman_verbose,
                            "very_verbose": chairman_very_verbose},
            interface_data={
                "normal": {"summary": "Council proposals and reviews produced a Chairman decision."},
                "info": {
                    "x": typed({"proposal_count": len(proposal_set.proposals),
                                "review_count": len(vote_sets)}, "council_review_set",
                               "engineering_council", "chairman"),
                    "f": execution_identity("chairman", provider=self._config.chairman.provider, model=self._config.chairman.model, actor="C", phase="phase3"),
                    "y": typed({"recommendation": council_result.recommendation,
                                "council_complete": council_result.council_complete},
                               "chairman_decision", "chairman", "engineering_council"),
                },
                "verbose": {
                    "x": typed({"proposals": proposals_for_review,
                          "reviews": [{"agent_id": item.agent_id,
                                       "review_count": len(item.votes)}
                                      for item in vote_sets]}, "council_review_set",
                               "engineering_council", "chairman"),
                    "f": execution_identity("chairman", provider=self._config.chairman.provider, model=self._config.chairman.model, actor="C", phase="phase3"),
                    "y": typed(chairman_verbose, "chairman_decision",
                               "chairman", "engineering_council"),
                },
                "very_verbose": {
                    "x": typed({"proposals": proposals_for_review,
                          "reviews": [{"agent_id": item.agent_id,
                                       "reviews": [{"variant_id": vote.variant_id,
                                                    "would_recommend": vote.would_recommend,
                                                    "concerns": list(vote.concerns),
                                                    "scores": vote.scores}
                                                   for vote in item.votes]}
                                      for item in vote_sets]}, "council_review_set",
                               "engineering_council", "chairman"),
                    "f": execution_identity("chairman", provider=self._config.chairman.provider, model=self._config.chairman.model, actor="C", phase="phase3"),
                    "y": typed(chairman_very_verbose, "chairman_decision",
                               "chairman", "engineering_council"),
                },
            },
        )

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

        result = self._execute_parallel([task], "phase3")[0]

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
        results_by_agent: dict[str, _AgentResult] = {}
        executor = ThreadPoolExecutor(max_workers=len(tasks))
        try:
            for task in tasks:
                self._activity(task, "waiting")
            futures = {executor.submit(self._run_single_agent, t): t for t in tasks}
            deadlines = {
                future: time.monotonic()
                + task.config.timeout_seconds
                + _TIMEOUT_GRACE_SECONDS
                for future, task in futures.items()
            }
            pending = set(futures)

            while pending:
                now = time.monotonic()
                expired = {future for future in pending if deadlines[future] <= now}
                for future in expired:
                    task = futures[future]
                    task.activity_closed.set()
                    self._activity(
                        task, "failed", force=True, failure_category="timeout",
                    )
                    future.cancel()
                    error = "provider call exceeded its configured deadline"
                    results_by_agent[task.agent_id] = _AgentResult(
                        agent_id=task.agent_id, success=False, error=error,
                    )
                    self._call_records.append(AgentCallRecord(
                        agent_id=task.agent_id,
                        role=task.role,
                        provider=task.config.provider,
                        model=task.config.model,
                        temperature=task.config.temperature,
                        phase=phase,
                        started_at=task.started_at,
                        duration_ms=(task.config.timeout_seconds + _TIMEOUT_GRACE_SECONDS) * 1000,
                        success=False,
                        error=error,
                    ))
                pending.difference_update(expired)
                if not pending:
                    break

                next_deadline = min(deadlines[future] for future in pending)
                completed, _ = wait(
                    pending,
                    timeout=max(0.0, next_deadline - time.monotonic()),
                    return_when=FIRST_COMPLETED,
                )
                for future in completed:
                    task = futures[future]
                    pending.remove(future)
                    try:
                        results_by_agent[task.agent_id] = future.result()
                    except Exception as exc:
                        self._activity(
                            task, "failed", failure_category="provider_failure",
                        )
                        logger.warning(f"Council agent {task.agent_id} failed: {exc}")
                        results_by_agent[task.agent_id] = _AgentResult(
                            agent_id=task.agent_id,
                            success=False,
                            error=str(exc),
                        )
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
        finally:
            # A context manager or wait=True would block on a provider that
            # violated its own HTTP timeout. Running calls cannot be killed by
            # ThreadPoolExecutor; close their activity and return control.
            executor.shutdown(wait=False, cancel_futures=True)

        return [results_by_agent[task.agent_id] for task in tasks]

    # ------------------------------------------------------------------
    # Single agent call with retry
    # ------------------------------------------------------------------

    def _run_single_agent(self, task: _AgentTask) -> _AgentResult:
        self._activity(task, "preparing")
        try:
            provider = create_council_provider(
                task.config,
                self._secret_resolver,
                self._config.ollama_url,
            )
        except Exception:
            self._activity(task, "failed", failure_category="provider_configuration")
            raise

        last_raw = ""
        for attempt in range(_MAX_RETRIES + 1):
            started = datetime.now()
            try:
                self._activity(task, "thinking")
                raw = provider.complete(task.prompt)
                last_raw = raw
                self._activity(task, "reviewing")
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

                result = _AgentResult(
                    agent_id=task.agent_id,
                    success=True,
                    parsed=parsed,
                    raw_response=raw,
                )
                self._activity(task, "completed")
                return result

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
                    self._activity(task, "failed", failure_category="invalid_json")
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
                self._activity(task, "failed", failure_category="provider_failure")
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
