#!/usr/bin/env python3
"""P0 selfcheck: chat turn FSM phase order + skip_llm evaluation."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pha.chat_turn_fsm import (
    ChatTurnPhase,
    ChatTurnPhaseRecorder,
    plan_precedes_compose,
    validate_phase_transition,
)
from pha.harness_plan import build_turn_evidence_plan


def _selfcheck_compare_table():
    from pha.wearable_compare_table_v1 import CompareRowV1, CompareTableV1

    return CompareTableV1(
        rows=[
            CompareRowV1(
                metric_id="hrv_rmssd_ms",
                row_kind="snapshot_only",
                snapshot_value="34",
                snapshot_unit="ms",
                verdict="snapshot_only",
            ),
            CompareRowV1(
                metric_id="respiratory_rate",
                row_kind="snapshot_only",
                snapshot_value="15",
                snapshot_unit="breaths/min",
                verdict="snapshot_only",
            ),
            CompareRowV1(
                metric_id="workout_count_recent",
                row_kind="snapshot_only",
                snapshot_value="8",
                verdict="snapshot_only",
            ),
        ],
    )


def test_phase_order_guards() -> bool:
    assert validate_phase_transition(None, ChatTurnPhase.INIT)
    assert validate_phase_transition(ChatTurnPhase.INIT, ChatTurnPhase.SESSION)
    assert validate_phase_transition(ChatTurnPhase.PLAN, ChatTurnPhase.COMPOSE)
    assert not validate_phase_transition(ChatTurnPhase.COMPOSE, ChatTurnPhase.PLAN)
    rec = ChatTurnPhaseRecorder()
    for ph in (
        ChatTurnPhase.INIT,
        ChatTurnPhase.SESSION,
        ChatTurnPhase.PLAN,
        ChatTurnPhase.PLAN_PRE_LLM,
        ChatTurnPhase.SKIP_LLM_EVAL,
        ChatTurnPhase.COMPOSE,
        ChatTurnPhase.DONE,
    ):
        rec.enter(ph)
    rec.assert_plan_before_compose()
    assert plan_precedes_compose(rec.phases)
    return True


def test_plan_before_llm_contract() -> bool:
    plan = build_turn_evidence_plan("我最近的 HRV 怎么样？")
    assert plan.profile == "wearable_only"
    assert "NUMERICS_MANIFEST" in plan.slots_tier0
    return True


def test_skip_llm_warehouse_hrv() -> bool:
    from pha.chat_skip_llm import evaluate_skip_llm_path

    plan = build_turn_evidence_plan("我最近的 HRV 怎么样？")
    ev = evaluate_skip_llm_path(
        plan=plan,
        user_id="default",
        msg="我最近的 HRV 怎么样？",
        raw_user_msg="我最近的 HRV 怎么样？",
        prior_user_msg="",
        parsed_payload=None,
        attachment_asset_qa=False,
        wearable_screenshot_review=False,
        qa_mode="none",
        paths_in=[],
        numerics_manifest=None,
        wearable_compare_table_obj=None,
    )
    if not ev.skip_llm and not ev.answer_text:
        print("SKIP skip_llm warehouse hrv (no local warehouse rows)")
        return True
    if not ev.skip_llm or not ev.answer_text:
        print("FAIL skip_llm warehouse hrv empty", ev)
        return False
    if "HRV" not in ev.answer_text and "hrv" not in ev.answer_text.lower():
        print("FAIL skip_llm warehouse hrv content", ev.answer_text[:120])
        return False
    return True


def test_broad_intent_templates() -> bool:
    from pha.wearable_compare_table_v1 import (
        build_exercise_suitability_followup_answer,
        build_health_summary_followup_answer,
    )

    table = _selfcheck_compare_table()
    run = build_exercise_suitability_followup_answer(table, "明天能跑步吗")
    if not run or "跑步" not in run:
        print("FAIL exercise running template", run[:80] if run else "")
        return False
    summ = build_health_summary_followup_answer(table, "总结一下我的健康数据")
    if not summ or "概览" not in summ:
        print("FAIL health summary template", summ[:80] if summ else "")
        return False
    return True


def test_skip_llm_weak_episodic_followup() -> bool:
    from pha.chat_skip_llm import evaluate_skip_llm_path
    from pha.harness_plan import TurnEvidencePlan
    from pha.intent_gates import QuestionType

    table = _selfcheck_compare_table()
    plan = TurnEvidencePlan(
        profile="wearable_screenshot_review",
        slots_tier0=["TASK", "WEARABLE_COMPARE_TABLE"],
        slots_tier1=[],
        forbidden=[],
        tools_allowed=[],
        task_text="test",
        legacy_question_type=QuestionType.WEARABLE,
    )
    parsed = {"wearable_compare_table": table.model_dump(mode="python")}
    for msg, needle in (
        ("谢谢", "不客气"),
        ("还有什么要注意的", "留意"),
        ("好的", "不客气"),
    ):
        ev = evaluate_skip_llm_path(
            plan=plan,
            user_id="default",
            msg=msg,
            raw_user_msg=msg,
            prior_user_msg="",
            parsed_payload=parsed,
            attachment_asset_qa=False,
            wearable_screenshot_review=True,
            qa_mode="none",
            paths_in=[],
            numerics_manifest=None,
            wearable_compare_table_obj=table,
        )
        if not ev.skip_llm or needle not in ev.answer_text:
            print(f"FAIL skip_llm weak episodic {msg!r}", ev.answer_text[:80] if ev.answer_text else "")
            return False
        if "根据您上传的 Apple Watch 截图" in ev.answer_text:
            print(f"FAIL skip_llm weak episodic full table {msg!r}")
            return False
    return True


def test_warehouse_focus_heuristic_skip() -> bool:
    from pha.grounded_answer_composer import is_warehouse_metric_focus_turn
    from pha.harness_plan import plan_allows_heuristic_snapshot, build_turn_evidence_plan

    msg = "我最近的 HRV 怎么样？"
    plan = build_turn_evidence_plan(msg)
    if not is_warehouse_metric_focus_turn(msg):
        print("FAIL is_warehouse_metric_focus_turn")
        return False
    if plan_allows_heuristic_snapshot(plan, user_message=msg):
        print("FAIL heuristic snapshot should be off for warehouse focus")
        return False
    # P2 Stage 3G-followup: colloquial weak warehouse sentences must also take the focus skip
    # (single-metric resolution via declarative schema triggers), not fall through to slow LLM.
    # 4-α.1: use non-affective colloquial cores (fuzzy 睡得好* retired from schema).
    for weak in ("睡眠呢", "走路多吗", "静息心率多少"):
        if not is_warehouse_metric_focus_turn(weak):
            print(f"FAIL warehouse focus colloquial {weak!r}")
            return False
    return True


def test_skip_llm_episodic_delta_before_weak() -> bool:
    from pha.chat_skip_llm import evaluate_skip_llm_path
    from pha.harness_plan import TurnEvidencePlan
    from pha.intent_gates import QuestionType

    table = _selfcheck_compare_table()
    plan = TurnEvidencePlan(
        profile="wearable_screenshot_review",
        slots_tier0=["TASK", "WEARABLE_COMPARE_TABLE"],
        slots_tier1=[],
        forbidden=[],
        tools_allowed=[],
        task_text="test",
        legacy_question_type=QuestionType.WEARABLE,
    )
    parsed = {"wearable_compare_table": table.model_dump(mode="python")}
    ev = evaluate_skip_llm_path(
        plan=plan,
        user_id="default",
        msg="和上周比呢",
        raw_user_msg="和上周比呢",
        prior_user_msg="HRV 怎么样",
        parsed_payload=parsed,
        attachment_asset_qa=False,
        wearable_screenshot_review=True,
        qa_mode="none",
        paths_in=[],
        numerics_manifest=None,
        wearable_compare_table_obj=table,
    )
    if not ev.skip_llm or "HRV" not in ev.answer_text:
        print("FAIL delta before weak", ev.answer_text[:120] if ev.answer_text else "")
        return False
    if "关于您还需留意" in ev.answer_text:
        print("FAIL delta routed to weak caution", ev.answer_text[:80])
        return False
    return True


def test_weak_not_delta() -> bool:
    from pha.health_intent_catalog import is_episodic_delta_followup_message, is_weak_episodic_followup

    if not is_episodic_delta_followup_message("和上周比呢"):
        print("FAIL delta token detect")
        return False
    if is_weak_episodic_followup("和上周比呢"):
        print("FAIL weak should not match delta")
        return False
    if not is_weak_episodic_followup("谢谢"):
        print("FAIL thanks still weak")
        return False
    return True


def main() -> int:
    ok = all(
        [
            test_phase_order_guards(),
            test_plan_before_llm_contract(),
            test_skip_llm_warehouse_hrv(),
            test_skip_llm_weak_episodic_followup(),
            test_skip_llm_episodic_delta_before_weak(),
            test_weak_not_delta(),
            test_warehouse_focus_heuristic_skip(),
            test_broad_intent_templates(),
        ],
    )
    print("pha_chat_turn_fsm_selfcheck:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
