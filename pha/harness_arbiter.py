"""Stage 3F-α — Harness Arbiter: authoritative profile after GoalClassifier + existence_probe."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from pha.catalog_existence import _probe_lipid_data, _probe_wearable_data
from pha.goal_classifier import GoalClassification, classify_goal, goal_classifier_enabled, goal_session_anchor_enabled, clarify_intent_scope_enabled
from pha.health_intent_catalog import (
    catalog_clarify_kind,
    catalog_holistic_proxy_metrics,
    infer_metrics_from_message,
    is_weak_episodic_followup,
    message_has_lab_marker,
    message_matches_goal_class,
)
from pha.health_turn_resolver import HealthTurnScope


def _should_continue_holistic_goal(
    user_message: str,
    *,
    goal: GoalClassification,
    episodic: Any,
) -> bool:
    if episodic is None or (getattr(episodic, "focus_goal", "") or "") != "holistic_assessment":
        return False
    if infer_metrics_from_message(user_message):
        return False
    if message_has_lab_marker(user_message) and goal.goal_class != "holistic_assessment":
        return False
    if goal.goal_class == "holistic_assessment":
        return True
    if is_weak_episodic_followup(user_message):
        from pha.health_intent_catalog import (
            is_advisory_episodic_followup,
            is_weak_close_followup,
        )

        if is_weak_close_followup(user_message) or is_advisory_episodic_followup(
            user_message,
        ):
            return False
        return True
    if message_matches_goal_class(user_message, "holistic_assessment"):
        return True
    return False


@dataclass(frozen=True)
class ArbiterDecision:
    goal_class: str
    goal_source: str
    router_profile: str
    authoritative_profile: str
    reason: str
    existence_probe: dict[str, bool]
    turn_scope: HealthTurnScope | None = None

    def to_report_dict(self) -> dict[str, Any]:
        return {
            "authoritative_profile": self.authoritative_profile,
            "router_profile": self.router_profile,
            "reason": self.reason,
            "existence_probe": dict(self.existence_probe),
        }


def probe_domain_availability(
    user_id: str,
    *,
    existence_override: dict[str, bool] | None = None,
) -> dict[str, bool]:
    if existence_override is not None:
        return {
            "lab": bool(existence_override.get("lab")),
            "wearable": bool(existence_override.get("wearable")),
        }
    uid = (user_id or "default").strip() or "default"
    lab_ok, _ = _probe_lipid_data(uid)
    wear_ok, _ = _probe_wearable_data(uid)
    return {"lab": lab_ok, "wearable": wear_ok}


def _build_intent_scope_clarify(
    *,
    prompt: str,
    choices: list[dict[str, Any]],
    probe: dict[str, bool],
) -> HealthTurnScope:
    proxy = catalog_holistic_proxy_metrics() or ["ldl"]
    return HealthTurnScope(
        metric_keys=list(proxy[:3]),
        metric_source="default",
        needs_clarification=True,
        clarify_kind="intent_scope",
        clarify_prompt=prompt,
        clarify_choices=choices,
        profile_hint="combined_review",
    )


def _build_data_gap_clarify(*, prompt: str) -> HealthTurnScope:
    kind = catalog_clarify_kind("data_gap") or {}
    choices = list(kind.get("choices") or [])
    return HealthTurnScope(
        needs_clarification=True,
        clarify_kind="data_gap",
        clarify_prompt=prompt or str(kind.get("prompt_template") or "库内暂无足够数据域，请先导入化验或穿戴数据。"),
        clarify_choices=choices,
    )


def _intent_scope_clarify_scope(probe: dict[str, bool]) -> HealthTurnScope:
    kind = catalog_clarify_kind("intent_scope") or {}
    prompt = str(kind.get("prompt_template") or "您希望基于库内哪些数据做综合评估？")
    all_choices = list(kind.get("choices") or [])
    choices: list[dict[str, Any]] = []
    for choice in all_choices:
        domains = list(choice.get("domains") or [])
        if not domains:
            choices.append(dict(choice))
            continue
        if domains == ["lab", "wearable"] and probe.get("lab") and probe.get("wearable"):
            choices.append(dict(choice))
        elif domains == ["lab"] and probe.get("lab"):
            choices.append(dict(choice))
        elif domains == ["wearable"] and probe.get("wearable"):
            choices.append(dict(choice))
    if not choices:
        return _build_data_gap_clarify(prompt="库内暂无足够化验或穿戴数据，请先导入后再试。")
    return _build_intent_scope_clarify(prompt=prompt, choices=choices, probe=probe)


def resolve_harness_arbiter(
    user_message: str,
    *,
    user_id: str,
    router_profile: str,
    turn_scope: HealthTurnScope | None = None,
    goal: GoalClassification | None = None,
    existence_override: dict[str, bool] | None = None,
    episodic: Any = None,
) -> ArbiterDecision | None:
    if not goal_classifier_enabled():
        return None

    msg = (user_message or "").strip()
    if turn_scope is not None and turn_scope.needs_clarification:
        return None

    goal = goal or classify_goal(msg)
    probe = probe_domain_availability(user_id, existence_override=existence_override)
    router = (router_profile or "lifestyle").strip() or "lifestyle"

    if goal_session_anchor_enabled() and _should_continue_holistic_goal(
        msg,
        goal=goal,
        episodic=episodic,
    ):
        if probe.get("lab") and probe.get("wearable"):
            return ArbiterDecision(
                goal_class=goal.goal_class,
                goal_source=goal.source,
                router_profile=router,
                authoritative_profile="combined_review",
                reason="episodic_goal_continue",
                existence_probe=probe,
            )

    if goal.goal_class == "holistic_assessment":
        if probe.get("lab") and probe.get("wearable"):
            return ArbiterDecision(
                goal_class=goal.goal_class,
                goal_source=goal.source,
                router_profile=router,
                authoritative_profile="combined_review",
                reason="goal_holistic_upgrade",
                existence_probe=probe,
            )
        if not clarify_intent_scope_enabled():
            if probe.get("lab"):
                return ArbiterDecision(
                    goal_class=goal.goal_class,
                    goal_source=goal.source,
                    router_profile=router,
                    authoritative_profile="lab_cross_year",
                    reason="goal_single_domain_lab",
                    existence_probe=probe,
                )
            if probe.get("wearable"):
                return ArbiterDecision(
                    goal_class=goal.goal_class,
                    goal_source=goal.source,
                    router_profile=router,
                    authoritative_profile="wearable_only",
                    reason="goal_single_domain_wearable",
                    existence_probe=probe,
                )
            return ArbiterDecision(
                goal_class=goal.goal_class,
                goal_source=goal.source,
                router_profile=router,
                authoritative_profile=router,
                reason="schema_default",
                existence_probe=probe,
            )
        if probe.get("lab") or probe.get("wearable"):
            scope = _intent_scope_clarify_scope(probe)
            return ArbiterDecision(
                goal_class=goal.goal_class,
                goal_source=goal.source,
                router_profile=router,
                authoritative_profile="clarify",
                reason="goal_clarify_scope",
                existence_probe=probe,
                turn_scope=scope,
            )
        scope = _build_data_gap_clarify(
            prompt=str(
                (catalog_clarify_kind("data_gap") or {}).get("prompt_template")
                or "库内暂无化验或穿戴数据，请先导入后再做综合评估。",
            ),
        )
        return ArbiterDecision(
            goal_class=goal.goal_class,
            goal_source=goal.source,
            router_profile=router,
            authoritative_profile="clarify",
            reason="goal_clarify_data_gap",
            existence_probe=probe,
            turn_scope=scope,
        )

    return ArbiterDecision(
        goal_class=goal.goal_class,
        goal_source=goal.source,
        router_profile=router,
        authoritative_profile=router,
        reason="schema_default",
        existence_probe=probe,
    )


def merge_arbiter_turn_scope(
    turn_scope: HealthTurnScope | None,
    decision: ArbiterDecision | None,
) -> HealthTurnScope | None:
    if decision is None or decision.turn_scope is None:
        return turn_scope
    if turn_scope is None:
        return decision.turn_scope
    return replace(
        turn_scope,
        needs_clarification=decision.turn_scope.needs_clarification,
        clarify_kind=decision.turn_scope.clarify_kind,
        clarify_prompt=decision.turn_scope.clarify_prompt,
        clarify_choices=list(decision.turn_scope.clarify_choices or []),
        profile_hint=decision.turn_scope.profile_hint or turn_scope.profile_hint,
    )


__all__ = [
    "ArbiterDecision",
    "merge_arbiter_turn_scope",
    "probe_domain_availability",
    "resolve_harness_arbiter",
]
