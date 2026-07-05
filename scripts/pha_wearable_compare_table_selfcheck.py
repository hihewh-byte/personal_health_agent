#!/usr/bin/env python3
"""Wave 3d-γ-a selfcheck: CompareTableV1 build vs golden fixture."""

from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE_ROOT = os.path.join(ROOT, "tests", "fixtures", "wearable")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if FIXTURE_ROOT not in sys.path:
    sys.path.insert(0, FIXTURE_ROOT)

from datetime import date

from golden_wearable import load_golden_compare_table, load_golden_ocr  # noqa: E402
from pha.wearable_compare_table_v1 import (  # noqa: E402
    build_wearable_compare_table_v1,
    compute_verdict,
    parse_snapshot_numeric,
    user_requests_workout_compare,
)
from pha.wearable_snapshot_v1 import finalize_wearable_attachment  # noqa: E402


def test_verdict_range_alignment() -> bool:
    if compute_verdict(8.72, range_min=6.4, range_max=9.9) != "within_range":
        print("FAIL sleep within range")
        return False
    if compute_verdict(10.5, range_min=6.4, range_max=9.9) != "above_mean":
        print("FAIL above range")
        return False
    if compute_verdict(5.0, range_min=6.4, range_max=9.9) != "below_mean":
        print("FAIL below range")
        return False
    return True


def test_parse_snapshot_numeric() -> bool:
    if parse_snapshot_numeric("sleep_time_asleep", "8hr43min") != 8 + 43 / 60:
        print("FAIL parse sleep")
        return False
    if parse_snapshot_numeric("hrv_rmssd_ms", "30") != 30.0:
        print("FAIL parse hrv")
        return False
    return True


def test_golden_compare_standard() -> bool:
    ocr = load_golden_ocr()
    cmp_fix = load_golden_compare_table()
    panels = ocr.get("panels") or []
    parts = [{"ocr_text": p["ocr_text"], "document_family": "wearable"} for p in panels]
    parsed = finalize_wearable_attachment(
        parts[0],
        attachment_count=len(parts),
        user_message=str(cmp_fix["inputs"]["user_message_standard"]),
        parts=parts,
    )
    table = build_wearable_compare_table_v1(
        parsed,
        user_message=str(cmp_fix["inputs"]["user_message_standard"]),
        baseline_override=cmp_fix["inputs"]["baseline_90d"],
        reference_date=date.fromisoformat(str(cmp_fix["reference_date"])),
        window_90d_override=cmp_fix["window_90d"],
    )
    expected_rows = (cmp_fix.get("expected_standard") or {}).get("rows") or []
    by_id = {r.metric_id: r for r in table.rows}
    for exp in expected_rows:
        mid = str(exp["metric_id"])
        got = by_id.get(mid)
        if not got:
            print("FAIL missing row", mid, list(by_id))
            return False
        for key in ("row_kind", "snapshot_value", "baseline_90d_value", "verdict"):
            want = exp.get(key)
            val = getattr(got, key, None)
            if val != want:
                print(f"FAIL {mid}.{key}: want={want!r} got={val!r}")
                return False
        if exp.get("baseline_90d_range") and got.baseline_90d_range != exp["baseline_90d_range"]:
            print(f"FAIL {mid}.range: want={exp['baseline_90d_range']!r} got={got.baseline_90d_range!r}")
            return False
    forbidden = (cmp_fix.get("expected_spo2_absent") or {}).get("forbidden_rows") or []
    omit = (cmp_fix.get("expected_spo2_absent") or {}).get("omit_panel_indices") or []
    if omit:
        keep = [p for i, p in enumerate(panels) if i not in set(omit)]
        parts2 = [{"ocr_text": p["ocr_text"], "document_family": "wearable"} for p in keep]
        parsed2 = finalize_wearable_attachment(
            parts2[0],
            attachment_count=len(parts2),
            user_message="对比过去90天",
            parts=parts2,
        )
        table2 = build_wearable_compare_table_v1(
            parsed2,
            user_message="对比过去90天",
            baseline_override=cmp_fix["inputs"]["baseline_90d"],
            reference_date=date.fromisoformat(str(cmp_fix["reference_date"])),
        )
        ids2 = {r.metric_id for r in table2.rows}
        for mid in forbidden:
            if mid in ids2:
                print("FAIL spo2 absent should omit", mid)
                return False
    return True


