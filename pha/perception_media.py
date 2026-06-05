"""L0.0 media routing and L0.5 document family classification (asset-agnostic)."""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

MediaRoute = Literal["pdf_native", "pdf_scan", "raster_photo", "unknown"]
DocumentFamily = Literal[
    "supplement",
    "lab",
    "medication",
    "wearable",
    "unknown",
]

_MEDICATION_MARKERS = (
    "国药准字",
    "批准文号",
    "适应症",
    "禁忌",
    "drug facts",
    "otc",
    "处方药",
    "用法用量",
)


def detect_media_route(
    raw: bytes,
    filename: str = "",
    *,
    mime: Optional[str] = None,
) -> Tuple[MediaRoute, Dict[str, Any]]:
    """
    L0.0 — classify attachment by physical medium only (no business semantics).
    """
    name = (filename or "").strip().lower()
    guessed, _ = mimetypes.guess_type(name)
    mime_type = (mime or guessed or "").split(";")[0].strip().lower()
    meta: Dict[str, Any] = {
        "filename": filename,
        "mime": mime_type,
        "byte_len": len(raw or b""),
        "page_count": 0,
        "has_native_text_layer": False,
    }

    if mime_type == "application/pdf" or name.endswith(".pdf"):
        has_text = _pdf_has_extractable_text(raw)
        meta["has_native_text_layer"] = has_text
        try:
            import fitz

            doc = fitz.open(stream=raw, filetype="pdf")
            meta["page_count"] = doc.page_count
            doc.close()
        except Exception:
            meta["page_count"] = 0
        route: MediaRoute = "pdf_native" if has_text else "pdf_scan"
        return route, meta

    if mime_type.startswith("image/") or name.endswith(
        (".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif"),
    ):
        return "raster_photo", meta

    if raw[:4] == b"%PDF":
        has_text = _pdf_has_extractable_text(raw)
        meta["has_native_text_layer"] = has_text
        return ("pdf_native" if has_text else "pdf_scan"), meta

    return "unknown", meta


def _pdf_has_extractable_text(raw: bytes, *, min_chars: int = 40) -> bool:
    try:
        import fitz

        doc = fitz.open(stream=raw, filetype="pdf")
        chunks: List[str] = []
        for i in range(min(3, doc.page_count)):
            chunks.append(doc.load_page(i).get_text() or "")
        doc.close()
        text = "\n".join(chunks).strip()
        return len(text) >= min_chars
    except Exception:
        return False


def classify_document_family(
    ocr_text: str,
    *,
    layout_hints: Optional[List[str]] = None,
) -> Tuple[DocumentFamily, float, List[str]]:
    """
    L0.5 — post-perception business family from structure markers (no brand whitelist).
    """
    from pha.vision_ocr import _score_lab_report, _score_supplement_label

    o = (ocr_text or "").strip()
    hints = [str(h).lower() for h in (layout_hints or [])]
    evidence: List[str] = []

    med_score = 0
    for marker in _MEDICATION_MARKERS:
        if marker.lower() in o.lower():
            med_score += 2
            evidence.append(f"marker:{marker}")

    from pha.vision_ocr import _WATCH_HINT_RE

    wear_s = 0
    if _WATCH_HINT_RE.search(o):
        wear_s += 4
        evidence.append("marker:wearable_ui")
    if re.search(
        r"time\s+asleep|blood\s+oxygen|血氧|respiratory\s+rate|锻炼|workouts?|"
        r"heart\s+rate\s+variability|睡眠",
        o,
        re.I,
    ):
        wear_s += 2
        evidence.append("marker:health_kpi")

    supp_s = _score_supplement_label(o)
    lab_s = _score_lab_report(o)
    if wear_s >= 3 and wear_s >= supp_s and wear_s >= lab_s:
        return "wearable", min(0.95, 0.5 + 0.1 * wear_s), evidence

    combined_markers = len(_WATCH_HINT_RE.findall(o)) + len(
        re.findall(r"time\s+asleep|blood\s+oxygen|workouts?", o, re.I),
    )
    if combined_markers >= 2 and supp_s < 4:
        return "wearable", 0.72, evidence + ["marker:health_ui_batch"]

    if any("supplement_facts" in h or "facts_panel" in h for h in hints):
        supp_s += 2
        evidence.append("hint:supplement_facts_panel")
    if any("watch" in h or "wearable" in h for h in hints):
        return "wearable", 0.75, evidence + ["hint:wearable_layout"]

    scores = {
        "medication": med_score,
        "supplement": supp_s,
        "lab": lab_s,
    }
    best = max(scores, key=scores.get)  # type: ignore[arg-type]
    best_score = scores[best]
    second = sorted(scores.values(), reverse=True)[1] if len(scores) > 1 else 0
    confidence = min(0.99, 0.45 + 0.08 * best_score) if best_score > 0 else 0.2
    if best_score <= 0 or best_score <= second:
        return "unknown", 0.25, evidence

    family_map = {
        "supplement": "supplement",
        "lab": "lab",
        "medication": "medication",
    }
    return family_map.get(best, "unknown"), confidence, evidence  # type: ignore[return-value]


def legacy_doc_kind_from_family(family: DocumentFamily) -> str:
    """Map to historical ``classify_document_from_ocr`` strings for VLM prompts."""
    if family == "supplement":
        return "supplement_label"
    if family == "lab":
        return "lab_report"
    if family == "wearable":
        return "apple_watch"
    return "other"


def attach_perception_routing_metadata(
    parsed: Dict[str, Any],
    *,
    raw: bytes,
    filename: str,
    ocr_text: str = "",
) -> Dict[str, Any]:
    """Annotate parsed payload with media_route + document_family."""
    route, route_meta = detect_media_route(raw, filename)
    hints = list(parsed.get("layout_hints") or [])
    if parsed.get("layout_hints_per_image"):
        for entry in parsed["layout_hints_per_image"]:
            if isinstance(entry, dict):
                hints.extend(entry.get("hints") or [])

    family, conf, ev = classify_document_family(ocr_text, layout_hints=hints)
    out = dict(parsed)
    out["media_route"] = route
    out["media_route_meta"] = route_meta
    out["document_family"] = family
    out["family_confidence"] = conf
    out["family_evidence"] = ev
    out["document_type"] = legacy_doc_kind_from_family(family)
    from pha.perception_family import coerce_wearable_family

    return coerce_wearable_family(out)


__all__ = [
    "MediaRoute",
    "DocumentFamily",
    "attach_perception_routing_metadata",
    "classify_document_family",
    "detect_media_route",
    "legacy_doc_kind_from_family",
]
