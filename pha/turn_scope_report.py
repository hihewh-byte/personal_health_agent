"""Harness turnScope serialization for HealthTurnResolver (Stage 3C-α)."""

from __future__ import annotations

from typing import Any

from pha.health_turn_resolver import HealthTurnScope


def turn_scope_to_report_dict(scope: HealthTurnScope) -> dict[str, Any]:
    window = None
    if scope.wearable_window is not None:
        window = scope.wearable_window.to_dict()
    return {
        "metricKeys": list(scope.metric_keys),
        "metricSource": scope.metric_source,
        "labYears": list(scope.lab_years),
        "yearSource": scope.year_source,
        "wearableWindow": window,
        "timeSource": scope.time_source,
        "episodicRevived": bool(scope.episodic_revived),
        "focusProfile": scope.focus_profile or scope.profile_hint,
        "turnsRemaining": scope.turns_remaining,
        "needsClarification": scope.needs_clarification,
        "clarifyKind": scope.clarify_kind,
        "attachmentQaMode": scope.attachment_qa_mode,
    }
