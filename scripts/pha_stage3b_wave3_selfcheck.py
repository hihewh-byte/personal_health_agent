#!/usr/bin/env python3
"""Wave 3 selfcheck: layout_region + G6/warnings decoupling."""

from __future__ import annotations

import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pha.label_ledger_v1 import IngredientRowV1, LabelLedgerV1, assess_confidence
from pha.layout_region import detect_layout_regions, layout_hints_from_regions, primary_parse_regions
from pha.perception_arbitration import merge_ocr_texts


def _tiny_png() -> bytes:
    from PIL import Image

    img = Image.new("RGB", (200, 400), color=(255, 255, 255))
    # top blank
    for y in range(80, 320):
        for x in range(20, 180):
            if (x + y) % 7 == 0:
                img.putpixel((x, y), (0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_g6_warning_only() -> bool:
    leg = LabelLedgerV1(
        attachment_count=2,
        ingredient_rows=[
            IngredientRowV1(name="Test Compound", amount="10", unit="mg"),
        ],
        layout_hints=["supplement_front"],
        layout_hints_per_image=[
            {"index": 0, "hints": ["supplement_front"]},
            {"index": 1, "hints": ["supplement_front"]},
        ],
        ocr_char_count=200,
        ledger_markdown="Test Compound 10 mg",
    )
    conf, reasons, warns = assess_confidence(leg, attachment_count=2)
    if conf != "high":
        print("FAIL: expected high when rows parseable without panel hint", conf, reasons)
        return False
    if "missing_authoritative_panel" in reasons:
        print("FAIL: panel alone blocked", reasons)
        return False
    if "layout_panel_hint_missing" not in warns:
        print("FAIL: expected layout_panel_hint_missing warning", warns)
        return False
    return True


def test_layout_regions() -> bool:
    png = _tiny_png()
    regions = detect_layout_regions(png)
    if not regions:
        print("FAIL: no regions")
        return False
    primary = primary_parse_regions(regions)
    if not primary:
        print("FAIL: no primary regions")
        return False
    hints = layout_hints_from_regions(regions)
    if not isinstance(hints, list):
        print("FAIL: hints type")
        return False
    return True


def test_merge_ocr() -> bool:
    a = "Line A\n10 mg"
    b = "Line B\n20 mg"
    merged = merge_ocr_texts(a, b)
    if "Line A" not in merged or "Line B" not in merged:
        print("FAIL: merge_ocr", merged)
        return False
    return True


def main() -> int:
    failed = 0
    for name, fn in (
        ("g6_warning", test_g6_warning_only),
        ("layout_regions", test_layout_regions),
        ("merge_ocr", test_merge_ocr),
    ):
        if not fn():
            failed += 1
        else:
            print(f"OK  {name}")
    if failed:
        return 1
    print("OK: stage3b wave3 selfcheck")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
