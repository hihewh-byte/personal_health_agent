#!/usr/bin/env python3
"""P1.6 DCH — dynamic catalog hints + schema-driven infer_wearable_metrics."""

from __future__ import annotations

import os
import sys

os.environ["PHA_CATALOG_EXISTENCE_VETO"] = "0"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pha.evidence_catalog import build_evidence_catalog_block  # noqa: E402
from pha.intent_gates import infer_wearable_metrics  # noqa: E402
from pha.universal_catalog_manager import reload_catalog_manager  # noqa: E402

T_COMBINED = (
    "根据检验报告血脂，分析血氧和HRV对血脂的影响，并给补剂建议"
)
T_SPO2_ONLY = "我最近血氧正常吗"
T_GENERIC = "你好"


def main() -> int:
    reload_catalog_manager()
    failed = 0

    cat_spo2 = build_evidence_catalog_block(
        profile="combined_review",
        user_message=T_COMBINED,
    )
    if "血氧" not in cat_spo2:
        print("FAIL combined catalog should mention 血氧 dynamically")
        failed += 1
    if cat_spo2.count("HRV") + cat_spo2.count("步数") + cat_spo2.count("睡眠") > 6:
        print("FAIL catalog should not list all 9 metrics statically")
        failed += 1

    cat_generic = build_evidence_catalog_block(
        profile="combined_review",
        user_message=T_GENERIC,
    )
    if "本轮命中" not in cat_generic:
        print("FAIL generic catalog missing DCH fallback hints")
        failed += 1

    m = infer_wearable_metrics(T_COMBINED)
    if "spo2" not in m or "hrv" not in m:
        print("FAIL infer metrics for combined:", m)
        failed += 1

    m2 = infer_wearable_metrics(T_SPO2_ONLY)
    if m2 != ["spo2"]:
        print("FAIL spo2-only infer expected ['spo2'], got", m2)
        failed += 1

    print("OK P1.6 DCH self-check")
    print("combined catalog snippet:", [ln for ln in cat_spo2.splitlines() if "wearable" in ln][:1])
    print("infer combined:", m)
    print("infer spo2-only:", m2)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
