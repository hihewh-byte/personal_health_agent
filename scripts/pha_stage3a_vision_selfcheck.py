#!/usr/bin/env python3
"""Stage 3A — structural OCR classify + JSON cleaner (no product name literals)."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pha.json_utils import robust_json_cleaner, safe_json_object
from pha.vision_ocr import classify_document_from_ocr, ocr_tokens
from pha.vision_supplement import extraction_from_ocr_fallback

# Generic panel text — no real brand or ingredient names.
SAMPLE_SUPPLEMENT_OCR = """
ACME NUTRITION INC
Supplement Facts
Serving Size 2 Capsules
Component Alpha 50 mcg 91%
Component Beta extract 320 mg
Component Gamma (species) leaf extract 100 mg
Other ingredients: olive oil, capsule shell.
"""

SAMPLE_LAB_OCR = """
City Hospital Laboratory
Reference Range
LDL-C mmol/L 3.2 参考范围 1.5-3.0
"""


def main() -> int:
    failed = 0

    prose = 'Sure! Here is JSON:\n```json\n{"document_type":"supplement_label","results":[]}\n```\nThanks!'
    doc = robust_json_cleaner(prose)
    if doc.get("document_type") != "supplement_label":
        print("FAIL: robust_json_cleaner fenced block", doc)
        failed += 1

    brace = 'noise {"title":"x","results":[],"narratives":[{"category":"a","content":"b"}]} tail'
    doc2 = safe_json_object(brace)
    if not doc2.get("narratives"):
        print("FAIL: brace extract", doc2)
        failed += 1

    if classify_document_from_ocr(SAMPLE_SUPPLEMENT_OCR) != "supplement_label":
        print("FAIL: supplement panel classify")
        failed += 1
    if classify_document_from_ocr(SAMPLE_LAB_OCR) != "lab_report":
        print("FAIL: lab panel classify")
        failed += 1

    toks = ocr_tokens(SAMPLE_SUPPLEMENT_OCR)
    if not any("320" in t or "mg" in t.lower() for t in toks):
        print("FAIL: dose tokens", toks[:10])
        failed += 1

    ext = extraction_from_ocr_fallback(SAMPLE_SUPPLEMENT_OCR)
    if not ext.narratives:
        print("FAIL: ocr fallback narratives empty")
        failed += 1
    if ext.results:
        print("FAIL: supplement fallback must not emit lab results", ext.results)
        failed += 1
    fact_rows = [n for n in ext.narratives if n.category == "supplement_facts"]
    if len(fact_rows) < 2:
        print("FAIL: expected multiple supplement_facts rows", fact_rows)
        failed += 1

    img = os.environ.get("PHA_STAGE3A_TEST_IMAGE", "").strip()
    if img and os.path.isfile(img):
        from pha.vision_engine import image_file_to_png_list
        from pha.vision_ocr import tesseract_ocr_png

        pages = image_file_to_png_list(open(img, "rb").read(), filename=os.path.basename(img))
        ocr = tesseract_ocr_png(pages[0]) if pages else ""
        kind = classify_document_from_ocr(ocr)
        print("live OCR chars:", len(ocr), "kind:", kind)
        if kind == "other" and len(ocr) > 80:
            print("WARN: live image classified as other — will use lab prompt + OCR block")

    if failed:
        print("\nFAIL", failed)
        return 1
    print("OK stage3a vision selfcheck (structural, no name literals)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
