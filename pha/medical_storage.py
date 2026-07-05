"""SQLite persistence for structured medical lab metrics from PDF reports."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional, Sequence

from pha.date_parser import safe_parse_date
from pha.data_sanitizer import sanitize_metric_fields
from pha.metric_customs import apply_customs_gate, is_polluted_metric_name
from pha.medical_metric_catalog import (
    HRV_LINKAGE_METRIC_CODES,
    resolve_metric_name,
    resolve_metric_name_for_read,
    UNKNOWN_REJECT,
    seed_medical_metrics_table,
)
from pha.sqlite_connection import release_connection
from pha.sqlite_storage import _connect, init_schema

logger = logging.getLogger(__name__)


@dataclass
class MedicalMetricRow:
    user_id: str
    report_date: date
    metric_name: str
    value: Optional[float]
    unit: str = ""
    reference_range: str = ""
    is_abnormal: bool = False
    source_filename: str = ""
    metric_code: str = ""
    name_en: str = ""
    name_zh: str = ""


@dataclass
class HealthNarrativeRow:
    """Non-numeric clinical narrative (ultrasound, ECG conclusions, physician summary)."""

    user_id: str
    report_date: date
    hospital: str = ""
    category: str = ""
    content: str = ""
    summary: str = ""
    source_filename: str = ""


def _narrative_summary(content: str, *, max_len: int = 50) -> str:
    s = re.sub(r"\s+", " ", (content or "").strip())
    if not s:
        return ""
    if len(s) <= max_len:
        return s
    return s[:max_len] + "…"


def _parse_ref_bounds(ref: str) -> tuple[Optional[float], Optional[float]]:
    s = (ref or "").strip().replace("—", "-").replace("–", "-")
    if not s:
        return None, None
    m_range = re.match(r"^([\d.]+)\s*[-~]\s*([\d.]+)", s)
    if m_range:
        return float(m_range.group(1)), float(m_range.group(2))
    m_lt = re.match(r"^[<≤]\s*([\d.]+)", s)
    if m_lt:
        return None, float(m_lt.group(1))
    m_gt = re.match(r"^[>≥]\s*([\d.]+)", s)
    if m_gt:
        return float(m_gt.group(1)), None
    return None, None


def parse_ref_bounds(ref: str) -> tuple[Optional[float], Optional[float]]:
    """Public alias for reference-range bound parsing (v2.1.0 clinical pipe)."""
    return _parse_ref_bounds(ref)


def is_value_abnormal(value: Optional[float], reference_range: str) -> bool:
    if value is None:
        return False
    lo, hi = _parse_ref_bounds(reference_range)
    if lo is not None and value < lo:
        return True
    if hi is not None and value > hi:
        return True
    return False


def _migrate_medical_reports_columns(db: sqlite3.Connection) -> None:
    cols = {row[1] for row in db.execute("PRAGMA table_info(medical_reports)")}
    for col, ddl in (
        ("metric_code", "ALTER TABLE medical_reports ADD COLUMN metric_code TEXT"),
        ("name_en", "ALTER TABLE medical_reports ADD COLUMN name_en TEXT"),
        ("name_zh", "ALTER TABLE medical_reports ADD COLUMN name_zh TEXT"),
    ):
        if col not in cols:
            db.execute(ddl)


def init_medical_schema(conn: Optional[sqlite3.Connection] = None) -> None:
    init_schema(conn)
    own = conn is None
    db = conn or _connect()
    try:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS medical_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                report_date TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                value REAL,
                unit TEXT,
                reference_range TEXT,
                is_abnormal INTEGER NOT NULL DEFAULT 0,
                source_filename TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_medical_user_date
                ON medical_reports (user_id, report_date);
            CREATE INDEX IF NOT EXISTS idx_medical_user_metric
                ON medical_reports (user_id, metric_name);
            """,
        )
        _migrate_medical_reports_columns(db)
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_medical_user_code
                ON medical_reports (user_id, metric_code)
            """,
        )
        db.commit()
        seed_medical_metrics_table(db)
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS health_report_assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                report_date TEXT NOT NULL,
                source_filename TEXT,
                source_kind TEXT NOT NULL DEFAULT 'pdf',
                vision_model TEXT,
                vision_raw_json TEXT,
                metrics_preview TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_health_assets_user
                ON health_report_assets (user_id, report_date DESC);
            CREATE TABLE IF NOT EXISTS health_narratives (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                date TEXT NOT NULL,
                hospital TEXT,
                category TEXT,
                content TEXT NOT NULL,
                summary TEXT,
                source_filename TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_health_narratives_user_date
                ON health_narratives (user_id, date);
            """,
        )
        db.commit()
    finally:
        if own:
            release_connection(db)


def _metrics_preview_from_rows(rows: Sequence[MedicalMetricRow], *, limit: int = 6) -> str:
    parts: List[str] = []
    for r in rows[:limit]:
        code = (r.metric_code or r.metric_name or "?").upper()
        val = f"{r.value:g}" if r.value is not None else "?"
        parts.append(f"{code}:{val}")
    return ", ".join(parts)


def _metrics_preview_from_json(data: dict[str, Any], *, limit: int = 6) -> str:
    parts: List[str] = []
    if data.get("hrv_rmssd_ms") is not None:
        parts.append(f"HRV:{data['hrv_rmssd_ms']}")
    if data.get("resting_heart_rate_bpm") is not None:
        parts.append(f"RHR:{data['resting_heart_rate_bpm']}")
    for entry in (data.get("metrics") or [])[:limit]:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("metric_name") or entry.get("item") or "?")
        val = entry.get("value")
        parts.append(f"{name}:{val}")
        if len(parts) >= limit:
            break
    return ", ".join(parts) if parts else "—"


