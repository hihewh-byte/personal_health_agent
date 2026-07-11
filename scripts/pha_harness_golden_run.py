#!/usr/bin/env python3
"""No-LLM harness golden dry-run — Plan / Tier0 / BuildReport without calling Ollama.

Usage (from repo root, after ``bash scripts/bootstrap.sh`` or editable install)::

    python scripts/pha_harness_golden_run.py

Exit 0 = assertions passed. No Ollama / no API keys required.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("PHA_HARNESS_DEBUG", "1")
_DEFAULT_JSONL = str(Path(tempfile.gettempdir()) / "pha-harness-golden.jsonl")
os.environ.setdefault("PHA_HARNESS_REPORT_PATH", _DEFAULT_JSONL)

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


def _print_builder_card(case_id: str, report: dict) -> None:
    """Human-readable card for OSS visitors (no LLM involved)."""
    plan = report.get("plan") or {}
    integrity = report.get("tier0_integrity") or {}
    slots = integrity.get("slots") or []
    present = [
        f"{r.get('id')}={r.get('state')}({r.get('chars') or 0}c)"
        for r in slots
        if (r.get("chars") or 0) > 0
    ]
    tools = plan.get("tools_allowed") or []
    forbidden = plan.get("forbidden") or []
    print(f"\n--- {case_id} ---")
    print(f"  profile        : {plan.get('profile')}")
    print(f"  runtime_mode   : {report.get('runtime_mode')}")
    print(f"  tools_allowed  : {tools or '(none)'}")
    print(f"  forbidden      : {forbidden[:6]}{'…' if len(forbidden) > 6 else ''}")
    print(f"  tier0 slots    : {', '.join(present) if present else '(empty)'}")
    print(f"  tier0 used     : {integrity.get('used_chars') or 0} chars")
    print(f"  plan_vs_actual : {report.get('plan_vs_actual') or []}")
    print(f"  summary        : {format_harness_summary(report)}")


def main() -> int:
    report_path = os.environ["PHA_HARNESS_REPORT_PATH"]
    open(report_path, "w").close()
    cases = [("T1_supplement", T1_SUPPLEMENT), ("T2_combined", T2_COMBINED)]
    print("=== PHA Harness — 30s No-LLM Golden Run ===")
    print("Control plane only: Plan → Tier0 assembly → BuildReport (no Ollama call).\n")
    failed = 0
    for case_id, msg in cases:
        report = dry_run_harness_report(msg)
        report["case_id"] = case_id
        emit_harness_build_report(report)
        plan = report.get("plan") or {}
        pva = report.get("plan_vs_actual") or []
        integrity = report.get("tier0_integrity") or {}
        errs = integrity.get("errors") or []
        _print_builder_card(case_id, report)
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
            admitted = ce.get("admitted") or []
            if "lab_lipid_panel" in admitted:
                if not dates:
                    print("FAIL: lab_lipid_panel admitted but manifest has no allowed dates:", nm)
                    failed += 1
            else:
                print("INFO: no local lab fixture; catalog vetoed lab_lipid_panel as expected")
            if "dynamic_slots" not in report:
                print("FAIL: dynamic_slots block missing")
                failed += 1
    print(f"\nJSONL report: {report_path}")
    if failed:
        print(f"RESULT: FAIL ({failed} assertion(s))")
        return 1

    # Optional: sibling harness_core adapter bridge (soft — public clone may omit it)
    try:
        from pha.harness_core_adapter import harness_core_available, smoke_adapter_roundtrip
        from pha.harness_plan import build_turn_evidence_plan

        if harness_core_available():
            plan_obj = build_turn_evidence_plan(T1_SUPPLEMENT)
            smoke = smoke_adapter_roundtrip(plan_obj)
            if smoke.get("core_profile") != "supplement_manifest":
                print("FAIL: harness_core adapter profile mismatch", smoke)
                return 1
            if "plan" not in (smoke.get("core_phases") or []):
                print("FAIL: harness_core adapter missing PLAN spine", smoke)
                return 1
            print(
                f"PASS harness_core adapter "
                f"profile={smoke['core_profile']} core_phases={smoke['core_phases']}"
            )
        else:
            print("FAIL: vendored packages/harness_core missing (adapter unavailable)")
            return 1
    except Exception as exc:  # noqa: BLE001 — golden must surface adapter bugs
        print("FAIL: harness_core adapter:", exc)
        return 1

    print("RESULT: PASS — harness planned and assembled evidence without calling an LLM.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
