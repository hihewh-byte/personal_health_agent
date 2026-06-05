"""L0.2 layout_region crop — asset-agnostic region detection (Wave 3).

Spec: docs/stage3b-beta-vision-worker-spec.md §7.2
PM: docs/pha-pm-constitution.md §4 (generic Layout Crop, not business-specific targets)
"""

from __future__ import annotations

import io
import logging
import os
from typing import Any, Dict, List, Literal, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

RegionType = Literal[
    "dense_text_block",
    "tabular_block",
    "header_block",
    "figure_block",
    "barcode_block",
    "full_page",
]

LayoutRegionDetector = Literal["heuristic_strip", "ADP-LAYOUT-01", "full_page_fallback"]


class LayoutRegion(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    region_id: str
    region_type: RegionType
    bbox_norm: List[float] = Field(description="x0,y0,x1,y1 in 0..1")
    source_page_index: int = 0
    crop_bytes: bytes = Field(repr=False)
    detector: LayoutRegionDetector = "heuristic_strip"
    confidence: float = 0.5
    ocr_preview: str = ""


def _strip_count() -> int:
    return max(4, min(12, int(os.environ.get("PHA_LAYOUT_STRIP_COUNT", "8") or "8")))


def _score_band_text(text: str) -> int:
    from pha.vision_ocr import _score_lab_report, _score_supplement_label

    raw = (text or "").strip()
    if not raw:
        return 0
    return len(raw) + _score_supplement_label(raw) * 8 + _score_lab_report(raw) * 6


def _merge_bands(
    bands: List[Tuple[int, int, int]],
    scores: List[int],
    *,
    threshold_ratio: float = 0.45,
) -> List[Tuple[int, int]]:
    if not bands:
        return []
    max_s = max(scores) if scores else 0
    if max_s <= 0:
        return [(bands[0][0], bands[-1][1])]
    thr = max(8, int(max_s * threshold_ratio))
    merged: List[Tuple[int, int]] = []
    cur_start = -1
    cur_end = -1
    for (y0, y1, _), sc in zip(bands, scores):
        if sc >= thr:
            if cur_start < 0:
                cur_start, cur_end = y0, y1
            else:
                cur_end = y1
        elif cur_start >= 0:
            merged.append((cur_start, cur_end))
            cur_start, cur_end = -1, -1
    if cur_start >= 0:
        merged.append((cur_start, cur_end))
    return merged or [(bands[0][0], bands[-1][1])]


def _classify_region_type(ocr_text: str) -> RegionType:
    from pha.vision_supplement import _DOSE_LINE_RE, _PANEL_HEADER_RE

    _DOSE_UNIT_RE = _DOSE_LINE_RE

    o = ocr_text or ""
    if _PANEL_HEADER_RE.search(o):
        return "tabular_block"
    dose_hits = len(_DOSE_UNIT_RE.findall(o))
    if dose_hits >= 2:
        return "tabular_block"
    if dose_hits >= 1 or len(o.strip()) > 40:
        return "dense_text_block"
    if len(o.strip()) < 12:
        return "header_block"
    return "dense_text_block"


def detect_layout_regions(
    image_bytes: bytes,
    *,
    source_page_index: int = 0,
) -> List[LayoutRegion]:
    """
    Heuristic horizontal-band OCR scoring → crop primary text regions.
    No business-family or brand-specific targets.
    """
    if not image_bytes:
        return []

    try:
        from PIL import Image
    except ImportError:
        logger.warning("Pillow missing; layout_region full_page only")
        return [
            LayoutRegion(
                region_id="r0",
                region_type="full_page",
                bbox_norm=[0.0, 0.0, 1.0, 1.0],
                source_page_index=source_page_index,
                crop_bytes=image_bytes,
                detector="full_page_fallback",
                confidence=0.2,
            ),
        ]

    with Image.open(io.BytesIO(image_bytes)) as img:
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        w, h = img.size
        n = _strip_count()
        band_h = max(1, h // n)
        bands: List[Tuple[int, int, int]] = []
        scores: List[int] = []
        from pha.vision_ocr import tesseract_ocr_png

        for i in range(n):
            y0 = i * band_h
            y1 = h if i == n - 1 else min(h, (i + 1) * band_h)
            crop = img.crop((0, y0, w, y1))
            buf = io.BytesIO()
            crop.save(buf, format="PNG")
            txt = tesseract_ocr_png(buf.getvalue())
            bands.append((y0, y1, i))
            scores.append(_score_band_text(txt))

        merged = _merge_bands(bands, scores)
        regions: List[LayoutRegion] = []
        pad = max(4, int(h * 0.02))
        for idx, (y0, y1) in enumerate(merged):
            y0p = max(0, y0 - pad)
            y1p = min(h, y1 + pad)
            crop_img = img.crop((0, y0p, w, y1p))
            buf = io.BytesIO()
            crop_img.save(buf, format="PNG")
            crop_bytes = buf.getvalue()
            ocr_full = tesseract_ocr_png(crop_bytes)
            rtype = _classify_region_type(ocr_full)
            conf = min(0.99, 0.35 + scores[max(0, min(len(scores) - 1, idx))] / 200.0)
            regions.append(
                LayoutRegion(
                    region_id=f"r{idx}",
                    region_type=rtype,
                    bbox_norm=[
                        0.0,
                        y0p / float(h),
                        1.0,
                        y1p / float(h),
                    ],
                    source_page_index=source_page_index,
                    crop_bytes=crop_bytes,
                    detector="heuristic_strip",
                    confidence=conf,
                    ocr_preview=(ocr_full or "")[:400],
                ),
            )

        if not regions:
            regions.append(
                LayoutRegion(
                    region_id="r0",
                    region_type="full_page",
                    bbox_norm=[0.0, 0.0, 1.0, 1.0],
                    source_page_index=source_page_index,
                    crop_bytes=image_bytes,
                    detector="full_page_fallback",
                    confidence=0.25,
                ),
            )
        return regions


def primary_parse_regions(regions: List[LayoutRegion]) -> List[LayoutRegion]:
    """Regions fed to OCR/VLM: dense_text_block + tabular_block, else full_page."""
    primary = [r for r in regions if r.region_type in ("dense_text_block", "tabular_block")]
    if primary:
        return sorted(primary, key=lambda r: r.confidence, reverse=True)
    full = [r for r in regions if r.region_type == "full_page"]
    return full or regions[:1]


def layout_hints_from_regions(regions: List[LayoutRegion]) -> List[str]:
    hints: List[str] = []
    for r in regions:
        if r.region_type in ("tabular_block", "dense_text_block"):
            if r.region_type not in hints:
                hints.append(r.region_type)
    return hints


def ocr_with_layout_regions(
    image_bytes: bytes,
    *,
    source_page_index: int = 0,
) -> Tuple[str, List[LayoutRegion], Dict[str, Any]]:
    """Full-page OCR + L0.2 region crops → arbitrated text (Wave 3)."""
    from pha.perception_arbitration import arbitrate_ocr_for_page
    from pha.vision_ocr import tesseract_ocr_png

    full_page_ocr = tesseract_ocr_png(image_bytes)
    regions = detect_layout_regions(image_bytes, source_page_index=source_page_index)
    primary = primary_parse_regions(regions)
    region_ocrs = [r.ocr_preview or tesseract_ocr_png(r.crop_bytes) for r in primary]
    merged, _lane = arbitrate_ocr_for_page(full_page_ocr, region_ocrs)
    telem = regions_to_telemetry(regions)
    return merged, regions, telem


def regions_to_telemetry(regions: List[LayoutRegion]) -> Dict[str, Any]:
    return {
        "layout_region_count": len(regions),
        "layout_detector": regions[0].detector if regions else "",
        "regions": [
            {
                "region_id": r.region_id,
                "region_type": r.region_type,
                "bbox_norm": r.bbox_norm,
                "confidence": r.confidence,
            }
            for r in regions
        ],
    }


__all__ = [
    "LayoutRegion",
    "RegionType",
    "detect_layout_regions",
    "layout_hints_from_regions",
    "ocr_with_layout_regions",
    "primary_parse_regions",
    "regions_to_telemetry",
]
