#!/usr/bin/env python3
"""Selfcheck: HKWorkout import + CompareTable workout baselines (3d-δ-b)."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pha.workout_storage import (
    count_workout_sessions_in_range,
    query_workout_sessions_in_range,
    rebuild_workout_daily_rollup,
)
from pha.wearable_compare_table_v1 import build_wearable_compare_table_v1


def _load_golden_ocr():
    return json.loads(
        (_ROOT / "tests/fixtures/wearable/golden_ocr.json").read_text(encoding="utf-8"),
    )


def _finalize(ocr: dict, user_message: str):
    from scripts.pha_wearable_compare_table_selfcheck import finalize_wearable_attachment

    panels = ocr.get("panels") or []
    parts = [{"ocr_text": p["ocr_text"], "document_family": "wearable"} for p in panels]
    return finalize_wearable_attachment(
        parts[0],
        attachment_count=len(parts),
        user_message=user_message,
        parts=parts,
    )


def test_workout_sessions_exist() -> bool:
    uid = "default"
    n = rebuild_workout_daily_rollup(uid)
    total = count_workout_sessions_in_range(uid, date(2020, 1, 1), date(2035, 1, 1))
    if total <= 0:
        print("SKIP no workout sessions in DB — re-import export.zip to enable G-Delta-2")
        return True
    with_hr = [
        s
        for s in query_workout_sessions_in_range(uid, date(2020, 1, 1), date(2035, 1, 1))
        if s.get("hr_min_bpm") is not None and s.get("hr_max_bpm") is not None
    ]
    if not with_hr:
        print("FAIL workouts exist but none have HR statistics")
        return False
    print("OK workout sessions=", total, "with_hr=", len(with_hr), "daily_rollup_days=", n)
    return True


def test_compare_workout_comparable_when_warehouse() -> bool:
    ocr = _load_golden_ocr()
    msg = (
        "附件是5月30号的apple watch，请分析锻炼与过去90天相比是否正常"
    )
    parsed = _finalize(ocr, msg)
    table = build_wearable_compare_table_v1(parsed, user_message=msg, user_id="default")
    hr = next((r for r in table.rows if r.metric_id == "workout_heart_rate_range_bpm"), None)
    cnt = next((r for r in table.rows if r.metric_id == "workout_count_recent"), None)
    if not hr or not cnt:
        print("FAIL missing workout compare rows")
        return False
    if count_workout_sessions_in_range("default", date(2020, 1, 1), date(2035, 1, 1)) <= 0:
        print("OK workout rows present (snapshot_only — no HK import yet)")
        return True
    if hr.baseline_90d_value == "NO_BASELINE":
        print("FAIL expected workout HR comparable baseline")
        return False
    print("OK workout HR baseline", hr.baseline_90d_value, hr.baseline_90d_range)
    print("OK workout count baseline", cnt.baseline_90d_value, cnt.baseline_90d_range)
    return True


def main() -> int:
    ok = test_workout_sessions_exist() and test_compare_workout_comparable_when_warehouse()
    print("pha_workout_import_selfcheck:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
