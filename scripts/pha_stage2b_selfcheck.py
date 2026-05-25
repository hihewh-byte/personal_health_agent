#!/usr/bin/env python3
"""Stage 2B — dynamic registry + existence veto selfcheck."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["PHA_USER_DYNAMIC_SLOTS"] = "1"
os.environ["PHA_DYNAMIC_SLOT_DISCOVERY"] = "1"
os.environ["PHA_CATALOG_EXISTENCE_VETO"] = "1"

from pha.catalog_existence import build_catalog_existence, catalog_existence_veto_enabled
from pha.dynamic_slot_registry import (
    discover_rule_based,
    load_preset_registry,
    load_user_slots_doc,
    on_background_captured,
    on_request_start,
    promote_eligible_slots,
)
from pha.evidence_catalog import build_evidence_catalog_block
from pha.universal_catalog_manager import get_catalog_manager

T_DISCOVER = "最近开始喝草药茶饮调理，请帮我记下来"
T_CAPTURE = "我每天服用草药茶饮方案，镁片一粒"
T_COMBINED = "根据血脂和HRV分析补剂方案"


def main() -> int:
    failed = 0
    preset = load_preset_registry()
    if not preset.get("domains"):
        print("FAIL: universal_health_assets.json empty")
        failed += 1
    if not catalog_existence_veto_enabled():
        print("FAIL: veto should be on")
        failed += 1

    mgr = get_catalog_manager()
    ids_default = mgr.catalog_asset_ids_for_profile("combined_review", T_COMBINED, user_id="default")
    if "lab_lipid_panel" not in ids_default:
        print("FAIL: default user missing lab in menu", ids_default)
        failed += 1

    ids_empty = mgr.catalog_asset_ids_for_profile(
        "combined_review",
        T_COMBINED,
        user_id="__no_such_user_stage2b__",
    )
    if "supplement_bg" in ids_empty:
        print("FAIL: supplement_bg should be vetoed for empty user", ids_empty)
        failed += 1

    uid = "stage2b_test_user"
    doc = load_user_slots_doc(uid)
    doc["slots"] = []
    from pha.dynamic_slot_registry import save_user_slots_doc

    save_user_slots_doc(uid, doc)
    n = discover_rule_based(uid, T_DISCOVER)
    if n < 1:
        print("FAIL: expected discovery proposal", n)
        failed += 1
    from pha.chat_background import maybe_capture_chat_background

    stored, _ = maybe_capture_chat_background(uid, T_CAPTURE, session_id="dry")
    if not stored:
        print("FAIL: background capture")
        failed += 1
    on_background_captured(uid, T_CAPTURE)
    doc2 = load_user_slots_doc(uid)
    captured = [s for s in doc2.get("slots") or [] if s.get("status") == "captured"]
    if not captured:
        print("FAIL: expected captured slot", doc2)
        failed += 1

    promoted = promote_eligible_slots(uid)
    if not promoted:
        print("FAIL: expected promote on next request start", promoted, doc2)
        failed += 1

    block = build_evidence_catalog_block(
        profile="combined_review",
        user_message=T_CAPTURE,
        user_id=uid,
    )
    if "dyn:" not in block and "herbal" not in block:
        print("FAIL: promoted dynamic line missing from catalog:\n", block[:500])
        failed += 1

    meta = on_request_start("default", T_COMBINED)
    if not isinstance(meta.get("promoted_this_request"), list):
        print("FAIL: meta shape", meta)
        failed += 1

    ce = build_catalog_existence(uid, "combined_review", T_COMBINED)
    if ce.get("veto_enabled") is not True:
        print("FAIL: catalog_existence", ce)
        failed += 1

    print("preset domains:", list((preset.get("domains") or {}).keys()))
    print("default menu ids:", ids_default)
    print("empty-user menu ids:", ids_empty)
    print("promoted:", promoted)
    print("dynamic meta:", meta)

    if failed:
        print("\nFAIL", failed)
        return 1
    print("\nOK stage2b selfcheck")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