def test_workout_intent_rows() -> bool:
    ocr = load_golden_ocr()
    cmp_fix = load_golden_compare_table()
    panels = ocr.get("panels") or []
    parts = [{"ocr_text": p["ocr_text"], "document_family": "wearable"} for p in panels]
    msg = str((cmp_fix.get("expected_workout_intent") or {}).get("user_message") or "")
    parsed = finalize_wearable_attachment(
        parts[0],
        attachment_count=len(parts),
        user_message=msg,
        parts=parts,
    )
    if not user_requests_workout_compare(msg):
        print("FAIL workout intent detect")
        return False
    table = build_wearable_compare_table_v1(
        parsed,
        user_message=msg,
        baseline_override=cmp_fix["inputs"]["baseline_90d"],
        reference_date=date.fromisoformat(str(cmp_fix["reference_date"])),
    )
    ids = {r.metric_id for r in table.rows}
    for row in (cmp_fix.get("expected_workout_intent") or {}).get("additional_rows") or []:
        if row["metric_id"] not in ids:
            print("FAIL workout row missing", row["metric_id"], ids)
            return False
    return True


def test_markdown_header() -> bool:
    ocr = load_golden_ocr()
    cmp_fix = load_golden_compare_table()
    panels = ocr.get("panels") or []
    parts = [{"ocr_text": p["ocr_text"], "document_family": "wearable"} for p in panels]
    parsed = finalize_wearable_attachment(
        parts[0],
        attachment_count=len(parts),
        user_message="对比",
        parts=parts,
    )
    md = build_wearable_compare_table_v1(
        parsed,
        user_message="对比",
        baseline_override=cmp_fix["inputs"]["baseline_90d"],
    ).to_markdown()
    if "Wearable Compare Table" not in md or "NO_BASELINE" not in md:
        print("FAIL markdown", md[:200])
        return False
    parsed["wearable_compare_table_v1"] = json.loads(
        build_wearable_compare_table_v1(parsed, baseline_override=cmp_fix["inputs"]["baseline_90d"]).model_dump_json(),
    )
    if "wearable_compare_table_v1" not in parsed:
        print("FAIL persist key")
        return False
    return True


def test_compare_audit_fallback() -> bool:
    """G-Compare-5: fabrication → user-facing fallback, Tier0 only in audit telemetry."""
    from datetime import date

    from pha.wearable_compare_table_v1 import (
        apply_compare_table_fallback_if_needed,
        build_wearable_compare_table_v1,
    )

    ocr = load_golden_ocr()
    cmp_fix = load_golden_compare_table()
    panels = ocr.get("panels") or []
    parts = [{"ocr_text": p["ocr_text"], "document_family": "wearable"} for p in panels]
    parsed = finalize_wearable_attachment(
        parts[0],
        attachment_count=len(parts),
        user_message=str(cmp_fix["inputs"]["user_message_standard"]),
        parts=parts,
    )
    table = build_wearable_compare_table_v1(
        parsed,
        user_message=str(cmp_fix["inputs"]["user_message_standard"]),
        baseline_override=cmp_fix["inputs"]["baseline_90d"],
        reference_date=date.fromisoformat(str(cmp_fix["reference_date"])),
    )
    bad = (
        "深睡时长 sleep_deep 1hr9min 比 User Data Snapshot 近90天平均值 1hr52min 稍低。\n"
        "REM 2hr17min 比 REM 睡眠均值45.2 min 有所减少。"
    )
    fixed, audit = apply_compare_table_fallback_if_needed(bad, table)
    if audit.get("passed"):
        print("FAIL audit should fail on fabrication", audit)
        return False
    if not audit.get("fallback_applied"):
        print("FAIL fallback not applied", audit)
        return False
    if "1hr52" in fixed or "45.2" in fixed:
        print("FAIL fabrication left in fallback", fixed[:200])
        return False
    if "Tier0" in fixed or "metric_id" in fixed:
        print("FAIL fallback leaked Tier0 format", fixed[:200])
        return False
    if "睡眠总时长" not in fixed:
        print("FAIL fallback missing user summary", fixed[:200])
        return False
    if not audit.get("tier0_markdown"):
        print("FAIL tier0 should be in audit telemetry only")
        return False
    return True


