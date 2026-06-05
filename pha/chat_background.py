"""Persist lifestyle / supplement / medication notes from free-form chat (v2.2.0)."""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import date
from typing import List, Optional

from pha.sqlite_storage import _connect, init_schema

_BACKGROUND_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_health_background_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    note_date TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'general',
    content TEXT NOT NULL,
    session_id TEXT,
    source_message_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_user_bg_notes_user
    ON user_health_background_notes (user_id, created_at DESC);
"""

_CAPTURE_HINT_RE = re.compile(
    r"补剂|服用|吃药|用药|药物|肌酸|镁|维生素|鱼油|辅酶|褪黑素|"
    r"睡眠|晚睡|失眠|熬夜|午睡|"
    r"饮食|戒|戒烟|戒酒|"
    r"症状|疼痛|不适|过敏|"
    r"每天|每日|mg|毫克|粒|片",
    re.I,
)

_CATEGORY_RULES = (
    (re.compile(r"补剂|肌酸|镁|维生素|鱼油|辅酶|褪黑素|mg|毫克", re.I), "supplement"),
    (re.compile(r"吃药|用药|药物|片|粒|处方", re.I), "medication"),
    (re.compile(r"睡眠|晚睡|失眠|熬夜|午睡", re.I), "sleep_lifestyle"),
    (re.compile(r"症状|疼痛|不适|过敏", re.I), "symptom"),
)

PHA_BG_INJECT_MAX_SUPPLEMENT = int(os.environ.get("PHA_BG_INJECT_MAX_SUPPLEMENT", "1200"))
PHA_BG_INJECT_MAX_MEDICATION = int(os.environ.get("PHA_BG_INJECT_MAX_MEDICATION", "1200"))
PHA_BG_INJECT_MAX_OTHER = int(os.environ.get("PHA_BG_INJECT_MAX_OTHER", "600"))

_ALL_SUPPS_RE = re.compile(r"所有补剂|全部补剂|目前在服|正在服用|用药清单|所有药物", re.I)

MAX_CHAT_BACKGROUND_CHARS = int(os.environ.get("PHA_CHAT_BACKGROUND_MAX_CHARS", "4000"))


def init_background_schema(conn: Optional[sqlite3.Connection] = None) -> None:
    init_schema()
    own = conn is None
    db = conn or _connect()
    try:
        db.executescript(_BACKGROUND_SCHEMA)
        db.commit()
    finally:
        if own:
            db.close()


def _infer_category(text: str) -> str:
    for pattern, cat in _CATEGORY_RULES:
        if pattern.search(text):
            return cat
    return "general"


def should_capture_background_message(message: str) -> bool:
    """Long-term DB memo capture — schema-driven (A+); independent of lane routing."""
    from pha.universal_catalog_manager import get_catalog_manager

    return get_catalog_manager().should_capture_background(message)


def maybe_capture_chat_background(
    user_id: str,
    message: str,
    *,
    session_id: str = "",
    source_message_id: Optional[int] = None,
) -> tuple[bool, Optional[str]]:
    """Heuristically store user-reported lifestyle context for future Patient State.

    Returns ``(stored_ok, reject_reason)`` where ``reject_reason`` is e.g.
    ``\"background_too_long\"`` when content exceeds the configured cap.
    """
    text = (message or "").strip()
    if not should_capture_background_message(text):
        return False, None
    if len(text) > MAX_CHAT_BACKGROUND_CHARS:
        return False, "background_too_long"
    uid = (user_id or "default").strip() or "default"
    note_date = date.today().isoformat()
    category = _infer_category(text)
    init_background_schema()
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO user_health_background_notes (
                user_id, note_date, category, content, session_id, source_message_id
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                uid,
                note_date,
                category,
                text[:MAX_CHAT_BACKGROUND_CHARS],
                (session_id or "").strip() or None,
                source_message_id,
            ),
        )
        conn.commit()
        return True, None
    finally:
        conn.close()


def store_unstructured_vision_note(
    user_id: str,
    *,
    ocr_text: str = "",
    error: str = "",
    source_message_id: Optional[int] = None,
    session_id: str = "",
) -> bool:
    """Stage 3A fallback — never promotes to catalog menu; audit trail only."""
    body_parts = []
    if (error or "").strip():
        body_parts.append(f"[vision_parse_failed] {(error or '')[:1200]}")
    if (ocr_text or "").strip():
        body_parts.append(f"[ocr]\n{(ocr_text or '')[:MAX_CHAT_BACKGROUND_CHARS - 200]}")
    text = "\n\n".join(body_parts).strip()
    if not text:
        return False
    uid = (user_id or "default").strip() or "default"
    note_date = date.today().isoformat()
    init_background_schema()
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO user_health_background_notes (
                user_id, note_date, category, content, session_id, source_message_id
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                uid,
                note_date,
                "unstructured_vision",
                text[:MAX_CHAT_BACKGROUND_CHARS],
                (session_id or "").strip() or None,
                source_message_id,
            ),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def list_background_notes(user_id: str, *, limit: int = 20) -> List[dict]:
    uid = (user_id or "default").strip() or "default"
    init_background_schema()
    conn = _connect()
    try:
        cur = conn.execute(
            """
            SELECT id, note_date, category, content, created_at
            FROM user_health_background_notes
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (uid, max(1, limit)),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


