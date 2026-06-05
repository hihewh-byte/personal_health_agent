#!/usr/bin/env python3
"""Wave 3d-γ Phase 1: wearable golden OCR + CompareTable fixture selfcheck."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE_ROOT = os.path.join(ROOT, "tests", "fixtures", "wearable")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if FIXTURE_ROOT not in sys.path:
    sys.path.insert(0, FIXTURE_ROOT)

from golden_wearable import golden_match_all, load_golden_compare_table, load_golden_ocr  # noqa: E402


def main() -> int:
    ocr = load_golden_ocr()
    cmp = load_golden_compare_table()
    print(f"golden_ocr: {ocr.get('fixture_id')} panels={len(ocr.get('panels') or [])}")
    print(f"golden_compare: {cmp.get('fixture_id')} rows={len((cmp.get('expected_standard') or {}).get('rows') or [])}")

    fails = golden_match_all()
    if fails:
        print("FAIL pha_wearable_golden_fixture:")
        for f in fails:
            print(" ", f)
        return 1
    print("OK pha_wearable_golden_fixture (γ-1.1 ~ γ-1.3)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
