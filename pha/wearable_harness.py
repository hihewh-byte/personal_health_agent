"""Harness contract for wearable UI screenshot review (Wave 3c)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from pha.wearable_compare_table_v1 import CompareTableV1

PHA_WEARABLE_SOUL_MINIMAL = """Role: You are PHA, a personal health assistant. This turn only interprets the user's Apple Watch / Health screenshot against the injected compare table.

Rules:
- Use a natural conversational tone (language per RESPONSE LANGUAGE directive); do not use the three-step clinical review headings (no "Trend review / Cross-metric linkage / Intervention protocol" template titles).
- Do not pull 90-day means/ranges from Patient State or User Data Snapshot; comparison numbers must come only from WEARABLE_COMPARE_TABLE.
- Whether deep sleep/REM/workout can be compared to 90d is determined by each row's verdict in WEARABLE_COMPARE_TABLE; if 90d mean exists, state the comparison — never claim "no history".
- After numeric compliance, you may give brief lifestyle suggestions grounded in facts (no prescriptions).
- Do not use internal terms: metric_id, Tier0, ledger, warehouse, SSO, etc."""


WEARABLE_SCREENSHOT_REVIEW_TASK_BASE = """【Turn task · Wearable screenshot review】
The user uploaded Apple Health / Watch screenshots. Answer in natural conversational prose (language per RESPONSE LANGUAGE directive), like a health coach — not an engineering doc.

Must:
- **90-day comparison numbers only** from WEARABLE_COMPARE_TABLE; never invent 90d means or ranges.
- **Cover every comparable row** in CompareTable; when the user asks "these metrics / are they normal", do not discuss sleep only.
- If the user mentions workout/exercise, cover workout-related CompareTable rows when present.
- Macro trends (Pearson, monthly, etc.) may cite WEARABLE_90D_SUMMARY, but **never** substitute its means/ranges for CompareTable KPI comparisons.

Forbidden in user-visible text:
- Internal terms: metric_id, Tier0, Patient State, Manifest, ledger, warehouse, SSO, verdict, NO_BASELINE, WEARABLE_90D_SUMMARY (do not name blocks)
- Raw snake_case metric ids (sleep_time_asleep, sleep_deep, …) — use human-readable labels from the compare table / evidence
- Template titles: three-step clinical review section names in any language
- Claiming "no 90-day history" for metrics CompareTable marks as comparable