def test_legitimate_sleep_analysis_passes() -> bool:
    from datetime import date

    from pha.wearable_compare_table_v1 import audit_wearable_compare_table, build_wearable_compare_table_v1

    ocr = load_golden_ocr()
    cmp_fix = load_golden_compare_table()
    panels = ocr.get("panels") or []
    parts = [{"ocr_text": p["ocr_text"], "document_family": "wearable"} for p in panels]
    parsed = finalize_wearable_attachment(
        parts[0], attachment_count=len(parts), user_message="对比睡眠", parts=parts,
    )
    table = build_wearable_compare_table_v1(
        parsed,
        user_message="对比睡眠",
        baseline_override=cmp_fix["inputs"]["baseline_90d"],
        reference_date=date.fromisoformat(str(cmp_fix["reference_date"])),
    )
    good = (
        "截图显示睡眠总时长 8hr43min，与近 90 天数仓相比落在正常区间内；"
        "HRV 30 ms、静息心率 58 bpm 亦在区间内。"
        "深睡 1hr9min 与 REM 2hr17min 仅来自截图，数仓无分期历史，无法与 90 天对比。"
    )
    audit = audit_wearable_compare_table(good, table)
    if not audit.get("passed"):
        print("FAIL legitimate analysis should pass", audit.get("violations"))
        return False
    return True


def test_sleep_only_incomplete_triggers_fallback() -> bool:
    from datetime import date

    from pha.wearable_compare_table_v1 import (
        apply_compare_table_fallback_if_needed,
        build_wearable_compare_table_v1,
    )

    ocr = load_golden_ocr()
    cmp_fix = load_golden_compare_table()
    panels = ocr.get("panels") or []
    parts = [{"ocr_text": p["ocr_text"], "document_family": "wearable"} for p in panels]
    parsed = finalize_wearable_attachment(
        parts[0], attachment_count=len(parts),
        user_message="这些指标是否正常", parts=parts,
    )
    table = build_wearable_compare_table_v1(
        parsed,
        user_message="请分析这些指标是否正常，尤其睡眠",
        baseline_override=cmp_fix["inputs"]["baseline_90d"],
        reference_date=date.fromisoformat(str(cmp_fix["reference_date"])),
    )
    sleep_only = (
        "### 纵向趋势对账\n"
        "从 Patient State 看，sleep_time_asleep 为 8hr43min（截图定账），与近 90 天 8 小时接近。\n"
        "sleep_deep 1hr9min、sleep_rem 2hr17min 无数仓基线。"
    )
    fixed, audit = apply_compare_table_fallback_if_needed(
        sleep_only, table, user_message="这些指标是否正常，尤其睡眠",
    )
    if audit.get("passed"):
        print("FAIL sleep-only should fail incomplete coverage", audit)
        return False
    if "HRV" not in fixed or "静息心率" not in fixed:
        print("FAIL fallback should include all metrics", fixed[:300])
        return False
    if "metric_id" in fixed or "Patient State" in fixed:
        print("FAIL fallback still has jargon", fixed[:200])
        return False
    return True


def test_wearable_polish() -> bool:
    from pha.wearable_presentation import polish_wearable_user_visible_reply

    raw = (
        "### 纵向趋势对账\n"
        "Patient State 中 sleep_time_asleep 8hr43min（截图定账），数仓均值 8.0。"
    )
    out = polish_wearable_user_visible_reply(raw)
    if "sleep_time_asleep" in out or "Patient State" in out or "数仓" in out:
        print("FAIL polish left jargon", out)
        return False
    if "睡眠总时长" not in out:
        print("FAIL polish missing label", out)
        return False
    return True


