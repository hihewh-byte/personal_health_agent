"""P0 — Chat turn orchestrator (SSE state machine runner)."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from pha.structured_log import log_exception
from pha.agent import (
    AgentAnswer,
    EvidenceItem,
    _parse_cited_refs,
)
from pha.agent_tools import (
    FAST_PATH_SYSTEM_ADDENDUM,
    FAST_MODE_STATUS,
    PHA_AGENT_TOOLS,
    apply_health_heuristic_override,
    execute_tool_call,
    infer_auto_tool_fallback,
    message_has_health_snapshot,
    tool_status_message,
    SNAPSHOT_MARKER,
    MAX_TOOL_ROUNDS,
)
from pha.chat_background import (
    MAX_CHAT_BACKGROUND_CHARS,
    build_user_background_block,
    maybe_capture_chat_background,
)
from pha.intent_gates import (
    QuestionType,
    classify_question_type,
    resolve_ldl_authority_years,
    should_inject_wearable_snapshot,
    should_strip_polluted_assistant_history,
    user_message_is_casual,
    user_message_needs_attachment_recall,
    user_message_needs_lab_dossier,
    user_message_needs_wearable_query,
)
from pha.chat_context import build_chat_context_block, extract_health_keywords, recent_turns
from pha.chat_storage import list_messages, search_messages_by_keywords
from pha.chat_router import (
    build_chat_audit_payload,
    build_ldl_authority_system_block,
    log_harness_payload,
    prepare_chat_evidence_bundle,
    probe_temporal_route,
)
from pha.chat_storage import (
    append_message,
    create_session,
    get_session,
    maybe_set_title_from_first_message,
    update_message_parsed_json,
)
from pha.event_medical import metrics_preview_dicts, narratives_preview_dicts
from pha.health_data import (
    build_system_date_block,
    effective_query_reference_date,
)
from pha.llm_provider import OllamaProvider
from pha.chat_ingest import ingest_chat_message, ingest_parsed_payload
from pha.patient_state import build_patient_state_evidence_slice
from pha.harness_plan import (
    TurnEvidencePlan,
    assemble_tiered_supplemental,
    build_turn_evidence_plan,
    build_wearable_90d_summary_block,
)
from pha.evidence_catalog import (
    build_evidence_catalog_block,
    catalog_mode_enabled,
    format_fetched_evidence_text,
)
from pha.grounded_answer_composer import grounded_composer_enabled
from pha.numerics_manifest import (
    NumericsManifest,
    apply_numerics_audit_to_answer,
    audit_response_numerics,
    build_numerics_manifest,
    format_manifest_tier0_block,
    numerics_audit_mode,
    numerics_require_citation,
)

logger = logging.getLogger(__name__)

from pha.chat_message_stack import (  # noqa: E402
    ATTACH_PARSE_FAILURE_ADDENDUM,
    CHAT_HISTORY_MAX_CHARS,
    CHAT_HISTORY_MAX_TURNS,
    PATIENT_STATE_USER_PREAMBLE,
    PHA_MEDICAL_SOUL_LITE_SYSTEM_PROMPT,
    PHA_MEDICAL_SOUL_SYSTEM_PROMPT,
    SLOW_PATH_CHAT_STAGES,
    SYSTEM_CONTENT_MAX_CHARS,
    _build_supplemental_system_layers,
    _cap_system_content,
    _cap_system_tiered,
    _format_recalled_snippets,
    _merge_user_message,
    _session_history_messages,
    build_pha_chat_message_stack,
)
from pha.chat_attachments import (  # noqa: E402
    _message_needs_lab_ledger,
    _vision_parse_attachment,
    compute_attachment_ingest_status,
    parse_chat_attachment_file,
    record_chat_attachment_parse_failure,
)
from pha.chat_agent_runtime import (  # noqa: E402
    _agent_tools_for_plan,
    _catalog_stream_messages,
    _resolve_runtime_mode,
    _run_catalog_fetch_phase,
    _run_tool_loop_then_stream,
    _runtime_status_message,
)
from pha.chat_skip_llm import evaluate_skip_llm_path  # noqa: E402
from pha.chat_turn_fsm import ChatTurnPhase, ChatTurnPhaseRecorder  # noqa: E402
from pha.chat_turn_harness_report import HarnessEmitContext, emit_turn_harness_report  # noqa: E402
from pha.chat_turn_routing import resolve_turn_routing  # noqa: E402


def orchestrate_chat_turn_events(
    *,
    user_id: str,
    user_message: str,
    model: str,
    session_id: Optional[str] = None,
    extra_system_context: str = "",
    attachment_path: Optional[str] = None,
    attachment_name: Optional[str] = None,
    attachment_paths: Optional[List[str]] = None,
    attachment_names: Optional[List[str]] = None,
    attachment_parsed_parts: Optional[List[Dict[str, Any]]] = None,
    clarify_choice_id: Optional[str] = None,
    response_locale: Optional[str] = None,
) -> Iterator[str]:
    """
    Yield SSE payloads (JSON per ``data:`` line content):
    status | delta | done | error
    """
    uid = (user_id or "default").strip() or "default"
    _phase_rec = ChatTurnPhaseRecorder()
    _phase_rec.enter(ChatTurnPhase.INIT)
    msg = (user_message or "").strip()
    _paths_in = [p.strip() for p in (attachment_paths or []) if (p or "").strip()]
    if not _paths_in and (attachment_path or "").strip():
        _paths_in = [(attachment_path or "").strip()]
    _names_in = [n.strip() for n in (attachment_names or []) if (n or "").strip()]
    if not msg and not _paths_in:
        yield json.dumps({"event": "error", "message": "消息不能为空"}, ensure_ascii=False)
        return
    if not msg and _paths_in:
        from pha.response_language import resolve_response_locale

        _attach_loc = resolve_response_locale("", request_locale=response_locale)
        if _attach_loc == "en":
            msg = (
                "Using the attachment and Current Patient State ledger, interpret each lab "
                "metric (name | value | reference range). Do not reply with generic wellness templates."
            )
        else:
            msg = "请根据附件与 Current Patient State 事实账本，逐项解读化验指标（指标 | 数值 | 参考），勿输出空泛健康模板。"

    # Step 0: hard temporal intercept — SSE status before any heavy work
    temporal_probe = probe_temporal_route(msg)
    if temporal_probe.is_temporal_dynamic:
        from pha.temporal_router import build_temporal_status_message

        for stage_idx, stage_msg in enumerate(SLOW_PATH_CHAT_STAGES, start=1):
            yield json.dumps(
                {
                    "event": "status",
                    "type": "status",
                    "message": stage_msg,
                    "status": stage_msg,
                    "slow_path_stage": stage_idx,
                    "is_temporal_dynamic": True,
                    "years": temporal_probe.explicit_years,
                },
                ensure_ascii=False,
            )
        temporal_msg = build_temporal_status_message(temporal_probe)
        yield json.dumps(
            {
                "event": "status",
                "type": "status",
                "message": temporal_msg,
                "status": temporal_msg,
                "is_temporal_dynamic": True,
                "years": temporal_probe.explicit_years,
            },
            ensure_ascii=False,
        )

    sid = session_id
    if sid:
        if not get_session(sid, uid):
            yield json.dumps({"event": "error", "message": "会话不存在"}, ensure_ascii=False)
            return
    else:
        sess = create_session(uid)
        sid = sess.id
    _phase_rec.enter(ChatTurnPhase.SESSION)

    att_path = _paths_in[0] if len(_paths_in) == 1 else json.dumps(_paths_in, ensure_ascii=False)
    att_name = (
        _names_in[0]
        if len(_names_in) == 1
        else " + ".join(_names_in[:4])
        if _names_in
        else (attachment_name or "").strip()
    )
    raw_user_msg = (msg or "").strip()
    parsed_payload: Optional[Dict[str, Any]] = None
    attach_parse_failed = False
    attachment_asset_qa = False
    attach_status_suffix = ""
    attach_client_reuse = False
    user_row = append_message(
        sid,
        "user",
        msg,
        attachment_path=att_path,
        attachment_name=att_name,
    )
    _prior_user_msg = ""
    if sid:
        _user_hist = [
            str(m.content).strip()
            for m in reversed(list_messages(sid))
            if m.role == "user" and (m.content or "").strip()
        ]
        if len(_user_hist) >= 2:
            _prior_user_msg = _user_hist[1]
    maybe_set_title_from_first_message(sid, msg)
    from pha.dynamic_slot_registry import on_background_captured, on_request_start

    slot_turn_meta = on_request_start(uid, msg)
    stored_bg, bg_reject = maybe_capture_chat_background(
        uid,
        msg,
        session_id=sid,
        source_message_id=user_row.id,
    )
    if stored_bg:
        on_background_captured(uid, msg)
    if bg_reject == "background_too_long":
        yield json.dumps(
            {
                "event": "status",
                "code": "background_too_long",
                "message": (
                    f"生活背景摘录表单次最长 {MAX_CHAT_BACKGROUND_CHARS} 字，已跳过写入（本条对话正文已照常保存）。"
                    "请分多次或分条目发送补剂/生活记录，以免摘录表静默截断。"
                ),
            },
            ensure_ascii=False,
        )

    if not temporal_probe.is_temporal_dynamic:
        yield json.dumps(
            {
                "event": "status",
                "message": "正在组装健康证据与语义历史上下文…",
                "session_id": sid,
                "model": model,
            },
            ensure_ascii=False,
        )

    from pha.chat_turn_perception import TurnAttachmentContext, iter_attachment_upload_phase, iter_session_parse_reuse_phase

    _attach_ctx = TurnAttachmentContext(
        uid=uid,
        sid=sid or "",
        msg=msg,
        raw_user_msg=raw_user_msg,
        prior_user_msg=_prior_user_msg,
        paths_in=_paths_in,
        names_in=_names_in,
        att_path=att_path,
        att_name=att_name,
        user_row_id=user_row.id,
        parsed_payload=parsed_payload,
        attach_status_suffix=attach_status_suffix,
        attach_client_reuse=attach_client_reuse,
        attach_parse_failed=attach_parse_failed,
    )
    if _paths_in:
        _phase_rec.enter(ChatTurnPhase.PERCEPTION)
        yield from iter_attachment_upload_phase(_attach_ctx)
    if not _attach_ctx.parsed_payload and not _paths_in and sid:
        _phase_rec.enter(ChatTurnPhase.PARSE_REUSE)
        yield from iter_session_parse_reuse_phase(_attach_ctx)
    parsed_payload = _attach_ctx.parsed_payload
    msg = _attach_ctx.msg
    attach_status_suffix = _attach_ctx.attach_status_suffix
    attach_client_reuse = _attach_ctx.attach_client_reuse
    attach_parse_failed = _attach_ctx.attach_parse_failed

    audit_md = ""
    audit_json: Dict[str, Any] = {}
    audit_warn = ""
    _health_turn_scope = None
    _health_episodic_focus = None
    _episodic_bridge_block = ""
    _arbiter_decision = None
    _arbiter_auth_profile = None
    try:
        _phase_rec.enter(ChatTurnPhase.EVIDENCE_PROBE)
        _, temporal_intent, temporal_status, _, is_temporal_dynamic, fusion_stats = (
            prepare_chat_evidence_bundle(
                uid,
                msg,
                extra_system_context=extra_system_context,
                intent=temporal_probe,
                build_dossier=False,
            )
        )
        yield json.dumps(
            {
                "event": "status",
                "type": "status",
                "message": temporal_status,
                "status": temporal_status,
                "is_temporal_dynamic": is_temporal_dynamic,
                "years": temporal_intent.explicit_years,
                "metrics_fused": fusion_stats.metric_rows,
            },
            ensure_ascii=False,
        )

        provider = OllamaProvider(model=model.strip())

        from pha.health_session_focus_store import (
            available_lab_years_for_user,
            episodic_all_profiles_enabled,
            episodic_report_meta,
            health_episodic_bridge_block,
            health_episodic_runtime_enabled,
            load_health_session_focus,
            record_health_turn_focus,
            revive_health_session_focus,
        )
        from pha.health_turn_resolver import resolve_health_turn_scope
        from pha.clarify_turns import (
            build_clarify_answer_text,
            build_clarify_sse_payload,
            clarify_turns_enabled,
            emit_clarify_harness_turn_complete,
            persist_pending_clarify_scope,
            resolve_scope_from_clarify_choice,
        )

        _lab_years_available = available_lab_years_for_user(uid)
        if health_episodic_runtime_enabled() or clarify_turns_enabled():
            _health_episodic_focus = (
                revive_health_session_focus(sid or "", raw_user_msg)
                or load_health_session_focus(sid or "")
            )
            if clarify_turns_enabled() and (clarify_choice_id or "").strip():
                _health_turn_scope = resolve_scope_from_clarify_choice(
                    clarify_choice_id or "",
                    available_lab_years=_lab_years_available,
                    session_id=sid or "",
                )
            else:
                _health_turn_scope = resolve_health_turn_scope(
                    raw_user_msg,
                    episodic=_health_episodic_focus,
                    available_lab_years=_lab_years_available,
                    response_locale=response_locale,
                )
            from pha.health_intent_catalog import (
                health_intent_catalog_enabled,
                is_session_anchor_profile,
                resolve_inherited_focus_profile,
            )

            if (
                health_intent_catalog_enabled()
                and _health_episodic_focus
                and _health_episodic_focus.focus_profile
                and not (clarify_turns_enabled() and (clarify_choice_id or "").strip())
            ):
                inherited = resolve_inherited_focus_profile(
                    raw_user_msg,
                    focus_profile=_health_episodic_focus.focus_profile,
                    profile_hint=_health_turn_scope.profile_hint if _health_turn_scope else None,
                )
                if inherited and _health_turn_scope is not None:
                    from dataclasses import replace

                    if is_session_anchor_profile(_health_episodic_focus.focus_profile or ""):
                        inherited = _health_episodic_focus.focus_profile
                    _health_turn_scope = replace(
                        _health_turn_scope,
                        focus_profile=inherited,
                        profile_hint=inherited,
                    )

        from pha.goal_classifier import goal_classifier_enabled

        if goal_classifier_enabled():
            from pha.harness_arbiter import merge_arbiter_turn_scope, resolve_harness_arbiter
            from pha.intent_gates import resolve_schema_intent as _resolve_schema_for_arbiter

            _router_for_arbiter = _resolve_schema_for_arbiter(raw_user_msg)
            _arbiter_decision = resolve_harness_arbiter(
                raw_user_msg,
                user_id=uid,
                router_profile=_router_for_arbiter.profile,
                turn_scope=_health_turn_scope,
                episodic=_health_episodic_focus,
            )
            if _arbiter_decision is not None:
                _health_turn_scope = merge_arbiter_turn_scope(
                    _health_turn_scope,
                    _arbiter_decision,
                )
                _auth = (_arbiter_decision.authoritative_profile or "").strip()
                if _auth:
                    _arbiter_auth_profile = _auth

        if (
            clarify_turns_enabled()
            and _health_turn_scope
            and _health_turn_scope.needs_clarification
            and not (clarify_choice_id or "").strip()
        ):
            _phase_rec.enter(ChatTurnPhase.CLARIFY)
            yield json.dumps(
                build_clarify_sse_payload(_health_turn_scope),
                ensure_ascii=False,
            )
            clarify_text = build_clarify_answer_text(_health_turn_scope)
            assistant_row = append_message(sid, "assistant", clarify_text)
            persist_pending_clarify_scope(
                sid or "",
                _health_turn_scope,
                message_id=assistant_row.id,
            )
            emit_clarify_harness_turn_complete(
                user_id=uid,
                session_id=sid or "",
                user_message_id=user_row.id,
                model=model.strip(),
                user_message=msg,
                scope=_health_turn_scope,
                temporal_years=list(temporal_intent.explicit_years or []),
            )
            yield json.dumps(
                {
                    "event": "done",
                    "session_id": sid,
                    "clarify": True,
                    "model": model.strip(),
                    "assistant_message_id": assistant_row.id,
                    "turn_scope": _health_turn_scope.to_report_dict(),
                    "answer": {
                        "answer_text": clarify_text,
                        "evidence_items": [],
                        "model_reply_raw": clarify_text,
                    },
                },
                ensure_ascii=False,
            )
            return

        from pha.attachment_asset_qa import (
            build_lipid_bridge_snapshot_block,
            focus_tokens_from_text,
        )
        from pha.session_turn_focus import (
            consume_session_turn_focus,
            focus_summary_from_parsed,
            get_session_turn_focus,
            revive_session_turn_focus_for_message,
            save_session_turn_focus,
        )

        _has_parse = False
        from pha.perception_family import attachment_parse_is_actionable, family_from_parsed

        if parsed_payload:
            _has_parse = attachment_parse_is_actionable(parsed_payload)
        _existing_focus = get_session_turn_focus(sid or "")
        _route_focus = revive_session_turn_focus_for_message(sid or "", raw_user_msg) or _existing_focus
        _focus_tokens = list(_route_focus.focus_tokens) if _route_focus else []
        _attach_family = family_from_parsed(parsed_payload) if parsed_payload else ""
        if user_message_needs_wearable_query(raw_user_msg) and _route_focus and _route_focus.active:
            _prev_doc = str(_route_focus.document_type or "").strip().lower()
            if _prev_doc in ("supplement", "supplement_label", ""):
                from pha.session_turn_focus import clear_session_turn_focus

                clear_session_turn_focus(sid or "")
                _route_focus = None
                _focus_tokens = []
        _routing = resolve_turn_routing(
            raw_user_msg,
            health_turn_scope=_health_turn_scope,
            health_episodic_focus=_health_episodic_focus,
            route_focus=_route_focus,
            parsed_payload=parsed_payload,
            paths_in=_paths_in,
            has_parse=_has_parse,
            attach_family=_attach_family,
        )
        _qa_mode = _routing.qa_mode
        wearable_screenshot_review = _routing.wearable_screenshot_review
        attachment_asset_qa = _routing.attachment_asset_qa
        attachment_grounded_review = _routing.attachment_grounded_review
        _health_turn_scope = _routing.health_turn_scope
        session_focus_row = None
        if _qa_mode in ("lipid_bridge", "episodic_bridge"):
            session_focus_row = consume_session_turn_focus(sid or "")
            if not session_focus_row and _route_focus:
                session_focus_row = _route_focus
        elif _has_parse and parsed_payload:
            _fsum = focus_summary_from_parsed(parsed_payload)
            _ftoks = focus_tokens_from_text(_fsum)
            _doc_type = str(
                parsed_payload.get("document_family")
                or parsed_payload.get("document_type")
                or "unknown",
            )
            if _doc_type not in ("wearable", "apple_watch") and _attach_family != "wearable":
                if (
                    _route_focus
                    and _route_focus.active
                    and _route_focus.document_type
                    and _doc_type != _route_focus.document_type
                    and _doc_type in ("wearable", "supplement", "lab")
                ):
                    from pha.session_turn_focus import clear_session_turn_focus

                    clear_session_turn_focus(sid or "")
                save_session_turn_focus(
                    sid or "",
                    focus_summary=_fsum,
                    document_type=_doc_type,
                    focus_tokens=_ftoks,
                )
            if attachment_asset_qa:
                session_focus_row = get_session_turn_focus(sid or "")

        _phase_rec.enter(ChatTurnPhase.ROUTE_QA)
        plan = build_turn_evidence_plan(
            msg,
            is_temporal_dynamic=is_temporal_dynamic,
            attachment_asset_qa=attachment_asset_qa,
            attachment_qa_mode=_qa_mode if attachment_asset_qa else "initial",
            wearable_screenshot_review=wearable_screenshot_review,
            attachment_grounded_review=attachment_grounded_review,
            turn_scope=_health_turn_scope,
            authoritative_profile=_arbiter_auth_profile,
        )
        _phase_rec.enter(ChatTurnPhase.PLAN)
        qtype = plan.legacy_question_type

        ldl_authority = ""
        if "LDL_AUTHORITY" in plan.all_slots:
            if _qa_mode == "lipid_bridge":
                ldl_authority = build_lipid_bridge_snapshot_block(uid)
            else:
                ldl_years = resolve_ldl_authority_years(uid, msg, temporal_intent)
                if ldl_years:
                    ldl_authority = build_ldl_authority_system_block(uid, ldl_years)

        forced_dossier = ""
        build_forced_dossier = (
            "DOSSIER_CLINICAL_COMPACT" in plan.all_slots or "DOSSIER_LAB" in plan.all_slots
        )
        catalog_turn = "fetch_evidence_by_id" in set(plan.tools_allowed or [])
        if build_forced_dossier and not catalog_turn and (
            user_message_needs_lab_dossier(msg) or plan.profile == "combined_review"
        ):
            forced_dossier, temporal_intent, dossier_status, _, is_temporal_dynamic, fusion_stats = (
                prepare_chat_evidence_bundle(
                    uid,
                    msg,
                    intent=temporal_intent,
                    build_dossier=True,
                    omit_ldl_fusion_blocks=plan.profile != "lab_cross_year",
                    compact_clinical_only=(plan.profile == "combined_review"),
                )
            )
            yield json.dumps(
                {
                    "event": "status",
                    "message": dossier_status,
                    "is_temporal_dynamic": is_temporal_dynamic,
                    "years": temporal_intent.explicit_years,
                    "metrics_fused": fusion_stats.metric_rows,
                },
                ensure_ascii=False,
            )

        session_focus_summary = ""
        from pha.chat_turn_slots import TurnSlotContext, iter_turn_harness_assembly_phase

        _slot_ctx = TurnSlotContext(
            uid=uid,
            sid=sid or "",
            msg=msg,
            raw_user_msg=raw_user_msg,
            plan=plan,
            qtype=qtype,
            parsed_payload=parsed_payload,
            temporal_intent=temporal_intent,
            extra_system_context=extra_system_context,
            ldl_authority=ldl_authority,
            forced_dossier=forced_dossier,
            catalog_turn=catalog_turn,
            attach_parse_failed=attach_parse_failed,
            has_parse=_has_parse,
            paths_in=_paths_in,
            user_row_id=user_row.id,
            attachment_asset_qa=attachment_asset_qa,
            wearable_screenshot_review=wearable_screenshot_review,
            qa_mode=_qa_mode,
            route_focus=_route_focus,
            session_focus_row=session_focus_row,
            focus_tokens=_focus_tokens,
            health_turn_scope=_health_turn_scope,
            health_episodic_focus=_health_episodic_focus,
            episodic_bridge_block=_episodic_bridge_block,
            request_locale=response_locale,
        )
        yield from iter_turn_harness_assembly_phase(_slot_ctx, _phase_rec)
        plan = _slot_ctx.plan
        if _slot_ctx.grounded_fallback_applied:
            attachment_grounded_review = True
            attachment_asset_qa = False
            wearable_screenshot_review = False
            _qa_mode = "grounded"
        wearable_compare_table_obj = _slot_ctx.wearable_compare_table_obj
        wearable_metric_probe_payload = _slot_ctx.wearable_metric_probe_payload
        background_block = _slot_ctx.background_block
        recalled_snippets = _slot_ctx.recalled_snippets
        audit_md = _slot_ctx.audit_md
        audit_json = _slot_ctx.audit_json
        audit_warn = _slot_ctx.audit_warn
        numerics_manifest = _slot_ctx.numerics_manifest
        manifest_block = _slot_ctx.manifest_block
        slot_contents = _slot_ctx.slot_contents
        recall_focus_block = _slot_ctx.recall_focus_block
        tier0_supp = _slot_ctx.tier0_supp
        tier1_supp = _slot_ctx.tier1_supp
        tier0_integrity = _slot_ctx.tier0_integrity
        supplemental_raw_for_report = _slot_ctx.supplemental_raw_for_report
        _episodic_harness = _slot_ctx.episodic_harness
        if _arbiter_decision is not None and _arbiter_decision.reason in (
            "goal_holistic_upgrade",
            "episodic_goal_continue",
        ):
            _ep = _episodic_harness.setdefault("episodic", {})
            _ep["focusGoal"] = "holistic_assessment"
            _ep["focusDomains"] = [
                k for k, ok in (_arbiter_decision.existence_probe or {}).items() if ok
            ]
        shadow_handle = _slot_ctx.shadow_handle
        augmented_message = _slot_ctx.augmented_message
        pre_status = _slot_ctx.pre_status
        pre_results = _slot_ctx.pre_results
        patient_state = _slot_ctx.patient_state
        soul_base = _slot_ctx.soul_base
        fast_path = _slot_ctx.fast_path
        chat_messages = _slot_ctx.chat_messages
        wearable_summary = _slot_ctx.wearable_summary

        log_harness_payload(
            user_id=uid,
            intent=temporal_intent,
            stats=fusion_stats,
            system_prompt=str(chat_messages[0].get("content", "")) if chat_messages else "",
            user_message=msg,
        )

        plan_tools = _agent_tools_for_plan(plan)
        evidence_items: List[Any] = []
        runtime_mode = _resolve_runtime_mode(
            model.strip(),
            plan_tools,
            fast_path=fast_path,
            plan=plan,
        )

        harness_ctx = HarnessEmitContext(
            uid=uid,
            sid=sid or "",
            msg=msg,
            model=model.strip(),
            user_row_id=user_row.id,
            qtype=qtype,
            temporal_intent=temporal_intent,
            ldl_authority=ldl_authority,
            background_block=background_block,
            forced_dossier=forced_dossier,
            audit_warn=audit_warn,
            recalled_snippets=recalled_snippets,
            plan=plan,
            slot_contents=slot_contents,
            tier0_supp=tier0_supp,
            tier0_integrity=tier0_integrity,
            supplemental_raw_for_report=supplemental_raw_for_report,
            episodic_harness=_episodic_harness,
            augmented_message=augmented_message,
            patient_state=patient_state,
            fast_path=fast_path,
            runtime_mode=runtime_mode,
            numerics_manifest=numerics_manifest,
            manifest_block=manifest_block,
            qa_mode=_qa_mode,
            attachment_asset_qa=attachment_asset_qa,
            session_focus_row=session_focus_row,
            parsed_payload=parsed_payload,
            paths_in=_paths_in,
            attach_client_reuse=attach_client_reuse,
            build_forced_dossier=build_forced_dossier,
            arbiter_decision=(
                _arbiter_decision.to_report_dict() if _arbiter_decision is not None else None
            ),
            goal_class=_arbiter_decision.goal_class if _arbiter_decision else "",
            goal_source=_arbiter_decision.goal_source if _arbiter_decision else "",
        )

        _phase_rec.enter(ChatTurnPhase.PLAN_PRE_LLM)
        emit_turn_harness_report(
            harness_ctx,
            mode="plan_pre_llm",
            messages=chat_messages,
            tools=list(pre_results),
        )

        tool_results: List[Dict[str, Any]] = pre_results
        tool_status: List[str] = []
        _phase_rec.enter(ChatTurnPhase.SKIP_LLM_EVAL)
        _skip_eval = evaluate_skip_llm_path(
            plan=plan,
            user_id=uid,
            msg=msg,
            raw_user_msg=raw_user_msg,
            prior_user_msg=_prior_user_msg,
            parsed_payload=parsed_payload,
            attachment_asset_qa=attachment_asset_qa,
            wearable_screenshot_review=wearable_screenshot_review,
            qa_mode=_qa_mode,
            paths_in=_paths_in,
            numerics_manifest=numerics_manifest,
            wearable_compare_table_obj=wearable_compare_table_obj,
            response_locale=_slot_ctx.response_locale,
        )
        for _skip_ev in _skip_eval.status_events:
            yield json.dumps(_skip_ev, ensure_ascii=False)
        skip_llm = _skip_eval.skip_llm
        _det = _skip_eval.answer_text

        use_tools = runtime_mode == "tool_loop"
        use_catalog = runtime_mode == "catalog_tool_loop"
        _composer_follow_ups: Dict[str, Any] = {}
        if grounded_composer_enabled():
            from pha.grounded_answer_composer import (
                build_composer_meta_event,
                build_fact_card_event,
                build_follow_ups_event,
            )

            _scope_report = (
                _health_turn_scope.to_report_dict() if _health_turn_scope is not None else {}
            )
            yield json.dumps(
                build_composer_meta_event(
                    session_id=sid or "",
                    profile=plan.profile,
                    turn_scope=_scope_report,
                ),
                ensure_ascii=False,
            )
            _composer_manifest = numerics_manifest
            if _composer_manifest is None and plan.profile in (
                "wearable_only",
                "wearable_screenshot_review",
            ):
                from pha.grounded_answer_composer import try_warehouse_metric_focus_skip

                _wm_skip = try_warehouse_metric_focus_skip(
                    user_id=uid,
                    profile=plan.profile,
                    user_message=msg,
                    manifest=None,
                    response_locale=_slot_ctx.response_locale,
                )
                if _wm_skip or skip_llm:
                    _composer_manifest = build_numerics_manifest(
                        uid,
                        profile=plan.profile,
                        user_message=msg,
                        include_lipid=False,
                        include_wearable=True,
                    )
            if _composer_manifest is None and wearable_screenshot_review and skip_llm:
                _composer_manifest = build_numerics_manifest(
                    uid,
                    profile=plan.profile,
                    user_message=msg,
                    include_lipid=False,
                    include_wearable=True,
                )
            _fc = build_fact_card_event(_composer_manifest)
            if _fc:
                yield json.dumps(_fc, ensure_ascii=False)
            _composer_follow_ups = build_follow_ups_event(
                profile=plan.profile,
                metric_keys=list(_health_turn_scope.metric_keys) if _health_turn_scope else [],
            )
        _phase_rec.enter(ChatTurnPhase.COMPOSE)
        _phase_rec.assert_plan_before_compose()
        from pha.chat_turn_compose import TurnComposeContext, iter_compose_response_phase, iter_post_compose_audit_phase

        _compose_ctx = TurnComposeContext(
            skip_llm=skip_llm,
            det_text=_det,
            fast_path=fast_path,
            use_catalog=use_catalog,
            use_tools=use_tools,
            provider=provider,
            chat_messages=chat_messages,
            plan_tools=plan_tools,
            plan=plan,
            uid=uid,
            msg=msg,
            raw_user_msg=raw_user_msg,
            runtime_mode=runtime_mode,
            attachment_asset_qa=attachment_asset_qa,
            attach_status_suffix=attach_status_suffix,
            wearable_screenshot_review=wearable_screenshot_review,
            wearable_compare_table_obj=wearable_compare_table_obj,
            numerics_manifest=numerics_manifest,
            pre_results=pre_results,
            response_locale=_slot_ctx.response_locale,
        )
        yield from iter_compose_response_phase(_compose_ctx)
        raw = _compose_ctx.raw
        answer_text = _compose_ctx.answer_text
        cited = _compose_ctx.cited
        tool_results = _compose_ctx.tool_results
        tool_status = _compose_ctx.tool_status
        chat_messages = _compose_ctx.chat_messages
        numerics_manifest = _compose_ctx.numerics_manifest
        if _compose_ctx.manifest_block:
            manifest_block = _compose_ctx.manifest_block

        numerics_audit: Dict[str, Any] = {}
        compare_table_audit: Dict[str, Any] = {}
        _phase_rec.enter(ChatTurnPhase.POST_AUDIT)
        yield from iter_post_compose_audit_phase(_compose_ctx)
        answer_text = _compose_ctx.answer_text
        numerics_audit = _compose_ctx.numerics_audit
        compare_table_audit = _compose_ctx.compare_table_audit

        from pha.presentation_filter import polish_final_user_answer

        answer_text = polish_final_user_answer(
            answer_text or raw,
            profile=plan.profile,
            locale=_slot_ctx.response_locale,
        )
        _compose_ctx.answer_text = answer_text

        l3_focus_violation = False
        if attachment_asset_qa:
            from pha.telemetry_attachment import detect_l3_focus_violation

            l3_focus_violation = detect_l3_focus_violation(
                answer_text or raw,
                attachment_qa_mode=_qa_mode,
            )

        assistant_row = append_message(sid, "assistant", answer_text or raw)

        if episodic_all_profiles_enabled() and _health_turn_scope is not None:
            _record_fsum = ""
            _record_doc = ""
            if parsed_payload:
                _record_fsum = focus_summary_from_parsed(parsed_payload)
                _record_doc = str(
                    parsed_payload.get("document_family")
                    or parsed_payload.get("document_type")
                    or "",
                )
            record_health_turn_focus(
                sid or "",
                turn_scope=_health_turn_scope,
                harness_profile=plan.profile,
                user_message=raw_user_msg,
                assistant_reply=answer_text or raw,
                focus_summary=_record_fsum,
                document_type=_record_doc,
                skip_consume=bool(
                    session_focus_row and _qa_mode in ("lipid_bridge", "episodic_bridge"),
                ),
                arbiter_reason=(
                    _arbiter_decision.reason if _arbiter_decision is not None else ""
                ),
                existence_probe=(
                    dict(_arbiter_decision.existence_probe)
                    if _arbiter_decision is not None
                    else None
                ),
            )

        answer = AgentAnswer(
            user_id=uid,
            model=provider.model,
            answer_text=answer_text or raw,
            evidence_items=evidence_items,
            referenced_evidence_ref_ids=cited,
            model_reply_raw=raw,
            tool_status_messages=pre_status + tool_status,
            tool_results=tool_results,
        )
        done_payload: Dict[str, Any] = {
            "event": "done",
            "session_id": sid,
            "model": provider.model,
            "answer": answer.model_dump(mode="json"),
            "assistant_message_id": assistant_row.id,
            "harness": {
                "plan": {"profile": plan.profile},
                "qa_mode": _qa_mode,
                "grounded_fallback_applied": bool(_slot_ctx.grounded_fallback_applied),
            },
        }
        if audit_json:
            done_payload["data_pipeline_audit"] = audit_json
        if numerics_audit:
            done_payload["numerics_audit"] = numerics_audit
        if compare_table_audit:
            done_payload["compare_table_audit"] = compare_table_audit
        if wearable_metric_probe_payload:
            done_payload["wearable_metric_probe"] = wearable_metric_probe_payload

        shadow_payload: Dict[str, Any] = {}
        if shadow_handle is not None:
            from pha.shadow_routing import build_shadow_status_message

            shadow_payload = shadow_handle.collect()
            _shadow_status = build_shadow_status_message(shadow_payload)
            if _shadow_status:
                yield json.dumps({"event": "status", "message": _shadow_status}, ensure_ascii=False)

        emit_turn_harness_report(
            harness_ctx,
            mode="as_is_post_tools",
            messages=chat_messages,
            tools=tool_results,
        )
        emit_turn_harness_report(
            harness_ctx,
            mode="turn_complete",
            messages=chat_messages,
            tools=tool_results,
            numerics_audit=numerics_audit,
            shadow_routing=shadow_payload,
            l3_focus_violation=l3_focus_violation,
        )

        if parsed_payload:
            done_payload["ingest_payload"] = parsed_payload
            done_payload["user_message_id"] = user_row.id
            done_payload["ingest_status"] = compute_attachment_ingest_status(parsed_payload)
            done_payload["ingest_metrics_stored"] = int(
                (parsed_payload.get("ingest") or {}).get("metrics_stored") or 0,
            )
        if _composer_follow_ups:
            yield json.dumps(_composer_follow_ups, ensure_ascii=False)
        _phase_rec.enter(ChatTurnPhase.DONE)
        yield json.dumps(done_payload, ensure_ascii=False)
    except Exception as exc:
        _phase_rec.enter(ChatTurnPhase.ERROR)
        log_exception(
            logger,
            "stream_pha_chat_failed",
            exc,
            user_id=uid,
            session_id=sid,
        )
        yield json.dumps({"event": "error", "message": str(exc)}, ensure_ascii=False)
