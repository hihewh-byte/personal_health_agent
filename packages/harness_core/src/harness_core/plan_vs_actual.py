"""plan_vs_actual — portable machine-diff of TurnPlan vs runtime."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from harness_core.integrity import IntegrityResult, integrity_diff_codes
from harness_core.turn_plan import TurnPlan


def compute_plan_vs_actual(
    plan: TurnPlan | Any,
    *,
    tools_executed: Sequence[str] = (),
    slot_contents: Mapping[str, str] | None = None,
    tool_error: str | None = None,
    integrity: IntegrityResult | Mapping[str, Any] | None = None,
) -> list[str]:
    """Return sorted unique diff codes. No PII — codes only."""
    diffs: list[str] = []
    tools_executed = list(tools_executed or [])
    allowed = set(getattr(plan, "tools_allowed", ()) or [])
    forbidden = set(getattr(plan, "forbidden", ()) or [])
    slot_contents = slot_contents or {}

    for t in tools_executed:
        if t not in allowed:
            diffs.append(f"tool_not_allowed:{t}")

    if "LLM_COMPUTE" in forbidden and any(
        t in ("compute", "run_compute", "llm_compute") for t in tools_executed
    ):
        diffs.append("forbidden_tool_llm_compute")

    if tool_error:
        diffs.append("tool_error")

    for slot in getattr(plan, "slots_tier0", ()) or ():
        if slot in ("MASTER_ANCHOR", "TASK"):
            continue
        if slot in slot_contents and not (slot_contents.get(slot) or "").strip():
            diffs.append(f"missing_tier0_slot:{slot}")

    diffs.extend(integrity_diff_codes(integrity))
    return sorted(set(diffs))


__all__ = ["compute_plan_vs_actual"]
