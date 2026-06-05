#!/usr/bin/env python3
"""Simulate 6-panel wearable turn: OCR golden → CompareTable → policy-compliant narrative."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from datetime import date

from tests.fixtures.wearable.golden_wearable import load_golden_ocr, _panel_parts
from pha.wearable_snapshot_v1 import finalize_wearable_attachment
from pha.wearable_compare_table_v1 import (
    apply_compare_table_fallback_if_needed,
    audit_wearable_compare_table,
    build_wearable_compare_table_v1,
    compare_table_to_user_summary,
)

USER_6PANEL = (
    "附件是5月30号的apple watch上的一些指标，其中一张是5月29号的work out数据，"
    "请分析与过去90的指标相比，这些指标是否正常，尤其是分析睡眠数据"
)
USER_LIPID = "根据这些指标分析，是否对我的血脂指标有改善的影响？"


def _sleep_narrative(table) -> str:
    """Type-A compliant add-on (numbers only from CompareTable)."""
    rows = {r.metric_id: r for r in table.rows}
    sleep = rows.get("sleep_time_asleep")
    deep = rows.get("sleep_deep")
    rem = rows.get("sleep_rem")
    workout = rows.get("workout_count_recent")
    lines = [
        "",
        "### 睡眠专项解读",
        "",
        f"您 5 月 30 日总睡眠 **{sleep.snapshot_value if sleep else '—'}**（约 8 小时 43 分钟），"
        f"落在个人近 90 天常见区间 {sleep.baseline_90d_range if sleep else '—'} 内，节律总体稳定。",
    ]
    if deep and deep.row_kind == "comparable_90d":
        lines.append(
            f"深睡 **{deep.snapshot_value}** 略低于个人 90 天平均 **{deep.baseline_90d_value} hr**（区间 {deep.baseline_90d_range}），"
            f"但仍落在个人常见区间内；不必单日焦虑，可连续 2–4 周观察就寝时间与咖啡因。"
        )
    if rem and rem.row_kind == "comparable_90d":
        lines.append(
            f"REM **{rem.snapshot_value}** 低于个人平均 **{rem.baseline_90d_value} hr**（区间 {rem.baseline_90d_range}），"
            f"同样落在区间内；若持续偏低，可记录就寝时间并咨询医生。"
        )
    if workout and workout.verdict == "below_mean":
        lines.append(
            f"近期锻炼 **{workout.snapshot_value}** 低于个人滚动基线（见上表），可适当增加有氧频率以支持代谢健康。"
        )
    lines.extend(
        [
            "",
            "### 建议（非处方）",
            "",
            "- 维持规律作息与适度有氧；继续用 Watch 追踪 HRV、静息心率与睡眠分期。",
            "- 血脂与穿戴的因果需结合化验复查；以下为账本血脂趋势，供您与医生讨论。",
        ],
    )
    return "\n".join(lines)


def main() -> int:
    golden = load_golden_ocr()
    parts = _panel_parts(golden["panels"])
    parsed = finalize_wearable_attachment(
        parts[0],
        attachment_count=len(parts),
        user_message=USER_6PANEL,
        parts=parts,
    )
    table = build_wearable_compare_table_v1(parsed, user_message=USER_6PANEL)
    base = compare_table_to_user_summary(table)
    llm = base + _sleep_narrative(table)
    audit = audit_wearable_compare_table(llm, table, user_message=USER_6PANEL)
    final, fa = apply_compare_table_fallback_if_needed(llm, table, user_message=USER_6PANEL)

    print("=== PHA 模拟真机 6 图 · 第一轮 ===")
    print(f"[用户] {USER_6PANEL}\n")
    mode = "LLM 全文" if not fa.get("fallback_applied") else (
        f"混合 Fallback（建议 {fa.get('advisory_chars', 0)} 字）"
    )
    print(f"[助手] ({mode} · {len(final)} 字)")
    print(final)
    print("\n--- audit ---")
    print(json.dumps({"passed": audit["passed"], "violations": audit.get("violations")}, ensure_ascii=False))
    print(f"\nsnapshot_reference_date={parsed.get('snapshot_reference_date')}")
    print(f"compare_rows={len(table.rows)} ref={table.reference_date}")

    print("\n=== 第二轮（血脂追问 · 模拟）===")
    print(f"[用户] {USER_LIPID}\n")
    print(
        "[助手] （需 LLM + Patient State；此处仅提示：真机 msg-339 已含 HDL/LDL/TC/TG "
        "2023-12-15 → 2025-12-07 对账与穿戴小结。）"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
