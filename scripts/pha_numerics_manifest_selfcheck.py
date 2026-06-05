#!/usr/bin/env python3
"""Offline self-check for numerics manifest + C-layer audit (Manifest Tier v1)."""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pha.numerics_manifest import (  # noqa: E402
    audit_response_numerics,
    build_numerics_manifest,
    format_manifest_tier0_block,
    numerics_audit_scope,
)

COMBINED_MSG = (
    "根据我所有的检验报告中的血脂情况 ，请分析HRV与运动消耗对血脂有没有影响，"
    "然后给我更新的补剂方案建议"
)

GOOD_ANSWER = (
    "低密度脂蛋白从2023年12月15日的4.05 mmol/L下降至2025年12月7日的2.45 mmol/L；"
    "HRV 均值 33.1 ms。"
)

BAD_ANSWER = (
    "2026-04-30 总胆固醇 5.1 mmol/L，LDL 3.2；"
    "请提供你的 HRV 原始数据。"
)

T0_ZH = (
    "您的 LDL 从 2023年12月15日 的 4.05 mmol/L 降至 2025年12月7日 的 2.45 mmol/L。"
)

T1_ZH = (
    "【参考标准】部分指南将 LDL 理想上限定在 3.4 mmol/L 以下"
    "（来源：中国成人血脂异常防治指南，请自行查证，非医疗建议）"
)

T1_EN = (
    "[Reference Standard] LDL ideal upper limit is often below 3.4 mmol/L "
    "(source: clinical guidelines, verify by yourself, not medical advice)"
)

T1_MIX = (
    "【参考标准】LDL 理想上限约 3.4 mmol/L（来源：中国指南摘要，请自行查证，非医疗建议）。"
    " Also [Reference Standard] general adult LDL target (source: WHO lipid note, "
    "verify by yourself, not medical advice)"
)


def _run_case(
    case_id: str,
    answer: str,
    manifest,
    *,
    require_citation: bool,
    expect_pass: bool,
    expect_violation_substr: str = "",
) -> bool:
    audit = audit_response_numerics(answer, manifest, require_citation=require_citation)
    ok = audit.get("passed") == expect_pass
    if expect_violation_substr and expect_violation_substr not in "|".join(audit.get("violations") or []):
        ok = False
    status = "OK" if ok else "FAIL"
    print(f"{status} {case_id} passed={audit.get('passed')} violations={audit.get('violations')}")
    if not ok:
        print(json.dumps(audit, ensure_ascii=False, indent=2))
    return ok


