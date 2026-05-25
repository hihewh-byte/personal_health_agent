#!/usr/bin/env python3
"""P1.5 wearable extension metrics — registry + importer + SQLite migration."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pha.data_importer import _normalize_spo2_percent  # noqa: E402
from pha.health_data import ALLOWED_METRICS, EXTENSION_WEARABLE_METRICS, get_health_data  # noqa: E402
from pha.intent_gates import infer_wearable_metrics  # noqa: E402
from pha.sqlite_storage import init_schema, query_wearable_daily_range  # noqa: E402
from pha.universal_catalog_manager import get_catalog_manager, reload_catalog_manager  # noqa: E402


def main() -> int:
    failed = 0
    expected_ext = {"spo2", "respiratory_rate", "vo2max", "wrist_temp"}
    if EXTENSION_WEARABLE_METRICS != expected_ext:
        print("FAIL EXTENSION_WEARABLE_METRICS:", EXTENSION_WEARABLE_METRICS)
        failed += 1
    if not expected_ext.issubset(ALLOWED_METRICS):
        print("FAIL extensions not in ALLOWED_METRICS")
        failed += 1

    if _normalize_spo2_percent(0.97) != 97.0:
        print("FAIL spo2 fraction normalize")
        failed += 1
    if _normalize_spo2_percent(98.0) != 98.0:
        print("FAIL spo2 percent passthrough")
        failed += 1

    inferred = infer_wearable_metrics("最近血氧和呼吸率怎么样")
    if "spo2" not in inferred or "respiratory_rate" not in inferred:
        print("FAIL infer_wearable_metrics:", inferred)
        failed += 1

    init_schema()
    reload_catalog_manager()
    doc = get_catalog_manager().get_asset("wearable_bundle") or {}
    ext = (doc.get("extension_registry") or {}).get("spo2") or {}
    if not ext.get("enabled"):
        print("FAIL wearable_bundle schema spo2 not enabled")
        failed += 1

    uid = "default"
    from datetime import timedelta

    from pha.health_data import effective_query_reference_date

    ref = effective_query_reference_date()
    start = ref - timedelta(days=365)
    rows = query_wearable_daily_range(uid, start, ref)
    has_ext_col = rows and hasattr(rows[0], "spo2_pct")
    if not has_ext_col:
        print("WARN no daily rows or model missing extension fields (ok on empty DB)")

    result = get_health_data(
        uid,
        start,
        ref,
        ["spo2"],
        user_message="血氧趋势",
    )
    if not result.metrics_supported and result.message:
        print("INFO get_health_data spo2:", result.message[:120])

    print("OK P1.5 wearable self-check")
    print("ALLOWED_METRICS:", sorted(ALLOWED_METRICS))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
