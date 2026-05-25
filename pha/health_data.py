"""Queryable local health metrics + Apple Health import integrity checks."""

from __future__ import annotations

import logging
import os
import statistics
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

from pha.date_parser import safe_parse_date

from pha.health_analytics import build_analytics_snapshot
from pha.sqlite_storage import (
    count_wearable_samples,
    get_max_wearable_timestamp,
    query_wearable_daily_range,
)
from pha.store import store

logger = logging.getLogger(__name__)

# Optional demo / fixture “present day” floor (ISO YYYY-MM-DD). When unset, queries use real ``date.today()``.
# Set e.g. ``PHA_ENV_DEMO_ANCHOR=2026-05-15`` for local databases whose exports end in the future relative to OS clock.
_PHA_ENV_DEMO_ANCHOR_RAW = (os.environ.get("PHA_ENV_DEMO_ANCHOR") or "").strip()


def _optional_demo_anchor_date() -> Optional[date]:
    if not _PHA_ENV_DEMO_ANCHOR_RAW:
        return None
    return safe_parse_date(_PHA_ENV_DEMO_ANCHOR_RAW[:10])


def effective_query_reference_date() -> date:
    """Upper-bound calendar day for SQLite range queries and UI alignment (v2.2.3)."""
    today = date.today()
    anchor = _optional_demo_anchor_date()
    if anchor is not None:
        return max(anchor, today)
    return today


def build_system_date_block(reference_date: Optional[date] = None) -> str:
    """Single runtime string for LLM “today” alignment (replaces hard-coded SYSTEM_DATE_BLOCK)."""
    ref = reference_date or effective_query_reference_date()
    return (
        f'[SYSTEM BLOCK: TODAY IS {ref.isoformat()}. '
        f'USE THIS AS THE BASE FOR ANY "RECENT" QUERY.]\n\n'
    )


def clamp_tool_query_window(
    start_date: date,
    end_date: date,
    *,
    reference_date: Optional[date] = None,
    max_days: int = 365,
) -> tuple[date, date, Optional[str]]:
    """Clamp tool/API query windows to [ref - max_days, ref] (v2.2.4)."""
    ref = reference_date or effective_query_reference_date()
    lo = ref - timedelta(days=max(1, max_days) - 1)
    hi = ref
    orig_start, orig_end = start_date, end_date
    if end_date > hi:
        end_date = hi
    if start_date < lo:
        start_date = lo
    if end_date < start_date:
        start_date, end_date = end_date, start_date
    note: Optional[str] = None
    if (orig_start, orig_end) != (start_date, end_date):
        note = (
            f"查询窗口已钳制为 {start_date.isoformat()}～{end_date.isoformat()} "
            f"（参考日 {ref.isoformat()}，最长 {max_days} 天）。"
        )
    return start_date, end_date, note

CORE_WEARABLE_METRICS = frozenset({"sleep", "hrv", "steps", "rhr", "activity_kcal"})
EXTENSION_WEARABLE_METRICS = frozenset(
    {"spo2", "respiratory_rate", "vo2max", "wrist_temp"},
)
ALLOWED_METRICS = CORE_WEARABLE_METRICS | EXTENSION_WEARABLE_METRICS
METRICS_REGISTRY = ALLOWED_METRICS  # v2.2.9-p1.5 — tools / validation / analytics

METRIC_ALIASES: Dict[str, str] = {
    "sleep": "sleep",
    "sleep_hours": "sleep",
    "hrv": "hrv",
    "hrv_rmssd": "hrv",
    "steps": "steps",
    "step": "steps",
    "rhr": "rhr",
    "resting_heart_rate": "rhr",
    "heart_rate": "rhr",
    "activity_kcal": "activity_kcal",
    "active_energy": "activity_kcal",
    "kcal": "activity_kcal",
    "calories": "activity_kcal",
    "spo2": "spo2",
    "blood_oxygen": "spo2",
    "oxygen_saturation": "spo2",
    "血氧": "spo2",
    "respiratory_rate": "respiratory_rate",
    "resp_rate": "respiratory_rate",
    "呼吸率": "respiratory_rate",
    "vo2max": "vo2max",
    "vo2_max": "vo2max",
    "最大摄氧量": "vo2max",
    "wrist_temp": "wrist_temp",
    "wrist_temperature": "wrist_temp",
    "body_temperature": "wrist_temp",
    "体温": "wrist_temp",
    "手腕温度": "wrist_temp",
}


