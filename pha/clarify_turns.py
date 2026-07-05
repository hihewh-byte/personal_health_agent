"""Stage 3C-δ — clarify turn SSE short-circuit + chip scope resolution."""

from __future__ import annotations

import json
import os
from typing import Any

from pha.health_turn_resolver import HealthTurnScope

CLARIFY_PENDING_JSON_KEY = "pha_clarify_pending"

CLARIFY_TASK = (
    "用户需先澄清年份/指标后再作答；本轮仅展示选项，勿编造化验数字或 Patient State 内容。"
)

CLARIFY_FORBIDDEN_SLOTS = [
    "USER_SNAPSHOT",
    "USER_SNAPSHOT_IN_RAW_USER",
    "GET_HEALTH_DATA",
    "GET_TEMPORAL_HISTORY_DOSSIER",
    "DOSSIER_CLINICAL_COMPACT",
    "DOSSIER_LAB",
    "EVIDENCE_CATALOG",
    "METADATA_CATALOG",
    "SUPPLEMENT_BG",
    "LDL_AUTHORITY",
    "NUMERICS_MANIFEST",
    "RECALL",
    "fetch_evidence_by_id",
    "PATIENT_STATE_LAB",
    "PATIENT_STATE_WEARABLE",
    "WEARABLE_90D_SUMMARY",
    "WEARABLE_SNAPSHOT",
    "WEARABLE_COMPARE_TABLE",
    "ATTACHMENT_LABEL",
    "DATA_AVAILABILITY",
    "EPISODIC_BRIDGE",
]


