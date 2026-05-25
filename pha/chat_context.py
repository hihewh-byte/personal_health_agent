"""Semantic keyword recall for PHA chat context windows."""

from __future__ import annotations

import re
from typing import List, Tuple

from pha.chat_storage import ChatMessageRow, list_messages, search_messages_by_keywords

HEALTH_KEYWORD_LEXICON: tuple[str, ...] = (
    "睡眠",
    "深睡",
    "rem",
    "清醒",
    "waso",
    "hrv",
    "心率",
    "静息",
    "步数",
    "运动",
    "转氨酶",
    "alt",
    "ast",
    "肌酸",
    "血脂",
    "胆固醇",
    "ldl",
    "hdl",
    "血糖",
    "crp",
    "炎症",
    "体检",
    "化验",
    "审计",
    "报告",
    "可穿戴",
    "apple",
    "watch",
    "疲劳",
    "恢复",
    "镁",
    "补剂",
)


def extract_health_keywords(text: str) -> List[str]:
    raw = (text or "").lower()
    found: List[str] = []
    for kw in HEALTH_KEYWORD_LEXICON:
        if kw.lower() in raw or kw in (text or ""):
            found.append(kw)
    # short latin tokens
    for m in re.findall(r"\b[a-z]{2,6}\b", raw):
        if m in ("hrv", "rem", "alt", "ast", "ldl", "hdl", "crp", "waso"):
            if m not in found:
                found.append(m)
    return found[:16]


def recent_turns(messages: List[ChatMessageRow], *, max_turns: int = 8) -> List[ChatMessageRow]:
    """Last N user/assistant pairs from current session."""
    if not messages:
        return []
    pairs: List[ChatMessageRow] = []
    buf: List[ChatMessageRow] = []
    for msg in messages:
        buf.append(msg)
    # walk backwards collecting up to max_turns*2 messages
    collected: List[ChatMessageRow] = []
    turn = 0
    i = len(buf) - 1
    while i >= 0 and turn < max_turns:
        collected.insert(0, buf[i])
        if buf[i].role == "user":
            turn += 1
        i -= 1
    return collected


def _is_cross_year_ldl_compare(user_message: str) -> bool:
    from pha.intent_gates import should_suppress_assistant_history

    return should_suppress_assistant_history(user_message)


def build_chat_context_block(
    user_id: str,
    session_id: str,
    user_message: str,
    *,
    extra_system_context: str = "",
    suppress_stale_assistant_recall: bool = False,
) -> Tuple[str, List[ChatMessageRow]]:
    """
    Compose dynamic context: recent 3 turns + keyword-recalled history snippets.
    Returns (context_block_for_user_message_augmentation, recalled_rows).
    """
    all_msgs = list_messages(session_id)
    recent = recent_turns(all_msgs, max_turns=8)
    keywords = extract_health_keywords(user_message)
    recalled: List[ChatMessageRow] = []
    if suppress_stale_assistant_recall or _is_cross_year_ldl_compare(user_message):
        recent = [m for m in recent if m.role == "user"]
    else:
        recalled = search_messages_by_keywords(
            user_id,
            keywords,
            exclude_session_id=session_id,
            limit=6,
        )

    parts: List[str] = []
    if extra_system_context.strip():
        parts.append(extra_system_context.strip())

    if recent:
        parts.append("【当前会话 · 最近对话】")
        for m in recent:
            role = "用户" if m.role == "user" else "助手"
            excerpt = m.content.strip()
            if len(excerpt) > 600:
                excerpt = excerpt[:600] + "…"
            parts.append(f"{role}: {excerpt}")

    if recalled:
        parts.append("【历史相关片段 · 语义召回】")
        for m in recalled:
            role = "用户" if m.role == "user" else "助手"
            excerpt = m.content.strip()
            if len(excerpt) > 450:
                excerpt = excerpt[:450] + "…"
            parts.append(f"({m.created_at[:10]}) {role}: {excerpt}")

    block = "\n".join(parts).strip()
    return block, recalled
