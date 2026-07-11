#!/usr/bin/env python3
"""A+ SchemaIntentRouter self-check (no LLM)."""

from __future__ import annotations

import os
import sys

os.environ["PHA_CATALOG_EXISTENCE_VETO"] = "0"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pha.evidence_catalog import build_evidence_catalog_block  # noqa: E402
from pha.intent_gates import resolve_schema_intent  # noqa: E402
from pha.universal_catalog_manager import reload_catalog_manager  # noqa: E402

SPO2_MSG = "请分析最近90天我的睡眠时间的血氧数据是否正常"
SUPPLEMENT_MSG = """以下是我的补剂方案：
上午 训练后 蛋白粉30g + 香蕉 + 5g肌酸 + B族 + 益生菌
中午 鱼油 + 卵磷脂 + D3+K2 + Q10 + 非布司他 + 他汀
晚上 烤红薯 + 蛋白 + 蔬菜 + Move Free + 姜黄素
睡前 镁300-400mg + 纳豆激酶 + 南非醉茄
"""
COMBINED_MSG = (
    "根据我所有的检验报告中的血脂情况，请分析HRV与运动消耗对血脂有没有影响，"
    "然后给我更新的补剂方案建议"
)


def main() -> int:
    reload_catalog_manager()
    failed = 0

    spo2 = resolve_schema_intent(SPO2_MSG)
    if spo2.profile != "wearable_only":
        print("FAIL spo2 profile:", spo2.profile, spo2.asset_scores)
        failed += 1
    cat_spo2 = build_evidence_catalog_block(profile="combined_review", user_message=SPO2_MSG)
    if "supplement_bg" in cat_spo2:
        print("FAIL spo2 catalog should hide supplement_bg")
        failed += 1
    if cat_spo2.count("\n- ") != 2:
        print("FAIL spo2 combined catalog lines:", cat_spo2.count("\n- "))
        failed += 1

    supp = resolve_schema_intent(SUPPLEMENT_MSG)
    if supp.profile != "supplement_manifest":
        print("FAIL supplement profile:", supp.profile, supp.asset_scores)
        failed += 1

    comb = resolve_schema_intent(COMBINED_MSG)
    if comb.profile != "combined_review":
        print("FAIL combined profile:", comb.profile, comb.asset_scores)
        failed += 1
    if not comb.include_supplement_catalog:
        print("FAIL combined should include supplement catalog row")
        failed += 1
    cat_comb = build_evidence_catalog_block(profile="combined_review", user_message=COMBINED_MSG)
    if "supplement_bg" not in cat_comb:
        print("FAIL combined catalog missing supplement_bg")
        failed += 1

    print("OK schema intent self-check")
    print("spo2:", spo2.profile, spo2.asset_scores)
    print("supplement:", supp.profile, supp.asset_scores)
    print("combined:", comb.profile, comb.include_supplement_catalog, comb.asset_scores)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
