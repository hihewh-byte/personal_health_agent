#!/usr/bin/env python3
"""Selfcheck: wearable_metric_probe intent → warehouse readiness (Wave 3d C-20)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pha.wearable_metric_probe import (
    infer_requested_compare_metric_ids,
    probe_wearable_metric_needs,
    warehouse_ready_for_metric,
)


def main() -> int:
    errors: list[str] = []

    broad = infer_requested_compare_metric_ids("帮我看这些指标和过去90天比是否正常")
    if len(broad) < 5:
        errors.append(f"broad compare should request >=5 metrics, got {broad!r}")

    workout = infer_requested_compare_metric_ids("最近锻炼心率范围怎么样")
    if "workout_heart_rate_range_bpm" not in workout:
        errors.append(f"workout hint missing workout metrics: {workout!r}")

    stage = infer_requested_compare_metric_ids("深睡和REM对比90天")
    if "sleep_deep" not in stage or "sleep_rem" not in stage:
        errors.append(f"stage hint missing sleep_deep/rem: {stage!r}")

    empty = probe_wearable_metric_needs("default", "今天天气怎么样")
    if empty.get("requested_metric_ids"):
        errors.append(f"casual message should not probe metrics: {empty!r}")

    probe = probe_wearable_metric_needs("default", "锻炼次数和90天比")
    if not probe.get("requested_metric_ids"):
        errors.append("workout compare should request metrics")
    if "user_message_zh" not in probe:
        errors.append("probe payload missing user_message_zh")

    ok, reason = warehouse_ready_for_metric("default", "sleep_time_asleep")
    if not ok and reason not in ("insufficient_days", "no_daily_warehouse", "ready"):
        errors.append(f"unexpected ready reason for sleep: {reason!r}")

    bogus, bogus_reason = warehouse_ready_for_metric("default", "not_a_metric")
    if bogus or bogus_reason != "not_registered":
        errors.append(f"unknown metric should be not_registered: {bogus!r} {bogus_reason!r}")

    if errors:
        for e in errors:
            print(f"FAIL  {e}")
        return 1
    print("PASS  wearable_metric_probe selfcheck (C-20)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
