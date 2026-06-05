#!/usr/bin/env python3
"""Stage 3A.1 — attachment_asset_qa profile + focused background selfcheck."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pha.attachment_asset_qa import (
    build_focused_background_for_attachment_qa,
    is_attachment_asset_qa_turn,
)
from pha.harness_plan import build_turn_evidence_plan

Q_ASSET = "这个是什么？对我有什么帮助？"
Q_LAB = "这个补剂对我的血脂和HRV有什么帮助？"

FOCUS = """
Supplement Facts
Serving Size 2 Gummies
Component X extract 150 mg
Component Y 300 mg
"""


def main() -> int:
    failed = 0

    if not is_attachment_asset_qa_turn(Q_ASSET, has_parsed_attachment=True):
        print("FAIL: should detect attachment QA turn")
        failed += 1
    if is_attachment_asset_qa_turn(Q_LAB, has_parsed_attachment=True):
        print("FAIL: lab explicit should not use attachment_asset_qa")
        failed += 1
    if is_attachment_asset_qa_turn(Q_ASSET, has_parsed_attachment=False):
        print("FAIL: no attachment should not trigger")
        failed += 1

    plan = build_turn_evidence_plan(
        Q_ASSET + "\n【附件视觉解析摘要】\nServing Size 2 Gummies",
        attachment_asset_qa=True,
    )
    if plan.profile != "attachment_asset_qa":
        print("FAIL: plan profile", plan.profile)
        failed += 1
    if "PATIENT_STATE_LAB" in plan.all_slots:
        print("FAIL: patient state should be forbidden", plan.all_slots)
        failed += 1
    if "WEARABLE_90D_SUMMARY" in plan.all_slots:
        print("FAIL: wearable in slots", plan.slots_tier0)
        failed += 1
    if "fetch_evidence_by_id" in (plan.tools_allowed or []):
        print("FAIL: catalog tools allowed")
        failed += 1

    block = build_focused_background_for_attachment_qa("default", focus_text=FOCUS)
    if block and len(block) > 5000:
        print("FAIL: focused block too large", len(block))
        failed += 1

    plan2 = build_turn_evidence_plan(Q_LAB, attachment_asset_qa=False)
    if plan2.profile == "attachment_asset_qa":
        print("FAIL: lab question routed to attachment_asset_qa")
        failed += 1

    print("plan.profile (forced):", plan.profile)
    print("slots_tier0:", plan.slots_tier0)
    print("focused_bg_chars:", len(block or ""))

    if failed:
        print("\nFAIL", failed)
        return 1
    print("\nOK stage3a1 attachment_qa selfcheck")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
