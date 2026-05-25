"""SchemaIntentRouter — configuration-driven lane scoring (A+)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pha.catalog_dch import token_in_message


@dataclass(frozen=True)
class AssetIntentScore:
    asset_id: str
    score: float
    asset_class: str
    lane: str
    priority: int


@dataclass(frozen=True)
class IntentRouteResult:
    profile: str
    question_type: str
    asset_scores: Dict[str, float] = field(default_factory=dict)
    include_supplement_catalog: bool = False
    context_only_lane: bool = False


def _rules(schema: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    intent = schema.get("intent") or {}
    catalog = schema.get("catalog") or {}
    raw = intent.get(key) or catalog.get(key) or []
    out: List[Dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            out.append(item)
        elif isinstance(item, str):
            out.append({"token": item, "weight": 1.0})
    return out


def score_asset(user_message: str, schema: Dict[str, Any]) -> AssetIntentScore:
    intent = schema.get("intent") or {}
    aid = str(schema.get("asset_id") or "").strip()
    msg = user_message or ""
    score = 0.0
    for rule in _rules(schema, "trigger_keywords"):
        token = str(rule.get("token") or "").strip()
        if not token:
            continue
        if token_in_message(token, msg, case_insensitive=bool(rule.get("match_case_insensitive", True))):
            score += float(rule.get("weight") or 1.0)
    for rule in _rules(schema, "negative_keywords"):
        token = str(rule.get("token") or "").strip()
        if not token:
            continue
        if token_in_message(token, msg, case_insensitive=bool(rule.get("match_case_insensitive", True))):
            score -= float(rule.get("weight") or 2.0)
    return AssetIntentScore(
        asset_id=aid,
        score=score,
        asset_class=str(intent.get("asset_class") or "data"),
        lane=str(intent.get("lane") or ""),
        priority=int(intent.get("priority") or 50),
    )


def score_asset_positive(user_message: str, schema: Dict[str, Any]) -> float:
    """Positive trigger score only — for Context catalog mount (A+ DCH)."""
    msg = user_message or ""
    score = 0.0
    for rule in _rules(schema, "trigger_keywords"):
        token = str(rule.get("token") or "").strip()
        if not token:
            continue
        if token_in_message(token, msg, case_insensitive=bool(rule.get("match_case_insensitive", True))):
            score += float(rule.get("weight") or 1.0)
    return score


def score_all_assets(user_message: str, assets: Dict[str, Dict[str, Any]]) -> Dict[str, AssetIntentScore]:
    out: Dict[str, AssetIntentScore] = {}
    for aid, doc in assets.items():
        if str(doc.get("status") or "active") != "active":
            continue
        out[aid] = score_asset(user_message, doc)
    return out


def _supplement_catalog_threshold(schema: Optional[Dict[str, Any]]) -> float:
    if not schema:
        return 2.0
    intent = schema.get("intent") or {}
    cat = schema.get("catalog") or {}
    return float(intent.get("catalog_min_score") or cat.get("catalog_min_score") or 2.0)


def should_capture_background_from_schema(user_message: str, schema: Optional[Dict[str, Any]]) -> bool:
    """Long-term note capture — independent of turn lane."""
    text = (user_message or "").strip()
    if len(text) < 8 or text.startswith("[附件]"):
        return False
    if not schema:
        return False
    intent = schema.get("intent") or {}
    for rule in intent.get("background_capture_keywords") or []:
        if isinstance(rule, dict):
            token = str(rule.get("token") or "").strip()
        else:
            token = str(rule).strip()
        if token and token_in_message(token, text):
            return True
    return False


def resolve_intent_route(
    user_message: str,
    assets: Dict[str, Dict[str, Any]],
    *,
    is_casual: bool,
    needs_lab_dossier: bool,
    has_clinical_lab: bool,
    has_wearable_query: bool,
) -> IntentRouteResult:
    """Pick harness profile from schema scores (Data > Context on ties)."""
    msg = (user_message or "").strip()
    if is_casual:
        return IntentRouteResult(profile="casual", question_type="casual")

    scores = score_all_assets(msg, assets)
    by_id = {k: v.score for k, v in scores.items()}
    lab_s = by_id.get("lab_lipid_panel", 0.0)
    wear_s = by_id.get("wearable_bundle", 0.0)
    supp_s = by_id.get("supplement_bg", 0.0)
    supp_schema = assets.get("supplement_bg")
    supp_threshold = _supplement_catalog_threshold(supp_schema)

    has_lab_clinical = has_clinical_lab or lab_s > 0
    has_wearable = has_wearable_query or wear_s > 0
    has_supp_explicit = supp_s >= supp_threshold
    supp_pos = score_asset_positive(msg, supp_schema) if supp_schema else 0.0

    if has_lab_clinical and (has_wearable or has_supp_explicit or supp_pos >= supp_threshold):
        include_supp = supp_pos >= supp_threshold
        return IntentRouteResult(
            profile="combined_review",
            question_type="combined",
            asset_scores=by_id,
            include_supplement_catalog=include_supp,
        )

    if needs_lab_dossier or (lab_s > wear_s and lab_s > supp_s and lab_s > 0):
        return IntentRouteResult(
            profile="lab_cross_year",
            question_type="lab",
            asset_scores=by_id,
        )

    # Data beats Context: wearable analytics over supplement capture hints.
    if has_wearable and wear_s >= supp_s:
        return IntentRouteResult(
            profile="wearable_only",
            question_type="wearable",
            asset_scores=by_id,
        )

    if has_supp_explicit and supp_s > wear_s:
        return IntentRouteResult(
            profile="supplement_manifest",
            question_type="lifestyle",
            asset_scores=by_id,
            context_only_lane=True,
        )

    if has_wearable:
        return IntentRouteResult(
            profile="wearable_only",
            question_type="wearable",
            asset_scores=by_id,
        )

    return IntentRouteResult(
        profile="lifestyle",
        question_type="lifestyle",
        asset_scores=by_id,
    )


__all__ = [
    "AssetIntentScore",
    "IntentRouteResult",
    "resolve_intent_route",
    "score_asset",
    "score_asset_positive",
    "score_all_assets",
    "should_capture_background_from_schema",
]
