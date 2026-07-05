"""P0 — Chat turn finite-state machine: phase order guards (Harness consensus).

CONSENSUS_ACK: harness-opus48-v2026-06-08 read
Rollback: PHA_CHAT_TURN_FSM=0 disables strict phase-order assertions (telemetry only).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Sequence


class ChatTurnPhase(str, Enum):
    """Ordered harness phases for one SSE chat turn."""

    INIT = "init"
    SESSION = "session"
    PERCEPTION = "perception"
    PARSE_REUSE = "parse_reuse"
    EVIDENCE_PROBE = "evidence_probe"
    CLARIFY = "clarify"
    ROUTE_QA = "route_qa"
    PLAN = "plan"
    SLOT_ASSEMBLY = "slot_assembly"
    TIER0_ASSEMBLE = "tier0_assemble"
    PLAN_PRE_LLM = "plan_pre_llm"
    SKIP_LLM_EVAL = "skip_llm_eval"
    COMPOSE = "compose"
    POST_AUDIT = "post_audit"
    DONE = "done"
    ERROR = "error"


# Indices enforce TurnEvidencePlan before any LLM compose (consensus §2.1).
_PHASE_RANK = {p: i for i, p in enumerate(ChatTurnPhase)}

_PLAN_PHASES = frozenset(
    {
        ChatTurnPhase.PLAN,
        ChatTurnPhase.SLOT_ASSEMBLY,
        ChatTurnPhase.TIER0_ASSEMBLE,
        ChatTurnPhase.PLAN_PRE_LLM,
        ChatTurnPhase.SKIP_LLM_EVAL,
    },
)
_COMPOSE_PHASES = frozenset({ChatTurnPhase.COMPOSE})


def fsm_strict_enabled() -> bool:
    return (os.environ.get("PHA_CHAT_TURN_FSM") or "1").strip().lower() not in (
        "0",
        "false",
        "off",
    )


def validate_phase_transition(
    previous: ChatTurnPhase | None,
    next_phase: ChatTurnPhase,
) -> bool:
    if previous is None:
        return next_phase == ChatTurnPhase.INIT
    prev_rank = _PHASE_RANK.get(previous, -1)
    next_rank = _PHASE_RANK.get(next_phase, -1)
    if next_phase == ChatTurnPhase.ERROR:
        return True
    return next_rank >= prev_rank


def plan_precedes_compose(phases: Sequence[ChatTurnPhase]) -> bool:
    """True when PLAN ran before COMPOSE (consensus hard constraint)."""
    plan_idx = None
    compose_idx = None
    for i, ph in enumerate(phases):
        if ph in _PLAN_PHASES and plan_idx is None:
            plan_idx = i
        if ph in _COMPOSE_PHASES:
            compose_idx = i
    if compose_idx is None:
        return True
    if plan_idx is None:
        return False
    return plan_idx < compose_idx


@dataclass
class ChatTurnPhaseRecorder:
    """Records phase transitions for harness telemetry and selfchecks."""

    phases: List[ChatTurnPhase] = field(default_factory=list)

    def enter(self, phase: ChatTurnPhase) -> None:
        prev = self.phases[-1] if self.phases else None
        if fsm_strict_enabled() and not validate_phase_transition(prev, phase):
            raise RuntimeError(f"invalid chat turn phase transition: {prev} -> {phase}")
        self.phases.append(phase)

    def assert_plan_before_compose(self) -> None:
        if not plan_precedes_compose(self.phases):
            raise RuntimeError(
                "consensus violation: COMPOSE reached without PLAN phase",
            )


__all__ = [
    "ChatTurnPhase",
    "ChatTurnPhaseRecorder",
    "fsm_strict_enabled",
    "plan_precedes_compose",
    "validate_phase_transition",
]
