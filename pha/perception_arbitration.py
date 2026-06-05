"""Wave 3 — multi-engine OCR/VLM text arbitration (product-agnostic).

Spec: stage3b-beta-vision-worker-spec.md §7.6
"""

from __future__ import annotations

import re
from typing import List, Literal, Tuple

PerceptionLane = Literal[
    "layout_crop",
    "ocr_cluster",
    "vision_structured",
    "cloud_vision_byok",
]


def _normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", (line or "").strip().lower())


def merge_ocr_texts(*sources: str) -> str:
    """Union lines from multiple OCR/VLM transcripts; prefer longer line on duplicate keys."""
    by_key: dict[str, str] = {}
    order: List[str] = []
    for blob in sources:
        if not (blob or "").strip():
            continue
        for line in blob.splitlines():
            ln = line.strip()
            if not ln or len(ln) < 2:
                continue
            key = _normalize_line(ln)
            if key not in by_key:
                order.append(key)
                by_key[key] = ln
            elif len(ln) > len(by_key[key]):
                by_key[key] = ln
    return "\n".join(by_key[k] for k in order)


def pick_perception_channel(*channels: str) -> str:
    rank = {
        "cloud_vision_byok": 4,
        "vision_structured": 3,
        "ocr_plus_vision_validate": 2,
        "ocr_cluster": 1,
        "ocr_only": 0,
    }
    best = "ocr_only"
    best_r = -1
    for ch in channels:
        c = (ch or "ocr_only").strip()
        r = rank.get(c, 0)
        if r > best_r:
            best_r = r
            best = c
    return best


def arbitrate_ocr_for_page(
    full_page_ocr: str,
    region_ocrs: List[str],
) -> Tuple[str, PerceptionLane]:
    merged = merge_ocr_texts(full_page_ocr, *region_ocrs)
    lane: PerceptionLane = "ocr_cluster" if region_ocrs else "ocr_only"
    if region_ocrs and len(merged) > len((full_page_ocr or "").strip()) + 20:
        lane = "layout_crop"
    return merged, lane


__all__ = [
    "PerceptionLane",
    "arbitrate_ocr_for_page",
    "merge_ocr_texts",
    "pick_perception_channel",
]
