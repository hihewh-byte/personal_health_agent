"""Stage 3A.2 — Session episodic focus for attachment asset Q&A (multi-turn)."""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
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


def _focus_ttl_turns() -> int:
    try:
        return max(1, int(os.environ.get("PHA_SESSION_FOCUS_TTL_TURNS", "3")))
    except ValueError:
        return 3


def init_session_focus_schema(conn: Optional[sqlite3.Connection] = None) -> None:
    init_schema()
    own = conn is None
    db = conn or _connect()
    try:
        db.executescript(_FOCUS_SCHEMA)
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

    @property
    def active(self) -> bool:
        return bool((self.focus_summary or "").strip()) and self.turns_remaining > 0


def save_session_turn_focus(
    session_id: str,
    *,
    focus_summary: str,
    document_type: str = "",
    focus_tokens: Optional[List[str]] = None,
    turns_remaining: Optional[int] = None,
) -> None:
    sid = (session_id or "").strip()
    if not sid:
        return
    ttl = turns_remaining if turns_remaining is not None else _focus_ttl_turns()
    init_session_focus_schema()
    conn = _connect()
    try:
        now = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

        conn.execute(
            """
            INSERT INTO chat_session_turn_focus (
                session_id, focus_summary, document_type, focus_tokens_json,
                turns_remaining, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                focus_summary = excluded.focus_summary,
                document_type = excluded.document_type,
                focus_tokens_json = excluded.focus_tokens_json,
                turns_remaining = excluded.turns_remaining,
                updated_at = excluded.updated_at
            """,
            (
                sid,
                (focus_summary or "")[:4000],
                (document_type or "unknown")[:64],
                json.dumps(list(focus_tokens or [])[:64], ensure_ascii=False),
                int(ttl),
                now,
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
                   turns_remaining, updated_at
            FROM chat_session_turn_focus WHERE session_id = ?
            """,
            (sid,),
        ).fetchone()
        if not row:
            return None
        try:
            tokens = json.loads(row["focus_tokens_json"] or "[]")
        except json.JSONDecodeError:
            tokens = []
        return SessionTurnFocus(
            session_id=row["session_id"],
            focus_summary=row["focus_summary"] or "",
            document_type=row["document_type"] or "",
            focus_tokens=[str(t) for t in tokens if str(t).strip()],
            turns_remaining=int(row["turns_remaining"] or 0),
            updated_at=row["updated_at"] or "",
        )
    finally:
        conn.close()


def revive_session_turn_focus_for_message(
    session_id: str,
    raw_user_message: str,
) -> Optional[SessionTurnFocus]:
    """If TTL expired but user message hits stored focus tokens, refresh TTL once."""
    focus = get_session_turn_focus(session_id)
    if not focus or not (focus.focus_summary or "").strip():
        return None
    if focus.active:
        return focus
    from pha.attachment_asset_qa import user_hits_focus_tokens

    if not user_hits_focus_tokens(raw_user_message, focus.focus_tokens):
        return None
    save_session_turn_focus(
        session_id,
        focus_summary=focus.focus_summary,
        document_type=focus.document_type,
        focus_tokens=focus.focus_tokens,
        turns_remaining=_focus_ttl_turns(),
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


def focus_summary_from_parsed(parsed: Dict[str, Any]) -> str:
    ledger = (parsed.get("label_ledger") or "").strip()
    if ledger:
        return ledger[:4000]
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
