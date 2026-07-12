"""Wearable Metric Registry — config-driven CompareTable & ingest modules (Wave 3d-δ-c)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

_REGISTRY_PATH = (
    Path(__file__).resolve().parent.parent / "storage" / "registry" / "wearable_metric_registry.json"
)

MetricTriple = Tuple[str, str, str]


@lru_cache(maxsize=1)
def load_wearable_metric_registry() -> Dict[str, Any]:
    if not _REGISTRY_PATH.is_file():
        return {"schema_version": "wearable_metric_registry_v1", "metrics": [], "ingest_modules": []}
    with _REGISTRY_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def registry_path() -> Path:
    return _REGISTRY_PATH


def list_metric_entries() -> List[Dict[str, Any]]:
    doc = load_wearable_metric_registry()
    metrics = doc.get("metrics") or []
    return [m for m in metrics if isinstance(m, dict) and m.get("metric_id")]


def metric_entry(metric_id: str) -> Optional[Dict[str, Any]]:
    mid = (metric_id or "").strip()
    for m in list_metric_entries():
        if str(m.get("metric_id") or "").strip() == mid:
            return m
    return None


def comparable_wearable_daily_specs() -> Tuple[MetricTriple, ...]:
    """(metric_id, wearable_daily field, snapshot unit) for 90d warehouse rollups."""
    out: List[MetricTriple] = []
    for m in list_metric_entries():
        l1 = m.get("l1") or {}
        if str(l1.get("kind") or "") != "wearable_daily":
            continue
        compare = m.get("compare") or {}
        if not compare.get("comparable_90d"):
            continue
        field = str(l1.get("field") or "").strip()
        unit = str((m.get("snapshot") or {}).get("unit") or "").strip()
        mid = str(m.get("metric_id") or "").strip()
        if mid and field:
            out.append((mid, field, unit))
    return tuple(out)


def workout_compare_metric_ids() -> Tuple[str, ...]:
    out: List[str] = []
    for m in list_metric_entries():
        l1 = m.get("l1") or {}
        if str(l1.get("kind") or "") != "workout_sessions":
            continue
        compare = m.get("compare") or {}
        if not compare.get("conditional_row"):
            continue
        mid = str(m.get("metric_id") or "").strip()
        if mid:
            out.append(mid)
    return tuple(out)


def snapshot_only_fallback_metric_ids() -> Tuple[str, ...]:
    """Daily metrics that emit snapshot_only row when OCR has value but warehouse has no baseline."""
    out: List[str] = []
    for m in list_metric_entries():
        compare = m.get("compare") or {}
        if not compare.get("snapshot_only_if_no_baseline"):
            continue
        mid = str(m.get("metric_id") or "").strip()
        if mid:
            out.append(mid)
    return tuple(out)


def metric_labels_zh() -> Dict[str, str]:
    labels: Dict[str, str] = {}
    for m in list_metric_entries():
        mid = str(m.get("metric_id") or "").strip()
        zh = str((m.get("ui") or {}).get("label_zh") or "").strip()
        if mid and zh:
            labels[mid] = zh
    return labels


_METRIC_LABEL_EN_FALLBACK: Dict[str, str] = {
    "sleep_time_asleep": "Sleep duration",
    "hrv_rmssd_ms": "HRV",
    "resting_heart_rate_bpm": "Resting HR",
    "spo2_percent": "SpO2",
    "respiratory_rate": "Respiratory rate",
    "sleep_deep": "Deep sleep",
    "sleep_rem": "REM",
    "workout_heart_rate_range_bpm": "Workout HR range",
    "workout_count_recent": "Recent workout days",
}


def metric_labels_en() -> Dict[str, str]:
    labels: Dict[str, str] = dict(_METRIC_LABEL_EN_FALLBACK)
    for m in list_metric_entries():
        mid = str(m.get("metric_id") or "").strip()
        en = str((m.get("ui") or {}).get("label_en") or "").strip()
        if mid and en:
            labels[mid] = en
    return labels


def metric_mention_hints() -> Dict[str, Tuple[str, ...]]:
    hints: Dict[str, Tuple[str, ...]] = {}
    for m in list_metric_entries():
        mid = str(m.get("metric_id") or "").strip()
        raw = m.get("intent_hints") or []
        if mid and isinstance(raw, list):
            hints[mid] = tuple(str(x) for x in raw if str(x).strip())
    return hints


def metrics_footer_when_snapshot_only() -> frozenset[str]:
    ids: List[str] = []
    for m in list_metric_entries():
        if not (m.get("ui") or {}).get("footer_when_snapshot_only"):
            continue
        mid = str(m.get("metric_id") or "").strip()
        if mid:
            ids.append(mid)
    return frozenset(ids)


def list_ingest_modules() -> List[Dict[str, Any]]:
    doc = load_wearable_metric_registry()
    modules = doc.get("ingest_modules") or []
    return [x for x in modules if isinstance(x, dict) and x.get("module_id")]


def ingest_module(module_id: str) -> Optional[Dict[str, Any]]:
    mid = (module_id or "").strip()
    for m in list_ingest_modules():
        if str(m.get("module_id") or "").strip() == mid:
            return m
    return None


def is_registered_comparable_metric(metric_id: str) -> bool:
    entry = metric_entry(metric_id)
    if not entry:
        return False
    return bool((entry.get("compare") or {}).get("comparable_90d"))


def clear_registry_cache() -> None:
    load_wearable_metric_registry.cache_clear()


__all__ = [
    "clear_registry_cache",
    "comparable_wearable_daily_specs",
    "ingest_module",
    "is_registered_comparable_metric",
    "list_ingest_modules",
    "list_metric_entries",
    "load_wearable_metric_registry",
    "metric_entry",
    "metric_labels_en",
    "metric_labels_zh",
    "metric_mention_hints",
    "metrics_footer_when_snapshot_only",
    "registry_path",
    "snapshot_only_fallback_metric_ids",
    "workout_compare_metric_ids",
]
