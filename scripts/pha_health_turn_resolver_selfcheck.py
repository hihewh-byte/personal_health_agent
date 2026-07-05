#!/usr/bin/env python3
"""Stage 3C-α: HealthTurnResolver golden multi-turn cases H1–H4 + H-A."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pha.harness_plan import build_turn_evidence_plan
from pha.health_episodic_focus import HealthSessionFocus, WearableWindow
from pha.health_intent_catalog import profile_recall_forbidden
from pha.health_turn_resolver import (
    focus_from_turn_scope,
    resolve_attachment_qa_mode,
    resolve_health_turn_scope,
)

REF = date(2026, 6, 10)


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def test_h1_wearable_anaphora_window() -> None:
    r1 = resolve_health_turn_scope("HRV 怎么样", reference_date=REF)
    _assert("hrv" in r1.metric_keys, f"H1 R1 metric: {r1}")
    focus = focus_from_turn_scope(
        "h1",
        r1,
        user_message="HRV 怎么样",
        assistant_digest="近90天 HRV 均值约 33ms",
        turns_remaining=8,
    )
    focus.focus_profile = "wearable_only"
    focus.focus_metric = "hrv"
    r2 = resolve_health_turn_scope("那上个月呢", episodic=focus, reference_date=REF)
    _assert(r2.metric_keys == ["hrv"], f"H1 R2 metrics: {r2}")
    _assert(r2.metric_source == "focus", f"H1 R2 metric_source: {r2}")
    _assert(r2.time_source == "explicit", f"H1 R2 time_source: {r2}")
    _assert(r2.wearable_window is not None, "H1 R2 window missing")
    _assert(r2.wearable_window.start == date(2026, 5, 1), r2.wearable_window)
    _assert(r2.wearable_window.end == date(2026, 5, 31), r2.wearable_window)
    print("PASS H1 HRV → 那上个月呢 → focus + May window")


def test_h2_multi_year_ldl() -> None:
    scope = resolve_health_turn_scope(
        "每年的 LDL",
        available_lab_years=[2023, 2024],
        reference_date=REF,
    )
    _assert(scope.lab_years == [2023, 2024], scope)
    _assert(scope.year_source == "uploaded", scope)
    _assert(2022 not in scope.lab_years and 2025 not in scope.lab_years, scope)
    print("PASS H2 每年的 LDL → uploaded 2023-2024")


def test_h3_fast_lane_continue() -> None:
    focus = HealthSessionFocus(
        session_id="h3",
        focus_profile="wearable_only",
        focus_metric="hrv",
        focus_wearable_window=WearableWindow(
            start=date(2026, 3, 12),
            end=REF,
        ),
        turns_remaining=8,
        last_user_message="HRV 怎么样",
        last_assistant_digest="近90天 HRV 摘要",
    )
    scope = resolve_health_turn_scope("继续", episodic=focus, reference_date=REF)
    _assert(scope.metric_source == "focus", scope)
    _assert(scope.focus_profile == "wearable_only", scope)
    _assert(scope.profile_hint == "wearable_only", scope)
    _assert(scope.metric_keys == ["hrv"], scope)
    print("PASS H3 快车道后「继续」→ wearable_only focus")


def test_h4_lab_year_clarify() -> None:
    scope = resolve_health_turn_scope(
        "血脂怎么样",
        available_lab_years=[2023, 2024],
        reference_date=REF,
    )
    _assert(scope.needs_clarification, scope)
    _assert(scope.clarify_kind == "lab_year", scope)
    ids = {c["id"] for c in scope.clarify_choices}
    _assert("2023" in ids and "2024" in ids, scope.clarify_choices)
    print("PASS H4 血脂怎么样 → clarify lab_year")


def test_h5_screenshot_session_beats_lab_clarify() -> None:
    focus = HealthSessionFocus(
        session_id="h5",
        focus_profile="wearable_screenshot_review",
        turns_remaining=8,
        last_user_message="附件截图",
        last_assistant_digest="CompareTable 定账摘要",
    )
    scope = resolve_health_turn_scope(
        "血脂怎么样",
        episodic=focus,
        available_lab_years=[2023, 2024],
        reference_date=REF,
    )
    _assert(not scope.needs_clarification, scope)
    _assert(scope.focus_profile == "wearable_screenshot_review", scope)
    _assert(scope.profile_hint == "wearable_screenshot_review", scope)
    print("PASS H5 截图会话短问「血脂怎么样」→ 续焦，不 lab_year clarify")


def test_h5b_intent_scope_clarify_long_cross_domain() -> None:
    focus = HealthSessionFocus(
        session_id="h5b",
        focus_profile="wearable_screenshot_review",
        turns_remaining=8,
        last_user_message="附件截图",
        last_assistant_digest="CompareTable 定账摘要",
    )
    long_msg = (
        "请帮我看看血脂这个指标，是继续分析刚才上传的截图内容，"
        "还是查看我数据库里存档的化验数据更合适"
    )
    scope = resolve_health_turn_scope(
        long_msg,
        episodic=focus,
        available_lab_years=[2023, 2024],
        reference_date=REF,
    )
    _assert(scope.needs_clarification, scope)
    _assert(scope.clarify_kind == "intent_scope", scope)
    ids = {c["id"] for c in scope.clarify_choices}
    _assert("continue_session" in ids, scope.clarify_choices)
    _assert("2023" in ids and "2024" in ids, scope.clarify_choices)
    print("PASS H5b 长句跨域 → intent_scope clarify（会话 vs 化验年）")


def test_ha1_attachment_recall_forbidden() -> None:
    focus = HealthSessionFocus(
        session_id="ha1",
        focus_profile="attachment_asset_qa",
        focus_summary="磷脂酰丝氨酸 PS 100mg 定账",
        focus_tokens=["PS", "100mg"],
        turns_remaining=3,
        last_user_message="这个标签是什么",
        last_assistant_digest="定账摘要",
    )
    mode = resolve_attachment_qa_mode("为什么有这些帮助", focus)
    _assert(mode in ("followup", "episodic_bridge"), mode)
    plan = build_turn_evidence_plan(
        "为什么有这些帮助",
        attachment_asset_qa=True,
        attachment_qa_mode="initial",
    )
    _assert("RECALL" in plan.forbidden, plan.forbidden)
    _assert(profile_recall_forbidden("attachment_asset_qa"), "catalog recall_forbidden")
    print("PASS H-A1 attachment followup + RECALL forbidden")


def test_ha2_attachment_hrv_bridge() -> None:
    focus = HealthSessionFocus(
        session_id="ha2",
        focus_profile="attachment_asset_qa",
        focus_summary="磷脂酰丝氨酸 PS 100mg",
        turns_remaining=3,
        last_user_message="对我有什么帮助",
        last_assistant_digest="补剂定账",
    )
    mode = resolve_attachment_qa_mode("能提高 HRV 吗", focus)
    _assert(mode == "episodic_bridge", mode)
    plan = build_turn_evidence_plan(
        "能提高 HRV 吗",
        attachment_asset_qa=True,
        attachment_qa_mode="episodic_bridge",
    )
    _assert(plan.profile == "attachment_episodic_bridge", plan.profile)
    _assert("DATA_AVAILABILITY" in plan.slots_tier0, plan.slots_tier0)
    _assert("DOSSIER_LAB" in plan.forbidden, plan.forbidden)
    print("PASS H-A2 attachment + HRV → episodic_bridge + DATA_AVAILABILITY")


def test_ha3_recall_focus_slot() -> None:
    focus = HealthSessionFocus(
        session_id="ha3",
        focus_profile="attachment_asset_qa",
        focus_summary="磷脂酰丝氨酸 PS 100mg；每日睡前",
        focus_tokens=["PS", "100mg", "磷脂酰丝氨酸"],
        turns_remaining=2,
        last_user_message="和他汀一起吃可以吗",
        last_assistant_digest="注意事项摘要",
    )
    scope = resolve_health_turn_scope("和他汀一起吃可以吗", episodic=focus, reference_date=REF)
    _assert(scope.attachment_qa_mode in ("followup", "episodic_bridge"), scope)
    plan = build_turn_evidence_plan(
        "和他汀一起吃可以吗",
        attachment_asset_qa=True,
        attachment_qa_mode=scope.attachment_qa_mode or "followup",
    )
    _assert("RECALL" in plan.forbidden, plan.forbidden)
    _assert("PS" in focus.focus_summary or "100mg" in focus.focus_summary, focus.focus_summary)
    print("PASS H-A3 交互问句 + 定账 tokens 保持 + RECALL forbidden")


def test_turn_scope_report() -> None:
    scope = resolve_health_turn_scope("HRV 怎么样", reference_date=REF)
    report = scope.to_report_dict()
    _assert("metricKeys" in report and report["metricKeys"], report)
    _assert("yearSource" in report, report)
    print("PASS turnScope report dict")


def main() -> int:
    tests = [
        test_h1_wearable_anaphora_window,
        test_h2_multi_year_ldl,
        test_h3_fast_lane_continue,
        test_h4_lab_year_clarify,
        test_h5_screenshot_session_beats_lab_clarify,
        test_h5b_intent_scope_clarify_long_cross_domain,
        test_ha1_attachment_recall_forbidden,
        test_ha2_attachment_hrv_bridge,
        test_ha3_recall_focus_slot,
        test_turn_scope_report,
    ]
    for fn in tests:
        fn()
    print("pha_health_turn_resolver_selfcheck: PASS", len(tests), "cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
