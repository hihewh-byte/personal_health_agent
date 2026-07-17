"""Stage 3C-ε — GroundedAnswerComposer SSE (meta / fact_card / follow_ups)."""

from __future__ import annotations

import os
from typing import Any

from pha.health_intent_catalog import load_health_intent_catalog
from pha.numerics_manifest import NumericsManifest

_PROFILE_FOLLOWUPS: dict[str, list[tuple[str, str]]] = {
    "wearable_only": [
        ("hrv_trend", "近90天 HRV 趋势如何？"),
        ("sleep", "睡眠怎么样？"),
        ("steps", "步数呢？"),
    ],
    "lab_cross_year": [
        ("ldl_year", "每年的 LDL 对比"),
        ("ldl_latest", "最近一次血脂怎么样"),
        ("lab_trend", "历年血脂趋势"),
    ],
    "combined_review": [
        ("ldl", "血脂怎么样"),
        ("hrv", "HRV 怎么样"),
        ("sleep", "睡眠呢"),
    ],
    "lifestyle": [
        ("ldl", "血脂怎么样"),
        ("hrv", "HRV 怎么样"),
        ("steps", "最近步数"),
    ],
}


def grounded_composer_enabled() -> bool:
    return (os.environ.get("PHA_GROUNDED_COMPOSER") or "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def build_composer_meta_event(
    *,
    session_id: str,
    profile: str,
    turn_scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "event": "meta",
        "session_id": session_id,
        "profile": profile,
        "turn_scope": dict(turn_scope or {}),
    }


def build_fact_card_event(manifest: NumericsManifest | None) -> dict[str, Any] | None:
    """T0 fact card — numbers must ⊆ numerics_manifest entries."""
    if manifest is None or not manifest.entries:
        return None
    items = []
    for entry in manifest.entries[:16]:
        items.append(
            {
                "domain": entry.domain,
                "metric": entry.metric,
                "value": entry.value,
                "unit": entry.unit,
                "anchor": entry.anchor,
                "label": f"{entry.metric} {entry.value:g}{entry.unit or ''}".strip(),
            },
        )
    return {
        "event": "fact_card",
        "profile": manifest.profile,
        "reference_date": manifest.reference_date,
        "items": items,
        "entry_count": len(manifest.entries),
    }


def build_follow_ups_event(
    *,
    profile: str,
    metric_keys: list[str] | None = None,
) -> dict[str, Any]:
    """L4: catalog-allowed next steps (deterministic, not LLM-generated)."""
    prof = (profile or "lifestyle").strip() or "lifestyle"
    catalog = load_health_intent_catalog()
    markers = (catalog.get("topic_markers") or {}).get(prof) or []
    canned = list(_PROFILE_FOLLOWUPS.get(prof) or _PROFILE_FOLLOWUPS["lifestyle"])
    choices: list[dict[str, str]] = []
    seen: set[str] = set()
    for cid, label in canned:
        if cid in seen:
            continue
        seen.add(cid)
        choices.append({"id": cid, "label": label})
        if len(choices) >= 3:
            break
    if len(choices) < 3 and markers:
        for tok in markers:
            label = f"继续聊{tok}"
            cid = f"topic_{tok}"
            if cid in seen:
                continue
            seen.add(cid)
            choices.append({"id": cid, "label": label})
            if len(choices) >= 3:
                break
    if metric_keys:
        for mk in metric_keys[:2]:
            label = f"看看{mk}"
            cid = f"metric_{mk}"
            if cid in seen or len(choices) >= 3:
                continue
            seen.add(cid)
            choices.append({"id": cid, "label": label})
    return {"event": "follow_ups", "choices": choices[:3]}


def fact_card_values_subset_of_manifest(
    fact_card: dict[str, Any],
    manifest: NumericsManifest,
) -> bool:
    allowed = {(e.metric, e.anchor, float(e.value)) for e in manifest.entries}
    for item in fact_card.get("items") or []:
        key = (
            str(item.get("metric") or ""),
            str(item.get("anchor") or ""),
            float(item.get("value")),
        )
        if key not in allowed:
            return False
    return True


def build_manifest_metric_focus_summary(
    manifest: NumericsManifest | None,
    *,
    locale: str | None = None,
) -> str:
    """Warehouse-only single-metric answer (no screenshot CompareTable)."""
    if manifest is None or not manifest.entries:
        return ""
    from pha.response_language import default_response_locale, normalize_response_locale

    loc = normalize_response_locale(locale) or default_response_locale()
    if loc == "en":
        lines = ["From your ~90-day health records:", ""]
        for entry in manifest.entries[:6]:
            val_s = f"{entry.value:g}{entry.unit or ''}"
            metric_en = _WAREHOUSE_FOCUS_LABEL_EN.get(entry.metric, entry.metric)
            lines.append(f"- **{metric_en}**: {val_s} ({entry.anchor})")
        return "\n".join(lines).strip()
    lines = ["根据您近 90 天的健康记录：", ""]
    for entry in manifest.entries[:6]:
        val_s = f"{entry.value:g}{entry.unit or ''}"
        label = _WAREHOUSE_FOCUS_LABEL_ZH_DISPLAY.get(entry.metric, entry.metric)
        lines.append(f"- **{label}**：{val_s}（{entry.anchor}）")
    return "\n".join(lines).strip()


