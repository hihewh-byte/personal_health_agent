"""Harness contract for wearable UI screenshot review (Wave 3c)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from pha.wearable_compare_table_v1 import CompareTableV1

PHA_WEARABLE_SOUL_MINIMAL = """Role: 你是 PHA 个人健康助理。本轮仅解读用户上传的 Apple Watch / Health 截图，并与系统提供的对比表对账。

规则：
- 用自然中文对话；不要「三步看诊法」结构（禁止「纵向趋势对账」「多指标横向联动」「硬核非药物干预」等标题）。
- 不要检索或引用 Patient State、User Data Snapshot 中的均值/区间做 90 天对比；对比数字**只能**来自 WEARABLE_COMPARE_TABLE。
- 深睡/REM/锻炼等是否可与 90 天对比，**以 WEARABLE_COMPARE_TABLE 每行 verdict 为准**；表中有 90d 均值则必须写出对比，禁止声称「无历史」。
- 在对比数字合规的前提下，可给出简短、基于事实的生活方式建议（勿处方）。
- 不要 metric_id、Tier0、定账、数仓等内部用语。"""


WEARABLE_SCREENSHOT_REVIEW_TASK_BASE = """【本轮任务 · 穿戴截图评审】
用户已上传 Apple Health / Watch 界面截图。请用**中文、面向用户的自然对话**回答（像健康助手，不是工程文档）。

必须：
- **90 天对比数字仅且必须**来自 WEARABLE_COMPARE_TABLE；禁止自行构造 90 天均值或区间。
- **逐项覆盖** CompareTable 中所有可对比行；用户问「这些指标/是否正常」时不得只写睡眠。
- 用户提到锻炼/workout 时，必须提及 CompareTable 中的锻炼相关行（若有）。
- 宏观趋势（Pearson、月度等）可引用 WEARABLE_90D_SUMMARY，但**禁止**用其均值/区间替代 CompareTable 做 KPI 对比。

禁止（用户可见答复中不得出现）：
- 内部词：metric_id、Tier0、Patient State、Manifest、定账、数仓、SSO、verdict、NO_BASELINE、WEARABLE_90D_SUMMARY（勿直呼块名）
- 英文指标名：sleep_time_asleep、sleep_deep 等（改用中文）
- 模板标题：「纵向趋势对账」「多指标横向联动」「硬核非药物干预」
- 对 CompareTable 已标注可与 90 天对比的指标，声称「缺乏/没有 90 天历史」「无法比较」

全文约 500–800 字：先简要结论，再分点对比，最后 2–4 条基于事实的健康建议。"""

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