_CATEGORY_LABELS = {
    "supplement": "补剂",
    "medication": "用药",
    "sleep_lifestyle": "睡眠/作息",
    "symptom": "症状",
    "general": "生活方式",
}


def _inject_cap(category: str, body: str) -> str:
    cat = (category or "general").strip()
    lim = PHA_BG_INJECT_MAX_OTHER
    if cat == "supplement":
        lim = PHA_BG_INJECT_MAX_SUPPLEMENT
    elif cat == "medication":
        lim = PHA_BG_INJECT_MAX_MEDICATION
    b = (body or "").strip()
    if len(b) <= lim:
        return b
    return b[: lim - 1] + "…"


def build_user_background_block(user_id: str, *, limit: int = 16, user_message: str = "") -> str:
    rows = list_background_notes(user_id, limit=limit)
    if not rows:
        return ""
    lines = [
        "【聊天背景档案 · user_health_background_notes（用户自述，非化验单）】",
        "以下为用户在对话中主动提供的补剂/用药/睡眠/症状等背景，请与化验数字区分引用。",
    ]
    buckets: dict[str, List[str]] = {k: [] for k in ("supplement", "medication", "sleep_lifestyle", "symptom", "general")}
    for r in reversed(rows):
        cat = str(r.get("category") or "general").strip()
        if cat not in buckets:
            cat = "general"
        day = str(r.get("note_date") or "")[:10]
        body = _inject_cap(cat, str(r.get("content") or ""))
        label = _CATEGORY_LABELS.get(cat, "其他")
        buckets[cat].append(f"- [{day}·{label}] {body}")

    order = ("supplement", "medication", "sleep_lifestyle", "symptom", "general")
    for key in order:
        items = buckets.get(key) or []
        if not items:
            continue
        sec = _CATEGORY_LABELS.get(key, key)
        lines.append(f"\n#### {sec}")
        lines.extend(items)

    if _ALL_SUPPS_RE.search(user_message or ""):
        lines.append(
            "\n【背景档案审计】用户询问了「所有补剂/用药」类问题：请先逐条列出上文中已出现的补剂/用药条目；"
            "若用户实际服用的品种多于上文，请明确追问并引导其在对话中补充录入。",
        )
    return "\n".join(lines)


def summarize_supplement_bg_for_tier0(raw: str, *, max_chars: int = 800) -> str:
    """Condensed supplement background for Tier0 (v2.2.6.1); full text stays in Raw User / Tier1."""
    text = (raw or "").strip()
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    lines = text.split("\n")
    out: List[str] = []
    header_done = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("【聊天背景档案") or stripped.startswith("以下为用户"):
            out.append(stripped)
            header_done = True
            continue
        if stripped.startswith("####"):
            out.append(stripped)
            continue
        if stripped.startswith("- ["):
            out.append(stripped)
            continue
        if any(k in stripped for k in ("上午", "中午", "晚上", "睡前", "他汀", "非布司他")):
            out.append(stripped)
    if not out:
        out = lines[:12]
    body = "\n".join(out).strip()
    if len(body) > max_chars:
        body = body[: max_chars - 24] + "\n…（补剂 Tier0 摘要已截断）"
    note = (
        "【Tier0 补剂摘要 · 完整时间表见用户本轮原话或下方背景档案全文】"
        if header_done
        else "【Tier0 补剂摘要】"
    )
    return f"{note}\n{body}".strip()