def build_generic_english_locale_fallback(*, user_message: str = "") -> str:
    """Last-resort English reply when manifest-backed fallback is unavailable."""
    _ = user_message
    return (
        "From the available health records in your account, I can review verified lab and "
        "wearable values when you name a specific metric or time window.\n\n"
        "Educational context only, not a medical diagnosis. "
        "Ask a clinician for persistent symptoms or treatment decisions."
    )


def resolve_locale_fallback_manifest(
    manifest: NumericsManifest | None,
    *,
    user_id: str,
    profile: str,
    user_message: str = "",
) -> NumericsManifest | None:
    """Build or reuse a manifest suitable for English locale fallback."""
    if manifest is not None and manifest.entries:
        return manifest
    from pha.numerics_manifest import build_numerics_manifest

    uid = (user_id or "default").strip() or "default"
    prof = (profile or "").strip()
    candidates: list[str] = []
    for p in (prof, "combined_review", "lab_cross_year", "lifestyle", "wearable_only"):
        if p and p not in candidates:
            candidates.append(p)
    for cand in candidates:
        built = build_numerics_manifest(
            uid,
            profile=cand,
            user_message=user_message,
            include_lipid=True,
            include_wearable=True,
        )
        if built.entries:
            return built
    return manifest if manifest is not None and manifest.entries else None


def build_manifest_locale_fallback_summary(
    manifest: NumericsManifest | None,
    *,
    user_message: str = "",
    locale: str | None = None,
) -> str:
    """Deterministic fallback when an English LLM answer leaks substantial CJK."""
    if manifest is None or not manifest.entries:
        return ""
    from pha.response_language import default_response_locale, normalize_response_locale

    loc = normalize_response_locale(locale) or default_response_locale()
    if loc != "en":
        return ""
    lines = ["From the available health records:", ""]
    for entry in manifest.entries[:8]:
        val_s = f"{entry.value:g}{(' ' + entry.unit) if entry.unit else ''}"
        metric = _WAREHOUSE_FOCUS_LABEL_EN.get(entry.metric, entry.metric)
        anchor = f" ({entry.anchor})" if entry.anchor else ""
        lines.append(f"- **{metric}**: {val_s}{anchor}")
    lines.append("")
    lines.append(
        "Educational context only, not a medical diagnosis. "
        "Ask a clinician for persistent symptoms or treatment decisions.",
    )
    return "\n".join(lines).strip()


def apply_english_locale_leak_guard(
    answer_text: str,
    *,
    locale: str | None,
    numerics_manifest: NumericsManifest | None,
    user_id: str,
    profile: str,
    user_message: str = "",
) -> tuple[str, dict[str, object]]:
    """Replace English answers that leak substantial CJK with manifest or generic fallback."""
    if not answer_has_cjk_locale_leak(answer_text, locale=locale):
        return answer_text, {}
    manifest = resolve_locale_fallback_manifest(
        numerics_manifest,
        user_id=user_id,
        profile=profile,
        user_message=user_message,
    )
    fallback = build_manifest_locale_fallback_summary(
        manifest,
        user_message=user_message,
        locale=locale,
    )
    mode = "manifest"
    if not fallback:
        fallback = build_generic_english_locale_fallback(user_message=user_message)
        mode = "generic"
    return fallback, {
        "locale_fallback_applied": True,
        "locale_fallback_reason": "english_cjk_leak",
        "locale_fallback_mode": mode,
    }


def answer_has_cjk_locale_leak(text: str, *, locale: str | None = None) -> bool:
    """Detect substantial CJK leakage in an English user-visible answer."""
    from pha.response_language import normalize_response_locale

    if normalize_response_locale(locale) != "en":
        return False
    blob = text or ""
    if len(blob) < 80:
        return False
    import re

    cjk = len(re.findall(r"[\u4e00-\u9fff]", blob))
    return (cjk / max(len(blob), 1)) > 0.12


_WAREHOUSE_FOCUS_LABEL_BY_CAT: dict[str, str] = {
    "hrv": "HRV均值",
    "steps": "步数均值",
    "sleep": "睡眠均值",
    "rhr": "静息心率均值",
    "spo2": "血氧均值",
    "respiratory_rate": "呼吸率均值",
    "activity_kcal": "活动消耗日均",
    "vo2max": "VO2max均值",
}

