#!/usr/bin/env python3
"""Phase 1 golden cases — dry-run HarnessBuildReport without LLM."""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("PHA_HARNESS_DEBUG", "1")
os.environ["PHA_HARNESS_REPORT_PATH"] = "/tmp/pha-harness-golden.jsonl"

from pha.harness_report import (  # noqa: E402
    REPORT_SCHEMA,
    dry_run_harness_report,
    emit_harness_build_report,
    format_harness_summary,
)

T1_SUPPLEMENT = """以下是我的补剂方案：
上午 训练后 蛋白粉30g + 香蕉 + 5g肌酸 + B族 + 益生菌
中午 鱼油 + 卵磷脂 + D3+K2 + Q10 + 非布司他 + 他汀
晚上 烤红薯 + 蛋白 + 蔬菜 + Move Free + 姜黄素
睡前 镁300-400mg + 纳豆激酶 + 南非醉茄
"""

T2_COMBINED = (
    "根据我所有的检验报告中的血脂情况 ，请分析HRV与运动消耗对血脂有没有影响，"
    "然后给我更新的补剂方案建议"
)


def _slot_ok(report: dict, slot_id: str) -> bool:
    integrity = report.get("tier0_integrity") or {}
    for row in integrity.get("slots") or []:
        if row.get("id") == slot_id:
            return row.get("state") in ("full", "summary", "min") and (row.get("chars") or 0) > 0
    return False


def main() -> int:
    open(os.environ["PHA_HARNESS_REPORT_PATH"], "w").close()
    cases = [("T1_supplement", T1_SUPPLEMENT), ("T2_combined", T2_COMBINED)]
    print("=== PHA Harness golden dry-run (harness_report v1.1) ===\n")
    failed = 0
    for case_id, msg in cases:
        report = dry_run_harness_report(msg)
        report["case_id"] = case_id
        emit_harness_build_report(report)
        plan = report.get("plan") or {}
        pva = report.get("plan_vs_actual") or []
        integrity = report.get("tier0_integrity") or {}
        errs = integrity.get("errors") or []
        print(f"\n--- {case_id} ---")
        print(format_harness_summary(report))
        print("plan.profile:", plan.get("profile"))
        print("runtime_mode:", report.get("runtime_mode"))
        print("tier0_integrity.errors:", errs)
        print("plan_vs_actual:", pva)
        if case_id == "T1_supplement":
            if plan.get("profile") != "supplement_manifest":
                print("FAIL: expected supplement_manifest")
                failed += 1
            if not _slot_ok(report, "TASK"):
                print("FAIL: TASK not in tier0 integrity")
                failed += 1
        if case_id == "T2_combined":
            if plan.get("profile") != "combined_review":
                print("FAIL: expected combined_review")
                failed += 1
            tools = plan.get("tools_allowed") or []
            if "fetch_evidence_by_id" not in tools:
                print("FAIL: expected fetch_evidence_by_id in tools_allowed:", tools)
                failed += 1
            if errs:
                print("FAIL: tier0_integrity errors:", errs)
                failed += 1
            if not _slot_ok(report, "EVIDENCE_CATALOG"):
                print("FAIL: EVIDENCE_CATALOG not in tier0 integrity")
                failed += 1
            if not _slot_ok(report, "NUMERICS_MANIFEST"):
                print("FAIL: NUMERICS_MANIFEST not in tier0 integrity")
                failed += 1
            tier0_used = (integrity.get("used_chars") or 0)
            if tier0_used > 2200:
                print(f"FAIL: tier0 too large for catalog mode: {tier0_used} chars")
                failed += 1
            slot_rows = {r.get("id"): r for r in (integrity.get("slots") or [])}
            if (slot_rows.get("LDL_AUTHORITY") or {}).get("chars", 0) > 0:
                print("FAIL: LDL_AUTHORITY still materialized in tier0")
                failed += 1
            if (slot_rows.get("WEARABLE_90D_SUMMARY") or {}).get("chars", 0) > 0:
                print("FAIL: WEARABLE_90D_SUMMARY still materialized in tier0")
                failed += 1
            nm = report.get("numerics_manifest") or {}
            dates = nm.get("allowed_dates") or []
            if "2023-12-15" not in dates or "2025-12-07" not in dates:
                print("FAIL: manifest missing ground-truth dates:", dates)
                failed += 1
            if report.get("runtime_mode") != "catalog_tool_loop":
                print("FAIL: expected runtime_mode catalog_tool_loop:", report.get("runtime_mode"))
                failed += 1
            if any(d.startswith("forbidden_") or d.startswith("tier0_not_materialized") for d in pva):
                print("FAIL: plan_vs_actual:", pva)
                failed += 1
            if report.get("schema") != REPORT_SCHEMA:
                print("FAIL: expected harness_report schema:", REPORT_SCHEMA, report.get("schema"))
                failed += 1
            ir = report.get("intent_route") or {}
            if ir.get("authoritative_profile") != "combined_review":
                print("FAIL: intent_route.profile:", ir)
                failed += 1
            ce = report.get("catalog_existence") or {}
            if not ce.get("candidates"):
                print("FAIL: catalog_existence missing candidates")
                failed += 1
            if "lab_lipid_panel" not in (ce.get("admitted") or []):
                print("FAIL: lab_lipid_panel should pass existence:", ce)
                failed += 1
            if "dynamic_slots" not in report:
                print("FAIL: dynamic_slots block missing")
                failed += 1
    print(f"\nJSONL: {os.environ['PHA_HARNESS_REPORT_PATH']}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
