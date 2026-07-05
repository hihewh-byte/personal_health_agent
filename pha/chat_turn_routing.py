"""P0 — Turn routing flags: resolver turn_scope / session anchor over phrase rules."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, List, Optional

from pha.attachment_asset_qa import resolve_attachment_qa_mode
from pha.health_intent_catalog import (
    health_intent_catalog_enabled,
    is_session_anchor_profile,
)
from pha.intent_gates import user_message_needs_wearable_query
from pha.wearable_harness import should_use_wearable_screenshot_review


@dataclass
class TurnRoutingDecision:
    qa_mode: str
    attachment_asset_qa: bool
    wearable_screenshot_review: bool
    session_anchor_profile: str
    health_turn_scope: Any
    attachment_grounded_review: bool = False


def _pick_focus_profile(*sources: Any) -> str:
    for src in sources:
        if src is None:
            continue
        fp = str(getattr(src, "focus_profile", None) or "").strip()
        if fp:
            return fp
    return ""


def _routing_from_session_anchor(
    anchor_fp: str,
    *,
    health_turn_scope: Any,
    has_parse: bool,
    parsed_payload: Any,
) -> TurnRoutingDecision | None:
    if not is_session_anchor_profile(anchor_fp):
        return None
    updated_scope = health_turn_scope
    if health_turn_scope and not (health_turn_scope.focus_profile or "").strip():
        updated_scope = replace(
            health_turn_scope,
            focus_profile=anchor_fp,
            profile_hint=anchor_fp,
        )
    if anchor_fp == "wearable_screenshot_review":
        return TurnRoutingDecision(
            qa_mode="none",
            attachment_asset_qa=False,
            wearable_screenshot_review=True,
            session_anchor_profile=anchor_fp,
            health_turn_scope=updated_scope,
        )
    return TurnRoutingDecision(
        qa_mode="none",
        attachment_asset_qa=False,
        wearable_screenshot_review=False,
        session_anchor_profile=anchor_fp,
        health_turn_scope=updated_scope,
    )


def resolve_turn_routing(
    raw_user_msg: str,
    *,
    health_turn_scope: Any,
    health_episodic_focus: Any,
    route_focus: Any,
    parsed_payload: Any,
    paths_in: List[str],
    has_parse: bool,
    attach_family: str,
) -> TurnRoutingDecision:
    """Resolve harness routing flags; session anchor / turn_scope beats phrase rules."""
    scope_fp = _pick_focus_profile(health_turn_scope)
    anchor_fp = scope_fp or _pick_focus_profile(
        health_episodic_focus,
        route_focus,
    )

    anchored = _routing_from_session_anchor(
        anchor_fp,
        health_turn_scope=health_turn_scope,
        has_parse=has_parse,
        parsed_payload=parsed_payload,
    )
    if anchored is not None:
        return anchored

    focus_tokens = list(route_focus.focus_tokens) if route_focus else []
    qa_mode = resolve_attachment_qa_mode(
        raw_user_msg,
        has_parsed_attachment=has_parse,
        session_focus_active=bool(route_focus and route_focus.active),
        focus_tokens=focus_tokens,
        document_family=attach_family,
        has_attachment_paths=bool(paths_in),
        parsed_payload=parsed_payload if isinstance(parsed_payload, dict) else None,
    )

    if health_intent_catalog_enabled() and health_turn_scope:
        fp = (health_turn_scope.focus_profile or "").strip()
        if fp in ("attachment_asset_qa", "attachment_episodic_bridge"):
            if route_focus and route_focus.active and qa_mode == "none":
                qa_mode = "episodic_bridge"
        elif fp == "wearable_only" and qa_mode != "none":
            if not has_parse and not user_message_needs_wearable_query(raw_user_msg):
                qa_mode = "none"

    wearable_screenshot_review = should_use_wearable_screenshot_review(
        document_family=attach_family,
        has_parsed_attachment=has_parse,
        user_message=raw_user_msg,
    )
    if (
        not paths_in
        and (has_parse or parsed_payload)
        and attach_family in ("wearable", "apple_watch")
    ):
        wearable_screenshot_review = True
        qa_mode = "none"

    updated_scope = health_turn_scope
    if (
        health_turn_scope
        and anchor_fp
        and not (health_turn_scope.focus_profile or "").strip()
    ):
        updated_scope = replace(
            health_turn_scope,
            focus_profile=anchor_fp,
            profile_hint=anchor_fp,
        )

    attachment_asset_qa = (
        not wearable_screenshot_review
        and qa_mode in ("initial", "lipid_bridge", "episodic_bridge")
    )
    attachment_grounded_review = (
        not wearable_screenshot_review and qa_mode == "grounded"
    )
    return TurnRoutingDecision(
        qa_mode=qa_mode,
        attachment_asset_qa=attachment_asset_qa,
        wearable_screenshot_review=wearable_screenshot_review,
        session_anchor_profile=anchor_fp,
        health_turn_scope=updated_scope,
        attachment_grounded_review=attachment_grounded_review,
    )


__all__ = ["TurnRoutingDecision", "resolve_turn_routing"]
