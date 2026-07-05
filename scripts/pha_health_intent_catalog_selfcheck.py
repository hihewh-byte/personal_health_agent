#!/usr/bin/env python3
"""Stage 3C-γ: health_intent_catalog episodic inheritance + attachment R1 routing."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["PHA_HEALTH_INTENT_CATALOG"] = "1"

from pha.health_episodic_focus import HealthSessionFocus
from pha.health_intent_catalog import (
    explicit_profile_shift,
    is_episodic_delta_followup_message,
    is_session_anchor_profile,
    is_weak_episodic_followup,
    profile_allows_active_recall_ledger,
    resolve_inherited_focus_profile,
    should_prefer_attachment_qa_over_wearable,
)
from pha.health_turn_resolver import resolve_health_turn_scope
from pha.wearable_harness import should_use_wearable_screenshot_review


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def test_hg1_supplement_r1_not_wearable() -> None:
    prefer = should_prefer_attachment_qa_over_wearable(
        document_family="supplement",
        user_message="我上传了补剂标签，这是什么？对我有什么帮助？",
        has_parsed_attachment=True,
    )
    _assert(prefer, "supplement R1 should prefer attachment QA")
    wear = should_use_wearable_screenshot_review(
        document_family="supplement",
        has_parsed_attachment=True,
        user_message="我上传了补剂标签，这是什么？对我有什么帮助？",
    )
    _assert(not wear, "supplement R1 must not use wearable_screenshot_review")
    print("PASS H-γ1 supplement R1 → attachment not wearable")


def test_hg2_weak_followup_inherits_wearable() -> None:
    inherited = resolve_inherited_focus_profile(
        "谢谢",
        focus_profile="wearable_only",
    )
    _assert(inherited == "wearable_only", inherited)
    _assert(is_weak_episodic_followup("好的知道了"), "weak close")
    from pha.health_intent_catalog import is_advisory_episodic_followup, is_weak_close_followup

    _assert(is_weak_close_followup("谢谢"), "close token")
    _assert(is_advisory_episodic_followup("还有什么要注意的"), "advisory token")
    _assert(not is_weak_close_followup("还有什么要注意的"), "advisory not close")
    _assert(is_episodic_delta_followup_message("和上周比呢"), "delta token")
    _assert(not is_weak_episodic_followup("和上周比呢"), "delta not weak")
    print("PASS H-γ2 谢谢/好的 → inherit wearable_only")


def test_hg3_no_attachment_revive_on_hrv_pivot() -> None:
    focus = HealthSessionFocus(
        session_id="hg3",
        focus_profile="attachment_asset_qa",
        focus_summary="PS 100mg",
        turns_remaining=3,
        last_user_message="这是什么",
        last_assistant_digest="补剂定账",
    )
    _assert(
        explicit_profile_shift("我最近的 HRV 怎么样", "attachment_asset_qa"),
        "HRV pivot shifts away from attachment",
    )
    scope = resolve_health_turn_scope("我最近的 HRV 怎么样", episodic=focus)
    _assert(scope.metric_keys == ["hrv"], scope)
    print("PASS H-γ3 HRV pivot from attachment focus → explicit hrv scope")


def test_hg4_continue_inherits_attachment() -> None:
    focus = HealthSessionFocus(
        session_id="hg4",
        focus_profile="attachment_episodic_bridge",
        focus_summary="PS label",
        turns_remaining=3,
        last_user_message="能提高哪些指标",
        last_assistant_digest="补剂分析",
    )
    inherited = resolve_inherited_focus_profile("继续", focus_profile=focus.focus_profile)
    _assert(inherited == "attachment_episodic_bridge", inherited)
    print("PASS H-γ4 继续 → inherit attachment_episodic_bridge")


def test_hg5_combined_review_session_anchor() -> None:
    _assert(is_session_anchor_profile("combined_review"), "combined_review anchor")
    inherited = resolve_inherited_focus_profile(
        "继续",
        focus_profile="combined_review",
    )
    _assert(inherited == "combined_review", inherited)
    print("PASS H-γ5 combined_review session anchor + weak inherit")


def test_hg6_recall_ledger_profile_gate() -> None:
    _assert(profile_allows_active_recall_ledger("attachment_asset_qa"), "attachment ledger")
    _assert(profile_allows_active_recall_ledger("wearable_screenshot_review"), "screenshot ledger")
    _assert(not profile_allows_active_recall_ledger("combined_review"), "no combined ledger")
    _assert(not profile_allows_active_recall_ledger("lab_cross_year"), "no lab ledger")
    print("PASS H-γ6 recall ledger allowed only on attachment/screenshot profiles")


def main() -> int:
    test_hg1_supplement_r1_not_wearable()
    test_hg2_weak_followup_inherits_wearable()
    test_hg3_no_attachment_revive_on_hrv_pivot()
    test_hg4_continue_inherits_attachment()
    test_hg5_combined_review_session_anchor()
    test_hg6_recall_ledger_profile_gate()
    print("pha_health_intent_catalog_selfcheck: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
