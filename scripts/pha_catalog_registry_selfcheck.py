#!/usr/bin/env python3
"""P1 Schema Registry self-check (no LLM)."""

from __future__ import annotations

import os
import sys

os.environ["PHA_CATALOG_EXISTENCE_VETO"] = "0"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pha.evidence_catalog import (  # noqa: E402
    build_evidence_catalog_block,
    default_combined_fetch_ids,
    fetch_evidence_by_id,
)
from pha.universal_catalog_manager import get_catalog_manager, reload_catalog_manager  # noqa: E402


def main() -> int:
    reload_catalog_manager()
    mgr = get_catalog_manager()
    failed = 0

    for raw, want in [("LDL_TABLE", "lab_lipid_panel"), ("WEARABLE_90D", "wearable_bundle")]:
        got = mgr.resolve_id(raw)
        if got != want:
            print(f"FAIL resolve {raw!r} -> {got!r} (want {want!r})")
            failed += 1

    defaults = default_combined_fetch_ids()
    if defaults != ["lab_lipid_panel", "wearable_bundle"]:
        print("FAIL default_combined_fetch_ids:", defaults)
        failed += 1

    cat = build_evidence_catalog_block(profile="combined_review")
    if "lab_lipid_panel" not in cat or "wearable_bundle" not in cat:
        print("FAIL catalog block missing canonical ids")
        failed += 1
    if cat.count("\n- ") > 5:
        print("FAIL catalog too many entries")
        failed += 1

    uid = "default"
    msg = "根据血脂与 HRV 活动消耗分析补剂"
    for ids in (
        defaults,
        ["LDL_TABLE", "WEARABLE_90D"],
    ):
        payload = fetch_evidence_by_id(uid, ids, msg)
        if not payload.get("fetched_ids"):
            print("FAIL empty fetched_ids for", ids)
            failed += 1
        lipid = any(
            mgr.manifest_domain_for_asset(x) == "lipid" for x in payload["fetched_ids"]
        )
        wear = any(
            mgr.manifest_domain_for_asset(x) == "wearable" for x in payload["fetched_ids"]
        )
        if not lipid or not wear:
            print("FAIL manifest domains for", ids, payload["fetched_ids"])
            failed += 1

    print("OK schema registry self-check")
    print("defaults:", defaults)
    print("catalog_chars:", len(cat))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