# Registry metric_id → warehouse manifest metric label (same strings as numerics_manifest).
_REGISTRY_TO_WAREHOUSE_LABEL: dict[str, str] = {
    "sleep_time_asleep": "睡眠均值",
    "hrv_rmssd_ms": "HRV均值",
    "resting_heart_rate_bpm": "静息心率均值",
    "spo2_percent": "血氧均值",
    "respiratory_rate": "呼吸率均值",
}

_WAREHOUSE_FOCUS_LABEL_EN: dict[str, str] = {
    "HRV均值": "Mean HRV",
    "步数均值": "Mean steps",
    "睡眠均值": "Mean sleep",
    "静息心率均值": "Mean resting HR",
    "血氧均值": "Mean SpO2",
    "呼吸率均值": "Mean respiratory rate",
    "活动消耗日均": "Mean active kcal/day",
    "VO2max均值": "Mean VO2max",
}

# Prefer Chinese display labels in ZH replies (CJK ratio / readability).
_WAREHOUSE_FOCUS_LABEL_ZH_DISPLAY: dict[str, str] = {
    "HRV均值": "心率变异性均值",
    "VO2max均值": "最大摄氧量均值",
}


def is_warehouse_metric_focus_turn(user_message: str) -> bool:
    """Pure warehouse single-metric query (skip heavy 90d snapshot assembly)."""
    msg = (user_message or "").strip()
    if not msg:
        return False
    from pha.intent_gates import infer_wearable_metrics
    from pha.wearable_compare_table_v1 import infer_single_metric_focus_ids

    return bool(infer_single_metric_focus_ids(msg)) or len(infer_wearable_metrics(msg)) == 1


def _filter_manifest_to_metric_focus(
    manifest: NumericsManifest,
    user_message: str,
) -> NumericsManifest:
    from pha.intent_gates import infer_wearable_metrics
    from pha.wearable_compare_table_v1 import infer_single_metric_focus_ids

    labels: list[str] = []
    # Prefer registry-hint focus (e.g. 「心率正常吗」「呼吸正常吗」) over broad core catalog.
    for mid in infer_single_metric_focus_ids(user_message):
        lab = _REGISTRY_TO_WAREHOUSE_LABEL.get(mid)
        if lab and lab not in labels:
            labels.append(lab)
    if not labels:
        cats = infer_wearable_metrics(user_message)
        if len(cats) == 1:
            lab = _WAREHOUSE_FOCUS_LABEL_BY_CAT.get(cats[0])
            if lab:
                labels = [lab]
    if not labels:
        return manifest
    filtered = [e for e in manifest.entries if e.metric in labels]
    if not filtered:
        # Fail closed: never present an unfocused multi-metric dump as a "focus" answer.
        return NumericsManifest(
            profile=manifest.profile,
            user_id=manifest.user_id,
            entries=[],
            reference_date=manifest.reference_date,
            forbidden_dates=manifest.forbidden_dates,
        )
    return NumericsManifest(
        profile=manifest.profile,
        user_id=manifest.user_id,
        entries=filtered,
        reference_date=manifest.reference_date,
        forbidden_dates=manifest.forbidden_dates,
    )


def try_warehouse_metric_focus_skip(
    *,
    user_id: str,
    profile: str,
    user_message: str,
    manifest: NumericsManifest | None,
    response_locale: str | None = None,
) -> str:
    """
    Pure warehouse wearable follow-up: skip LLM when manifest focus is available.

    Builds manifest lazily when plan omitted NUMERICS_MANIFEST (legacy); wearable_only now includes the slot.
    """
    from pha.intent_gates import infer_wearable_metrics
    from pha.numerics_manifest import build_numerics_manifest
    from pha.wearable_compare_table_v1 import infer_single_metric_focus_ids

    msg = (user_message or "").strip()
    if not msg:
        return ""
    wants_focus = bool(infer_single_metric_focus_ids(msg)) or len(
        infer_wearable_metrics(msg),
    ) == 1
    if not wants_focus:
        return ""
    wm = manifest
    if wm is None or not wm.entries:
        wm = build_numerics_manifest(
            user_id,
            profile=profile,
            user_message=user_message,
            include_lipid=False,
            include_wearable=True,
        )
    wm = _filter_manifest_to_metric_focus(wm, user_message)
    return build_manifest_metric_focus_summary(wm, locale=response_locale)


__all__ = [
    "build_composer_meta_event",
    "build_fact_card_event",
    "build_follow_ups_event",
    "build_manifest_metric_focus_summary",
    "build_manifest_locale_fallback_summary",
    "build_generic_english_locale_fallback",
    "resolve_locale_fallback_manifest",
    "apply_english_locale_leak_guard",
    "answer_has_cjk_locale_leak",
    "is_warehouse_metric_focus_turn",
    "try_warehouse_metric_focus_skip",
    "fact_card_values_subset_of_manifest",
    "grounded_composer_enabled",
]
