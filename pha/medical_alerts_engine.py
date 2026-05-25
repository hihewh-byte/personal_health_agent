"""Medical alerts — LLM clinical slow path (PHA v2.1.0, accuracy-first)."""

from __future__ import annotations

import json
import logging
import re
import time
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence

from pha.clinical_llm import (
    CLINICAL_JUDGE_SYSTEM_PROMPT,
    parse_clinical_json_with_retry,
)
from pha.data_sanitizer import sanitize_metric_fields
from pha.health_data import effective_query_reference_date
from pha.medical_storage import MedicalMetricRow, parse_ref_bounds, query_metrics_in_range

logger = logging.getLogger(__name__)

VOLATILITY_THRESHOLD_PCT = 15.0
_ALERTS_CACHE: Dict[str, tuple[float, List[Dict[str, Any]]]] = {}
_ALERTS_CACHE_TTL = float(__import__("os").environ.get("PHA_ALERTS_CACHE_TTL", "600"))

# Lightweight pipe-only blacklist (never sent to LLM as clinical signals)
ALERT_BLACKLIST_PATTERNS: tuple[str, ...] = (
    r"主检日期",
    r"检查者",
    r"检查日期",
    r"检验日期",
    r"报告日期",
    r"采样日期",
    r"医生",
    r"医师",
    r"姓名",
    r"科室",
    r"病区",
    r"床号",
    r"标本号",
    r"病历号",
    r"住院号",
    r"检验者",
    r"审核者",
)

_BLACKLIST_RE = re.compile("|".join(ALERT_BLACKLIST_PATTERNS), re.IGNORECASE)
_META_ONLY_RE = re.compile(
    r"^(日期|时间|编号|序号|页码|第\d+页|\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?)$",
    re.IGNORECASE,
)