class ImportIncompleteError(RuntimeError):
    """Raised when SQLite max timestamp lags behind export.xml (silent partial import)."""


class ImportIntegrityReport(BaseModel):
    ok: bool
    user_id: str
    xml_max_timestamp: str = ""
    db_max_timestamp: str = ""
    wearable_samples: int = 0
    daily_rows: int = 0
    message: str = ""


class HealthDataPoint(BaseModel):
    date: str
    value: Optional[float] = None


class MetricSummary(BaseModel):
    metric: str
    count: int = 0
    average: Optional[float] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    unit: str = ""


class HealthDataResult(BaseModel):
    user_id: str
    start_date: str
    end_date: str
    metrics: List[str]
    row_count: int = 0
    summaries: Dict[str, MetricSummary] = Field(default_factory=dict)
    series: Dict[str, List[HealthDataPoint]] = Field(default_factory=dict)
    analytics_snapshot: str = Field(
        default="",
        description="Precomputed <=300 char narrative for LLM fast path.",
    )
    message: str = ""
    metrics_supported: bool = True
    unsupported_metrics_requested: List[str] = Field(default_factory=list)

    def as_tool_payload(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "metrics": self.metrics,
            "row_count": self.row_count,
            "summaries": {k: v.model_dump(mode="python") for k, v in self.summaries.items()},
            "series": {k: [p.model_dump(mode="python") for p in v] for k, v in self.series.items()},
            "analytics_snapshot": self.analytics_snapshot,
            "message": self.message,
            "metrics_supported": self.metrics_supported,
            "unsupported_metrics_requested": self.unsupported_metrics_requested,
        }


def verify_import_completeness(
    user_id: str,
    *,
    xml_max_dt: Optional[datetime],
    min_expected_date: Optional[date] = None,
    allow_same_day: bool = True,
) -> ImportIntegrityReport:
    """
    Post-check: DB ``MAX(timestamp)`` must reach the last day seen in export.xml.

    Raises ``ImportIncompleteError`` if import stopped early (memory/timeout).
    """
    uid = (user_id or "default").strip() or "default"
    db_max = get_max_wearable_timestamp(uid)
    samples = count_wearable_samples(uid)
    daily_rows = len(store.list_wearable_rows(uid))

    xml_s = xml_max_dt.isoformat() if xml_max_dt else ""
    db_s = db_max.isoformat() if db_max else ""

    ref = min_expected_date or effective_query_reference_date()
    ok = True
    msg = f"导入完整性校验通过：{samples:,} 条样本，{daily_rows} 天聚合。"

    if xml_max_dt is None:
        ok = False
        msg = "导入未完成：export.xml 中未检测到任何 Record 时间戳。"
    elif db_max is None:
        ok = False
        msg = "导入未完成：wearable_data 为空，SQLite 未写入样本。"
    else:
        xml_day = xml_max_dt.date()
        db_day = db_max.date()
        if db_day < xml_day:
            ok = False
            msg = (
                f"导入未完成：数据库最新日期 {db_day.isoformat()} 早于 "
                f"export.xml 最后记录 {xml_day.isoformat()}。"
                f"（样本数 {samples:,}）"
            )
        elif min_expected_date and db_day < min_expected_date and xml_day >= min_expected_date:
            ok = False
            msg = (
                f"导入未完成：期望至少覆盖至 {min_expected_date.isoformat()}，"
                f"但数据库仅到 {db_day.isoformat()}。"
            )

    report = ImportIntegrityReport(
        ok=ok,
        user_id=uid,
        xml_max_timestamp=xml_s,
        db_max_timestamp=db_s,
        wearable_samples=samples,
        daily_rows=daily_rows,
        message=msg,
    )
    if not ok:
        logger.error("IMPORT INCOMPLETE: %s", msg)
        raise ImportIncompleteError(msg)
    logger.info("Import integrity OK: xml_max=%s db_max=%s samples=%s", xml_s, db_s, samples)
    return report


def _partition_requested_metrics(metrics: Sequence[str]) -> tuple[List[str], List[str]]:
    """Split user-requested tokens into (canonical wearable ids, unknown labels)."""
    unknown: List[str] = []
    out: List[str] = []
    seen_unknown: set[str] = set()
    for raw in metrics:
        label = str(raw or "").strip()
        if not label:
            continue
        key = label.lower()
        canon = METRIC_ALIASES.get(key)
        if not canon:
            lk = label.lower()
            if lk not in seen_unknown:
                seen_unknown.add(lk)
                unknown.append(label)
            continue
        if canon not in out:
            out.append(canon)
    return out, unknown