def test_summary_only_reply_fails_audit() -> bool:
    from datetime import date

    from pha.wearable_compare_table_v1 import audit_wearable_compare_table, build_wearable_compare_table_v1

    ocr = load_golden_ocr()
    cmp_fix = load_golden_compare_table()
    panels = ocr.get("panels") or []
    parts = [{"ocr_text": p["ocr_text"], "document_family": "wearable"} for p in panels]
    parsed = finalize_wearable_attachment(
        parts[0], attachment_count=len(parts), user_message="对比", parts=parts,
    )
    table = build_wearable_compare_table_v1(
        parsed,
        baseline_override=cmp_fix["inputs"]["baseline_90d"],
        reference_date=date.fromisoformat(str(cmp_fix["reference_date"])),
    )
    warehouse_only = (
        "从 User Data Snapshot 看，近 80 天睡眠均值 8.0 小时（范围 [0.4-9.9]），"
        "HRV 最低 5 日为 23–27 ms。建议放松训练。"
    )
    audit = audit_wearable_compare_table(warehouse_only, table, user_message="指标是否正常")
    if audit.get("passed"):
        print("FAIL warehouse-only should not pass compare audit")
        return False
    return True


def test_fallback_summary_passes_audit() -> bool:
    from datetime import date

    from pha.wearable_compare_table_v1 import (
        audit_wearable_compare_table,
        build_wearable_compare_table_v1,
        compare_table_to_user_summary,
    )
    from pha.wearable_presentation import polish_wearable_user_visible_reply

    ocr = load_golden_ocr()
    cmp_fix = load_golden_compare_table()
    panels = ocr.get("panels") or []
    parts = [{"ocr_text": p["ocr_text"], "document_family": "wearable"} for p in panels]
    parsed = finalize_wearable_attachment(
        parts[0], attachment_count=len(parts),
        user_message="这些指标是否正常", parts=parts,
    )
    user_msg = (
        "附件是5月30号的apple watch上的一些指标，其中一张是5月29号的work out数据，"
        "请分析与过去90的指标相比，这些指标是否正常，尤其是分析睡眠数据"
    )
    table = build_wearable_compare_table_v1(
        parsed,
        user_message=user_msg,
        baseline_override=cmp_fix["inputs"]["baseline_90d"],
        reference_date=date.fromisoformat(str(cmp_fix["reference_date"])),
    )
    summary = polish_wearable_user_visible_reply(compare_table_to_user_summary(table))
    audit = audit_wearable_compare_table(summary, table, user_message=user_msg)
    if not audit.get("passed"):
        print("FAIL polished fallback should pass compare audit", audit.get("violations"))
        return False
    if "无法与过去 90 天对比" in summary and "深睡" in summary and "1.8" in summary:
        print("FAIL fallback stale footer when deep/rem comparable")
        return False
    if "仅来自本次截图" in summary and "59-183" in summary:
        print("FAIL fallback duplicate workout snapshot when comparable")
        return False
    return True


    return True


def test_llm_compare_table_format() -> bool:
    from datetime import date

    from pha.wearable_compare_table_v1 import (
        build_wearable_compare_table_v1,
        compare_table_to_llm_markdown,
    )

    ocr = load_golden_ocr()
    cmp_fix = load_golden_compare_table()
    panels = ocr.get("panels") or []
    parts = [{"ocr_text": p["ocr_text"], "document_family": "wearable"} for p in panels]
    parsed = finalize_wearable_attachment(
        parts[0], attachment_count=len(parts), user_message="对比", parts=parts,
    )
    table = build_wearable_compare_table_v1(
        parsed,
        baseline_override=cmp_fix["inputs"]["baseline_90d"],
        reference_date=date.fromisoformat(str(cmp_fix["reference_date"])),
    )
    md = compare_table_to_llm_markdown(table)
    if "metric_id" in md or "sleep_time_asleep" in md:
        print("FAIL llm compare table still has engineering ids", md[:200])
        return False
    if "睡眠总时长" not in md or "本次截图" not in md:
        print("FAIL llm compare table missing zh headers", md[:200])
        return False
    return True


