#!/usr/bin/env python3
"""Selfcheck: PHA ↔ harness_core thin adapter (soft if sibling missing)."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main() -> int:
    from pha.harness_core_adapter import (
        HarnessCoreUnavailable,
        harness_core_available,
        plan_vs_actual_via_core,
        smoke_adapter_roundtrip,
        to_core_plan,
    )
    from pha.harness_plan import build_turn_evidence_plan

    if not harness_core_available():
        print("SKIP pha_harness_core_adapter_selfcheck (harness_core not found)")
        return 0

    plan = build_turn_evidence_plan(
        "以下是我的补剂方案：蛋白粉30g + 鱼油 + 镁300mg"
    )
    core = to_core_plan(plan)
    assert core.profile == "supplement_manifest", core.profile
    assert "TASK" in core.slots_tier0
    assert "legacy_question_type" in core.domain_meta

    smoke = smoke_adapter_roundtrip(plan)
    assert "plan" in smoke["core_phases"]
    assert "compose" in smoke["core_phases"]

    diffs = plan_vs_actual_via_core(
        plan,
        tools_executed=["not_a_real_tool"],
    )
    assert any(d.startswith("tool_not_allowed:") for d in diffs), diffs

    print("PASS pha_harness_core_adapter_selfcheck")
    print(f"  profile={core.profile} phases={smoke['core_phases']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print("FAIL:", exc)
        raise SystemExit(1)
