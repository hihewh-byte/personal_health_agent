#!/usr/bin/env python3
"""Stage 3F-δ: Intent Scout shadow goal_class telemetry + zero-adopt status hint."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if str(ROOT) not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["PHA_SHADOW_ROUTING"] = "1"
os.environ["PHA_GOAL_CLASSIFIER"] = "1"

from pha.shadow_routing import build_shadow_status_message, run_shadow_routing


def main() -> int:
    failed = 0
    holistic_msg = "根据各项指标综合评估健康状态"
    payload = run_shadow_routing(
        holistic_msg,
        authoritative_profile="lifestyle",
        authoritative_catalog_ids=["lab_lipid_panel"],
        user_id="default",
    )
    if payload.get("goal_class") != "holistic_assessment":
        print("FAIL: expected holistic goal_class", payload.get("goal_class"))
        failed += 1
    domains = payload.get("suggested_domains") or []
    if domains != ["lab", "wearable"]:
        print("FAIL: expected suggested_domains lab+wearable", domains)
        failed += 1
    if payload.get("authoritative_profile") != "lifestyle":
        print("FAIL: shadow must not rewrite authoritative profile")
        failed += 1

    hint = build_shadow_status_message(
        {
            "enabled": True,
            "sampled": True,
            "telemetry_priority": "high",
            "authoritative_profile": "lifestyle",
            "goal_class": "holistic_assessment",
            "shadow_profile_hint": "combined_review",
            "shadow_confidence": 0.9,
            "disagreement_class": None,
        },
    )
    if "综合评估" not in hint:
        print("FAIL: holistic lifestyle hint missing", repr(hint))
        failed += 1

    silent = build_shadow_status_message(
        {
            "enabled": True,
            "sampled": True,
            "telemetry_priority": "low",
            "authoritative_profile": "lifestyle",
            "goal_class": "holistic_assessment",
            "shadow_confidence": 0.2,
        },
    )
    if silent:
        print("FAIL: low priority should not emit status", repr(silent))
        failed += 1

    if failed:
        return 1
    print("OK stage3f-delta shadow selfcheck")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
