"""Response Language Policy (RLP) — resolve reply locale and inject system directive."""

from __future__ import annotations

import os
import re
from typing import Optional

_SUPPORTED = frozenset({"en", "zh"})

_EXPLICIT_ZH_RE = re.compile(
    r"(?:^|\b)(?:reply|respond|answer|write)\s+(?:in\s+)?(?:chinese|mandarin|简体|繁体)\b|"
    r"\buse\s+(?:chinese|mandarin)\b|"
    r"请用中文|用中文回答|中文回复|简体中文|"
    r"后面都用中文|之后都用中文|都用中文|改用中文|切换到中文|用中文说",
    re.I,
)
_EXPLICIT_EN_RE = re.compile(
    r"(?:^|\b)(?:reply|respond|answer|write)\s+(?:in\s+)?english\b|"
    r"\buse\s+english\b|"
    r"请用英文|用英文回答|英文回复|英语回答|"
    r"后面都用英文|之后都用英文|都用英文|改用英文|切换到英文",
    re.I,
)
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def default_response_locale() -> str:
    """OSS default ``en``; override via PHA_RESPONSE_LOCALE or PHA_UI_LANG."""
    raw = (os.environ.get("PHA_RESPONSE_LOCALE") or os.environ.get("PHA_UI_LANG") or "en").strip().lower()
    return "zh" if raw.startswith("zh") else "en"


def normalize_response_locale(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    raw = str(value).strip().lower()
    if not raw:
        return None
    if raw.startswith("zh"):
        return "zh"
    if raw.startswith("en"):
        return "en"
    return None


def detect_explicit_locale_request(user_message: str) -> Optional[str]:
    text = (user_message or "").strip()
    if not text:
        return None
    if _EXPLICIT_ZH_RE.search(text):
        return "zh"
    if _EXPLICIT_EN_RE.search(text):
        return "en"
    return None


_HEALTH_CONTENT_RE = re.compile(
    r"睡眠|步数|心率|hrv|血脂|胆固醇|ldl|化验|体检|血氧|spo2|呼吸|血糖|"
    r"sleep|steps?|heart|oxygen|lab|lipid|glucose|warehouse|截图|附件",
    re.I,
)


def is_locale_preference_only(user_message: str) -> bool:
    """True when the user only asks to switch reply language (no health ask)."""
    text = (user_message or "").strip()
    if not text or len(text) > 48:
        return False
    if detect_explicit_locale_request(text) is None:
        return False
    return not bool(_HEALTH_CONTENT_RE.search(text))


def detect_message_locale_heuristic(user_message: str, *, min_chars: int = 4) -> Optional[str]:
    """CJK vs Latin ratio on meaningful user text (no API locale).

    Short pure-CJK acks (谢谢 / 好的) must resolve to ``zh`` — otherwise the OSS
    default ``en`` incorrectly answers Chinese close tokens. Short Latin acks
    (hi / ok) intentionally fall through to env/default so PHA_RESPONSE_LOCALE
    can still steer them.
    """
    text = (user_message or "").strip()
    if not text:
        return None
    cjk = len(_CJK_RE.findall(text))
    latin = len(_LATIN_RE.findall(text))
    total = cjk + latin
    if total == 0:
        return None
    if len(text) < min_chars or total < min_chars:
        if cjk and not latin:
            return "zh"
        return None
    if cjk > latin:
        return "zh"
    if latin > cjk:
        return "en"
    if cjk > 0:
        return "zh"
    if latin > 0:
        return "en"
    return None


def resolve_response_locale(
    user_message: str,
    *,
    request_locale: Optional[str] = None,
) -> str:
    """
    Priority: explicit user instruction > API ``response_locale`` >
    message heuristic > env default (``en`` for OSS).
    """
    explicit = detect_explicit_locale_request(user_message)
    if explicit in _SUPPORTED:
        return explicit

    req = normalize_response_locale(request_locale)
    if req in _SUPPORTED:
        return req

    heuristic = detect_message_locale_heuristic(user_message)
    if heuristic in _SUPPORTED:
        return heuristic

    return default_response_locale()


def build_language_directive(locale: str) -> str:
    loc = normalize_response_locale(locale) or "en"
    if loc == "zh":
        return """【RESPONSE LANGUAGE · Tier0-adjacent advisory】
- 本轮用户可见回复必须使用**简体中文**，语气自然、专业，像资深健康顾问对话。
- 医学名词与生化指标采用「中文名 (英文缩写/Canonical Code)」格式。
- 禁止在答复中出现 Harness 内部用语（Tier0、Manifest、账本、定账、数仓、metric_id、verdict 等）。"""
    return """【RESPONSE LANGUAGE · Tier0-adjacent advisory】
- Reply to the user in **English** with natural, professional clinical prose.
- For medical terms and biomarkers, use "English term (canonical code)" when a code exists in evidence.
- Do not expose harness internals (Tier0, Manifest, ledger, metric_id, verdict, SSO, etc.) in user-visible text."""


def append_language_directive(system_content: str, locale: str) -> str:
    base = (system_content or "").strip()
    directive = build_language_directive(locale).strip()
    if not base:
        return directive
    if directive in base:
        return base
    return f"{base}\n\n{directive}"


__all__ = [
    "append_language_directive",
    "build_language_directive",
    "default_response_locale",
    "detect_explicit_locale_request",
    "detect_message_locale_heuristic",
    "is_locale_preference_only",
    "normalize_response_locale",
    "resolve_response_locale",
]
