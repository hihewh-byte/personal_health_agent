#!/usr/bin/env python3
"""F-layer: PNG → layout_region OCR → wearable metric candidates (Wave 3d-perception-v1)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "wearable"
PNG_MANIFEST = FIXTURE_DIR / "png_manifest.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_manifest() -> list[dict]:
    if not PNG_MANIFEST.is_file():
        return []
    return json.loads(PNG_MANIFEST.read_text(encoding="utf-8"))


def _ocr_png(path: Path) -> str:
    from pha.layout_region import ocr_with_layout_regions

    raw = path.read_bytes()
    text, _regions, _telem = ocr_with_layout_regions(raw, source_page_index=0)
    return (text or "").strip()


def main() -> int:
    manifest = _load_manifest()
    if not manifest:
        print("SKIP pha_wearable_perception_regression: no png_manifest.json entries")
        return 0

    from pha.wearable_snapshot_v1 import extract_metrics_from_ocr, merge_wearable_parts

    fails: list[str] = []
    for entry in manifest:
        fid = str(entry.get("fixture_id") or "?")
        rel = str(entry.get("path") or "")
        png_path = FIXTURE_DIR / rel
        if not png_path.is_file():
            fails.append(f"{fid}: missing png {png_path}")
            continue
        try:
            ocr_text = _ocr_png(png_path)
        except Exception as exc:
            fails.append(f"{fid}: OCR failed ({exc})")
            continue
        if not ocr_text:
            fails.append(f"{fid}: empty OCR")
            continue

        expected = dict(entry.get("expected_metrics") or {})
        if entry.get("merge_with"):
            parts = [{"ocr_text": ocr_text, "document_family": "wearable"}]
            for extra in entry.get("merge_with") or []:
                parts.append({"ocr_text": str(extra), "document_family": "wearable"})
            ledger = merge_wearable_parts(parts)
            actual = {m.metric_id: m.value for m in ledger.metrics}
        else:
            actual = {m.metric_id: m.value for m in extract_metrics_from_ocr(ocr_text)}

        for mid, want in expected.items():
            got = actual.get(mid)
            if got != want:
                fails.append(f"{fid} {mid}: want={want!r} got={got!r} ocr_head={ocr_text[:120]!r}")

    if fails:
        print("FAIL pha_wearable_perception_regression:")
        for f in fails:
            print(" ", f)
        return 1
    print(f"OK pha_wearable_perception_regression ({len(manifest)} png fixture(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
