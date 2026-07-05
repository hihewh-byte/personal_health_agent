"""Wearable metric candidates — screen-scoped extraction + scored merge (Wave 3d-perception-v1).

Extends stage3c WearableSnapshotLedgerV1 without replacing it. Aligns with:
- stage3c-wearable-snapshot-bridge.md (L0.6 structured ledger)
- stage3d-wearable-merge-and-gates-spec.md (merge coerce, no per-case patches)
- wearable-metric-registry-v1.md (metric_id stable keys)

CONSENSUS_ACK: harness-opus48-v2026-06-08 read — P2 Registry/校验工具向；本变更为感知定账 P0（可回滚：env PHA_WEARABLE_CANDIDATE_MERGE=0）。
"""

from __future__ import annotations

import os
import re
from typing import Dict, List, Literal, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

RegionType = Literal["hero_kpi", "chart_axis", "body_text", "unknown"]

# Registry-aligned screen bindings (snapshot metrics only; workout unchanged).
_METRIC_ALLOWED_SCREENS: Dict[str, Tuple[str, ...]] = {
    "hrv_rmssd_ms": ("hrv",),
    "spo2_percent": ("spo2",),
    "resting_heart_rate_bpm": ("heart_rate",),
    "heart_rate_range_bpm": ("heart_rate", "workout"),
    "respiratory_rate": ("respiratory_rate",),
    "sleep_time_asleep": ("sleep",),
    "sleep_deep": ("sleep",),
    "sleep_rem": ("sleep",),
    "workout_heart_rate_range_bpm": ("workout",),
    "workout_count_recent": ("workout",),
    "workout_energy_kcal": ("workout",),
    "workout_duration_min": ("workout",),
}

_HRV_AVERAGE_HERO_RE = re.compile(r"AVERAGE\s*(.+?)\s*(?:ms|ins)", re.I | re.S)
_HRV_CHART_AXIS_MS_RE = re.compile(r"^\s*(0|50|100|150)\s*ms\s*$", re.I)

_HRV_LEGACY_PATTERNS: List[re.Pattern[str]] = [
    re.compile(r"(?:hrv|variability).*?(\d{1,3})\s*(?:ms|ins)", re.I | re.S),
    re.compile(r"average\s+(\d{1,3})\s*(?:ms|ins)", re.I),
]


class MetricCandidate(BaseModel):
    metric_id: str
    value: str
    unit: str = ""
    sub_value: str = ""
    source_screen_index: int = 0
    source_line: str = ""
    screen_type: str = "unknown"
    region_type: RegionType = "unknown"
    extractor_id: str = ""
    score: int = 0


