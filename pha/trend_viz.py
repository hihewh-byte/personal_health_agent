"""Structured wearable trend payloads for Chart.js dashboards."""

from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

from pha.models import WearableDailySummary

logger = logging.getLogger(__name__)

STEPS_CHART_START_YEAR = 2016
RHR_ALERT_THRESHOLD = 80.0


class TrendPoint(BaseModel):
    label: str
    value: Optional[float] = None
    granularity: str = "day"  # day | month | year


class RhrAnnotation(BaseModel):
    label: str
    value: float
    note: str = "RHR > 80"


class TrendChartsPayload(BaseModel):
    reference_date: str
    user_id: str
    has_data: bool = False
    sleep: Dict[str, List[TrendPoint]] = Field(default_factory=dict)
    steps: Dict[str, List[TrendPoint]] = Field(default_factory=dict)
    rhr: Dict[str, List[TrendPoint]] = Field(default_factory=dict)
    hrv: Dict[str, List[TrendPoint]] = Field(default_factory=dict)
    steps_for_overlay: List[TrendPoint] = Field(
        default_factory=list,
        description="Aligned daily/monthly steps for HRV dual-axis (recent window).",
    )
    rhr_annotations: List[RhrAnnotation] = Field(default_factory=list)
    summaries: Dict[str, str] = Field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="python")


def _mean(vals: List[float]) -> Optional[float]:
    if not vals:
        return None
    return float(statistics.mean(vals))


def _merge_day(samples: List[WearableDailySummary]) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    steps = [float(s.steps) for s in samples if s.steps is not None]
    rhr = [float(s.resting_heart_rate_bpm) for s in samples if s.resting_heart_rate_bpm is not None]
    hrv = [float(s.hrv_rmssd_ms) for s in samples if s.hrv_rmssd_ms is not None]
    sleep = [float(s.sleep_hours) for s in samples if s.sleep_hours is not None]
    return _mean(steps), _mean(rhr), _mean(hrv), _mean(sleep)


def _merge_month(samples: List[WearableDailySummary]) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    return _merge_day(samples)


def _merge_year(samples: List[WearableDailySummary]) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    return _merge_day(samples)


def _year_from_label(label: str) -> int:
    return int(label[:4])


