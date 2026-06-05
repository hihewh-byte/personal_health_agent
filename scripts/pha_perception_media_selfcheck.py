#!/usr/bin/env python3
"""L0.0 / L0.5 perception media routing selfcheck."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pha.perception_media import (
    classify_document_family,
    detect_media_route,
    legacy_doc_kind_from_family,
)


def main() -> int:
    failed = 0
    route, meta = detect_media_route(b"fake", "test.jpg")
    if route != "raster_photo":
        print("FAIL: jpg route", route)
        failed += 1

    ocr = "Supplement Facts\nServing Size 1 capsule\nPhosphatidyl Serine 100 mg"
    fam, conf, _ = classify_document_family(ocr)
    if fam != "supplement":
        print("FAIL: supplement family", fam, conf)
        failed += 1
    if legacy_doc_kind_from_family(fam) != "supplement_label":
        print("FAIL: legacy kind")
        failed += 1

    lab = "检验项目 参考范围 LDL 3.2 mmol/L 医院"
    fam2, _, _ = classify_document_family(lab)
    if fam2 != "lab":
        print("FAIL: lab family", fam2)
        failed += 1

    if failed:
        return 1
    print("OK: perception_media selfcheck")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
