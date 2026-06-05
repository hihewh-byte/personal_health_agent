#!/usr/bin/env python3
"""Stage 3A.2 / 3C selfcheck — attachment QA routing + harness slots."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pha.attachment_asset_qa import (  # noqa: E402
    build_episodic_bridge_task,
    resolve_attachment_qa_mode,
)
from pha.harness_plan import build_turn_evidence_plan  # noqa: E402

TOKENS = ["Phosphatidyl", "Serine", "NOW"]
Q_FOLLOWUP = "还有其他的帮助吗？"
Q_LIPID = "跟我其他的哪些补剂结合能改善血脂？"
Q_METRIC = "能够帮我提高哪些身体指标？"


def main() -> int:
    failed = 0

    if resolve_attachment_qa_mode(
        Q_FOLLOWUP,
        has_parsed_attachment=False,
        session_focus_active=True,
        focus_tokens=TOKENS,
    ) != "episodic_bridge":
        print(
            "FAIL: focus follow-up should be episodic_bridge",
            resolve_attachment_qa_mode(
                Q_FOLLOWUP,
                has_parsed_attachment=False,
                session_focus_active=True,
                focus_tokens=TOKENS,
            ),
        )
        failed += 1

    if resolve_attachment_qa_mode(
        Q_METRIC,
        has_parsed_attachment=False,
        session_focus_active=True,
        focus_tokens=TOKENS,
    ) != "episodic_bridge":
        print("FAIL: metric question should be episodic_bridge")
        failed += 1

    if resolve_attachment_qa_mode(
        Q_LIPID,
        has_parsed_attachment=False,
        session_focus_active=True,
        focus_tokens=TOKENS,
    ) != "lipid_bridge":
        print("FAIL: lipid_bridge")
        failed += 1

    plan_lb = build_turn_evidence_plan(
        "降血脂",
        attachment_asset_qa=True,
        attachment_qa_mode="lipid_bridge",
    )
    if "LDL_AUTHORITY" not in plan_lb.slots_tier0:
        print("FAIL: lipid_bridge needs LDL_AUTHORITY slot")
        failed += 1

    plan_ep = build_turn_evidence_plan(
        Q_METRIC,
        attachment_asset_qa=True,
        attachment_qa_mode="episodic_bridge",
    )
    if plan_ep.profile != "attachment_episodic_bridge":
        print("FAIL: episodic profile", plan_ep.profile)
        failed += 1
    if "DATA_AVAILABILITY" not in plan_ep.slots_tier0:
        print("FAIL: episodic needs DATA_AVAILABILITY")
        failed += 1
    if "NUMERICS_MANIFEST" not in plan_ep.slots_tier0:
        print("FAIL: episodic needs NUMERICS_MANIFEST")
        failed += 1

    narrow = build_episodic_bridge_task(Q_FOLLOWUP)
    if "短句延续" not in narrow:
        print("FAIL: narrow addendum expected for short follow-up")
        failed += 1

    if failed:
        print("lipid_bridge slots:", plan_lb.slots_tier0)
        print("episodic slots:", plan_ep.slots_tier0)
        return 1
    print("OK: stage3a2/3c attachment routing selfcheck")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
