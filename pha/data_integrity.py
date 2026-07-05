"""Data deduplication, sleep re-aggregation, and LLM common-sense guards."""

from __future__ import annotations

import logging
import statistics
from typing import List, Sequence

from pydantic import BaseModel

from pha.models import WearableDailySummary
from pha.sqlite_storage import (
    dedupe_wearable_data,
    load_wearable_rows,
    rebuild_daily_sleep_from_segments,
)
from pha.store import store

logger = logging.getLogger(__name__)

SLEEP_HOURS_MAX = 14.0
RHR_BPM_MIN = 30.0
STEPS_DAY_MAX = 60_000
STEPS_DAY_WARN = 20_000
STEPS_KCAL_PER_1K_WARN = 30.0
SPO2_PCT_MAX = 100.0
RESPIRATORY_BPM_MAX = 40.0
VO2MAX_MAX = 90.0


class RecomputeResult(BaseModel):
    ok: bool = True
    user_id: str
    wearable_rows_removed: int = 0
    sleep_segments_removed: int = 0
    days_sleep_rebuilt: int = 0
    message: str = ""


def validate_common_sense(rows: Sequence[WearableDailySummary]) -> str:
    """
    Return warning block for LLM context when daily rollups look sensor-overlapped.
    """
    issues: List[str] = []
    for row in rows:
        d = row.day.isoformat()
        if row.sleep_hours is not None and row.sleep_hours > SLEEP_HOURS_MAX:
            issues.append(f"{d} sleep={row.sleep_hours:.1f}h (>14h)")
        if row.resting_heart_rate_bpm is not None and row.resting_heart_rate_bpm < RHR_BPM_MIN:
            issues.append(f"{d} RHR={row.resting_heart_rate_bpm:.0f}bpm (<30)")
        if row.steps is not None and row.steps > STEPS_DAY_MAX:
            issues.append(f"{d} steps={row.steps:,} (>60k)")
        elif row.steps is not None and row.steps > STEPS_DAY_WARN:
            issues.append(f"{d} steps={row.steps:,} (>20k, check multi-source overlap)")
        if row.spo2_pct is not None and row.spo2_pct > SPO2_PCT_MAX:
            issues.append(f"{d} SpO2={row.spo2_pct:.0f}% (>100)")
        if row.respiratory_rate_bpm is not None and row.respiratory_rate_bpm > RESPIRATORY_BPM_MAX:
            issues.append(f"{d} RR={row.respiratory_rate_bpm:.0f}/min (>40)")
        if row.vo2max_ml_kg_min is not None and row.vo2max_ml_kg_min > VO2MAX_MAX:
            issues.append(f"{d} VO2max={row.vo2max_ml_kg_min:.0f} (>90)")

    coherence = _steps_kcal_coherence_note(rows)
    if coherence:
        issues.append(coherence)

    if not issues:
        return ""

    detail = "; ".join(issues[:8])
    if len(issues) > 8:
        detail += f"; …+{len(issues) - 8} more"
    return (
        "[Data Anomaly Warning] Abnormal cumulative value detected for this date. "
        "Potential sensor overlap or duplicate import. "
        f"Flagged: {detail}. "
        "Interpret trends cautiously and mention data quality if relevant."
    )


def _steps_kcal_coherence_note(rows: Sequence[WearableDailySummary]) -> str:
    """Flag when daily steps look inflated relative to active energy (typical walk ~40–50 kcal/1k steps)."""
    ratios: List[float] = []
    for row in rows:
        if (
            row.steps is not None
            and row.steps >= 5000
            and row.active_energy_kcal is not None
            and row.active_energy_kcal > 0
        ):
            ratios.append(float(row.active_energy_kcal) / float(row.steps) * 1000.0)
    if len(ratios) < 5:
        return ""
    med = statistics.median(ratios)
    if med >= STEPS_KCAL_PER_1K_WARN:
        return ""
    return (
        f"steps vs active_energy median {med:.0f} kcal/1000 steps (<{STEPS_KCAL_PER_1K_WARN:.0f}); "
        "steps may be multi-device inflated — re-import export.zip recommended"
    )


def run_startup_data_audit() -> dict:
    """Dedupe ``wearable_data`` / sleep segments on service boot."""
    from pha.data_audit import clear_ingest_traces
    from pha.medical_storage import purge_harness_test_ldl_seed_rows, purge_invalid_ldl_metrics

    wd_removed, seg_removed = dedupe_wearable_data()
    harness_purged = purge_harness_test_ldl_seed_rows()
    if harness_purged:
        clear_ingest_traces()
    ldl_purged = purge_invalid_ldl_metrics()
    msg = (
        f"startup dedupe: wearable_data -{wd_removed}, sleep_segments -{seg_removed}; "
        f"harness LDL seed purged={harness_purged}; invalid LDL purged={ldl_purged}"
    )
    logger.info(msg)
    return {
        "wearable_data_removed": wd_removed,
        "sleep_segments_removed": seg_removed,
        "harness_ldl_seed_purged": harness_purged,
        "invalid_ldl_purged": ldl_purged,
        "message": msg,
    }


def recompute_user_data_integrity(user_id: str) -> RecomputeResult:
    """
    Dedupe raw samples, rebuild daily sleep from segment union, refresh in-memory store.
    """
    uid = (user_id or "default").strip() or "default"
    wd_removed, seg_removed = dedupe_wearable_data(user_id=uid)
    days_rebuilt = rebuild_daily_sleep_from_segments(uid)
    from pha.workout_storage import rebuild_workout_daily_rollup

    rebuild_workout_daily_rollup(uid)

    rows = load_wearable_rows(uid)
    if rows:
        store.replace_wearable_rows_in_memory(uid, rows)

    return RecomputeResult(
        user_id=uid,
        wearable_rows_removed=wd_removed,
        sleep_segments_removed=seg_removed,
        days_sleep_rebuilt=days_rebuilt,
        message=(
            f"已优化：删除重复样本 {wd_removed} 条、重复睡眠片段 {seg_removed} 条，"
            f"重算 {days_rebuilt} 天睡眠并集与深睡/REM 分期。"
        ),
    )