def save_health_report_asset(
    user_id: str,
    report_date: date,
    *,
    source_filename: str,
    source_kind: str,
    vision_model: str,
    vision_raw: dict[str, Any],
    metrics_preview: str = "",
) -> int:
    """Idempotent asset archive — replaces prior row for same day + filename."""
    return upsert_health_report_asset(
        user_id,
        report_date,
        source_filename=source_filename,
        source_kind=source_kind,
        vision_model=vision_model,
        vision_raw=vision_raw,
        metrics_preview=metrics_preview,
    )


def upsert_health_report_asset(
    user_id: str,
    report_date: date,
    *,
    source_filename: str,
    source_kind: str,
    vision_model: str,
    vision_raw: dict[str, Any],
    metrics_preview: str = "",
) -> int:
    init_medical_schema()
    uid = (user_id or "default").strip() or "default"
    day = report_date.isoformat()
    fname = (source_filename or "").strip()
    preview = metrics_preview or _metrics_preview_from_json(vision_raw)
    conn = _connect()
    try:
        conn.execute(
            """
            DELETE FROM health_report_assets
            WHERE user_id = ? AND report_date LIKE ? AND source_filename = ?
            """,
            (uid, f"{day}%", fname),
        )
        cur = conn.execute(
            """
            INSERT INTO health_report_assets (
                user_id, report_date, source_filename, source_kind,
                vision_model, vision_raw_json, metrics_preview
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uid,
                _report_date_storage_value(report_date),
                fname,
                source_kind,
                vision_model or "",
                json.dumps(vision_raw, ensure_ascii=False),
                preview,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def list_health_report_assets(user_id: str, *, limit: int = 100) -> List[Dict[str, Any]]:
    """Archived uploads — falls back to grouped ``medical_reports`` if assets table empty."""
    init_medical_schema()
    uid = (user_id or "default").strip() or "default"
    conn = _connect()
    try:
        cur = conn.execute(
            """
            SELECT id, user_id, report_date, source_filename, source_kind,
                   vision_model, metrics_preview, created_at
            FROM health_report_assets
            WHERE user_id = ?
            ORDER BY report_date DESC, id DESC
            LIMIT ?
            """,
            (uid, limit),
        )
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            r["report_date"] = str(r.get("report_date") or "")[:10]
        if rows:
            return rows
    finally:
        conn.close()

    return _list_assets_from_medical_reports(uid, limit=limit)


def _list_assets_from_medical_reports(user_id: str, *, limit: int) -> List[Dict[str, Any]]:
    conn = _connect()
    try:
        cur = conn.execute(
            """
            SELECT substr(report_date, 1, 10) AS report_day,
                   source_filename,
                   GROUP_CONCAT(metric_code || ':' || COALESCE(CAST(value AS TEXT), '?'), ', ') AS preview
            FROM medical_reports
            WHERE user_id = ?
            GROUP BY report_day, source_filename
            ORDER BY report_day DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        out: List[Dict[str, Any]] = []
        for idx, row in enumerate(cur.fetchall()):
            fname = row["source_filename"] or "report"
            kind = "screenshot" if fname.lower().endswith((".png", ".jpg", ".jpeg")) else "pdf"
            out.append(
                {
                    "id": f"legacy-{idx}",
                    "user_id": user_id,
                    "report_date": row["report_day"],
                    "source_filename": fname,
                    "source_kind": kind,
                    "vision_model": "",
                    "metrics_preview": row["preview"] or "—",
                    "created_at": "",
                    "legacy": True,
                },
            )
        return out
    finally:
        conn.close()


def get_health_report_asset(asset_id: int, user_id: str) -> Optional[Dict[str, Any]]:
    init_medical_schema()
    uid = (user_id or "default").strip() or "default"
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT id, user_id, report_date, source_filename, source_kind,
                   vision_model, vision_raw_json, metrics_preview, created_at
            FROM health_report_assets
            WHERE id = ? AND user_id = ?
            """,
            (asset_id, uid),
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        data["report_date"] = str(data.get("report_date") or "")[:10]
        raw = data.get("vision_raw_json") or "{}"
        try:
            data["vision_raw"] = json.loads(raw)
        except json.JSONDecodeError:
            data["vision_raw"] = {"raw": raw}
        return data
    finally:
        conn.close()


def _report_date_storage_value(d: date) -> str:
    """End-of-day timestamp for alignment with full-day wearable rollups."""
    return datetime.combine(d, time(23, 59, 59)).isoformat()


def delete_metric_by_name(user_id: str, report_date: date, metric_name: str, *, metric_code: str = "") -> None:
    """Remove one metric slot before idempotent upsert (same day + same name/code)."""
    init_medical_schema()
    uid = user_id.strip() or "default"
    day = report_date.isoformat()
    name = (metric_name or "").strip()
    code = (metric_code or name).strip()
    conn = _connect()
    try:
        conn.execute(
            """
            DELETE FROM medical_reports
            WHERE user_id = ? AND report_date LIKE ?
              AND (metric_name = ? OR metric_code = ? OR metric_name = ?)
            """,
            (uid, f"{day}%", name, code, code),
        )
        conn.commit()
    finally:
        conn.close()


def _dedupe_metric_rows(rows: Sequence[MedicalMetricRow]) -> List[MedicalMetricRow]:
    """Keep last row per (report_date, metric_name) within one ingest batch."""
    out: dict[tuple[str, str], MedicalMetricRow] = {}
    for r in rows:
        key = (r.report_date.isoformat(), (r.metric_name or "").strip().lower())
        if not key[1]:
            continue
        out[key] = r
    return list(out.values())


def upsert_medical_metrics(rows: Sequence[MedicalMetricRow]) -> int:
    """
    Idempotent write: same user + day + metric_name always has at most one row (latest wins).
    """
    guarded: List[MedicalMetricRow] = []
    for r in rows:
        if is_ldl_metric_name(r.metric_name or r.metric_code or ""):
            sv = sanitize_ldl_value(r.value)
            if r.value is not None and sv is None:
                logger.warning(
                    "[PHA LDL Guard] Blocked upsert invalid LDL user=%s date=%s raw=%s",
                    r.user_id,
                    r.report_date,
                    r.value,
                )
                continue
            r.value = sv
        guarded.append(r)
    deduped = _dedupe_metric_rows(guarded)
    if not deduped:
        return 0
    for r in deduped:
        delete_metric_by_name(
            r.user_id,
            r.report_date,
            r.metric_name,
            metric_code=r.metric_code or r.metric_name,
        )
    return insert_medical_metrics(deduped)


def insert_medical_metrics(rows: Sequence[MedicalMetricRow]) -> int:
    if not rows:
        return 0
    init_medical_schema()
    conn = _connect()
    try:
        conn.executemany(
            """
            INSERT INTO medical_reports (
                user_id, report_date, metric_name, metric_code, name_en, name_zh,
                value, unit, reference_range, is_abnormal, source_filename
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    r.user_id,
                    _report_date_storage_value(r.report_date),
                    r.metric_name.strip(),
                    r.metric_code or r.metric_name,
                    r.name_en or r.metric_name,
                    r.name_zh or r.metric_name,
                    r.value,
                    r.unit or "",
                    r.reference_range or "",
                    1 if r.is_abnormal else 0,
                    r.source_filename or "",
                )
                for r in rows
            ],
        )
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def delete_report_metrics(user_id: str, report_date: date) -> None:
    init_medical_schema()
    conn = _connect()
    try:
        conn.execute(
            "DELETE FROM medical_reports WHERE user_id = ? AND report_date LIKE ?",
            (user_id.strip() or "default", f"{report_date.isoformat()}%"),
        )
        conn.commit()
    finally:
        conn.close()


