#!/usr/bin/env python3
"""Generate Loop B T0 ingest proposals from parsed attachment JSON.

Input can be a single parsed payload JSON, a list of parsed payloads, or an E2E
done payload containing ``ingest_payload``. Output is proposal-only.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pha.t0_ingest_proposal import build_t0_ingest_proposal  # noqa: E402


def _load_payloads(path: Path) -> list[dict[str, Any]]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(doc, list):
        return [d for d in doc if isinstance(d, dict)]
    if not isinstance(doc, dict):
        return []
    if isinstance(doc.get("ingest_payload"), dict):
        return [doc["ingest_payload"]]
    if isinstance(doc.get("parsed_payload"), dict):
        return [doc["parsed_payload"]]
    return [doc]


def main() -> int:
    ap = argparse.ArgumentParser(description="Build T0 ingest proposal from parsed attachment JSON")
    ap.add_argument("--input", required=True, help="Parsed payload JSON")
    ap.add_argument("--user-id", default="default")
    ap.add_argument(
        "--out-dir",
        default=str(ROOT / "reports" / "loop" / "t0_ingest_proposals"),
    )
    args = ap.parse_args()

    payloads = _load_payloads(Path(args.input))
    proposal = build_t0_ingest_proposal(payloads, user_id=args.user_id)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"t0_ingest_proposal_{ts}.json"
    out_path.write_text(json.dumps(proposal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("== T0 ingest proposal ==")
    print(f" input : {args.input}")
    print(f" payloads : {len(payloads)}")
    print(f" rows : {proposal['row_count']}")
    print(f" output : {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
