#!/usr/bin/env python3
"""Stage 2A — HarnessBuildReport v1.1 field selfcheck (no LLM)."""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pha.catalog_existence import build_catalog_existence, build_intent_route_payload
from pha.harness_report import REPORT_SCHEMA, build_harness_report, dry_run_harness_report
from pha.universal_catalog_manager import get_catalog_manager

T2 = "根据血脂和HRV分析补剂方案"


def main() -> int:
    failed = 0
    report = dry_run_harness_report(T2, user_id="default")
    if report.get("schema") != REPORT_SCHEMA:
        print("FAIL schema", report.get("schema"))
        failed += 1
    for key in ("intent_route", "catalog_existence", "dynamic_slots"):
        if key not in report:
            print(f"FAIL missing {key}")
            failed += 1
    ir = report["intent_route"]
    if ir.get("authoritative_profile") != "combined_review":
        print("FAIL intent_route", ir)
        failed += 1
    ce = report["catalog_existence"]
    if not ce.get("candidates"):
        print("FAIL catalog_existence", ce)
        failed += 1

    mgr = get_catalog_manager()
    route = mgr.resolve_intent(T2)
    payload = build_intent_route_payload(route, plan_profile="combined_review")
    if not payload.get("asset_scores"):
        print("FAIL empty asset_scores")
        failed += 1

    ce2 = build_catalog_existence("default", "combined_review", T2)
    print("catalog_existence sample:", json.dumps(ce2, ensure_ascii=False, indent=2))
    print("intent_route sample:", json.dumps(ir, ensure_ascii=False, indent=2))
    print("dynamic_slots:", report.get("dynamic_slots"))

    if failed:
        print("\nFAIL", failed, "checks")
        return 1
    print("\nOK harness_report v1.1 selfcheck")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
