"""Stage 3C-β — health episodic focus persistence + bridge blocks."""

from __future__ import annotations

import json
import os
import re
from datetime import date
from typing import Any

from pha.health_episodic_focus import HealthSessionFocus, WearableWindow
from pha.health_intent_catalog import extract_health_keywords, infer_metrics_from_message, matches_anaphora
from pha.goal_classifier import goal_session_anchor_enabled
from pha.health_turn_resolver import HealthTurnScope
from pha.session_turn_focus import (
    SessionTurnFocus,
    consume_session_turn_focus,
    get_session_turn_focus,
    save_session_turn_focus,
)


def episodic_all_profiles_enabled() -> bool:
    return (os.environ.get("PHA_EPISODIC_ALL_PROFILES") or "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def health_episodic_runtime_enabled() -> bool:
    return episodic_all_profiles_enabled() or (
        (os.environ.get("PHA_HEALTH_TURN_RESOLVER") or "0").strip().lower()
        in ("1", "true", "yes")
    )


def _general_focus_ttl_turns() -> int:
    try:
        return max(1, int(os.environ.get("PHA_HEALTH_FOCUS_TTL_TURNS", "8")))
    except ValueError:
        return 8


def _ttl_for_profile(profile: str) -> int:
    if profile in ("attachment_asset_qa", "attachment_episodic_bridge"):
        from pha.session_turn_focus import _focus_ttl_turns

        return _focus_ttl_turns()
    return _general_focus_ttl_turns()


def summarize_assistant_digest(reply: str, *, max_len: int = 320) -> str:
    text = re.sub(r"\s+", " ", (reply or "").strip())
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def available_lab_years_for_user(user_id: str) -> list[int]:
    from pha.medical_storage import list_distinct_report_dates

    uid = (user_id or "default").strip() or "default"
    report_days = list_distinct_report_dates(uid, limit=16)
    return sorted({d.year for d in report_days})


def session_focus_to_health(focus: SessionTurnFocus | None) -> HealthSessionFocus | None:
    if focus is None:
        return None
    window = None
    if focus.focus_wearable_start and focus.focus_wearable_end:
        try:
            window = WearableWindow(
                start=date.fromisoformat(focus.focus_wearable_start),
                end=date.fromisoformat(focus.focus_wearable_end),
            )
        except ValueError:
            window = None
    profile = focus.focus_profile or ""
    if not profile and (focus.focus_summary or "").strip():
        profile = "attachment_asset_qa"
    return HealthSessionFocus(
        session_id=focus.session_id,
        focus_profile=profile,
        focus_metric=focus.focus_metric or "",
        focus_lab_years=list(focus.focus_lab_years or []),
        focus_wearable_window=window,
        focus_summary=focus.focus_summary or "",
        focus_tokens=list(focus.focus_tokens or []),
        turns_remaining=int(focus.turns_remaining or 0),
        last_user_message=focus.last_user_message or "",
        last_assistant_digest=focus.last_assistant_digest or "",
        focus_goal=focus.focus_goal or "",
        focus_domains=list(focus.focus_domains or []),
    )


def load_health_session_focus(session_id: str) -> HealthSessionFocus | None:
    return session_focus_to_health(get_session_turn_focus(session_id))


def save_health_session_focus(
    session_id: str,
    focus: HealthSessionFocus,
    *,
    document_type: str = "",
    turns_remaining: int | None = None,
) -> None:
    ttl = turns_remaining if turns_remaining is not None else _ttl_for_profile(focus.focus_profile)
    w_start = ""
    w_end = ""
    if focus.focus_wearable_window is not None:
        w_start = focus.focus_wearable_window.start.isoformat()
        w_end = focus.focus_wearable_window.end.isoformat()
    save_session_turn_focus(
        session_id,
        focus_summary=focus.focus_summary,
        document_type=document_type or focus.focus_profile or "health",
        focus_tokens=focus.focus_tokens,
        turns_remaining=ttl,
        focus_profile=focus.focus_profile,
        focus_metric=focus.focus_metric,
        focus_lab_years=focus.focus_lab_years,
        focus_wearable_start=w_start,
        focus_wearable_end=w_end,
        last_user_message=focus.last_user_message,
        last_assistant_digest=focus.last_assistant_digest,
        focus_goal=focus.focus_goal,
        focus_domains=list(focus.focus_domains or []),
    )


def _topic_continues(message: str, focus: HealthSessionFocus) -> bool:
    msg = (message or "").strip()
    if not msg:
        return False
    if matches_anaphora(msg):
        return True
    digest = (focus.last_assistant_digest or "").strip()
    if digest:
        overlap = set(extract_health_keywords(msg)) & set(extract_health_keywords(digest))
        if overlap:
            return True
    return False


def revive_health_session_focus(session_id: str, user_message: str) -> HealthSessionFocus | None:
    focus = load_health_session_focus(session_id)
    if focus is None:
        return None
    if focus.active:
        return focus
    if not _topic_continues(user_message, focus):
        from pha.attachment_asset_qa import user_hits_focus_tokens

        if not user_hits_focus_tokens(user_message, focus.focus_tokens):
            return None
    save_health_session_focus(session_id, focus, turns_remaining=_ttl_for_profile(focus.focus_profile))
    return load_health_session_focus(session_id)


def health_episodic_bridge_block(focus: HealthSessionFocus | SessionTurnFocus | None) -> str:
    if focus is None:
        return ""
    if isinstance(focus, SessionTurnFocus):
        focus = session_focus_to_health(focus)
    if focus is None:
        return ""
    if not (focus.last_user_message or focus.last_assistant_digest):
        return ""
    lines = ["【上轮对话摘要 · EPISODIC_BRIDGE】"]
    if focus.focus_metric:
        lines.append(f"- 关注指标: {focus.focus_metric.upper()}")
    if focus.focus_lab_years:
        lines.append(f"- 化验年度: {', '.join(str(y) for y in focus.focus_lab_years)}")
    if focus.focus_wearable_window is not None:
        w = focus.focus_wearable_window
        lines.append(f"- 时间窗: {w.start.isoformat()}～{w.end.isoformat()}")
    if focus.focus_profile:
        lines.append(f"- 主题 profile: {focus.focus_profile}")
    if focus.focus_goal:
        lines.append(f"- 合成目标: {focus.focus_goal}")
    if focus.focus_domains:
        lines.append(f"- 数据域: {', '.join(focus.focus_domains)}")
    if focus.last_user_message:
        lines.append(
            f"- 用户：{summarize_assistant_digest(focus.last_user_message, max_len=200)}",
        )
    if focus.last_assistant_digest:
        lines.append(f"- 助手：{focus.last_assistant_digest}")
    if focus.turns_remaining > 0:
        lines.append(f"- 续焦剩余: {focus.turns_remaining} 轮")
    return "\n".join(lines)


def record_health_turn_focus(
    session_id: str,
    *,
    turn_scope: HealthTurnScope,
    harness_profile: str,
    user_message: str,
    assistant_reply: str,
    focus_summary: str = "",
    document_type: str = "",
    skip_consume: bool = False,
    arbiter_reason: str = "",
    existence_probe: dict[str, bool] | None = None,
) -> None:
    sid = (session_id or "").strip()
    if not sid or turn_scope.needs_clarification:
        return
    profile = harness_profile or turn_scope.focus_profile or turn_scope.profile_hint or ""
    if not profile:
        return
    if not skip_consume:
        consume_session_turn_focus(sid)
    metric = turn_scope.primary_metric()
    summary = (focus_summary or turn_scope.profile_hint or user_message or "")[:4000]
    focus_goal = ""
    focus_domains: list[str] = []
    prior = load_health_session_focus(sid)
    explicit_metrics = infer_metrics_from_message(user_message)
    if explicit_metrics and goal_session_anchor_enabled():
        focus_goal = ""
        focus_domains = []
    elif harness_profile == "combined_review" and arbiter_reason in (
        "goal_holistic_upgrade",
        "episodic_goal_continue",
    ):
        focus_goal = "holistic_assessment"
        probe = existence_probe or {}
        if probe.get("lab"):
            focus_domains.append("lab")
        if probe.get("wearable"):
            focus_domains.append("wearable")
        if not focus_domains:
            focus_domains = ["lab", "wearable"]
    elif prior and goal_session_anchor_enabled():
        focus_goal = prior.focus_goal
        focus_domains = list(prior.focus_domains or [])
    focus = HealthSessionFocus(
        session_id=sid,
        focus_profile=profile,
        focus_metric=metric,
        focus_lab_years=list(turn_scope.lab_years),
        focus_wearable_window=turn_scope.wearable_window,
        focus_summary=summary,
        focus_tokens=extract_health_keywords(user_message)[:32],
        turns_remaining=_ttl_for_profile(profile),
        last_user_message=(user_message or "")[:2000],
        last_assistant_digest=summarize_assistant_digest(assistant_reply),
        focus_goal=focus_goal,
        focus_domains=focus_domains,
    )
    save_health_session_focus(
        sid,
        focus,
        document_type=document_type,
        turns_remaining=_ttl_for_profile(profile),
    )


def episodic_report_meta(
    *,
    turn_scope: HealthTurnScope | None,
    bridge_injected: bool,
    recall_focus_injected: bool,
    focus_goal: str = "",
    focus_domains: list[str] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "episodic": {
            "bridgeInjected": bool(bridge_injected),
            "recallFocusInjected": bool(recall_focus_injected),
            "episodicAllProfiles": episodic_all_profiles_enabled(),
        },
    }
    if focus_goal:
        out["episodic"]["focusGoal"] = focus_goal
    if focus_domains:
        out["episodic"]["focusDomains"] = list(focus_domains)
    if turn_scope is not None:
        out["turnScope"] = turn_scope.to_report_dict()
    return out


__all__ = [
    "available_lab_years_for_user",
    "episodic_all_profiles_enabled",
    "episodic_report_meta",
    "health_episodic_bridge_block",
    "health_episodic_runtime_enabled",
    "load_health_session_focus",
    "record_health_turn_focus",
    "revive_health_session_focus",
    "save_health_session_focus",
    "session_focus_to_health",
    "summarize_assistant_digest",
]
