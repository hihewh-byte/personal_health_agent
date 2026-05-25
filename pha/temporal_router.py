"""Dynamic temporal intent parsing and panoramic cross-year dossier assembly (v1.8.9)."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Optional, Sequence, Set, Tuple

from pha.health_data import effective_query_reference_date
from pha.medical_storage import (
    MedicalMetricRow,
    format_ldl_crossyear_markdown_table,
    get_latest_medical_report,
    list_distinct_report_dates,
    query_ldl_metrics_for_calendar_years,
    query_metrics_for_calendar_years,
    query_narratives_for_calendar_years,
)
from pha.temporal_penetrate import build_cross_table_context_bundle
from pha.wearable_features import build_wearable_temporal_dossier_for_window

logger = logging.getLogger(__name__)

DEFAULT_RECENT_WEARABLE_DAYS = 90
DEFAULT_CHECKUP_SNAPSHOT_COUNT = 3
CHECKUP_WEARABLE_PADDING_DAYS = 7

# Layer-1: high-determinism four-digit years (with or without 年, glued to Chinese chars)
_YEAR_PATTERNS = (
    re.compile(r"(?<![0-9])(20\d{2}|19\d{2})(?![0-9])"),
    re.compile(r"(20\d{2}|19\d{2})\s*年"),
)
_TEMPORAL_KEYWORDS_RE = re.compile(
    r"对比|比较|相较|对照|跨年|历史|往年|两年|三年|年度|"
    r"体检.*年|年.*体检|WASO|waso|穿戴|时序|对账|勾兑",
    re.IGNORECASE,
)
_COMPARE_RE = re.compile(r"对比|比较|vs|相较|对照|两年|跨年", re.IGNORECASE)

DOSSIER_TITLE = "【全景纵向时空对账卷宗】"
DOSSIER_MANDATE = (
    "【硬性约束 · SQLite 已注入】\n"
    "以下账本为 Python 从 medical_reports / health_narratives / wearable_daily 真实 SELECT 结果；\n"
    "你必须仅依据本账本作答；严禁声称「未提供数据」「未粘贴原始数据」「无法访问数据库」。\n"
    "用户若指定年份，禁止擅自改写（例如将 2025 写成 2024）。\n"
)


@dataclass
class TemporalIntent:
    """Parsed time scope from a user health question."""

    explicit_years: List[int] = field(default_factory=list)
    compare_years: bool = False
    use_default_checkups: bool = True
    checkup_padding_days: int = CHECKUP_WEARABLE_PADDING_DAYS
    recent_wearable_days: int = DEFAULT_RECENT_WEARABLE_DAYS
    is_temporal_dynamic: bool = False
    sniff_source: str = "none"  # regex | keyword | llm | default

    @property
    def has_explicit_years(self) -> bool:
        return bool(self.explicit_years)


@dataclass
class TemporalFusionStats:
    """Counts for harness logging."""

    metric_rows: int = 0
    narrative_rows: int = 0
    wearable_windows: int = 0
    years_queried: List[int] = field(default_factory=list)


_DOSE_YEAR_SKIP_RE = re.compile(
    r"(?:\bFU\b|\bfu\b|毫克|\bmg\b|毫升|\bml\b|次/|步/|kcal|千卡|μg|\bug\b|\bIU\b|单位/日)",
    re.I,
)


def _year_match_is_calendar_year(match: re.Match[str], raw: str) -> bool:
    y = int(match.group(1))
    start, end = match.start(), match.end()
    window = raw[max(0, start - 12) : min(len(raw), end + 28)]
    if _DOSE_YEAR_SKIP_RE.search(window):
        return False
    if re.search(rf"{y}\s*[-~～]\s*\d{{3,4}}", window):
        return False
    if re.search(rf"\d{{3,4}}\s*[-~～]\s*{y}", window):
        return False
    return True


def extract_years_regex(text: str, *, reference_date: Optional[date] = None) -> List[int]:
    """Layer-1 deterministic year extraction."""
    ref = reference_date or effective_query_reference_date()
    raw = (text or "").strip()
    if not raw:
        return []
    years: List[int] = []
    seen: Set[int] = set()
    for pat in _YEAR_PATTERNS:
        for m in pat.finditer(raw):
            if not _year_match_is_calendar_year(m, raw):
                continue
            y = int(m.group(1))
            if 1990 <= y <= ref.year + 1 and y not in seen:
                seen.add(y)
                years.append(y)
    years.sort()
    return years


def _llm_semantic_year_sniff(text: str, *, reference_date: Optional[date] = None) -> List[int]:
    """
    Layer-2 optional LLM year sniff (env ``PHA_TEMPORAL_LLM_SNIFF=1``).
    Falls back to empty list on any failure — regex layer remains authoritative.
    """
    if (os.environ.get("PHA_TEMPORAL_LLM_SNIFF") or "").strip() not in ("1", "true", "yes"):
        return []
    ref = reference_date or effective_query_reference_date()
    try:
        from pha.llm_provider import OllamaProvider, find_medical_text_model, list_ollama_installed_models, load_dotenv_if_present

        load_dotenv_if_present()
        base = (
            os.environ.get("OLLAMA_BASE_URL")
            or os.environ.get("OLLAMA_HOST")
            or "http://127.0.0.1:11434"
        ).rstrip("/")
        installed = list_ollama_installed_models(base, timeout_seconds=8.0)
        model = find_medical_text_model(installed)
        if not model:
            return []
        provider = OllamaProvider(base_url=base, model=model, timeout_seconds=30.0)
        prompt = (
            f"参考日 {ref.isoformat()}。从用户问题中提取所有四位数年份（如 2023、2025）。\n"
            "只输出 JSON 数组，例如 [2023,2025]；若无年份输出 []。\n"
            f"用户问题：{text[:800]}"
        )
        raw = provider.chat_completion(
            system_prompt="你是年份实体提取器，只输出 JSON 数组。",
            user_message=prompt,
        )
        m = re.search(r"\[[\d,\s]*\]", raw)
        if not m:
            return []
        import json

        arr = json.loads(m.group(0))
        out: List[int] = []
        for item in arr:
            y = int(item)
            if 1990 <= y <= ref.year + 1:
                out.append(y)
        return sorted(set(out))
    except Exception as exc:
        logger.warning("LLM temporal year sniff skipped: %s", exc)
        return []


def parse_temporal_intent(user_message: str, *, reference_date: Optional[date] = None) -> TemporalIntent:
    """Regex + optional LLM double-layer year sniff; sets ``is_temporal_dynamic``."""
    text = (user_message or "").strip()
    ref = reference_date or effective_query_reference_date()

    years = extract_years_regex(text, reference_date=ref)
    sniff_source = "regex" if years else "none"

    if not years and _TEMPORAL_KEYWORDS_RE.search(text):
        llm_years = _llm_semantic_year_sniff(text, reference_date=ref)
        if llm_years:
            years = llm_years
            sniff_source = "llm"

    has_keywords = bool(_TEMPORAL_KEYWORDS_RE.search(text))
    compare = bool(_COMPARE_RE.search(text)) or len(years) >= 2
    is_dynamic = bool(years) or has_keywords

    return TemporalIntent(
        explicit_years=years,
        compare_years=compare,
        use_default_checkups=not years,
        checkup_padding_days=CHECKUP_WEARABLE_PADDING_DAYS,
        recent_wearable_days=DEFAULT_RECENT_WEARABLE_DAYS,
        is_temporal_dynamic=is_dynamic,
        sniff_source=sniff_source if years else ("keyword" if has_keywords else "none"),
    )


def build_temporal_status_message(intent: TemporalIntent) -> str:
    """SSE status line — must fire when ``is_temporal_dynamic``."""
    if intent.explicit_years:
        ys = "/".join(str(y) for y in intent.explicit_years)
        return (
            f"AI 正在勾兑时间轴：正在动态提取 {ys} 历史体检对账窗口"
            f"及对应时段前后各 {intent.checkup_padding_days} 天的高密度可穿戴特征…"
        )
    if intent.is_temporal_dynamic:
        return (
            f"AI 正在勾兑时间轴：联动最近 {DEFAULT_CHECKUP_SNAPSHOT_COUNT} 次完整体检快照"
            f" + 近 {intent.recent_wearable_days} 日可穿戴时序特征…"
        )
    return "正在组装健康证据与语义历史上下文…"


def _warn_empty_year_metrics(user_id: str, year: int, count: int) -> None:
    if count > 0:
        return
    print(
        f"[PHA Warning] Year {year} data parsed as EMPTY. Check SQL conditions! user_id={user_id}",
        flush=True,
    )


def _metrics_for_year(
    user_id: str,
    year: int,
    pool: Sequence[MedicalMetricRow],
) -> List[MedicalMetricRow]:
    """Per-year slice with SQL fallback if Python bucket is empty."""
    uid = (user_id or "default").strip() or "default"
    ym = [r for r in pool if r.report_date.year == year]
    if not ym:
        ym = query_metrics_for_calendar_years(uid, [year])
    _warn_empty_year_metrics(uid, year, len(ym))
    return ym


def _narratives_for_year(year: int, pool: Sequence) -> List:
    yn = [n for n in pool if n.report_date.year == year]
    return yn


def _metrics_lines(rows: Sequence[MedicalMetricRow], *, max_rows: int = 500) -> List[str]:
    from pha.dossier_filters import filter_line_list, is_dossier_junk_line
    from pha.medical_storage import format_ldl_display_value, is_ldl_metric_name

    lines: List[str] = []
    for r in rows[:max_rows]:
        name = (r.metric_name or "").strip()
        code = (r.metric_code or "").strip()
        if is_dossier_junk_line(name) or is_dossier_junk_line(code):
            continue
        if is_ldl_metric_name(r.metric_name or r.metric_code or ""):
            val = format_ldl_display_value(r.value)
        else:
            val = f"{r.value:g}" if r.value is not None else "?"
        flag = " [异常]" if r.is_abnormal else ""
        code = (r.metric_code or r.metric_name or "?").strip()
        lines.append(
            f"- {r.report_date.isoformat()} | {code} | {r.metric_name} | {val} {r.unit} | "
            f"ref {r.reference_range or '—'}{flag}",
        )
    if len(rows) > max_rows:
        lines.append(f"…（另有 {len(rows) - max_rows} 项未展开）")
    return filter_line_list(lines)


def _narrative_lines(rows, *, max_rows: int = 80) -> List[str]:
    from pha.dossier_filters import filter_line_list, is_dossier_junk_line

    lines: List[str] = []
    for n in rows[:max_rows]:
        body = (n.content or n.summary or "").strip()
        if is_dossier_junk_line(body):
            continue
        if len(body) > 600:
            body = body[:600] + "…"
        row = f"- {n.report_date.isoformat()} | {n.hospital or '—'} | [{n.category}] {body}"
        if is_dossier_junk_line(row):
            continue
        lines.append(row)
    return filter_line_list(lines)


def _resolve_checkup_anchor_dates(user_id: str, intent: TemporalIntent) -> List[date]:
    uid = (user_id or "default").strip() or "default"
    ref = effective_query_reference_date()

    if intent.has_explicit_years:
        anchors: List[date] = []
        for y in intent.explicit_years:
            rows = query_metrics_for_calendar_years(uid, [y])
            days = sorted({r.report_date for r in rows})
            if days:
                anchors.append(days[-1])
                if len(days) > 1:
                    anchors.append(days[0])
            else:
                anchors.append(date(y, 6, 15))
        out: List[date] = []
        seen: Set[str] = set()
        for d in sorted(anchors):
            key = d.isoformat()
            if key not in seen:
                seen.add(key)
                out.append(d)
        return out

    distinct = list_distinct_report_dates(uid, limit=12)
    if distinct:
        return distinct[:DEFAULT_CHECKUP_SNAPSHOT_COUNT]
    latest_d, _ = get_latest_medical_report(uid)
    return [latest_d] if latest_d else []


def _fetch_clinical_for_intent(user_id: str, intent: TemporalIntent) -> Tuple[List[MedicalMetricRow], list]:
    uid = (user_id or "default").strip() or "default"
    if intent.has_explicit_years:
        metrics = query_metrics_for_calendar_years(uid, intent.explicit_years)
        narratives = query_narratives_for_calendar_years(uid, intent.explicit_years)
        return metrics, narratives

    anchors = _resolve_checkup_anchor_dates(uid, intent)
    metrics: List[MedicalMetricRow] = []
    narratives = []
    seen_m: Set[str] = set()
    for d in anchors:
        from pha.medical_storage import query_metrics_in_range, query_narratives_in_range

        start = d - timedelta(days=3)
        end = d + timedelta(days=3)
        for r in query_metrics_in_range(uid, start, end):
            key = f"{r.report_date}|{r.metric_name}"
            if key not in seen_m:
                seen_m.add(key)
                metrics.append(r)
        narratives.extend(query_narratives_in_range(uid, start, end))
    return metrics, narratives


def build_panoramic_temporal_dossier(
    user_id: str,
    user_message: str,
    *,
    reference_date: Optional[date] = None,
    intent: Optional[TemporalIntent] = None,
    omit_ldl_fusion_blocks: bool = False,
    compact_clinical_only: bool = False,
) -> tuple[str, TemporalIntent, str, TemporalFusionStats]:
    """
    Build《全景纵向时空对账卷宗》with guaranteed SQLite fusion.

    Returns ``(dossier_text, intent, status_message, fusion_stats)``.
    """
    ref = reference_date or effective_query_reference_date()
    intent = intent or parse_temporal_intent(user_message, reference_date=ref)
    uid = (user_id or "default").strip() or "default"
    stats = TemporalFusionStats(years_queried=list(intent.explicit_years))

    metric_rows, narrative_rows = _fetch_clinical_for_intent(uid, intent)
    stats.metric_rows = len(metric_rows)
    stats.narrative_rows = len(narrative_rows)

    blocks: List[str] = [
        DOSSIER_TITLE,
        DOSSIER_MANDATE,
        f"user_id={uid} reference_date={ref.isoformat()}",
        f"时间意图: years={intent.explicit_years or '默认近{0}次体检'.format(DEFAULT_CHECKUP_SNAPSHOT_COUNT)} "
        f"compare={intent.compare_years} is_temporal_dynamic={intent.is_temporal_dynamic} "
        f"sniff={intent.sniff_source}",
    ]

    if intent.has_explicit_years:
        ldl_all: List[MedicalMetricRow] = []
        if not omit_ldl_fusion_blocks:
            ldl_all = query_ldl_metrics_for_calendar_years(
                uid,
                intent.explicit_years,
                security_inspect=True,
            )
            blocks.append(
                format_ldl_crossyear_markdown_table(
                    uid,
                    intent.explicit_years,
                    security_inspect=False,
                ),
            )
        for y in intent.explicit_years:
            year_metrics = _metrics_for_year(uid, y, metric_rows)
            year_narr = _narratives_for_year(y, narrative_rows)
            if not year_narr:
                year_narr = query_narratives_for_calendar_years(uid, [y])
            ldl_rows = [r for r in ldl_all if r.report_date.year == y]
            blocks.append(
                f"=== 临床指标轨 {y} 年（SQLite medical_reports · {len(year_metrics)} 项）===\n"
                + ("\n".join(_metrics_lines(year_metrics)) or f"（{y} 年无入库指标，请先归仓化验单）"),
            )
            if not omit_ldl_fusion_blocks and ldl_rows:
                blocks.append(
                    f"=== {y} 年 · LDL 实测行（SQL · {len(ldl_rows)} 项）===\n"
                    + "\n".join(_metrics_lines(ldl_rows, max_rows=24)),
                )
            if year_narr:
                blocks.append(
                    f"=== 叙事轨 {y} 年（health_narratives · {len(year_narr)} 段）===\n"
                    + "\n".join(_narrative_lines(year_narr)),
                )
    else:
        blocks.append(
            f"=== 临床指标轨（最近体检快照 · {len(metric_rows)} 项）===\n"
            + ("\n".join(_metrics_lines(metric_rows)) or "（无入库指标）"),
        )
        if narrative_rows:
            blocks.append(
                f"=== 叙事轨（{len(narrative_rows)} 段）===\n"
                + "\n".join(_narrative_lines(narrative_rows)),
            )

    anchors = _resolve_checkup_anchor_dates(uid, intent)
    status_msg = build_temporal_status_message(intent)

    if compact_clinical_only:
        blocks.append(
            "【复合体检问 · 临床精简卷宗】已省略全年可穿戴窗口与跨表对齐块；"
            "穿戴/活动消耗请使用 Patient State 账本或 get_health_data 点名指标。"
        )
        return "\n\n".join(blocks), intent, status_msg, stats

    if intent.has_explicit_years:
        for y in intent.explicit_years:
            y_start = date(y, 1, 1)
            y_end = min(date(y, 12, 31), ref)
            blocks.append(
                build_wearable_temporal_dossier_for_window(
                    uid,
                    y_start,
                    y_end,
                    label=f"{y} 全年可穿戴 · WASO/HRV/睡眠（破除仅数日断层）",
                    reference_date=ref,
                ),
            )
            stats.wearable_windows += 1
        for anchor in anchors:
            w_start = anchor - timedelta(days=intent.checkup_padding_days)
            w_end = anchor + timedelta(days=intent.checkup_padding_days)
            if w_end > ref:
                w_end = ref
            label = f"体检日 {anchor.isoformat()} ±{intent.checkup_padding_days}d · WASO/HRV 锚点对齐"
            blocks.append(
                build_wearable_temporal_dossier_for_window(
                    uid,
                    w_start,
                    w_end,
                    label=label,
                    reference_date=ref,
                ),
            )
            stats.wearable_windows += 1
    else:
        w_end = ref
        w_start = ref - timedelta(days=intent.recent_wearable_days - 1)
        blocks.append(
            build_wearable_temporal_dossier_for_window(
                uid,
                w_start,
                w_end,
                label=f"最近 {intent.recent_wearable_days} 日可穿戴（默认窗口）",
                reference_date=ref,
            ),
        )
        stats.wearable_windows = 1

    blocks.append(
        build_cross_table_context_bundle(uid, reference_date=ref),
    )
    blocks.append(
        "【时空对账铁律】临床指标与可穿戴特征已按体检锚点对齐；"
        "回答跨年因果问题须显式引用对应年份/体检日的双轨证据，禁止混用未对齐时段。",
    )
    return "\n\n".join(blocks), intent, status_msg, stats


def infer_dynamic_health_tool_range(
    intent: TemporalIntent,
    *,
    reference_date: Optional[date] = None,
) -> tuple[date, date]:
    """Date range for optional get_health_data tool (not hardcoded 90d when years given)."""
    ref = reference_date or effective_query_reference_date()
    if intent.has_explicit_years:
        y0, y1 = min(intent.explicit_years), max(intent.explicit_years)
        return date(y0, 1, 1), min(date(y1, 12, 31), ref)
    return ref - timedelta(days=intent.recent_wearable_days - 1), ref