def candidate_merge_enabled() -> bool:
    raw = (os.environ.get("PHA_WEARABLE_CANDIDATE_MERGE") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _screen_allows(metric_id: str, screen_type: str) -> bool:
    allowed = _METRIC_ALLOWED_SCREENS.get(metric_id)
    if not allowed:
        return True
    return screen_type in allowed


def _normalize_hero_ocr_noise(text: str) -> str:
    """Hero KPI OCR denoise — delegates to shared wearable normalizer."""
    from pha.wearable_snapshot_v1 import normalize_wearable_ocr_text

    return normalize_wearable_ocr_text(text)


def _parse_hrv_hero_digits(block: str) -> Optional[str]:
    """Join digit fragments between AVERAGE and ms (split OCR ``2`` + ``7`` → ``27``)."""
    normalized = _normalize_hero_ocr_noise(block)
    parts = re.findall(r"\d{1,3}", normalized)
    if not parts:
        return None
    compact = parts[0] if len(parts) == 1 else "".join(parts)
    try:
        val = int(compact)
    except ValueError:
        return None
    if val < 8 or val > 180:
        return None
    return str(val)


def _score_candidate(c: MetricCandidate) -> int:
    score = int(c.score)
    if c.region_type == "hero_kpi":
        score += 120
    elif c.region_type == "chart_axis":
        score -= 500
    if _screen_allows(c.metric_id, c.screen_type):
        score += 80
    else:
        score -= 200
    try:
        v = float(c.value)
        if c.metric_id == "hrv_rmssd_ms" and 12 <= v <= 120:
            score += 30
        elif c.metric_id == "hrv_rmssd_ms" and v < 12:
            score -= 40
    except ValueError:
        pass
    return score


def _finalize_scores(candidates: List[MetricCandidate]) -> List[MetricCandidate]:
    out: List[MetricCandidate] = []
    for c in candidates:
        scored = c.model_copy()
        scored.score = _score_candidate(c)
        out.append(scored)
    return out


def extract_hrv_candidates(
    blob: str,
    *,
    screen_type: str,
    source_screen_index: int,
    unit: str = "ms",
) -> List[MetricCandidate]:
    if screen_type != "hrv":
        return []
    found: List[MetricCandidate] = []

    hero = _HRV_AVERAGE_HERO_RE.search(blob)
    if hero:
        val = _parse_hrv_hero_digits(hero.group(1))
        if val:
            found.append(
                MetricCandidate(
                    metric_id="hrv_rmssd_ms",
                    value=val,
                    unit=unit,
                    source_screen_index=source_screen_index,
                    source_line=hero.group(0).strip()[:160],
                    screen_type=screen_type,
                    region_type="hero_kpi",
                    extractor_id="hrv_average_hero",
                    score=200,
                ),
            )

    for pat in _HRV_LEGACY_PATTERNS:
        m = pat.search(blob)
        if not m:
            continue
        raw_val = m.group(1)
        line = m.group(0).strip()
        if _HRV_CHART_AXIS_MS_RE.match(f"{raw_val} ms"):
            found.append(
                MetricCandidate(
                    metric_id="hrv_rmssd_ms",
                    value=raw_val,
                    unit=unit,
                    source_screen_index=source_screen_index,
                    source_line=line[:160],
                    screen_type=screen_type,
                    region_type="chart_axis",
                    extractor_id="hrv_chart_axis",
                    score=10,
                ),
            )
            continue
        if raw_val in ("0", "50", "100", "150") and "AVERAGE" not in line.upper():
            found.append(
                MetricCandidate(
                    metric_id="hrv_rmssd_ms",
                    value=raw_val,
                    unit=unit,
                    source_screen_index=source_screen_index,
                    source_line=line[:160],
                    screen_type=screen_type,
                    region_type="chart_axis",
                    extractor_id="hrv_chart_axis",
                    score=10,
                ),
            )
            continue
        found.append(
            MetricCandidate(
                metric_id="hrv_rmssd_ms",
                value=raw_val,
                unit=unit,
                source_screen_index=source_screen_index,
                source_line=line[:160],
                screen_type=screen_type,
                region_type="body_text",
                extractor_id="hrv_variability_fallback",
                score=50,
            ),
        )
        break
    return found


def merge_metric_candidates_global(
    candidates: Sequence[MetricCandidate],
) -> Dict[str, MetricCandidate]:
    """Pick one winning candidate per metric_id (score desc, then earlier screen)."""
    from collections import defaultdict

    buckets: Dict[str, List[MetricCandidate]] = defaultdict(list)
    for c in _finalize_scores(list(candidates)):
        buckets[c.metric_id].append(c)
    winners: Dict[str, MetricCandidate] = {}
    for metric_id, group in buckets.items():
        winners[metric_id] = max(
            group,
            key=lambda c: (c.score, -c.source_screen_index),
        )
    return winners


def extract_metric_candidates_from_ocr(
    ocr_text: str,
    *,
    source_screen_index: int = 0,
) -> List[MetricCandidate]:
    """Collect scored candidates for one screen OCR blob."""
    from pha.wearable_snapshot_v1 import (
        _METRIC_UNIT,
        _extract_respiratory_rate,
        _extract_resting_hr,
        _extract_sleep_stage,
        _extract_sleep_time_asleep,
        _extract_workout_metrics,
        _HEART_RATE_RANGE_RE,
        _SPO2_PATTERNS,
        infer_screen_type,
    )

    blob = (ocr_text or "").strip()
    if not blob:
        return []
    screen_type = infer_screen_type(blob)
    out: List[MetricCandidate] = []

    def _from_metric(metric, *, region: RegionType, extractor_id: str, score: int) -> MetricCandidate:
        return MetricCandidate(
            metric_id=metric.metric_id,
            value=metric.value,
            unit=metric.unit or _METRIC_UNIT.get(metric.metric_id, ""),
            sub_value=metric.sub_value,
            source_screen_index=metric.source_screen_index,
            source_line=metric.source_line,
            screen_type=screen_type,
            region_type=region,
            extractor_id=extractor_id,
            score=score,
        )

    out.extend(
        extract_hrv_candidates(
            blob,
            screen_type=screen_type,
            source_screen_index=source_screen_index,
            unit=_METRIC_UNIT.get("hrv_rmssd_ms", "ms"),
        ),
    )

    if screen_type == "spo2":
        for pat in _SPO2_PATTERNS:
            m = pat.search(blob)
            if m:
                out.append(
                    MetricCandidate(
                        metric_id="spo2_percent",
                        value=m.group(1),
                        unit="%",
                        source_screen_index=source_screen_index,
                        source_line=m.group(0).strip()[:160],
                        screen_type=screen_type,
                        region_type="hero_kpi",
                        extractor_id="spo2_hero",
                        score=180,
                    ),
                )
                break

    if screen_type == "heart_rate" or (
        screen_type == "unknown" and re.search(r"resting|heart\s+rate|\bbpm\b", blob, re.I)
    ):
        rh = _extract_resting_hr(blob, source_screen_index=source_screen_index)
        if rh and _screen_allows("resting_heart_rate_bpm", screen_type):
            out.append(_from_metric(rh, region="hero_kpi", extractor_id="resting_hr", score=160))
        m = _HEART_RATE_RANGE_RE.search(blob)
        if m and _screen_allows("heart_rate_range_bpm", screen_type):
            out.append(
                MetricCandidate(
                    metric_id="heart_rate_range_bpm",
                    value=f"{m.group(1)}-{m.group(2)}",
                    unit="bpm",
                    sub_value=m.group(2),
                    source_screen_index=source_screen_index,
                    source_line=m.group(0).strip()[:160],
                    screen_type=screen_type,
                    region_type="body_text",
                    extractor_id="hr_range",
                    score=120,
                ),
            )

    if screen_type == "respiratory_rate":
        rr = _extract_respiratory_rate(blob, source_screen_index=source_screen_index)
        if rr:
            out.append(_from_metric(rr, region="hero_kpi", extractor_id="respiratory_rate", score=160))

    if screen_type == "sleep":
        asleep = _extract_sleep_time_asleep(blob, source_screen_index=source_screen_index)
        if asleep:
            out.append(
                MetricCandidate(
                    metric_id=asleep.metric_id,
                    value=asleep.value,
                    unit=asleep.unit or "hr",
                    sub_value=asleep.sub_value,
                    source_screen_index=asleep.source_screen_index,
                    source_line=asleep.source_line,
                    screen_type=screen_type,
                    region_type="hero_kpi",
                    extractor_id="sleep_asleep",
                    score=200,
                ),
            )
        for stage_label, mid in (("Deep", "sleep_deep"), ("REM", "sleep_rem")):
            st = _extract_sleep_stage(blob, stage_label, mid, source_screen_index=source_screen_index)
            if st:
                out.append(_from_metric(st, region="body_text", extractor_id=f"sleep_{stage_label.lower()}", score=140))

    if screen_type == "workout" or re.search(
        r"heart\s+rate:\s*workout|workouts?\s+highlights|"
        r"during your (?:recent\s+run|last\s+workout)|worked out on \d+ days",
        blob,
        re.I,
    ):
        for wm in _extract_workout_metrics(blob, source_screen_index=source_screen_index):
            if _screen_allows(wm.metric_id, screen_type):
                out.append(_from_metric(wm, region="hero_kpi", extractor_id="workout", score=150))

    return _finalize_scores(out)


def candidate_to_wearable_metric(c: MetricCandidate):
    from pha.wearable_snapshot_v1 import WearableMetricV1

    return WearableMetricV1(
        metric_id=c.metric_id,
        value=c.value,
        unit=c.unit,
        sub_value=c.sub_value,
        source_screen_index=c.source_screen_index,
        source_line=c.source_line,
    )


__all__ = [
    "MetricCandidate",
    "candidate_merge_enabled",
    "candidate_to_wearable_metric",
    "extract_hrv_candidates",
    "extract_metric_candidates_from_ocr",
    "merge_metric_candidates_global",
]
