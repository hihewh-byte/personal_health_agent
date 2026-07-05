"""Stage 3H-γ: specialized attachment lanes → safe fallback to grounded review.

When wearable_screenshot_review or supplement attachment lanes cannot serve a turn
(insufficient structured KPIs / label ledger) but vision still extracted groundable
facts (metrics[], narratives[], vision_summary), rebind to attachment_grounded_review
instead of letting the turn fall through to lifestyle warehouse or LLM confabulation.

RFC §3 diagram: 专用车道未命中/失败 → 安全回落通用层，**绝不**回落 lifestyle。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from pha.harness_plan import TurnEvidencePlan, build_turn_evidence_plan

# Explicit fallback contract (RFC 3H-γ): specialized profiles degrade here, not lifestyle.
SPECIALIZED_ATTACHMENT_PROFILES = frozenset({
    "wearable_screenshot_review",
    "attachment_asset_qa",
    "attachment_episodic_bridge",
})

PROFILE_GROUNDED_FALLBACK_TARGET = "attachment_grounded_review"

_SPECIALIZED_TO_GROUNDED: Dict[str, str] = {
    prof: PROFILE_GROUNDED_FALLBACK_TARGET for prof in SPECIALIZED_ATTACHMENT_PROFILES
}


@dataclass
class GroundedFallbackResult:
    plan: TurnEvidencePlan
    attachment_label: str
    data_availability_block: str
    from_profile: str


def parse_has_groundable_facts(parsed: Dict[str, Any] | None) -> bool:
    """Vision/OCR facts sufficient for the universal grounded lane (structure signal only)."""
    if not parsed:
        return False
    if (parsed.get("label_ledger") or "").strip():
        return True
    if parsed.get("metrics"):
        return True
    if parsed.get("narratives"):
        return True
    if (parsed.get("vision_summary") or "").strip():
        return True
    return False


def _compare_table_has_snapshot(table: Any) -> bool:
    if table is None:
        return False
    rows = getattr(table, "rows", None) or []
    for row in rows:
        snap = (getattr(row, "snapshot_value", None) or "").strip()
        if snap:
            return True
    return False


def specialized_lane_insufficient(
    profile: str,
    parsed: Dict[str, Any] | None,
    *,
    wearable_compare_table: Any = None,
) -> bool:
    """
    True when a specialized lane cannot honor this turn but grounded facts remain.

    Pure structure signals — no business phrase routing.
    """
    prof = (profile or "").strip()
    if prof not in SPECIALIZED_ATTACHMENT_PROFILES:
        return False
    if not parse_has_groundable_facts(parsed):
        return False
    p = parsed or {}

    if prof == "wearable_screenshot_review":
        wearable_metrics = p.get("wearable_metrics") or []
        if wearable_metrics and _compare_table_has_snapshot(wearable_compare_table):
            return False
        # Generic vision facts (lab-like metrics, narratives) → wearable compare lane useless.
        if p.get("metrics") or p.get("narratives"):
            return True
        if not wearable_metrics and not _compare_table_has_snapshot(wearable_compare_table):
            return bool((p.get("vision_summary") or "").strip() or p.get("narratives"))
        return False

    # Supplement attachment lanes: ledger/rows present → lane still valid.
    if (p.get("label_ledger") or "").strip() or p.get("ingredient_rows"):
        return False
    return bool(p.get("metrics") or p.get("narratives") or (p.get("vision_summary") or "").strip())


def try_specialized_fallback_to_grounded(
    *,
    plan: TurnEvidencePlan,
    parsed: Dict[str, Any] | None,
    wearable_compare_table: Any = None,
    user_id: str,
    user_message: str,
) -> Optional[GroundedFallbackResult]:
    """Rebind plan to attachment_grounded_review when specialized lane is insufficient."""
    from pha.attachment_asset_qa import universal_attachment_lane_enabled
    from pha.data_availability import build_data_availability_block
    from pha.session_turn_focus import focus_summary_from_parsed

    if not universal_attachment_lane_enabled():
        return None
    if (plan.profile or "") == PROFILE_GROUNDED_FALLBACK_TARGET:
        return None
    if not specialized_lane_insufficient(
        plan.profile,
        parsed,
        wearable_compare_table=wearable_compare_table,
    ):
        return None

    label = focus_summary_from_parsed(parsed or {})
    if not label.strip():
        return None

    new_plan = build_turn_evidence_plan(
        user_message,
        attachment_grounded_review=True,
    )
    avail = build_data_availability_block(user_id, user_message=user_message)
    return GroundedFallbackResult(
        plan=new_plan,
        attachment_label=label,
        data_availability_block=avail,
        from_profile=(plan.profile or ""),
    )


__all__ = [
    "GroundedFallbackResult",
    "PROFILE_GROUNDED_FALLBACK_TARGET",
    "SPECIALIZED_ATTACHMENT_PROFILES",
    "_SPECIALIZED_TO_GROUNDED",
    "parse_has_groundable_facts",
    "specialized_lane_insufficient",
    "try_specialized_fallback_to_grounded",
]
