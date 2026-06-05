"""Server-side health analytics — precomputed snapshots for LLM (no raw 90-day JSON)."""

from __future__ import annotations

import re
import statistics
from collections import defaultdict
from datetime import date
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from pha.data_integrity import validate_common_sense
from pha.medical_storage import (
    format_historical_baseline_block,
    format_medical_abnormal_blurb,
    format_medical_context_line,
)
from pha.models import WearableDailySummary


def _needs_medical_exercise_linkage(user_message: str) -> bool:
    text = (user_message or "").lower()
    triggers = (
        "hrv",
        "为什么",
        "为何",
        "不高",
        "偏低",
        "恢复",
        "体检",
        "血糖",
        "ldl",
        "hdl",
        "炎症",
        "crp",
        "运动",
        "睡眠",
    )
    return any(t in text or t in (user_message or "") for t in triggers)


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    if len(xs) < 5 or len(xs) != len(ys):
        return None
    mx = statistics.mean(xs)
    my = statistics.mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den_x = sum((x - mx) ** 2 for x in xs) ** 0.5
    den_y = sum((y - my) ** 2 for y in ys) ** 0.5
    if den_x == 0 or den_y == 0:
        return None
    return num / (den_x * den_y)


def _paired(
    rows: Sequence[WearableDailySummary],
    pick_a: Callable[[WearableDailySummary], Optional[float]],
    pick_b: Callable[[WearableDailySummary], Optional[float]],
) -> Tuple[List[float], List[float]]:
    xs: List[float] = []
    ys: List[float] = []
    for row in rows:
        a, b = pick_a(row), pick_b(row)
        if a is None or b is None:
            continue
        xs.append(float(a))
        ys.append(float(b))
    return xs, ys


def _monthly_means(rows: Sequence[WearableDailySummary]) -> Dict[str, Dict[str, Optional[float]]]:
    buckets: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        key = row.day.strftime("%Y-%m")
        if row.sleep_hours is not None:
            buckets[key]["sleep"].append(float(row.sleep_hours))
        if row.hrv_rmssd_ms is not None:
            buckets[key]["hrv"].append(float(row.hrv_rmssd_ms))
        if row.steps is not None:
            buckets[key]["steps"].append(float(row.steps))
        if row.resting_heart_rate_bpm is not None:
            buckets[key]["rhr"].append(float(row.resting_heart_rate_bpm))
        if row.awake_duration_hours is not None:
            buckets[key]["awake"].append(float(row.awake_duration_hours))
        if row.spo2_pct is not None:
            buckets[key]["spo2"].append(float(row.spo2_pct))
        if row.respiratory_rate_bpm is not None:
            buckets[key]["respiratory_rate"].append(float(row.respiratory_rate_bpm))
        if row.vo2max_ml_kg_min is not None:
            buckets[key]["vo2max"].append(float(row.vo2max_ml_kg_min))
        if row.wrist_temp_c is not None:
            buckets[key]["wrist_temp"].append(float(row.wrist_temp_c))
    return {
        month: {m: (float(statistics.mean(v)) if v else None) for m, v in metrics.items()}
        for month, metrics in sorted(buckets.items())
    }


def _lowest_hrv_days(rows: Sequence[WearableDailySummary], *, n: int = 5) -> List[WearableDailySummary]:
    with_hrv = [r for r in rows if r.hrv_rmssd_ms is not None]
    with_hrv.sort(key=lambda r: float(r.hrv_rmssd_ms))
    return with_hrv[:n]


def _aligned_hrv_kcal(
    rows: Sequence[WearableDailySummary],
    kcal_by_day: Dict[date, float],
) -> Tuple[List[float], List[float]]:
    xs: List[float] = []
    ys: List[float] = []
    for row in rows:
        if row.hrv_rmssd_ms is None:
            continue
        k = kcal_by_day.get(row.day)
        if k is None:
            continue
        xs.append(float(row.hrv_rmssd_ms))
        ys.append(float(k))
    return xs, ys


