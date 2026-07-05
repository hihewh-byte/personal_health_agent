"""P0 — Deterministic skip-LLM evaluation (testable, Harness-owned)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pha.harness_plan import TurnEvidencePlan
from pha.numerics_manifest import NumericsManifest


@dataclass
class SkipLlmEvaluation:
    skip_llm: bool = False
    answer_text: str = ""
    status_events: List[Dict[str, Any]] = field(default_factory=list)


def _status(message: str) -> Dict[str, Any]:
    return {"event": "status", "message": message}


def evaluate_skip_llm_path(
    *,
    plan: TurnEvidencePlan,
    user_id: str,
    msg: str,
    raw_user_msg: str,
    prior_user_msg: str,
    parsed_payload: Optional[Dict[str, Any]],
    attachment_asset_qa: bool,
    wearable_screenshot_review: bool,
    qa_mode: str,
    paths_in: List[str],
    numerics_manifest: Optional[NumericsManifest],
    wearable_compare_table_obj: Any,
) -> SkipLlmEvaluation:
    """Harness veto path: deterministic answers before LLM compose."""
    out = SkipLlmEvaluation()

    if plan.profile == "wearable_only" and not wearable_screenshot_review:
        from pha.grounded_answer_composer import try_warehouse_metric_focus_skip

        manifest_focus = try_warehouse_metric_focus_skip(
            user_id=user_id,
            profile=plan.profile,
            user_message=msg,
            manifest=numerics_manifest,
        )
        if manifest_focus:
            out.skip_llm = True
            out.answer_text = manifest_focus
            out.status_events.append(_status("单指标追问：已返回数仓聚焦摘要"))
            return out

    if attachment_asset_qa and parsed_payload:
        from pha.attachment_asset_qa import maybe_deterministic_attachment_reply

        det = maybe_deterministic_attachment_reply(
            parsed_payload,
            qa_mode=qa_mode,
            attachment_path_count=len(paths_in),
            raw_user_message=raw_user_msg,
        )
        if det:
            out.skip_llm = True
            out.answer_text = det
            out.status_events.append(
                _status("识别置信度偏低，已返回核对指引"),
            )
            return out

    if not wearable_screenshot_review:
        return out

    from pha.wearable_harness import maybe_deterministic_wearable_reply
    from pha.wearable_compare_table_v1 import (
        build_catalog_followup_focus_answer,
        build_compare_first_upload_answer,
        build_compare_table_correction_summary,
        build_exercise_suitability_followup_answer,
        build_health_summary_followup_answer,
        build_single_metric_focus_answer,
        build_weak_episodic_followup_answer,
        compare_table_from_parsed,
        user_requests_snapshot_correction,
    )

    focus_table = wearable_compare_table_obj
    if focus_table is None and parsed_payload:
        focus_table = compare_table_from_parsed(parsed_payload)
    if focus_table is not None:
        if user_requests_snapshot_correction(raw_user_msg):
            corr = build_compare_table_correction_summary(focus_table, raw_user_msg)
            if corr:
                out.skip_llm = True
                out.answer_text = corr
                out.status_events.append(_status("已根据您的更正返回小结"))
                return out
        if paths_in:
            first = build_compare_first_upload_answer(focus_table, raw_user_msg)
            if first:
                out.skip_llm = True
                out.answer_text = first
                out.status_events.append(
                    _status("已根据本次截图整理读数小结"),
                )
                return out
        from pha.wearable_compare_table_v1 import build_episodic_delta_focus_answer

        delta_ans = build_episodic_delta_focus_answer(
            focus_table,
            raw_user_msg,
            prior_user_message=prior_user_msg,
        )
        if delta_ans:
            out.skip_llm = True
            out.answer_text = delta_ans
            out.status_events.append(
                _status("已为您对比前后读数"),
            )
            return out
        from pha.health_intent_catalog import is_weak_episodic_followup

        if is_weak_episodic_followup(raw_user_msg):
            weak_ans = build_weak_episodic_followup_answer(focus_table, raw_user_msg)
            if weak_ans:
                out.skip_llm = True
                out.answer_text = weak_ans
                out.status_events.append(
                    _status("已返回延伸小结"),
                )
                return out
        focus_ans = build_single_metric_focus_answer(
            focus_table,
            raw_user_msg,
            prior_user_message=prior_user_msg,
        )
        if focus_ans:
            out.skip_llm = True
            out.answer_text = focus_ans
            out.status_events.append(
                _status("已返回该指标的小结"),
            )
            return out
        cat_focus = build_catalog_followup_focus_answer(focus_table, raw_user_msg)
        if cat_focus:
            out.skip_llm = True
            out.answer_text = cat_focus
            out.status_events.append(_status("已返回该指标的小结"))
            return out
        ex_adv = build_exercise_suitability_followup_answer(focus_table, raw_user_msg)
        if ex_adv:
            out.skip_llm = True
            out.answer_text = ex_adv
            out.status_events.append(
                _status("已返回运动建议"),
            )
            return out
        health_sum = build_health_summary_followup_answer(focus_table, raw_user_msg)
        if health_sum:
            out.skip_llm = True
            out.answer_text = health_sum
            out.status_events.append(
                _status("已返回健康概览"),
            )
            return out
        from pha.intent_gates import infer_wearable_metrics
        from pha.grounded_answer_composer import try_warehouse_metric_focus_skip

        if len(infer_wearable_metrics(raw_user_msg)) == 1:
            manifest_focus = try_warehouse_metric_focus_skip(
                user_id=user_id,
                profile=plan.profile,
                user_message=msg,
                manifest=numerics_manifest,
            )
            if manifest_focus:
                out.skip_llm = True
                out.answer_text = manifest_focus
                out.status_events.append(_status("已返回该指标的历史小结"))
                return out

    if parsed_payload:
        det = maybe_deterministic_wearable_reply(
            parsed_payload,
            raw_user_message=raw_user_msg,
        )
        if det:
            out.skip_llm = True
            out.answer_text = det
            out.status_events.append(
                _status("截图读数不足，已返回核对指引"),
            )
    return out


__all__ = ["SkipLlmEvaluation", "evaluate_skip_llm_path"]
