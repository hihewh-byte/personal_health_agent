"""Stage 3F-α — declarative goal classification (C-layer, no profile selection)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from pha.health_intent_catalog import (
    catalog_goal_markers,
    infer_metrics_from_message,
    message_matches_goal_class,
)
from pha.intent_gates import user_message_is_casual


def goal_classifier_enabled() -> bool:
    return (os.environ.get("PHA_GOAL_CLASSIFIER") or "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )


@dataclass(frozen=True)
class GoalClassification:
    goal_class: str
    confidence: float
    source: str


def classify_goal(user_message: str) -> GoalClassification:
    msg = (user_message or "").strip()
    if not msg:
        return GoalClassification("casual", 1.0, "empty")

    if user_message_is_casual(msg):
        return GoalClassification("casual", 1.0, "casual_gate")

    metrics = infer_metrics_from_message(msg)
    if metrics:
        return GoalClassification("metric_specific", 1.0, "explicit_metric")

    if message_matches_goal_class(msg, "holistic_assessment"):
        return GoalClassification("holistic_assessment", 1.0, "catalog")

    return GoalClassification("metric_specific", 0.5, "default")


def goal_session_anchor_enabled() -> bool:
    if not goal_classifier_enabled():
        return False
    return (os.environ.get("PHA_GOAL_SESSION_ANCHOR") or "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def clarify_intent_scope_enabled() -> bool:
    """3F-γ: holistic intent_scope / data_gap clarify (rollback via unset)."""
    if not goal_classifier_enabled():
        return False
    return (os.environ.get("PHA_CLARIFY_INTENT_SCOPE") or "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )


__all__ = [
    "GoalClassification",
    "classify_goal",
    "clarify_intent_scope_enabled",
    "goal_classifier_enabled",
    "goal_session_anchor_enabled",
]
