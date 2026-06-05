#!/usr/bin/env python3
"""Selfcheck: sleep deep/REM daily rollup + CompareTable comparable rows (3d-δ-a)."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pha.sqlite_storage import rebuild_daily_sleep_from_segments, query_wearable_daily_range
from pha.wearable_compare_table_v1 import build_wearable_compare_table_v1


def _load_golden_ocr():
    p = _ROOT / "tests/fixtures/wearable/golden_ocr.json"
    return json.loads(p.read_text(encoding="utf-8"))


def _finalize_first_panel(ocr: dict, user_message: str):
    from scripts.pha_wearable_compare_table_selfcheck import finalize_wearable_attachment

    panels = ocr.get("panels") or []
    parts = [{"ocr_text": p["ocr_text"], "document_family": "wearable"} for p in panels]
    return finalize_wearable_attachment(
        parts[0],
        attachment_count=len(parts),
        user_message=user_message,
        parts=parts,
    )


def test_rebuild_populates_stage_columns() -> bool:
    uid = "default"
    n = rebuild_daily_sleep_from_segments(uid)
    if n <= 0:
        print("SKIP rebuild: no sleep segments for user", uid)
        return True
    rows = list(query_wearable_daily_range(uid, date(2026, 1, 1), date(2030, 1, 1)))
    with_deep = [r for r in rows if r.sleep_deep_hours is not None and r.sleep_deep_hours > 0]
    with_rem = [r for r in rows if r.sleep_rem_hours is not None and r.sleep_rem_hours > 0]
    if not with_deep and not with_rem:
        print("FAIL no sleep_deep_hours/sleep_rem_hours after rebuild", n, "days")
        return False
    print("OK stage columns deep_days=", len(with_deep), "rem_days=", len(with_rem))
    return True


def test_compare_table_stage_baseline_when_warehouse() -> bool:
    ocr = _load_golden_ocr()
    parsed = _finalize_first_panel(ocr, "对比过去90天是否正常，尤其睡眠")
    table = build_wearable_compare_table_v1(parsed, user_message="对比过去90天")
    deep = next((r for r in table.rows if r.metric_id == "sleep_deep"), None)
    rem = next((r for r in table.rows if r.metric_id == "sleep_rem"), None)
    if not deep or not rem:
        print("FAIL missing sleep_deep/rem rows")
        return False
  # If warehouse has stage data, expect comparable; else snapshot_only
    if deep.baseline_90d_value != "NO_BASELINE":
        if deep.row_kind != "comparable_90d":
            print("FAIL sleep_deep expected comparable_90d", deep.row_kind)
            return False
        print("OK sleep_deep comparable baseline", deep.baseline_90d_value, deep.baseline_90d_range)
    else:
        if deep.row_kind != "snapshot_only":
            print("FAIL sleep_deep expected snapshot_only")
            return False
        print("OK sleep_deep snapshot_only (warehouse empty)")
    return True


def main() -> int:
    ok = test_rebuild_populates_stage_columns() and test_compare_table_stage_baseline_when_warehouse()
    print("pha_sleep_stage_rollup_selfcheck:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
