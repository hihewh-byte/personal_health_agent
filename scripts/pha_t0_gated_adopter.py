#!/usr/bin/env python3
"""Loop B gated adopter — apply reviewed T0 ingest proposals (never auto-merge)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pha.t0_gated_adopter import (  # noqa: E402
    apply_t0_ingest_proposal,
    write_adoption_record,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="Gated T0 ingest adopter (proposal → append-only write)")
    ap.add_argument("--proposal", required=True, help="pha.t0_ingest_proposal/v1 JSON")
    ap.add_argument(
        "--out-dir",
        default=str(ROOT / "reports" / "loop" / "t0_adoptions"),
    )
    ap.add_argument("--apply", action="store_true", help="Write T0 (requires --confirm)")
    ap.add_argument(
        "--confirm",
        default=os.environ.get("PHA_T0_ADOPT_CONFIRM", ""),
        help="Explicit adoption token (or PHA_T0_ADOPT_CONFIRM env)",
    )
    ap.add_argument(
        "--allow-user-statement",
        action="store_true",
        help="Allow user_statement rows (default blocked)",
    )
    ap.add_argument(
        "--recompile-chb",
        action="store_true",
        help="After apply, run CHB stale recompile for proposal user_id",
    )
    args = ap.parse_args()

    proposal_path = Path(args.proposal)
    doc = json.loads(proposal_path.read_text(encoding="utf-8"))
    dry_run = not args.apply
    result = apply_t0_ingest_proposal(
        doc,
        proposal_path=str(proposal_path),
        allow_user_statement=args.allow_user_statement,
        confirm_token=args.confirm,
        dry_run=dry_run,
    )

    print("== T0 gated adopter ==")
    print(f" proposal : {proposal_path}")
    print(f" mode     : {'APPLY' if args.apply else 'DRY-RUN'}")
    print(f" veto     : {result.veto or 'none'}")
    print(f" applied  : {result.applied}")
    print(f" skipped  : {result.skipped}")

    if not result.rows:
        return 1 if result.veto else 0

    record = result.rows[0]
    out_path = write_adoption_record(record, out_dir=Path(args.out_dir))
    print(f" record   : {out_path}")

    if args.apply and result.applied > 0 and args.recompile_chb:
        from pha.chb_compiler import recompile_chb_if_stale

        uid = str(doc.get("user_id") or "default")
        status, path = recompile_chb_if_stale(uid)
        print(f" chb      : stale={status.get('is_stale')} path={path}")

    if result.veto:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
