#!/usr/bin/env python3
"""Simulate multi-turn attachment harness routing (no LLM)."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pha.attachment_asset_qa import resolve_attachment_qa_mode  # noqa: E402
from pha.harness_plan import build_turn_evidence_plan  # noqa: E402

TOKENS = ["Quercetin", "500mg"]

CASES = [
    ("Q1", "这是什么？对我有什么帮助？", True, "initial"),
    ("Q2", "还有什么其他帮助吗？", False, "episodic_bridge"),
    ("Q3", "跟我其他的哪些补剂结合能改善血脂？", False, "lipid_bridge"),
    ("Q4", "对比历年所有报告趋势", False, "none"),
]


def main() -> int:
    failed = 0
    for label, msg, has_parse, want in CASES:
        mode = resolve_attachment_qa_mode(
            msg,
            has_parsed_attachment=has_parse,
            session_focus_active=not has_parse and label != "Q1",
            focus_tokens=TOKENS if label != "Q1" else [],
        )
        if mode != want:
            print(f"FAIL {label}: want={want} got={mode} msg={msg!r}")
            failed += 1
            continue
        if mode in ("episodic_bridge", "lipid_bridge", "initial"):
            plan = build_turn_evidence_plan(
                msg,
                attachment_asset_qa=True,
                attachment_qa_mode=mode,
            )
            if mode == "episodic_bridge" and plan.profile != "attachment_episodic_bridge":
                print(f"FAIL {label}: profile={plan.profile}")
                failed += 1
        print(f"OK {label}: mode={mode}")

    if failed:
        return 1
    print("OK: harness route sim")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
