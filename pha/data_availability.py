"""C-layer data availability disclosure (Stage 3C · no product-specific gates)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from pha.date_range_parser import default_wearable_window
from pha.health_data import effective_query_reference_date
from pha.medical_storage import query_metrics_in_range
from pha.sqlite_storage import query_wearable_daily_range


def build_data_availability_block(
    user_id: str,
    *,
    user_message: str = "",
    reference_date: Optional[date] = None,
) -> str:
    """
    Short disclosure so L3 knows what exists in SQLite without injecting full Patient State.
    """
    uid = (user_id or "default").strip() or "default"
    ref = reference_date or effective_query_reference_date()
    start = ref - timedelta(days=365 * 3)
    lab_rows = query_metrics_in_range(uid, start, ref)
    lab_n = len(lab_rows)
    lab_dates = sorted({r.report_date.isoformat()[:10] for r in lab_rows}, reverse=True)
    lab_hint = lab_dates[0] if lab_dates else ""

    window = default_wearable_window(user_message or "", reference=ref)
    wear_rows = query_wearable_daily_range(uid, window.start, window.end)
    wear_n = len(wear_rows)
    hrv_vals = [float(r.hrv_rmssd_ms) for r in wear_rows if r.hrv_rmssd_ms is not None]

    lines = [
        "【数据可用性 · 库内概况（非本轮全文证据）】",
        f"- 化验账本：{'有' if lab_n else '无'}"
        + (f"；最近报告日 {lab_hint}；约 {lab_n} 条指标行" if lab_n else ""),
        f"- 穿戴日级（{window.iso_span()}）：{'有' if wear_n else '无'}"
        + (
            f"；HRV 样本约 {len(hrv_vals)} 天"
            if hrv_vals
            else ""
        ),
        "- 本轮若未注入全表，回答时不得声称「系统没有任何您的数据」；无关指标可说明「与焦点补剂无直接关联」。",
    ]
    return "\n".join(lines)


__all__ = ["build_data_availability_block"]
