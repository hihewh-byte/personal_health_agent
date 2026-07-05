#!/usr/bin/env python3
"""Selfcheck: unified wearable daily rollup (P1-2)."""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pha.models import WearableDailySummary
from pha.wearable_daily_aggregator import (
    WearableDayMetricAgg,
    accumulate_wearable_sample,
    build_wearable_daily_summary,
    resolve_daily_metrics,
    sleep_metrics_from_segment_rows,
)


def test_resolve_daily_metrics_rhr_fallback() -> bool:
    agg = WearableDayMetricAgg(hr_sum=80.0, hr_n=2)
    m = resolve_daily_metrics(agg)
    if m["resting_heart_rate_bpm"] != 40.0:
        print("FAIL rhr fallback from hr", m)
        return False
    agg2 = WearableDayMetricAgg(rhr_sum=55.0, rhr_n=1, hr_sum=80.0, hr_n=2)
    m2 = resolve_daily_metrics(agg2)
    if m2["resting_heart_rate_bpm"] != 55.0:
        print("FAIL rhr prefers METRIC_RHR", m2)
        return False
    print("OK resolve_daily_metrics rhr fallback")
    return True


def test_steps_max_per_source() -> bool:
    agg = WearableDayMetricAgg()
    accumulate_wearable_sample("steps", 1000.0, "a|watch", agg)
    accumulate_wearable_sample("steps", 1200.0, "b|iphone", agg)
    accumulate_wearable_sample("steps", 900.0, "c|watch", agg)
    m = resolve_daily_metrics(agg)
    if m["steps"] != 1900:
        print("FAIL steps max across sources", m["steps"])
        return False
    print("OK steps max per source")
    return True


def test_sleep_segment_roundtrip() -> bool:
    base = datetime(2026, 6, 9, 23, 0, 0)
    deep_end = base + timedelta(hours=1, minutes=30)
    rem_end = deep_end + timedelta(minutes=45)
    awake_end = rem_end + timedelta(minutes=15)
    segment_rows = [
        {
            "start_time": base.isoformat(),
            "end_time": deep_end.isoformat(),
            "source_name": "watch",
            "sample_id": "HKCategoryTypeIdentifierSleepAnalysis|s|e|HKCategoryValueSleepAnalysisAsleepDeep|watch",
            "is_awake": 0,
        },
        {
            "start_time": deep_end.isoformat(),
            "end_time": rem_end.isoformat(),
            "source_name": "watch",
            "sample_id": "HKCategoryTypeIdentifierSleepAnalysis|s|e|HKCategoryValueSleepAnalysisAsleepREM|watch",
            "is_awake": 0,
        },
        {
            "start_time": rem_end.isoformat(),
            "end_time": awake_end.isoformat(),
            "source_name": "watch",
            "sample_id": "HKCategoryTypeIdentifierSleepAnalysis|awake|z",
            "is_awake": 1,
        },
    ]
    sleep_h, awake_h, deep_h, rem_h, first_start = sleep_metrics_from_segment_rows(segment_rows)
    if first_start != base or deep_h is None or rem_h is None or awake_h is None:
        print("FAIL sleep segment roundtrip", sleep_h, awake_h, deep_h, rem_h, first_start)
        return False
    print("OK sleep segment roundtrip")
    return True


def test_build_summary_sleep_only_preserves_metrics() -> bool:
    existing = WearableDailySummary(
        user_id="default",
        day=date(2026, 6, 9),
        steps=8000,
        hrv_rmssd_ms=42.5,
    )
    row = build_wearable_daily_summary(
        "default",
        date(2026, 6, 9),
        existing=existing,
        segment_rows=[],
        sleep_only=True,
    )
    if row.steps != 8000 or row.hrv_rmssd_ms != 42.5:
        print("FAIL sleep_only preserved metrics", row.steps, row.hrv_rmssd_ms)
        return False
    print("OK sleep_only preserves metrics")
    return True


def test_build_matches_legacy_metric_resolution() -> bool:
    """Offline parity: extracted aggregator vs inlined pre-P1-2 resolution."""
    agg = WearableDayMetricAgg()
    samples = [
        ("steps", 500.0, "x|watch"),
        ("steps", 700.0, "x|watch"),
        ("steps", 600.0, "y|phone"),
        ("rhr", 58.0, "a"),
        ("hrv", 33.0, "b"),
        ("active_energy", 12.5, "c"),
        ("active_energy", 7.5, "d"),
        ("spo2", 98.0, "e"),
        ("respiratory_rate", 14.0, "f"),
        ("vo2max", 42.0, "g"),
        ("wrist_temp", 36.5, "h"),
    ]
    for mt, val, sid in samples:
        accumulate_wearable_sample(mt, val, sid, agg)

    resolved = resolve_daily_metrics(agg)
    steps = max(agg.steps_by_source.values()) if agg.steps_by_source else None
    legacy = {
        "steps": steps,
        "resting_heart_rate_bpm": agg.rhr_sum / agg.rhr_n,
        "hrv_rmssd_ms": agg.hrv_sum / agg.hrv_n,
        "active_energy_kcal": agg.active_energy_sum,
        "spo2_pct": agg.spo2_sum / agg.spo2_n,
        "respiratory_rate_bpm": agg.respiratory_sum / agg.respiratory_n,
        "vo2max_ml_kg_min": agg.vo2max_sum / agg.vo2max_n,
        "wrist_temp_c": agg.wrist_temp_sum / agg.wrist_temp_n,
    }
    if resolved != legacy:
        print("FAIL legacy metric resolution", resolved, legacy)
        return False
    row = build_wearable_daily_summary("default", date(2026, 6, 9), metrics=agg)
    if row.steps != 1200 or row.active_energy_kcal != 20.0:
        print("FAIL build_wearable_daily_summary metrics", row.steps, row.active_energy_kcal)
        return False
    print("OK legacy metric resolution parity")
    return True


def main() -> int:
    ok = all(
        [
            test_resolve_daily_metrics_rhr_fallback(),
            test_steps_max_per_source(),
            test_sleep_segment_roundtrip(),
            test_build_summary_sleep_only_preserves_metrics(),
            test_build_matches_legacy_metric_resolution(),
        ],
    )
    print("pha_wearable_daily_aggregator_selfcheck:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