def main() -> int:
    print("=== pha_numerics_manifest_selfcheck (Manifest Tier v1) ===\n")
    print("audit_scope:", numerics_audit_scope())

    manifest = build_numerics_manifest(
        "default",
        profile="combined_review",
        user_message=COMBINED_MSG,
    )
    block = format_manifest_tier0_block(manifest)
    print(f"entries={len(manifest.entries)} dates={sorted(manifest.allowed_dates)}")
    print(f"manifest_chars={len(block)}\n")
    if "T0" not in block:
        print("FAIL: manifest header missing T0 marker")
        return 1

    lipid = [e for e in manifest.entries if e.domain == "lipid"]
    if len(lipid) < 8:
        print(f"FAIL: expected >=8 lipid entries, got {len(lipid)}")
        return 1

    failed = 0

    # R0 — strict regression (explicit scope; production default is plus)
    os.environ["PHA_NUMERICS_AUDIT_SCOPE"] = "t0_strict"
    good = audit_response_numerics(GOOD_ANSWER, manifest, require_citation=True)
    bad = audit_response_numerics(BAD_ANSWER, manifest, require_citation=True)
    if not good.get("passed"):
        print("FAIL R0: good answer strict")
        failed += 1
    if bad.get("passed"):
        print("FAIL R0: bad answer strict")
        failed += 1
    print("OK R0 strict regression")

    os.environ["PHA_NUMERICS_AUDIT_SCOPE"] = "t0_plus_disclosure"
    os.environ["PHA_NUMERICS_T1_M4_MODE"] = "warn"

    cases = [
        ("A-zh", T0_ZH + "\n" + T1_ZH, True, ""),
        ("A-en", T0_ZH + "\n" + T1_EN, True, ""),
        ("A-mix", T0_ZH + "\n" + T1_MIX, True, ""),
        ("B-zh", T0_ZH + " 理想线 3.4 mmol/L。", False, "unauthorized_value:3.4"),
        ("B-en", T0_ZH + " ideal LDL 3.4 mmol/L.", False, "unauthorized_value:3.4"),
        ("C", T0_ZH + " 您的 LDL 为 3.8 mmol/L。", False, "unauthorized_value:3.8"),
        (
            "D",
            T0_ZH
            + "【参考标准】LDL 3.4（来源：指南，非医疗建议）",
            False,
            "t1_disclosure_incomplete",
        ),
        ("E", T0_ZH + T1_ZH.replace("3.4", "4.2"), True, ""),
        (
            "H-en-fake-guide",
            T0_ZH
            + "[Reference Standard] LDL below 4.2 (source: Fake Guide 2099, verify by yourself, not medical advice)",
            True,
            "",
        ),
        (
            "I",
            T0_ZH + "【参考标准】您的 LDL 为 3.4（来源：某某指南名称，请自行查证，非医疗建议）",
            False,
            "t0_forgery_in_t1_block",
        ),
        ("F", BAD_ANSWER, False, "forbidden_date"),
    ]
    for cid, ans, exp_pass, vsub in cases:
        if not _run_case(cid, ans, manifest, require_citation=True, expect_pass=exp_pass, expect_violation_substr=vsub):
            failed += 1

    os.environ["PHA_NUMERICS_T1_M4_MODE"] = "strict"
    d_strict = T0_ZH + "【参考标准】LDL 3.4（来源：指南名，请自行查证）"
    a_d = audit_response_numerics(d_strict, manifest, require_citation=True)
    if a_d.get("passed"):
        print("FAIL D-strict: should fail without M4")
        failed += 1
    else:
        print("OK D-strict missing M4 blocks")

    os.environ.pop("PHA_NUMERICS_AUDIT_SCOPE", None)
    os.environ.pop("PHA_NUMERICS_T1_M4_MODE", None)

    wear_manifest = build_numerics_manifest(
        "default",
        profile="wearable_screenshot_review",
        user_message="对比过去90天睡眠是否正常",
    )
    wear_bad = (
        "深睡时长 sleep_deep 1hr9min 比 User Data Snapshot 近90天平均值 1hr52min 稍低。"
        "REM 2hr17min 比 REM 睡眠均值45.2 min 有所减少。"
    )
    from pha.wearable_compare_table_v1 import (
        CompareRowV1,
        CompareTableV1,
        apply_compare_table_fallback_if_needed,
        audit_wearable_compare_table,
    )

    wear_table = CompareTableV1(
        reference_date="2026-05-31",
        rows=[
            CompareRowV1(
                metric_id="sleep_deep",
                row_kind="snapshot_only",
                snapshot_value="1hr9min",
                baseline_90d_value="NO_BASELINE",
                verdict="snapshot_only",
            ),
        ],
    )
    wear_audit = audit_wearable_compare_table(wear_bad, wear_table)
    if wear_audit.get("passed"):
        print("FAIL W-wearable-stage-90d compare audit should fail")
        failed += 1
    else:
        print("OK W-wearable-stage-90d compare audit")
    fixed, fb = apply_compare_table_fallback_if_needed(wear_bad, wear_table)
    if "1hr52" in fixed:
        print("FAIL W-wearable fallback still has fabrication")
        failed += 1
    else:
        print("OK W-wearable fallback")
    wear_block = format_manifest_tier0_block(wear_manifest, profile="wearable_screenshot_review")
    if "FORBIDDEN_90D" not in wear_block:
        print("FAIL W-manifest-forbidden footer missing")
        failed += 1
    else:
        print("OK W-manifest-forbidden footer")

    print("\n" + ("OK all" if not failed else f"FAILED {failed} case(s)"))
    return failed


if __name__ == "__main__":
    raise SystemExit(main())