def is_blacklisted_metric_name(raw_name: str, *, metric_code: str = "") -> bool:
    blob = f"{raw_name or ''} {metric_code or ''}".strip()
    if not blob or len(blob) < 2:
        return True
    if _BLACKLIST_RE.search(blob):
        return True
    if _META_ONLY_RE.match(blob.strip()):
        return True
    if re.fullmatch(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", blob.strip()):
        return True
    if "10^" in blob and not re.search(r"[A-Za-z]{2,}#?", blob):
        return True
    return False


def _volatility_pct(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    vmin, vmax = min(values), max(values)
    denom = abs(vmin) if abs(vmin) > 1e-9 else abs(vmax)
    if denom < 1e-9:
        return 0.0
    return abs(vmax - vmin) / denom * 100.0


def _in_dead_center_normal(value: float, reference_range: str) -> bool:
    lo, hi = parse_ref_bounds(reference_range)
    if lo is None or hi is None or hi <= lo:
        return False
    span = hi - lo
    mid_lo = lo + span * 0.25
    mid_hi = hi - span * 0.25
    return mid_lo <= value <= mid_hi


def _prepare_rows_for_ledger(rows: Sequence[MedicalMetricRow]) -> List[MedicalMetricRow]:
    cleaned: List[MedicalMetricRow] = []
    for row in rows:
        clean_name, val, unit = sanitize_metric_fields(
            row.metric_name,
            row.value,
            row.unit,
            reference_range=row.reference_range,
        )
        code = (row.metric_code or clean_name or "").strip()
        if is_blacklisted_metric_name(clean_name, metric_code=code):
            continue
        if val is None:
            continue
        cleaned.append(
            MedicalMetricRow(
                user_id=row.user_id,
                report_date=row.report_date,
                metric_name=clean_name or row.metric_name,
                metric_code=code or clean_name,
                name_en=row.name_en,
                name_zh=row.name_zh,
                value=val,
                unit=unit or row.unit,
                reference_range=row.reference_range,
                is_abnormal=row.is_abnormal,
                source_filename=row.source_filename,
            ),
        )
    return cleaned


def build_dynamic_review_ledger(rows: Sequence[MedicalMetricRow]) -> List[Dict[str, Any]]:
    """
  轻量过滤：剔除正常区间中部且低波动的死数据；
  保留跨年偏离、标记异常、或波动率 >15% 的核心动态审阅账本。
    """
    prepared = _prepare_rows_for_ledger(rows)
    by_key: Dict[str, List[MedicalMetricRow]] = defaultdict(list)
    for row in prepared:
        key = (row.metric_code or row.metric_name or "").strip().upper()
        if key:
            by_key[key].append(row)

    ledger: List[Dict[str, Any]] = []
    for key, series in by_key.items():
        series_sorted = sorted(series, key=lambda r: r.report_date)
        values = [float(r.value) for r in series_sorted if r.value is not None]
        if not values:
            continue

        years = {r.report_date.year for r in series_sorted}
        cross_year = len(years) >= 2 and _volatility_pct(values) >= VOLATILITY_THRESHOLD_PCT
        volatile = _volatility_pct(values) >= VOLATILITY_THRESHOLD_PCT
        any_flagged = any(r.is_abnormal for r in series_sorted)

        for row in series_sorted:
            val = float(row.value)  # type: ignore[arg-type]
            dead_center = _in_dead_center_normal(val, row.reference_range)
            if not any_flagged and not cross_year and not volatile and dead_center:
                continue
            if not any_flagged and not cross_year and not volatile and not row.is_abnormal:
                if len(values) >= 2 and _volatility_pct(values) < VOLATILITY_THRESHOLD_PCT:
                    continue

            ledger.append(
                {
                    "report_date": row.report_date.isoformat()[:10],
                    "metric_name": row.metric_name,
                    "metric_code": row.metric_code or row.metric_name,
                    "name_zh": row.name_zh or row.metric_name,
                    "value": val,
                    "unit": row.unit,
                    "reference_range": row.reference_range,
                    "is_abnormal_flag": bool(row.is_abnormal),
                    "series_years": sorted(years),
                    "series_volatility_pct": round(_volatility_pct(values), 1),
                },
            )

    ledger.sort(key=lambda x: (x["report_date"], x["metric_name"]))
    return ledger


def _ledger_to_prompt(ledger: List[Dict[str, Any]]) -> str:
    if not ledger:
        return "（核心动态审阅账本为空：无需要医生关注的波动或异常信号）"
    lines = ["【核心动态审阅账本 · 已剔除死数据，仅供医学裁判】"]
    for item in ledger[:120]:
        lines.append(
            f"- {item['report_date']} | {item.get('name_zh') or item['metric_name']} "
            f"({item['metric_code']}) = {item['value']} {item.get('unit') or ''} "
            f"ref={item.get('reference_range') or '—'} "
            f"flag={item.get('is_abnormal_flag')} "
            f"vol%={item.get('series_volatility_pct')} years={item.get('series_years')}",
        )
    if len(ledger) > 120:
        lines.append(f"… 另有 {len(ledger) - 120} 条未展开")
    return "\n".join(lines)


def _invoke_clinical_llm(ledger: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    from pha.llm_provider import OllamaProvider

    user_msg = (
        "请审阅以下体检指标动态账本，输出需要临床警惕的异常项 JSON 数组。\n\n"
        f"{_ledger_to_prompt(ledger)}"
    )
    provider = OllamaProvider.for_clinical_review()
    raw = provider.chat_completion(
        system_prompt=CLINICAL_JUDGE_SYSTEM_PROMPT,
        user_message=user_msg,
        json_mode=True,
    )

    def _retry() -> str:
        repair_prompt = (
            "上一次输出无法解析。请仅输出合法 JSON 数组，"
            "每项含 metric_name, value, unit, status_alert, clinical_advice, report_date。\n\n"
            f"{_ledger_to_prompt(ledger)}"
        )
        return provider.chat_completion(
            system_prompt=CLINICAL_JUDGE_SYSTEM_PROMPT,
            user_message=repair_prompt,
            json_mode=True,
        )

    return parse_clinical_json_with_retry(raw, retry_fn=_retry)


def get_professional_medical_alerts(
    user_id: str,
    reference_date: date,
    *,
    years: float = 10.0,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> List[Dict[str, Any]]:
    """
    Slow-path clinical alerts — LLM JSON review with per-row ``report_date``.

    Code only builds the dynamic ledger and pipes LLM output; no hardcoded ref-range verdicts.
    """
    uid = (user_id or "default").strip() or "default"
    if use_cache and not force_refresh:
        cached = _ALERTS_CACHE.get(uid)
        if cached and (time.time() - cached[0]) < _ALERTS_CACHE_TTL:
            return list(cached[1])

    days = int(years * 365)
    start = reference_date - timedelta(days=days)
    rows = query_metrics_in_range(uid, start, reference_date)
    ledger = build_dynamic_review_ledger(rows)

    if not ledger:
        _ALERTS_CACHE[uid] = (time.time(), [])
        return []

    try:
        alerts = _invoke_clinical_llm(ledger)
    except Exception as exc:
        logger.exception("clinical LLM review failed for %s", uid)
        alerts = [
            {
                "metric_name": "PHA_CLINICAL_REVIEW",
                "name_zh": "临床审阅暂不可用",
                "value": None,
                "unit": "",
                "status_alert": "系统提示",
                "clinical_advice": f"大模型医生审阅暂时失败，请稍后重试：{exc}",
                "report_date": reference_date.isoformat()[:10],
            },
        ]

    _ALERTS_CACHE[uid] = (time.time(), alerts)
    return alerts


def invalidate_alerts_cache(user_id: str) -> None:
    uid = (user_id or "default").strip() or "default"
    _ALERTS_CACHE.pop(uid, None)


def get_cached_alert_count(user_id: str) -> Optional[int]:
    """Hero stats: never triggers slow-path LLM — returns None if not yet reviewed."""
    uid = (user_id or "default").strip() or "default"
    cached = _ALERTS_CACHE.get(uid)
    if not cached:
        return None
    if (time.time() - cached[0]) >= _ALERTS_CACHE_TTL:
        return None
    return len(cached[1])