def _dedupe_narrative_rows(rows: Sequence[HealthNarrativeRow]) -> List[HealthNarrativeRow]:
    out: dict[tuple[str, str, str], HealthNarrativeRow] = {}
    for r in rows:
        content = (r.content or "").strip()
        if not content:
            continue
        key = (
            r.report_date.isoformat(),
            (r.category or "").strip().lower(),
            content[:200].lower(),
        )
        out[key] = r
    return list(out.values())


def upsert_health_narratives(rows: Sequence[HealthNarrativeRow]) -> int:
    """Replace same-day narratives from same source file, then insert deduped rows."""
    deduped = _dedupe_narrative_rows(rows)
    if not deduped:
        return 0
    by_day_source: dict[tuple[str, str], List[HealthNarrativeRow]] = {}
    for r in deduped:
        k = (r.report_date.isoformat(), (r.source_filename or "").strip())
        by_day_source.setdefault(k, []).append(r)
    conn = _connect()
    init_medical_schema()
    try:
        for (day, src), group in by_day_source.items():
            if src:
                conn.execute(
                    """
                    DELETE FROM health_narratives
                    WHERE user_id = ? AND date LIKE ? AND source_filename = ?
                    """,
                    (group[0].user_id, f"{day}%", src),
                )
            else:
                delete_report_narratives(group[0].user_id, group[0].report_date)
        conn.commit()
    finally:
        conn.close()
    return insert_health_narratives(deduped)