def test_ideal_compliant_llm_passes_audit() -> bool:
    from datetime import date

    from pha.wearable_compare_table_v1 import audit_wearable_compare_table, build_wearable_compare_table_v1

    ocr = load_golden_ocr()
    cmp_fix = load_golden_compare_table()
    panels = ocr.get("panels") or []
    parts = [{"ocr_text": p["ocr_text"], "document_family": "wearable"} for p in panels]
    parsed = finalize_wearable_attachment(
        parts[0], attachment_count=len(parts), user_message="对比", parts=parts,
    )
    user_msg = (
        "附件是5月30号的apple watch上的一些指标，其中一张是5月29号的work out数据，"
        "请分析与过去90的指标相比，这些指标是否正常，尤其是分析睡眠数据"
    )
    table = build_wearable_compare_table_v1(
        parsed,
        user_message=user_msg,
        baseline_override=cmp_fix["inputs"]["baseline_90d"],
        reference_date=date.fromisoformat(str(cmp_fix["reference_date"])),
    )
    ideal = (
        "简要结论：睡眠、HRV、静息心率、血氧、呼吸率与过去约90天相比均在常见范围内。\n\n"
        "- 睡眠总时长：本次 8hr43min；过去约90天平均 8.0 hr（区间 6.4–9.9），落在近 90 天正常区间内。\n"
        "- HRV：本次 30 ms；过去约90天平均 32.8 ms（区间 23.1–45.0），落在近 90 天正常区间内。\n"
        "- 静息心率：本次 58 bpm；过去约90天平均 57.4 bpm（区间 51.0–64.0），落在近 90 天正常区间内。\n"
        "- 血氧：本次 96%；过去约90天平均 96.2%（区间 94.0–98.0），落在近 90 天正常区间内。\n"
        "- 呼吸率：本次 11.0-17.5 breaths/min；过去约90天平均 13.2（区间 11.0–17.5），落在近 90 天正常区间内。\n\n"
        "深睡 1hr9min、REM 2hr17min：仅来自截图，系统没有90天历史，无法与过去90天对比。\n\n"
        "锻炼心率 76-147 bpm、近期锻炼 8 次：仅来自本次截图。"
    )
    audit = audit_wearable_compare_table(ideal, table, user_message=user_msg)
    if not audit.get("passed"):
        print("FAIL ideal compliant LLM should pass audit", audit.get("violations"))
        return False
    return True


def test_no_baseline_subjective_audit() -> bool:
    from datetime import date

    from pha.wearable_compare_table_v1 import audit_wearable_compare_table, build_wearable_compare_table_v1

    ocr = load_golden_ocr()
    cmp_fix = load_golden_compare_table()
    panels = ocr.get("panels") or []
    parts = [{"ocr_text": p["ocr_text"], "document_family": "wearable"} for p in panels]
    parsed = finalize_wearable_attachment(
        parts[0], attachment_count=len(parts), user_message="对比", parts=parts,
    )
    user_msg = (
        "附件是5月30号的apple watch上的一些指标，其中一张是5月29号的work out数据，"
        "请分析与过去90的指标相比，这些指标是否正常，尤其是分析睡眠数据"
    )
    table = build_wearable_compare_table_v1(
        parsed,
        user_message=user_msg,
        baseline_override=cmp_fix["inputs"]["baseline_90d"],
        reference_date=date.fromisoformat(str(cmp_fix["reference_date"])),
    )
    deepseek_style = (
        "深睡时间为1小时9分钟，REM 睡眠时间为2小时17分钟。"
        "由于系统中没有这两项的90天历史数据，无法进行对比分析。"
        "但当天的数据显示您的深度睡眠和 REM 睡眠时间都较为充足。"
    )
    audit = audit_wearable_compare_table(deepseek_style, table, user_message=user_msg)
    if audit.get("passed"):
        print("FAIL deepseek-style subjective should fail audit", audit.get("violations"))
        return False
    if not any("compare_no_baseline_subjective" in v for v in audit.get("violations", [])):
        print("FAIL expected compare_no_baseline_subjective", audit.get("violations"))
        return False

    factual = (
        "深睡 1hr9min、REM 2hr17min：仅来自截图，系统没有90天历史，无法与过去90天对比。"
    )
    audit2 = audit_wearable_compare_table(factual, table, user_message="")
    if not audit2.get("passed"):
        print("FAIL factual no-baseline wording should pass", audit2.get("violations"))
        return False
    return True


