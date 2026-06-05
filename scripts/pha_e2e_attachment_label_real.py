#!/usr/bin/env python3
"""
F-layer E2E: real (desensitized) supplement label images → server perception → Fixture asserts.

Requires two image paths (front + Supplement Facts). Does not start HTTP server.
Spec: docs/stage3b-e2e-real-label-fixture.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FIXTURE_DIR = os.path.join(ROOT, "tests", "fixtures", "supplement")
if FIXTURE_DIR not in sys.path:
    sys.path.insert(0, FIXTURE_DIR)

from golden_now_ps import golden_match_now_ps_choline_inositol  # noqa: E402

from pha.label_ledger_v1 import LabelLedgerV1, finalize_parsed_payload
from pha.perception_worker import finalize_attachment_parse


def _default_paths() -> tuple[Path, Path]:
    base = Path(ROOT) / "tests" / "fixtures" / "supplement" / "now_ps_6800_6801"
    return base / "IMG_6800.jpg", base / "IMG_6801.jpg"


def main() -> int:
    parser = argparse.ArgumentParser(description="PHA real-label attachment E2E (F-layer)")
    parser.add_argument("--front", help="Front / product image path")
    parser.add_argument("--facts", help="Supplement Facts image path")
    parser.add_argument("--user-id", default="e2e_fixture")
    parser.add_argument("--json-out", help="Write merged parsed payload JSON here")
    args = parser.parse_args()

    front = Path(args.front or os.environ.get("PHA_E2E_LABEL_FRONT", "")).expanduser()
    facts = Path(args.facts or os.environ.get("PHA_E2E_LABEL_FACTS", "")).expanduser()
    if not str(front) or not front.is_file():
        d_front, d_facts = _default_paths()
        front = d_front if d_front.is_file() else front
        facts = d_facts if d_facts.is_file() else facts

    if not front.is_file() or not facts.is_file():
        print(
            "SKIP: missing desensitized images.\n"
            "  Set PHA_E2E_LABEL_FRONT / PHA_E2E_LABEL_FACTS or --front/--facts\n"
            f"  Expected default dir: {Path(ROOT) / 'tests/fixtures/supplement/now_ps_6800_6801'}/\n"
            "  See docs/stage3b-e2e-real-label-fixture.md",
            file=sys.stderr,
        )
        return 2

    from pha.chat_service import _vision_parse_attachment

    parts = []
    for path in (front, facts):
        parts.append(
            _vision_parse_attachment(
                str(path),
                path.name,
                user_id=args.user_id,
                auto_ingest=False,
            ),
        )

    merged = parts[0]
    if len(parts) > 1:
        from pha.vision_label_ledger import merge_parsed_payloads

        merged = merge_parsed_payloads(parts)

    best_ch = "ocr_only"
    for p in parts:
        if str(p.get("perception_channel") or "") == "vision_structured":
            best_ch = "vision_structured"
            break

    final = finalize_attachment_parse(
        finalize_parsed_payload(
            merged,
            attachment_count=len(parts),
            parts=parts,
            perception_channel=best_ch,  # type: ignore[arg-type]
        ),
        attachment_path_count=len(parts),
        parts=parts,
        client_parse_reuse=False,
        perception_channel=best_ch,  # type: ignore[arg-type]
    )

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(final, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print("=== PHA E2E real label ===")
    print("front:", front)
    print("facts:", facts)
    print("perception_channel:", final.get("perception_channel"))
    print("parse_confidence:", final.get("parse_confidence"))
    print("reject_reasons:", final.get("reject_reasons"))
    print("attachment_count:", final.get("attachment_count"))
    print("ingredient_rows:", len(final.get("ingredient_rows") or []))
    print("brand:", (final.get("label_ledger_v1") or {}).get("brand"))

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
        return 1

    # F-layer: allow low confidence on real images until perception adapters land
    conf = str(final.get("parse_confidence") or "").lower()
    if conf == "low":
        print("WARN: parse_confidence=low (real images may fail G-rules until 3B-β adapters)")
        print("WARN: reject_reasons:", final.get("reject_reasons"))
        return 0

    print("OK: F-layer golden match + parse_confidence=", conf)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
