"""Core turn FSM — spine phases + plan-before-compose invariant."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Sequence


class CoreTurnPhase(str, Enum):
    """Domain-agnostic spine. Plugins map richer phases onto these ranks."""

    INIT = "init"
    SESSION = "session"
    PLAN = "plan"
    COMPOSE = "compose"
    POST_AUDIT = "post_audit"
    DONE = "done"
    ERROR = "error"


_PHASE_RANK = {p: i for i, p in enumerate(CoreTurnPhase)}

_PLAN_PHASES = frozenset({CoreTurnPhase.PLAN})
_COMPOSE_PHASES = frozenset({CoreTurnPhase.COMPOSE})


def fsm_strict_enabled() -> bool:
    return (os.environ.get("HARNESS_TURN_FSM") or "1").strip().lower() not in (
        "0",
        "false",
        "off",
    )


def validate_phase_transition(
    previous: CoreTurnPhase | None,
    next_phase: CoreTurnPhase,
) -> bool:
    if previous is None:
        return next_phase == CoreTurnPhase.INIT
    if next_phase == CoreTurnPhase.ERROR:
        return True
    # Early exits (clarify / profile) may jump to DONE without compose.
    if next_phase == CoreTurnPhase.DONE:
        return previous != CoreTurnPhase.ERROR
    prev_rank = _PHASE_RANK.get(previous, -1)
    next_rank = _PHASE_RANK.get(next_phase, -1)
    return next_rank >= prev_rank


def plan_precedes_compose(phases: Sequence[CoreTurnPhase]) -> bool:
    plan_idx = None
    compose_idx = None
    for i, ph in enumerate(phases):
        if ph in _PLAN_PHASES and plan_idx is None:
            plan_idx = i
        if ph in _COMPOSE_PHASES and compose_idx is None:
            compose_idx = i
    if compose_idx is None:
        return True
    if plan_idx is None:
        return False
    return plan_idx < compose_idx


@dataclass
class PhaseRecorder:
    phases: List[CoreTurnPhase] = field(default_factory=list)
    domain_aliases: List[str] = field(default_factory=list)

    def enter(self, phase: CoreTurnPhase, *, domain_alias: str | None = None) -> None:
        prev = self.phases[-1] if self.phases else None
        if fsm_strict_enabled() and not validate_phase_transition(prev, phase):
            raise RuntimeError(f"invalid harness turn phase transition: {prev} -> {phase}")
        self.phases.append(phase)
        self.domain_aliases.append(domain_alias or phase.value)

    def assert_plan_before_compose(self) -> None:
        if not plan_precedes_compose(self.phases):
            raise RuntimeError(
                "consensus violation: COMPOSE reached without PLAN phase",
            )

    def as_names(self) -> list[str]:
        return [p.value for p in self.phases]


# Common domain alias → core spine (Week 3 adapters may extend).
DOMAIN_PHASE_TO_CORE: dict[str, CoreTurnPhase] = {
    "init": CoreTurnPhase.INIT,
    "session": CoreTurnPhase.SESSION,
    "perception": CoreTurnPhase.SESSION,
    "parse_reuse": CoreTurnPhase.SESSION,
    "evidence_probe": CoreTurnPhase.SESSION,
    "scope": CoreTurnPhase.SESSION,
    "clarify": CoreTurnPhase.SESSION,
    "route_qa": CoreTurnPhase.SESSION,
    "plan": CoreTurnPhase.PLAN,
    "slot_assembly": CoreTurnPhase.PLAN,
    "tier0_assemble": CoreTurnPhase.PLAN,
    "plan_pre_llm": CoreTurnPhase.PLAN,
    "skip_llm_eval": CoreTurnPhase.PLAN,
    "compose": CoreTurnPhase.COMPOSE,
    "fast_lane": CoreTurnPhase.COMPOSE,
    "post_audit": CoreTurnPhase.POST_AUDIT,
    "done": CoreTurnPhase.DONE,
    "error": CoreTurnPhase.ERROR,
}


def map_domain_phase(name: str) -> CoreTurnPhase:
    key = (name or "").strip().lower()
    if key not in DOMAIN_PHASE_TO_CORE:
        raise KeyError(f"unknown domain phase alias: {name!r}")
    return DOMAIN_PHASE_TO_CORE[key]


__all__ = [
    "CoreTurnPhase",
    "PhaseRecorder",
    "DOMAIN_PHASE_TO_CORE",
    "fsm_strict_enabled",
    "map_domain_phase",
    "plan_precedes_compose",
    "validate_phase_transition",
]
