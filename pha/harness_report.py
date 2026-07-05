"""PHA Harness build report — Phase 0 as-is observability (v2.2.5)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from pha.agent_tools import SNAPSHOT_MARKER
from pha.build_marker import PHA_SERVER_BUILD
from pha.chat_background import (
    PHA_BG_INJECT_MAX_MEDICATION,
    PHA_BG_INJECT_MAX_OTHER,
    PHA_BG_INJECT_MAX_SUPPLEMENT,
)
from pha.chat_router import DOSSIER_TITLE
from pha.health_data import build_system_date_block, effective_query_reference_date
from pha.intent_gates import (
    QuestionType,
    user_message_is_combined_health_review,
    user_message_needs_lab_dossier,
    user_message_needs_wearable_query,
)

logger = logging.getLogger(__name__)

REPORT_SCHEMA = "pha.harness_report/v1.2"
REPORT_SCHEMA_V11 = "pha.harness_report/v1.1"
REPORT_SCHEMA_LEGACY = "pha.harness_report/v1"

_MATRIX_TARGETS: Dict[str, Dict[str, Any]] = {
    "supplement_manifest": {
        "slots_ordered": ["MASTER_ANCHOR", "SUPPLEMENT_BG"],
        "forbidden": ["USER_SNAPSHOT", "GET_HEALTH_DATA"],
        "tools_allowed": [],
    },
    "combined_review": {
        "slots_ordered": [
            "MASTER_ANCHOR",
            "EVIDENCE_CATALOG",
            "NUMERICS_MANIFEST",
            "TASK",
        ],
        "forbidden": ["USER_SNAPSHOT", "GET_HEALTH_DATA"],
        "tools_allowed": ["fetch_evidence_by_id"],
    },
    "lab_cross_year": {
        "slots_ordered": ["MASTER_ANCHOR", "LDL_AUTHORITY", "DOSSIER_LAB", "PATIENT_STATE_LAB"],
        "forbidden": ["GET_HEALTH_DATA"],
        "tools_allowed": ["get_temporal_history_dossier"],
    },
    "wearable_only": {
        "slots_ordered": ["MASTER_ANCHOR", "WEARABLE_90D"],
        "forbidden": [],
        "tools_allowed": ["get_health_data"],
    },
    "casual": {
        "slots_ordered": ["MASTER_ANCHOR"],
        "forbidden": ["USER_SNAPSHOT", "GET_HEALTH_DATA"],
        "tools_allowed": [],
    },
    "lifestyle": {
        "slots_ordered": ["MASTER_ANCHOR", "SUPPLEMENT_BG"],
        "forbidden": [],
        "tools_allowed": [],
    },
}


def harness_debug_enabled() -> bool:
    return os.environ.get("PHA_HARNESS_DEBUG", "0").strip() in ("1", "true", "yes", "on")


def _sha_prefix(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def _preview(text: str, n: int = 80) -> str:
    s = (text or "").replace("\n", " ")
    return s[:n] + ("…" if len(s) > n else "")


def guess_target_profile(
    *,
    question_type: QuestionType,
    user_message: str,
    inject_snapshot: bool,
) -> str:
    msg = user_message or ""
    if question_type == QuestionType.CASUAL:
        return "casual"
    if user_message_is_combined_health_review(msg) or question_type == QuestionType.COMBINED:
        return "combined_review"
    if user_message_needs_lab_dossier(msg) or question_type == QuestionType.LAB:
        return "lab_cross_year"
    if inject_snapshot or user_message_needs_wearable_query(msg):
        if question_type == QuestionType.LIFESTYLE and _looks_like_supplement_manifest(msg):
            return "supplement_manifest"
        return "wearable_only"
    if _looks_like_supplement_manifest(msg):
        return "supplement_manifest"
    return "lifestyle"


def _looks_like_supplement_manifest(user_message: str) -> bool:
    from pha.intent_gates import resolve_schema_intent

    return resolve_schema_intent(user_message).profile == "supplement_manifest"


@dataclass
class HarnessSlotInput:
    id: str
    tier: int
    content: str
    source: str
    present: bool = True


@dataclass
class HarnessTurnInputs:
    user_id: str
    session_id: str
    user_message_id: Optional[int]
    model: str
    user_message: str
    question_type: QuestionType
    temporal_years: List[int]
    master_anchor_chars: int = 0
    ldl_authority: str = ""
    supplement_bg: str = ""
    forced_dossier: str = ""
    audit_warn: str = ""
    recalled_snippets: str = ""
    patient_state: str = ""
    augmented_user_message: str = ""
    raw_supplemental: str = ""
    system_after_stack: str = ""
    system_content_max: int = 10000
    inject_wearable_snapshot: bool = False
    build_forced_dossier: bool = False
    has_snapshot: bool = False
    fast_path: bool = False
    use_tools_runtime: bool = True
    tool_results: List[Dict[str, Any]] = field(default_factory=list)
    chat_messages: List[Dict[str, Any]] = field(default_factory=list)
    mode: str = "as_is_pre_llm"
    turn_plan: Optional[Any] = None
    plan_vs_actual: List[str] = field(default_factory=list)
    tier0_integrity: Dict[str, Any] = field(default_factory=dict)
    runtime_mode: str = ""
    numerics_manifest: Dict[str, Any] = field(default_factory=dict)
    numerics_manifest_block: str = ""
    intent_route: Dict[str, Any] = field(default_factory=dict)
    catalog_existence: Dict[str, Any] = field(default_factory=dict)
    numerics_audit: Dict[str, Any] = field(default_factory=dict)
    dynamic_slots: Dict[str, Any] = field(default_factory=dict)
    metadata_catalog_block: str = ""
    shadow_routing: Dict[str, Any] = field(default_factory=dict)
    turn_scope: Dict[str, Any] = field(default_factory=dict)
    episodic: Dict[str, Any] = field(default_factory=dict)
    goal_class: str = ""
    goal_source: str = ""
    arbiter_decision: Dict[str, Any] = field(default_factory=dict)


def _slot_rows(inputs: HarnessTurnInputs) -> List[Dict[str, Any]]:
    ref = effective_query_reference_date()
    anchor = build_system_date_block(ref)
    rows = [
        HarnessSlotInput("MASTER_ANCHOR", 0, anchor, "build_system_date_block"),
        HarnessSlotInput(
            "LDL_AUTHORITY",
            0,
            inputs.ldl_authority,
            "build_ldl_authority_system_block",
            present=bool(inputs.ldl_authority.strip()),
        ),
        HarnessSlotInput(
            "NUMERICS_MANIFEST",
            0,
            inputs.numerics_manifest_block,
            "build_numerics_manifest",
            present=bool(inputs.numerics_manifest_block.strip()),
        ),
        HarnessSlotInput(
            "SUPPLEMENT_BG",
            0,
            inputs.supplement_bg,
            "build_user_background_block",
            present=bool(inputs.supplement_bg.strip()),
        ),
        HarnessSlotInput(
            "DOSSIER_CLINICAL_COMPACT",
            1,
            inputs.forced_dossier,
            "prepare_chat_evidence_bundle",
            present=bool(inputs.forced_dossier.strip()),
        ),
        HarnessSlotInput("AUDIT", 1, inputs.audit_warn, "build_chat_audit_payload", present=bool(inputs.audit_warn.strip())),
        HarnessSlotInput(
            "RECALL",
            1,
            inputs.recalled_snippets,
            "build_chat_context_block",
            present=bool(inputs.recalled_snippets.strip()),
        ),
        HarnessSlotInput(
            "PATIENT_STATE_LAB",
            0,
            inputs.patient_state,
            "build_patient_state_evidence_slice",
            present=bool(inputs.patient_state.strip()),
        ),
        HarnessSlotInput(
            "USER_SNAPSHOT",
            0,
            inputs.augmented_user_message if inputs.has_snapshot else "",
            "apply_health_heuristic_override",
            present=inputs.has_snapshot,
        ),
    ]
    out: List[Dict[str, Any]] = []
    for s in rows:
        body = s.content or ""
        chars = len(body)
        truncated = False
        truncated_from: Optional[int] = None
        if s.id == "SUPPLEMENT_BG" and chars > 0:
            raw_note = _supplement_raw_len_hint(inputs.supplement_bg)
            if raw_note:
                truncated = True
                truncated_from = raw_note
        out.append(
            {
                "id": s.id,
                "tier": s.tier,
                "chars": chars,
                "truncated": truncated,
                "truncated_from": truncated_from,
                "source": s.source,
                "present": s.present,
            },
        )
    return out


def _supplement_raw_len_hint(block: str) -> Optional[int]:
    """If block ends with ellipsis from inject cap, we cannot know exact source len; flag cap."""
    if (block or "").rstrip().endswith("…"):
        return PHA_BG_INJECT_MAX_SUPPLEMENT + 1
    return None


def _caps_rows(inputs: HarnessTurnInputs) -> List[Dict[str, Any]]:
    caps: List[Dict[str, Any]] = [
        {
            "layer": "PHA_BG_INJECT_MAX_SUPPLEMENT",
            "limit": PHA_BG_INJECT_MAX_SUPPLEMENT,
            "note": "per-note inject cap in build_user_background_block",
        },
        {
            "layer": "PHA_BG_INJECT_MAX_MEDICATION",
            "limit": PHA_BG_INJECT_MAX_MEDICATION,
            "note": "",
        },
        {
            "layer": "PHA_BG_INJECT_MAX_OTHER",
            "limit": PHA_BG_INJECT_MAX_OTHER,
            "note": "",
        },
        {
            "layer": "SYSTEM_CONTENT_MAX_CHARS",
            "limit": inputs.system_content_max,
            "note": "build_pha_chat_message_stack _cap_system_content",
        },
    ]
    raw_len = len(inputs.raw_supplemental) + len(build_system_date_block()) + 8000
    if inputs.system_after_stack and raw_len > inputs.system_content_max:
        caps.append(
            {
                "layer": "SYSTEM_CONTENT_MAX_CHARS",
                "limit": inputs.system_content_max,
                "note": f"applied: raw_est~{raw_len} -> {len(inputs.system_after_stack)}",
            },
        )
    return caps


def _tools_section(inputs: HarnessTurnInputs) -> Dict[str, Any]:
    executed: List[Dict[str, Any]] = []
    for tr in inputs.tool_results or []:
        name = str(tr.get("tool") or "")
        args = tr.get("arguments") or {}
        result = tr.get("result") or {}
        executed.append(
            {
                "name": name,
                "heuristic": bool(tr.get("heuristic")),
                "auto": bool(tr.get("auto")),
                "args": args,
                "result_metrics": result.get("metrics") if isinstance(result, dict) else None,
                "result_row_count": result.get("row_count") if isinstance(result, dict) else None,
            },
        )
    return {
        "allowed_legacy": ["get_health_data", "get_temporal_history_dossier"],
        "use_tools_runtime": inputs.use_tools_runtime,
        "fast_path": inputs.fast_path,
        "executed": executed,
    }


def _messages_stack_rows(messages: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for idx, m in enumerate(messages):
        role = str(m.get("role") or "")
        content = str(m.get("content") or "")
        label = "history"
        if idx == 0 and role == "system":
            label = "system"
        elif "Patient State" in content or "证据切片" in content:
            label = "patient_state"
        elif role == "user" and idx == len(messages) - 1:
            label = "current_user"
        elif SNAPSHOT_MARKER in content:
            label = "current_user_with_snapshot"
        elif role == "tool":
            label = "tool"
        elif role == "assistant":
            label = "assistant"
        rows.append(
            {
                "index": idx,
                "role": role,
                "chars": len(content),
                "label": label,
                "sha256_prefix": _sha_prefix(content),
                "preview": _preview(content),
            },
        )
    return rows


def _warnings(
    inputs: HarnessTurnInputs,
    target_profile: str,
    slots: List[Dict[str, Any]],
    system_prompt: str,
) -> List[str]:
    w: List[str] = []
    target = _MATRIX_TARGETS.get(target_profile, {})
    forbidden = set(target.get("forbidden") or [])

    if "USER_SNAPSHOT" in forbidden and inputs.has_snapshot:
        w.append("matrix_gap_snapshot_on_supplement" if target_profile == "supplement_manifest" else "matrix_gap_snapshot_forbidden")
    if target_profile == "combined_review":
        for ex in inputs.tool_results or []:
            if ex.get("tool") == "get_health_data":
                w.append("matrix_gap_tool_on_combined")
        if inputs.inject_wearable_snapshot:
            w.append("matrix_gap_snapshot_on_combined")
    if _looks_like_supplement_manifest(inputs.user_message) and inputs.has_snapshot:
        w.append("matrix_gap_snapshot_on_supplement")
    if _looks_like_supplement_manifest(inputs.user_message) and inputs.question_type == QuestionType.WEARABLE:
        w.append("matrix_gap_supplement_classified_wearable")
    if inputs.question_type == QuestionType.LIFESTYLE and user_message_needs_wearable_query(inputs.user_message):
        if _looks_like_supplement_manifest(inputs.user_message):
            w.append("matrix_gap_supplement_text_matches_wearable_regex")

    for sl in slots:
        if sl["id"] == "SUPPLEMENT_BG" and sl.get("truncated"):
            w.append("supplement_bg_truncated_1200")
        if sl["id"] == "LDL_AUTHORITY" and not sl.get("present") and target_profile in (
            "combined_review",
            "lab_cross_year",
        ):
            w.append("ldl_authority_missing")
        if sl["id"] == "LDL_AUTHORITY" and sl.get("present") and "LDL 权威表" not in system_prompt:
            w.append("ldl_missing_in_capped_system")

    if len(system_prompt) >= inputs.system_content_max - 40:
        w.append("cap_system_truncated")
    if DOSSIER_TITLE in system_prompt and "ldl_missing_in_capped_system" not in w:
        if target_profile == "combined_review" and "LDL" not in system_prompt[:4000]:
            w.append("dossier_may_have_displaced_ldl")

    return sorted(set(w))


def build_harness_report(inputs: HarnessTurnInputs) -> Dict[str, Any]:
    target = guess_target_profile(
        question_type=inputs.question_type,
        user_message=inputs.user_message,
        inject_snapshot=inputs.inject_wearable_snapshot,
    )
    target_spec = _MATRIX_TARGETS.get(target, {})
    slots = _slot_rows(inputs)
    system_prompt = inputs.system_after_stack or ""
    if not system_prompt and inputs.chat_messages:
        system_prompt = str(inputs.chat_messages[0].get("content") or "")

    turn_id = f"{inputs.session_id}:{inputs.user_message_id or 'pending'}"
    warnings = _warnings(inputs, target, slots, system_prompt)
    t0_errs = list((inputs.tier0_integrity or {}).get("errors") or [])
    for e in t0_errs:
        warnings.append(e)
    warnings = sorted(set(warnings))

    report: Dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "turn_id": turn_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        "build": PHA_SERVER_BUILD,
        "path": "stream_pha_chat_events",
        "mode": inputs.mode,
        "model": inputs.model,
        "user_message_len": len(inputs.user_message or ""),
        "user_message_sha256": _sha_prefix(inputs.user_message or ""),
        "intent_profile": {
            "legacy_question_type": inputs.question_type.value,
            "primary_goal_guess": target,
            "needs_lab": _needs_lab(inputs.user_message),
            "needs_wearable_query": user_message_needs_wearable_query(inputs.user_message),
            "needs_lab_dossier": user_message_needs_lab_dossier(inputs.user_message),
            "is_combined": user_message_is_combined_health_review(inputs.user_message),
            "inject_wearable_snapshot": inputs.inject_wearable_snapshot,
            "build_forced_dossier": inputs.build_forced_dossier,
            "temporal_years": list(inputs.temporal_years or []),
        },
        "plan": {
            "mode": "planned",
            "profile": getattr(inputs.turn_plan, "profile", None) if inputs.turn_plan else None,
            "slots_tier0": getattr(inputs.turn_plan, "slots_tier0", []) if inputs.turn_plan else [],
            "slots_tier1": getattr(inputs.turn_plan, "slots_tier1", []) if inputs.turn_plan else [],
            "forbidden": getattr(inputs.turn_plan, "forbidden", []) if inputs.turn_plan else [],
            "tools_allowed": getattr(inputs.turn_plan, "tools_allowed", []) if inputs.turn_plan else [],
        },
        "plan_vs_actual": list(inputs.plan_vs_actual or []),
        "tier0_integrity": dict(inputs.tier0_integrity or {}),
        "runtime_mode": inputs.runtime_mode or "",
        "numerics_manifest": dict(inputs.numerics_manifest or {}),
        "slots_built": slots,
        "caps_applied": _caps_rows(inputs),
        "tools": _tools_section(inputs),
        "messages_stack": _messages_stack_rows(inputs.chat_messages),
        "warnings": warnings,
    }
    if inputs.intent_route:
        report["intent_route"] = dict(inputs.intent_route)
    if inputs.catalog_existence:
        report["catalog_existence"] = dict(inputs.catalog_existence)
    if inputs.numerics_audit:
        report["numerics_audit"] = dict(inputs.numerics_audit)
    if inputs.dynamic_slots:
        report["dynamic_slots"] = dict(inputs.dynamic_slots)
    if (inputs.metadata_catalog_block or "").strip():
        from pha.metadata_catalog import estimate_token_count

        tier = "tier1"
        if inputs.turn_plan and "METADATA_CATALOG" in (inputs.turn_plan.slots_tier0 or []):
            tier = "tier0"
        report["metadata_catalog"] = {
            "enabled": True,
            "tier": tier,
            "chars": len(inputs.metadata_catalog_block),
            "approx_tokens": estimate_token_count(inputs.metadata_catalog_block),
        }
    if inputs.shadow_routing:
        report["shadow_routing"] = dict(inputs.shadow_routing)
    if inputs.turn_scope:
        report["turnScope"] = dict(inputs.turn_scope)
    if inputs.episodic:
        report["episodic"] = dict(inputs.episodic)
    if inputs.goal_class:
        report["goalClass"] = inputs.goal_class
    if inputs.goal_source:
        report["goalSource"] = inputs.goal_source
    if inputs.arbiter_decision:
        report["arbiterDecision"] = dict(inputs.arbiter_decision)
    return report


def _needs_lab(msg: str) -> bool:
    from pha.intent_gates import _LAB_MARKERS_RE

    return bool(_LAB_MARKERS_RE.search(msg or ""))


def format_harness_summary(report: Dict[str, Any]) -> str:
    ip = report.get("intent_profile") or {}
    tools = report.get("tools") or {}
    warns = report.get("warnings") or []
    ir = report.get("intent_route") or {}
    ce = report.get("catalog_existence") or {}
    na = report.get("numerics_audit") or {}
    sys_row = next((m for m in report.get("messages_stack") or [] if m.get("label") == "system"), {})
    ps_row = next((m for m in report.get("messages_stack") or [] if m.get("label") == "patient_state"), {})
    extra = ""
    if ir:
        extra += f" route={ir.get('authoritative_profile')}"
    if ce:
        extra += f" menu={len(ce.get('would_menu_ids') or [])}/{len(ce.get('candidates') or [])}"
    if na:
        extra += f" numerics={'ok' if na.get('passed') else 'FAIL'}"
    return (
        f"[PHA Harness] {report.get('mode')} {ip.get('primary_goal_guess')} "
        f"| qtype={ip.get('legacy_question_type')} snap={1 if ip.get('inject_wearable_snapshot') else 0} "
        f"tools_exec={len(tools.get('executed') or [])} fast={1 if tools.get('fast_path') else 0} "
        f"| sys={sys_row.get('chars', 0)} ps={ps_row.get('chars', 0)}"
        f"{extra} "
        f"| WARN: {','.join(warns) or 'none'}"
    )


def build_harness_telemetry(
    *,
    user_id: str,
    user_message: str,
    plan_profile: str,
    background_block_nonempty: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """Stage 2A: intent_route + catalog_existence + dynamic_slots for Harness JSONL."""
    from pha.catalog_existence import build_catalog_existence, build_intent_route_payload
    from pha.dynamic_slot_registry import on_request_start
    from pha.universal_catalog_manager import get_catalog_manager

    mgr = get_catalog_manager()
    route = mgr.resolve_intent(user_message)
    catalog_ids = mgr.catalog_asset_ids_for_profile(
        plan_profile,
        user_message=user_message,
        user_id=user_id,
    )
    return {
        "intent_route": build_intent_route_payload(
            route,
            catalog_ids=catalog_ids,
            plan_profile=plan_profile,
        ),
        "catalog_existence": build_catalog_existence(
            user_id,
            plan_profile,
            user_message,
            background_block_nonempty=background_block_nonempty,
        ),
        "dynamic_slots": on_request_start(user_id, user_message),
    }


def emit_harness_build_report(report: Dict[str, Any]) -> None:
    if not harness_debug_enabled():
        return
    path = os.environ.get("PHA_HARNESS_REPORT_PATH", "/tmp/pha-harness-reports.jsonl").strip()
    summary = format_harness_summary(report)
    print(summary, flush=True)
    logger.info("%s", summary)
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(report, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("HarnessBuildReport write failed: %s", exc)
    if os.environ.get("PHA_HARNESS_DEBUG_FULL", "0").strip() in ("1", "true", "yes"):
        full_dir = os.environ.get("PHA_HARNESS_FULL_DIR", "/tmp/pha-harness-full")
        os.makedirs(full_dir, exist_ok=True)
        safe_id = str(report.get("turn_id") or "unknown").replace("/", "_")
        full_path = os.path.join(full_dir, f"{safe_id}-{report.get('mode')}.json")
        with open(full_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)


def dry_run_harness_report(
    user_message: str,
    *,
    user_id: str = "default",
    question_type: Optional[QuestionType] = None,
) -> Dict[str, Any]:
    """Build report without SSE/LLM — Phase 1 plan-driven dry-run."""
    from pha.temporal_router import parse_temporal_intent
    from pha.chat_service import (
        SYSTEM_CONTENT_MAX_CHARS,
        _cap_system_tiered,
        build_pha_chat_message_stack,
        PHA_MEDICAL_SOUL_SYSTEM_PROMPT,
    )
    from pha.harness_plan import (
        assemble_tiered_supplemental,
        build_turn_evidence_plan,
        build_wearable_90d_summary_block,
        compute_plan_vs_actual,
        plan_allows_heuristic_snapshot,
    )
    from pha.health_data import build_system_date_block, effective_query_reference_date
    from pha.chat_background import build_user_background_block

    uid = user_id
    intent = parse_temporal_intent(user_message)
    plan = build_turn_evidence_plan(user_message)
    qtype = plan.legacy_question_type

    ldl_authority = ""
    if "LDL_AUTHORITY" in plan.all_slots:
        from pha.intent_gates import resolve_ldl_authority_years

        ldl_years = resolve_ldl_authority_years(uid, user_message, intent)
        if ldl_years:
            from pha.chat_router import build_ldl_authority_system_block

            ldl_authority = build_ldl_authority_system_block(uid, ldl_years)

    bg = build_user_background_block(uid, user_message=user_message)
    dossier = ""
    catalog_turn = "fetch_evidence_by_id" in set(plan.tools_allowed or [])
    build_dossier = (
        "DOSSIER_CLINICAL_COMPACT" in plan.all_slots or "DOSSIER_LAB" in plan.all_slots
    )
    if build_dossier and not catalog_turn and (
        user_message_needs_lab_dossier(user_message) or plan.profile == "combined_review"
    ):
        from pha.chat_router import prepare_chat_evidence_bundle

        dossier, *_ = prepare_chat_evidence_bundle(
            uid,
            user_message,
            build_dossier=True,
            omit_ldl_fusion_blocks=plan.profile != "lab_cross_year",
            compact_clinical_only=(plan.profile == "combined_review"),
        )

    wearable_summary = ""
    if "WEARABLE_90D_SUMMARY" in plan.slots_tier0:
        wearable_summary = build_wearable_90d_summary_block(uid, user_message)

    catalog_block = ""
    if "EVIDENCE_CATALOG" in plan.slots_tier0:
        from pha.evidence_catalog import build_evidence_catalog_block

        catalog_block = build_evidence_catalog_block(
            profile=plan.profile,
            user_message=user_message,
            user_id=uid,
        )

    numerics_manifest_obj = None
    manifest_block = ""
    if "NUMERICS_MANIFEST" in plan.slots_tier0:
        from pha.numerics_manifest import build_numerics_manifest, format_manifest_tier0_block

        numerics_manifest_obj = build_numerics_manifest(
            uid,
            profile=plan.profile,
            user_message=user_message,
            include_wearable=not catalog_turn,
        )
        manifest_block = format_manifest_tier0_block(numerics_manifest_obj)

    metadata_block = ""
    if "METADATA_CATALOG" in plan.all_slots:
        from pha.metadata_catalog import build_metadata_catalog_block

        metadata_block = build_metadata_catalog_block(
            uid,
            user_message=user_message,
            profile=plan.profile,
        )

    slot_contents: Dict[str, str] = {
        "TASK": plan.task_text,
        "EVIDENCE_CATALOG": catalog_block,
        "NUMERICS_MANIFEST": manifest_block,
        "METADATA_CATALOG": metadata_block,
        "LDL_AUTHORITY": ldl_authority,
        "SUPPLEMENT_BG": bg,
        "DOSSIER_CLINICAL_COMPACT": dossier,
        "DOSSIER_LAB": dossier,
        "WEARABLE_90D_SUMMARY": wearable_summary,
        "AUDIT": "",
        "RECALL": "",
    }
    tier0_supp, tier1_supp, _, tier0_integrity = assemble_tiered_supplemental(
        plan=plan,
        slot_contents=slot_contents,
    )
    raw_sup = f"{tier0_supp}\n\n---\n\n{tier1_supp}".strip()

    pre_results: List[Dict[str, Any]] = []
    if plan_allows_heuristic_snapshot(plan, user_message=user_message):
        from pha.agent_tools import apply_health_heuristic_override

        _, _, pre_results = apply_health_heuristic_override(user_message, uid)
        if pre_results and pre_results[0].get("result"):
            snap_body = str((pre_results[0].get("result") or {}).get("analytics_snapshot") or "")
            if snap_body.strip():
                slot_contents["WEARABLE_90D_SUMMARY"] = (
                    f"【Evidence · 穿戴预计算摘要 · 勿与补剂/化验混读】\n{snap_body.strip()}"
                )
                tier0_supp, tier1_supp, _, tier0_integrity = assemble_tiered_supplemental(
                    plan=plan,
                    slot_contents=slot_contents,
                )
                raw_sup = f"{tier0_supp}\n\n---\n\n{tier1_supp}".strip()

    from pha.patient_state import build_patient_state_evidence_slice

    patient = ""
    if "PATIENT_STATE_LAB" in plan.all_slots or "PATIENT_STATE_WEARABLE" in plan.all_slots:
        from pha.evidence_lane import wearable_block_has_user_snapshot

        patient = build_patient_state_evidence_slice(
            uid,
            user_message,
            question_type=qtype,
            has_wearable_user_snapshot=wearable_block_has_user_snapshot(
                wearable_summary,
            ),
        )

    ref = effective_query_reference_date()
    tiered_system = _cap_system_tiered(
        soul_with_anchor=build_system_date_block(ref) + PHA_MEDICAL_SOUL_SYSTEM_PROMPT.strip(),
        tier0_supplemental=tier0_supp,
        tier1_supplemental=tier1_supp,
    )
    messages = build_pha_chat_message_stack(
        supplemental_system="",
        history_messages=[],
        patient_state=patient,
        current_user_message=user_message,
        raw_user_message=user_message,
        tiered_system=tiered_system,
    )
    last_user = str(messages[-1].get("content") or "") if messages else user_message
    pva = compute_plan_vs_actual(
        plan,
        raw_user_message=user_message,
        current_user_message=last_user,
        tools_executed=[str(t.get("tool") or "") for t in pre_results],
        snapshot_in_user=SNAPSHOT_MARKER in last_user,
        slot_contents=slot_contents,
        tier0_text=tier0_supp,
        tier0_integrity=tier0_integrity,
    )
    telemetry = build_harness_telemetry(
        user_id=uid,
        user_message=user_message,
        plan_profile=plan.profile,
        background_block_nonempty=bool(bg.strip()),
    )
    shadow_payload: Dict[str, Any] = {}
    from pha.shadow_routing import maybe_start_shadow_job, shadow_routing_enabled
    from pha.universal_catalog_manager import get_catalog_manager

    if shadow_routing_enabled():
        _mgr = get_catalog_manager()
        _catalog_ids = _mgr.catalog_asset_ids_for_profile(
            plan.profile,
            user_message=user_message,
            user_id=uid,
        )
        _handle = maybe_start_shadow_job(
            user_message,
            authoritative_profile=plan.profile,
            authoritative_catalog_ids=_catalog_ids,
            user_id=uid,
            metadata_catalog_excerpt=(metadata_block or "")[:1200],
        )
        if _handle is not None:
            shadow_payload = _handle.collect()

    inputs = HarnessTurnInputs(
        user_id=uid,
        session_id="dry-run",
        user_message_id=None,
        model="dry-run",
        user_message=user_message,
        question_type=qtype,
        temporal_years=list(intent.explicit_years or []),
        ldl_authority=ldl_authority,
        supplement_bg=bg,
        forced_dossier=dossier,
        patient_state=patient,
        augmented_user_message=user_message,
        raw_supplemental=raw_sup,
        system_after_stack=str(messages[0].get("content") or "") if messages else "",
        system_content_max=SYSTEM_CONTENT_MAX_CHARS,
        inject_wearable_snapshot=plan_allows_heuristic_snapshot(plan, user_message=user_message),
        build_forced_dossier=build_dossier,
        has_snapshot=SNAPSHOT_MARKER in last_user,
        tool_results=pre_results,
        chat_messages=messages,
        mode="plan_dry_run",
        turn_plan=plan,
        plan_vs_actual=pva,
        tier0_integrity=tier0_integrity,
        runtime_mode="catalog_tool_loop" if catalog_turn else "evidence_preload",
        numerics_manifest=numerics_manifest_obj.to_dict() if numerics_manifest_obj else {},
        numerics_manifest_block=manifest_block,
        intent_route=telemetry["intent_route"],
        catalog_existence=telemetry["catalog_existence"],
        dynamic_slots=telemetry["dynamic_slots"],
        metadata_catalog_block=metadata_block,
        shadow_routing=shadow_payload,
    )
    return build_harness_report(inputs)
