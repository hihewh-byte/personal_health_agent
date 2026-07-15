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
        print("FAIL: vendored packages/harness_core required")
        return 1

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

    # P1.5-1: PHA must conform to the frozen v1 DomainAdapter contract.
    from pha.harness_core_adapter import (
        PHANumericsAdapter,
        selfcheck_domain_adapter_conformance,
    )

    conf = selfcheck_domain_adapter_conformance()
    assert conf["conforms"] is True, conf

    from harness_core.interfaces import run_post_audit
    from pha.numerics_manifest import ManifestEntry, NumericsManifest

    manifest = NumericsManifest(
        profile="selfcheck",
        user_id="selfcheck",
        entries=[
            ManifestEntry(
                domain="lipid",
                metric="ldl",
                value=4.05,
                unit="mmol/L",
                anchor="2026-06-01",
                source="selfcheck",
            )
        ],
    )
    ad = PHANumericsAdapter(manifest)
    core_plan2 = ad.build_plan("我最近一次的LDL是多少？")
    ok_verdict = run_post_audit(ad, core_plan2, "你 2026-06-01 的LDL为 4.05 mmol/L。")
    assert ok_verdict.ok, ok_verdict.violations
    bad_verdict = run_post_audit(ad, core_plan2, "你 2026-06-02 的LDL为 9.99 mmol/L。")
    assert not bad_verdict.ok
    assert any(v.startswith("atom_not_allowed:") for v in bad_verdict.violations), (
        bad_verdict.violations
    )

    print("PASS pha_harness_core_adapter_selfcheck")
    print(f"  profile={core.profile} phases={smoke['core_phases']}")
    print(f"  adapter_contract={conf['contract']} fail_closed_codes={list(bad_verdict.violations)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print("FAIL:", exc)
        raise SystemExit(1)