def _normalize_metrics(metrics: Sequence[str]) -> List[str]:
    out, _ = _partition_requested_metrics(metrics)
    return out


def _metric_value(row: Any, metric: str) -> Optional[float]:
    if metric == "sleep":
        return float(row.sleep_hours) if row.sleep_hours is not None else None
    if metric == "hrv":
        return float(row.hrv_rmssd_ms) if row.hrv_rmssd_ms is not None else None
    if metric == "steps":
        return float(row.steps) if row.steps is not None else None
    if metric == "rhr":
        return float(row.resting_heart_rate_bpm) if row.resting_heart_rate_bpm is not None else None
    if metric == "activity_kcal":
        return float(row.active_energy_kcal) if row.active_energy_kcal is not None else None
    if metric == "spo2":
        return float(row.spo2_pct) if row.spo2_pct is not None else None
    if metric == "respiratory_rate":
        return float(row.respiratory_rate_bpm) if row.respiratory_rate_bpm is not None else None
    if metric == "vo2max":
        return float(row.vo2max_ml_kg_min) if row.vo2max_ml_kg_min is not None else None
    if metric == "wrist_temp":
        return float(row.wrist_temp_c) if row.wrist_temp_c is not None else None
    return None


def _fetch_activity_kcal_series(
    uid: str,
    start_date: date,
    end_date: date,
) -> List[tuple[date, float]]:
    rows = query_wearable_daily_range(uid, start_date, end_date)
    from_daily = [
        (r.day, float(r.active_energy_kcal))
        for r in rows
        if r.active_energy_kcal is not None
    ]
    if from_daily:
        return from_daily
    from pha.sqlite_storage import query_active_energy_daily_range

    raw = query_active_energy_daily_range(uid, start_date, end_date)
    out: List[tuple[date, float]] = []
    for row in raw:
        label = str(row.get("label") or "")[:10]
        val = row.get("value")
        if not label or val is None:
            continue
        try:
            out.append((date.fromisoformat(label), float(val)))
        except ValueError:
            continue
    return out


def _metric_unit(metric: str) -> str:
    return {
        "sleep": "hours",
        "hrv": "ms",
        "steps": "count",
        "rhr": "bpm",
        "activity_kcal": "kcal",
        "spo2": "%",
        "respiratory_rate": "breaths/min",
        "vo2max": "mL/kg/min",
        "wrist_temp": "°C",
    }.get(metric, "")


def _fetch_rows_for_range(uid: str, start_date: date, end_date: date) -> list:
    rows = query_wearable_daily_range(uid, start_date, end_date)
    if rows:
        return rows
    return [r for r in store.list_wearable_rows(uid) if start_date <= r.day <= end_date]


