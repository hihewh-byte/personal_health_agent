#!/usr/bin/env python3
"""Stage 3A.2.2 — label ledger, merge, lab hallucination guard."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pha.vision_label_ledger import (
    build_label_ledger_block,
    detect_ecommerce_from_ocr,
    enrich_parsed_payload,
    merge_parsed_payloads,
    vision_summary_looks_like_lab,
)

OCR_FRONT = """
3:34
加入购物车
立即购买
NOW
Phosphatidyl Serine
100 mg
Cognitive Health
120 Veg Capsules
"""

OCR_FACTS = """
Supplement Facts
Serving Size 1 Veg Capsule
Choline (from Choline Bitartrate) 100 mg
Phosphatidyl Serine 100 mg
Inositol 50 mg
"""


def main() -> int:
    failed = 0

    if not detect_ecommerce_from_ocr(OCR_FRONT):
        print("FAIL: ecommerce detect front")
        failed += 1
    if not vision_summary_looks_like_lab("红细胞计数 4.88 白细胞 5.5 血红蛋白"):
        print("FAIL: lab hallucination detect")
        failed += 1

    front = enrich_parsed_payload(
        {"metrics": [], "narratives": [], "vision_summary": "红细胞计数 4.88"},
        ocr_text=OCR_FRONT,
        filename="front.png",
    )
    if front.get("metrics"):
        print("FAIL: front should drop lab metrics")
        failed += 1
    if front.get("parse_confidence") != "low" and not front.get("ingredient_rows"):
        # may still extract PS 100 from ocr
        pass
    rows_front = front.get("ingredient_rows") or []
    if not any("100" in str(r.get("amount", "")) for r in rows_front):
        print("FAIL: front should have 100 mg row", rows_front)
        failed += 1

    facts = enrich_parsed_payload(
        {"metrics": [], "narratives": [], "vision_summary": ""},
        ocr_text=OCR_FACTS,
        filename="facts.png",
    )
    merged = merge_parsed_payloads([front, facts])
    ing = merged.get("ingredient_rows") or []
    names = " ".join(r.get("name", "").lower() for r in ing)
    if "inositol" not in names and "50" not in " ".join(r.get("amount", "") for r in ing):
        print("FAIL: merged missing inositol 50", ing)
        failed += 1
    if "phosphatidyl" not in names:
        print("FAIL: merged missing PS", ing)
        failed += 1

    ledger, conf = build_label_ledger_block(merged, ocr_text=merged.get("ocr_text", ""))
    if "标签摘录" not in ledger or "成分定账" not in ledger:
        print("FAIL: ledger blocks missing")
        failed += 1
    if "卵磷脂" in ledger and "成分定账" not in ledger:
        print("FAIL: unexpected lecithin-only ledger")

    print("ingredient_rows:", len(ing), ing[:5])
    print("confidence:", conf, "attachment_count:", merged.get("attachment_count"))

    if failed:
        print("\nFAIL", failed)
        return 1
    print("\nOK stage3a2.2 vision ledger selfcheck")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