About 500–800 words: brief conclusion, point-by-point comparison, then 2–4 fact-based lifestyle tips."""

# 兼容 harness_plan 默认引用
WEARABLE_SCREENSHOT_REVIEW_TASK = WEARABLE_SCREENSHOT_REVIEW_TASK_BASE

_METRIC_LABEL = {
    "sleep_time_asleep": "睡眠总时长",
    "sleep_deep": "深睡",
    "sleep_rem": "REM",
    "hrv_rmssd_ms": "HRV",
    "resting_heart_rate_bpm": "静息心率",
    "spo2_percent": "血氧",
    "respiratory_rate": "呼吸率",
    "workout_heart_rate_range_bpm": "锻炼心率范围",
    "workout_count_recent": "近期锻炼次数",
}


def build_wearable_screenshot_review_task(
    table: Optional["CompareTableV1"] = None,
) -> str:
    """CompareTable-aware TASK（Wave 3d-post-e2e · δ-ux）。"""
    if table is None or not table.rows:
        return WEARABLE_SCREENSHOT_REVIEW_TASK_BASE

    comparable: List[str] = []
    snapshot_only: List[str] = []
    for row in table.rows:
        label = _METRIC_LABEL.get(row.metric_id, row.metric_id)
        if row.row_kind == "comparable_90d" and (row.baseline_90d_value or "").strip() not in (
            "",
            "NO_BASELINE",
        ):
            comparable.append(label)
        elif row.row_kind == "snapshot_only" or (row.baseline_90d_value or "") == "NO_BASELINE":
            snapshot_only.append(label)

    lines = [WEARABLE_SCREENSHOT_REVIEW_TASK_BASE, "", "【本轮 CompareTable 裁定 · 必须遵守】"]
    if comparable:
        lines.append(
            "- **可与过去约 90 天对比**（须写截图值 + 表内均值/区间/结论）："
            + "、".join(comparable),
        )
    if snapshot_only:
        lines.append(
            "- **仅本次截图、无个人 90 天基线**（只报截图值，说明无法与 90 天对比）："
            + "、".join(snapshot_only),
        )
    if not snapshot_only:
        lines.append(
            "- 深睡/REM 若出现在上表「可对比」列表中，**必须**写出 90 天对比，禁止写「无历史」。",
        )
    return "\n".join(lines)

_COMPARE_USER_RE = re.compile(
    r"正常|好不好|对比|比较|和过去|相比|趋势|是不是都",
    re.I,
)


def should_use_wearable_screenshot_review(
    *,
    document_family: str,
    has_parsed_attachment: bool,
    user_message: str,
) -> bool:
    if not has_parsed_attachment:
        return False
    from pha.wearable_compare_table_v1 import user_requests_snapshot_correction
    from pha.wearable_snapshot_v1 import user_requests_wearable_snapshot_remerge

    if user_requests_wearable_snapshot_remerge(user_message) or user_requests_snapshot_correction(
        user_message,
    ):
        fam_early = (document_family or "").strip().lower()
        if fam_early in ("wearable", "apple_watch"):
            return True
    from pha.health_intent_catalog import (
        health_intent_catalog_enabled,
        should_prefer_attachment_qa_over_wearable,
    )

    if health_intent_catalog_enabled() and should_prefer_attachment_qa_over_wearable(
        document_family=document_family,
        user_message=user_message,
        has_parsed_attachment=has_parsed_attachment,
    ):
        return False
    fam = (document_family or "").strip().lower()
    if fam == "wearable":
        return True
    from pha.intent_gates import (
        user_message_needs_attachment_recall,
        user_message_needs_wearable_query,
    )

    if user_message_needs_wearable_query(user_message):
        if health_intent_catalog_enabled() and should_prefer_attachment_qa_over_wearable(
            document_family=document_family,
            user_message=user_message,
            has_parsed_attachment=has_parsed_attachment,
        ):
            return False
        return True
    return user_message_needs_attachment_recall(user_message)


def is_wearable_screenshot_profile(profile: str) -> bool:
    return (profile or "").strip() == "wearable_screenshot_review"


def user_requests_wearable_comparison(user_message: str) -> bool:
    return bool(_COMPARE_USER_RE.search(user_message or ""))


def maybe_deterministic_wearable_reply(
    parsed: dict,
    *,
    raw_user_message: str = "",
) -> str:
    """
    When screenshot ledger has no structured KPIs, refuse to invoke L3 for
    comparison/analysis turns (prevents HR/HRV/step confabulation).
    """
    from pha.perception_family import (
        WEARABLE_FAMILY,
        family_from_parsed,
        ocr_suggests_wearable_ui,
    )

    if not parsed:
        return ""
    fam = family_from_parsed(parsed)
    ocr = str(parsed.get("ocr_text") or "")
    if fam != WEARABLE_FAMILY and not ocr_suggests_wearable_ui(ocr):
        return ""

    metrics = parsed.get("wearable_metrics") or []
    if metrics:
        return ""

    conf = str(parsed.get("parse_confidence") or "").strip().lower()
    reasons = list(parsed.get("reject_reasons") or [])
    wants_compare = user_requests_wearable_comparison(raw_user_message)
    if conf != "low" and not reasons and not wants_compare:
        return ""

    parts = [
        "我这边**没能从 Apple Watch / Health 截图中识别出可靠指标**（OCR 或合并置信度偏低），"
        "因此**不会**编造静息心率、HRV、步数或睡眠时长。",
    ]
    if "merge_family_conflict" in reasons:
        parts.append(
            "\n\n**可能原因**：多张截图的业务族识别不一致；请确认均为 Health 指标页后重试。"
        )
    elif int(parsed.get("attachment_count") or 0) >= 2 and not ocr.strip():
        parts.append(
            "\n\n**可能原因**：部分图片 OCR 为空；请换更清晰截图或稍等解析完成后再发送。"
        )
    parts.append(
        "\n\n**建议**：可结合系统已注入的「近 90 日穿戴摘要」作答；"
        "若需对比截图中的数值，请重新上传完整截图并等待解析完成。"
    )
    return "".join(parts)


__all__ = [
    "PHA_WEARABLE_SOUL_MINIMAL",
    "WEARABLE_SCREENSHOT_REVIEW_TASK",
    "WEARABLE_SCREENSHOT_REVIEW_TASK_BASE",
    "build_wearable_screenshot_review_task",
    "is_wearable_screenshot_profile",
    "maybe_deterministic_wearable_reply",
    "should_use_wearable_screenshot_review",
    "user_requests_wearable_comparison",
]