def insert_health_narratives(rows: Sequence[HealthNarrativeRow]) -> int:
    if not rows:
        return 0
    init_medical_schema()
    conn = _connect()
    try:
        conn.executemany(
            """
            INSERT INTO health_narratives (
                user_id, date, hospital, category, content, summary, source_filename
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    r.user_id,
                    _report_date_storage_value(r.report_date),
                    (r.hospital or "").strip(),
                    (r.category or "").strip() or "未分类",
                    (r.content or "").strip(),
                    (r.summary or _narrative_summary(r.content)).strip(),
                    r.source_filename or "",
                )
                for r in rows
                if (r.content or "").strip()
            ],
        )
        conn.commit()
        return len([r for r in rows if (r.content or "").strip()])
    finally:
        conn.close()


def delete_report_narratives(user_id: str, report_date: date) -> None:
    init_medical_schema()
    conn = _connect()
    try:
        conn.execute(
            "DELETE FROM health_narratives WHERE user_id = ? AND date LIKE ?",
            (user_id.strip() or "default", f"{report_date.isoformat()}%"),
        )
        conn.commit()
    finally:
        conn.close()


def query_narratives_in_range(
    user_id: str,
    start_date: date,
    end_date: date,
) -> List[HealthNarrativeRow]:
    init_medical_schema()
    uid = user_id.strip() or "default"
    if end_date < start_date:
        start_date, end_date = end_date, start_date
    conn = _connect()
    try:
        cur = conn.execute(
            """
            SELECT user_id, date, hospital, category, content, summary, source_filename
            FROM health_narratives
            WHERE user_id = ? AND date >= ? AND date <= ?
            ORDER BY date DESC, id DESC
            """,
            (uid, start_date.isoformat(), end_date.isoformat()),
        )
        out: List[HealthNarrativeRow] = []
        for row in cur.fetchall():
            out.append(
                HealthNarrativeRow(
                    user_id=row["user_id"],
                    report_date=safe_parse_date(row["date"]) or date.today(),
                    hospital=row["hospital"] or "",
                    category=row["category"] or "",
                    content=row["content"] or "",
                    summary=row["summary"] or "",
                    source_filename=row["source_filename"] or "",
                ),
            )
        return out
    finally:
        conn.close()


def clear_user_medical_data(user_id: str) -> tuple[int, int, int]:
    """Delete all ``medical_reports`` and ``health_report_assets`` for a user."""
    init_medical_schema()
    uid = (user_id or "default").strip() or "default"
    conn = _connect()
    try:
        before_reports = conn.execute(
            "SELECT COUNT(*) FROM medical_reports WHERE user_id = ?",
            (uid,),
        ).fetchone()[0]
        before_assets = conn.execute(
            "SELECT COUNT(*) FROM health_report_assets WHERE user_id = ?",
            (uid,),
        ).fetchone()[0]
        before_narratives = conn.execute(
            "SELECT COUNT(*) FROM health_narratives WHERE user_id = ?",
            (uid,),
        ).fetchone()[0]
        conn.execute("DELETE FROM medical_reports WHERE user_id = ?", (uid,))
        conn.execute("DELETE FROM health_report_assets WHERE user_id = ?", (uid,))
        conn.execute("DELETE FROM health_narratives WHERE user_id = ?", (uid,))
        conn.commit()
        return int(before_reports), int(before_assets), int(before_narratives)
    finally:
        conn.close()


def _row_from_db(row: sqlite3.Row) -> MedicalMetricRow:
    return MedicalMetricRow(
        user_id=row["user_id"],
        report_date=safe_parse_date(row["report_date"]) or date.today(),
        metric_name=row["metric_name"],
        value=row["value"],
        unit=row["unit"] or "",
        reference_range=row["reference_range"] or "",
        is_abnormal=bool(row["is_abnormal"]),
        source_filename=row["source_filename"] or "",
        metric_code=row["metric_code"] or row["metric_name"],
        name_en=row["name_en"] or row["metric_name"],
        name_zh=row["name_zh"] or row["metric_name"],
    )


def query_metrics_in_range(
    user_id: str,
    start_date: date,
    end_date: date,
) -> List[MedicalMetricRow]:
    init_medical_schema()
    uid = user_id.strip() or "default"
    if end_date < start_date:
        start_date, end_date = end_date, start_date
    conn = _connect()
    try:
        cur = conn.execute(
            """
            SELECT user_id, report_date, metric_name, metric_code, name_en, name_zh,
                   value, unit, reference_range, is_abnormal, source_filename
            FROM medical_reports
            WHERE user_id = ?
              AND substr(report_date, 1, 10) >= ?
              AND substr(report_date, 1, 10) <= ?
            ORDER BY report_date DESC, metric_name
            """,
            (uid, start_date.isoformat()[:10], end_date.isoformat()[:10]),
        )
        return [_row_from_db(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_latest_report_date(user_id: str, *, before: date) -> Optional[date]:
    init_medical_schema()
    uid = user_id.strip() or "default"
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT MAX(report_date) AS d FROM medical_reports
            WHERE user_id = ? AND report_date <= ?
            """,
            (uid, before.isoformat()),
        ).fetchone()
        if row and row["d"]:
            return safe_parse_date(row["d"])
        return None
    finally:
        conn.close()