def get_health_data(
    user_id: str,
    start_date: date,
    end_date: date,
    metrics: Sequence[str],
    *,
    reference_date: Optional[date] = None,
    user_message: str = "",
) -> HealthDataResult:
    uid = (user_id or "default").strip() or "default"
    if end_date < start_date:
        start_date, end_date = end_date, start_date

    raw_tokens = [str(m).strip() for m in metrics if str(m).strip()]
    extra_unsupported_note = ""
    unknown_requested: List[str] = []
    if raw_tokens:
        normalized, unknown_requested = _partition_requested_metrics(metrics)
        if not normalized:
            deny = (
                f"请求的穿戴指标均不在已接入集合 {sorted(METRICS_REGISTRY)}；"
                f"未识别项：{', '.join(unknown_requested)}。"
                "请改用抽屉中的原始 Apple Health 资产查看该指标，或只查询已支持字段。"
            )
            return HealthDataResult(
                user_id=uid,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
                metrics=[],
                row_count=0,
                metrics_supported=False,
                unsupported_metrics_requested=unknown_requested,
                message=deny,
            )
        if unknown_requested:
            extra_unsupported_note = (
                f"（以下指标未接入已忽略：{', '.join(unknown_requested)}）"
            )
    elif (user_message or "").strip():
        from pha.intent_gates import infer_wearable_metrics

        normalized = infer_wearable_metrics(user_message)
    else:
        normalized = []

    ref = reference_date or effective_query_reference_date()
    start_date, end_date, clamp_note = clamp_tool_query_window(start_date, end_date, reference_date=ref)
    if not normalized:
        deny = (
            "未指定或未从问题中推断出穿戴指标；化验/补剂请读 Patient State 与卷宗，"
            "穿戴请点名 sleep/hrv/steps/rhr/activity_kcal/spo2/respiratory_rate/vo2max/wrist_temp。"
        )
        if clamp_note:
            deny = f"{deny} {clamp_note}"
        return HealthDataResult(
            user_id=uid,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            metrics=[],
            row_count=0,
            metrics_supported=False,
            unsupported_metrics_requested=unknown_requested,
            message=deny,
        )
    rows = _fetch_rows_for_range(uid, start_date, end_date)
    wearable_metrics = [m for m in normalized if m != "activity_kcal"]
    kcal_metrics = [m for m in normalized if m == "activity_kcal"]

    summaries: Dict[str, MetricSummary] = {}
    series: Dict[str, List[HealthDataPoint]] = {}

    for metric in wearable_metrics:
        points: List[HealthDataPoint] = []
        vals: List[float] = []
        for row in rows:
            v = _metric_value(row, metric)
            points.append(HealthDataPoint(date=row.day.isoformat(), value=v))
            if v is not None:
                vals.append(v)
        series[metric] = points
        summaries[metric] = MetricSummary(
            metric=metric,
            count=len(vals),
            average=float(statistics.mean(vals)) if vals else None,
            minimum=float(min(vals)) if vals else None,
            maximum=float(max(vals)) if vals else None,
            unit=_metric_unit(metric),
        )

    for metric in kcal_metrics:
        kcal_pts = _fetch_activity_kcal_series(uid, start_date, end_date)
        points = [HealthDataPoint(date=d.isoformat(), value=v) for d, v in kcal_pts]
        vals = [v for _, v in kcal_pts]
        series[metric] = points
        summaries[metric] = MetricSummary(
            metric=metric,
            count=len(vals),
            average=float(statistics.mean(vals)) if vals else None,
            minimum=float(min(vals)) if vals else None,
            maximum=float(max(vals)) if vals else None,
            unit=_metric_unit(metric),
        )

    kcal_daily: list[tuple[date, float]] = []
    if kcal_metrics:
        kcal_daily = _fetch_activity_kcal_series(uid, start_date, end_date)

    analytics_snapshot = build_analytics_snapshot(
        rows,
        start_date=start_date,
        end_date=end_date,
        reference_date=ref,
        user_id=uid,
        user_message=user_message,
        metrics=normalized,
        activity_kcal_daily=kcal_daily if kcal_daily else None,
    )

    has_any = bool(rows) or any(
        summaries.get(m) and summaries[m].count > 0 for m in kcal_metrics
    )
    if not has_any:
        msg = (
            f"本地 PHA 库中 {start_date.isoformat()} 至 {end_date.isoformat()} "
            f"无穿戴数据；请确认 export.zip 已完整导入。"
        )
    else:
        msg = f"已索引查询 wearable {len(rows)} 天；已生成预计算分析快照。"
    if clamp_note:
        msg = f"{msg} {clamp_note}".strip()
    if extra_unsupported_note:
        msg = f"{msg}{extra_unsupported_note}"
    if not normalized and not has_any:
        msg = (
            f"{msg} 未指定有效穿戴指标；请在问题中点名 sleep/hrv/steps/rhr/activity_kcal，"
            f"或依赖 Patient State / 卷宗中的化验数据。"
        ).strip()
    if "activity_kcal" in normalized and not kcal_daily:
        msg = (
            f"{msg} 活动消耗：本场查询区间内 wearable_daily.active_energy_kcal 与 "
            "wearable_data 均无有效日序列，禁止口述具体千卡均值。"
        )

    return HealthDataResult(
        user_id=uid,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        metrics=normalized,
        row_count=len(rows),
        summaries=summaries,
        series=series,
        analytics_snapshot=analytics_snapshot,
        message=msg,
        metrics_supported=True,
        unsupported_metrics_requested=unknown_requested,
    )


def default_last_n_days_range(
    *,
    reference_date: date,
    days: int = 90,
) -> tuple[date, date]:
    end = reference_date
    start = end - timedelta(days=max(1, days) - 1)
    return start, end
