#!/usr/bin/env python3
"""P2 selfcheck: harness sub-agent protocol guards."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pha.harness_plan import build_turn_evidence_plan  # noqa: E402
from pha.harness_subagent_protocol import (  # noqa: E402
    validate_numerics_audit_required,
    validate_shadow_zero_adopt,
    validate_sse_emitter,
    validate_tool_invocation,
)


def main() -> int:
    failed = 0

    wear_plan = build_turn_evidence_plan("我最近的 HRV 怎么样？")
    chk = validate_tool_invocation(wear_plan, "fetch_evidence_by_id")
    if chk.ok:
        print("FAIL: wearable_only should block fetch_evidence_by_id")
        failed += 1

    combined = build_turn_evidence_plan("根据血脂和HRV分析补剂方案")
    chk2 = validate_tool_invocation(combined, "fetch_evidence_by_id", catalog_mode=True)
    if not chk2.ok:
        print("FAIL: combined should allow fetch_evidence_by_id", chk2.violations)
        failed += 1

    chk3 = validate_tool_invocation(combined, "get_health_data", catalog_mode=True)
    if chk3.ok:
        print("FAIL: catalog mode should block get_health_data")
        failed += 1

    chk4 = validate_sse_emitter("subagent", "done", phase="catalog_fetch")
    if chk4.ok:
        print("FAIL: subagent should not emit done")
        failed += 1

    chk5 = validate_sse_emitter("subagent", "status", phase="catalog_fetch")
    if not chk5.ok:
        print("FAIL: subagent should emit status", chk5.violations)
        failed += 1

    chk6 = validate_shadow_zero_adopt(
        shadow_payload={"shadow_profile_hint": "wearable_only", "enabled": True},
        authoritative_profile="combined_review",
        answer_changed=False,
    )
    if not chk6.ok:
        print("FAIL: shadow zero-adopt telemetry", chk6.violations)
        failed += 1

    chk7 = validate_shadow_zero_adopt(
        shadow_payload={"shadow_profile_hint": "wearable_only"},
        authoritative_profile="combined_review",
        answer_changed=True,
    )
    if chk7.ok:
        print("FAIL: shadow must not adopt answer changes")
        failed += 1

    chk8 = validate_numerics_audit_required(
        combined,
        skip_llm=False,
        numerics_manifest_present=True,
        compare_table_present=False,
    )
    if not chk8.ok:
        print("FAIL: combined with manifest should pass", chk8.violations)
        failed += 1

    if failed:
        print(f"\nFAIL {failed}")
        return 1
    print("OK harness subagent protocol selfcheck")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
