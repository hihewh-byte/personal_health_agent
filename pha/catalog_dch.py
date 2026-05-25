"""DCH — Dynamic Catalog Hint: schema trigger scan (zero LLM, C-layer substring)."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

_DEFAULT_CORE_HINTS = ("HRV", "活动消耗", "睡眠")
_DEFAULT_CORE_METRICS = ("hrv", "activity_kcal", "sleep")


def token_in_message(token: str, user_message: str, *, case_insensitive: bool = True) -> bool:
    t = (token or "").strip()
    msg = user_message or ""
    if not t or not msg:
        return False
    if case_insensitive and t.isascii():
        return t.lower() in msg.lower()
    return t in msg


def scan_trigger_keywords(
    user_message: str,
    catalog: Dict[str, Any],
) -> Tuple[List[str], List[str]]:
    """
  Match ``catalog.trigger_keywords`` against user text.

  Returns ``(zh_hints, metric_ids)`` preserving first-hit order.
  """
    hints: List[str] = []
    metric_ids: List[str] = []
    seen_h: set[str] = set()
    seen_m: set[str] = set()

    for rule in catalog.get("trigger_keywords") or []:
        if not isinstance(rule, dict):
            continue
        token = str(rule.get("token") or "").strip()
        if not token:
            continue
        ci = bool(rule.get("match_case_insensitive", True))
        if not token_in_message(token, user_message, case_insensitive=ci):
            continue
        zh = str(rule.get("zh") or token).strip()
        mid = str(rule.get("metric_id") or "").strip()
        if zh and zh not in seen_h:
            seen_h.add(zh)
            hints.append(zh)
        if mid and mid not in seen_m:
            seen_m.add(mid)
            metric_ids.append(mid)

    return hints, metric_ids


def build_dynamic_when_zh(
    user_message: str,
    catalog: Dict[str, Any],
    *,
    static_when_zh: str = "",
) -> str:
    """Catalog ``when`` column: dynamic hints + optional static fallback."""
    matched, _ = scan_trigger_keywords(user_message, catalog)
    max_n = int(catalog.get("max_matched_keywords_in_catalog") or 4)
    if matched:
        hints = matched[:max_n]
    else:
        core: List[str] = []
        for item in catalog.get("core_hint_keywords") or []:
            if isinstance(item, dict):
                zh = str(item.get("zh") or "").strip()
            else:
                zh = str(item).strip()
            if zh and zh not in core:
                core.append(zh)
        hints = (core or list(_DEFAULT_CORE_HINTS))[:max_n]
    prefix = (static_when_zh or "").strip()
    dynamic = f"本轮命中：{', '.join(hints)}"
    if prefix:
        return f"{prefix}；{dynamic}"
    return dynamic


def infer_wearable_metrics_from_schema(
    user_message: str,
    schema: Dict[str, Any],
    *,
    default_if_wearable_query: bool,
    has_lab_only: bool,
) -> List[str]:
    """
  Schema-driven metric list for Reduce (replaces hard-coded metric ifs).
  """
    catalog = schema.get("catalog") or {}
    metrics_block = schema.get("metrics") or {}
    canonical: List[str] = list(metrics_block.get("canonical") or [])
    core: List[str] = list(metrics_block.get("core") or list(_DEFAULT_CORE_METRICS))

    _, matched_ids = scan_trigger_keywords(user_message, catalog)
    if matched_ids:
        ordered = [m for m in canonical if m in matched_ids]
        for m in matched_ids:
            if m not in ordered:
                ordered.append(m)
        return ordered

    if default_if_wearable_query and not has_lab_only:
        return list(core)
    return []


__all__ = [
    "build_dynamic_when_zh",
    "infer_wearable_metrics_from_schema",
    "scan_trigger_keywords",
    "token_in_message",
]
