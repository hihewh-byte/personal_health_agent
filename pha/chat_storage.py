"""SQLite-backed PHA health chat sessions and messages."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, List, Optional

from pha.date_parser import safe_parse_datetime
from pha.sqlite_storage import _connect, init_schema

CHAT_SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '新会话',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user ON chat_sessions (user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages (session_id, id);
"""


_CHAT_EXTRA_COLUMNS = (
    ("attachment_path", "TEXT"),
    ("attachment_name", "TEXT"),
    ("parsed_json", "TEXT"),
    ("ingested_at", "TEXT"),
)


def _migrate_chat_columns(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(chat_messages)").fetchall()}
    for name, col_type in _CHAT_EXTRA_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE chat_messages ADD COLUMN {name} {col_type}")


def init_chat_schema() -> None:
    init_schema()
    conn = _connect()
    try:
        conn.executescript(CHAT_SCHEMA)
        _migrate_chat_columns(conn)
        conn.commit()
    finally:
        conn.close()


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


@dataclass
class ChatSessionRow:
    id: str
    user_id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int = 0


@dataclass
class ChatMessageRow:
    id: int
    session_id: str
    role: str
    content: str
    created_at: str
    attachment_path: str = ""
    attachment_name: str = ""
    parsed_json: str = ""
    ingested_at: str = ""


def _row_to_message(r: sqlite3.Row) -> ChatMessageRow:
    keys = r.keys()
    return ChatMessageRow(
        id=int(r["id"]),
        session_id=r["session_id"],
        role=r["role"],
        content=r["content"],
        created_at=r["created_at"],
        attachment_path=(r["attachment_path"] if "attachment_path" in keys else "") or "",
        attachment_name=(r["attachment_name"] if "attachment_name" in keys else "") or "",
        parsed_json=(r["parsed_json"] if "parsed_json" in keys else "") or "",
        ingested_at=(r["ingested_at"] if "ingested_at" in keys else "") or "",
    )


def create_session(user_id: str, *, title: str = "新会话") -> ChatSessionRow:
    init_chat_schema()
    sid = str(uuid.uuid4())
    now = _now_iso()
    uid = (user_id or "default").strip() or "default"
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO chat_sessions (id, user_id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (sid, uid, title[:200], now, now),
        )
        conn.commit()
    finally:
        conn.close()
    return ChatSessionRow(id=sid, user_id=uid, title=title[:200], created_at=now, updated_at=now)


def list_sessions(user_id: str, *, limit: int = 40) -> List[ChatSessionRow]:
    init_chat_schema()
    uid = (user_id or "default").strip() or "default"
    conn = _connect()
    try:
        cur = conn.execute(
            """
            SELECT s.id, s.user_id, s.title, s.created_at, s.updated_at,
                   (SELECT COUNT(*) FROM chat_messages m WHERE m.session_id = s.id) AS mc
            FROM chat_sessions s
            WHERE s.user_id = ?
            ORDER BY s.updated_at DESC
            LIMIT ?
            """,
            (uid, limit),
        )
        return [
            ChatSessionRow(
                id=r["id"],
                user_id=r["user_id"],
                title=r["title"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
                message_count=int(r["mc"] or 0),
            )
            for r in cur.fetchall()
        ]
    finally:
        conn.close()


def get_session(session_id: str, user_id: str) -> Optional[ChatSessionRow]:
    init_chat_schema()
    uid = (user_id or "default").strip() or "default"
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT id, user_id, title, created_at, updated_at
            FROM chat_sessions WHERE id = ? AND user_id = ?
            """,
            (session_id, uid),
        ).fetchone()
        if not row:
            return None
        return ChatSessionRow(
            id=row["id"],
            user_id=row["user_id"],
            title=row["title"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
    finally:
        conn.close()


def delete_session(session_id: str, user_id: str) -> bool:
    init_chat_schema()
    uid = (user_id or "default").strip() or "default"
    conn = _connect()
    try:
        conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
        cur = conn.execute(
            "DELETE FROM chat_sessions WHERE id = ? AND user_id = ?",
            (session_id, uid),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def append_message(
    session_id: str,
    role: str,
    content: str,
    *,
    attachment_path: str = "",
    attachment_name: str = "",
    parsed_json: str = "",
) -> ChatMessageRow:
    init_chat_schema()
    now = _now_iso()
    conn = _connect()
    try:
        cur = conn.execute(
            """
            INSERT INTO chat_messages (
                session_id, role, content, created_at,
                attachment_path, attachment_name, parsed_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                role,
                content,
                now,
                attachment_path or "",
                attachment_name or "",
                parsed_json or "",
            ),
        )
        conn.execute(
            "UPDATE chat_sessions SET updated_at = ? WHERE id = ?",
            (now, session_id),
        )
        conn.commit()
        mid = int(cur.lastrowid)
    finally:
        conn.close()
    return ChatMessageRow(
        id=mid,
        session_id=session_id,
        role=role,
        content=content,
        created_at=now,
        attachment_path=attachment_path or "",
        attachment_name=attachment_name or "",
        parsed_json=parsed_json or "",
    )


def update_message_parsed_json(message_id: int, parsed_json: str) -> None:
    init_chat_schema()
    conn = _connect()
    try:
        conn.execute(
            "UPDATE chat_messages SET parsed_json = ? WHERE id = ?",
            (parsed_json, message_id),
        )
        conn.commit()
    finally:
        conn.close()


def update_message_ingested(message_id: int, *, ingested_at: str) -> None:
    init_chat_schema()
    conn = _connect()
    try:
        conn.execute(
            "UPDATE chat_messages SET ingested_at = ? WHERE id = ?",
            (ingested_at, message_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_message(message_id: int) -> Optional[ChatMessageRow]:
    init_chat_schema()
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT id, session_id, role, content, created_at,
                   attachment_path, attachment_name, parsed_json, ingested_at
            FROM chat_messages WHERE id = ?
            """,
            (message_id,),
        ).fetchone()
        if not row:
            return None
        return _row_to_message(row)
    finally:
        conn.close()


def list_messages(session_id: str, *, limit: int = 500) -> List[ChatMessageRow]:
    init_chat_schema()
    conn = _connect()
    try:
        cur = conn.execute(
            """
            SELECT id, session_id, role, content, created_at,
                   attachment_path, attachment_name, parsed_json, ingested_at
            FROM chat_messages
            WHERE session_id = ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (session_id, limit),
        )
        return [_row_to_message(r) for r in cur.fetchall()]
    finally:
        conn.close()


def maybe_set_title_from_first_message(session_id: str, user_text: str) -> None:
    text = (user_text or "").strip().replace("\n", " ")
    if not text:
        return
    title = text[:48] + ("…" if len(text) > 48 else "")
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT title FROM chat_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if row and row["title"] in ("新会话", ""):
            conn.execute(
                "UPDATE chat_sessions SET title = ? WHERE id = ?",
                (title, session_id),
            )
            conn.commit()
    finally:
        conn.close()


def search_messages_by_keywords(
    user_id: str,
    keywords: List[str],
    *,
    exclude_session_id: Optional[str] = None,
    limit: int = 8,
) -> List[ChatMessageRow]:
    if not keywords:
        return []
    init_chat_schema()
    uid = (user_id or "default").strip() or "default"
    conn = _connect()
    try:
        clauses = []
        params: list = [uid]
        for kw in keywords[:12]:
            clauses.append("m.content LIKE ?")
            params.append(f"%{kw}%")
        where_kw = " OR ".join(clauses) if clauses else "1=0"
        excl = ""
        if exclude_session_id:
            excl = " AND m.session_id != ?"
            params.append(exclude_session_id)
        params.append(limit)
        sql = f"""
            SELECT m.id, m.session_id, m.role, m.content, m.created_at
            FROM chat_messages m
            JOIN chat_sessions s ON s.id = m.session_id
            WHERE s.user_id = ? AND ({where_kw}){excl}
            ORDER BY m.id DESC
            LIMIT ?
        """
        cur = conn.execute(sql, params)
        rows = [
            ChatMessageRow(
                id=r["id"],
                session_id=r["session_id"],
                role=r["role"],
                content=r["content"],
                created_at=r["created_at"],
            )
            for r in cur.fetchall()
        ]
        return list(reversed(rows))
    finally:
        conn.close()


def parse_message_time(created_at: str) -> Optional[datetime]:
    return safe_parse_datetime(created_at)
