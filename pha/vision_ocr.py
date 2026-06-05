"""Lightweight OCR + document classification for vision pipeline (Stage 3A).

Classification uses **label layout / units only** — never product or ingredient names.
"""

from __future__ import annotations

import io
import logging
import re
from typing import List, Literal

logger = logging.getLogger(__name__)

DocumentKind = Literal[
    "lab_report",
    "supplement_label",
    "apple_watch",
    "other",
]

# Structural FDA-style supplement panel markers (no brand/ingredient literals).
_SUPPLEMENT_FACTS_RE = re.compile(r"supplement\s+facts|营养成分表|营养成份表", re.I)
_SERVING_RE = re.compile(r"serving\s+size|每份|每次服用", re.I)
_DV_RE = re.compile(r"daily\s+value|每日参考值|\%\s*(?:daily\s+value|dv)\b|\d+\s*%", re.I)
_OTHER_ING_RE = re.compile(r"other\s+ingredients|其他成分", re.I)
_DOSE_UNIT_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:mg|mcg|μg|ug|g|iu|ml)\b",
    re.I,
)
_FORM_RE = re.compile(r"\bcapsules?\b|\bsoftgels?\b|\btablets?\b|胶囊|片剂", re.I)

_LAB_HINT_RE = re.compile(
    r"reference\s+range|参考范围|检验项目|化验|检验报告|"
    r"hospital|医院|mmol|μmol|umol/l|mmhg",
    re.I,
)
_WATCH_HINT_RE = re.compile(
    r"\bhrv\b|rmssd|apple\s+watch|health\b|静息心率|resting\s+heart|"
    r"time\s+asleep|blood\s+oxygen|血氧|respiratory\s+rate|"
    r"heart\s+rate\s+variability|variability|锻炼|workouts?",
    re.I,
)


def tesseract_ocr_png(png_bytes: bytes, *, lang: str = "eng") -> str:
    """Best-effort local OCR (0 VRAM) with multi-pass preprocessing."""
    if not png_bytes:
        return ""
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        logger.warning("pytesseract/Pillow not available: %s", exc)
        return ""
    try:
        with Image.open(io.BytesIO(png_bytes)) as base_img:
            if base_img.mode not in ("RGB", "L"):
                base_img = base_img.convert("RGB")
            variants = _ocr_variants(base_img)
            best = ""
            best_score = -1
            for img, config in variants:
                txt = (pytesseract.image_to_string(img, lang=lang, config=config) or "").strip()
                score = _ocr_quality_score(txt)
                if score > best_score:
                    best_score = score
                    best = txt
            return best
    except Exception as exc:
        logger.warning("Tesseract OCR failed: %s", exc)
        return ""


def _ocr_quality_score(text: str) -> int:
    raw = (text or "").strip()
    if not raw:
        return 0
    chars = len(raw)
    lines = len([ln for ln in raw.splitlines() if ln.strip()])
    dose_hits = len(_DOSE_UNIT_RE.findall(raw))
    panel_hits = int(bool(_SUPPLEMENT_FACTS_RE.search(raw))) + int(bool(_SERVING_RE.search(raw)))
    return chars + lines * 4 + dose_hits * 10 + panel_hits * 12


def _ocr_variants(img: "Image.Image") -> List[tuple["Image.Image", str]]:
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps

    # Upscale small text-heavy labels before OCR.
    base = img
    if min(base.size) < 1200:
        scale = max(1.0, 1800.0 / float(min(base.size)))
        if scale > 1.0:
            base = base.resize(
                (int(base.size[0] * scale), int(base.size[1] * scale)),
                Image.Resampling.LANCZOS,
            )

    gray = ImageOps.grayscale(base)
    hi_contrast = ImageEnhance.Contrast(gray).enhance(1.8)
    sharpen = hi_contrast.filter(ImageFilter.SHARPEN)
    bw = hi_contrast.point(lambda p: 255 if p > 160 else 0)

    return [
        (base, "--psm 6"),
        (gray, "--psm 6"),
        (hi_contrast, "--psm 6"),
        (sharpen, "--psm 4"),
        (bw, "--psm 11"),
    ]


def ocr_tokens(ocr_text: str, *, max_tokens: int = 80) -> List[str]:
    """Distinct alphanumeric tokens from OCR (for vision matching prompts)."""
    raw = ocr_text or ""
    found: List[str] = []
    seen: set[str] = set()
    for m in re.finditer(
        r"[A-Za-z][A-Za-z0-9+./\-]{2,}|\d+(?:\.\d+)?\s*(?:mg|mcg|μg|ug|g|iu)\b",
        raw,
    ):
        tok = m.group(0).strip()
        key = tok.lower()
        if key in seen or len(tok) < 3:
            continue
        seen.add(key)
        found.append(tok)
        if len(found) >= max_tokens:
            break
    return found


def _score_supplement_label(ocr_text: str) -> int:
    o = ocr_text or ""
    if not o.strip():
        return 0
    score = 0
    if _SUPPLEMENT_FACTS_RE.search(o):
        score += 4
    if _SERVING_RE.search(o):
        score += 2
    if _DV_RE.search(o):
        score += 2
    if _OTHER_ING_RE.search(o):
        score += 2
    if _FORM_RE.search(o):
        score += 1
    dose_hits = len(_DOSE_UNIT_RE.findall(o))
    if dose_hits >= 2:
        score += min(3, dose_hits)
    # Panel without explicit header: serving + multiple dose lines
    if not _SUPPLEMENT_FACTS_RE.search(o) and _SERVING_RE.search(o) and dose_hits >= 3:
        score += 3
    return score


def _score_lab_report(ocr_text: str) -> int:
    o = ocr_text or ""
    score = 0
    if _LAB_HINT_RE.search(o):
        score += 3
    if re.search(r"\b(?:ldl|hdl|tc|tg|glucose|血糖|胆固醇)\b", o, re.I):
        score += 2
    return score


def classify_document_from_ocr(ocr_text: str) -> DocumentKind:
    o = ocr_text or ""
    if _WATCH_HINT_RE.search(o):
        return "apple_watch"
    lab_s = _score_lab_report(o)
    supp_s = _score_supplement_label(o)
    if supp_s >= 4 and supp_s >= lab_s:
        return "supplement_label"
    if lab_s >= 3 and lab_s > supp_s:
        return "lab_report"
    if supp_s >= 3:
        return "supplement_label"
    return "other"


def format_ocr_context_block(ocr_text: str, *, max_chars: int = 2400) -> str:
    """Header block injected into vision user message."""
    text = (ocr_text or "").strip()
    if not text:
        return ""
    clipped = text[:max_chars]
    tokens = ocr_tokens(text)
    tok_line = ", ".join(tokens[:40]) if tokens else "(none)"
    return (
        "【raw_ocr_metadata · 印刷体死字，优先于图像脑补】\n"
        f"tokens: {tok_line}\n"
        f"full_text:\n{clipped}"
    )


def asset_whitelist_hint() -> str:
    """Catalog asset ids for vision multiple-choice (schema registry, not product names)."""
    return (
        "catalog_asset_whitelist: lab_lipid_panel, wearable_bundle, supplement_bg "
        "(map product/regimen labels → supplement_bg; do NOT invent new asset ids)"
    )
