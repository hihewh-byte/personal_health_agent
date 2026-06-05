"""Wearable golden fixture assertions (F-layer · Wave 3d-γ).

Non-production gate: used by ``scripts/pha_wearable_golden_fixture.py`` and future
``wearable_compare_table_v1`` unit tests. Production paths must not hard-code these strings.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from pha.wearable_snapshot_v1 import extract_metrics_from_ocr, finalize_wearable_attachment

_FIXTURE_DIR = Path(__file__).resolve().parent


def load_golden_ocr() -> Dict[str, Any]:
    path = _FIXTURE_DIR / "golden_ocr.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_golden_compare_table() -> Dict[str, Any]:
    path = _FIXTURE_DIR / "golden_compare_table.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _panel_parts(panels: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {"ocr_text": str(p["ocr_text"]), "document_family": "wearable"}
        for p in panels
    ]


def golden_match_panel_metrics(panels: Sequence[Mapping[str, Any]]) -> List[str]:
    """Per-panel OCR → expected metric_id/value."""
    fails: List[str] = []
    for panel in panels:
        idx = panel.get("screen_index", "?")
        ocr = str(panel.get("ocr_text") or "")
        expected = dict(panel.get("expected_metrics") or {})
        actual = {m.metric_id: m.value for m in extract_metrics_from_ocr(ocr)}
        for mid, want in expected.items():
            got = actual.get(mid)
            if got != want:
                fails.append(f"panel[{idx}] {mid}: want={want!r} got={got!r}")
    return fails


def golden_match_merged_finalize(
    panels: Sequence[Mapping[str, Any]],
    merged: Mapping[str, Any],
) -> List[str]:
    """Six-panel merge → WearableSnapshot finalize expectations."""
    fails: List[str] = []
    parts = _panel_parts(panels)
    if not parts:
        return ["no panels"]
    out = finalize_wearable_attachment(
        parts[0],
        attachment_count=len(parts),
        user_message="对比过去90天是否正常，尤其睡眠",
        parts=parts,
    )
    conf = str(out.get("parse_confidence") or "")
    conf_min = str(merged.get("parse_confidence_min") or "medium")
    rank = {"low": 0, "medium": 1, "high": 2}
    if rank.get(conf, -1) < rank.get(conf_min, 1):
        fails.append(f"parse_confidence: want>={conf_min!r} got={conf!r}")

    metrics = {m["metric_id"]: m["value"] for m in (out.get("wearable_metrics") or [])}
    required = dict(merged.get("required_metrics") or {})
    for mid, want in required.items():
        got = metrics.get(mid)
        if got != want:
            fails.append(f"merged {mid}: want={want!r} got={got!r}")

    min_count = int(merged.get("metric_count_min") or len(required))
    if len(metrics) < min_count:
        fails.append(f"merged metric count: want>={min_count} got={len(metrics)}")

    optional = dict(merged.get("optional_metrics") or {})
    for mid, want in optional.items():
        got = metrics.get(mid)
        if got is not None and got != want:
            fails.append(f"merged optional {mid}: want={want!r} got={got!r}")
    return fails


def golden_match_spo2_absent(panels: Sequence[Mapping[str, Any]], omit_indices: Sequence[int]) -> List[str]:
    """Structural shield: no SpO2 panel → no spo2_percent in extracted metrics."""
    fails: List[str] = []
    keep = [p for i, p in enumerate(panels) if i not in set(omit_indices)]
    parts = _panel_parts(keep)
    out = finalize_wearable_attachment(
        parts[0],
        attachment_count=len(parts),
        user_message="对比过去90天",
        parts=parts,
    )
    metrics = {m["metric_id"]: m["value"] for m in (out.get("wearable_metrics") or [])}
    if "spo2_percent" in metrics:
        fails.append(f"spo2_absent: spo2_percent should be omitted, got={metrics['spo2_percent']!r}")
    return fails


def golden_compare_table_shape(expected: Mapping[str, Any]) -> List[str]:
    """Validate golden_compare_table.json structural contract (pre-build)."""
    fails: List[str] = []
    rows = expected.get("rows") or []
    comparable = {"sleep_time_asleep", "hrv_rmssd_ms", "resting_heart_rate_bpm", "spo2_percent"}
    no_baseline = {"sleep_deep", "sleep_rem"}
    seen = set()
    for row in rows:
        mid = str(row.get("metric_id") or "")
        seen.add(mid)
        rk = str(row.get("row_kind") or "")
        if mid in comparable:
            if rk != "comparable_90d":
                fails.append(f"{mid}: row_kind want comparable_90d got {rk!r}")
            if row.get("baseline_90d_value") == "NO_BASELINE":
                fails.append(f"{mid}: comparable row must not be NO_BASELINE")
        if mid in no_baseline:
            if rk != "snapshot_only":
                fails.append(f"{mid}: row_kind want snapshot_only got {rk!r}")
            if row.get("baseline_90d_value") != "NO_BASELINE":
                fails.append(f"{mid}: baseline must be NO_BASELINE")
    for mid in comparable:
        if mid not in seen:
            fails.append(f"missing comparable row: {mid}")
    for mid in no_baseline:
        if mid not in seen:
            fails.append(f"missing NO_BASELINE row: {mid}")
    return fails


def golden_match_all() -> List[str]:
    ocr_fix = load_golden_ocr()
    cmp_fix = load_golden_compare_table()
    panels = ocr_fix.get("panels") or []
    fails: List[str] = []
    fails.extend(golden_match_panel_metrics(panels))
    fails.extend(golden_match_merged_finalize(panels, ocr_fix.get("merged_expected") or {}))

    for neg in ocr_fix.get("negative_panels") or []:
        omit = neg.get("omit_panel_indices") or []
        fails.extend(golden_match_spo2_absent(panels, omit))

    std = cmp_fix.get("expected_standard") or {}
    fails.extend(golden_compare_table_shape(std))

    absent = cmp_fix.get("expected_spo2_absent") or {}
    omit = absent.get("omit_panel_indices") or []
    if omit:
        fails.extend(golden_match_spo2_absent(panels, omit))

    return fails


__all__ = [
    "golden_compare_table_shape",
    "golden_match_all",
    "golden_match_merged_finalize",
    "golden_match_panel_metrics",
    "golden_match_spo2_absent",
    "load_golden_compare_table",
    "load_golden_ocr",
]
