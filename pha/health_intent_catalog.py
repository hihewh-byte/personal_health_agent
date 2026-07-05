"""Declarative health intent catalog loader (Stage 3C-α / 3C-γ)."""

from __future__ import annotations

import functools
import json
import os
import re
from pathlib import Path
from typing import Any

from pha.catalog_dch import token_in_message
from pha.temporal_router import extract_years_regex

_CATALOG_PATH = Path(__file__).resolve().parent.parent / "rules" / "health_intent_catalog.json"

_WEAK_CLOSE_RE = re.compile(
    r"^(谢谢|感谢|好的|知道了|收到|嗯|ok)[\s!.？?]*$",
    re.I,
)

_ATTACHMENT_PROFILES = frozenset({"attachment_asset_qa", "attachment_episodic_bridge"})
_WEARABLE_LAB_PROFILES = frozenset({"wearable_only", "lab_cross_year", "combined_review"})


def health_intent_catalog_enabled() -> bool:
    return (os.environ.get("PHA_HEALTH_INTENT_CATALOG") or "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )


@functools.lru_cache(maxsize=1)
def load_health_intent_catalog() -> dict[str, Any]:
    with _CATALOG_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def catalog_anaphora_tokens() -> list[str]:
    return list((load_health_intent_catalog().get("anaphora") or {}).get("tokens") or [])


def catalog_multi_scope_lab_tokens() -> list[str]:
    return list((load_health_intent_catalog().get("multi_scope_lab") or {}).get("tokens") or [])


def catalog_lab_markers() -> list[str]:
    return list(load_health_intent_catalog().get("lab_markers") or [])


def catalog_topic_markers(profile: str) -> list[str]:
    topics = load_health_intent_catalog().get("topic_markers") or {}
    return list(topics.get(profile) or [])


def catalog_metric_aliases(metric_key: str) -> list[str]:
    aliases = (load_health_intent_catalog().get("metric_aliases") or {}).get(metric_key) or []
    return [str(a) for a in aliases]


def catalog_all_metric_keys() -> list[str]:
    return list((load_health_intent_catalog().get("metric_aliases") or {}).keys())


def profile_episodic_continue(profile: str) -> bool:
    profiles = load_health_intent_catalog().get("profiles") or {}
    entry = profiles.get(profile) or {}
    return bool(entry.get("episodic_continue"))


def profile_recall_forbidden(profile: str) -> bool:
    profiles = load_health_intent_catalog().get("profiles") or {}
    entry = profiles.get(profile) or {}
    return bool(entry.get("recall_forbidden"))


def profile_allows_active_recall_ledger(profile: str) -> bool:
    """Active recall ledger sync/inject only on attachment or screenshot-review lanes."""
    profiles = load_health_intent_catalog().get("profiles") or {}
    entry = profiles.get((profile or "").strip()) or {}
    return bool(entry.get("recall_ledger_allowed"))


def matches_anaphora(message: str) -> bool:
    msg = (message or "").strip()
    if not msg:
        return False
    for tok in catalog_anaphora_tokens():
        if token_in_message(tok, msg):
            return True
    return False


def matches_multi_scope_lab(message: str) -> bool:
    msg = (message or "").strip()
    if not msg:
        return False
    for tok in catalog_multi_scope_lab_tokens():
        if token_in_message(tok, msg):
            return True
    return False


def infer_metrics_from_message(message: str) -> list[str]:
    msg = (message or "").strip()
    if not msg:
        return []
    found: list[str] = []
    for key in catalog_all_metric_keys():
        for alias in catalog_metric_aliases(key):
            if token_in_message(alias, msg, case_insensitive=True):
                if key not in found:
                    found.append(key)
                break
    return found


def infer_profile_hint(message: str) -> str | None:
    msg = (message or "").strip()
    if not msg:
        return None
    best_profile: str | None = None
    best_score = 0.0
    topics = (load_health_intent_catalog().get("topic_markers") or {}).items()
    for profile, markers in topics:
        score = 0.0
        for tok in markers:
            if token_in_message(str(tok), msg, case_insensitive=True):
                score += 1.0
        if score > best_score:
            best_score = score
            best_profile = str(profile)
    return best_profile if best_score > 0 else None


def message_has_lab_marker(message: str) -> bool:
    msg = (message or "").strip()
    if not msg:
        return False
    for tok in catalog_lab_markers():
        if token_in_message(tok, msg, case_insensitive=True):
            return True
    return False


def extract_health_keywords(message: str) -> list[str]:
    """Lightweight keyword bag for topic-continue overlap (no LLM)."""
    keys = infer_metrics_from_message(message)
    hint = infer_profile_hint(message)
    if hint:
        keys.append(hint)
    for tok in catalog_lab_markers():
        if token_in_message(tok, message, case_insensitive=True) and tok not in keys:
            keys.append(tok)
    return keys


def catalog_weak_followup_max_chars() -> int:
    block = load_health_intent_catalog().get("weak_followup") or {}
    return int(block.get("max_chars") or 24)


def catalog_weak_close_tokens() -> list[str]:
    block = load_health_intent_catalog().get("weak_followup") or {}
    return [str(t) for t in (block.get("close_tokens") or [])]


def catalog_advisory_followup_tokens() -> list[str]:
    block = load_health_intent_catalog().get("advisory_followup") or {}
    return [str(t) for t in (block.get("tokens") or [])]


def is_weak_close_followup(message: str) -> bool:
    """Catalog close tokens only (谢谢/好的等) — not advisory weak follow-ups."""
    msg = (message or "").strip()
    if not msg:
        return False
    if _WEAK_CLOSE_RE.match(msg):
        return True
    for tok in catalog_weak_close_tokens():
        if msg == tok or msg.startswith(tok):
            return True
    return False


def is_advisory_episodic_followup(message: str) -> bool:
    """Short advisory follow-up within weak_followup.max_chars (catalog tokens)."""
    msg = (message or "").strip()
    if not msg or len(msg) > catalog_weak_followup_max_chars():
        return False
    for tok in catalog_advisory_followup_tokens():
        if token_in_message(tok, msg, case_insensitive=True):
            return True
    return False

def catalog_episodic_delta_tokens() -> list[str]:
    block = load_health_intent_catalog().get("episodic_delta_followup") or {}
    return [str(t) for t in (block.get("tokens") or [])]


def is_episodic_delta_followup_message(message: str) -> bool:
    """Catalog episodic delta prompts — must not be classified as weak follow-up."""
    msg = (message or "").strip()
    if not msg:
        return False
    for tok in catalog_episodic_delta_tokens():
        if token_in_message(tok, msg, case_insensitive=True):
            return True
    return False


def catalog_supplement_families() -> frozenset[str]:
    fams = load_health_intent_catalog().get("supplement_families") or ["supplement", "supplement_label"]
    return frozenset(str(f).strip().lower() for f in fams if str(f).strip())


def is_supplement_document_family(document_family: str) -> bool:
    fam = (document_family or "").strip().lower()
    return fam in catalog_supplement_families() or fam == "supplement"


def is_weak_episodic_followup(message: str) -> bool:
    msg = (message or "").strip()
    if not msg:
        return False
    if is_episodic_delta_followup_message(msg):
        return False
    if _WEAK_CLOSE_RE.match(msg):
        return True
    for tok in catalog_weak_close_tokens():
        if msg == tok or msg.startswith(tok):
            return True
    if len(msg) <= catalog_weak_followup_max_chars() and matches_anaphora(msg):
        return True
    if len(msg) <= catalog_weak_followup_max_chars() and not infer_metrics_from_message(msg):
        if not infer_profile_hint(msg) or infer_profile_hint(msg) in _ATTACHMENT_PROFILES:
            return True
    return False


def catalog_lab_record_request_tokens() -> list[str]:
    block = load_health_intent_catalog().get("lab_record_request") or {}
    return [str(t) for t in (block.get("tokens") or [])]


def catalog_session_anchor_label(profile: str) -> str:
    labels = load_health_intent_catalog().get("session_anchor_labels") or {}
    fp = (profile or "").strip()
    return str(labels.get(fp) or "当前会话话题")


def session_anchor_profiles() -> frozenset[str]:
    profiles = load_health_intent_catalog().get("profiles") or {}
    out = {str(k) for k, v in profiles.items() if v.get("episodic_continue")}
    out.add("wearable_screenshot_review")
    return frozenset(out)


def catalog_scope_disambiguation_tokens() -> tuple[list[str], list[str]]:
    block = load_health_intent_catalog().get("scope_disambiguation") or {}
    session = [str(t) for t in (block.get("session_tokens") or [])]
    archive = [str(t) for t in (block.get("archive_tokens") or [])]
    return session, archive


def message_explicitly_requests_scope_choice(message: str) -> bool:
    """User names both session context and archived records — prefer clarify chips."""
    msg = (message or "").strip()
    if len(msg) <= catalog_weak_followup_max_chars():
        return False
    session_toks, archive_toks = catalog_scope_disambiguation_tokens()
    has_session = any(token_in_message(tok, msg, case_insensitive=True) for tok in session_toks)
    has_archive = any(token_in_message(tok, msg, case_insensitive=True) for tok in archive_toks)
    return has_session and has_archive and message_has_lab_marker(msg)


def explicit_lab_record_request(message: str) -> bool:
    """User explicitly asks for stored lab records (years/report), not a vague topic word."""
    msg = (message or "").strip()
    if not msg:
        return False
    if extract_years_regex(msg):
        return True
    if matches_multi_scope_lab(msg):
        return True
    for tok in catalog_lab_record_request_tokens():
        if token_in_message(tok, msg, case_insensitive=True):
            return True
    return False


def is_session_anchor_profile(profile: str) -> bool:
    return (profile or "").strip() in session_anchor_profiles()


def explicit_profile_shift(message: str, focus_profile: str) -> bool:
    """True when user explicitly pivots away from episodic focus profile."""
    hint = infer_profile_hint(message)
    if not hint or not focus_profile:
        return False
    fp = focus_profile.strip()
    if fp in _ATTACHMENT_PROFILES and hint in _WEARABLE_LAB_PROFILES:
        return bool(infer_metrics_from_message(message) or message_has_lab_marker(message))
    if fp in _WEARABLE_LAB_PROFILES and hint in _ATTACHMENT_PROFILES:
        return bool(re.search(r"是什么|标签|补剂|成分|附件|图片", message or "", re.I))
    if fp == "wearable_screenshot_review":
        return explicit_lab_record_request(message) or matches_multi_scope_lab(message)
    if hint != fp and infer_metrics_from_message(message):
        if message_has_lab_marker(message) and is_session_anchor_profile(fp):
            return explicit_lab_record_request(message)
        return True
    return False


def resolve_inherited_focus_profile(
    message: str,
    *,
    focus_profile: str | None,
    profile_hint: str | None = None,
) -> str | None:
    """Catalog episodic inheritance: weak follow-up keeps prior profile unless explicit shift."""
    fp = (focus_profile or "").strip()
    if not fp or not profile_episodic_continue(fp):
        return None
    if explicit_profile_shift(message, fp):
        return profile_hint or infer_profile_hint(message)
    if is_weak_episodic_followup(message) or matches_anaphora(message):
        return fp
    hint = profile_hint or infer_profile_hint(message)
    if hint and hint != fp and not explicit_profile_shift(message, fp):
        if infer_metrics_from_message(message) or message_has_lab_marker(message):
            return hint
    if hint == fp:
        return fp
    if len((message or "").strip()) <= catalog_weak_followup_max_chars():
        return fp
    return None


def should_prefer_attachment_qa_over_wearable(
    *,
    document_family: str,
    user_message: str,
    has_parsed_attachment: bool,
) -> bool:
    """R1 supplement labels must not lose to wearable_screenshot_review (3C-γ)."""
    if not has_parsed_attachment:
        return False
    if not is_supplement_document_family(document_family):
        return False
    from pha.attachment_asset_qa import is_attachment_asset_qa_turn

    if is_attachment_asset_qa_turn(user_message, has_parsed_attachment=True):
        return True
    if infer_profile_hint(user_message) in _ATTACHMENT_PROFILES:
        return True
    return bool(re.search(r"补剂|标签|成分|是什么|有什么帮助", user_message or "", re.I))


def catalog_goal_markers() -> dict[str, Any]:
    return dict(load_health_intent_catalog().get("goal_markers") or {})


def catalog_holistic_proxy_metrics() -> list[str]:
    return [str(m) for m in (load_health_intent_catalog().get("holistic_proxy_metrics") or [])]


def catalog_clarify_kind(kind: str) -> dict[str, Any]:
    kinds = load_health_intent_catalog().get("clarify_kinds") or {}
    entry = kinds.get(kind) or {}
    return dict(entry) if isinstance(entry, dict) else {}


def message_matches_goal_class(message: str, goal_class: str) -> bool:
    msg = (message or "").strip()
    if not msg:
        return False
    markers = (catalog_goal_markers().get(goal_class) or {}).get("tokens") or []
    for tok in markers:
        if token_in_message(str(tok), msg, case_insensitive=True):
            return True
    return False
