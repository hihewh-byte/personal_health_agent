"""Metadata Catalog (MC) — Stage 2C: compressed read-only asset index (Tier1 default)."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from pha.catalog_dch import token_in_message
from pha.schema_intent_router import score_asset_positive

_CHARS_PER_TOKEN = 2.5

_STATIC_ROWS_CACHE: Dict[str, Any] = {"key": None, "rows": []}


def metadata_catalog_enabled() -> bool:
    return os.environ.get("PHA_METADATA_CATALOG", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def metadata_catalog_force_tier0() -> bool:
    return os.environ.get("PHA_METADATA_CATALOG_FORCE_TIER0", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def metadata_catalog_max_tokens() -> int:
    try:
        return max(80, int(os.environ.get("PHA_METADATA_CATALOG_MAX_TOKENS", "400")))
    except ValueError:
        return 400


def metadata_catalog_profiles() -> List[str]:
    raw = os.environ.get("PHA_METADATA_CATALOG_PROFILES", "combined_review").strip()
    return [p.strip() for p in raw.split(",") if p.strip()] or ["combined_review"]


def should_inject_metadata_catalog(profile: str) -> bool:
    if not metadata_catalog_enabled():
        return False
    return (profile or "").strip() in metadata_catalog_profiles()


def _max_chars() -> int:
    return int(metadata_catalog_max_tokens() * _CHARS_PER_TOKEN)


def _domain_key(schema: Dict[str, Any], asset_id: str) -> str:
    dom = str(schema.get("context_domain") or schema.get("category") or "").strip()
    if dom.startswith("user_context"):
        return dom
    intent = schema.get("intent") or {}
    lane = str(intent.get("lane") or "").strip().lower()
    if lane == "lab" or asset_id.startswith("lab_"):
        return "lab"
    if lane == "wearable" or "wearable" in asset_id:
        return "wearable"
    if str(intent.get("asset_class") or "").lower() == "context":
        return "user_context.regimen"
    return dom or "other"


def mention_score(user_message: str, schema: Dict[str, Any]) -> float:
    msg = user_message or ""
    score = score_asset_positive(msg, schema)
    return min(3.0, max(0.0, score))


def recency_bonus(asset_id: str, user_id: str) -> float:
    """Placeholder — Stage 2D+ may read fetch telemetry; returns 0 in 2C."""
    _ = (asset_id, user_id)
    return 0.0


def rank_score(
    asset_id: str,
    schema: Dict[str, Any],
    *,
    user_message: str,
    user_id: str,
) -> float:
    intent = schema.get("intent") or {}
    asset_class = str(intent.get("asset_class") or "data").lower()
    base = float(intent.get("priority") or 50) * 10.0
    base += mention_score(user_message, schema) * 5.0
    base += recency_bonus(asset_id, user_id) * 2.0
    if asset_class == "context":
        base -= 3.0
    return base


def _asset_row(
    asset_id: str,
    schema: Dict[str, Any],
    *,
    dyn: bool = False,
) -> Dict[str, Any]:
    intent = schema.get("intent") or {}
    disp = schema.get("display") or {}
    asset_class = str(intent.get("asset_class") or "data").upper()
    if asset_class == "CONTEXT":
        asset_class = "CTX"
    elif asset_class == "DATA":
        asset_class = "DATA"
    title_zh = str(disp.get("title_zh") or schema.get("title_zh") or asset_id)[:40]
    title_en = str(disp.get("title_en") or disp.get("title_short") or asset_id)[:48]
    cat = schema.get("catalog") or {}
    profiles = ",".join(cat.get("profiles") or []) or "—"
    if dyn:
        profiles = "combined"
    return {
        "asset_id": asset_id,
        "dyn": dyn,
        "domain": _domain_key(schema, asset_id),
        "asset_class": asset_class,
        "title_zh": title_zh,
        "title_en": title_en,
        "profiles": profiles,
        "rank": 0.0,
        "is_context": str(intent.get("asset_class") or "").lower() == "context",
    }


def _collect_static_rows() -> List[Dict[str, Any]]:
    from pha.universal_catalog_manager import get_catalog_manager

    mgr = get_catalog_manager()
    cache_key = tuple(sorted(mgr._assets.keys()))
    if _STATIC_ROWS_CACHE.get("key") == cache_key:
        return list(_STATIC_ROWS_CACHE.get("rows") or [])

    rows: List[Dict[str, Any]] = []
    for aid, doc in sorted(mgr._assets.items()):
        cat = doc.get("catalog") or {}
        if not cat.get("enabled"):
            continue
        rows.append(_asset_row(aid, doc))
    _STATIC_ROWS_CACHE["key"] = cache_key
    _STATIC_ROWS_CACHE["rows"] = rows
    return list(rows)


def _promoted_dynamic_rows(user_id: str) -> List[Dict[str, Any]]:
    try:
        from pha.dynamic_slot_registry import list_promoted_slots, user_dynamic_slots_enabled
    except ImportError:
        return []
    if not user_dynamic_slots_enabled():
        return []
    out: List[Dict[str, Any]] = []
    for sl in list_promoted_slots(user_id, "combined_review"):
        sid = str(sl.get("slot_id") or "").strip()
        if not sid:
            continue
        pseudo = {
            "asset_id": f"dyn:{sid}",
            "context_domain": str(sl.get("maps_to_domain") or "user_context.regimen"),
            "intent": {"asset_class": "context", "priority": 5, "lane": "context"},
            "display": {
                "title_zh": str(sl.get("title_zh") or sid),
                "title_en": str(sl.get("title_en") or sid),
            },
            "catalog": {"enabled": True, "profiles": ["combined_review"]},
        }
        out.append(_asset_row(f"dyn:{sid}", pseudo, dyn=True))
    return out


def _layer_a_domain_summary(rows: List[Dict[str, Any]]) -> str:
    counts: Dict[str, int] = {}
    for r in rows:
        dom = str(r.get("domain") or "other")
        if dom.startswith("user_context"):
            key = "ctx.regimen" if "regimen" in dom else dom.replace("user_context.", "ctx.")
        elif dom == "lab":
            key = "lab"
        elif dom == "wearable":
            key = "wearable"
        else:
            key = dom[:12]
        counts[key] = counts.get(key, 0) + 1
    parts = [f"{k}:{counts[k]}" for k in sorted(counts.keys())]
    return "domains: " + " ".join(parts)


def _format_layer_b_line(row: Dict[str, Any]) -> str:
    aid = row["asset_id"]
    cls = row["asset_class"]
    zh = row["title_zh"]
    en = row["title_en"]
    lanes = row["profiles"]
    return f"{aid}|{cls}|{zh}|{en}|{lanes}"


def _truncate_rows(
    rows: List[Dict[str, Any]],
    *,
    budget_chars: int,
    header_chars: int,
    layer_a: str,
) -> Tuple[List[Dict[str, Any]], int]:
    """Context-first drop, then lowest rank; protect lab_lipid_panel & wearable_bundle."""
    protected_ids = {"lab_lipid_panel", "wearable_bundle"}
    remaining = list(rows)
    truncated = 0

    def total_len(selected: List[Dict[str, Any]]) -> int:
        body = "\n".join(_format_layer_b_line(r) for r in selected)
        return header_chars + len(layer_a) + len(body) + 40

    while remaining and total_len(remaining) > budget_chars:
        droppable = [
            r
            for r in remaining
            if r["asset_id"] not in protected_ids
        ]
        if not droppable:
            break
        context = [r for r in droppable if r.get("is_context")]
        pool = context if context else droppable
        pool.sort(key=lambda r: (r.get("rank") or 0, r["asset_id"]))
        drop = pool[0]
        remaining.remove(drop)
        truncated += 1

    return remaining, truncated


def build_metadata_catalog_block(
    user_id: str,
    *,
    user_message: str = "",
    profile: str = "combined_review",
) -> str:
    if not should_inject_metadata_catalog(profile):
        return ""

    uid = (user_id or "default").strip() or "default"
    msg = (user_message or "").strip()
    max_chars = _max_chars()

    header = "【Metadata Catalog · read-only · Tier1】"
    rows = _collect_static_rows()
    for r in rows:
        doc = None
        from pha.universal_catalog_manager import get_catalog_manager

        mgr = get_catalog_manager()
        aid = r["asset_id"]
        if not aid.startswith("dyn:"):
            doc = mgr.get_asset(aid)
        if doc:
            r["rank"] = rank_score(aid, doc, user_message=msg, user_id=uid)

    dyn_rows = _promoted_dynamic_rows(uid)
    for r in dyn_rows:
        r["rank"] = float(r.get("rank") or 0) + mention_score(msg, {"intent": {"trigger_keywords": []}})

    all_rows = rows + dyn_rows
    all_rows.sort(key=lambda r: (-(r.get("rank") or 0), r["asset_id"]))

    layer_a = _layer_a_domain_summary(all_rows)
    header_budget = len(header) + len(layer_a) + 8
    layer_b_budget = max_chars - header_budget
    selected, truncated = _truncate_rows(
        all_rows,
        budget_chars=max_chars,
        header_chars=len(header),
        layer_a=layer_a,
    )

    lines = [header, layer_a]
    for r in selected:
        lines.append(_format_layer_b_line(r))
    if truncated:
        lines.append(f"… +{truncated} assets truncated")
    return "\n".join(lines)


def estimate_token_count(text: str) -> int:
    return int(len(text or "") / _CHARS_PER_TOKEN)


def invalidate_metadata_catalog_cache() -> None:
    _STATIC_ROWS_CACHE["key"] = None
    _STATIC_ROWS_CACHE["rows"] = []


__all__ = [
    "build_metadata_catalog_block",
    "estimate_token_count",
    "invalidate_metadata_catalog_cache",
    "metadata_catalog_enabled",
    "metadata_catalog_force_tier0",
    "metadata_catalog_max_tokens",
    "metadata_catalog_profiles",
    "rank_score",
    "should_inject_metadata_catalog",
]