def build_analytics_snapshot(
    rows: Sequence[WearableDailySummary],
    *,
    start_date: date,
    end_date: date,
    reference_date: date,
    user_id: str = "default",
    user_message: str = "",
    metrics: Optional[Sequence[str]] = None,
    activity_kcal_daily: Optional[List[Tuple[date, float]]] = None,
) -> str:
    """
    Precomputed narrative for LLM.

    When ``metrics`` is set, only requested wearable dimensions appear in means / Pearson /
    monthly deltas (v2.2.2 — no steps-as-proxy for activity-only questions).
    """
    if not rows:
        return (
            f"User Data Snapshot（参考日{reference_date.isoformat()}，"
            f"{start_date.isoformat()}~{end_date.isoformat()}）："
            "无本地日聚合数据，请先上传 export.zip。"
        )

    mset = {str(x).strip().lower() for x in (metrics or ()) if str(x).strip()}
    dynamic = bool(mset)

    anomaly = validate_common_sense(rows)
    lines: List[str] = []
    if anomaly:
        lines.append(anomaly)
    lines.append(
        f"User Data Snapshot（SQLite预计算，参考日{reference_date.isoformat()}，"
        f"{start_date.isoformat()}~{end_date.isoformat()}，{len(rows)}天）：",
    )

    metric_specs: List[Tuple[str, Callable[[WearableDailySummary], Optional[float]]]] = []
    if not dynamic or "sleep" in mset:
        metric_specs.append(("睡眠", lambda r: r.sleep_hours))
    if not dynamic or "hrv" in mset:
        metric_specs.append(("HRV", lambda r: r.hrv_rmssd_ms))
    if not dynamic or "steps" in mset:
        metric_specs.append(("步数", lambda r: r.steps))
    if not dynamic or "rhr" in mset:
        metric_specs.append(("静息心率", lambda r: r.resting_heart_rate_bpm))
    if not dynamic or "spo2" in mset:
        metric_specs.append(("血氧", lambda r: r.spo2_pct))
    if not dynamic or "respiratory_rate" in mset:
        metric_specs.append(("呼吸率", lambda r: r.respiratory_rate_bpm))
    if not dynamic or "vo2max" in mset:
        metric_specs.append(("VO2max", lambda r: r.vo2max_ml_kg_min))
    if not dynamic or "wrist_temp" in mset:
        metric_specs.append(("手腕体温", lambda r: r.wrist_temp_c))
    if not dynamic:
        metric_specs.append(("清醒", lambda r: r.awake_duration_hours))

    for label, pick in metric_specs:
        vals = [float(pick(r)) for r in rows if pick(r) is not None]
        if vals:
            lines.append(
                f"{label}均值{statistics.mean(vals):.1f}[{min(vals):.1f}-{max(vals):.1f}]；",
            )

    pearsons: List[Tuple[str, Callable, Callable]] = []
    if not dynamic or ("steps" in mset and "hrv" in mset):
        pearsons.append(("步数-HRV", lambda r: r.steps, lambda r: r.hrv_rmssd_ms))
    if not dynamic or ("sleep" in mset and "hrv" in mset):
        pearsons.append(("睡眠-HRV", lambda r: r.sleep_hours, lambda r: r.hrv_rmssd_ms))
    if not dynamic or ("rhr" in mset and "hrv" in mset):
        pearsons.append(("静息心率-HRV", lambda r: r.resting_heart_rate_bpm, lambda r: r.hrv_rmssd_ms))

    for name, pa, pb in pearsons:
        xs, ys = _paired(rows, pa, pb)
        r = _pearson(xs, ys)
        if r is not None:
            lines.append(f"Pearson {name}={r:+.2f}(n={len(xs)})；")

    if (not dynamic or "activity_kcal" in mset) and activity_kcal_daily:
        vals = [float(v) for _, v in activity_kcal_daily if v is not None]
        if vals:
            lines.append(
                f"活动消耗日均{statistics.mean(vals):.0f}kcal（n={len(vals)}，wearable_daily/兜底 wearable_data）；",
            )
        kmap = {d: v for d, v in activity_kcal_daily}
        xs, ys = _aligned_hrv_kcal(rows, kmap)
        r = _pearson(xs, ys)
        if r is not None:
            lines.append(f"Pearson 活动消耗(kcal)-HRV={r:+.2f}(n={len(xs)})；")
        elif dynamic and "activity_kcal" in mset:
            lines.append("活动消耗(kcal)与 HRV 对齐日不足，无法计算 Pearson；")
    elif dynamic and "activity_kcal" in mset and not activity_kcal_daily:
        lines.append(
            "活动消耗(kcal)：本地库无日序列（wearable_daily.active_energy_kcal 与 wearable_data 均为空），"
            "禁止臆造千卡均值；请确认 export.zip 含 ActiveEnergyBurned 或重新导入。",
        )

    monthly = _monthly_means(rows)
    if len(monthly) >= 2:
        months = sorted(monthly.keys())
        last_m, prev_m = months[-1], months[-2]
        lm, pm = monthly[last_m], monthly[prev_m]
        parts: List[str] = []
        month_keys = (
            [("hrv", "HRV"), ("sleep", "睡眠"), ("steps", "步数")]
            if not dynamic
            else [(k, lbl) for k, lbl in (("hrv", "HRV"), ("sleep", "睡眠"), ("steps", "步数")) if k in mset]
        )
        for mk, label in month_keys:
            a, b = lm.get(mk), pm.get(mk)
            if a is not None and b is not None:
                delta = a - b
                sign = "+" if delta >= 0 else ""
                parts.append(f"{label}{prev_m}→{last_m}{sign}{delta:.1f}")
        if parts:
            lines.append("月度对比：" + "，".join(parts) + "；")

    lows = _lowest_hrv_days(rows, n=5)
    if lows:
        anomaly_parts: List[str] = []
        for r in lows:
            start_s = r.sleep_start_time.strftime("%H:%M") if r.sleep_start_time else "—"
            awake_s = f"{r.awake_duration_hours:.2f}h" if r.awake_duration_hours is not None else "—"
            if not dynamic or "steps" in mset:
                steps_s = str(int(r.steps)) if r.steps is not None else "—"
                tail = f"步{steps_s},清醒{awake_s},入睡{start_s}"
            else:
                tail = f"清醒{awake_s},入睡{start_s}"
            anomaly_parts.append(
                f"{r.day.isoformat()}:HRV={r.hrv_rmssd_ms:.0f}ms,{tail}",
            )
        lines.append("HRV最低5日：" + " | ".join(anomaly_parts) + "。")

    baseline = format_historical_baseline_block(user_id, reference_date)
    if baseline:
        lines.append(baseline)

    year_compare = bool(re.search(r"20\d{2}", user_message or "")) and re.search(
        r"对比|比较|ldl|血脂|低密度",
        user_message or "",
        re.I,
    )
    link_medical = _needs_medical_exercise_linkage(user_message) and not year_compare
    medical_context = ""
    if link_medical:
        medical_context = format_medical_context_line(user_id, reference_date)
        if medical_context and medical_context not in "".join(lines):
            lines.append(medical_context)

    medical_blurb = format_medical_abnormal_blurb(user_id, reference_date)
    if medical_blurb and medical_blurb not in "".join(lines):
        lines.append(medical_blurb)

    text = "".join(lines)
    max_len = 720 if baseline else (480 if (medical_blurb or medical_context) else 300)
    if len(text) > max_len:
        return text[: max_len - 1] + "…"
    return text


