#!/usr/bin/env python3
"""Incremental HKWorkout backfill — does not wipe wearable_daily / Record samples."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pha.data_importer import AppleHealthParser
from pha.workout_storage import (
    clear_workout_sessions,
    count_workout_sessions_in_range,
    rebuild_workout_daily_rollup,
)
from datetime import date


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill wearable_workout_sessions from export.zip")
    ap.add_argument("zip_path", type=Path, help="Path to Apple Health export.zip")
    ap.add_argument("--user-id", default="default")
    ap.add_argument(
        "--clear",
        action="store_true",
        help="Delete existing workout sessions for this user before backfill (needed to fix HR stats)",
    )
    args = ap.parse_args()

    zp = args.zip_path.expanduser().resolve()
    if not zp.is_file():
        print(f"FAIL: not a file: {zp}")
        return 1

    before = count_workout_sessions_in_range(args.user_id, date(2000, 1, 1), date(2100, 1, 1))
    print(f"workout sessions before: {before}")
    if args.clear and before > 0:
        clear_workout_sessions(args.user_id)
        print(f"cleared {before} workout sessions for user={args.user_id}")
        before = 0

    with zp.open("rb") as fh:
        result = AppleHealthParser(args.user_id).backfill_workouts_from_zip(
            fh,
            filename=zp.name,
            on_progress=lambda c, t, m: print(m),
        )

    after = count_workout_sessions_in_range(args.user_id, date(2000, 1, 1), date(2100, 1, 1))
    rebuild_workout_daily_rollup(args.user_id)
    print(result.message)
    print(f"workout sessions after: {after}")
    print("OK" if after > before else "WARN: no new sessions (zip may lack Workout or all duplicates)")
    return 0 if after > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
