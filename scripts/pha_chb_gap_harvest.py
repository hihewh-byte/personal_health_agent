#!/usr/bin/env python3
"""Loop B L2 Eval — harvest CHB gap candidates from slow_round / E2E JSONL."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pha.chb_gap_harvest import extract_chb_gap_candidates, write_gap_candidates  # noqa: E402


def _load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="Harvest CHB gap candidates (Loop B L2 Eval)")
    ap.add_argument("--candidates", default=str(ROOT / "reports" / "loop" / "slow_round_candidates.jsonl"))
    ap.add_argument("--e2e-jsonl", default="", help="Optional en_stress JSONL")
    ap.add_argument(
        "--report-root",
        default=str(ROOT / "reports" / "chb"),
    )
    args = ap.parse_args()

    rows = _load_jsonl(Path(args.candidates))
    if args.e2e_jsonl:
        rows.extend(_load_jsonl(Path(args.e2e_jsonl)))

    gaps = extract_chb_gap_candidates(rows)
    by_user: dict[str, list[dict]] = defaultdict(list)
    for g in gaps:
        by_user[str(g.get("user_id") or "default")].append(g)

    print("== CHB gap harvest ==")
    print(f" input_rows : {len(rows)}")
    print(f" gap_rows   : {len(gaps)}")
    for uid, group in sorted(by_user.items()):
        path = write_gap_candidates(group, user_id=uid, report_root=args.report_root)
        print(f" user={uid} gaps={len(group)} -> {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