def clarify_turns_enabled() -> bool:
    return (os.environ.get("PHA_CLARIFY_TURNS") or "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def clarify_scope_storage_dict(scope: HealthTurnScope) -> dict[str, Any]:
    window = scope.wearable_window.to_dict() if scope.wearable_window is not None else None
    return {
        "metric_keys": list(scope.metric_keys),
        "metric_source": scope.metric_source,
        "lab_years": list(scope.lab_years),
        "year_source": scope.year_source,
        "wearable_window": window,
        "time_source": scope.time_source,
        "profile_hint": scope.profile_hint,
        "focus_profile": scope.focus_profile,
        "needs_clarification": scope.needs_clarification,
        "clarify_kind": scope.clarify_kind,
        "clarify_prompt": scope.clarify_prompt,
        "clarify_choices": list(scope.clarify_choices or []),
        "attachment_qa_mode": scope.attachment_qa_mode,
    }


def clarify_scope_from_storage_dict(data: dict[str, Any]) -> HealthTurnScope:
    from datetime import date

    from pha.health_episodic_focus import WearableWindow

    window = None
    raw_window = data.get("wearable_window")
    if isinstance(raw_window, dict):
        try:
            window = WearableWindow(
                start=date.fromisoformat(str(raw_window.get("start"))),
                end=date.fromisoformat(str(raw_window.get("end"))),
            )
        except (TypeError, ValueError):
            window = None
    return HealthTurnScope(
        metric_keys=[str(m) for m in (data.get("metric_keys") or [])],
        metric_source=str(data.get("metric_source") or "default"),
        lab_years=[int(y) for y in (data.get("lab_years") or [])],
        year_source=str(data.get("year_source") or "default"),
        wearable_window=window,
        time_source=str(data.get("time_source") or "default"),
        profile_hint=data.get("profile_hint"),
        focus_profile=data.get("focus_profile"),
        needs_clarification=bool(data.get("needs_clarification")),
        clarify_kind=data.get("clarify_kind"),
        clarify_prompt=data.get("clarify_prompt"),
        clarify_choices=list(data.get("clarify_choices") or []),
        attachment_qa_mode=data.get("attachment_qa_mode"),
    )


def persist_pending_clarify_scope(session_id: str, scope: HealthTurnScope, *, message_id: int) -> None:
    from pha.chat_storage import update_message_parsed_json

    payload = {CLARIFY_PENDING_JSON_KEY: clarify_scope_storage_dict(scope)}
    update_message_parsed_json(message_id, json.dumps(payload, ensure_ascii=False))


def load_pending_clarify_scope(session_id: str) -> HealthTurnScope | None:
    from pha.chat_storage import list_messages

    sid = (session_id or "").strip()
    if not sid:
        return None
    for row in reversed(list_messages(sid)):
        if row.role != "assistant":
            continue
        raw = (row.parsed_json or "").strip()
        if not raw:
            continue
        try:
            doc = json.loads(raw)
        except json.JSONDecodeError:
            continue
        pending = doc.get(CLARIFY_PENDING_JSON_KEY)
        if isinstance(pending, dict):
            return clarify_scope_from_storage_dict(pending)
    return None


def _find_catalog_clarify_choice(choice_id: str) -> dict[str, Any] | None:
    from pha.health_intent_catalog import load_health_intent_catalog

    cid = (choice_id or "").strip()
    if not cid:
        return None
    kinds = load_health_intent_catalog().get("clarify_kinds") or {}
    for kind_cfg in kinds.values():
        if not isinstance(kind_cfg, dict):
            continue
        for choice in kind_cfg.get("choices") or []:
            if str(choice.get("id")) == cid:
                return dict(choice)
    return None


def _resolve_catalog_clarify_choice(choice: dict[str, Any]) -> HealthTurnScope | None:
    payload = dict(choice.get("payload") or {})
    action = str(payload.get("action") or "")
    if action == "intent_scope":
        hint = str(payload.get("profile_hint") or "combined_review")
        from pha.health_intent_catalog import catalog_holistic_proxy_metrics

        proxy = catalog_holistic_proxy_metrics() or ["ldl"]
        return HealthTurnScope(
            metric_keys=list(proxy[:3]),
            metric_source="explicit",
            profile_hint=hint,
            focus_profile=hint,
            needs_clarification=False,
        )
    if action == "continue_session":
        fp = str(payload.get("focus_profile") or "")
        return HealthTurnScope(
            metric_source="focus",
            profile_hint=fp or None,
            focus_profile=fp or None,
            needs_clarification=False,
        )
    lab_years = payload.get("lab_years")
    if lab_years:
        return HealthTurnScope(
            metric_keys=["ldl"],
            metric_source="explicit",
            lab_years=[int(y) for y in lab_years],
            year_source="explicit",
            profile_hint="lab_cross_year",
            needs_clarification=False,
        )
    return None


def build_clarify_sse_payload(scope: HealthTurnScope) -> dict[str, Any]:
    return {
        "event": "clarify",
        "kind": scope.clarify_kind or "lab_year",
        "prompt": scope.clarify_prompt or "请选择一项以继续。",
        "choices": list(scope.clarify_choices or []),
        "turn_scope": scope.to_report_dict(),
    }


def build_clarify_answer_text(scope: HealthTurnScope) -> str:
    return (scope.clarify_prompt or "请选择一项以继续。").strip()


def resolve_scope_from_clarify_choice(
    choice_id: str,
    *,
    pending_scope: HealthTurnScope | None = None,
    available_lab_years: list[int] | None = None,
    session_id: str | None = None,
) -> HealthTurnScope:
    cid = (choice_id or "").strip()
    if not cid:
        raise ValueError("empty clarify choice_id")

    if pending_scope is None and session_id:
        pending_scope = load_pending_clarify_scope(session_id)

    if pending_scope and pending_scope.clarify_choices:
        for choice in pending_scope.clarify_choices:
            if str(choice.get("id")) == cid:
                payload = dict(choice.get("payload") or {})
                if payload.get("action") == "intent_scope":
                    hint = str(payload.get("profile_hint") or "combined_review")
                    from pha.health_intent_catalog import catalog_holistic_proxy_metrics

                    proxy = catalog_holistic_proxy_metrics() or ["ldl"]
                    return HealthTurnScope(
                        metric_keys=list(proxy[:3]),
                        metric_source="explicit",
                        profile_hint=hint,
                        focus_profile=hint,
                        needs_clarification=False,
                    )
                if payload.get("action") == "continue_session":
                    fp = str(payload.get("focus_profile") or pending_scope.focus_profile or "")
                    metric_keys = list(pending_scope.metric_keys or [])
                    if not metric_keys:
                        from pha.health_intent_catalog import infer_metrics_from_message

                        metric_keys = infer_metrics_from_message(
                            str(pending_scope.clarify_prompt or ""),
                        )
                    return HealthTurnScope(
                        metric_keys=metric_keys,
                        metric_source="focus",
                        lab_years=list(pending_scope.lab_years),
                        year_source="focus",
                        profile_hint=fp or pending_scope.profile_hint,
                        focus_profile=fp or pending_scope.focus_profile,
                        needs_clarification=False,
                    )
                lab_years = payload.get("lab_years") or [int(cid)]
                metric_keys = list(pending_scope.metric_keys or ["ldl"])
                return HealthTurnScope(
                    metric_keys=metric_keys,
                    metric_source="explicit",
                    lab_years=[int(y) for y in lab_years],
                    year_source="explicit",
                    profile_hint="lab_cross_year",
                    focus_profile=pending_scope.focus_profile,
                    needs_clarification=False,
                )

    catalog_choice = _find_catalog_clarify_choice(cid)
    if catalog_choice is not None:
        resolved = _resolve_catalog_clarify_choice(catalog_choice)
        if resolved is not None:
            return resolved

    year = int(cid)
    allowed = {int(y) for y in (available_lab_years or []) if int(y) > 0}
    if allowed and year not in allowed:
        raise ValueError(f"clarify choice year {year} not in available lab years")
    return HealthTurnScope(
        metric_keys=["ldl"],
        metric_source="explicit",
        lab_years=[year],
        year_source="explicit",
        profile_hint="lab_cross_year",
        needs_clarification=False,
    )


def emit_clarify_harness_turn_complete(
    *,
    user_id: str,
    session_id: str,
    user_message_id: int | None,
    model: str,
    user_message: str,
    scope: HealthTurnScope,
    temporal_years: list[int] | None = None,
) -> None:
    from pha.harness_plan import build_clarify_turn_plan
    from pha.harness_report import (
        HarnessTurnInputs,
        build_harness_report,
        build_harness_telemetry,
        emit_harness_build_report,
    )
    from pha.health_session_focus_store import episodic_report_meta

    plan = build_clarify_turn_plan(scope)
    episodic_meta = episodic_report_meta(
        turn_scope=scope,
        bridge_injected=False,
        recall_focus_injected=False,
    )
    telemetry = build_harness_telemetry(
        user_id=user_id,
        user_message=user_message,
        plan_profile=plan.profile,
        background_block_nonempty=False,
    )
    telemetry["intent_route"]["clarify_short_circuit"] = True
    h_done = HarnessTurnInputs(
        user_id=user_id,
        session_id=session_id,
        user_message_id=user_message_id,
        model=model,
        user_message=user_message,
        question_type=plan.legacy_question_type,
        temporal_years=list(temporal_years or []),
        augmented_user_message=user_message,
        mode="turn_complete",
        turn_plan=plan,
        plan_vs_actual=[],
        runtime_mode="clarify_short_circuit",
        intent_route=telemetry["intent_route"],
        catalog_existence=telemetry["catalog_existence"],
        dynamic_slots=telemetry["dynamic_slots"],
        turn_scope=dict(episodic_meta.get("turnScope") or {}),
        episodic=dict(episodic_meta.get("episodic") or {}),
    )
    emit_harness_build_report(build_harness_report(h_done))


__all__ = [
    "CLARIFY_FORBIDDEN_SLOTS",
    "CLARIFY_PENDING_JSON_KEY",
    "CLARIFY_TASK",
    "build_clarify_answer_text",
    "build_clarify_sse_payload",
    "clarify_scope_from_storage_dict",
    "clarify_scope_storage_dict",
    "clarify_turns_enabled",
    "emit_clarify_harness_turn_complete",
    "load_pending_clarify_scope",
    "persist_pending_clarify_scope",
    "resolve_scope_from_clarify_choice",
]
