"""HealthTurnResolver — unified in-session turn scope (Stage 3C-α)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from pha.date_range_parser import default_wearable_window, parse_user_date_range
from pha.health_data import effective_query_reference_date
from pha.health_episodic_focus import HealthSessionFocus, WearableWindow
from pha.health_intent_catalog import (
    catalog_session_anchor_label,
    catalog_weak_followup_max_chars,
    explicit_lab_record_request,
    explicit_profile_shift,
    extract_health_keywords,
    health_intent_catalog_enabled,
    infer_metrics_from_message,
    infer_profile_hint,
    is_session_anchor_profile,
    matches_anaphora,
    matches_multi_scope_lab,
    message_has_lab_marker,
    message_explicitly_requests_scope_choice,
    profile_episodic_continue,
    resolve_inherited_focus_profile,
)
from pha.temporal_router import extract_years_regex


def health_turn_resolver_enabled() -> bool:
    return (os.environ.get("PHA_HEALTH_TURN_RESOLVER") or "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )


@dataclass(frozen=True)
class HealthTurnScope:
    metric_keys: list[str] = field(default_factory=list)
    metric_source: str = "default"
    lab_years: list[int] = field(default_factory=list)
    year_source: str = "default"
    wearable_window: WearableWindow | None = None
    time_source: str = "default"
    profile_hint: str | None = None
    focus_profile: str | None = None
    episodic_revived: bool = False
    needs_clarification: bool = False
    clarify_kind: str | None = None
    clarify_prompt: str | None = None
    clarify_choices: list[dict[str, Any]] = field(default_factory=list)
    turns_remaining: int | None = None
    attachment_qa_mode: str | None = None

    def primary_metric(self) -> str:
        return self.metric_keys[0] if self.metric_keys else ""

    def to_report_dict(self) -> dict[str, Any]:
        from pha.turn_scope_report import turn_scope_to_report_dict

        return turn_scope_to_report_dict(self)


def _relative_lab_year_shift(message: str, anchor_years: list[int]) -> list[int] | None:
    msg = (message or "").strip()
    if not msg or not anchor_years:
        return None
    explicit = extract_years_regex(msg)
    if explicit:
        return explicit
    anchor = max(anchor_years)
    if re.search(r"前年", msg):
        return [anchor - 2]
    if re.search(r"去年|上一年", msg):
        return [anchor - 1]
    if re.search(r"今年|本年", msg):
        return [effective_query_reference_date().year]
    m = re.search(r"那\s*(\d{2})\s*年", msg)
    if m:
        yy = int(m.group(1))
        y = 2000 + yy if yy < 70 else 1900 + yy
        return [y]
    m4 = re.search(r"那\s*(20\d{2})\s*年", msg)
    if m4:
        return [int(m4.group(1))]
    return None


def _parse_relative_wearable_window(message: str, *, reference: date | None = None) -> WearableWindow | None:
    msg = (message or "").strip()
    ref = reference or effective_query_reference_date()
    if not msg:
        return None
    if re.search(r"上个月|上月", msg):
        first_this = ref.replace(day=1)
        end_prev = first_this - timedelta(days=1)
        start_prev = end_prev.replace(day=1)
        return WearableWindow(start=start_prev, end=end_prev)
    if re.search(r"这个月|本月", msg):
        start = ref.replace(day=1)
        return WearableWindow(start=start, end=ref)
    explicit = parse_user_date_range(msg)
    if explicit:
        return WearableWindow(start=explicit.start, end=explicit.end)
    return None


def _default_wearable_window(
    message: str,
    *,
    reference: date | None = None,
) -> WearableWindow:
    parsed = default_wearable_window(message, reference=reference)
    return WearableWindow(start=parsed.start, end=parsed.end)


def _topic_continues(
    message: str,
    episodic: HealthSessionFocus,
    profile_hint: str | None,
) -> bool:
    msg = (message or "").strip()
    if not msg:
        return False
    fp = episodic.focus_profile or ""
    if health_intent_catalog_enabled() and fp:
        from pha.health_intent_catalog import explicit_profile_shift, is_weak_episodic_followup

        if explicit_profile_shift(msg, fp):
            return False
        if is_weak_episodic_followup(msg) and profile_episodic_continue(fp):
            return True
    if matches_anaphora(msg):
        return True
    if profile_hint and fp and profile_hint == fp:
        return True
    if profile_episodic_continue(fp) and len(msg) <= 24:
        return True
    digest = (episodic.last_assistant_digest or "").strip()
    if digest:
        overlap = set(extract_health_keywords(msg)) & set(extract_health_keywords(digest))
        if overlap:
            return True
    return False


def _lab_years_from_data(available_lab_years: list[int] | None) -> list[int]:
    if not available_lab_years:
        return []
    return sorted({int(y) for y in available_lab_years if int(y) > 0})


def _build_clarify_choices(years: list[int]) -> list[dict[str, Any]]:
    return [
        {"id": str(y), "label": f"{y}年", "payload": {"lab_years": [y], "action": "lab_year"}}
        for y in years
    ]


def _episodic_profile_hint(episodic: HealthSessionFocus, hint: str | None) -> str | None:
    fp = (episodic.focus_profile or "").strip()
    if is_session_anchor_profile(fp):
        return fp or hint
    return hint or fp or None


def _continue_episodic_scope(
    msg: str,
    episodic: HealthSessionFocus,
    *,
    hint: str | None,
    ref: date,
    revived: bool,
    explicit_metrics: list[str],
    explicit_window: WearableWindow | None,
) -> HealthTurnScope:
    fp = episodic.focus_profile or ""
    return HealthTurnScope(
        metric_keys=explicit_metrics
        or ([episodic.focus_metric] if episodic.focus_metric else infer_metrics_from_message(msg)),
        metric_source="focus"
        if episodic.focus_metric and not explicit_metrics
        else ("explicit" if explicit_metrics else "default"),
        lab_years=list(episodic.focus_lab_years),
        year_source="focus" if episodic.focus_lab_years else "default",
        profile_hint=_episodic_profile_hint(episodic, hint),
        focus_profile=fp or None,
        wearable_window=explicit_window
        or episodic.focus_wearable_window
        or _default_wearable_window(msg, reference=ref),
        time_source="explicit" if explicit_window else "focus",
        episodic_revived=revived,
        turns_remaining=episodic.turns_remaining,
        attachment_qa_mode=resolve_attachment_qa_mode(msg, episodic),
    )


def _cross_domain_lab_ambiguity(
    msg: str,
    episodic: HealthSessionFocus,
    uploaded_years: list[int],
) -> bool:
    fp = (episodic.focus_profile or "").strip()
    if not is_session_anchor_profile(fp):
        return False
    if fp in ("lab_cross_year", "combined_review"):
        return False
    if not message_has_lab_marker(msg):
        return False
    if explicit_lab_record_request(msg):
        return False
    if explicit_profile_shift(msg, fp):
        return False
    return True


def _build_intent_scope_clarify(
    msg: str,
    episodic: HealthSessionFocus,
    *,
    hint: str | None,
    ref: date,
    uploaded_years: list[int],
    explicit_metrics: list[str],
    response_locale: str | None = None,
) -> HealthTurnScope:
    from pha.response_language import normalize_response_locale, resolve_response_locale

    loc = normalize_response_locale(response_locale) or resolve_response_locale(
        msg,
        request_locale=response_locale,
    )
    fp = episodic.focus_profile or ""
    ys = ", ".join(str(y) for y in uploaded_years)
    session_label = catalog_session_anchor_label(fp, locale=loc)
    if loc == "en":
        choices: list[dict[str, Any]] = [
            {
                "id": "continue_session",
                "label": f"Continue {session_label}",
                "payload": {"action": "continue_session", "focus_profile": fp},
            },
        ]
        for y in uploaded_years:
            choices.append(
                {
                    "id": f"lab_year_{y}",
                    "label": f"Year {y}",
                    "payload": {"action": "lab_year", "year": y},
                },
            )
    else:
        choices = [
            {
                "id": "continue_session",
                "label": f"继续{session_label}",
                "payload": {"action": "continue_session", "focus_profile": fp},
            },
        ]
        choices.extend(_build_clarify_choices(uploaded_years))
    return HealthTurnScope(
        metric_keys=explicit_metrics or (["ldl"] if message_has_lab_marker(msg) else []),
        metric_source="default",
        lab_years=uploaded_years,
        year_source="clarify",
        needs_clarification=True,
        clarify_kind="intent_scope",
        clarify_prompt=(
            f"Are you asking about {session_label}, or reviewing multi-year lab records ({ys})? Please pick one."
            if loc == "en"
            else f"您是在问{session_label}，还是查看历年化验记录（{ys}）？请选择一项。"
        ),
        clarify_choices=choices,
        profile_hint=fp or hint or "lab_cross_year",
        focus_profile=fp or None,
        wearable_window=_default_wearable_window(msg, reference=ref),
        time_source="default",
        turns_remaining=episodic.turns_remaining,
    )


def _try_session_anchor_scope(
    msg: str,
    episodic: HealthSessionFocus,
    *,
    active: bool,
    revived: bool,
    hint: str | None,
    ref: date,
    uploaded_years: list[int],
    explicit_metrics: list[str],
    explicit_window: WearableWindow | None,
    response_locale: str | None = None,
) -> HealthTurnScope | None:
    """Prefer active session anchor over naive lab-year clarify (cross-domain arbitration)."""
    if not (active or revived):
        return None
    fp = (episodic.focus_profile or "").strip()
    if not is_session_anchor_profile(fp):
        return None
    if explicit_profile_shift(msg, fp) or explicit_lab_record_request(msg):
        return None

    if (
        message_explicitly_requests_scope_choice(msg)
        and _cross_domain_lab_ambiguity(msg=msg, episodic=episodic, uploaded_years=uploaded_years)
        and len(uploaded_years) > 1
    ):
        return _build_intent_scope_clarify(
            msg,
            episodic,
            hint=hint,
            ref=ref,
            uploaded_years=uploaded_years,
            explicit_metrics=explicit_metrics,
            response_locale=response_locale,
        )

    inherited = (
        resolve_inherited_focus_profile(msg, focus_profile=fp, profile_hint=hint)
        if health_intent_catalog_enabled()
        else None
    )
    if inherited or _topic_continues(msg, episodic, hint):
        return _continue_episodic_scope(
            msg,
            episodic,
            hint=hint,
            ref=ref,
            revived=revived,
            explicit_metrics=explicit_metrics,
            explicit_window=explicit_window,
        )

    if _cross_domain_lab_ambiguity(msg=msg, episodic=episodic, uploaded_years=uploaded_years):
        if (
            len(uploaded_years) > 1
            and len(msg) > catalog_weak_followup_max_chars()
        ):
            return _build_intent_scope_clarify(
                msg,
                episodic,
                hint=hint,
                ref=ref,
                uploaded_years=uploaded_years,
                explicit_metrics=explicit_metrics,
                response_locale=response_locale,
            )
        return _continue_episodic_scope(
            msg,
            episodic,
            hint=hint,
            ref=ref,
            revived=revived,
            explicit_metrics=explicit_metrics,
            explicit_window=explicit_window,
        )
    return None


def resolve_attachment_qa_mode(
    message: str,
    episodic: HealthSessionFocus | None,
) -> str | None:
    """Attachment episodic routing hint (H-A series)."""
    if not episodic or not episodic.active:
        return None
    profile = episodic.focus_profile or ""
    if profile not in ("attachment_asset_qa", "attachment_episodic_bridge"):
        if not (episodic.focus_summary or "").strip():
            return None
        profile = "attachment_asset_qa"
    metrics = infer_metrics_from_message(message)
    lab = message_has_lab_marker(message)
    wearable = bool(metrics) or re.search(r"hrv|睡眠|步数|穿戴|活动", message or "", re.I)
    if wearable or lab:
        return "episodic_bridge"
    if matches_anaphora(message) or len((message or "").strip()) <= 120:
        return "followup"
    return "followup"


def resolve_health_turn_scope(
    message: str,
    *,
    episodic: HealthSessionFocus | None = None,
    available_lab_years: list[int] | None = None,
    reference_date: date | None = None,
    profile_hint: str | None = None,
    response_locale: str | None = None,
) -> HealthTurnScope:
    """Resolve effective health scope for the current turn (C-layer, deterministic)."""
    msg = (message or "").strip()
    ref = reference_date or effective_query_reference_date()
    hint = profile_hint or infer_profile_hint(msg)
    uploaded_years = _lab_years_from_data(available_lab_years)
    explicit_metrics = infer_metrics_from_message(msg)
    explicit_years = extract_years_regex(msg, reference_date=ref)
    explicit_window = _parse_relative_wearable_window(msg, reference=ref)
    from pha.response_language import normalize_response_locale, resolve_response_locale

    loc = normalize_response_locale(response_locale) or resolve_response_locale(
        msg,
        request_locale=response_locale,
    )

    # --- Lab multi-year explicit scope ---
    if matches_multi_scope_lab(msg) and uploaded_years:
        metrics = explicit_metrics or (["ldl"] if message_has_lab_marker(msg) else [])
        return HealthTurnScope(
            metric_keys=metrics,
            metric_source="explicit" if metrics else "default",
            lab_years=uploaded_years,
            year_source="uploaded",
            profile_hint=hint or "lab_cross_year",
            wearable_window=_default_wearable_window(msg, reference=ref),
            time_source="default",
        )

    if explicit_years:
        metrics = explicit_metrics or (["ldl"] if message_has_lab_marker(msg) else [])
        return HealthTurnScope(
            metric_keys=metrics,
            metric_source="explicit" if metrics else "default",
            lab_years=sorted(set(explicit_years)),
            year_source="explicit",
            profile_hint=hint,
            wearable_window=explicit_window or _default_wearable_window(msg, reference=ref),
            time_source="explicit" if explicit_window else "default",
        )

    revived = False
    active = bool(episodic and episodic.active)
    if episodic and not active and _topic_continues(msg, episodic, hint):
        revived = True
        active = True

    if episodic and (active or revived):
        shifted_years = _relative_lab_year_shift(msg, episodic.focus_lab_years)
        if shifted_years and shifted_years != episodic.focus_lab_years:
            metrics = explicit_metrics or (
                [episodic.focus_metric] if episodic.focus_metric else infer_metrics_from_message(msg)
            )
            return HealthTurnScope(
                metric_keys=metrics,
                metric_source="focus" if episodic.focus_metric and not explicit_metrics else "explicit",
                lab_years=shifted_years,
                year_source="explicit",
                profile_hint=_episodic_profile_hint(episodic, hint),
                focus_profile=episodic.focus_profile or None,
                wearable_window=explicit_window
                or episodic.focus_wearable_window
                or _default_wearable_window(msg, reference=ref),
                time_source="explicit" if explicit_window else "focus",
                episodic_revived=revived,
                turns_remaining=episodic.turns_remaining,
                attachment_qa_mode=resolve_attachment_qa_mode(msg, episodic),
            )

        if explicit_window and episodic.focus_metric:
            return HealthTurnScope(
                metric_keys=[episodic.focus_metric],
                metric_source="focus",
                lab_years=list(episodic.focus_lab_years),
                year_source="focus" if episodic.focus_lab_years else "default",
                wearable_window=explicit_window,
                time_source="explicit",
                profile_hint=_episodic_profile_hint(episodic, hint),
                focus_profile=episodic.focus_profile or None,
                episodic_revived=revived,
                turns_remaining=episodic.turns_remaining,
                attachment_qa_mode=resolve_attachment_qa_mode(msg, episodic),
            )

        if episodic.focus_lab_years and (matches_anaphora(msg) or _topic_continues(msg, episodic, hint)):
            metrics = explicit_metrics or (
                [episodic.focus_metric] if episodic.focus_metric else ["ldl"]
            )
            return HealthTurnScope(
                metric_keys=metrics,
                metric_source="focus",
                lab_years=list(episodic.focus_lab_years),
                year_source="focus",
                profile_hint=_episodic_profile_hint(episodic, hint),
                focus_profile=episodic.focus_profile or None,
                wearable_window=episodic.focus_wearable_window
                or _default_wearable_window(msg, reference=ref),
                time_source="focus",
                episodic_revived=revived,
                turns_remaining=episodic.turns_remaining,
                attachment_qa_mode=resolve_attachment_qa_mode(msg, episodic),
            )

        if episodic.focus_metric and (matches_anaphora(msg) or _topic_continues(msg, episodic, hint)):
            return HealthTurnScope(
                metric_keys=[episodic.focus_metric],
                metric_source="focus",
                lab_years=list(episodic.focus_lab_years),
                year_source="focus" if episodic.focus_lab_years else "default",
                wearable_window=explicit_window
                or episodic.focus_wearable_window
                or _default_wearable_window(msg, reference=ref),
                time_source="explicit" if explicit_window else "focus",
                profile_hint=_episodic_profile_hint(episodic, hint),
                focus_profile=episodic.focus_profile or None,
                episodic_revived=revived,
                turns_remaining=episodic.turns_remaining,
                attachment_qa_mode=resolve_attachment_qa_mode(msg, episodic),
            )

        anchored = _try_session_anchor_scope(
            msg,
            episodic,
            active=active,
            revived=revived,
            hint=hint,
            ref=ref,
            uploaded_years=uploaded_years,
            explicit_metrics=explicit_metrics,
            explicit_window=explicit_window,
            response_locale=response_locale,
        )
        if anchored is not None:
            return anchored

        if episodic.focus_profile and _topic_continues(msg, episodic, hint):
            return _continue_episodic_scope(
                msg,
                episodic,
                hint=hint,
                ref=ref,
                revived=revived,
                explicit_metrics=explicit_metrics,
                explicit_window=explicit_window,
            )

    # --- Clarify: multi-year lab data + weak lab question ---
    if (
        len(uploaded_years) > 1
        and message_has_lab_marker(msg)
        and not explicit_years
        and not matches_multi_scope_lab(msg)
    ):
        ys = ", ".join(str(y) for y in uploaded_years)
        if loc == "en":
            year_choices = [
                {
                    "id": str(y),
                    "label": f"Year {y}",
                    "payload": {"lab_years": [y], "action": "lab_year"},
                }
                for y in uploaded_years
            ]
        else:
            year_choices = _build_clarify_choices(uploaded_years)
        return HealthTurnScope(
            metric_keys=explicit_metrics or ["ldl"],
            metric_source="default",
            lab_years=uploaded_years,
            year_source="clarify",
            needs_clarification=True,
            clarify_kind="lab_year",
            clarify_prompt=(
                f"You have multi-year lipid/lab records ({ys}). Which year should we look at?"
                if loc == "en"
                else f"您有多年的血脂/化验记录（{ys}）。请指定要查看的年份。"
            ),
            clarify_choices=year_choices,
            profile_hint=hint or "lab_cross_year",
            wearable_window=_default_wearable_window(msg, reference=ref),
            time_source="default",
        )

    if len(uploaded_years) == 1:
        metrics = explicit_metrics or (["ldl"] if message_has_lab_marker(msg) else [])
        return HealthTurnScope(
            metric_keys=metrics,
            metric_source="explicit" if metrics else "default",
            lab_years=uploaded_years,
            year_source="uploaded_single",
            profile_hint=hint,
            wearable_window=explicit_window or _default_wearable_window(msg, reference=ref),
            time_source="explicit" if explicit_window else "default",
        )

    metrics = explicit_metrics
    if metrics:
        return HealthTurnScope(
            metric_keys=metrics,
            metric_source="explicit",
            wearable_window=explicit_window or _default_wearable_window(msg, reference=ref),
            time_source="explicit" if explicit_window else "default",
            profile_hint=hint or "wearable_only",
        )

    return HealthTurnScope(
        metric_keys=[],
        metric_source="default",
        wearable_window=_default_wearable_window(msg, reference=ref),
        time_source="default",
        profile_hint=hint,
    )


def focus_from_turn_scope(
    session_id: str,
    scope: HealthTurnScope,
    *,
    user_message: str,
    assistant_digest: str = "",
    turns_remaining: int = 8,
) -> HealthSessionFocus:
    """Build episodic focus snapshot after a turn (3C-α test helper; wired in 3C-β)."""
    profile = scope.focus_profile or scope.profile_hint or ""
    metric = scope.primary_metric()
    return HealthSessionFocus(
        session_id=session_id,
        focus_profile=profile,
        focus_metric=metric,
        focus_lab_years=list(scope.lab_years),
        focus_wearable_window=scope.wearable_window,
        focus_summary=(assistant_digest or user_message or "")[:400],
        focus_tokens=extract_health_keywords(user_message)[:32],
        turns_remaining=turns_remaining,
        last_user_message=(user_message or "")[:2000],
        last_assistant_digest=(assistant_digest or "")[:320],
        focus_goal=getattr(scope, "focus_goal", "") or "",
        focus_domains=list(getattr(scope, "focus_domains", None) or []),
    )


__all__ = [
    "HealthTurnScope",
    "focus_from_turn_scope",
    "health_turn_resolver_enabled",
    "resolve_attachment_qa_mode",
    "resolve_health_turn_scope",
]
