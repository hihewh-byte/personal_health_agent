"""Chat intent gates — wearable vs lab dossier vs casual (v2.2.1)."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Dict, List

from pha.date_range_parser import (
    default_wearable_window,
    extract_snapshot_span_from_text,
    is_meta_date_range_question,
    parse_user_date_range,
)
from pha.medical_storage import list_distinct_report_dates, query_ldl_metrics_for_calendar_years
from pha.temporal_router import TemporalIntent, infer_dynamic_health_tool_range, parse_temporal_intent

_CASUAL_RE = re.compile(
    r"^(你好|您好|hi|hello|谢谢|感谢|收到|知道了|好的|ok|okay|在吗)[\s!！。.?？~]*$",
    re.I,
)

_LAB_MARKERS_RE = re.compile(
    r"ldl|hdl|血脂|胆固醇|甘油三酯|化验|体检|肝功能|肾功能|低密度|高密度|血糖|hba1c",
    re.I,
)

_CLINICAL_LAB_STRONG_RE = re.compile(
    r"ldl|hdl|血脂|胆固醇|甘油三酯|化验|体检|检验报告|肝功能|肾功能|低密度|高密度|"
    r"空腹血糖|糖化|hba1c",
    re.I,
)

_DIETARY_GLUCOSE_RE = re.compile(
    r"稳定.*血糖|夜间血糖|控糖|血糖稳定|低血糖|高血糖|血糖波动|皮质醇",
    re.I,
)

_LAB_DOSSIER_RE = re.compile(
    r"对比|比较|历年|不同年|跨年|历史|各年|年度|记录|查询|找出|所有|多年",
    re.I,
)

_WEARABLE_RE = re.compile(
    r"睡眠|步数|hrv|心率|静息|穿戴|运动|活动|活动消耗|activity|waso|清醒|苹果健康|"
    r"export\.zip|步行|跑步|卡路里|kcal|rmssd|训练量|运动量|血氧|spo2|呼吸率|vo2|体温|腕温",
    re.I,
)

_WEARABLE_WINDOW_RE = re.compile(r"90\s*天|近\s*90|三个月|3\s*个月|半年|一年|365", re.I)

_ATTACHMENT_RECALL_RE = re.compile(
    r"图片|附件|上传的|截图|刚才|那张|这些图|发的图",
    re.I,
)
_ATTACHMENT_RECALL_ASK_RE = re.compile(
    r"是什么|什么信息|分析|解读|说了什么|看到什么|信息是什么",
    re.I,
)


class QuestionType(str, Enum):
    CASUAL = "casual"
    WEARABLE = "wearable"
    LAB = "lab"
    LIFESTYLE = "lifestyle"
    COMBINED = "combined"


def user_message_has_clinical_lab_intent(user_message: str) -> bool:
    """Clinical lab query — excludes dietary phrases like 稳定夜间血糖."""
    text = (user_message or "").strip()
    if not text:
        return False
    if _CLINICAL_LAB_STRONG_RE.search(text):
        return True
    if re.search(r"血糖", text, re.I):
        if _DIETARY_GLUCOSE_RE.search(text) and not re.search(
            r"检验|化验|报告|mmol|指标",
            text,
            re.I,
        ):
            return False
        return bool(re.search(r"检验|化验|报告|血脂|胆固醇", text, re.I))
    return False


def resolve_schema_intent(user_message: str) -> "IntentRouteResult":
    from pha.schema_intent_router import IntentRouteResult
    from pha.universal_catalog_manager import get_catalog_manager

    return get_catalog_manager().resolve_intent(user_message)


def user_message_is_combined_health_review(user_message: str) -> bool:
    """Lab + (wearable and/or supplements) in one turn — v2.2.4 / A+ router."""
    return resolve_schema_intent(user_message).profile == "combined_review"


def classify_question_type(user_message: str) -> QuestionType:
    route = resolve_schema_intent(user_message)
    mapping = {
        "casual": QuestionType.CASUAL,
        "combined_review": QuestionType.COMBINED,
        "lab_cross_year": QuestionType.LAB,
        "wearable_only": QuestionType.WEARABLE,
        "supplement_manifest": QuestionType.LIFESTYLE,
        "attachment_asset_qa": QuestionType.LIFESTYLE,
        "lifestyle": QuestionType.LIFESTYLE,
    }
    return mapping.get(route.profile, QuestionType.LIFESTYLE)


def user_message_is_casual(user_message: str) -> bool:
    text = (user_message or "").strip()
    if not text or len(text) > 40:
        return False
    return bool(_CASUAL_RE.match(text))


def user_message_needs_wearable_query(user_message: str) -> bool:
    text = (user_message or "").strip()
    if not text or user_message_is_casual(text):
        return False
    if _WEARABLE_RE.search(text):
        return True
    if _WEARABLE_WINDOW_RE.search(text) and not _LAB_MARKERS_RE.search(text):
        return False
    if _WEARABLE_WINDOW_RE.search(text) and _WEARABLE_RE.search(text):
        return True
    return False


def user_message_needs_attachment_recall(user_message: str) -> bool:
    """Follow-up about a prior upload without re-attaching files."""
    text = (user_message or "").strip()
    if not text or user_message_is_casual(text):
        return False
    return bool(
        _ATTACHMENT_RECALL_RE.search(text) and _ATTACHMENT_RECALL_ASK_RE.search(text),
    )


def user_message_needs_lab_dossier(user_message: str) -> bool:
    text = (user_message or "").strip()
    if not text or user_message_is_casual(text):
        return False
    if not _LAB_MARKERS_RE.search(text):
        return False
    if _LAB_DOSSIER_RE.search(text):
        return True
    if re.search(r"20\d{2}", text) and re.search(r"对比|比较|ldl|血脂", text, re.I):
        return True
    intent = parse_temporal_intent(text)
    return bool(intent.explicit_years) and bool(intent.compare_years)


def user_message_needs_health_query(user_message: str) -> bool:
    return user_message_needs_wearable_query(user_message) or user_message_needs_lab_dossier(
        user_message,
    )


def should_show_lab_pipeline_audit(user_message: str, intent: TemporalIntent) -> bool:
    if classify_question_type(user_message) not in (QuestionType.LAB, QuestionType.COMBINED):
        return False
    return bool(intent.explicit_years)


def should_inject_wearable_snapshot(user_message: str, *, is_temporal_dynamic: bool) -> bool:
    from pha.harness_plan import build_turn_evidence_plan, plan_allows_heuristic_snapshot

    plan = build_turn_evidence_plan(user_message, is_temporal_dynamic=is_temporal_dynamic)
    if not plan_allows_heuristic_snapshot(plan, user_message=user_message):
        return False
    if user_message_is_casual(user_message):
        return False
    if user_message_is_combined_health_review(user_message):
        return False
    if classify_question_type(user_message) == QuestionType.COMBINED:
        return False
    if user_message_needs_lab_dossier(user_message):
        return False
    if not user_message_needs_wearable_query(user_message):
        return False
    if parse_user_date_range(user_message):
        return True
    if is_temporal_dynamic:
        return False
    return True


def infer_wearable_metrics(user_message: str) -> List[str]:
    """Schema-driven (P1.6 DCH); see ``wearable_bundle.schema.json`` trigger_keywords."""
    from pha.universal_catalog_manager import get_catalog_manager

    return get_catalog_manager().infer_wearable_metrics(user_message)


def resolve_wearable_tool_args(
    user_message: str,
    *,
    history_text: str = "",
) -> Dict[str, Any]:
    explicit = parse_user_date_range(user_message)
    if not explicit and is_meta_date_range_question(user_message) and history_text:
        explicit = extract_snapshot_span_from_text(history_text)
    if explicit:
        window = explicit
    else:
        intent = parse_temporal_intent(user_message)
        if intent.has_explicit_years and user_message_needs_wearable_query(user_message):
            start, end = infer_dynamic_health_tool_range(intent)
            from pha.date_range_parser import ParsedDateRange

            window = ParsedDateRange(start=start, end=end)
        else:
            window = default_wearable_window(user_message)
    return {
        "start_date": window.start.isoformat(),
        "end_date": window.end.isoformat(),
        "metrics": infer_wearable_metrics(user_message),
    }


def should_suppress_assistant_history(user_message: str) -> bool:
    text = user_message or ""
    if user_message_is_combined_health_review(text):
        return True
    if classify_question_type(text) == QuestionType.COMBINED:
        return True
    if user_message_needs_lab_dossier(text):
        return True
    if _LAB_MARKERS_RE.search(text) and _LAB_DOSSIER_RE.search(text):
        return True
    return bool(re.search(r"20\d{2}", text)) and bool(
        re.search(r"ldl|低密度|血脂|对比|比较", text, re.I),
    )


def should_strip_polluted_assistant_history(user_message: str) -> bool:
    """Drop prior assistant turns that embed heuristic User Data Snapshot."""
    if should_suppress_assistant_history(user_message):
        return True
    return classify_question_type(user_message) in (QuestionType.LAB, QuestionType.COMBINED)


def resolve_ldl_authority_years(
    user_id: str,
    user_message: str,
    intent: TemporalIntent,
) -> List[int]:
    if classify_question_type(user_message) not in (QuestionType.LAB, QuestionType.COMBINED):
        if not re.search(r"ldl|低密度脂蛋白", user_message or "", re.I):
            return []
    years = list(intent.explicit_years or [])
    if years:
        return sorted(set(years), reverse=True)
    if not user_message_needs_lab_dossier(user_message) and not re.search(
        r"ldl|低密度脂蛋白",
        user_message or "",
        re.I,
    ):
        return []
    uid = (user_id or "default").strip() or "default"
    report_days = list_distinct_report_dates(uid, limit=16)
    candidate_years = sorted({d.year for d in report_days}, reverse=True)
    if not candidate_years:
        return []
    rows = query_ldl_metrics_for_calendar_years(uid, candidate_years, security_inspect=False)
    with_ldl = sorted({r.report_date.year for r in rows}, reverse=True)
    return with_ldl or candidate_years[:6]