def test_respiratory_rate_compare_row() -> bool:
    from datetime import date

    from pha.wearable_compare_table_v1 import build_wearable_compare_table_v1

    ocr = load_golden_ocr()
    cmp_fix = load_golden_compare_table()
    panels = ocr.get("panels") or []
    parts = [{"ocr_text": p["ocr_text"], "document_family": "wearable"} for p in panels]
    parsed = finalize_wearable_attachment(
        parts[0], attachment_count=len(parts), user_message="对比", parts=parts,
    )
    table = build_wearable_compare_table_v1(
        parsed,
        baseline_override=cmp_fix["inputs"]["baseline_90d"],
        reference_date=date.fromisoformat(str(cmp_fix["reference_date"])),
    )
    row = next((r for r in table.rows if r.metric_id == "respiratory_rate"), None)
    if not row or row.row_kind != "comparable_90d":
        print("FAIL respiratory_rate comparable row missing", row)
        return False
    if row.snapshot_value != "11.0-17.5":
        print("FAIL respiratory snapshot", row.snapshot_value)
        return False
    return True


def test_macro_summary_omits_means() -> bool:
    from pha.harness_plan import build_wearable_90d_macro_summary_block

    block = build_wearable_90d_macro_summary_block("default", "对比过去90天是否正常")
    if re.search(r"均值\d+\.\d+\[", block):
        print("FAIL macro summary still has mean[range]", block[:300])
        return False
    if "User Data Snapshot" in block:
        print("FAIL macro summary still has User Data Snapshot header", block[:300])
        return False
    if "Pearson" not in block and "无本地" not in block and "宏观趋势" not in block:
        print("FAIL macro summary missing macro content", block[:300])
        return False
    return True


def test_false_no_baseline_claim_when_comparable() -> bool:
    """δ-ux: 表内深睡/REM 有 90d 基线时，禁止声称「缺乏90天历史」。"""
    from datetime import date

    from pha.wearable_compare_table_v1 import (
        audit_wearable_compare_table,
        build_wearable_compare_table_v1,
    )

    ocr = load_golden_ocr()
    panels = ocr.get("panels") or []
    parts = [{"ocr_text": p["ocr_text"], "document_family": "wearable"} for p in panels]
    parsed = finalize_wearable_attachment(parts[0], attachment_count=len(parts), parts=parts)
    table = build_wearable_compare_table_v1(
        parsed,
        reference_date=date.fromisoformat("2026-05-30"),
    )
    deep = next((r for r in table.rows if r.metric_id == "sleep_deep"), None)
    if not deep or deep.row_kind != "comparable_90d":
        print("SKIP false_no_baseline (no deep comparable in warehouse)")
        return True
    bad = "深睡 1hr9min。系统没有提供过去90天的历史数据来对比。REM 同样也缺乏90天历史。"
    audit = audit_wearable_compare_table(bad, table)
    if audit.get("passed"):
        print("FAIL should flag false no baseline", audit)
        return False
    if not any("false_no_baseline" in v for v in audit.get("violations") or []):
        print("FAIL missing violation", audit)
        return False
    return True


def test_hybrid_fallback_preserves_llm_advisory() -> bool:
    """Audit fail: SSO compare table + LLM 建议/综上所述（非整段替换）。"""
    from datetime import date

    from pha.wearable_compare_table_v1 import (
        apply_compare_table_fallback_if_needed,
        build_wearable_compare_table_v1,
    )

    ocr = load_golden_ocr()
    cmp_fix = load_golden_compare_table()
    panels = ocr.get("panels") or []
    parts = [{"ocr_text": p["ocr_text"], "document_family": "wearable"} for p in panels]
    msg = "对比过去90天是否正常，尤其睡眠"
    parsed = finalize_wearable_attachment(parts[0], attachment_count=len(parts), user_message=msg, parts=parts)
    table = build_wearable_compare_table_v1(
        parsed,
        user_message=msg,
        baseline_override=cmp_fix["inputs"]["baseline_90d"],
        reference_date=date.fromisoformat(str(cmp_fix["reference_date"])),
    )
    llm = (
        "根据您上传的最近90天的数据对比，睡眠 8hr43min 落在近90天正常区间内。\n\n"
        "综上所述，除锻炼略少外其余指标稳定。建议保持规律作息，可适当增加有氧锻炼；"
        "若深睡连续偏低可记录就寝时间并咨询医生。"
    )
    fixed, audit = apply_compare_table_fallback_if_needed(llm, table, user_message=msg)
    if not audit.get("fallback_applied") or audit.get("fallback_mode") != "hybrid":
        print("FAIL expected hybrid fallback", audit)
        return False
    if "综上所述" not in fixed or "建议" not in fixed:
        print("FAIL advisory stripped", fixed[:400])
        return False
    if "睡眠总时长" not in fixed or "8 小时 43 分钟" not in fixed:
        print("FAIL SSO summary missing", fixed[:400])
        return False
    return True


