#!/usr/bin/env python3
"""P1/P3 — offline CHB recompile for daily / cron use (Loop B · L1 Compile).

Never blocks chat turns. Writes ``reports/chb/{user_id}/brief_{hash}.json`` when T0
ledger hash diverges from the newest artifact.

Usage:
  python3 scripts/pha_chb_daily_recompile.py
  PHA_CHB_USER_IDS=default,alice python3 scripts/pha_chb_daily_recompile.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pha.chb_compiler import (  # noqa: E402
    chb_compiler_enabled,
    list_chb_report_user_ids,
    recompile_chb_if_stale,
)


def _user_ids(explicit: str) -> list[str]:
    raw = (explicit or os.environ.get("PHA_CHB_USER_IDS") or "default").strip()
    ids = [u.strip() for u in raw.split(",") if u.strip()]
    return ids or ["default"]


def main() -> int:
    ap = argparse.ArgumentParser(description="Offline CHB stale recompile (Loop B)")
    ap.add_argument("--user-ids", default="", help="Comma-separated user ids (default: default)")
    ap.add_argument(
        "--report-root",
        default=os.environ.get("PHA_CHB_REPORT_ROOT", str(ROOT / "reports" / "chb")),
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--include-known-artifacts",
        action="store_true",
        help="Also recompile users with existing CHB artifact dirs",
    )
    args = ap.parse_args()

    report_root = Path(args.report_root)
    users = set(_user_ids(args.user_ids))
    if args.include_known_artifacts:
        users.update(list_chb_report_user_ids(report_root=report_root))

    print("== CHB daily recompile ==")
    print(f" report_root : {report_root}")
    print(f" users       : {sorted(users)}")
    print(f" llm_interp  : {chb_compiler_enabled()}")
    print(f" dry_run     : {args.dry_run}")

    refreshed = 0
    skipped = 0
    for uid in sorted(users):
        status, path = recompile_chb_if_stale(
            uid,
            report_root=report_root,
            dry_run=args.dry_run,
        )
        if path is not None:
            refreshed += 1
            print(f" REFRESH {uid} -> {path.name} hash={status.get('artifact_hash')}")
        elif status.get("is_stale") and args.dry_run:
            refreshed += 1
            print(f" STALE   {uid} live={status.get('live_hash')} (dry-run)")
        else:
            skipped += 1
            print(f" OK      {uid} hash={status.get('artifact_hash') or status.get('live_hash')}")

    print(f"== summary refreshed={refreshed} skipped={skipped} ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
