#!/usr/bin/env python3
"""Selfcheck: wearable_metric_registry.json loads and matches CompareTable expectations (3d-δ-c)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pha.wearable_compare_table_v1 import COMPARABLE_METRIC_SPECS, WORKOUT_METRICS
from pha.wearable_metric_registry import (
    comparable_wearable_daily_specs,
    list_ingest_modules,
    load_wearable_metric_registry,
    registry_path,
    workout_compare_metric_ids,
)


def main() -> int:
    errors: list[str] = []
    if not registry_path().is_file():
        errors.append(f"missing registry file: {registry_path()}")
    doc = load_wearable_metric_registry()
    if doc.get("schema_version") != "wearable_metric_registry_v1":
        errors.append(f"unexpected schema_version: {doc.get('schema_version')!r}")

    daily = comparable_wearable_daily_specs()
    if daily != COMPARABLE_METRIC_SPECS:
        errors.append(f"daily specs drift: registry={daily!r} module={COMPARABLE_METRIC_SPECS!r}")

    workout = workout_compare_metric_ids()
    if workout != WORKOUT_METRICS:
        errors.append(f"workout ids drift: registry={workout!r} module={WORKOUT_METRICS!r}")

    if len(daily) < 7:
        errors.append(f"expected >=7 daily comparable metrics, got {len(daily)}")

    if list_ingest_modules():
        errors.append(
            "ingest_modules must be empty (full import only); "
            f"got {[m.get('module_id') for m in list_ingest_modules()]}"
        )

    if errors:
        for e in errors:
            print(f"FAIL  {e}")
        return 1
    print("PASS  wearable_metric_registry selfcheck (3d-δ-c)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
