"""Stage 3A.2 / 3C-β — Session episodic focus (attachment + health profiles)."""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from pha.sqlite_storage import _connect, init_schema

_FOCUS_SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_session_turn_focus (
    session_id TEXT PRIMARY KEY,
    focus_summary TEXT NOT NULL DEFAULT '',
    document_type TEXT NOT NULL DEFAULT '',
    focus_tokens_json TEXT NOT NULL DEFAULT '[]',
    turns_remaining INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
"""

_FOCUS_MIGRATIONS: dict[str, str] = {
    "focus_profile": "TEXT NOT NULL DEFAULT ''",
    "focus_metric": "TEXT NOT NULL DEFAULT ''",
    "focus_lab_years_json": "TEXT NOT NULL DEFAULT '[]'",
    "focus_wearable_start": "TEXT NOT NULL DEFAULT ''",
    "focus_wearable_end": "TEXT NOT NULL DEFAULT ''",
    "last_user_message": "TEXT NOT NULL DEFAULT ''",
    "last_assistant_digest": "TEXT NOT NULL DEFAULT ''",
    "focus_goal": "TEXT NOT NULL DEFAULT ''",
    "focus_domains_json": "TEXT NOT NULL DEFAULT '[]'",
}


def _focus_ttl_turns() -> int:
    try:
        return max(1, int(os.environ.get("PHA_SESSION_FOCUS_TTL_TURNS", "3")))
    except ValueError:
        return 3


def _ensure_focus_columns(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(chat_session_turn_focus)")}
    for name, typedef in _FOCUS_MIGRATIONS.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE chat_session_turn_focus ADD COLUMN {name} {typedef}")


def init_session_focus_schema(conn: Optional[sqlite3.Connection] = None) -> None:
    init_schema()
    own = conn is None
    db = conn or _connect()
    try:
        db.executescript(_FOCUS_SCHEMA)
        _ensure_focus_columns(db)
        db.commit()
    finally:
        if own:
            db.close()


@dataclass
class SessionTurnFocus:
    session_id: str
    focus_summary: str
    document_type: str
    focus_tokens: List[str]
    turns_remaining: int
    updated_at: str = ""
    focus_profile: str = ""
    focus_metric: str = ""
    focus_lab_years: List[int] = field(default_factory=list)
    focus_wearable_start: str = ""
    focus_wearable_end: str = ""
    last_user_message: str = ""
    last_assistant_digest: str = ""
    focus_goal: str = ""
    focus_domains: list[str] = field(default_factory=list)

    @property
    def active(self) -> bool:
        if self.turns_remaining <= 0:
            return False
        if self.focus_profile or self.focus_metric or self.focus_lab_years or self.focus_goal:
            return True
        return bool((self.focus_summary or "").strip())


def _row_to_focus(row: sqlite3.Row) -> SessionTurnFocus:
    try:
        tokens = json.loads(row["focus_tokens_json"] or "[]")
    except json.JSONDecodeError:
        tokens = []
    try:
        years = json.loads(row["focus_lab_years_json"] or "[]")
    except (json.JSONDecodeError, KeyError, TypeError):
        years = []
    try:
        domains = json.loads(row["focus_domains_json"] or "[]")
    except (json.JSONDecodeError, KeyError, TypeError):
        domains = []
    keys = row.keys()
    return SessionTurnFocus(
        session_id=row["session_id"],
        focus_summary=row["focus_summary"] or "",
        document_type=row["document_type"] or "",
        focus_tokens=[str(t) for t in tokens if str(t).strip()],
        turns_remaining=int(row["turns_remaining"] or 0),
        updated_at=row["updated_at"] or "",
        focus_profile=(row["focus_profile"] if "focus_profile" in keys else "") or "",
        focus_metric=(row["focus_metric"] if "focus_metric" in keys else "") or "",
        focus_lab_years=[int(y) for y in years if str(y).strip()],
        focus_wearable_start=(row["focus_wearable_start"] if "focus_wearable_start" in keys else "") or "",
        focus_wearable_end=(row["focus_wearable_end"] if "focus_wearable_end" in keys else "") or "",
        last_user_message=(row["last_user_message"] if "last_user_message" in keys else "") or "",
        last_assistant_digest=(row["last_assistant_digest"] if "last_assistant_digest" in keys else "") or "",
        focus_goal=(row["focus_goal"] if "focus_goal" in keys else "") or "",
        focus_domains=[str(d) for d in domains if str(d).strip()],
    )


def save_session_turn_focus(
    session_id: str,
    *,
    focus_summary: str,
    document_type: str = "",
    focus_tokens: Optional[List[str]] = None,
    turns_remaining: Optional[int] = None,
    focus_profile: str = "",
    focus_metric: str = "",
    focus_lab_years: Optional[List[int]] = None,
    focus_wearable_start: str = "",
    focus_wearable_end: str = "",
    last_user_message: str = "",
    last_assistant_digest: str = "",
    focus_goal: str = "",
    focus_domains: Optional[List[str]] = None,
) -> None:
    sid = (session_id or "").strip()
    if not sid:
        return
    ttl = turns_remaining if turns_remaining is not None else _focus_ttl_turns()
    init_session_focus_schema()
    conn = _connect()
    try:
        now = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        years_json = json.dumps(list(focus_lab_years or [])[:16], ensure_ascii=False)
        domains_json = json.dumps(list(focus_domains or [])[:8], ensure_ascii=False)
        conn.execute(
            """
            INSERT INTO chat_session_turn_focus (
                session_id, focus_summary, document_type, focus_tokens_json,
                turns_remaining, updated_at,
                focus_profile, focus_metric, focus_lab_years_json,
                focus_wearable_start, focus_wearable_end,
                last_user_message, last_assistant_digest,
                focus_goal, focus_domains_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                focus_summary = excluded.focus_summary,
                document_type = excluded.document_type,
                focus_tokens_json = excluded.focus_tokens_json,
                turns_remaining = excluded.turns_remaining,
                updated_at = excluded.updated_at,
                focus_profile = excluded.focus_profile,
                focus_metric = excluded.focus_metric,
                focus_lab_years_json = excluded.focus_lab_years_json,
                focus_wearable_start = excluded.focus_wearable_start,
                focus_wearable_end = excluded.focus_wearable_end,
                last_user_message = excluded.last_user_message,
                last_assistant_digest = excluded.last_assistant_digest,
                focus_goal = excluded.focus_goal,
                focus_domains_json = excluded.focus_domains_json
            """,
            (
                sid,
                (focus_summary or "")[:4000],
                (document_type or "unknown")[:64],
                json.dumps(list(focus_tokens or [])[:64], ensure_ascii=False),
                int(ttl),
                now,
                (focus_profile or "")[:64],
                (focus_metric or "")[:64],
                years_json,
                (focus_wearable_start or "")[:32],
                (focus_wearable_end or "")[:32],
                (last_user_message or "")[:2000],
                (last_assistant_digest or "")[:2000],
                (focus_goal or "")[:64],
                domains_json,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_session_turn_focus(session_id: str) -> Optional[SessionTurnFocus]:
    sid = (session_id or "").strip()
    if not sid:
        return None
    init_session_focus_schema()
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT session_id, focus_summary, document_type, focus_tokens_json,
                   turns_remaining, updated_at,
                   focus_profile, focus_metric, focus_lab_years_json,
                   focus_wearable_start, focus_wearable_end,
                   last_user_message, last_assistant_digest,
                   focus_goal, focus_domains_json
            FROM chat_session_turn_focus WHERE session_id = ?
            """,
            (sid,),
        ).fetchone()
        if not row:
            return None
        return _row_to_focus(row)
    finally:
        conn.close()


def revive_session_turn_focus_for_message(
    session_id: str,
    raw_user_message: str,
) -> Optional[SessionTurnFocus]:
    """If TTL expired but user message hits stored focus tokens, refresh TTL once."""
    focus = get_session_turn_focus(session_id)
    if not focus:
        return None
    if focus.active:
        return focus
    from pha.attachment_asset_qa import user_hits_focus_tokens
    from pha.health_intent_catalog import extract_health_keywords, matches_anaphora

    msg = raw_user_message or ""
    revived = False
    if matches_anaphora(msg):
        revived = True
    elif focus.last_assistant_digest:
        overlap = set(extract_health_keywords(msg)) & set(
            extract_health_keywords(focus.last_assistant_digest),
        )
        revived = bool(overlap)
    if not revived and not user_hits_focus_tokens(raw_user_message, focus.focus_tokens):
        return None
    if not revived and not (focus.focus_summary or "").strip():
        return None
    save_session_turn_focus(
        session_id,
        focus_summary=focus.focus_summary,
        document_type=focus.document_type,
        focus_tokens=focus.focus_tokens,
        turns_remaining=_focus_ttl_turns(),
        focus_profile=focus.focus_profile,
        focus_metric=focus.focus_metric,
        focus_lab_years=focus.focus_lab_years,
        focus_wearable_start=focus.focus_wearable_start,
        focus_wearable_end=focus.focus_wearable_end,
        last_user_message=focus.last_user_message,
        last_assistant_digest=focus.last_assistant_digest,
    )
    return get_session_turn_focus(session_id)


def consume_session_turn_focus(session_id: str) -> Optional[SessionTurnFocus]:
    """Load focus and decrement TTL (call once per turn that uses it)."""
    focus = get_session_turn_focus(session_id)
    if not focus or not focus.active:
        return None
    remaining = max(0, focus.turns_remaining - 1)
    init_session_focus_schema()
    conn = _connect()
    try:
        now = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

        conn.execute(
            """
            UPDATE chat_session_turn_focus
            SET turns_remaining = ?, updated_at = ?
            WHERE session_id = ?
            """,
            (remaining, now, focus.session_id),
        )
        conn.commit()
    finally:
        conn.close()
    focus.turns_remaining = remaining
    if remaining <= 0:
        from pha.active_recall_ledger import clear_active_recall_ledger

        clear_active_recall_ledger(session_id)
    return focus


def clear_session_turn_focus(session_id: str) -> None:
    """Drop session focus (e.g. document_family conflict between turns)."""
    sid = (session_id or "").strip()
    if not sid:
        return
    init_session_focus_schema()
    conn = _connect()
    try:
        conn.execute("DELETE FROM chat_session_turn_focus WHERE session_id = ?", (sid,))
        conn.commit()
    finally:
        conn.close()
    from pha.active_recall_ledger import clear_active_recall_ledger

    clear_active_recall_ledger(sid)


def _serialize_metrics_fact_table(metrics: list) -> str:
    """Stage 3H (崩塌点 C 修复): metrics[] → 不可变确定性事实表（宪法第三条）。

    数字 100% 来自附件解析，作为本轮唯一数字源注入 ATTACHMENT_LABEL。
    """
    rows: list[str] = []
    for m in metrics:
        if not isinstance(m, dict):
            continue
        name = str(m.get("item") or m.get("metric_name") or "").strip()
        if not name:
            continue
        val = str(m.get("value_text") or m.get("value") or "").strip()
        unit = str(m.get("unit") or "").strip()
        ref = str(m.get("ref") or m.get("reference_range") or "").strip()
        abnormal = "异常" if m.get("is_abnormal") else "—"
        rows.append(
            f"| {name} | {val or '—'} | {unit or '—'} | {ref or '—'} | {abnormal} |",
        )
        if len(rows) >= 60:
            break
    if not rows:
        return ""
    header = [
        "【附件解析事实 · 本轮唯一数字源（不可改写）】",
        "| 项目 | 结果 | 单位 | 参考区间 | 异常 |",
        "| --- | --- | --- | --- | --- |",
    ]
    return "\n".join(header + rows)


def focus_summary_from_parsed(parsed: Dict[str, Any]) -> str:
    ledger = (parsed.get("label_ledger") or "").strip()
    if ledger:
        return ledger[:4000]
    metrics = parsed.get("metrics") or []
    if metrics:
        table = _serialize_metrics_fact_table(metrics)
        if table:
            return table[:4000]
    summary = (parsed.get("vision_summary") or "").strip()
    if summary:
        return summary[:4000]
    narr = parsed.get("narratives") or []
    if narr:
        return json.dumps(narr, ensure_ascii=False)[:4000]
    return ""


__all__ = [
    "SessionTurnFocus",
    "clear_session_turn_focus",
    "consume_session_turn_focus",
    "revive_session_turn_focus_for_message",
    "focus_summary_from_parsed",
    "get_session_turn_focus",
    "init_session_focus_schema",
    "save_session_turn_focus",
]
