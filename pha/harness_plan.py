"""TurnEvidencePlan — v2.2.5 Phase 1 harness contract (三车道 + 矩阵)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from pha.health_data import effective_query_reference_date, get_health_data
from pha.intent_gates import (
    QuestionType,
    classify_question_type,
    infer_wearable_metrics,
    resolve_schema_intent,
    user_message_needs_lab_dossier,
)
from pha.date_range_parser import default_wearable_window
from pha.evidence_catalog import (
    catalog_mode_enabled,
    combined_catalog_task_text,
)
from pha.metadata_catalog import (
    metadata_catalog_force_tier0,
    should_inject_metadata_catalog,
)


def _append_metadata_catalog_slots(
    profile: str,
    *,
    slots_tier0: List[str],
    slots_tier1: List[str],
) -> tuple[List[str], List[str]]:
    """Inject METADATA_CATALOG per Stage 2C (default Tier1)."""
    if not should_inject_metadata_catalog(profile):
        return slots_tier0, slots_tier1
    t0 = list(slots_tier0)
    t1 = list(slots_tier1)
    if metadata_catalog_force_tier0():
        if "METADATA_CATALOG" not in t0:
            t0.append("METADATA_CATALOG")
    elif "METADATA_CATALOG" not in t1:
        t1 = ["METADATA_CATALOG"] + t1
    return t0, t1

PHA_HARNESS_TIER0_MAX_CHARS = int(os.environ.get("PHA_HARNESS_TIER0_MAX_CHARS", "4500"))


@dataclass(frozen=True)
class TurnEvidencePlan:
    profile: str
    slots_tier0: List[str]
    slots_tier1: List[str]
    forbidden: List[str]
    tools_allowed: List[str]
    task_text: str
    legacy_question_type: QuestionType
    preserve_raw_user: bool = True

    @property
    def all_slots(self) -> List[str]:
        return list(self.slots_tier0) + list(self.slots_tier1)


def build_turn_evidence_plan(
    user_message: str,
    *,
    question_type: Optional[QuestionType] = None,
    is_temporal_dynamic: bool = False,
    attachment_asset_qa: bool = False,
    attachment_qa_mode: str = "initial",
    wearable_screenshot_review: bool = False,
) -> TurnEvidencePlan:
    msg = (user_message or "").strip()
    if wearable_screenshot_review:
        from pha.wearable_harness import WEARABLE_SCREENSHOT_REVIEW_TASK

        return TurnEvidencePlan(
            profile="wearable_screenshot_review",
            slots_tier0=[
                "MASTER_ANCHOR",
                "WEARABLE_SNAPSHOT",
                "WEARABLE_COMPARE_TABLE",
                "WEARABLE_90D_SUMMARY",
                "TASK",
            ],
            slots_tier1=[],
            forbidden=[
                "USER_SNAPSHOT",
                "ATTACHMENT_LABEL",
                "GET_HEALTH_DATA",
                "GET_TEMPORAL_HISTORY_DOSSIER",
                "DOSSIER_CLINICAL_COMPACT",
                "DOSSIER_LAB",
                "EVIDENCE_CATALOG",
                "METADATA_CATALOG",
                "SUPPLEMENT_BG",
                "LDL_AUTHORITY",
                "NUMERICS_MANIFEST",
                "fetch_evidence_by_id",
                "PATIENT_STATE_WEARABLE",
                "PATIENT_STATE_LAB",
            ],
            tools_allowed=[],
            task_text=WEARABLE_SCREENSHOT_REVIEW_TASK,
            legacy_question_type=QuestionType.WEARABLE,
        )

    if attachment_asset_qa:
        from pha.attachment_asset_qa import (
            ATTACHMENT_ASSET_QA_TASK,
            ATTACHMENT_LIPID_BRIDGE_TASK,
            build_episodic_bridge_task,
        )

        mode = (attachment_qa_mode or "initial").strip()
        if mode == "episodic_bridge":
            task = build_episodic_bridge_task(msg)
            slots_t0 = [
                "MASTER_ANCHOR",
                "ATTACHMENT_LABEL",
                "DATA_AVAILABILITY",
                "TASK",
                "NUMERICS_MANIFEST",
                "WEARABLE_90D_SUMMARY",
                "SUPPLEMENT_BG",
            ]
            forbidden_ldl = False
        elif mode == "lipid_bridge":
            task = ATTACHMENT_LIPID_BRIDGE_TASK
            slots_t0 = [
                "MASTER_ANCHOR",
                "ATTACHMENT_LABEL",
                "TASK",
                "SUPPLEMENT_BG",
                "LDL_AUTHORITY",
            ]
            forbidden_ldl = False
        else:
            task = ATTACHMENT_ASSET_QA_TASK
            slots_t0 = ["MASTER_ANCHOR", "ATTACHMENT_LABEL", "TASK", "SUPPLEMENT_BG"]
            from pha.attachment_asset_qa import attachment_evidence_scope_enabled

            if attachment_evidence_scope_enabled():
                slots_t0 = [
                    "MASTER_ANCHOR",
                    "ATTACHMENT_LABEL",
                    "DATA_AVAILABILITY",
                    "TASK",
                    "SUPPLEMENT_BG",
                ]
            forbidden_ldl = True

        forbidden = [
            "USER_SNAPSHOT",
            "GET_HEALTH_DATA",
            "GET_TEMPORAL_HISTORY_DOSSIER",
            "DOSSIER_CLINICAL_COMPACT",
            "DOSSIER_LAB",
            "EVIDENCE_CATALOG",
            "METADATA_CATALOG",
            "RECALL",
            "fetch_evidence_by_id",
        ]
        if mode != "episodic_bridge":
            forbidden.extend(
                [
                    "WEARABLE_90D_SUMMARY",
                    "NUMERICS_MANIFEST",
                    "PATIENT_STATE_LAB",
                    "PATIENT_STATE_WEARABLE",
                ],
            )
        if forbidden_ldl:
            forbidden.append("LDL_AUTHORITY")

        profile_name = (
            "attachment_episodic_bridge" if mode == "episodic_bridge" else "attachment_asset_qa"
        )
        slots_t1 = (
            ["PATIENT_STATE_LAB", "PATIENT_STATE_WEARABLE"]
            if mode == "episodic_bridge"
            else []
        )

        return TurnEvidencePlan(
            profile=profile_name,
            slots_tier0=slots_t0,
            slots_tier1=slots_t1,
            forbidden=forbidden,
            tools_allowed=[],
            task_text=task,
            legacy_question_type=QuestionType.LIFESTYLE,
        )

    route = resolve_schema_intent(msg)
    qtype = question_type or classify_question_type(msg)

    if route.profile == "casual" or qtype == QuestionType.CASUAL:
        return TurnEvidencePlan(
            profile="casual",
            slots_tier0=["MASTER_ANCHOR", "TASK"],
            slots_tier1=[],
            forbidden=["USER_SNAPSHOT", "GET_HEALTH_DATA", "GET_TEMPORAL_HISTORY_DOSSIER"],
            tools_allowed=[],
            task_text="本轮为寒暄/短回复；勿展开化验或穿戴数据。",
            legacy_question_type=qtype,
        )

    if route.profile == "supplement_manifest":
        return TurnEvidencePlan(
            profile="supplement_manifest",
            slots_tier0=["MASTER_ANCHOR", "SUPPLEMENT_BG", "TASK"],
            slots_tier1=["PATIENT_STATE_LAB"],
            forbidden=["USER_SNAPSHOT", "GET_HEALTH_DATA", "DOSSIER_CLINICAL_COMPACT"],
            tools_allowed=[],
            task_text=(
                "【本轮任务】仅针对用户本条消息中的补剂/用药时间表进行结构化点评"
                "（时机、剂量、与他汀/非布司他等的潜在交互）。"
                "可结合 Patient State 化验数字；禁止输出无关的穿戴 Pearson/步数大盘；"
                "禁止向用户索要已给出的补剂清单。"
            ),
            legacy_question_type=QuestionType.LIFESTYLE,
        )

    if route.profile == "combined_review" or qtype == QuestionType.COMBINED:
        if catalog_mode_enabled():
            t0 = ["MASTER_ANCHOR", "TASK", "EVIDENCE_CATALOG", "NUMERICS_MANIFEST"]
            t1 = ["RECALL", "AUDIT"]
            t0, t1 = _append_metadata_catalog_slots("combined_review", slots_tier0=t0, slots_tier1=t1)
            return TurnEvidencePlan(
                profile="combined_review",
                slots_tier0=t0,
                slots_tier1=t1,
                forbidden=["USER_SNAPSHOT", "GET_HEALTH_DATA"],
                tools_allowed=["fetch_evidence_by_id"],
                task_text=combined_catalog_task_text(msg),
                legacy_question_type=qtype,
            )
        return TurnEvidencePlan(
            profile="combined_review",
            slots_tier0=[
                "MASTER_ANCHOR",
                "TASK",
                "NUMERICS_MANIFEST",
                "LDL_AUTHORITY",
                "WEARABLE_90D_SUMMARY",
                "SUPPLEMENT_BG",
            ],
            slots_tier1=["PATIENT_STATE_LAB", "DOSSIER_CLINICAL_COMPACT", "AUDIT", "RECALL"],
            forbidden=["USER_SNAPSHOT"],
            tools_allowed=[],
            task_text=(
                "【本轮任务】结合 SQLite LDL 权威表、Numerics Manifest 机器白名单、"
                "Patient State 化验、【Evidence·近90日穿戴摘要】与补剂背景，"
                "回答血脂与近90日 HRV/活动消耗的关系，并给出补剂调整建议。"
                "【数字引用契约】凡写出化验或穿戴数值，必须逐条对应 Manifest KV 或已注入证据中的"
                "「指标名 + 报告日/区间 + 数值」三元组；禁止编造日期；禁止跨指标挪用数字。"
                "必须引用 Manifest 或 system 证据块中的具体数值，或明确写「库内无该指标」；"
                "禁止向用户索要 HRV/运动消耗/血脂原始数据、日期范围或上传报告；"
                "禁止用无关穿戴大盘替代血脂。"
            ),
            legacy_question_type=qtype,
        )

    if route.profile == "lab_cross_year" or user_message_needs_lab_dossier(msg) or qtype == QuestionType.LAB:
        t0 = ["MASTER_ANCHOR", "TASK", "NUMERICS_MANIFEST", "LDL_AUTHORITY"]
        t1 = ["DOSSIER_LAB", "PATIENT_STATE_LAB", "AUDIT", "RECALL"]
        t0, t1 = _append_metadata_catalog_slots("lab_cross_year", slots_tier0=t0, slots_tier1=t1)
        return TurnEvidencePlan(
            profile="lab_cross_year",
            slots_tier0=t0,
            slots_tier1=t1,
            forbidden=["USER_SNAPSHOT", "GET_HEALTH_DATA"],
            tools_allowed=["get_temporal_history_dossier"],
            task_text="【本轮任务】以 SQLite 卷宗与 LDL 权威表为准，完成历年/对比类化验对账。",
            legacy_question_type=QuestionType.LAB,
        )

    if route.profile == "wearable_only" or qtype == QuestionType.WEARABLE:
        return TurnEvidencePlan(
            profile="wearable_only",
            slots_tier0=["MASTER_ANCHOR", "WEARABLE_90D_SUMMARY", "TASK"],
            slots_tier1=["PATIENT_STATE_WEARABLE"],
            forbidden=["USER_SNAPSHOT_IN_RAW_USER"],
            tools_allowed=["get_health_data"],
            task_text=(
                "【本轮任务】回答穿戴/睡眠/血氧/HRV 等问题；"
                "必须引用 Tier0「近90日穿戴摘要 / User Data Snapshot」中的区间均值与 n 天数；"
                "禁止引用已省略的近7日 Patient State 表；禁止向用户索要 export 原始数据。"
            ),
            legacy_question_type=qtype,
        )

    return TurnEvidencePlan(
        profile="lifestyle",
        slots_tier0=["MASTER_ANCHOR", "TASK"],
        slots_tier1=["SUPPLEMENT_BG", "PATIENT_STATE_LAB"],
        forbidden=["USER_SNAPSHOT"],
        tools_allowed=[],
        task_text="【本轮任务】基于用户问题与 Patient State 作答；勿臆造未列出指标。",
        legacy_question_type=qtype,
    )


def plan_allows_snapshot_in_user(plan: TurnEvidencePlan) -> bool:
    return "USER_SNAPSHOT" not in plan.forbidden and "USER_SNAPSHOT_IN_RAW_USER" in plan.forbidden


def plan_allows_heuristic_snapshot(plan: TurnEvidencePlan) -> bool:
    if "USER_SNAPSHOT" in plan.forbidden:
        return False
    return plan.profile == "wearable_only"


def build_wearable_90d_summary_block(user_id: str, user_message: str) -> str:
    """Precomputed wearable summary for Evidence Lane (never appended to raw user)."""
    uid = (user_id or "default").strip() or "default"
    ref = effective_query_reference_date()
    window = default_wearable_window(user_message, reference=ref)
    metrics = infer_wearable_metrics(user_message)
    if not metrics:
        metrics = ["hrv", "activity_kcal"]
    result = get_health_data(
        uid,
        window.start,
        window.end,
        metrics,
        user_message=user_message,
    )
    snap = (result.analytics_snapshot or "").strip()
    if not snap:
        return (
            f"【Evidence · 近90日穿戴摘要】\n"
            f"区间 {window.start.isoformat()}～{window.end.isoformat()}："
            f"{result.message or '无数据'}"
        )
    return (
        f"【Evidence · 近90日穿戴摘要 · {window.start.isoformat()}～{window.end.isoformat()}】\n"
        f"{snap}\n"
        f"（宏观趋势参考；90 天对比数字见 WEARABLE_COMPARE_TABLE。）"
    )


def build_wearable_90d_macro_summary_block(user_id: str, user_message: str) -> str:
    """Macro-only wearable context for screenshot-compare turns (no means/ranges)."""
    from pha.health_analytics import build_wearable_macro_analytics_snapshot
    from pha.sqlite_storage import query_wearable_daily_range
    from pha.store import store

    uid = (user_id or "default").strip() or "default"
    ref = effective_query_reference_date()
    window = default_wearable_window(user_message, reference=ref)
    metrics = infer_wearable_metrics(user_message)
    if not metrics:
        metrics = ["hrv", "activity_kcal"]
    rows = list(query_wearable_daily_range(uid, window.start, window.end) or [])
    if not rows:
        rows = [r for r in store.list_wearable_rows(uid) if window.start <= r.day <= window.end]
    snap = build_wearable_macro_analytics_snapshot(
        rows,
        start_date=window.start,
        end_date=window.end,
        reference_date=ref,
        user_message=user_message,
        metrics=metrics,
    )
    if not snap:
        return (
            f"【Evidence · 近90日穿戴宏观趋势 · {window.start.isoformat()}～{window.end.isoformat()}】\n"
            f"无本地日聚合数据。\n"
            f"（不含 90 天均值/区间；截图对比数字见 WEARABLE_COMPARE_TABLE。）"
        )
    return (
        f"【Evidence · 近90日穿戴宏观趋势 · {window.start.isoformat()}～{window.end.isoformat()}】\n"
        f"{snap}\n"
        f"（不含 90 天均值/区间；截图对比数字见 WEARABLE_COMPARE_TABLE。）"
    )


def _assemble_tiered_supplemental_legacy(
    *,
    plan: TurnEvidencePlan,
    slot_contents: Dict[str, str],
) -> tuple[str, str, List[str], Dict[str, Any]]:
    """Legacy concat+truncate (rollback via PHA_HARNESS_TIER0_ASSEMBLY=legacy)."""
    missing: List[str] = []
    t0_parts: List[str] = []
    t1_parts: List[str] = []

    for slot in plan.slots_tier0:
        if slot == "MASTER_ANCHOR":
            continue
        if slot == "TASK":
            t0_parts.append(slot_contents.get("TASK") or plan.task_text)
            continue
        body = (slot_contents.get(slot) or "").strip()
        if not body and slot in ("LDL_AUTHORITY", "SUPPLEMENT_BG", "WEARABLE_90D_SUMMARY", "NUMERICS_MANIFEST"):
            missing.append(slot)
        if body:
            t0_parts.append(body)

    for slot in plan.slots_tier1:
        body = (slot_contents.get(slot) or "").strip()
        if body:
            t1_parts.append(body)

    tier0 = "\n\n---\n\n".join(t0_parts)
    if len(tier0) > PHA_HARNESS_TIER0_MAX_CHARS:
        tier0 = tier0[: PHA_HARNESS_TIER0_MAX_CHARS - 20] + "\n…（Tier0 证据已按上限截断）"
    tier1 = "\n\n---\n\n".join(t1_parts)
    integrity: Dict[str, Any] = {
        "budget_limit": PHA_HARNESS_TIER0_MAX_CHARS,
        "used_chars": len(tier0),
        "slots": [],
        "errors": ["legacy_assembly"],
        "warnings": [],
    }
    return tier0, tier1, missing, integrity


def assemble_tiered_supplemental(
    *,
    plan: TurnEvidencePlan,
    slot_contents: Dict[str, str],
) -> tuple[str, str, List[str], Dict[str, Any]]:
    """Returns (tier0_text, tier1_text, missing_slots, tier0_integrity)."""
    mode = os.environ.get("PHA_HARNESS_TIER0_ASSEMBLY", "v2").strip().lower()
    if mode == "legacy":
        return _assemble_tiered_supplemental_legacy(plan=plan, slot_contents=slot_contents)
    from pha.harness_tier0_assembly import assemble_tiered_supplemental_v2

    return assemble_tiered_supplemental_v2(plan=plan, slot_contents=slot_contents)


def compute_plan_vs_actual(
    plan: TurnEvidencePlan,
    *,
    raw_user_message: str,
    current_user_message: str,
    tools_executed: Sequence[str],
    snapshot_in_user: bool,
    slot_contents: Dict[str, str],
    tier0_text: str = "",
    tier0_integrity: Optional[Dict[str, Any]] = None,
) -> List[str]:
    diffs: List[str] = []
    if plan.preserve_raw_user and (current_user_message or "").strip() != (raw_user_message or "").strip():
        diffs.append("raw_user_lane_modified")
    if "USER_SNAPSHOT" in plan.forbidden and snapshot_in_user:
        diffs.append("forbidden_snapshot_in_user")
    if "GET_HEALTH_DATA" in plan.forbidden:
        if any(t == "get_health_data" for t in tools_executed):
            diffs.append("forbidden_tool_get_health_data")
    allowed = set(plan.tools_allowed)
    for t in tools_executed:
        if t not in allowed:
            diffs.append(f"tool_not_allowed:{t}")
    for slot in plan.slots_tier0:
        if slot in ("MASTER_ANCHOR", "TASK"):
            continue
        if slot not in slot_contents or not (slot_contents.get(slot) or "").strip():
            if slot in ("LDL_AUTHORITY", "WEARABLE_90D_SUMMARY", "NUMERICS_MANIFEST", "EVIDENCE_CATALOG"):
                diffs.append(f"missing_tier0_slot:{slot}")
    if tier0_integrity:
        from pha.harness_tier0_assembly import tier0_integrity_plan_diffs

        diffs.extend(
            tier0_integrity_plan_diffs(
                plan,
                slot_contents=slot_contents,
                tier0_text=tier0_text,
                integrity=tier0_integrity,
            ),
        )
    return sorted(set(diffs))
