"""P0 — Deterministic skip-LLM evaluation (testable, Harness-owned)."""

from __future__ import annotations

import re
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
    response_locale: Optional[str] = None,
) -> SkipLlmEvaluation:
    """Harness veto path: deterministic answers before LLM compose."""
    out = SkipLlmEvaluation()

    from pha.health_intent_catalog import is_weak_close_followup
    from pha.response_language import (
        is_locale_preference_only,
        normalize_response_locale,
        resolve_response_locale,
    )

    loc = normalize_response_locale(response_locale) or resolve_response_locale(
        raw_user_msg,
        request_locale=response_locale,
    )
    # Any profile: pure close tokens should not re-enter LLM (EN/ZH ack only).
    if is_weak_close_followup(raw_user_msg) and not paths_in:
        out.skip_llm = True
        out.answer_text = (
            "You're welcome. Ask anytime if you want another look at your records."
            if loc == "en"
            else "不客气。若还想查看其他记录，随时告诉我。"
        )
        out.status_events.append(_status("弱收尾：已返回致谢"))
        return out

    # Locale-only preference ("后面都用中文") — acknowledge; do not dump labs.
    if is_locale_preference_only(raw_user_msg) and not paths_in:
        out.skip_llm = True
        out.answer_text = (
            "Got it — I'll reply in English from here. Ask a specific metric or upload when ready."
            if loc == "en"
            else "好的，后面我会用简体中文回复。需要看哪项指标或附件，直接说即可。"
        )
        out.status_events.append(_status("语种偏好：已确认，未拉取化验"))
        return out

    # Boundary confirm ("这不是医疗建议对吧？") — fixed disclaimer, no diagnosis essay.
    _boundary = re.compile(
        r"不是医疗建议|不构成诊断|非诊断|not medical advice|not a (?:medical )?diagnosis|"
        r"educational(?:\s+only)?|keep it educational",
        re.I,
    )
    if (
        _boundary.search(raw_user_msg or "")
        and len((raw_user_msg or "").strip()) <= 80
        and not paths_in
    ):
        out.skip_llm = True
        out.answer_text = (
            "Correct — this is educational wellness context only, not a medical diagnosis "
            "or treatment plan. For persistent symptoms or decisions, ask a clinician."
            if loc == "en"
            else "对，这里是健康教育参考，不构成医疗诊断或治疗方案。若有持续不适或需决策，请咨询医生。"
        )
        out.status_events.append(_status("边界确认：已返回非诊断声明"))
        return out

    if plan.profile == "wearable_only" and not wearable_screenshot_review:
        from pha.grounded_answer_composer import try_warehouse_metric_focus_skip

        manifest_focus = try_warehouse_metric_focus_skip(
            user_id=user_id,
            profile=plan.profile,
            user_message=msg,
            manifest=numerics_manifest,
            response_locale=response_locale,
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
            corr = build_compare_table_correction_summary(
                focus_table,
                raw_user_msg,
                locale=response_locale,
            )
            if corr:
                out.skip_llm = True
                out.answer_text = corr
                out.status_events.append(_status("已根据您的更正返回小结"))
                return out
        if paths_in:
            first = build_compare_first_upload_answer(
                focus_table,
                raw_user_msg,
                locale=response_locale,
            )
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
            locale=response_locale,
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
            weak_ans = build_weak_episodic_followup_answer(
                focus_table,
                raw_user_msg,
                locale=response_locale,
            )
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
            locale=response_locale,
        )
        if focus_ans:
            out.skip_llm = True
            out.answer_text = focus_ans
            out.status_events.append(
                _status("已返回该指标的小结"),
            )
            return out
        cat_focus = build_catalog_followup_focus_answer(
            focus_table,
            raw_user_msg,
            locale=response_locale,
        )
        if cat_focus:
            out.skip_llm = True
            out.answer_text = cat_focus
            out.status_events.append(_status("已返回该指标的小结"))
            return out
        ex_adv = build_exercise_suitability_followup_answer(
            focus_table,
            raw_user_msg,
            locale=response_locale,
        )
        if ex_adv:
            out.skip_llm = True
            out.answer_text = ex_adv
            out.status_events.append(
                _status("已返回运动建议"),
            )
            return out
        health_sum = build_health_summary_followup_answer(
            focus_table,
            raw_user_msg,
            locale=response_locale,
        )
        if health_sum:
            out.skip_llm = True
            out.answer_text = health_sum
            out.status_events.append(
                _status("已返回健康概览"),
            )
            return out
        from pha.intent_gates import infer_wearable_metrics
        from pha.grounded_answer_composer import try_warehouse_metric_focus_skip
        from pha.wearable_compare_table_v1 import infer_single_metric_focus_ids

        if len(infer_wearable_metrics(raw_user_msg)) == 1 or infer_single_metric_focus_ids(
            raw_user_msg,
        ):
            manifest_focus = try_warehouse_metric_focus_skip(
                user_id=user_id,
                profile=plan.profile,
                user_message=msg,
                manifest=numerics_manifest,
                response_locale=response_locale,
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
