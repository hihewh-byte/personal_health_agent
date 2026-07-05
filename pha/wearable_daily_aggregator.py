"""Shared wearable daily rollup: metrics + sleep (import, rebuild, segment refresh)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pha.data_processor import SleepSegment, compute_sleep_hours_union
from pha.date_parser import safe_parse_datetime
from pha.models import WearableDailySummary

# Keep in sync with ``pha.sqlite_storage`` metric_type values (no import — avoids cycle).
_METRIC_STEPS = "steps"
_METRIC_HEART_RATE = "heart_rate"
_METRIC_RHR = "rhr"
_METRIC_HRV = "hrv"
_METRIC_ACTIVE_ENERGY = "active_energy"
_METRIC_SPO2 = "spo2"
_METRIC_RESPIRATORY_RATE = "respiratory_rate"
_METRIC_VO2MAX = "vo2max"
_METRIC_WRIST_TEMP = "wrist_temp"


@dataclass
class WearableDayMetricAgg:
    """Per-calendar-day accumulators for non-sleep wearable metrics."""

    steps_by_source: Dict[str, int] = field(default_factory=dict)
    hr_sum: float = 0.0
    hr_n: int = 0
    rhr_sum: float = 0.0
    rhr_n: int = 0
    hrv_sum: float = 0.0
    hrv_n: int = 0
    active_energy_sum: float = 0.0
    spo2_sum: float = 0.0
    spo2_n: int = 0
    respiratory_sum: float = 0.0
    respiratory_n: int = 0
    vo2max_sum: float = 0.0
    vo2max_n: int = 0
    wrist_temp_sum: float = 0.0
    wrist_temp_n: int = 0


def accumulate_wearable_sample(
    metric_type: str,
    value: float,
    sample_id: str,
    agg: WearableDayMetricAgg,
) -> None:
    """Ingest one ``wearable_data`` row into daily metric accumulators."""
    mt = str(metric_type or "")
    if mt == _METRIC_STEPS:
        src = sample_id.rsplit("|", 1)[-1].strip() if "|" in sample_id else "unknown"
        agg.steps_by_source[src] = agg.steps_by_source.get(src, 0) + int(round(value))
    elif mt == _METRIC_HEART_RATE:
        agg.hr_sum += value
        agg.hr_n += 1
    elif mt == _METRIC_RHR:
        agg.rhr_sum += value
        agg.rhr_n += 1
    elif mt == _METRIC_HRV:
        agg.hrv_sum += value
        agg.hrv_n += 1
    elif mt == _METRIC_ACTIVE_ENERGY:
        agg.active_energy_sum += value
    elif mt == _METRIC_SPO2:
        agg.spo2_sum += value
        agg.spo2_n += 1
    elif mt == _METRIC_RESPIRATORY_RATE:
        agg.respiratory_sum += value
        agg.respiratory_n += 1
    elif mt == _METRIC_VO2MAX:
        agg.vo2max_sum += value
        agg.vo2max_n += 1
    elif mt == _METRIC_WRIST_TEMP:
        agg.wrist_temp_sum += value
        agg.wrist_temp_n += 1


def resolve_daily_metrics(agg: WearableDayMetricAgg) -> Dict[str, Any]:
    """Resolve optional daily metric fields from accumulators."""
    steps = max(agg.steps_by_source.values()) if agg.steps_by_source else None
    if agg.rhr_n > 0:
        rhr = agg.rhr_sum / agg.rhr_n
    elif agg.hr_n > 0:
        rhr = agg.hr_sum / agg.hr_n
    else:
        rhr = None
    hrv = (agg.hrv_sum / agg.hrv_n) if agg.hrv_n > 0 else None
    kcal = agg.active_energy_sum if agg.active_energy_sum > 0 else None
    spo2 = (agg.spo2_sum / agg.spo2_n) if agg.spo2_n > 0 else None
    resp = (agg.respiratory_sum / agg.respiratory_n) if agg.respiratory_n > 0 else None
    vo2 = (agg.vo2max_sum / agg.vo2max_n) if agg.vo2max_n > 0 else None
    wrist = (agg.wrist_temp_sum / agg.wrist_temp_n) if agg.wrist_temp_n > 0 else None
    return {
        "steps": steps,
        "resting_heart_rate_bpm": rhr,
        "hrv_rmssd_ms": hrv,
        "active_energy_kcal": kcal,
        "spo2_pct": spo2,
        "respiratory_rate_bpm": resp,
        "vo2max_ml_kg_min": vo2,
        "wrist_temp_c": wrist,
    }


def sleep_stage_hours_from_segment_rows(
    raw_segs: Sequence[Mapping[str, Any]],
) -> Tuple[Optional[float], Optional[float]]:
    """Sum deep/REM asleep segment durations (hours) from DB segment rows."""
    from pha.sleep_aggregator import sleep_stage_kind_from_sample_id

    deep_s = 0.0
    rem_s = 0.0
    for raw in raw_segs:
        if int(raw.get("is_awake") or 0):
            continue
        start = safe_parse_datetime(str(raw.get("start_time") or ""))
        end = safe_parse_datetime(str(raw.get("end_time") or ""))
        if start is None or end is None or end <= start:
            continue
        dur = (end - start).total_seconds()
        stage = sleep_stage_kind_from_sample_id(str(raw.get("sample_id") or ""))
        if stage == "deep":
            deep_s += dur
        elif stage == "rem":
            rem_s += dur
    deep_h = deep_s / 3600.0 if deep_s > 0 else None
    rem_h = rem_s / 3600.0 if rem_s > 0 else None
    return deep_h, rem_h


def sleep_metrics_from_segment_rows(
    raw_segs: Sequence[Mapping[str, Any]],
) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float], Optional[datetime]]:
    """Return sleep_h, awake_h, deep_h, rem_h, first_sleep_start from DB segment rows."""
    asleep: List[SleepSegment] = []
    awake_seconds = 0.0
    first_sleep_start: Optional[datetime] = None
    for raw in raw_segs:
        start = safe_parse_datetime(str(raw.get("start_time") or ""))
        end = safe_parse_datetime(str(raw.get("end_time") or ""))
        if start is None or end is None:
            continue
        if int(raw.get("is_awake") or 0):
            awake_seconds += max(0.0, (end - start).total_seconds())
        else:
            asleep.append(
                SleepSegment(
                    start=start,
                    end=end,
                    source_name=str(raw.get("source_name") or ""),
                    sample_id=str(raw.get("sample_id") or ""),
                ),
            )
            if first_sleep_start is None or start < first_sleep_start:
                first_sleep_start = start

    sleep_h, _ = compute_sleep_hours_union(asleep)
    awake_h = awake_seconds / 3600.0 if awake_seconds > 0 else None
    deep_h, rem_h = sleep_stage_hours_from_segment_rows(raw_segs)
    return (
        sleep_h if sleep_h > 0 else None,
        awake_h,
        deep_h,
        rem_h,
        first_sleep_start,
    )


def sleep_metrics_from_import_accumulators(
    *,
    sleep_segments: Sequence[SleepSegment],
    sleep_deep_seconds: float,
    sleep_rem_seconds: float,
    awake_seconds: float,
    first_sleep_start: Optional[datetime],
) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float], Optional[datetime]]:
    """Sleep fields during zip import (before segments are persisted)."""
    sleep_h, _ = compute_sleep_hours_union(list(sleep_segments))
    sleep_h = sleep_h if sleep_h > 0 else None
    deep_h = (sleep_deep_seconds / 3600.0) if sleep_deep_seconds > 0 else None
    rem_h = (sleep_rem_seconds / 3600.0) if sleep_rem_seconds > 0 else None
    awake_h = (awake_seconds / 3600.0) if awake_seconds > 0 else None
    return sleep_h, awake_h, deep_h, rem_h, first_sleep_start


def build_wearable_daily_summary(
    user_id: str,
    day: date,
    *,
    metrics: Optional[WearableDayMetricAgg] = None,
    segment_rows: Optional[Sequence[Mapping[str, Any]]] = None,
    import_sleep: Optional[tuple[Sequence[SleepSegment], float, float, float, Optional[datetime]]] = None,
    existing: Optional[WearableDailySummary] = None,
    sleep_only: bool = False,
) -> WearableDailySummary:
    """
    Build or patch a ``WearableDailySummary``.

    - ``metrics`` + optional ``segment_rows`` / ``import_sleep``: full day rollup.
    - ``sleep_only`` + ``segment_rows``: refresh sleep columns on ``existing`` row.
    """
    uid = (user_id or "default").strip() or "default"
    row = existing or WearableDailySummary(user_id=uid, day=day)

    if not sleep_only and metrics is not None:
        resolved = resolve_daily_metrics(metrics)
        row.steps = resolved["steps"]
        row.resting_heart_rate_bpm = resolved["resting_heart_rate_bpm"]
        row.hrv_rmssd_ms = resolved["hrv_rmssd_ms"]
        row.active_energy_kcal = resolved["active_energy_kcal"]
        row.spo2_pct = resolved["spo2_pct"]
        row.respiratory_rate_bpm = resolved["respiratory_rate_bpm"]
        row.vo2max_ml_kg_min = resolved["vo2max_ml_kg_min"]
        row.wrist_temp_c = resolved["wrist_temp_c"]

    if segment_rows is not None:
        sleep_h, awake_h, deep_h, rem_h, first_start = sleep_metrics_from_segment_rows(segment_rows)
        row.sleep_hours = sleep_h
        row.awake_duration_hours = awake_h
        row.sleep_deep_hours = deep_h
        row.sleep_rem_hours = rem_h
        row.sleep_start_time = first_start
    elif import_sleep is not None:
        segs, deep_s, rem_s, awake_s, first_start = import_sleep
        sleep_h, awake_h, deep_h, rem_h, first_start = sleep_metrics_from_import_accumulators(
            sleep_segments=segs,
            sleep_deep_seconds=deep_s,
            sleep_rem_seconds=rem_s,
            awake_seconds=awake_s,
            first_sleep_start=first_start,
        )
        row.sleep_hours = sleep_h
        row.awake_duration_hours = awake_h
        row.sleep_deep_hours = deep_h
        row.sleep_rem_hours = rem_h
        row.sleep_start_time = first_start

    return row
