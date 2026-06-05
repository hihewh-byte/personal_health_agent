#!/usr/bin/env python3
"""Export recent Harness JSONL lines (attachment fields) for weekly review."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default=os.environ.get("PHA_HARNESS_REPORT_PATH", "/tmp/pha-harness-reports.jsonl"))
    ap.add_argument("--limit", type=int, default=50)
    args = ap.parse_args()

    path = Path(args.path)
    if not path.is_file():
        print(f"No report file at {path}", file=sys.stderr)
        return 1

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    picked = lines[-args.limit :]
    for ln in picked:
        try:
            obj = json.loads(ln)
        except json.JSONDecodeError:
            continue
        ir = obj.get("intent_route") or {}
        if not ir.get("attachment_path_count") and not ir.get("attachment_qa_mode"):
            continue
        print(json.dumps({"intent_route": ir}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
