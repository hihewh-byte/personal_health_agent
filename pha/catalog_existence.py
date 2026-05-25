"""Catalog existence probes and telemetry (Stage 2A — observability only)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from pha.chat_background import list_background_notes
from pha.numerics_manifest import _query_lipid_rows
from pha.schema_intent_router import IntentRouteResult
from pha.sqlite_storage import _connect, init_schema


def catalog_existence_veto_enabled() -> bool:
    return os.environ.get("PHA_CATALOG_EXISTENCE_VETO", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _registry_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _dynamic_slots_path(user_id: str) -> Path:
    uid = (user_id or "default").strip() or "default"
    custom = os.environ.get("PHA_USER_DYNAMIC_SLOTS_DIR", "").strip()
    if custom:
        base = Path(custom)
    else:
        base = _registry_root() / "storage" / "users" / uid
    return base / "dynamic_slots.json"


def summarize_dynamic_slots(user_id: str) -> Dict[str, Any]:
    path = _dynamic_slots_path(user_id)
    if not path.is_file():
        return {"discovered": 0, "promoted": 0, "pending": [], "captured": 0}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"discovered": 0, "promoted": 0, "pending": [], "captured": 0, "read_error": True}
    slots = doc.get("slots") or []
    pending: List[str] = []
    promoted = 0
    captured = 0
    discovered = 0
    for sl in slots:
        if not isinstance(sl, dict):
            continue
        sid = str(sl.get("slot_id") or "").strip()
        status = str(sl.get("status") or "").strip()
        if status in ("pending_discovery", "pending"):
            discovered += 1
            if sid:
                pending.append(sid)
        elif status == "captured":
            captured += 1
        elif status == "promoted":
            promoted += 1
    return {
        "discovered": discovered,
        "promoted": promoted,
        "captured": captured,
        "pending": pending[:20],
        "path": str(path),
    }


def build_intent_route_payload(
    route: IntentRouteResult,
    *,
    catalog_ids: Optional[Sequence[str]] = None,
    plan_profile: Optional[str] = None,
) -> Dict[str, Any]:
    authoritative = plan_profile or route.profile
    return {
        "authoritative_profile": authoritative,
        "router_profile": route.profile,
        "question_type": route.question_type,
        "asset_scores": dict(route.asset_scores or {}),
        "include_supplement_catalog": bool(route.include_supplement_catalog),
        "include_context_regimen_catalog": bool(route.include_supplement_catalog),
        "context_only_lane": bool(route.context_only_lane),
        "catalog_ids": list(catalog_ids or []),
    }


def _probe_sqlite_notes(
    user_id: str,
    *,
    categories: Optional[Sequence[str]] = None,
    min_rows: int = 1,
) -> tuple[bool, str]:
    rows = list_background_notes(user_id, limit=50)
    if categories:
        cats = {str(c).strip() for c in categories}
        rows = [r for r in rows if str(r.get("category") or "") in cats]
    ok = len(rows) >= max(1, min_rows)
    reason = "sqlite_notes_ok" if ok else "sqlite_notes_min_rows"
    return ok, reason


def _probe_wearable_data(user_id: str, *, min_rows: int = 1) -> tuple[bool, str]:
    uid = (user_id or "default").strip() or "default"
    init_schema()
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT COUNT(*) AS c FROM wearable_data WHERE user_id = ?",
            (uid,),
        )
        count = int(cur.fetchone()[0])
    finally:
        conn.close()
    ok = count >= max(1, min_rows)
    return ok, "sqlite_wearable_ok" if ok else "sqlite_wearable_min_rows"


def _probe_lipid_data(user_id: str, *, min_rows: int = 1) -> tuple[bool, str]:
    rows = _query_lipid_rows(user_id)
    ok = len(rows) >= max(1, min_rows)
    return ok, "sqlite_lipid_ok" if ok else "sqlite_lipid_min_rows"


def existence_probe_for_asset(
    user_id: str,
    asset_id: str,
    schema: Optional[Dict[str, Any]],
    *,
    background_block_nonempty: bool = False,
    existence_override: Optional[Dict[str, Any]] = None,
) -> tuple[bool, str]:
    """Return (exists, reason_code) for telemetry / menu veto."""
    doc = schema or {}
    existence = dict(existence_override or doc.get("existence") or {})
    probe = str(existence.get("probe") or "").strip().lower()

    if probe == "always":
        return True, "existence_always"
    if probe == "sqlite_notes":
        where = existence.get("where") or {}
        cats = where.get("category_in") or existence.get("category_in")
        if isinstance(cats, str):
            cats = [cats]
        min_rows = int(existence.get("min_rows") or where.get("min_rows") or 1)
        return _probe_sqlite_notes(user_id, categories=cats, min_rows=min_rows)
    if probe == "sqlite_metric":
        domain = str((doc.get("manifest") or {}).get("domain") or "").lower()
        if domain == "lipid" or asset_id == "lab_lipid_panel":
            return _probe_lipid_data(user_id)
        if asset_id == "wearable_bundle":
            return _probe_wearable_data(user_id)
    if probe == "patient_state":
        return True, "patient_state_deferred"

    # Stage 2A defaults (no schema.existence block yet)
    if asset_id == "supplement_bg":
        ok, reason = _probe_sqlite_notes(
            user_id,
            categories=("supplement", "medication", "general"),
            min_rows=1,
        )
        if ok:
            return ok, reason
        if background_block_nonempty:
            return True, "background_block_nonempty"
        return False, reason
    if asset_id == "lab_lipid_panel":
        return _probe_lipid_data(user_id)
    if asset_id == "wearable_bundle":
        return _probe_wearable_data(user_id)

    intent = doc.get("intent") or {}
    if str(intent.get("asset_class") or "").lower() == "context":
        ok, reason = _probe_sqlite_notes(user_id, min_rows=1)
        return ok, reason
    return True, "existence_default_data"


def build_catalog_existence(
    user_id: str,
    profile: str,
    user_message: str = "",
    *,
    background_block_nonempty: bool = False,
) -> Dict[str, Any]:
    from pha.universal_catalog_manager import get_catalog_manager

    mgr = get_catalog_manager()
    candidates_raw = []
    for aid, doc in sorted(mgr._assets.items()):
        cat = doc.get("catalog") or {}
        if not cat.get("enabled"):
            continue
        profiles = cat.get("profiles") or []
        if profile and profiles and profile not in profiles:
            continue
        if cat.get("conditional") and aid == "supplement_bg":
            if not mgr.should_include_supplement_catalog(user_message):
                continue
        candidates_raw.append(aid)
    if profile == "combined_review":
        order = ["lab_lipid_panel", "wearable_bundle", "supplement_bg"]
        candidates = [x for x in order if x in candidates_raw] + [
            x for x in candidates_raw if x not in order
        ]
    else:
        candidates = candidates_raw
    vetoed: List[str] = []
    admitted: List[str] = []
    veto_reasons: Dict[str, str] = {}

    for aid in candidates:
        doc = mgr.get_asset(aid)
        ok, reason = existence_probe_for_asset(
            user_id,
            aid,
            doc,
            background_block_nonempty=(
                background_block_nonempty if aid == "supplement_bg" else False
            ),
        )
        if ok:
            admitted.append(aid)
        else:
            vetoed.append(aid)
            veto_reasons[aid] = reason

    return {
        "profile": profile,
        "veto_enabled": catalog_existence_veto_enabled(),
        "candidates": candidates,
        "admitted": admitted,
        "vetoed": vetoed,
        "veto_reasons": veto_reasons,
        "would_menu_ids": admitted if catalog_existence_veto_enabled() else candidates,
    }


__all__ = [
    "build_catalog_existence",
    "build_intent_route_payload",
    "catalog_existence_veto_enabled",
    "existence_probe_for_asset",
    "summarize_dynamic_slots",
]
