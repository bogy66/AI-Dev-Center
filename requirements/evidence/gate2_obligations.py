"""Gate-2 proof-obligation REPRESENTATION (KIA-ADC-TEST-ASSURANCE-MODEL-FIX-001
section 7).

This module only CATALOGS the productive-composition claims Gate-2 will
eventually have to prove -- real producer -> real artifact -> real
persistence (where applicable) -> real consumer, for every claimed
productive handoff between ADC's pipeline stages, plus the cross-cutting
Web/MCP/persistence-reload/retry-idempotency/cross-process/lifecycle/
environment/fault permutations named in this task.

It deliberately proves NOTHING: every obligation's status is the fixed
literal NOT_YET_EXECUTED, and `assert_none_marked_proven()` mechanically
enforces that this module (and this task) never marks a Gate-2
obligation PROVEN. A hand-constructed internal artifact (SetupPlan,
SetupStep, CapabilityRegistration, CouncilResult, ApprovalProvenance, a
recovery record, ExecutionRequest) may satisfy a genuine
component/unit test of that primitive itself, but can never satisfy one
of these obligations -- proving one requires the real producer that
actually generates that artifact.
"""
from __future__ import annotations

from dataclasses import dataclass

GATE2_STATUS_NOT_YET_EXECUTED = "NOT_YET_EXECUTED"


@dataclass(frozen=True)
class Gate2Obligation:
    obligation_id: str
    handoff: str
    description: str
    status: str = GATE2_STATUS_NOT_YET_EXECUTED


GATE2_OBLIGATIONS: tuple[Gate2Obligation, ...] = (
    Gate2Obligation("GATE2_S1_S2", "S1 -> S2", "Real intake artifact consumed productively by S2."),
    Gate2Obligation("GATE2_S2_S3", "S2 -> S3", "Real S2 output consumed productively by S3."),
    Gate2Obligation(
        "GATE2_S2_5_S3_IDENTITY", "S2.5 -> S3",
        "The exact real EngineeringDecision identity produced by S2.5 is the one S3 consumes -- never a hand-constructed substitute.",
    ),
    Gate2Obligation(
        "GATE2_S3_1_TO_S3_5", "S3.1 -> S3.2 -> S3.3 -> S3.4/S3.5",
        "The real S3 internal chain runs productively end to end through its own real sub-stages.",
    ),
    Gate2Obligation(
        "GATE2_S3_S4_ENVIRONMENT_STATE", "S3 -> S4",
        "The real EnvironmentState produced by S3 is the one S4 consumes.",
    ),
    Gate2Obligation(
        "GATE2_S4_1_TO_S4_4", "S4.1 -> S4.2 -> S4.3 -> S4.4",
        "The real S4 internal chain runs productively end to end through its own real sub-stages.",
    ),
    Gate2Obligation("GATE2_S4_S5", "S4 -> S5", "Real S4 output consumed productively by S5."),
    Gate2Obligation(
        "GATE2_S5_1_TO_S5_7", "S5.1 -> S5.2 -> S5.3 -> S5.4 -> S5.5 -> S5.6 -> S5.7",
        "The real S5 internal chain runs productively end to end through its own real sub-stages.",
    ),
    Gate2Obligation(
        "GATE2_S5_S4_BOUNDED_REWORK", "S5 -> S4",
        "Exactly one bounded rework cycle from S5 back to S4, never an unbounded loop.",
    ),
    Gate2Obligation(
        "GATE2_S5_S3_BOUNDED_RECOVERY", "S5 -> S3",
        "Bounded missing-toolchain recovery from S5 back to S3, never an unbounded loop.",
    ),
    Gate2Obligation("GATE2_S5_S6", "S5 -> S6", "Real S5 output consumed productively by S6."),
    Gate2Obligation("GATE2_WEB", "cross-cutting", "The same productive chain, driven through the real Web boundary."),
    Gate2Obligation("GATE2_MCP", "cross-cutting", "The same productive chain, driven through the real MCP boundary."),
    Gate2Obligation(
        "GATE2_PERSISTENCE_RELOAD", "cross-cutting",
        "State persisted by one real process instance is correctly reloaded by a fresh real instance.",
    ),
    Gate2Obligation(
        "GATE2_RETRY_IDEMPOTENCY", "cross-cutting",
        "A retried request against real persisted state never causes a second real productive execution.",
    ),
    Gate2Obligation(
        "GATE2_CROSS_PROCESS", "cross-cutting",
        "The same productive chain holds correctly across a genuine OS process boundary, not just in-process.",
    ),
    Gate2Obligation("GATE2_LIFECYCLE_PERMUTATIONS", "cross-cutting", "Real lifecycle-state permutations across the productive chain."),
    Gate2Obligation("GATE2_ENVIRONMENT_PERMUTATIONS", "cross-cutting", "Real environment-shape permutations across the productive chain."),
    Gate2Obligation("GATE2_FAULT_PERMUTATIONS", "cross-cutting", "Real fault-injection permutations across the productive chain."),
)


def assert_none_marked_proven(obligations: tuple[Gate2Obligation, ...] = GATE2_OBLIGATIONS) -> None:
    """Mechanical enforcement of this task's own constraint: Gate-2 must
    never be marked proven here. Raises if it ever is."""
    proven = [o.obligation_id for o in obligations if o.status != GATE2_STATUS_NOT_YET_EXECUTED]
    if proven:
        raise AssertionError(
            f"KIA-ADC-TEST-ASSURANCE-MODEL-FIX-001 section 7 violation: "
            f"Gate-2 obligations marked proven by this task: {proven}"
        )
