"""document_family routing helpers — avoid supplement LabelLedger on non-supplement attachments."""

from __future__ import annotations

import re
from typing import Any, Dict, List

SUPPLEMENT_FAMILY = "supplement"
WEARABLE_FAMILY = "wearable"
LAB_FAMILY = "lab"
MEDICATION_FAMILY = "medication"
UNKNOWN_FAMILY = "unknown"

# Health UI structure markers (not product/brand literals).
_HEALTH_UI_RE = re.compile(
    r"heart\s+rate\s+variability|blood\s+oxygen|time\s+asleep|"
    r"respiratory\s+rate|workouts?\s+highlights|heart\s+rate:\s*workout|"
    r"about\s+heart\s+rate\s+variability|cardio\s+fitness|vo2\s*max|"
    r"show\s+all\s+cardio|"
    r"血氧|睡眠|心率|锻炼|呼吸率",
    re.I,
)
_HEALTH_UI_STRONG_RE = re.compile(
    r"\bhrv\b|rmssd|\bms\b|breaths/min|beats per minute|"
    r"functional strength training|\bkcal\b",
    re.I,
)


def should_skip_vlm_for_wearable(
    *,
    doc_kind: str,
    document_family: str,
    ocr_text: str,
) -> bool:
    """Lane-O: OCR+rules wearable path — skip per-image VLM when OCR is actionable."""
    blob = (ocr_text or "").strip()
    if not blob:
        return False
    fam = (document_family or "").strip().lower()
    kind = (doc_kind or "").strip().lower()
    if kind == "apple_watch" or fam == WEARABLE_FAMILY:
        return True
    return ocr_suggests_wearable_ui(blob)


def ocr_suggests_wearable_ui(ocr_text: str) -> bool:
    blob = (ocr_text or "").strip()
    if not blob:
        return False
    hits = 0
    if _HEALTH_UI_RE.search(blob):
        hits += 2
    if _HEALTH_UI_STRONG_RE.search(blob):
        hits += 1
    if re.search(r"\b\d{1,2}\s*hr\b|\d{1,3}\s*ms\b|\d{2,3}\s*%\b|\d{1,2}\s*bpm\b", blob, re.I):
        hits += 1
    return hits >= 2


def parts_should_finalize_as_wearable(parts: List[Dict[str, Any]]) -> bool:
    """True when batch should skip supplement merge/LabelLedger."""
    if not parts:
        return False
    fams = {family_from_parsed(p) for p in parts}
    if WEARABLE_FAMILY in fams:
        return True
    combined = "\n".join(str(p.get("ocr_text") or "") for p in parts)
    if ocr_suggests_wearable_ui(combined):
        return True
    # Majority vote: >= half parts individually look like Health UI.
    n = sum(1 for p in parts if ocr_suggests_wearable_ui(str(p.get("ocr_text") or "")))
    return n >= max(1, len(parts) // 2)


def coerce_wearable_family(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """Post-OCR family correction when Health UI markers dominate."""
    ocr = str(parsed.get("ocr_text") or "")
    if not ocr_suggests_wearable_ui(ocr):
        return parsed
    out = dict(parsed)
    out["document_family"] = WEARABLE_FAMILY
    out["document_type"] = "apple_watch"
    hints = list(out.get("layout_hints") or [])
    hints = [h for h in hints if h not in ("supplement_label", "supplement_facts_panel")]
    if "wearable_ui" not in hints:
        hints.append("wearable_ui")
    out["layout_hints"] = hints
    return out


def family_from_parsed(parsed: Dict[str, Any] | None) -> str:
    if not parsed:
        return UNKNOWN_FAMILY
    ocr = str(parsed.get("ocr_text") or "")
    fam = str(parsed.get("document_family") or "").strip().lower()
    if fam and fam not in (UNKNOWN_FAMILY, "other"):
        return fam
    if fam in (UNKNOWN_FAMILY, "other") and ocr_suggests_wearable_ui(ocr):
        return WEARABLE_FAMILY
    if fam:
        return fam
    if ocr_suggests_wearable_ui(ocr):
        return WEARABLE_FAMILY
    legacy = str(parsed.get("document_type") or "").strip().lower()
    if legacy in ("supplement_label", "ecommerce_product_screenshot"):
        if ocr_suggests_wearable_ui(ocr):
            return WEARABLE_FAMILY
        return SUPPLEMENT_FAMILY
    if legacy in ("apple_watch", "wearable"):
        return WEARABLE_FAMILY
    if legacy in ("lab_report",):
        return LAB_FAMILY
    return UNKNOWN_FAMILY


def requires_label_ledger_v1(parsed: Dict[str, Any] | None) -> bool:
    """Only supplement family uses ingredient_rows / G1–G6 LabelLedger gates."""
    return family_from_parsed(parsed) == SUPPLEMENT_FAMILY


def supplement_deterministic_reply_allowed(parsed: Dict[str, Any] | None) -> bool:
    return requires_label_ledger_v1(parsed)


def attachment_parse_is_actionable(parsed: Dict[str, Any] | None) -> bool:
    """True when parsed attachment has enough structure for harness routing."""
    if not parsed:
        return False
    if (parsed.get("vision_summary") or "").strip():
        return True
    if (parsed.get("label_ledger") or "").strip():
        return True
    if parsed.get("narratives"):
        return True
    if parsed.get("wearable_metrics"):
        return True
    ocr = (parsed.get("ocr_text") or "").strip()
    if ocr and ocr_suggests_wearable_ui(ocr):
        return True
    if family_from_parsed(parsed) == WEARABLE_FAMILY and ocr:
        return True
    return False


__all__ = [
    "LAB_FAMILY",
    "MEDICATION_FAMILY",
    "SUPPLEMENT_FAMILY",
    "UNKNOWN_FAMILY",
    "WEARABLE_FAMILY",
    "attachment_parse_is_actionable",
    "coerce_wearable_family",
    "family_from_parsed",
    "ocr_suggests_wearable_ui",
    "should_skip_vlm_for_wearable",
    "parts_should_finalize_as_wearable",
    "requires_label_ledger_v1",
    "supplement_deterministic_reply_allowed",
]