def build_trend_charts_json(
    rows: Sequence[WearableDailySummary],
    user_id: str,
    *,
    reference_date: Optional[date] = None,
) -> dict[str, Any]:
    """
    Build chart-ready series from raw wearable rows (same stratification as memory_engine).
    """
    ref = reference_date or date.today()
    uid = user_id.strip() or "default"

    if not rows:
        return TrendChartsPayload(
            reference_date=ref.isoformat(),
            user_id=uid,
            has_data=False,
            summaries={"global": "暂无穿戴数据，请先上传 Apple Health export.zip。"},
        ).as_dict()

    daily_recent: Dict[date, List[WearableDailySummary]] = defaultdict(list)
    daily_mid: Dict[date, List[WearableDailySummary]] = defaultdict(list)
    monthly: Dict[Tuple[int, int], List[WearableDailySummary]] = defaultdict(list)
    yearly: Dict[int, List[WearableDailySummary]] = defaultdict(list)

    for row in rows:
        if row.user_id != uid and row.user_id:
            continue
        if row.day > ref:
            continue
        age_days = (ref - row.day).days
        if age_days <= 90:
            daily_recent[row.day].append(row)
        elif age_days <= 365:
            daily_mid[row.day].append(row)
        elif age_days <= 365 * 3:
            monthly[(row.day.year, row.day.month)].append(row)
        else:
            yearly[row.day.year].append(row)

    steps_timeline: List[TrendPoint] = []
    rhr_timeline: List[TrendPoint] = []
    hrv_timeline: List[TrendPoint] = []
    sleep_yearly: List[TrendPoint] = []
    sleep_daily_90: List[TrendPoint] = []
    overlay_steps: List[TrendPoint] = []
    rhr_annotations: List[RhrAnnotation] = []

    for year in sorted(yearly.keys()):
        samples = yearly[year]
        st, rhr, hrv, sl = _merge_year(samples)
        ylabel = f"{year:04d}"
        if year >= STEPS_CHART_START_YEAR:
            steps_timeline.append(TrendPoint(label=ylabel, value=st, granularity="year"))
        rhr_timeline.append(TrendPoint(label=ylabel, value=rhr, granularity="year"))
        hrv_timeline.append(TrendPoint(label=ylabel, value=hrv, granularity="year"))
        sleep_yearly.append(TrendPoint(label=ylabel, value=sl, granularity="year"))

    for (year, month) in sorted(monthly.keys()):
        samples = monthly[(year, month)]
        st, rhr, hrv, sl = _merge_month(samples)
        label = f"{year:04d}-{month:02d}"
        if year >= STEPS_CHART_START_YEAR:
            steps_timeline.append(TrendPoint(label=label, value=st, granularity="month"))
        rhr_timeline.append(TrendPoint(label=label, value=rhr, granularity="month"))
        hrv_timeline.append(TrendPoint(label=label, value=hrv, granularity="month"))
        if rhr is not None and rhr > RHR_ALERT_THRESHOLD and label.startswith("2024-"):
            rhr_annotations.append(
                RhrAnnotation(label=label, value=rhr, note=f"静息心率偏高 {rhr:.0f} bpm"),
            )
        overlay_steps.append(TrendPoint(label=label, value=st, granularity="month"))

    for day in sorted(daily_mid.keys()):
        samples = daily_mid[day]
        st, rhr, hrv, sl = _merge_day(samples)
        label = day.isoformat()
        if day.year >= STEPS_CHART_START_YEAR:
            steps_timeline.append(TrendPoint(label=label, value=st, granularity="day"))
        rhr_timeline.append(TrendPoint(label=label, value=rhr, granularity="day"))
        hrv_timeline.append(TrendPoint(label=label, value=hrv, granularity="day"))
        overlay_steps.append(TrendPoint(label=label, value=st, granularity="day"))
        if rhr is not None and rhr > RHR_ALERT_THRESHOLD and label.startswith("2024-"):
            rhr_annotations.append(
                RhrAnnotation(label=label, value=rhr, note=f"静息心率偏高 {rhr:.0f} bpm"),
            )

    for day in sorted(daily_recent.keys()):
        samples = daily_recent[day]
        st, rhr, hrv, sl = _merge_day(samples)
        label = day.isoformat()
        if day.year >= STEPS_CHART_START_YEAR:
            steps_timeline.append(TrendPoint(label=label, value=st, granularity="day"))
        rhr_timeline.append(TrendPoint(label=label, value=rhr, granularity="day"))
        hrv_timeline.append(TrendPoint(label=label, value=hrv, granularity="day"))
        sleep_daily_90.append(TrendPoint(label=label, value=sl, granularity="day"))
        overlay_steps.append(TrendPoint(label=label, value=st, granularity="day"))
        if rhr is not None and rhr > RHR_ALERT_THRESHOLD and label.startswith("2024-"):
            rhr_annotations.append(
                RhrAnnotation(label=label, value=rhr, note=f"静息心率偏高 {rhr:.0f} bpm"),
            )

    # Deduplicate annotations by label (keep max RHR)
    ann_by_label: Dict[str, RhrAnnotation] = {}
    for ann in rhr_annotations:
        prev = ann_by_label.get(ann.label)
        if prev is None or ann.value > prev.value:
            ann_by_label[ann.label] = ann
    rhr_annotations = sorted(ann_by_label.values(), key=lambda a: a.label)

    steps_vals = [p.value for p in steps_timeline if p.value is not None]
    sleep_vals = [p.value for p in sleep_daily_90 + sleep_yearly if p.value is not None]

    summaries = {
        "sleep": _sleep_summary(sleep_yearly, sleep_daily_90),
        "steps": _steps_summary(steps_vals),
        "rhr": _rhr_summary(rhr_timeline, rhr_annotations),
        "hrv": _hrv_summary(hrv_timeline),
    }

    return TrendChartsPayload(
        reference_date=ref.isoformat(),
        user_id=uid,
        has_data=bool(steps_timeline or rhr_timeline or hrv_timeline or sleep_daily_90 or sleep_yearly),
        sleep={"yearly": [p.model_dump() for p in sleep_yearly], "daily_90d": [p.model_dump() for p in sleep_daily_90]},
        steps={"timeline": [p.model_dump() for p in steps_timeline]},
        rhr={"timeline": [p.model_dump() for p in rhr_timeline]},
        hrv={"timeline": [p.model_dump() for p in hrv_timeline]},
        steps_for_overlay=[p.model_dump() for p in overlay_steps[-120:]],
        rhr_annotations=[a.model_dump() for a in rhr_annotations],
        summaries=summaries,
    ).as_dict()


def _sleep_summary(yearly: List[TrendPoint], daily_90: List[TrendPoint]) -> str:
    parts: List[str] = []
    if yearly:
        ys = [p.value for p in yearly if p.value is not None]
        if ys:
            parts.append(f"长期年均睡眠约 {statistics.mean(ys):.1f} 小时")
    if daily_90:
        ds = [p.value for p in daily_90 if p.value is not None]
        if ds:
            parts.append(f"近 90 日日均 {statistics.mean(ds):.1f} 小时")
    return "；".join(parts) if parts else "睡眠数据不足"


def _steps_summary(vals: List[float]) -> str:
    if not vals:
        return "步数数据不足"
    lo, hi = min(vals), max(vals)
    return f"{STEPS_CHART_START_YEAR} 年至今：最低约 {lo:,.0f} 步，最高约 {hi:,.0f} 步（分层聚合）"


def _rhr_summary(timeline: List[TrendPoint], annotations: List[RhrAnnotation]) -> str:
    vals = [p.value for p in timeline if p.value is not None]
    base = f"静息心率样本 {len(vals)} 个时点"
    if annotations:
        peak = max(annotations, key=lambda a: a.value)
        return f"{base}；{peak.label} 附近出现异常高点（{peak.value:.0f} bpm）"
    return base


def _hrv_summary(timeline: List[TrendPoint]) -> str:
    vals = [p.value for p in timeline if p.value is not None]
    if not vals:
        return "HRV 数据不足"
    return f"HRV (RMSSD) 均值约 {statistics.mean(vals):.1f} ms，可叠加步数对照恢复"
