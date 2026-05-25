"""Tier0 budget assembly with Protected SLA — v2.2.6.1."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Set, Tuple

from pha.chat_background import summarize_supplement_bg_for_tier0
from pha.evidence_catalog import catalog_mode_enabled
from pha.harness_plan import PHA_HARNESS_TIER0_MAX_CHARS, TurnEvidencePlan


def _assembly_profile_key(plan: TurnEvidencePlan) -> str:
    if (
        plan.profile == "combined_review"
        and catalog_mode_enabled()
        and "EVIDENCE_CATALOG" in plan.slots_tier0
    ):
        return "combined_review_catalog"
    return plan.profile

SlotState = Literal["full", "summary", "min", "absent", "dropped"]
TierLevel = Literal["full", "summary", "min"]

_TIER0_SEP = "\n\n---\n\n"

_SLOT_MARKERS: Dict[str, str] = {
    "TASK": "本轮任务",
    "EVIDENCE_CATALOG": "Evidence Catalog",
    "NUMERICS_MANIFEST": "Numerics Manifest",
    "LDL_AUTHORITY": "SQLite LDL 权威表",
    "WEARABLE_90D_SUMMARY": "近90日穿戴",
    "SUPPLEMENT_BG": "聊天背景档案",
}

_PROFILE_CONFIG: Dict[str, Dict[str, Any]] = {
    "combined_review_catalog": {
        "priority": ["TASK", "EVIDENCE_CATALOG", "NUMERICS_MANIFEST"],
        "protected": {"TASK", "EVIDENCE_CATALOG", "NUMERICS_MANIFEST"},
        "degradation_order": [],
        "supplement_start": "full",
    },
    "combined_review": {
        "priority": [
            "TASK",
            "NUMERICS_MANIFEST",
            "LDL_AUTHORITY",
            "WEARABLE_90D_SUMMARY",
            "SUPPLEMENT_BG",
        ],
        "protected": {"TASK", "NUMERICS_MANIFEST", "LDL_AUTHORITY", "WEARABLE_90D_SUMMARY"},
        "degradation_order": ["SUPPLEMENT_BG", "WEARABLE_90D_SUMMARY", "LDL_AUTHORITY"],
        "supplement_start": "summary",
    },
    "supplement_manifest": {
        "priority": ["TASK", "SUPPLEMENT_BG"],
        "protected": {"TASK", "SUPPLEMENT_BG"},
        "degradation_order": ["SUPPLEMENT_BG"],
        "supplement_start": "summary",
    },
    "lab_cross_year": {
        "priority": ["TASK", "NUMERICS_MANIFEST", "LDL_AUTHORITY"],
        "protected": {"TASK", "NUMERICS_MANIFEST", "LDL_AUTHORITY"},
        "degradation_order": ["LDL_AUTHORITY"],
        "supplement_start": "full",
    },
    "wearable_only": {
        "priority": ["TASK", "WEARABLE_90D_SUMMARY"],
        "protected": {"TASK", "WEARABLE_90D_SUMMARY"},
        "degradation_order": ["WEARABLE_90D_SUMMARY"],
        "supplement_start": "full",
    },
    "casual": {
        "priority": ["TASK"],
        "protected": {"TASK"},
        "degradation_order": [],
        "supplement_start": "full",
    },
    "lifestyle": {
        "priority": ["TASK"],
        "protected": {"TASK"},
        "degradation_order": [],
        "supplement_start": "full",
    },
}


@dataclass
class _SlotAssembly:
    slot_id: str
    raw: str
    level: TierLevel
    protected: bool
    text_full: str = ""
    text_summary: str = ""
    text_min: str = ""

    def text_at(self, level: TierLevel) -> str:
        if level == "full":
            return self.text_full
        if level == "summary":
            return self.text_summary
        return self.text_min

    @property
    def has_source(self) -> bool:
        return bool((self.raw or "").strip())

    @property
    def state(self) -> SlotState:
        if not self.has_source:
            return "absent"
        cur = self.text_at(self.level).strip()
        if not cur:
            return "dropped"
        if self.level == "full":
            return "full"
        if self.level == "summary":
            return "summary"
        return "min"


def _compress_manifest(raw: str, level: TierLevel) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    if level == "min" and len(text) > 420:
        return text[:400] + "\n…（Manifest 最小占位）"
    return text


def _compress_wearable_summary(raw: str, level: TierLevel) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    if level == "full":
        return text
    if level == "min":
        return (
            "【Evidence · 近90日穿戴摘要 · Tier0 最小占位】"
            " HRV/活动消耗/Pearson 见 Patient State 或工具结果。"
        )
    keep: List[str] = []
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            continue
        if any(
            k in s
            for k in (
                "Evidence",
                "近90日",
                "HRV均值",
                "活动消耗",
                "Pearson",
                "区间",
                "wearable",
            )
        ):
            keep.append(s)
        if s.startswith("User Data Snapshot") and len(keep) < 3:
            keep.append(s[:280])
    if not keep:
        keep = [text.split("\n", 1)[0][:240]]
    body = "\n".join(keep[:8])
    return f"【Evidence · 近90日穿戴摘要 · Tier0 压缩】\n{body}".strip()


def _compress_ldl_block(raw: str, level: TierLevel) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    if level == "full":
        return text
    if level == "min":
        return (
            "【SQLite LDL 权威表 · Tier0 最小占位】"
            " 历年 LDL 数值见 Patient State 账本或 Tier1 卷宗。"
        )
    if len(text) <= 900:
        return text
    return text[:880] + "\n…（LDL Tier0 摘要已截断）"


def _compress_supplement(raw: str, level: TierLevel) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    if level == "full":
        return text
    if level == "min":
        return (
            "【聊天背景档案 · Tier0 最小占位】"
            " 补剂/用药时间表见用户本轮原话或 Tier1 背景档案。"
        )
    return summarize_supplement_bg_for_tier0(text, max_chars=800)


def _compress_task(raw: str, plan: TurnEvidencePlan, level: TierLevel) -> str:
    text = (raw or plan.task_text or "").strip()
    if level == "min" and len(text) > 400:
        return text[:380] + "…"
    return text


def _build_slot_assemblies(
    plan: TurnEvidencePlan,
    slot_contents: Dict[str, str],
) -> Tuple[List[_SlotAssembly], Set[str]]:
    cfg = _PROFILE_CONFIG.get(_assembly_profile_key(plan), _PROFILE_CONFIG["lifestyle"])
    priority: List[str] = list(cfg["priority"])
    protected: Set[str] = set(cfg["protected"])
    supplement_start: TierLevel = cfg.get("supplement_start", "full")

    assemblies: List[_SlotAssembly] = []
    for slot_id in priority:
        raw = (slot_contents.get(slot_id) or "").strip()
        if slot_id == "TASK" and not raw:
            raw = plan.task_text
        if slot_id == "SUPPLEMENT_BG":
            start: TierLevel = supplement_start if raw else "full"
        elif slot_id in protected:
            start = "full"
        else:
            start = "full"

        asm = _SlotAssembly(slot_id=slot_id, raw=raw, level=start, protected=slot_id in protected)
        if slot_id == "TASK":
            asm.text_full = _compress_task(raw, plan, "full")
            asm.text_summary = asm.text_full
            asm.text_min = _compress_task(raw, plan, "min")
        elif slot_id in ("NUMERICS_MANIFEST", "EVIDENCE_CATALOG"):
            asm.text_full = _compress_manifest(raw, "full")
            asm.text_summary = _compress_manifest(raw, "summary")
            asm.text_min = _compress_manifest(raw, "min")
        elif slot_id == "LDL_AUTHORITY":
            asm.text_full = _compress_ldl_block(raw, "full")
            asm.text_summary = _compress_ldl_block(raw, "summary")
            asm.text_min = _compress_ldl_block(raw, "min")
        elif slot_id == "WEARABLE_90D_SUMMARY":
            asm.text_full = _compress_wearable_summary(raw, "full")
            asm.text_summary = _compress_wearable_summary(raw, "summary")
            asm.text_min = _compress_wearable_summary(raw, "min")
        elif slot_id == "SUPPLEMENT_BG":
            asm.text_full = _compress_supplement(raw, "full")
            asm.text_summary = _compress_supplement(raw, "summary")
            asm.text_min = _compress_supplement(raw, "min")
        else:
            asm.text_full = raw
            asm.text_summary = raw
            asm.text_min = raw[:120] if raw else ""
        assemblies.append(asm)
    return assemblies, protected


def _join_tier0(assemblies: List[_SlotAssembly]) -> str:
    parts: List[str] = []
    for asm in assemblies:
        body = asm.text_at(asm.level).strip()
        if body:
            parts.append(body)
    return _TIER0_SEP.join(parts)


def _degrade_one(assemblies: List[_SlotAssembly], slot_id: str) -> bool:
    order: List[TierLevel] = ["full", "summary", "min"]
    for asm in assemblies:
        if asm.slot_id != slot_id:
            continue
        if asm.slot_id == "TASK":
            return False
        idx = order.index(asm.level)
        if idx >= len(order) - 1:
            return False
        asm.level = order[idx + 1]
        return True
    return False


def assemble_tiered_supplemental_v2(
    *,
    plan: TurnEvidencePlan,
    slot_contents: Dict[str, str],
    budget: Optional[int] = None,
) -> Tuple[str, str, List[str], Dict[str, Any]]:
    """Budget-based Tier0 assembly with Protected SLA."""
    cap = budget if budget is not None else PHA_HARNESS_TIER0_MAX_CHARS
    cfg = _PROFILE_CONFIG.get(_assembly_profile_key(plan), _PROFILE_CONFIG["lifestyle"])
    degradation_order: List[str] = list(cfg.get("degradation_order") or [])

    assemblies, protected = _build_slot_assemblies(plan, slot_contents)
    missing: List[str] = []
    for asm in assemblies:
        if asm.slot_id in ("LDL_AUTHORITY", "SUPPLEMENT_BG", "WEARABLE_90D_SUMMARY", "NUMERICS_MANIFEST"):
            if not asm.has_source:
                missing.append(asm.slot_id)

    tier0 = _join_tier0(assemblies)
    guard = 0
    while len(tier0) > cap and guard < 24:
        guard += 1
        degraded = False
        for slot_id in degradation_order:
            if _degrade_one(assemblies, slot_id):
                degraded = True
                tier0 = _join_tier0(assemblies)
                if len(tier0) <= cap:
                    break
        if not degraded:
            break

    errors: List[str] = []
    warnings: List[str] = []
    slot_rows: List[Dict[str, Any]] = []

    for asm in assemblies:
        state = asm.state
        body = asm.text_at(asm.level).strip()
        chars = len(body)
        severity = "ok"
        if state == "absent":
            if asm.protected and asm.slot_id in ("LDL_AUTHORITY", "WEARABLE_90D_SUMMARY", "NUMERICS_MANIFEST"):
                severity = "warning"
                warnings.append(f"absent:{asm.slot_id}")
        elif state == "dropped":
            severity = "error"
            errors.append(f"tier0_slot_dropped:{asm.slot_id}")
        elif asm.protected and state == "min":
            severity = "warning"
            warnings.append(f"min:{asm.slot_id}")
        if asm.protected and asm.has_source and state == "dropped":
            errors.append(f"protected_dropped:{asm.slot_id}")
        slot_rows.append(
            {"id": asm.slot_id, "state": state, "chars": chars, "severity": severity, "level": asm.level},
        )

    if len(tier0) > cap:
        errors.append("tier0_budget_exceeded")

    # Tier1 unchanged + optional supplement overflow
    t1_parts: List[str] = []
    for slot in plan.slots_tier1:
        body = (slot_contents.get(slot) or "").strip()
        if body:
            t1_parts.append(body)
    sup_asm = next((a for a in assemblies if a.slot_id == "SUPPLEMENT_BG"), None)
    if sup_asm and sup_asm.has_source and sup_asm.level != "full":
        full_sup = sup_asm.text_full.strip()
        if full_sup and full_sup not in _TIER0_SEP.join(t1_parts):
            t1_parts.append(full_sup)
    tier1 = _TIER0_SEP.join(t1_parts)

    integrity: Dict[str, Any] = {
        "budget_limit": cap,
        "used_chars": len(tier0),
        "slots": slot_rows,
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
    }
    return tier0, tier1, missing, integrity


def slot_materialized_in_tier0(slot_id: str, tier0_text: str) -> bool:
    marker = _SLOT_MARKERS.get(slot_id)
    if not marker:
        return True
    return marker in (tier0_text or "")


def tier0_integrity_plan_diffs(
    plan: TurnEvidencePlan,
    *,
    slot_contents: Dict[str, str],
    tier0_text: str,
    integrity: Dict[str, Any],
) -> List[str]:
    diffs: List[str] = []
    for err in integrity.get("errors") or []:
        diffs.append(err)
    cfg = _PROFILE_CONFIG.get(_assembly_profile_key(plan), {})
    for slot_id in cfg.get("priority") or []:
        raw = (slot_contents.get(slot_id) or "").strip()
        if slot_id == "TASK":
            raw = raw or plan.task_text
        if raw and not slot_materialized_in_tier0(slot_id, tier0_text):
            diffs.append(f"tier0_not_materialized:{slot_id}")
    return sorted(set(diffs))