def test_snapshot_reference_date_anchor() -> bool:
    """User/OCR May 30 anchors CompareTable (not server today)."""
    ocr = load_golden_ocr()
    panels = ocr.get("panels") or []
    parts = [{"ocr_text": p["ocr_text"], "document_family": "wearable"} for p in panels]
    msg = "附件是5月30号的apple watch上的一些指标，请分析与过去90的指标相比"
    parsed = finalize_wearable_attachment(
        parts[0],
        attachment_count=len(parts),
        user_message=msg,
        parts=parts,
    )
    if parsed.get("snapshot_reference_date") != "2026-05-30":
        print("FAIL snapshot_reference_date", parsed.get("snapshot_reference_date"))
        return False
    table = build_wearable_compare_table_v1(parsed, user_message=msg)
    if table.reference_date != "2026-05-30":
        print("FAIL table.reference_date", table.reference_date)
        return False
    w = next((r for r in table.rows if r.metric_id == "workout_count_recent"), None)
    if not w or w.snapshot_value != "8":
        print("FAIL workout snapshot at May 30 anchor", w)
        return False
    if w.row_kind == "snapshot_only":
        if w.baseline_90d_value not in ("NO_BASELINE", None, ""):
            print("FAIL workout baseline expected NO_BASELINE in snapshot_only", w)
            return False
    elif w.row_kind == "comparable_90d":
        if not w.baseline_90d_value or w.baseline_90d_value == "NO_BASELINE":
            print("FAIL workout baseline missing for comparable_90d", w)
            return False
        print("OK workout comparable baseline", w.baseline_90d_value, w.baseline_90d_range)
    else:
        print("FAIL workout row_kind", w.row_kind, w)
        return False
    return True


def test_comparable_stage_narrative_not_fabrication() -> bool:
    """δ-a: LLM may cite personal 90d mean for deep/REM when comparable."""
    from pha.wearable_compare_table_v1 import audit_wearable_compare_table

    ocr = load_golden_ocr()
    panels = ocr.get("panels") or []
    parts = [{"ocr_text": p["ocr_text"], "document_family": "wearable"} for p in panels]
    msg = "对比过去90天是否正常，尤其睡眠"
    parsed = finalize_wearable_attachment(parts[0], attachment_count=len(parts), user_message=msg, parts=parts)
    table = build_wearable_compare_table_v1(
        parsed,
        user_message=msg,
        reference_date=date.fromisoformat("2026-05-30"),
    )
    deep = next((r for r in table.rows if r.metric_id == "sleep_deep"), None)
    if not deep or deep.row_kind != "comparable_90d":
        print("SKIP comparable_stage (no warehouse deep baseline)")
        return True
    text = (
        "深睡 1hr9min 略低于个人近 90 天平均 1.8 hr，仍在常见区间内。"
        " REM 2hr17min 低于平均 3.8 hr，仍在区间内。"
    )
    audit = audit_wearable_compare_table(text, table, user_message=msg)
    bad = [v for v in audit.get("violations") or [] if "forbidden_90d_stage" in v]
    if bad:
        print("FAIL comparable stage narrative flagged", bad)
        return False
    return True


def test_respiratory_range_endpoint_authorized() -> bool:
    from pha.wearable_compare_table_v1 import audit_wearable_compare_table

    ocr = load_golden_ocr()
    panels = ocr.get("panels") or []
    parts = [{"ocr_text": p["ocr_text"], "document_family": "wearable"} for p in panels]
    parsed = finalize_wearable_attachment(parts[0], attachment_count=len(parts), parts=parts)
    table = build_wearable_compare_table_v1(
        parsed,
        reference_date=date.fromisoformat("2026-05-30"),
    )
    answer = (
        "呼吸率：本次 11-17.5 breaths/min；过去约 90 天平均 13.2 breaths/min"
        "（常见区间 12.3–15.0），落在近 90 天正常区间内。"
    )
    audit = audit_wearable_compare_table(answer, table)
    drift = [v for v in audit.get("violations") or [] if "numeric_drift:17.5" in v]
    if drift:
        print("FAIL 17.5 should be authorized", audit)
        return False
    return True


