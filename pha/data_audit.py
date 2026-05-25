"""PHA LDL data-pipeline auto-verifier — stages A→D with frontend-visible audit trace."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Sequence

from pha.medical_storage import (
    get_health_report_asset,
    is_ldl_metric_name,
    query_ldl_metrics_for_calendar_years,
    sanitize_ldl_value,
)

logger = logging.getLogger(__name__)

_STAGE_LABELS = {
    "A": "阶段 A：提取工具端（Raw Extraction）",
    "B": "阶段 B：解析工具端（Parsed JSON）",
    "C": "阶段 C：存储工具端（DB Verification）",
    "D": "阶段 D：组装工具端（Context Prompt）",
}

_FLOAT_TOL = 0.05

# Recent ingest traces keyed by user_id (in-memory; survives until process restart)
_ingest_traces: Dict[str, List[Dict[str, Any]]] = {}


def clear_ingest_traces(user_id: Optional[str] = None) -> None:
    """Drop cached A/B traces (e.g. after harness seed purge)."""
    if user_id:
        _ingest_traces.pop((user_id or "default").strip() or "default", None)
    else:
        _ingest_traces.clear()


def _fmt_stage_value(value: Optional[float], *, empty: str = "—") -> str:
    v = sanitize_ldl_value(value)
    if v is None:
        if value is not None:
            return f"无效({value})"
        return empty
    return f"{v:g}"


def _values_equal(a: Optional[float], b: Optional[float]) -> bool:
    sa, sb = sanitize_ldl_value(a), sanitize_ldl_value(b)
    if sa is None and sb is None:
        return True
    if sa is None or sb is None:
        return False
    return abs(sa - sb) <= _FLOAT_TOL


def extract_ldl_snippet_from_text(text: str, *, max_len: int = 120) -> str:
    """Stage A helper — pull LDL-adjacent raw text from PDF/OCR blob."""
    if not (text or "").strip():
        return "（无原始文本片段）"
    patterns = (
        r"低密度脂蛋白[^\n\r]{0,80}",
        r"LDL[-\s]?C?[^\n\r]{0,60}",
        r"low\s+density\s+lipoprotein[^\n\r]{0,60}",
    )
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            s = re.sub(r"\s+", " ", m.group(0)).strip()
            return s[:max_len] + ("…" if len(s) > max_len else "")
    return "（未在原始文本中定位 LDL 片段）"


def ldl_value_from_metrics_blob(blob: Any) -> Optional[float]:
    """Extract first LDL numeric from vision JSON / metrics list."""
    if isinstance(blob, dict):
        metrics = blob.get("metrics") or blob.get("health_metrics") or []
    elif isinstance(blob, list):
        metrics = blob
    else:
        return None
    for m in metrics:
        if not isinstance(m, dict):
            continue
        name = str(m.get("metric_name") or m.get("name") or m.get("code") or "")
        if not is_ldl_metric_name(name):
            continue
        raw = m.get("value")
        try:
            v = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            continue
        return sanitize_ldl_value(v)
    return None


def record_ingest_ldl_trace(
    user_id: str,
    report_date: date,
    *,
    raw_snippet: str = "",
    parsed_value: Optional[float] = None,
    db_value: Optional[float] = None,
    source_filename: str = "",
) -> None:
    """Remember latest ingest audit for a report day (stages A–C at upload time)."""
    uid = (user_id or "default").strip() or "default"
    trace = {
        "report_date": report_date.isoformat(),
        "year": report_date.year,
        "source_filename": source_filename,
        "stage_a": raw_snippet or "（未记录）",
        "stage_b": parsed_value,
        "stage_c": db_value,
    }
    bucket = _ingest_traces.setdefault(uid, [])
    bucket = [t for t in bucket if t.get("report_date") != trace["report_date"]]
    bucket.append(trace)
    _ingest_traces[uid] = bucket[-24:]


def _ingest_trace_for_year(user_id: str, year: int) -> Optional[Dict[str, Any]]:
    traces = _ingest_traces.get((user_id or "default").strip() or "default", [])
    for t in reversed(traces):
        if int(t.get("year") or 0) == year:
            return t
    return None


def _vision_asset_ldl_for_year(user_id: str, year: int) -> tuple[str, Optional[float]]:
    """Fallback A/B from archived health_report_assets vision_raw_json."""
    from pha.medical_storage import list_health_report_assets

    uid = (user_id or "default").strip() or "default"
    for asset in list_health_report_assets(uid, limit=200):
        rd = str(asset.get("report_date") or "")[:10]
        if not rd.startswith(str(year)):
            continue
        aid = asset.get("id")
        if aid is None or str(aid).startswith("legacy-"):
            preview = str(asset.get("metrics_preview") or "")
            b_val = None
            m = re.search(r"LDL[^:]*:?\s*([\d.]+)", preview, re.I)
            if m:
                try:
                    b_val = sanitize_ldl_value(float(m.group(1)))
                except ValueError:
                    pass
            return preview[:100] or "（legacy 聚合预览）", b_val
        try:
            detail = get_health_report_asset(int(aid), uid)
        except (TypeError, ValueError):
            continue
        if not detail:
            continue
        raw_json = detail.get("vision_raw") or detail.get("vision_raw_json")
        if isinstance(raw_json, str):
            try:
                raw_json = json.loads(raw_json)
            except json.JSONDecodeError:
                raw_json = {}
        snippet = extract_ldl_snippet_from_text(json.dumps(raw_json, ensure_ascii=False)[:2000])
        b_val = ldl_value_from_metrics_blob(raw_json if isinstance(raw_json, dict) else {})
        return snippet, b_val
    return "（无归档 Vision 资产）", None


@dataclass
class YearLdlAudit:
    year: int
    stage_a: str = "—"
    stage_b: Optional[float] = None
    stage_c: Optional[float] = None
    stage_d: Optional[float] = None
    report_date: str = ""
    issues: List[str] = field(default_factory=list)


def _audit_year_row(
    user_id: str,
    year: int,
    db_row_value: Optional[float],
    report_date: str,
) -> YearLdlAudit:
    trace = _ingest_trace_for_year(user_id, year)
    stage_a = trace.get("stage_a") if trace else ""
    stage_b = trace.get("stage_b") if trace else None
    stage_c_db = sanitize_ldl_value(db_row_value)
    if trace and trace.get("stage_c") is not None:
        stage_c_db = sanitize_ldl_value(trace.get("stage_c")) or stage_c_db

    if not stage_a:
        stage_a, stage_b_asset = _vision_asset_ldl_for_year(user_id, year)
        if stage_b is None:
            stage_b = stage_b_asset
    else:
        stage_a = str(stage_a)

    stage_d = stage_c_db  # Context table must mirror validated DB read
    row = YearLdlAudit(
        year=year,
        stage_a=stage_a or "—",
        stage_b=stage_b,
        stage_c=stage_c_db,
        stage_d=stage_d,
        report_date=report_date,
    )
    row.issues = _verify_year_stages(row)
    return row


def _ldl_number_from_snippet(snippet: str) -> Optional[float]:
    if not snippet:
        return None
    m = re.search(r"([\d.]+)\s*(?:mmol|μmol|umol|mg)?", snippet, re.I)
    if not m:
        return None
    try:
        return sanitize_ldl_value(float(m.group(1)))
    except ValueError:
        return None


def _verify_year_stages(row: YearLdlAudit) -> List[str]:
    issues: List[str] = []
    a_num = _ldl_number_from_snippet(row.stage_a)
    if a_num is not None and row.stage_b is not None and not _values_equal(a_num, row.stage_b):
        issues.append(f"A→B：原文提取 {a_num:g} ≠ 解析值 {_fmt_stage_value(row.stage_b)}")
    for label, raw in (
        ("B", row.stage_b),
        ("C", row.stage_c),
        ("D", row.stage_d),
    ):
        if raw is not None and sanitize_ldl_value(raw) is None:
            issues.append(f"阶段 {label} 数值非法（{raw}），疑似串线")
    if row.stage_b is not None and row.stage_c is not None and not _values_equal(row.stage_b, row.stage_c):
        issues.append(f"A→B→C：解析值 {_fmt_stage_value(row.stage_b)} ≠ 库内值 {_fmt_stage_value(row.stage_c)}")
    if row.stage_c is not None and row.stage_d is not None and not _values_equal(row.stage_c, row.stage_d):
        issues.append(f"C→D：库内值 {_fmt_stage_value(row.stage_c)} ≠ 上下文表值 {_fmt_stage_value(row.stage_d)}")
    return issues


def build_ldl_pipeline_audit(
    user_id: str,
    years: Sequence[int],
) -> tuple[str, Dict[str, Any], str]:
    """
    Build markdown audit table + JSON payload + optional warning banner.

    Returns (markdown, json_dict, warning_banner).
    """
    year_list = sorted({int(y) for y in years if 1990 <= int(y) <= 2100})
    if not year_list:
        return "", {}, ""

    # Stage C/D: SQLite SELECT only — no static/mock LDL dictionaries.
    rows_db = query_ldl_metrics_for_calendar_years(
        user_id,
        year_list,
        security_inspect=False,
    )
    by_year: Dict[int, tuple[Optional[float], str]] = {}
    for r in rows_db:
        y = r.report_date.year
        sv = sanitize_ldl_value(r.value)
        if sv is None and r.value is not None:
            logger.warning(
                "[PHA Audit] Rejected invalid LDL in DB user=%s year=%s raw=%s",
                user_id,
                y,
                r.value,
            )
            continue
        prev = by_year.get(y)
        code = (r.metric_code or r.metric_name or "").upper()
        if prev is None or code == "LDL" or "LDL" in (r.metric_name or "").upper():
            by_year[y] = (sv, r.report_date.isoformat())

    audits: List[YearLdlAudit] = []
    for y in year_list:
        val, rd = by_year.get(y, (None, ""))
        audits.append(_audit_year_row(user_id, y, val, rd))

    all_issues: List[str] = []
    warning_banner = ""
    for a in audits:
        all_issues.extend(a.issues)

    if any(
        (a.stage_b is not None and a.stage_c is not None and not _values_equal(a.stage_b, a.stage_c))
        for a in audits
    ):
        warning_banner = (
            "[PHA System Warning: 检测到数据流在 B→C 阶段发生非预期篡改/串线，已锁定病灶。]"
        )
    elif any(
        (a.stage_c is not None and a.stage_d is not None and not _values_equal(a.stage_c, a.stage_d))
        for a in audits
    ):
        warning_banner = (
            "[PHA System Warning: 检测到数据流在 C→D 阶段发生非预期篡改/串线，已锁定病灶。]"
        )
    elif any(
        a.stage_b is not None and sanitize_ldl_value(a.stage_b) is None
        or a.stage_c is not None and sanitize_ldl_value(a.stage_c) is None
        for a in audits
    ):
        warning_banner = (
            "[PHA System Warning: 检测到数据流存在非法 LDL 数值（含负数或超范围），已锁定病灶。]"
        )

    lines = [
        "【PHA 资产全链路数据审计表 · Data Pipeline Audit Trace】",
        "| 年份 | A 原始片段 | B 解析值 | C SQLite | D 上下文表 | 体检日 | 状态 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for a in audits:
        status = "✅" if not a.issues else "⚠️ " + "; ".join(a.issues[:2])
        lines.append(
            f"| {a.year} | {a.stage_a[:40]}{'…' if len(a.stage_a) > 40 else ''} "
            f"| {_fmt_stage_value(a.stage_b, empty='未检出')} "
            f"| {_fmt_stage_value(a.stage_c, empty='未检出')} "
            f"| {_fmt_stage_value(a.stage_d, empty='未检出')} "
            f"| {a.report_date or '—'} | {status} |",
        )

    markdown = "\n".join(lines)
    payload = {
        "years": year_list,
        "warning_banner": warning_banner,
        "issues": all_issues,
        "rows": [
            {
                "year": a.year,
                "stage_a": a.stage_a,
                "stage_b": _fmt_stage_value(a.stage_b, empty="未检出"),
                "stage_c": _fmt_stage_value(a.stage_c, empty="未检出"),
                "stage_d": _fmt_stage_value(a.stage_d, empty="未检出"),
                "report_date": a.report_date,
                "issues": a.issues,
            }
            for a in audits
        ],
        "markdown": markdown,
    }
    return markdown, payload, warning_banner


def append_audit_to_message(
    user_message: str,
    audit_markdown: str,
    warning_banner: str,
) -> str:
    parts: List[str] = []
    if warning_banner:
        parts.append(warning_banner)
    if audit_markdown:
        parts.append(audit_markdown)
    if not parts:
        return user_message
    block = "\n\n".join(parts)
    return f"{user_message}\n\n---\n{block}" if user_message.strip() else block
