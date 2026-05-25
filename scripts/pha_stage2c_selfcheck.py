#!/usr/bin/env python3
"""Stage 2C — Metadata Catalog Tier1 injection selfcheck."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["PHA_METADATA_CATALOG"] = "1"
os.environ["PHA_METADATA_CATALOG_MAX_TOKENS"] = "400"

from pha.harness_plan import build_turn_evidence_plan
from pha.harness_report import dry_run_harness_report
from pha.metadata_catalog import (
    build_metadata_catalog_block,
    estimate_token_count,
    metadata_catalog_force_tier0,
    should_inject_metadata_catalog,
)

T2 = "根据血脂和HRV分析补剂方案"


def main() -> int:
    failed = 0
    if not should_inject_metadata_catalog("combined_review"):
        print("FAIL: MC should be enabled")
        failed += 1

    plan = build_turn_evidence_plan(T2)
    if "METADATA_CATALOG" not in plan.slots_tier1:
        print("FAIL: METADATA_CATALOG not in tier1", plan.slots_tier1)
        failed += 1
    if "METADATA_CATALOG" in plan.slots_tier0 and not metadata_catalog_force_tier0():
        print("FAIL: MC should not be in tier0 by default", plan.slots_tier0)
        failed += 1

    block = build_metadata_catalog_block("default", user_message=T2, profile="combined_review")
    if "Metadata Catalog" not in block:
        print("FAIL: missing MC header")
        failed += 1
    if "domains:" not in block:
        print("FAIL: missing layer A", block)
        failed += 1
    if "lab_lipid_panel" not in block:
        print("FAIL: missing lab asset", block)
        failed += 1

    tok = estimate_token_count(block)
    if tok > 450:
        print(f"FAIL: MC too large ~{tok} tokens", len(block), "chars")
        failed += 1

    report = dry_run_harness_report(T2, user_id="default")
    integrity = report.get("tier0_integrity") or {}
    tier0_used = integrity.get("used_chars") or 0
    if tier0_used > 2200:
        print(f"FAIL: tier0 bloated by MC: {tier0_used}")
        failed += 1
    if "METADATA_CATALOG" not in (report.get("plan") or {}).get("slots_tier1", []):
        print("FAIL: plan in report missing MC tier1", report.get("plan"))
        failed += 1
    mc_rep = report.get("metadata_catalog") or {}
    if not mc_rep.get("enabled"):
        print("FAIL: metadata_catalog telemetry missing", report.keys())
        failed += 1
    sys_msg = next(
        (m for m in report.get("messages_stack") or [] if m.get("label") == "system"),
        {},
    )
    if "Metadata Catalog" not in str(sys_msg.get("preview") or ""):
        # tier1 may be after tier0 in stack — check tier1 chars increased
        if (sys_msg.get("chars") or 0) < 3500:
            print("WARN: system preview may not include tier1 MC", sys_msg.get("chars"))

    print("plan.slots_tier1:", plan.slots_tier1)
    print("MC tokens~:", tok, "chars:", len(block))
    print("tier0_used:", tier0_used)
    print("MC sample:\n", block[:600])

    if failed:
        print("\nFAIL", failed)
        return 1
    print("\nOK stage2c selfcheck")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
