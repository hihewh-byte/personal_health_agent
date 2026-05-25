"""Shadow Routing — Stage 2D: async telemetry-only semantic contrast (zero adopt)."""

from __future__ import annotations

import json
import os
import random
import re
import threading
import time
from typing import Any, Dict, List, Optional, Sequence

from pha.schema_intent_router import IntentRouteResult


def shadow_routing_enabled() -> bool:
    return os.environ.get("PHA_SHADOW_ROUTING", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def shadow_force_sample() -> bool:
    return os.environ.get("PHA_SHADOW_ROUTING_FORCE_SAMPLE", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def shadow_timeout_ms() -> int:
    try:
        return max(100, int(os.environ.get("PHA_SHADOW_ROUTING_TIMEOUT_MS", "800")))
    except ValueError:
        return 800


def shadow_confidence_threshold() -> float:
    try:
        return float(os.environ.get("PHA_SHADOW_CONFIDENCE_THRESHOLD", "0.7"))
    except ValueError:
        return 0.7


def shadow_model_name() -> str:
    return os.environ.get("PHA_SHADOW_ROUTING_MODEL", "qwen2.5:1.5b-instruct").strip()


def effective_sample_rate(profile: str) -> float:
    p = (profile or "").strip()
    if p == "casual":
        return 0.0
    if p == "combined_review":
        try:
            return float(os.environ.get("PHA_SHADOW_PROFILE_COMBINED_RATE", "0.10"))
        except ValueError:
            return 0.10
    if p == "lab_cross_year":
        try:
            return float(os.environ.get("PHA_SHADOW_PROFILE_LAB_RATE", "0.15"))
        except ValueError:
            return 0.15
    if p == "wearable_only":
        return 0.02
    try:
        return float(os.environ.get("PHA_SHADOW_ROUTING_SAMPLE_RATE", "0.05"))
    except ValueError:
        return 0.05


def should_sample_shadow(profile: str) -> bool:
    if not shadow_routing_enabled():
        return False
    if shadow_force_sample():
        return effective_sample_rate(profile) > 0 or profile != "casual"
    rate = effective_sample_rate(profile)
    if rate <= 0:
        return False
    return random.random() < rate


def _ids_jaccard(a: Sequence[str], b: Sequence[str]) -> float:
    sa = {str(x).strip() for x in a if str(x).strip()}
    sb = {str(x).strip() for x in b if str(x).strip()}
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _classify_disagreement(
    *,
    authoritative_profile: str,
    shadow_profile: str,
    authoritative_ids: Sequence[str],
    shadow_ids: Sequence[str],
) -> Optional[str]:
    if shadow_profile != authoritative_profile:
        return "shadow_profile_conflict"
    auth = set(authoritative_ids)
    sh = set(shadow_ids)
    extra_ctx = sh - auth
    if extra_ctx & {"supplement_bg"} or any(x.startswith("dyn:") for x in extra_ctx):
        if extra_ctx - auth:
            return "shadow_ctx_extra"
    missed = auth - sh
    data_ids = {"lab_lipid_panel", "wearable_bundle"}
    if missed & data_ids:
        return "shadow_data_miss"
    if extra_ctx:
        return "shadow_ctx_extra"
    return None


def _rule_based_shadow(
    user_message: str,
    *,
    user_id: str = "default",
) -> Dict[str, Any]:
    """Deterministic shadow (0ms) — mirrors SchemaIntentRouter for telemetry baseline."""
    from pha.universal_catalog_manager import get_catalog_manager

    mgr = get_catalog_manager()
    route = mgr.resolve_intent(user_message)
    proposed = mgr.catalog_asset_ids_for_profile(
        route.profile,
        user_message,
        user_id=user_id,
    )
    scores = route.asset_scores or {}
    conf = min(0.95, 0.45 + 0.08 * sum(scores.values()))
    return {
        "profile_hint": route.profile,
        "proposed_ids": proposed,
        "confidence": round(conf, 3),
        "source": "shadow:rules",
    }


def _parse_shadow_json(text: str) -> Optional[Dict[str, Any]]:
    raw = (text or "").strip()
    if not raw:
        return None
    m = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        doc = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(doc, dict):
        return None
    return doc


def _ollama_shadow(
    user_message: str,
    *,
    metadata_catalog_excerpt: str = "",
    user_id: str = "default",
) -> Dict[str, Any]:
    """Optional LLM shadow; falls back to rules on failure."""
    try:
        from pha.llm_provider import OllamaProvider
    except ImportError:
        return _rule_based_shadow(user_message, user_id=user_id)

    mc = (metadata_catalog_excerpt or "")[:1200]
    prompt = (
        "Suggest catalog asset IDs only. Reply JSON: "
        '{"profile_hint":"combined_review","proposed_ids":["lab_lipid_panel"],"confidence":0.0}\n'
        f"Catalog index:\n{mc}\nUser: {user_message[:800]}"
    )
    provider = OllamaProvider(model=shadow_model_name())
    t0 = time.perf_counter()
    try:
        out = provider.chat_completion(
            system_prompt="Output JSON only.",
            user_message=prompt,
            json_mode=True,
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)
        doc = _parse_shadow_json(str(out or ""))
        if not doc:
            raise ValueError("shadow_parse_error")
        return {
            "profile_hint": str(doc.get("profile_hint") or ""),
            "proposed_ids": list(doc.get("proposed_ids") or []),
            "confidence": float(doc.get("confidence") or 0.0),
            "source": "shadow:ollama",
            "latency_ms": latency_ms,
        }
    except Exception:
        fb = _rule_based_shadow(user_message, user_id=user_id)
        fb["source"] = "shadow:rules_fallback"
        return fb


def run_shadow_routing(
    user_message: str,
    *,
    authoritative_profile: str,
    authoritative_catalog_ids: Sequence[str],
    user_id: str = "default",
    metadata_catalog_excerpt: str = "",
    use_llm: bool = False,
) -> Dict[str, Any]:
    """Compute shadow_routing payload for HarnessBuildReport (telemetry only)."""
    t0 = time.perf_counter()
    if use_llm and os.environ.get("PHA_SHADOW_ROUTING_USE_LLM", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        proposal = _ollama_shadow(
            user_message,
            metadata_catalog_excerpt=metadata_catalog_excerpt,
            user_id=user_id,
        )
    else:
        proposal = _rule_based_shadow(user_message, user_id=user_id)

    latency_ms = int(proposal.pop("latency_ms", int((time.perf_counter() - t0) * 1000)))
    shadow_profile = str(proposal.get("profile_hint") or "")
    shadow_ids = list(proposal.get("proposed_ids") or [])
    conf = float(proposal.get("confidence") or 0.0)
    profile_match = shadow_profile == authoritative_profile
    jaccard = _ids_jaccard(authoritative_catalog_ids, shadow_ids)
    disagree = None
    if latency_ms > shadow_timeout_ms():
        disagree = "shadow_timeout"
    elif proposal.get("source") == "shadow:rules_fallback" and use_llm:
        disagree = "shadow_parse_error"
    else:
        disagree = _classify_disagreement(
            authoritative_profile=authoritative_profile,
            shadow_profile=shadow_profile,
            authoritative_ids=authoritative_catalog_ids,
            shadow_ids=shadow_ids,
        )

    threshold = shadow_confidence_threshold()
    telemetry_priority = "high" if conf >= threshold else "low"

    return {
        "enabled": True,
        "sampled": True,
        "completed": disagree != "shadow_timeout",
        "latency_ms": latency_ms,
        "model": shadow_model_name() if use_llm else "shadow:rules",
        "authoritative_profile": authoritative_profile,
        "shadow_profile_hint": shadow_profile,
        "shadow_proposed_ids": shadow_ids,
        "shadow_confidence": conf,
        "telemetry_priority": telemetry_priority,
        "agreement": {
            "profile_match": profile_match,
            "ids_jaccard": round(jaccard, 3),
            "extra_context_ids": sorted(set(shadow_ids) - set(authoritative_catalog_ids)),
            "missed_data_ids": sorted(
                set(authoritative_catalog_ids) - set(shadow_ids) - {"supplement_bg"}
            ),
        },
        "disagreement_class": disagree,
        "source": proposal.get("source"),
    }


class ShadowJobHandle:
    """Background shadow worker — join at turn end with timeout."""

    def __init__(
        self,
        user_message: str,
        *,
        authoritative_profile: str,
        authoritative_catalog_ids: Sequence[str],
        user_id: str = "default",
        metadata_catalog_excerpt: str = "",
    ) -> None:
        self._result: Dict[str, Any] = {}
        self._done = threading.Event()
        self._user_message = user_message
        self._profile = authoritative_profile
        self._catalog_ids = list(authoritative_catalog_ids)
        self._user_id = user_id
        self._mc = metadata_catalog_excerpt

    def _worker(self) -> None:
        try:
            self._result = run_shadow_routing(
                self._user_message,
                authoritative_profile=self._profile,
                authoritative_catalog_ids=self._catalog_ids,
                user_id=self._user_id,
                metadata_catalog_excerpt=self._mc,
                use_llm=False,
            )
        except Exception as exc:
            self._result = {
                "enabled": True,
                "sampled": True,
                "completed": False,
                "disagreement_class": "shadow_parse_error",
                "error": str(exc),
            }
        finally:
            self._done.set()

    def start(self) -> None:
        threading.Thread(target=self._worker, daemon=True).start()

    def collect(self, timeout_ms: Optional[int] = None) -> Dict[str, Any]:
        ms = shadow_timeout_ms() if timeout_ms is None else timeout_ms
        self._done.wait(timeout=ms / 1000.0)
        if not self._done.is_set():
            return {
                "enabled": True,
                "sampled": True,
                "completed": False,
                "disagreement_class": "shadow_timeout",
                "latency_ms": ms,
            }
        return dict(self._result or {})


def maybe_start_shadow_job(
    user_message: str,
    *,
    authoritative_profile: str,
    authoritative_catalog_ids: Sequence[str],
    user_id: str = "default",
    metadata_catalog_excerpt: str = "",
) -> Optional[ShadowJobHandle]:
    if not should_sample_shadow(authoritative_profile):
        return None
    handle = ShadowJobHandle(
        user_message,
        authoritative_profile=authoritative_profile,
        authoritative_catalog_ids=authoritative_catalog_ids,
        user_id=user_id,
        metadata_catalog_excerpt=metadata_catalog_excerpt,
    )
    handle.start()
    return handle


__all__ = [
    "ShadowJobHandle",
    "effective_sample_rate",
    "maybe_start_shadow_job",
    "run_shadow_routing",
    "shadow_confidence_threshold",
    "shadow_force_sample",
    "shadow_routing_enabled",
    "should_sample_shadow",
]