def build_wearable_macro_analytics_snapshot(
    rows: Sequence[WearableDailySummary],
    *,
    start_date: date,
    end_date: date,
    reference_date: date,
    user_message: str = "",
    metrics: Optional[Sequence[str]] = None,
) -> str:
    """
    Macro-only narrative for wearable screenshot-compare turns.

    Omits per-metric means/ranges and HRV-lowest-day tables so LLM cannot hijack
    them for 90d compare (CompareTable remains the SSO for compare digits).
    """
    if not rows:
        return ""

    mset = {str(x).strip().lower() for x in (metrics or ()) if str(x).strip()}
    dynamic = bool(mset)

    lines: List[str] = []
    anomaly = validate_common_sense(rows)
    if anomaly:
        lines.append(anomaly)
    lines.append(
        f"区间 {start_date.isoformat()}～{end_date.isoformat()}，共 {len(rows)} 天有效记录。",
    )

    pearsons: List[Tuple[str, Callable, Callable]] = []
    if not dynamic or ("steps" in mset and "hrv" in mset):
        pearsons.append(("步数-HRV", lambda r: r.steps, lambda r: r.hrv_rmssd_ms))
    if not dynamic or ("sleep" in mset and "hrv" in mset):
        pearsons.append(("睡眠-HRV", lambda r: r.sleep_hours, lambda r: r.hrv_rmssd_ms))
    if not dynamic or ("rhr" in mset and "hrv" in mset):
        pearsons.append(("静息心率-HRV", lambda r: r.resting_heart_rate_bpm, lambda r: r.hrv_rmssd_ms))

    for name, pa, pb in pearsons:
        xs, ys = _paired(rows, pa, pb)
        r = _pearson(xs, ys)
        if r is not None:
            lines.append(f"Pearson {name}={r:+.2f}(n={len(xs)})；")

    monthly = _monthly_means(rows)
    if len(monthly) >= 2:
        months = sorted(monthly.keys())
        last_m, prev_m = months[-1], months[-2]
        lm, pm = monthly[last_m], monthly[prev_m]
        parts: List[str] = []
        month_keys = (
            [("hrv", "HRV"), ("sleep", "睡眠"), ("steps", "步数")]
            if not dynamic
            else [(k, lbl) for k, lbl in (("hrv", "HRV"), ("sleep", "睡眠"), ("steps", "步数")) if k in mset]
        )
        for mk, label in month_keys:
            a, b = lm.get(mk), pm.get(mk)
            if a is not None and b is not None:
                delta = a - b
                sign = "+" if delta >= 0 else ""
                parts.append(f"{label}{prev_m}→{last_m}{sign}{delta:.1f}")
        if parts:
            lines.append("月度变化：" + "，".join(parts) + "；")

    return "".join(lines)
