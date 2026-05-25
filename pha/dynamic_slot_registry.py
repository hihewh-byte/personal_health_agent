"""Universal Dynamic Slots Registry — Discover → Capture → Promote (Stage 2B)."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pha.catalog_existence import existence_probe_for_asset, summarize_dynamic_slots
from pha.catalog_dch import token_in_message

_SLOT_ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,48}$")

_REGISTRY_ROOT = Path(__file__).resolve().parent.parent / "storage" / "registry"
_PRESET_PATH = _REGISTRY_ROOT / "universal_health_assets.json"

_DOMAIN_ALLOWLIST = frozenset(
    {
        "lab",
        "wearable",
        "user_context.regimen",
        "user_context.lifestyle",
        "user_context.symptom",
        "genomics",
        "allergy",
    }
)


def dynamic_slot_discovery_enabled() -> bool:
    return os.environ.get("PHA_DYNAMIC_SLOT_DISCOVERY", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def user_dynamic_slots_enabled() -> bool:
    return os.environ.get("PHA_USER_DYNAMIC_SLOTS", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ) or dynamic_slot_discovery_enabled()


def auto_promote_enabled() -> bool:
    return os.environ.get("PHA_DYNAMIC_SLOT_AUTO_PROMOTE", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def max_promoted_slots() -> int:
    try:
        return max(1, int(os.environ.get("PHA_DYNAMIC_SLOTS_MAX_PROMOTED", "8")))
    except ValueError:
        return 8


def _slots_path(user_id: str) -> Path:
    uid = (user_id or "default").strip() or "default"
    custom = os.environ.get("PHA_USER_DYNAMIC_SLOTS_DIR", "").strip()
    if custom:
        base = Path(custom)
    else:
        base = Path(__file__).resolve().parent.parent / "storage" / "users" / uid
    base.mkdir(parents=True, exist_ok=True)
    return base / "dynamic_slots.json"


def load_preset_registry() -> Dict[str, Any]:
    if not _PRESET_PATH.is_file():
        return {"domains": {}}
    return json.loads(_PRESET_PATH.read_text(encoding="utf-8"))


def load_user_slots_doc(user_id: str) -> Dict[str, Any]:
    if not user_dynamic_slots_enabled():
        return {"version": "1", "user_id": user_id, "slots": []}
    path = _slots_path(user_id)
    if not path.is_file():
        return {"version": "1", "user_id": user_id, "slots": []}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": "1", "user_id": user_id, "slots": []}
    doc.setdefault("slots", [])
    return doc


def save_user_slots_doc(user_id: str, doc: Dict[str, Any]) -> None:
    if not user_dynamic_slots_enabled():
        return
    path = _slots_path(user_id)
    doc["user_id"] = (user_id or "default").strip() or "default"
    doc["version"] = doc.get("version") or "1"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _valid_slot_id(slot_id: str, *, reserved: Optional[set[str]] = None) -> bool:
    sid = (slot_id or "").strip()
    if not _SLOT_ID_RE.match(sid):
        return False
    if reserved and sid in reserved:
        return False
    return True


def admission_check(slot: Dict[str, Any], *, reserved_asset_ids: set[str]) -> Tuple[bool, str]:
    sid = str(slot.get("slot_id") or "").strip()
    if not _valid_slot_id(sid, reserved=reserved_asset_ids):
        return False, "invalid_slot_id"
    domain = str(slot.get("maps_to_domain") or slot.get("domain") or "").strip()
    if domain not in _DOMAIN_ALLOWLIST:
        return False, "unmapped_domain"
    if not str(slot.get("title_zh") or "").strip():
        return False, "missing_title_zh"
    maps_to = str(slot.get("maps_to_asset") or "").strip()
    if maps_to and maps_to not in reserved_asset_ids:
        return False, "unknown_maps_to_asset"
    if not maps_to and domain.startswith("user_context"):
        slot["maps_to_asset"] = "supplement_bg"
    return True, "ok"


def promote_eligible_slots(user_id: str) -> List[str]:
    """Promote captured slots from prior turns (call at request start, before catalog)."""
    if not auto_promote_enabled() or not user_dynamic_slots_enabled():
        return []
    from pha.universal_catalog_manager import get_catalog_manager

    mgr = get_catalog_manager()
    reserved = set(mgr._assets.keys())
    doc = load_user_slots_doc(user_id)
    promoted_ids: List[str] = []
    changed = False

    for sl in doc.get("slots") or []:
        if not isinstance(sl, dict):
            continue
        if str(sl.get("status") or "") not in ("captured", "pending_discovery"):
            continue
        ok_admit, reason = admission_check(sl, reserved_asset_ids=reserved)
        if not ok_admit:
            sl["last_promote_reject"] = reason
            changed = True
            continue
        maps_to = str(sl.get("maps_to_asset") or "supplement_bg").strip()
        schema = mgr.get_asset(maps_to)
        ex = sl.get("existence") or {
            "probe": "sqlite_notes",
            "where": {"category_in": ["supplement", "medication", "general"]},
            "min_rows": 1,
        }
        exists, ex_reason = existence_probe_for_asset(
            user_id,
            maps_to,
            schema,
            existence_override=ex if isinstance(ex, dict) else None,
        )
        if not exists:
            sl["last_existence_reason"] = ex_reason
            if str(sl.get("status")) == "pending_discovery":
                sl["status"] = "captured" if ex_reason != "sqlite_notes_min_rows" else "pending_discovery"
            changed = True
            continue
        sl["status"] = "promoted"
        sl["promoted_at"] = _now_iso()
        sl["promotion_reason"] = "capture+existence"
        promoted_ids.append(str(sl.get("slot_id")))
        changed = True

    if promoted_ids:
        _enforce_promoted_cap(doc)
        save_user_slots_doc(user_id, doc)
    elif changed:
        save_user_slots_doc(user_id, doc)
    return promoted_ids


def _enforce_promoted_cap(doc: Dict[str, Any]) -> None:
    cap = max_promoted_slots()
    promoted = [s for s in doc.get("slots") or [] if isinstance(s, dict) and s.get("status") == "promoted"]
    if len(promoted) <= cap:
        return
    promoted.sort(key=lambda s: str(s.get("promoted_at") or ""))
    drop = len(promoted) - cap
    for sl in promoted[:drop]:
        sl["status"] = "archived"
        sl["archived_at"] = _now_iso()


def list_promoted_slots(user_id: str, profile: str = "") -> List[Dict[str, Any]]:
    if not user_dynamic_slots_enabled():
        return []
    out: List[Dict[str, Any]] = []
    for sl in load_user_slots_doc(user_id).get("slots") or []:
        if isinstance(sl, dict) and sl.get("status") == "promoted":
            if profile and profile != "combined_review":
                continue
            out.append(sl)
    return out


def mark_captured_after_background_store(user_id: str, message: str) -> None:
    """After DB capture: align pending proposals to captured (no same-turn promote)."""
    if not user_dynamic_slots_enabled():
        return
    doc = load_user_slots_doc(user_id)
    changed = False
    msg = message or ""
    for sl in doc.get("slots") or []:
        if not isinstance(sl, dict):
            continue
        if str(sl.get("status")) != "pending_discovery":
            continue
        tokens = sl.get("mention_tokens") or []
        if any(token_in_message(str(t), msg) for t in tokens if t):
            sl["status"] = "captured"
            sl["captured_at"] = _now_iso()
            changed = True
    if changed:
        save_user_slots_doc(user_id, doc)


def discover_rule_based(user_id: str, user_message: str) -> int:
    """Lightweight Discover (no LLM): regimen keywords → pending proposal."""
    if not dynamic_slot_discovery_enabled():
        return 0
    from pha.universal_catalog_manager import get_catalog_manager

    msg = (user_message or "").strip()
    if len(msg) < 8:
        return 0

    preset = load_preset_registry()
    mgr = get_catalog_manager()
    reserved = set(mgr._assets.keys())
    route = mgr.resolve_intent(msg)

    # Already covered by schema router — skip duplicate proposals
    if route.include_supplement_catalog or route.asset_scores.get("supplement_bg", 0) >= 2.0:
        return 0

    regimen_tokens = (
        ("草药", "herbal_regimen"),
        ("茶饮", "herbal_tea_regimen"),
        ("偏方", "folk_regimen"),
        ("中成药", "tcm_regimen"),
    )
    added = 0
    doc = load_user_slots_doc(user_id)
    existing_ids = {str(s.get("slot_id")) for s in doc.get("slots") or [] if isinstance(s, dict)}

    for token, slot_id in regimen_tokens:
        if not token_in_message(token, msg):
            continue
        if slot_id in existing_ids:
            continue
        proposal = {
            "slot_id": slot_id,
            "domain": "user_context.regimen",
            "maps_to_domain": "user_context.regimen",
            "maps_to_asset": "supplement_bg",
            "title_zh": f"用户{token}相关方案",
            "title_en": f"User {token} regimen",
            "mention_tokens": [token],
            "status": "pending_discovery",
            "discovered_at": _now_iso(),
            "confidence": 0.6,
            "source": "discovery_hook:rules",
        }
        ok, _ = admission_check(proposal, reserved_asset_ids=reserved)
        if not ok:
            continue
        doc.setdefault("slots", []).append(proposal)
        existing_ids.add(slot_id)
        added += 1

    if added:
        save_user_slots_doc(user_id, doc)
    return added


def on_request_start(user_id: str, user_message: str = "") -> Dict[str, Any]:
    """Start-of-turn hook: promote prior captures, optional discover."""
    promoted = promote_eligible_slots(user_id)
    discovered = 0
    if user_message:
        discovered = discover_rule_based(user_id, user_message)
    summary = summarize_dynamic_slots(user_id)
    summary["promoted_this_request"] = promoted
    summary["discovered_this_request"] = discovered
    return summary


def on_background_captured(user_id: str, message: str) -> None:
    mark_captured_after_background_store(user_id, message)


__all__ = [
    "admission_check",
    "discover_rule_based",
    "dynamic_slot_discovery_enabled",
    "list_promoted_slots",
    "load_preset_registry",
    "mark_captured_after_background_store",
    "max_promoted_slots",
    "on_background_captured",
    "on_request_start",
    "promote_eligible_slots",
    "user_dynamic_slots_enabled",
]
