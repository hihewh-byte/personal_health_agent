#!/usr/bin/env python3
"""Stage 2D — Shadow Routing telemetry selfcheck (zero adopt)."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["PHA_SHADOW_ROUTING"] = "1"
os.environ["PHA_SHADOW_ROUTING_FORCE_SAMPLE"] = "1"
os.environ["PHA_METADATA_CATALOG"] = "0"

from pha.harness_report import dry_run_harness_report
from pha.shadow_routing import (
    effective_sample_rate,
    run_shadow_routing,
    shadow_confidence_threshold,
    shadow_routing_enabled,
    should_sample_shadow,
)

T2 = "根据血脂和HRV分析补剂方案"


def main() -> int:
    failed = 0

    if not shadow_routing_enabled():
        print("FAIL: PHA_SHADOW_ROUTING not enabled")
        failed += 1

    if effective_sample_rate("casual") != 0.0:
        print("FAIL: casual sample rate should be 0")
        failed += 1

    if not should_sample_shadow("combined_review"):
        print("FAIL: force sample should trigger for combined_review")
        failed += 1

    if should_sample_shadow("casual"):
        print("FAIL: casual should never sample")
        failed += 1

    from pha.universal_catalog_manager import get_catalog_manager

    mgr = get_catalog_manager()
    route = mgr.resolve_intent(T2)
    catalog_ids = mgr.catalog_asset_ids_for_profile(
        "combined_review",
        user_message=T2,
        user_id="default",
    )
    payload = run_shadow_routing(
        T2,
        authoritative_profile="combined_review",
        authoritative_catalog_ids=catalog_ids,
        user_id="default",
    )
    if not payload.get("enabled"):
        print("FAIL: shadow payload missing enabled", payload)
        failed += 1
    if not payload.get("sampled"):
        print("FAIL: shadow payload missing sampled", payload)
        failed += 1
    if payload.get("authoritative_profile") != "combined_review":
        print("FAIL: wrong authoritative_profile", payload)
        failed += 1
    agree = payload.get("agreement") or {}
    if agree.get("profile_match") is not True:
        print("FAIL: rule mirror should match profile", payload)
        failed += 1
    if payload.get("shadow_profile_hint") != route.profile:
        print("FAIL: shadow profile hint", payload.get("shadow_profile_hint"), route.profile)
        failed += 1

    thresh = shadow_confidence_threshold()
    pri = payload.get("telemetry_priority")
    conf = float(payload.get("shadow_confidence") or 0.0)
    expected_pri = "high" if conf >= thresh else "low"
    if pri != expected_pri:
        print("FAIL: telemetry_priority", pri, "expected", expected_pri, "conf", conf)
        failed += 1

    report = dry_run_harness_report(T2, user_id="default")
    sr = report.get("shadow_routing") or {}
    if not sr.get("enabled"):
        print("FAIL: harness report missing shadow_routing", report.keys())
        failed += 1
    if not sr.get("completed"):
        print("FAIL: shadow job not completed", sr)
        failed += 1

    print("shadow_confidence:", conf, "priority:", pri)
    print("disagreement_class:", sr.get("disagreement_class"))
    print("ids_jaccard:", (sr.get("agreement") or {}).get("ids_jaccard"))

    if failed:
        print("\nFAIL", failed)
        return 1
    print("\nOK stage2d selfcheck")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
