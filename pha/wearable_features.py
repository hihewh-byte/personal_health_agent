"""Wearable multidimensional temporal feature extraction for PHA global audit."""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from pha.date_parser import safe_parse_datetime
from pha.health_data import effective_query_reference_date
from pha.models import WearableDailySummary
from pha.sqlite_storage import (
    query_sleep_segments_in_range,
    query_wearable_daily_range,
    query_wearable_hr_samples_in_range,
)

WEARABLE_FEATURE_WINDOW_DAYS = 90


def _mean(vals: Sequence[float]) -> Optional[float]:
    if not vals:
        return None
    return float(statistics.mean(vals))


def _pct(part: float, whole: float) -> Optional[float]:
    if whole <= 0:
        return None
    return 100.0 * part / whole


def _linreg_slope(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    if len(xs) < 8 or len(xs) != len(ys):
        return None
    mx = statistics.mean(xs)
    my = statistics.mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    return num / den


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    if len(xs) < 6 or len(xs) != len(ys):
        return None
    mx, my = statistics.mean(xs), statistics.mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den_x = sum((x - mx) ** 2 for x in xs) ** 0.5
    den_y = sum((y - my) ** 2 for y in ys) ** 0.5
    if den_x == 0 or den_y == 0:
        return None
    return num / (den_x * den_y)


def _sleep_stage_from_sample_id(sample_id: str) -> str:
    parts = (sample_id or "").split("|")
    if len(parts) < 4:
        return "unknown"
    v = parts[3].lower()
    if "awake" in v:
        return "awake"
    if "deep" in v:
        return "deep"
    if "rem" in v:
        return "rem"
    if "core" in v:
        return "core"
    if "asleep" in v:
        return "asleep"
    return "unknown"


def _segment_duration_hours(seg: dict) -> float:
    start = safe_parse_datetime(seg.get("start_time"))
    end = safe_parse_datetime(seg.get("end_time"))
    if start is None or end is None or end <= start:
        return 0.0
    return (end - start).total_seconds() / 3600.0


def _aggregate_sleep_stages(segments: Sequence[dict]) -> Dict[str, float]:
    totals: Dict[str, float] = defaultdict(float)
    for seg in segments:
        if int(seg.get("is_awake") or 0):
            totals["awake"] += _segment_duration_hours(seg)
            continue
        stage = _sleep_stage_from_sample_id(str(seg.get("sample_id") or ""))
        totals[stage] += _segment_duration_hours(seg)
    return totals


def _hrv_trend_label(rows: Sequence[WearableDailySummary]) -> str:
    ordered = sorted(
        [r for r in rows if r.hrv_rmssd_ms is not None],
        key=lambda r: r.day,
    )
    if len(ordered) < 14:
        return "数据不足，无法判断 90 日 HRV 趋势"
    xs = [(r.day - ordered[0].day).days for r in ordered]
    ys = [float(r.hrv_rmssd_ms) for r in ordered]
    slope = _linreg_slope(xs, ys)
    if slope is None:
        return "波动平稳"
    first30 = _mean([float(r.hrv_rmssd_ms) for r in ordered[:30]])
    last30 = _mean([float(r.hrv_rmssd_ms) for r in ordered[-30:]])
    if slope > 0.15:
        trend = "上升稳态（自主神经恢复向好）"
    elif slope < -0.15:
        trend = "断崖式下跌或持续走低（需警惕慢性疲劳/过度训练）"
    else:
        trend = "横盘波动"
    if first30 is not None and last30 is not None:
        delta = last30 - first30
        trend += f"；前30日均 {first30:.0f}ms → 近30日均 {last30:.0f}ms（Δ{delta:+.0f}ms）"
    return trend


def _weekly_steps_trend(rows: Sequence[WearableDailySummary]) -> List[str]:
    buckets: Dict[str, List[int]] = defaultdict(list)
    for r in rows:
        if r.steps is not None:
            buckets[r.day.strftime("%Y-W%W")].append(int(r.steps))
    lines: List[str] = []
    for wk in sorted(buckets.keys())[-13:]:
        vals = buckets[wk]
        lines.append(f"  - {wk}: 周均步数 {int(round(statistics.mean(vals))):,}（{len(vals)} 天）")
    return lines


def _high_intensity_proxy_hours(
    hr_samples: Sequence[tuple],
    rhr_mean: Optional[float],
) -> Tuple[float, float]:
    """Estimate high-intensity hours from HR samples above dynamic threshold."""
    threshold = max(100.0, (rhr_mean or 65.0) * 1.35)
    if not hr_samples:
        return 0.0, threshold
    hi_minutes = sum(1 for _, bpm in hr_samples if bpm >= threshold)
    # Each sample ≈ 1 observation; scale to hours conservatively (cap per day handled upstream)
    return hi_minutes / 60.0, threshold


def build_sleep_panorama_block(
    rows: Sequence[WearableDailySummary],
    segments: Sequence[dict],
) -> str:
    sleep_vals = [float(r.sleep_hours) for r in rows if r.sleep_hours is not None]
    waso_vals = [float(r.awake_duration_hours) for r in rows if r.awake_duration_hours is not None]

    stage_totals = _aggregate_sleep_stages(segments)
    tst = (
        stage_totals.get("deep", 0)
        + stage_totals.get("rem", 0)
        + stage_totals.get("core", 0)
        + stage_totals.get("asleep", 0)
    )
    deep_h = stage_totals.get("deep", 0)
    rem_h = stage_totals.get("rem", 0)
    deep_pct = _pct(deep_h, tst) if tst > 0 else None
    rem_pct = _pct(rem_h, tst) if tst > 0 else None

    lines = [
        "【睡眠多维全景 · 近90日】",
        f"- 平均总睡眠时长: {_fmt(_mean(sleep_vals) if sleep_vals else None, 'h', 2)}（有效日 n={len(sleep_vals)}）",
    ]
    if deep_pct is not None and rem_pct is not None:
        lines.append(
            f"- 深睡比例 / REM 比例（Apple 分段聚合）: {deep_pct:.1f}% / {rem_pct:.1f}%"
            f"（深睡 {deep_h:.1f}h + REM {rem_h:.1f}h / TST {tst:.1f}h）",
        )
    else:
        lines.append("- 深睡/REM 比例: 分段元数据不足，以下以日级 sleep_hours + WASO 代理")

    lines.append(
        f"- 夜间清醒总时长 WASO 均值: {_fmt(_mean(waso_vals) if waso_vals else None, 'h', 2)}"
        f"（有效日 n={len(waso_vals)}）",
    )

    if waso_vals:
        top_waso = sorted(
            [r for r in rows if r.awake_duration_hours is not None],
            key=lambda r: float(r.awake_duration_hours),
            reverse=True,
        )[:5]
        lines.append("- WASO Top5 异常日（清醒最长）:")
        for r in top_waso:
            sleep_s = f"{r.sleep_hours:.2f}h" if r.sleep_hours is not None else "—"
            hrv_s = f"{r.hrv_rmssd_ms:.0f}ms" if r.hrv_rmssd_ms is not None else "—"
            lines.append(
                f"  · {r.day.isoformat()}: 清醒 {r.awake_duration_hours:.2f}h"
                f"，总睡 {sleep_s}，HRV {hrv_s}",
            )

    if len(waso_vals) >= 14:
        ordered = sorted(
            [r for r in rows if r.awake_duration_hours is not None],
            key=lambda r: r.day,
        )
        xs = [(r.day - ordered[0].day).days for r in ordered]
        ys = [float(r.awake_duration_hours) for r in ordered]
        slope = _linreg_slope(xs, ys)
        if slope is not None:
            if slope > 0.02:
                lines.append(f"- WASO 趋势: 上升（+{slope:.3f} h/日），夜间碎片化加重风险")
            elif slope < -0.02:
                lines.append(f"- WASO 趋势: 下降（{slope:.3f} h/日），睡眠连续性改善")
            else:
                lines.append("- WASO 趋势: 相对稳定")

    return "\n".join(lines)


def build_hrv_block(rows: Sequence[WearableDailySummary]) -> str:
    hrv_vals = [float(r.hrv_rmssd_ms) for r in rows if r.hrv_rmssd_ms is not None]
    rhr_vals = [float(r.resting_heart_rate_bpm) for r in rows if r.resting_heart_rate_bpm is not None]
    return "\n".join(
        [
            "【自主神经张力（HRV）时序 · 近90日】",
            f"- HRV(RMSSD) 均值: {_fmt(_mean(hrv_vals) if hrv_vals else None, 'ms', 0)}（n={len(hrv_vals)}）",
            f"- 静息心率 RHR 均值: {_fmt(_mean(rhr_vals) if rhr_vals else None, 'bpm', 1)}（n={len(rhr_vals)}）",
            f"- 90日波动曲线研判: {_hrv_trend_label(rows)}",
        ],
    )


def build_exercise_load_block(
    rows: Sequence[WearableDailySummary],
    hr_samples: Sequence[tuple],
) -> str:
    step_vals = [int(r.steps) for r in rows if r.steps is not None]
    rhr_mean = _mean([float(r.resting_heart_rate_bpm) for r in rows if r.resting_heart_rate_bpm is not None])
    hi_h, thr = _high_intensity_proxy_hours(hr_samples, rhr_mean)

    lines = [
        "【运动负荷 · 近90日】",
        f"- 日均步数: {_fmt(step_vals and statistics.mean(step_vals), '步', 0)}（有效日 n={len(step_vals)}）",
        f"- 高强度活跃时间（HR≥{thr:.0f}bpm 样本折算）: 约 {hi_h:.1f} 小时",
        "- 每周步数消耗趋势（周均）:",
    ]
    weekly = _weekly_steps_trend(rows)
    lines.extend(weekly if weekly else ["  - （无步数周数据）"])
    return "\n".join(lines)


def build_causal_cross_hints(
    rows: Sequence[WearableDailySummary],
) -> str:
    xs_steps: List[float] = []
    ys_waso: List[float] = []
    xs_steps_hrv: List[float] = []
    ys_hrv: List[float] = []
    for r in rows:
        if r.steps is not None and r.awake_duration_hours is not None:
            xs_steps.append(float(r.steps))
            ys_waso.append(float(r.awake_duration_hours))
        if r.steps is not None and r.hrv_rmssd_ms is not None:
            xs_steps_hrv.append(float(r.steps))
            ys_hrv.append(float(r.hrv_rmssd_ms))

    r_steps_waso = _pearson(xs_steps, ys_waso)
    r_steps_hrv = _pearson(xs_steps_hrv, ys_hrv)

    lines = [
        "【三维因果交叉矩阵 · Python 预计算提示（供 R1 推演，非最终结论）】",
        "关联 A【运动量 vs 夜间清醒 WASO】:",
    ]
    if r_steps_waso is not None:
        lines.append(
            f"  - Pearson(日步数, WASO) = {r_steps_waso:+.2f} (n={len(xs_steps)})；"
            "请结合高步数/缺乏运动日与 Top5 清醒日对齐，判断皮质醇回落与过度疲劳假说。",
        )
    else:
        lines.append("  - 配对数据不足，请定性对照周步数趋势与 WASO Top5。")

    lines.append("关联 B【体检化验 vs HRV/WASO】: 仅对照卷宗中已查询到的化验实测项；")
    if r_steps_hrv is not None:
        lines.append(f"  - Pearson(日步数, HRV) = {r_steps_hrv:+.2f} (n={len(xs_steps_hrv)})。")
    return "\n".join(lines)


def _fmt(val: Optional[float], unit: str, digits: int) -> str:
    if val is None:
        return "—"
    if unit == "步":
        return f"{val:,.0f} {unit}"
    return f"{val:.{digits}f} {unit}"


def build_wearable_temporal_dossier_for_window(
    user_id: str,
    start_date: date,
    end_date: date,
    *,
    label: str = "",
    reference_date: Optional[date] = None,
) -> str:
    """Wearable feature block for an arbitrary inclusive date window."""
    uid = (user_id or "default").strip() or "default"
    ref = reference_date or effective_query_reference_date()
    if end_date < start_date:
        start_date, end_date = end_date, start_date

    rows = query_wearable_daily_range(uid, start_date, end_date)
    if not rows:
        head = label or f"{start_date.isoformat()}~{end_date.isoformat()}"
        return f"【可穿戴时序 · {head}】\n（该窗口无日聚合数据）"

    segments = query_sleep_segments_in_range(uid, start_date, end_date)
    hr_samples = query_wearable_hr_samples_in_range(uid, start_date, end_date)
    window_days = (end_date - start_date).days + 1
    title = label or f"{start_date.isoformat()}~{end_date.isoformat()}"
    blocks = [
        f"=== 可穿戴时序特征 · {title}（{window_days}日窗 · {len(rows)} 有效日 · 分段 n={len(segments)}）===",
        build_sleep_panorama_block(rows, segments),
        build_hrv_block(rows),
        build_exercise_load_block(rows, hr_samples),
        build_causal_cross_hints(rows),
    ]
    return "\n\n".join(blocks)


def build_wearable_temporal_dossier(
    user_id: str,
    *,
    reference_date: Optional[date] = None,
    window_days: int = WEARABLE_FEATURE_WINDOW_DAYS,
) -> str:
    """Multidimensional wearable feature text (global audit default window)."""
    ref = reference_date or effective_query_reference_date()
    start = ref - timedelta(days=max(1, window_days) - 1)
    return build_wearable_temporal_dossier_for_window(
        user_id,
        start,
        ref,
        label=f"近{window_days}日",
        reference_date=ref,
    )
