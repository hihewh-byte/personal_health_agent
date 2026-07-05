"""P0 — Harness report emission for chat turn lifecycle (plan_pre_llm → turn_complete)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from pha.agent_tools import SNAPSHOT_MARKER
from pha.chat_message_stack import SYSTEM_CONTENT_MAX_CHARS
from pha.harness_plan import TurnEvidencePlan, compute_plan_vs_actual, plan_allows_heuristic_snapshot
from pha.harness_report import (
    HarnessTurnInputs,
    build_harness_report,
    build_harness_telemetry,
    emit_harness_build_report,
)
from pha.intent_gates import QuestionType


@dataclass
class HarnessEmitContext:
    uid: str
    sid: str
    msg: str
    model: str
    user_row_id: int
    qtype: QuestionType
    temporal_intent: Any
    ldl_authority: str
    background_block: str
    forced_dossier: str
    audit_warn: str
    recalled_snippets: str
    plan: TurnEvidencePlan
    slot_contents: Dict[str, Any]
    tier0_supp: str
    tier0_integrity: Dict[str, Any]
    supplemental_raw_for_report: str
    episodic_harness: Dict[str, Any]
    augmented_message: str
    patient_state: str
    fast_path: bool
    runtime_mode: str
    numerics_manifest: Any
    manifest_block: str
    qa_mode: str
    attachment_asset_qa: bool
    session_focus_row: Any
    parsed_payload: Optional[Dict[str, Any]]
    paths_in: List[str]
    attach_client_reuse: bool
    build_forced_dossier: bool
    arbiter_decision: Dict[str, Any] | None = None
    goal_class: str = ""
    goal_source: str = ""


def build_turn_intent_route_telemetry(ctx: HarnessEmitContext) -> Dict[str, Any]:
    telemetry = build_harness_telemetry(
        user_id=ctx.uid,
        user_message=ctx.msg,
        plan_profile=ctx.plan.profile,
        background_block_nonempty=bool(ctx.background_block.strip()),
    )
    telemetry["intent_route"]["attachment_qa_mode"] = (
        ctx.qa_mode if ctx.attachment_asset_qa else "none"
    )
    if ctx.session_focus_row is not None:
        telemetry["intent_route"]["session_focus_turns_remaining"] = int(
            ctx.session_focus_row.turns_remaining,
        )
    if ctx.parsed_payload:
        from pha.telemetry_attachment import build_attachment_route_telemetry

        telemetry["intent_route"].update(
            build_attachment_route_telemetry(
                ctx.parsed_payload,
                attachment_path_count=len(ctx.paths_in) if ctx.paths_in else 0,
                client_parse_reuse=bool(
                    ctx.parsed_payload.get("client_parse_reuse") or ctx.attach_client_reuse
                ),
                attachment_qa_mode=ctx.qa_mode if ctx.attachment_asset_qa else "none",
            ),
        )
        telemetry["intent_route"]["vision_parse_confidence"] = str(
            ctx.parsed_payload.get("parse_confidence") or "",
        )
        telemetry["intent_route"]["document_type"] = str(
            ctx.parsed_payload.get("document_type") or "",
        )
    return telemetry


def emit_turn_harness_report(
    ctx: HarnessEmitContext,
    *,
    mode: str,
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    numerics_audit: Optional[Dict[str, Any]] = None,
    shadow_routing: Optional[Dict[str, Any]] = None,
    l3_focus_violation: Optional[bool] = None,
) -> None:
    executed = [str(t.get("tool") or "") for t in tools]
    pva = compute_plan_vs_actual(
        ctx.plan,
        raw_user_message=ctx.msg,
        current_user_message=str(messages[-1].get("content") or "") if messages else ctx.msg,
        tools_executed=executed,
        snapshot_in_user=SNAPSHOT_MARKER in str(messages[-1].get("content") or ""),
        slot_contents=ctx.slot_contents,
        tier0_text=ctx.tier0_supp,
        tier0_integrity=ctx.tier0_integrity,
    )
    telemetry = build_turn_intent_route_telemetry(ctx)
    if l3_focus_violation is not None:
        telemetry["intent_route"]["l3_focus_violation"] = l3_focus_violation
    h_in = HarnessTurnInputs(
        user_id=ctx.uid,
        session_id=ctx.sid or "",
        user_message_id=ctx.user_row_id,
        model=ctx.model.strip(),
        user_message=ctx.msg,
        question_type=ctx.qtype,
        temporal_years=list(ctx.temporal_intent.explicit_years or []),
        ldl_authority=ctx.ldl_authority,
        supplement_bg=ctx.background_block,
        forced_dossier=ctx.forced_dossier,
        audit_warn=ctx.audit_warn,
        recalled_snippets=ctx.recalled_snippets,
        patient_state=ctx.patient_state,
        augmented_user_message=ctx.augmented_message,
        raw_supplemental=ctx.supplemental_raw_for_report,
        system_after_stack=str(messages[0].get("content", "")) if messages else "",
        system_content_max=SYSTEM_CONTENT_MAX_CHARS,
        inject_wearable_snapshot=plan_allows_heuristic_snapshot(ctx.plan, user_message=ctx.msg),
        build_forced_dossier=ctx.build_forced_dossier,
        has_snapshot=SNAPSHOT_MARKER in ctx.augmented_message,
        fast_path=ctx.fast_path,
        use_tools_runtime=ctx.runtime_mode in ("tool_loop", "catalog_tool_loop"),
        tool_results=tools,
        chat_messages=messages,
        mode=mode,
        turn_plan=ctx.plan,
        plan_vs_actual=pva,
        tier0_integrity=ctx.tier0_integrity,
        runtime_mode=ctx.runtime_mode,
        numerics_manifest=ctx.numerics_manifest.to_dict() if ctx.numerics_manifest else {},
        numerics_manifest_block=ctx.manifest_block,
        intent_route=telemetry["intent_route"],
        catalog_existence=telemetry["catalog_existence"],
        dynamic_slots=telemetry["dynamic_slots"],
        numerics_audit=numerics_audit or {},
        metadata_catalog_block=ctx.slot_contents.get("METADATA_CATALOG") or "",
        shadow_routing=shadow_routing or {},
        turn_scope=dict(ctx.episodic_harness.get("turnScope") or {}),
        episodic=dict(ctx.episodic_harness.get("episodic") or {}),
        goal_class=ctx.goal_class or "",
        goal_source=ctx.goal_source or "",
        arbiter_decision=dict(ctx.arbiter_decision or {}),
    )
    emit_harness_build_report(build_harness_report(h_in))


__all__ = ["HarnessEmitContext", "build_turn_intent_route_telemetry", "emit_turn_harness_report"]
