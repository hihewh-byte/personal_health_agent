"""Dynamic exam-date anchors and ±7d wearable cross-table penetration (PHA v2.1.3)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import List, Optional, Sequence

from pha.clinical_llm import CAUSAL_CROSS_TABLE_MANDATE
from pha.health_data import effective_query_reference_date
from pha.medical_storage import list_distinct_report_dates
from pha.sqlite_storage import query_wearable_daily_range

EXAM_WEARABLE_PADDING_DAYS = 7

_WEARABLE_SIGNALS = (
    ("steps", "步数", lambda r: r.steps, "步"),
    ("rhr", "静息心率", lambda r: r.resting_heart_rate_bpm, "bpm"),
    ("hrv", "HRV", lambda r: r.hrv_rmssd_ms, "ms"),
    ("sleep", "睡眠时长", lambda r: r.sleep_hours, "h"),
    ("waso", "夜间清醒", lambda r: r.awake_duration_hours, "h"),
)


def list_exam_temporal_anchors(user_id: str, *, limit: int = 24) -> List[date]:
    """Distinct SQLite ``report_date`` values as dynamic anchors."""
    return list_distinct_report_dates(user_id, limit=limit)


def _fmt_mean(vals: List[float], unit: str) -> str:
    if not vals:
        return "—"
    return f"{sum(vals) / len(vals):.2f}{unit}"


def build_exam_anchor_wearable_block(
    user_id: str,
    *,
    anchors: Optional[Sequence[date]] = None,
    padding_days: int = EXAM_WEARABLE_PADDING_DAYS,
    reference_date: Optional[date] = None,
) -> str:
    """For each exam anchor, inject ±7d wearable_daily stream means (all core signals)."""
    uid = (user_id or "default").strip() or "default"
    ref = reference_date or effective_query_reference_date()
    anchor_list = list(anchors) if anchors is not None else list_exam_temporal_anchors(uid)
    if not anchor_list:
        return (
            "【跨表时空穿透 · 动态体检锚点】\n"
            "（库内暂无体检 report_date，无法对齐穿戴窗口）"
        )

    lines: List[str] = [
        f"【跨表时空穿透 · 体检日动态锚点 ±{padding_days}d · 穿戴流体序列】",
        "窗口由 SQLite 真实 report_date 驱动；禁止臆造日期。",
    ]
    for anchor in sorted(anchor_list):
        w_start = anchor - timedelta(days=padding_days)
        w_end = min(anchor + timedelta(days=padding_days), ref)
        rows = query_wearable_daily_range(uid, w_start, w_end)
        lines.append(
            f"\n■ 锚点 T={anchor.isoformat()} · 窗口 [{w_start.isoformat()}, {w_end.isoformat()}] · n日={len(rows)}",
        )
        if not rows:
            lines.append("  （该窗口无 wearable_daily 记录）")
            continue
        for sid, label, getter, unit in _WEARABLE_SIGNALS:
            vals = [float(getter(r)) for r in rows if getter(r) is not None]
            lines.append(f"  - {label} 均值: {_fmt_mean(vals, unit)}（有效日 {len(vals)}）")
        try:
            from pha.sqlite_storage import query_active_energy_daily_range

            kcal_pts = query_active_energy_daily_range(uid, w_start, w_end)
            if kcal_pts:
                kvals = [float(p["value"]) for p in kcal_pts]
                lines.append(f"  - 活动消耗 均值: {_fmt_mean(kvals, 'kcal')}（有效日 {len(kvals)}）")
        except Exception:
            pass
    return "\n".join(lines)


def build_cross_table_context_bundle(user_id: str, *, reference_date: Optional[date] = None) -> str:
    block = build_exam_anchor_wearable_block(user_id, reference_date=reference_date)
    return f"{block}\n\n{CAUSAL_CROSS_TABLE_MANDATE}"
