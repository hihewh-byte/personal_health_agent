"""P0 — Chat turn slot assembly, Tier0 budget, and message-stack build."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

from pha.agent_tools import (
    FAST_PATH_SYSTEM_ADDENDUM,
    apply_health_heuristic_override,
)
from pha.chat_background import build_user_background_block
from pha.chat_context import build_chat_context_block
from pha.chat_message_stack import (
    ATTACH_PARSE_FAILURE_ADDENDUM,
    CHAT_HISTORY_MAX_TURNS,
    PHA_MEDICAL_SOUL_LITE_SYSTEM_PROMPT,
    PHA_MEDICAL_SOUL_SYSTEM_PROMPT,
    SYSTEM_CONTENT_MAX_CHARS,
    _cap_system_tiered,
    _format_recalled_snippets,
    _session_history_messages,
    build_pha_chat_message_stack,
)
from pha.chat_router import build_chat_audit_payload
from pha.chat_storage import update_message_parsed_json
from pha.evidence_catalog import build_evidence_catalog_block
from pha.harness_plan import (
    TurnEvidencePlan,
    assemble_tiered_supplemental,
    build_wearable_90d_summary_block,
    plan_allows_heuristic_snapshot,
)
from pha.health_data import build_system_date_block, effective_query_reference_date
from pha.intent_gates import (
    QuestionType,
    should_strip_polluted_assistant_history,
    user_message_needs_wearable_query,
)
from pha.numerics_manifest import (
    NumericsManifest,
    build_numerics_manifest,
    format_manifest_tier0_block,
)
from pha.patient_state import build_patient_state_evidence_slice
from pha.chat_attachments import _message_needs_lab_ledger
from pha.chat_turn_fsm import ChatTurnPhase, ChatTurnPhaseRecorder


@dataclass
class TurnSlotContext:
    """Mutable harness slot assembly context (SLOT_ASSEMBLY → message stack)."""

    uid: str
    sid: str
    msg: str
    raw_user_msg: str
    plan: TurnEvidencePlan
    qtype: QuestionType
    parsed_payload: Optional[Dict[str, Any]]
    temporal_intent: Any
    extra_system_context: str
    ldl_authority: str
    forced_dossier: str
    catalog_turn: bool
    attach_parse_failed: bool
    has_parse: bool
    paths_in: List[str]
    user_row_id: int
    attachment_asset_qa: bool
    wearable_screenshot_review: bool
    qa_mode: str
    route_focus: Any
    session_focus_row: Any
    focus_tokens: List[str]
    health_turn_scope: Any
    health_episodic_focus: Any
    episodic_bridge_block: str = ""

    attachment_label_block: str = ""
    wearable_snapshot_block: str = ""
    wearable_compare_table_block: str = ""
    wearable_compare_table_obj: Any = None
    wearable_metric_probe_payload: Optional[Dict[str, Any]] = None
    data_availability_block: str = ""
    background_block: str = ""
    recalled_snippets: str = ""
    audit_md: str = ""
    audit_json: Dict[str, Any] = field(default_factory=dict)
    audit_warn: str = ""
    wearable_summary: str = ""
    catalog_block: str = ""
    numerics_manifest: Optional[NumericsManifest] = None
    manifest_block: str = ""
    metadata_block: str = ""
    slot_contents: Dict[str, str] = field(default_factory=dict)
    recall_focus_block: str = ""
    tier0_supp: str = ""
    tier1_supp: str = ""
    tier0_integrity: Dict[str, Any] = field(default_factory=dict)
    supplemental_raw_for_report: str = ""
    episodic_harness: Dict[str, Any] = field(default_factory=dict)
    shadow_handle: Any = None
    history_messages: List[Dict[str, Any]] = field(default_factory=list)
    augmented_message: str = ""
    pre_status: List[str] = field(default_factory=list)
    pre_results: List[Dict[str, Any]] = field(default_factory=list)
    patient_state: str = ""
    soul_base: Optional[str] = None
    fast_path: bool = False
    chat_messages: List[Dict[str, Any]] = field(default_factory=list)
    request_locale: Optional[str] = None
    response_locale: str = "en"
    grounded_fallback_applied: bool = False
    grounded_fallback_from_profile: str = ""


def iter_turn_harness_assembly_phase(
    ctx: TurnSlotContext,
    phase_rec: ChatTurnPhaseRecorder,
) -> Iterator[str]:
    """SLOT_ASSEMBLY + TIER0_ASSEMBLE + chat message stack (pre-LLM)."""
    from pha.attachment_asset_qa import (
        is_attachment_grounded_profile,
        is_attachment_qa_profile,
    )
    from pha.session_turn_focus import focus_summary_from_parsed
    from pha.wearable_harness import is_wearable_screenshot_profile

    uid = ctx.uid
    sid = ctx.sid
    msg = ctx.msg
    plan = ctx.plan
    parsed_payload = ctx.parsed_payload

    phase_rec.enter(ChatTurnPhase.SLOT_ASSEMBLY)
    if parsed_payload and is_wearable_screenshot_profile(plan.profile):
        from pha.wearable_snapshot_v1 import build_wearable_snapshot_tier0_block
        from pha.wearable_compare_table_v1 import (
            build_wearable_compare_table_v1,
            compare_table_from_parsed,
            compare_table_to_llm_markdown_focused,
            infer_single_metric_focus_ids,
            persist_compare_table_to_parsed,
        )

        ctx.wearable_snapshot_block = build_wearable_snapshot_tier0_block(parsed_payload)
        if "WEARABLE_COMPARE_TABLE" in plan.slots_tier0:
            ctx.wearable_compare_table_obj = compare_table_from_parsed(parsed_payload)
            if ctx.wearable_compare_table_obj is None:
                ctx.wearable_compare_table_obj = build_wearable_compare_table_v1(
                    parsed_payload,
                    user_id=uid,
                    user_message=ctx.raw_user_msg,
                )
            _focus_ids = infer_single_metric_focus_ids(ctx.raw_user_msg)
            if _focus_ids:
                ctx.wearable_compare_table_block = compare_table_to_llm_markdown_focused(
                    ctx.wearable_compare_table_obj,
                    _focus_ids,
                )
            else:
                ctx.wearable_compare_table_block = ctx.wearable_compare_table_obj.to_llm_markdown()
            persist_compare_table_to_parsed(parsed_payload, ctx.wearable_compare_table_obj)
            _persist_parse_msg_id = ctx.user_row_id if ctx.paths_in else None
            if not _persist_parse_msg_id and sid:
                from pha.chat_storage import get_latest_session_attachment_message_id

                _persist_parse_msg_id = get_latest_session_attachment_message_id(sid or "")
            if _persist_parse_msg_id and parsed_payload.get("wearable_metrics"):
                update_message_parsed_json(
                    _persist_parse_msg_id,
                    json.dumps(parsed_payload, ensure_ascii=False),
                )
            from dataclasses import replace
            from pha.wearable_harness import build_wearable_screenshot_review_task

            plan = replace(
                plan,
                task_text=build_wearable_screenshot_review_task(ctx.wearable_compare_table_obj),
            )
            ctx.plan = plan
    elif parsed_payload:
        ctx.attachment_label_block = focus_summary_from_parsed(parsed_payload)

    # Stage 3H-γ: specialized lane insufficient → safe fallback to grounded (never lifestyle).
    from pha.attachment_grounded_fallback import try_specialized_fallback_to_grounded

    _fb = try_specialized_fallback_to_grounded(
        plan=plan,
        parsed=parsed_payload,
        wearable_compare_table=ctx.wearable_compare_table_obj,
        user_id=uid,
        user_message=msg,
    )
    if _fb is not None:
        plan = _fb.plan
        ctx.plan = plan
        ctx.grounded_fallback_applied = True
        ctx.grounded_fallback_from_profile = _fb.from_profile
        ctx.wearable_screenshot_review = False
        ctx.attachment_asset_qa = False
        ctx.wearable_compare_table_obj = None
        ctx.wearable_compare_table_block = ""
        ctx.wearable_snapshot_block = ""
        ctx.wearable_summary = ""
        ctx.numerics_manifest = None
        ctx.manifest_block = ""
        ctx.background_block = ""
        ctx.attachment_label_block = _fb.attachment_label
        ctx.data_availability_block = _fb.data_availability_block
        yield json.dumps(
            {
                "event": "status",
                "                message": "📎 正在依据本次上传的内容为您解读",
            },
            ensure_ascii=False,
        )

    from pha.wearable_metric_probe import (
        infer_requested_compare_metric_ids,
        probe_wearable_metric_needs,
    )

    _probe_compare = ctx.wearable_screenshot_review or (
        bool(infer_requested_compare_metric_ids(ctx.raw_user_msg))
        and user_message_needs_wearable_query(ctx.raw_user_msg)
    )
    if _probe_compare:
        ctx.wearable_metric_probe_payload = probe_wearable_metric_needs(uid, ctx.raw_user_msg)
        _probe_msg = str(ctx.wearable_metric_probe_payload.get("user_message_zh") or "").strip()
        if _probe_msg and not ctx.wearable_metric_probe_payload.get("all_ready"):
            yield json.dumps(
                {
                    "event": "status",
                    "message": f"📦 数据探针：{_probe_msg}",
                    "open_data_drawer": bool(
                        ctx.wearable_metric_probe_payload.get("ingest_modules"),
                    ),
                },
                ensure_ascii=False,
            )

    if is_attachment_qa_profile(plan.profile):
        from pha.attachment_asset_qa import build_attachment_supplement_context
        from pha.data_availability import build_data_availability_block
        from pha.attachment_asset_qa import attachment_evidence_scope_enabled

        focus_text = ctx.attachment_label_block or ctx.raw_user_msg
        ctx.background_block = build_attachment_supplement_context(
            uid,
            focus_text=focus_text,
            session_focus_summary="",
            include_causal_anchor=(ctx.qa_mode == "lipid_bridge"),
            user_message=msg,
        )
        ctx.data_availability_block = (
            build_data_availability_block(uid, user_message=msg)
            if attachment_evidence_scope_enabled()
            else ""
        )
    elif is_attachment_grounded_profile(plan.profile):
        from pha.data_availability import build_data_availability_block

        # Stage 3H 通用兜底：仅注入库内概况（只读，不可作数字源），
        # 物理隔离数仓历史 + 补剂背景，强制就图论事。
        ctx.data_availability_block = build_data_availability_block(uid, user_message=msg)
        ctx.background_block = ""
    else:
        ctx.background_block = build_user_background_block(uid, user_message=msg)

    if not (
        is_attachment_qa_profile(plan.profile)
        or is_attachment_grounded_profile(plan.profile)
    ):
        _context_unused, recalled_rows = build_chat_context_block(
            uid,
            sid,
            msg,
            extra_system_context="",
            suppress_stale_assistant_recall=should_strip_polluted_assistant_history(msg),
        )
        ctx.recalled_snippets = _format_recalled_snippets(recalled_rows)

    ctx.audit_md, ctx.audit_json, ctx.audit_warn = build_chat_audit_payload(
        uid,
        ctx.temporal_intent,
        user_message=msg,
    )

    if "WEARABLE_90D_SUMMARY" in plan.slots_tier0:
        from pha.grounded_answer_composer import is_warehouse_metric_focus_turn

        _wm_focus_turn = plan.profile == "wearable_only" and is_warehouse_metric_focus_turn(msg)
        if _wm_focus_turn:
            ctx.wearable_summary = ""
        elif is_wearable_screenshot_profile(plan.profile):
            from pha.harness_plan import build_wearable_90d_macro_summary_block

            ctx.wearable_summary = build_wearable_90d_macro_summary_block(uid, msg)
        else:
            ctx.wearable_summary = build_wearable_90d_summary_block(uid, msg)

    if "EVIDENCE_CATALOG" in plan.slots_tier0:
        ctx.catalog_block = build_evidence_catalog_block(
            profile=plan.profile,
            user_message=msg,
            user_id=uid,
        )

    if "NUMERICS_MANIFEST" in plan.slots_tier0:
        ctx.numerics_manifest = build_numerics_manifest(
            uid,
            profile=plan.profile,
            user_message=msg,
            include_wearable=not ctx.catalog_turn,
        )
        ctx.manifest_block = format_manifest_tier0_block(
            ctx.numerics_manifest,
            profile=plan.profile,
        )

    supplement_slot = ctx.background_block
    if ctx.extra_system_context.strip():
        supplement_slot = (
            f"{ctx.background_block}\n\n{ctx.extra_system_context}".strip()
            if ctx.background_block
            else ctx.extra_system_context
        )

    if "METADATA_CATALOG" in plan.all_slots:
        from pha.metadata_catalog import build_metadata_catalog_block

        ctx.metadata_block = build_metadata_catalog_block(
            uid,
            user_message=msg,
            profile=plan.profile,
        )

    from pha.health_session_focus_store import episodic_all_profiles_enabled, health_episodic_bridge_block

    if episodic_all_profiles_enabled():
        from pha.attachment_asset_qa import is_attachment_qa_profile as _is_attach_profile

        if not _is_attach_profile(plan.profile):
            ctx.episodic_bridge_block = health_episodic_bridge_block(
                ctx.health_episodic_focus or ctx.route_focus,
            )

    user_context_brief_block = ""
    if "USER_CONTEXT_BRIEF" in plan.slots_tier1:
        from pha.chb_compiler import build_user_context_brief_block, user_context_brief_enabled

        if user_context_brief_enabled():
            user_context_brief_block = build_user_context_brief_block(
                uid,
                profile=plan.profile,
            )

    ctx.slot_contents = {
        "TASK": plan.task_text,
        "EPISODIC_BRIDGE": ctx.episodic_bridge_block,
        "ATTACHMENT_LABEL": ctx.attachment_label_block,
        "WEARABLE_SNAPSHOT": ctx.wearable_snapshot_block,
        "WEARABLE_COMPARE_TABLE": ctx.wearable_compare_table_block,
        "DATA_AVAILABILITY": ctx.data_availability_block
        if (
            is_attachment_qa_profile(plan.profile)
            or is_attachment_grounded_profile(plan.profile)
        )
        else "",
        "EVIDENCE_CATALOG": ctx.catalog_block,
        "NUMERICS_MANIFEST": ctx.manifest_block,
        "METADATA_CATALOG": ctx.metadata_block,
        "LDL_AUTHORITY": ctx.ldl_authority,
        "SUPPLEMENT_BG": supplement_slot,
        "DOSSIER_CLINICAL_COMPACT": ctx.forced_dossier,
        "DOSSIER_LAB": ctx.forced_dossier,
        "WEARABLE_90D_SUMMARY": ctx.wearable_summary,
        "AUDIT": ctx.audit_warn,
        "RECALL": ctx.recalled_snippets,
        "USER_CONTEXT_BRIEF": user_context_brief_block,
    }

    from pha.health_intent_catalog import profile_allows_active_recall_ledger

    _recall_ledger_ok = profile_allows_active_recall_ledger(plan.profile)
    _focus_active = _recall_ledger_ok and bool(
        ctx.attachment_asset_qa
        or ctx.wearable_screenshot_review
        or (ctx.route_focus and ctx.route_focus.active)
        or (ctx.session_focus_row and ctx.session_focus_row.active),
    )
    if sid and _focus_active:
        from pha.active_recall_ledger import build_recall_focus_block, sync_ledger_after_turn

        _ledger = sync_ledger_after_turn(
            sid,
            parsed_payload=parsed_payload if ctx.has_parse else None,
            slot_contents=ctx.slot_contents,
            user_message=msg,
            profile=plan.profile,
            focus_tokens=ctx.focus_tokens,
            source_turn=2 if ctx.qa_mode in ("episodic_bridge", "lipid_bridge") else 1,
            focus_active=True,
        )
        ctx.recall_focus_block = build_recall_focus_block(
            _ledger,
            parse_confidence=str((parsed_payload or {}).get("parse_confidence") or ""),
        )
        ctx.slot_contents["RECALL_FOCUS"] = ctx.recall_focus_block

    phase_rec.enter(ChatTurnPhase.TIER0_ASSEMBLE)
    ctx.tier0_supp, ctx.tier1_supp, _missing_slots, ctx.tier0_integrity = assemble_tiered_supplemental(
        plan=plan,
        slot_contents=ctx.slot_contents,
    )
    if is_attachment_qa_profile(plan.profile):
        from pha.attachment_asset_qa import ATTACHMENT_QA_SOUL_ADDENDUM

        ctx.tier1_supp = (
            f"{ATTACHMENT_QA_SOUL_ADDENDUM.strip()}\n\n---\n\n{ctx.tier1_supp}".strip()
            if ctx.tier1_supp
            else ATTACHMENT_QA_SOUL_ADDENDUM.strip()
        )
    ctx.supplemental_raw_for_report = f"{ctx.tier0_supp}\n\n---\n\n{ctx.tier1_supp}".strip()

    from pha.health_session_focus_store import episodic_report_meta

    ctx.episodic_harness = episodic_report_meta(
        turn_scope=ctx.health_turn_scope,
        bridge_injected=bool(ctx.episodic_bridge_block),
        recall_focus_injected=bool(ctx.recall_focus_block),
        focus_goal=(
            getattr(ctx.health_episodic_focus, "focus_goal", "") or ""
            if ctx.health_episodic_focus is not None
            else ""
        ),
        focus_domains=(
            list(getattr(ctx.health_episodic_focus, "focus_domains", None) or [])
            if ctx.health_episodic_focus is not None
            else []
        ),
    )

    from pha.shadow_routing import maybe_start_shadow_job
    from pha.universal_catalog_manager import get_catalog_manager

    _shadow_mgr = get_catalog_manager()
    _shadow_catalog_ids = _shadow_mgr.catalog_asset_ids_for_profile(
        plan.profile,
        user_message=msg,
        user_id=uid,
    )
    ctx.shadow_handle = maybe_start_shadow_job(
        msg,
        authoritative_profile=plan.profile,
        authoritative_catalog_ids=_shadow_catalog_ids,
        user_id=uid,
        metadata_catalog_excerpt=(ctx.metadata_block or "")[:1200],
    )

    if ctx.attach_parse_failed:
        ctx.tier1_supp = f"{ATTACH_PARSE_FAILURE_ADDENDUM}\n\n---\n\n{ctx.tier1_supp}".strip()

    ctx.history_messages = _session_history_messages(
        sid,
        max_turns=CHAT_HISTORY_MAX_TURNS,
        exclude_current_user=True,
        strip_polluted_assistant=should_strip_polluted_assistant_history(msg),
    )

    if ctx.audit_md:
        yield json.dumps(
            {
                "event": "audit",
                "data_pipeline_audit": ctx.audit_json,
                "markdown": ctx.audit_md,
                "warning_banner": ctx.audit_warn,
            },
            ensure_ascii=False,
        )

    ctx.augmented_message = msg
    if plan_allows_heuristic_snapshot(plan, user_message=msg):
        _, ctx.pre_status, ctx.pre_results = apply_health_heuristic_override(msg, uid)
        for st in ctx.pre_status:
            yield json.dumps({"event": "status", "message": st}, ensure_ascii=False)
        if ctx.pre_results and ctx.pre_results[0].get("result"):
            snap_body = str((ctx.pre_results[0].get("result") or {}).get("analytics_snapshot") or "")
            if snap_body.strip():
                ctx.wearable_summary = (
                    f"【Evidence · 穿戴预计算摘要 · 勿与补剂/化验混读】\n{snap_body.strip()}"
                )
                ctx.slot_contents["WEARABLE_90D_SUMMARY"] = ctx.wearable_summary
                ctx.tier0_supp, ctx.tier1_supp, _, ctx.tier0_integrity = assemble_tiered_supplemental(
                    plan=plan,
                    slot_contents=ctx.slot_contents,
                )
                ctx.supplemental_raw_for_report = f"{ctx.tier0_supp}\n\n---\n\n{ctx.tier1_supp}".strip()

    if "PATIENT_STATE_LAB" in plan.all_slots or "PATIENT_STATE_WEARABLE" in plan.all_slots:
        if not is_wearable_screenshot_profile(plan.profile):
            from pha.evidence_lane import wearable_block_has_user_snapshot

            ctx.patient_state = build_patient_state_evidence_slice(
                uid,
                msg,
                question_type=ctx.qtype,
                has_wearable_user_snapshot=wearable_block_has_user_snapshot(ctx.wearable_summary),
                parsed_overlay=parsed_payload,
                reference_date=effective_query_reference_date(),
            )

    if is_attachment_qa_profile(plan.profile):
        from pha.attachment_asset_qa import PHA_ATTACHMENT_SOUL_MINIMAL

        ctx.soul_base = PHA_ATTACHMENT_SOUL_MINIMAL
    elif is_wearable_screenshot_profile(plan.profile):
        from pha.wearable_harness import PHA_WEARABLE_SOUL_MINIMAL

        ctx.soul_base = PHA_WEARABLE_SOUL_MINIMAL
    else:
        ctx.soul_base = (
            PHA_MEDICAL_SOUL_LITE_SYSTEM_PROMPT if ctx.qtype == QuestionType.CASUAL else None
        )

    soul = (ctx.soul_base or PHA_MEDICAL_SOUL_SYSTEM_PROMPT).strip()
    ref = effective_query_reference_date()
    tiered_system = _cap_system_tiered(
        soul_with_anchor=build_system_date_block(ref) + soul,
        tier0_supplemental=ctx.tier0_supp,
        tier1_supplemental=ctx.tier1_supp,
    )
    soul_t0_len = len(build_system_date_block(ref) + soul) + len(ctx.tier0_supp or "")
    if soul_t0_len > SYSTEM_CONTENT_MAX_CHARS - 200:
        errs = list(ctx.tier0_integrity.get("errors") or [])
        if "cap_system_tiered_overflow" not in errs:
            errs.append("cap_system_tiered_overflow")
        ctx.tier0_integrity["errors"] = sorted(set(errs))

    ctx.fast_path = (
        plan.profile == "wearable_only"
        and bool(ctx.wearable_summary)
        and not _message_needs_lab_ledger(msg)
    )
    if ctx.fast_path:
        tiered_system = f"{tiered_system}\n\n{FAST_PATH_SYSTEM_ADDENDUM}".strip()

    from pha.response_language import append_language_directive, resolve_response_locale

    ctx.response_locale = resolve_response_locale(
        ctx.raw_user_msg,
        request_locale=ctx.request_locale,
    )
    tiered_system = append_language_directive(tiered_system, ctx.response_locale)

    ctx.chat_messages = build_pha_chat_message_stack(
        supplemental_system="",
        history_messages=ctx.history_messages,
        patient_state=ctx.patient_state,
        current_user_message=msg,
        raw_user_message=msg,
        medical_soul_base=ctx.soul_base,
        tiered_system=tiered_system,
        recall_focus_user_block=ctx.recall_focus_block,
    )
