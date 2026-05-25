"""Physical + SQLite batch deletion for PHA health assets (v1.9.5)."""

from __future__ import annotations

import logging
import os
import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from pha.attachment_storage import STORAGE_ROOT
from pha.chat_storage import init_chat_schema, _connect as chat_connect
from pha.date_parser import safe_parse_date
from pha.medical_storage import (
    get_health_report_asset,
    init_medical_schema,
)
from pha.sqlite_storage import _connect

logger = logging.getLogger(__name__)


def _safe_unlink(path: str) -> bool:
    p = (path or "").strip()
    if not p:
        return False
    try:
        resolved = Path(p).resolve()
        root = STORAGE_ROOT.resolve()
        if not str(resolved).startswith(str(root)):
            logger.warning("Refusing to delete path outside attachments root: %s", p)
            return False
        if resolved.is_file():
            resolved.unlink()
            return True
    except OSError as exc:
        logger.warning("Failed to unlink %s: %s", p, exc)
    return False


def _delete_sql_for_report_day(uid: str, day_prefix: str) -> Dict[str, int]:
    init_medical_schema()
    conn = _connect()
    counts = {"medical_reports": 0, "health_narratives": 0, "health_report_assets": 0}
    try:
        cur = conn.execute(
            "DELETE FROM medical_reports WHERE user_id = ? AND report_date LIKE ?",
            (uid, f"{day_prefix}%"),
        )
        counts["medical_reports"] = cur.rowcount
        cur = conn.execute(
            "DELETE FROM health_narratives WHERE user_id = ? AND date LIKE ?",
            (uid, f"{day_prefix}%"),
        )
        counts["health_narratives"] = cur.rowcount
        cur = conn.execute(
            "DELETE FROM health_report_assets WHERE user_id = ? AND report_date LIKE ?",
            (uid, f"{day_prefix}%"),
        )
        counts["health_report_assets"] = cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return counts


def _unlink_attachments_for_report_day(uid: str, day_prefix: str) -> int:
    init_chat_schema()
    conn = chat_connect()
    removed = 0
    try:
        rows = conn.execute(
            """
            SELECT id, attachment_path FROM chat_messages
            WHERE attachment_path IS NOT NULL AND attachment_path != ''
            """,
        ).fetchall()
        for row in rows:
            path = (row["attachment_path"] or "").strip()
            if not path:
                continue
            if day_prefix not in path and day_prefix not in str(row["id"]):
                continue
            if _safe_unlink(path):
                removed += 1
            conn.execute(
                """
                UPDATE chat_messages
                SET attachment_path = '', attachment_name = '', parsed_json = '', ingested_at = ''
                WHERE id = ?
                """,
                (int(row["id"]),),
            )
        conn.commit()
    finally:
        conn.close()
    return removed


def _parse_asset_id(asset_id: str) -> tuple[Optional[int], bool]:
    s = (asset_id or "").strip()
    if not s:
        return None, False
    if s.startswith("legacy-"):
        return None, True
    try:
        return int(s), False
    except ValueError:
        return None, False


def delete_assets_batch(
    user_id: str,
    *,
    asset_ids: Optional[Sequence[str]] = None,
    report_dates: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """
    Physical + SQL wipe for archived reports.

    Accepts numeric ``health_report_assets.id`` values and ``legacy-*`` synthetic ids.
    """
    uid = (user_id or "default").strip() or "default"
    days: set[str] = set()
    files_removed = 0
    sql_totals = {"medical_reports": 0, "health_narratives": 0, "health_report_assets": 0}
    assets_deleted_ids: List[str] = []

    for rd in report_dates or []:
        d = safe_parse_date(str(rd).strip()[:10])
        if d:
            days.add(d.isoformat()[:10])

    for aid in asset_ids or []:
        aid_s = str(aid).strip()
        if not aid_s:
            continue
        num_id, is_legacy = _parse_asset_id(aid_s)
        if is_legacy:
            m = re.match(r"legacy-(\d+)", aid_s)
            if m:
                assets_deleted_ids.append(aid_s)
            continue
        if num_id is None:
            continue
        asset = get_health_report_asset(num_id, uid)
        if asset:
            days.add(str(asset.get("report_date") or "")[:10])
            fname = (asset.get("source_filename") or "").strip()
            if fname:
                user_dir = STORAGE_ROOT / uid
                if user_dir.is_dir():
                    for f in user_dir.glob(f"*{Path(fname).suffix}"):
                        if fname in f.name or f.name.startswith(Path(fname).stem):
                            if _safe_unlink(str(f)):
                                files_removed += 1
        init_medical_schema()
        conn = _connect()
        try:
            conn.execute(
                "DELETE FROM health_report_assets WHERE id = ? AND user_id = ?",
                (num_id, uid),
            )
            conn.commit()
            sql_totals["health_report_assets"] += 1
        finally:
            conn.close()
        assets_deleted_ids.append(aid_s)

    for day in sorted(days):
        if len(day) < 10:
            continue
        c = _delete_sql_for_report_day(uid, day[:10])
        for k in sql_totals:
            sql_totals[k] += c.get(k, 0)
        files_removed += _unlink_attachments_for_report_day(uid, day[:10])
        user_dir = STORAGE_ROOT / uid
        if user_dir.is_dir():
            for f in user_dir.iterdir():
                if f.is_file() and day[:4] in f.name:
                    if _safe_unlink(str(f)):
                        files_removed += 1

    return {
        "ok": True,
        "user_id": uid,
        "report_dates": sorted(days),
        "asset_ids": assets_deleted_ids,
        "files_removed": files_removed,
        "sql_deleted": sql_totals,
    }