def get_metrics_for_report(user_id: str, report_date: date) -> List[MedicalMetricRow]:
    """All metrics for one report day (handles ``YYYY-MM-DD`` and ``…T23:59:59`` storage)."""
    init_medical_schema()
    uid = user_id.strip() or "default"
    prefix = report_date.isoformat()
    conn = _connect()
    try:
        cur = conn.execute(
            """
            SELECT user_id, report_date, metric_name, metric_code, name_en, name_zh,
                   value, unit, reference_range, is_abnormal, source_filename
            FROM medical_reports
            WHERE user_id = ? AND report_date LIKE ?
            ORDER BY metric_name
            """,
            (uid, f"{prefix}%"),
        )
        return [_row_from_db(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_latest_medical_report(
    user_id: str,
) -> tuple[Optional[date], List[MedicalMetricRow]]:
    """Global latest checkup: ORDER BY report_date DESC LIMIT 1 (any year — 2023/2025/2026)."""
    init_medical_schema()
    uid = user_id.strip() or "default"
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT substr(report_date, 1, 10) AS d
            FROM medical_reports
            WHERE user_id = ?
            ORDER BY report_date DESC
            LIMIT 1
            """,
            (uid,),
        ).fetchone()
        if not row or not row["d"]:
            return None, []
        latest = safe_parse_date(row["d"])
        if latest is None:
            return None, []
    finally:
        conn.close()
    return latest, get_metrics_for_report(uid, latest)


def _year_match_sql_clause(years: Sequence[int]) -> tuple[str, list]:
    """
    Robust calendar-year match for TEXT report_date (ISO, T-suffix, Z, spaces).

    Uses ``LIKE 'YYYY%'`` OR ``strftime('%Y')`` — never rely on substr alone.
    """
    year_strs = sorted({str(int(y)) for y in years if 1990 <= int(y) <= 2100})
    if not year_strs:
        return "0", []
    parts: List[str] = []
    params: List[str] = []
    for ys in year_strs:
        parts.append(
            "(CAST(report_date AS TEXT) LIKE ? OR strftime('%Y', report_date) = ? "
            "OR substr(CAST(report_date AS TEXT), 1, 4) = ?)",
        )
        params.extend([f"{ys}%", ys, ys])
    return "(" + " OR ".join(parts) + ")", params


LDL_ALIAS_LIST: tuple[str, ...] = (
    "LDL",
    "LDL-C",
    "LDL_C",
    "低密度脂蛋白",
    "低密度脂蛋白胆固醇",
    "低密度脂蛋白(LDL-C)",
)

LDL_METRIC_ALIASES: tuple[str, ...] = tuple(
    {a.lower() for a in LDL_ALIAS_LIST}
    | {"ldl", "ldl-c", "ldl_c", "low density lipoprotein", "低密度脂蛋白胆固醇测定"}
)

LDL_VALUE_MIN: float = 0.0
LDL_VALUE_MAX: float = 15.0  # mmol/L physical sanity ceiling


def is_ldl_metric_name(name: str) -> bool:
    blob = (name or "").lower()
    return any(alias in blob for alias in LDL_METRIC_ALIASES)


def sanitize_ldl_value(value: Optional[float]) -> Optional[float]:
    """Reject negative / out-of-range LDL (prevents Pearson-like串线 values)."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v < LDL_VALUE_MIN or v > LDL_VALUE_MAX:
        return None
    return round(v, 4)


def format_ldl_display_value(value: Optional[float]) -> str:
    """Human-facing LDL cell — never show negative numbers."""
    v = sanitize_ldl_value(value)
    if v is None:
        return "未检出"
    return f"{v:g}"


def query_metrics_for_calendar_years(
    user_id: str,
    years: Sequence[int],
) -> List[MedicalMetricRow]:
    """All metrics whose report_date calendar year is in *years*."""
    init_medical_schema()
    uid = user_id.strip() or "default"
    clause, clause_params = _year_match_sql_clause(years)
    if clause == "0":
        return []
    conn = _connect()
    try:
        cur = conn.execute(
            f"""
            SELECT user_id, report_date, metric_name, metric_code, name_en, name_zh,
                   value, unit, reference_range, is_abnormal, source_filename
            FROM medical_reports
            WHERE user_id = ? AND {clause}
            ORDER BY report_date DESC, metric_name
            """,
            (uid, *clause_params),
        )
        return [_row_from_db(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _ldl_metric_sql_clause() -> tuple[str, list]:
    """SQL fragment matching LDL / LDL-C / 低密度脂蛋白* (ASCII + Chinese)."""
    parts: List[str] = []
    params: List[str] = []
    ascii_upper = sorted({a.upper() for a in LDL_ALIAS_LIST if a.isascii()})
    if ascii_upper:
        ph = ",".join("?" * len(ascii_upper))
        parts.append(f"UPPER(metric_name) IN ({ph})")
        parts.append(f"UPPER(metric_code) IN ({ph})")
        params.extend(ascii_upper)
        params.extend(ascii_upper)
    for zh in LDL_ALIAS_LIST:
        if not zh.isascii():
            parts.append("(metric_name LIKE ? OR name_zh LIKE ? OR metric_code LIKE ?)")
            params.extend([f"%{zh}%", f"%{zh}%", f"%{zh}%"])
    if not parts:
        return "0", []
    return "(" + " OR ".join(parts) + ")", params


# Harness/dev LDL seed rows inserted during agent testing — must never ship to users.
_HARNESS_TEST_LDL_DATES: tuple[str, ...] = ("2023-06-15", "2025-03-10")
_HARNESS_TEST_LDL_VALUES: tuple[float, ...] = (3.2, 2.9)


def purge_harness_test_ldl_seed_rows() -> int:
    """
    Physically delete mock LDL rows (2023-06-15 / 2025-03-10 · 3.2 / 2.9) from SQLite.
    No in-code static dicts — this only clears mistaken dev seeds in ``medical_reports``.
    """
    init_medical_schema()
    conn = _connect()
    removed = 0
    try:
        for day in _HARNESS_TEST_LDL_DATES:
            for val in _HARNESS_TEST_LDL_VALUES:
                cur = conn.execute(
                    """
                    DELETE FROM medical_reports
                    WHERE (report_date LIKE ? OR substr(report_date, 1, 10) = ?)
                      AND UPPER(metric_name) = 'LDL'
                      AND value = ?
                    """,
                    (f"{day}%", day, val),
                )
                removed += cur.rowcount
        if removed:
            conn.commit()
            logger.warning(
                "[PHA Purge] Removed %s harness test LDL seed row(s) (%s)",
                removed,
                ", ".join(_HARNESS_TEST_LDL_DATES),
            )
    finally:
        conn.close()
    return removed


def purge_invalid_ldl_metrics(user_id: Optional[str] = None) -> int:
    """Delete LDL rows with negative or out-of-range values (legacy串线 cleanup)."""
    init_medical_schema()
    conn = _connect()
    removed = 0
    try:
        ldl_clause, ldl_params = _ldl_metric_sql_clause()
        if ldl_clause == "0":
            return 0
        if user_id:
            uids = [(user_id or "default").strip() or "default"]
        else:
            uids = [
                str(r[0])
                for r in conn.execute(
                    "SELECT DISTINCT user_id FROM medical_reports",
                ).fetchall()
            ]
        bad_ids: List[int] = []
        for uid in uids:
            cur = conn.execute(
                f"""
                SELECT id, value FROM medical_reports
                WHERE user_id = ? AND {ldl_clause}
                """,
                (uid, *ldl_params),
            )
            for row in cur.fetchall():
                if sanitize_ldl_value(row["value"]) is None and row["value"] is not None:
                    bad_ids.append(int(row["id"]))
        if bad_ids:
            ph = ",".join("?" * len(bad_ids))
            conn.execute(
                f"DELETE FROM medical_reports WHERE id IN ({ph})",
                bad_ids,
            )
            conn.commit()
            removed = len(bad_ids)
            logger.warning(
                "[PHA LDL Purge] Removed %s invalid LDL rows for user=%s",
                removed,
                uid,
            )
    finally:
        conn.close()
    return removed


def query_ldl_metrics_for_calendar_years(
    user_id: str,
    years: Sequence[int],
    *,
    security_inspect: bool = True,
) -> List[MedicalMetricRow]:
    """
    LDL rows for calendar years — SQL-first (strftime + LIKE year + alias IN/LIKE).

    Prints ``[PHA Security Inspection]`` rows for harness audit.
    """
    init_medical_schema()
    uid = user_id.strip() or "default"
    year_strs = sorted({str(int(y)) for y in years if 1990 <= int(y) <= 2100})
    if not year_strs:
        if security_inspect:
            print("[PHA Security Inspection] SQL Extracted LDL rows: []", flush=True)
        return []

    year_parts: List[str] = []
    year_params: List[str] = []
    for ys in year_strs:
        year_parts.append(
            "(strftime('%Y', report_date) = ? OR CAST(report_date AS TEXT) LIKE ?)",
        )
        year_params.extend([ys, f"{ys}%"])

    ldl_clause, ldl_params = _ldl_metric_sql_clause()
    if ldl_clause == "0":
        if security_inspect:
            print("[PHA Security Inspection] SQL Extracted LDL rows: []", flush=True)
        return []

    year_sql = "(" + " OR ".join(year_parts) + ")"
    conn = _connect()
    try:
        cur = conn.execute(
            f"""
            SELECT user_id, report_date, metric_name, metric_code, name_en, name_zh,
                   value, unit, reference_range, is_abnormal, source_filename
            FROM medical_reports
            WHERE user_id = ?
              AND {year_sql}
              AND {ldl_clause}
            ORDER BY report_date ASC, metric_name
            """,
            (uid, *year_params, *ldl_params),
        )
        raw_rows = cur.fetchall()
    finally:
        conn.close()

    rows = [_row_from_db(r) for r in raw_rows]
    validated: List[MedicalMetricRow] = []
    for r in rows:
        if not is_ldl_metric_name(r.metric_name or r.metric_code or ""):
            continue
        sv = sanitize_ldl_value(r.value)
        if r.value is not None and sv is None:
            logger.warning(
                "[PHA LDL Guard] Dropped invalid LDL row user=%s date=%s raw=%s name=%s",
                uid,
                r.report_date,
                r.value,
                r.metric_name,
            )
            continue
        if sv is not None:
            r.value = sv
        validated.append(r)
    rows = validated
    if security_inspect:
        slim = [
            {
                "metric_name": r.metric_name,
                "value": r.value,
                "report_date": str(r.report_date),
                "unit": r.unit,
            }
            for r in rows
        ]
        print(f"[PHA Security Inspection] SQL Extracted LDL rows: {slim}", flush=True)
        if not slim:
            ys = "/".join(year_strs)
            print(
                f"[PHA Warning] Year {ys} LDL data parsed as EMPTY. Check SQL conditions!",
                flush=True,
            )

    return rows


def format_ldl_crossyear_markdown_table(
    user_id: str,
    years: Sequence[int],
    *,
    security_inspect: bool = True,
) -> str:
    """Markdown table for user-message boundary — only SQLite-extracted LDL values."""
    year_list = sorted({int(y) for y in years})
    rows = query_ldl_metrics_for_calendar_years(
        user_id,
        year_list,
        security_inspect=security_inspect,
    )
    lines = [
        "【LDL 跨年对账表 · SQLite 实测】",
        "| 年份 | 指标名 | 数值 | 单位 | 参考范围 | 体检日 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    if not rows:
        for y in year_list:
            lines.append(f"| {y} | （无入库记录） | — | — | — | — |")
        lines.append(
            "说明：上表为空表示 medical_reports 中无 LDL/LDL-C/低密度脂蛋白 记录，"
            "禁止编造转氨酶、CRP 或其他未列出指标数值。"
        )
        return "\n".join(lines)

    # Best row per calendar year (prefer metric_code LDL, else first)
    by_year: dict[int, MedicalMetricRow] = {}
    for r in rows:
        y = r.report_date.year
        prev = by_year.get(y)
        if prev is None:
            by_year[y] = r
            continue
        code = (r.metric_code or r.metric_name or "").upper()
        if code == "LDL" or "LDL" in (r.metric_name or "").upper():
            by_year[y] = r

    for y in year_list:
        r = by_year.get(y)
        if not r:
            lines.append(f"| {y} | （无入库记录） | — | — | — | — |")
            continue
        val = format_ldl_display_value(r.value)
        name = r.name_zh or r.metric_name or r.metric_code or "LDL"
        ref = r.reference_range or "—"
        lines.append(
            f"| {y} | {name} | {val} | {r.unit or '—'} | {ref} | {r.report_date.isoformat()} |",
        )
    return "\n".join(lines)


def query_narratives_for_calendar_years(
    user_id: str,
    years: Sequence[int],
) -> List[HealthNarrativeRow]:
    """Narratives for calendar years in *years*."""
    init_medical_schema()
    uid = user_id.strip() or "default"
    clause, clause_params = _year_match_sql_clause(years)
    if clause == "0":
        return []
    conn = _connect()
    try:
        date_clause = clause.replace("report_date", "date")
        cur = conn.execute(
            f"""
            SELECT user_id, date, hospital, category, content, summary, source_filename
            FROM health_narratives
            WHERE user_id = ? AND {date_clause}
            ORDER BY date DESC
            """,
            (uid, *clause_params),
        )
        out: List[HealthNarrativeRow] = []
        for row in cur.fetchall():
            out.append(
                HealthNarrativeRow(
                    user_id=row["user_id"],
                    report_date=safe_parse_date(row["date"]) or date.today(),
                    hospital=row["hospital"] or "",
                    category=row["category"] or "",
                    content=row["content"] or "",
                    summary=row["summary"] or "",
                    source_filename=row["source_filename"] or "",
                ),
            )
        return out
    finally:
        conn.close()


def list_distinct_report_dates(user_id: str, *, limit: int = 20) -> List[date]:
    """Distinct calendar checkup days (newest first) for temporal routing."""
    init_medical_schema()
    uid = user_id.strip() or "default"
    conn = _connect()
    try:
        cur = conn.execute(
            """
            SELECT DISTINCT substr(report_date, 1, 10) AS d
            FROM medical_reports
            WHERE user_id = ?
            ORDER BY d DESC
            LIMIT ?
            """,
            (uid, max(1, limit)),
        )
        out: List[date] = []
        for row in cur.fetchall():
            d = safe_parse_date(row["d"])
            if d is not None:
                out.append(d)
        return out
    finally:
        conn.close()


def get_latest_linkage_metrics(
    user_id: str,
    reference_date: date,
) -> List[MedicalMetricRow]:
    """Key labs from the most recent checkup (for HRV / recovery questions)."""
    latest = get_latest_report_date(user_id, before=reference_date)
    if latest is None:
        return []
    rows = get_metrics_for_report(user_id, latest)
    out: List[MedicalMetricRow] = []
    for row in rows:
        code = (
            row.metric_code or resolve_metric_name_for_read(row.metric_name).code
        ).upper()
        if code in HRV_LINKAGE_METRIC_CODES:
            if row.value is not None and not row.is_abnormal:
                row.is_abnormal = is_value_abnormal(row.value, row.reference_range)
            out.append(row)
    return out


def get_abnormal_metrics_last_year(
    user_id: str,
    reference_date: date,
    *,
    years: float = 1.0,
) -> List[MedicalMetricRow]:
    days = int(years * 365)
    start = reference_date - timedelta(days=days)
    rows = query_metrics_in_range(user_id, start, reference_date)
    seen: set[tuple[str, str]] = set()
    abnormal: List[MedicalMetricRow] = []
    for row in rows:
        if row.value is not None and not row.is_abnormal:
            row.is_abnormal = is_value_abnormal(row.value, row.reference_range)
        if not row.is_abnormal:
            continue
        key = (row.report_date.isoformat(), row.metric_code or row.metric_name)
        if key in seen:
            continue
        seen.add(key)
        abnormal.append(row)
    return abnormal


def _display_label(row: MedicalMetricRow) -> str:
    code = row.metric_code or row.metric_name
    if code in ("LDL", "HDL"):
        return f"{code}-C"
    return code


def _abnormal_phrase_en(row: MedicalMetricRow) -> str:
    label = _display_label(row)
    val = f"{row.value:g}" if row.value is not None else "?"
    unit = f" {row.unit}".strip() if row.unit else ""
    ref = row.reference_range or "—"
    lo, hi = _parse_ref_bounds(ref)
    direction = "abnormal"
    if row.value is not None and hi is not None and row.value > hi:
        direction = "high"
    elif row.value is not None and lo is not None and row.value < lo:
        direction = "low"
    return f"{label} is {direction} ({val}{unit}), Reference: {ref}"


def format_historical_baseline_block(
    user_id: str,
    reference_date: date,
    *,
    max_metrics: int = 24,
) -> str:
    """
    [Historical Baseline] — always inject the most recent checkup regardless of query window.
    """
    report_d, rows = get_latest_medical_report(user_id)
    if not report_d or not rows:
        return ""
    parts: List[str] = []
    for r in rows[:max_metrics]:
        if r.value is not None and not r.is_abnormal:
            r.is_abnormal = is_value_abnormal(r.value, r.reference_range)
        label = r.name_zh or r.metric_name or r.metric_code
        val = f"{r.value:g}" if r.value is not None else "?"
        unit = f" {r.unit}".strip() if r.unit else ""
        flag = "↑" if r.is_abnormal else ""
        parts.append(f"{label}{flag}={val}{unit}(ref:{r.reference_range or '—'})")
    body = "; ".join(parts)
    return (
        f"[Historical Baseline] 用户最近一次完整体检（{report_d.isoformat()}）。"
        f"以下为数据库实测指标（仅此列表，不得臆造未列出项）：{body}。"
    )


def format_medical_context_line(
    user_id: str,
    reference_date: date,
    *,
    prefer_latest_report: bool = True,
) -> str:
    """
    English line for LLM snapshot, e.g.
    ``Medical Context: [2026-03-01] LDL-C is high (4.2 mmol/L), Reference: <3.4.``
    """
    if prefer_latest_report:
        linkage = get_latest_linkage_metrics(user_id, reference_date)
        abnormal = [r for r in linkage if r.is_abnormal]
        if not abnormal:
            abnormal = [r for r in linkage if r.value is not None][:4]
        if abnormal:
            report_d = abnormal[0].report_date.isoformat()
            seen_codes: set[str] = set()
            parts: List[str] = []
            for r in abnormal:
                code = r.metric_code or r.metric_name
                if code in seen_codes:
                    continue
                seen_codes.add(code)
                parts.append(_abnormal_phrase_en(r))
                if len(parts) >= 5:
                    break
            return f"Medical Context: [{report_d}] " + "; ".join(parts) + "."

    abnormal = get_abnormal_metrics_last_year(user_id, reference_date)
    if not abnormal:
        return ""
    report_d = abnormal[0].report_date.isoformat()
    parts = [_abnormal_phrase_en(r) for r in abnormal[:5]]
    return f"Medical Context: [{report_d}] " + "; ".join(parts) + "."


def format_medical_abnormal_blurb(
    user_id: str,
    reference_date: date,
    *,
    max_items: int = 8,
) -> str:
    abnormal = get_abnormal_metrics_last_year(user_id, reference_date)
    if not abnormal:
        return ""
    parts: List[str] = ["体检异常指标(近1年):"]
    for row in abnormal[:max_items]:
        val_s = f"{row.value:g}" if row.value is not None else "?"
        label = row.name_zh or row.metric_name
        ref_s = f"({row.reference_range})" if row.reference_range else ""
        parts.append(f"{label}={val_s}{row.unit}{ref_s}@{row.report_date.isoformat()}")
    if len(abnormal) > max_items:
        parts.append(f"等共{len(abnormal)}项")
    return " ".join(parts) + "；"


def list_available_metrics_catalog(user_id: str) -> List[Dict[str, Any]]:
    """Distinct clean medical metrics only (wearable golden strip is API-level)."""
    init_medical_schema()
    uid = (user_id or "default").strip() or "default"
    items: List[Dict[str, Any]] = []
    seen: set[str] = set()

    conn = _connect()
    try:
        cur = conn.execute(
            """
            SELECT DISTINCT metric_code, metric_name, name_zh, unit
            FROM medical_reports
            WHERE user_id = ?
            ORDER BY metric_code, metric_name
            """,
            (uid,),
        )
        for row in cur.fetchall():
            raw_code = (row["metric_code"] or row["metric_name"] or "").strip()
            if not raw_code:
                continue
            resolved = resolve_metric_name_for_read(raw_code)
            code = resolved.code
            if not code or code == UNKNOWN_REJECT:
                continue
            label = (
                resolved.name_zh
                or (row["name_zh"] or row["metric_name"] or code).strip()
            )
            key = code
            if key in seen:
                continue
            seen.add(key)
            items.append(
                {
                    "id": key,
                    "label": label,
                    "source": "medical",
                    "unit": (row["unit"] or "").strip(),
                },
            )
    finally:
        conn.close()

    items.sort(key=lambda x: x["label"])
    return items


def query_metric_timeseries(
    user_id: str,
    metric_id: str,
    start_date: date,
    end_date: date,
) -> List[Dict[str, Any]]:
    """Time series for one metric — wearable daily or medical report points."""
    from pha.sqlite_storage import query_wearable_daily_range

    uid = (user_id or "default").strip() or "default"
    mid = (metric_id or "").strip().lower()
    if end_date < start_date:
        start_date, end_date = end_date, start_date

    if mid == "activity_kcal":
        rows = query_wearable_daily_range(uid, start_date, end_date)
        out: List[Dict[str, Any]] = []
        for r in rows:
            if r.active_energy_kcal is None:
                continue
            out.append({"label": r.day.isoformat(), "value": float(r.active_energy_kcal)})
        if out:
            return out
        from pha.sqlite_storage import query_active_energy_daily_range

        return query_active_energy_daily_range(uid, start_date, end_date)

    wearable_map = {
        "steps": lambda r: r.steps,
        "hrv": lambda r: r.hrv_rmssd_ms,
        "sleep": lambda r: r.sleep_hours,
        "rhr": lambda r: r.resting_heart_rate_bpm,
        "waso": lambda r: r.awake_duration_hours,
    }
    if mid in wearable_map:
        getter = wearable_map[mid]
        rows = query_wearable_daily_range(uid, start_date, end_date)
        out: List[Dict[str, Any]] = []
        for r in rows:
            v = getter(r)
            if v is None:
                continue
            out.append({"label": r.day.isoformat(), "value": float(v)})
        return out

    init_medical_schema()
    conn = _connect()
    try:
        cur = conn.execute(
            """
            SELECT substr(report_date, 1, 10) AS d, value, unit
            FROM medical_reports
            WHERE user_id = ?
              AND report_date >= ? AND report_date <= ?
              AND (metric_code = ? OR metric_name = ? OR UPPER(metric_code) = UPPER(?))
              AND value IS NOT NULL
            ORDER BY d ASC
            """,
            (
                uid,
                _report_date_storage_value(start_date),
                _report_date_storage_value(end_date),
                metric_id,
                metric_id,
                metric_id,
            ),
        )
        return [
            {"label": str(row["d"]), "value": float(row["value"])}
            for row in cur.fetchall()
            if row["value"] is not None
        ]
    finally:
        conn.close()


def normalize_and_enrich_row(
    user_id: str,
    report_date: date,
    raw_name: str,
    value: Optional[float],
    unit: str,
    reference_range: str,
    *,
    source_filename: str = "",
) -> Optional[MedicalMetricRow]:
    gated = apply_customs_gate(
        raw_name,
        value,
        unit,
        reference_range=reference_range,
        ingest_context=f"{user_id}:{report_date.isoformat()}",
    )
    if not gated:
        return None
    clean_name, value, unit, reference_range = gated
    resolved = resolve_metric_name(clean_name or raw_name)
    if resolved.code == UNKNOWN_REJECT:
        return None
    if resolved.code == "LDL" or is_ldl_metric_name(raw_name):
        value = sanitize_ldl_value(value)
    abnormal = is_value_abnormal(value, reference_range)
    return MedicalMetricRow(
        user_id=user_id,
        report_date=report_date,
        metric_name=resolved.code,
        metric_code=resolved.code,
        name_en=resolved.name_en,
        name_zh=resolved.name_zh,
        value=value,
        unit=unit,
        reference_range=reference_range,
        is_abnormal=abnormal,
        source_filename=source_filename,
    )