def test_single_metric_focus() -> bool:
    from pha.wearable_compare_table_v1 import (
        CompareRowV1,
        CompareTableV1,
        build_single_metric_focus_answer,
        infer_single_metric_focus_ids,
    )

    if infer_single_metric_focus_ids("HRV 怎么样") != ["hrv_rmssd_ms"]:
        print("FAIL focus ids hrv", infer_single_metric_focus_ids("HRV 怎么样"))
        return False
    if infer_single_metric_focus_ids("指标是否都正常"):
        print("FAIL broad compare should not focus")
        return False
    if infer_single_metric_focus_ids("分析所有指标"):
        print("FAIL 所有指标 should stay broad compare")
        return False
    # P2 Stage 3G-followup: narrow-hint precedence must beat the broad bundle `core` fallback.
    p2_focus = {
        "心率范围呢": ["workout_heart_rate_range_bpm"],
        "请分析心率指标": ["resting_heart_rate_bpm"],
        "心率正常吗": ["resting_heart_rate_bpm"],
    }
    for msg, expected in p2_focus.items():
        got = infer_single_metric_focus_ids(msg)
        if got != expected:
            print(f"FAIL p2 single focus {msg!r}: {got} != {expected}")
            return False
    # 深睡时长 / 锻炼成对 → allowed metric pairs (not blocked by 2-non-sleep rule).
    if set(infer_single_metric_focus_ids("深睡时长是多少")) != {"sleep_deep", "sleep_rem"}:
        print("FAIL 深睡时长 pair", infer_single_metric_focus_ids("深睡时长是多少"))
        return False
    if set(infer_single_metric_focus_ids("请报告锻炼心率范围")) != {
        "workout_heart_rate_range_bpm",
        "workout_count_recent",
    }:
        print("FAIL 锻炼心率范围 workout pair", infer_single_metric_focus_ids("请报告锻炼心率范围"))
        return False
    table = CompareTableV1(
        rows=[
            CompareRowV1(
                metric_id="hrv_rmssd_ms",
                row_kind="comparable_90d",
                snapshot_value="34",
                baseline_90d_value="33.0",
                baseline_90d_unit="ms",
                baseline_90d_range="23.1-45.8",
                verdict="within_range",
            ),
            CompareRowV1(
                metric_id="sleep_time_asleep",
                row_kind="comparable_90d",
                snapshot_value="6hr32min",
                baseline_90d_value="8.1",
                baseline_90d_unit="hr",
                baseline_90d_range="0.4-10.0",
                verdict="within_range",
            ),
        ],
    )
    ans = build_single_metric_focus_answer(table, "HRV 怎么样")
    if "34" not in ans or "睡眠" in ans:
        print("FAIL focus answer", ans)
        return False
    return True


def main() -> int:
    ok = all(
        [
            test_verdict_range_alignment(),
            test_parse_snapshot_numeric(),
            test_golden_compare_standard(),
            test_workout_intent_rows(),
            test_markdown_header(),
            test_compare_audit_fallback(),
            test_legitimate_sleep_analysis_passes(),
            test_summary_only_reply_fails_audit(),
            test_sleep_only_incomplete_triggers_fallback(),
            test_wearable_polish(),
            test_fallback_summary_passes_audit(),
            test_llm_compare_table_format(),
            test_ideal_compliant_llm_passes_audit(),
            test_macro_summary_omits_means(),
            test_no_baseline_subjective_audit(),
            test_respiratory_rate_compare_row(),
            test_snapshot_reference_date_anchor(),
            test_false_no_baseline_claim_when_comparable(),
            test_hybrid_fallback_preserves_llm_advisory(),
            test_comparable_stage_narrative_not_fabrication(),
            test_respiratory_range_endpoint_authorized(),
            test_single_metric_focus(),
        ],
    )
    print("pha_wearable_compare_table_selfcheck:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
