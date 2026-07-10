"""TurnPlan — frozen pre-compose evidence boundary (domain-agnostic)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


@runtime_checkable
class TurnPlan(Protocol):
    """Minimal contract both PHA and tax plans already satisfy."""

    @property
    def profile(self) -> str: ...

    @property
    def slots_tier0(self) -> Sequence[str]: ...

    @property
    def slots_tier1(self) -> Sequence[str]: ...

    @property
    def forbidden(self) -> Sequence[str]: ...

    @property
    def tools_allowed(self) -> Sequence[str]: ...

    @property
    def task_text(self) -> str: ...


@dataclass(frozen=True)
class TurnPlanData:
    """Concrete TurnPlan for dry-runs and adapters."""

    profile: str
    slots_tier0: tuple[str, ...] = ()
    slots_tier1: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()
    tools_allowed: tuple[str, ...] = ()
    task_text: str = ""
    fast_lane: bool = False
    preserve_raw_user: bool = True
    domain_meta: Mapping[str, Any] = field(default_factory=dict)

    @property
    def all_slots(self) -> tuple[str, ...]:
        return self.slots_tier0 + self.slots_tier1


def as_turn_plan_data(plan: Any, *, domain_meta: Mapping[str, Any] | None = None) -> TurnPlanData:
    """Best-effort map from PHA/tax plan objects without importing those packages."""
    meta = dict(domain_meta or {})
    for key in (
        "legacy_question_type",
        "tax_year",
        "journey_phase",
        "focus",
        "inject_insight",
        "intent_score",
    ):
        if hasattr(plan, key) and key not in meta:
            val = getattr(plan, key)
            if val is not None:
                meta[key] = val.value if hasattr(val, "value") else val
    return TurnPlanData(
        profile=str(getattr(plan, "profile", "") or ""),
        slots_tier0=tuple(getattr(plan, "slots_tier0", ()) or ()),
        slots_tier1=tuple(getattr(plan, "slots_tier1", ()) or ()),
        forbidden=tuple(getattr(plan, "forbidden", ()) or ()),
        tools_allowed=tuple(getattr(plan, "tools_allowed", ()) or ()),
        task_text=str(getattr(plan, "task_text", "") or ""),
        fast_lane=bool(getattr(plan, "fast_lane", False)),
        preserve_raw_user=bool(getattr(plan, "preserve_raw_user", True)),
        domain_meta=meta,
    )


__all__ = [
    "TurnPlan",
    "TurnPlanData",
    "as_turn_plan_data",
]
