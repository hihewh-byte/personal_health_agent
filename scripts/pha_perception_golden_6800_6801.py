#!/usr/bin/env python3
"""Stage 3B Fixture golden (F-layer) — now_ps_6800_6801 synthetic OCR.

Not a production gate. Run only when architecture regression is enabled.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FIXTURE_DIR = os.path.join(ROOT, "tests", "fixtures", "supplement")
if FIXTURE_DIR not in sys.path:
    sys.path.insert(0, FIXTURE_DIR)

from golden_now_ps import golden_match_now_ps_choline_inositol  # noqa: E402

from pha.label_ledger_v1 import LabelLedgerV1, finalize_parsed_payload
from pha.vision_label_ledger import enrich_parsed_payload, merge_parsed_payloads

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


def _part(ocr: str, name: str) -> dict:
    p = enrich_parsed_payload(
        {"metrics": [], "narratives": [], "vision_summary": ""},
        ocr_text=ocr,
        filename=name,
    )
    p["source_filename"] = name
    return p


def main() -> int:
    failed = 0
    front = _part(OCR_FRONT, "IMG_6800-front.png")
    facts = _part(OCR_FACTS, "IMG_6801-facts.png")
    merged = merge_parsed_payloads([front, facts])
    final = finalize_parsed_payload(
        merged,
        attachment_count=2,
        parts=[front, facts],
        perception_channel="ocr_only",
    )

    raw = final.get("label_ledger_v1") or {}
    try:
        ledger = LabelLedgerV1.model_validate(raw)
    except Exception as exc:
        print("FAIL: invalid LabelLedgerV1", exc)
        return 1

    fails = golden_match_now_ps_choline_inositol(ledger)
    if fails:
        for f in fails:
            print("FAIL:", f)
        print("ingredient_rows:", ledger.ingredient_rows)
        print("brand:", ledger.brand)
        failed += len(fails)
    else:
        print("OK golden 6800+6801")
        print("brand:", ledger.brand)
        print("rows:", [(r.name, r.amount_display) for r in ledger.ingredient_rows[:6]])
        print("confidence:", ledger.parse_confidence)

    if failed:
        print("\nFAIL", failed, "checks")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
