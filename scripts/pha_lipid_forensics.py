#!/usr/bin/env python3
"""Audit SQLite lipid rows vs Harness LDL_AUTHORITY — v2.2.6.1 forensics."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pha.chat_router import build_ldl_authority_system_block
from pha.intent_gates import resolve_ldl_authority_years
from pha.patient_state import build_patient_state_evidence_slice
from pha.intent_gates import QuestionType
from pha.temporal_router import parse_temporal_intent

DB = ROOT / "data" / "pha_storage.db"
UID = "default"
COMBINED_MSG = (
    "根据我所有的检验报告中的血脂情况 ，请分析HRV与运动消耗对血脂有没有影响，"
    "然后给我更新的补剂方案建议"
)


def main() -> int:
    print("=== PHA Lipid Forensics ===\n")
    print("DB:", DB)
    if not DB.exists():
        print("ERROR: database missing")
        return 1

    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        """
        SELECT report_date, metric_name, metric_code, name_zh, value, unit
        FROM medical_reports
        WHERE user_id = ?
          AND (
            lower(coalesce(metric_name,'')) LIKE '%胆固醇%'
            OR lower(coalesce(metric_name,'')) LIKE '%ldl%'
            OR lower(coalesce(metric_name,'')) LIKE '%hdl%'
            OR lower(coalesce(metric_name,'')) LIKE '%甘油三酯%'
            OR lower(coalesce(metric_code,'')) IN ('ldl','hdl','tc','tg')
          )
        ORDER BY report_date ASC
        """,
        (UID,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    print(f"\n[SQLite] lipid rows: {len(rows)}")
    for r in rows:
        d = str(r["report_date"])[:10]
        name = r["metric_name"] or r["name_zh"] or r["metric_code"]
        print(f"  {d} | {name} | {r['value']} {r.get('unit') or ''}")

    intent = parse_temporal_intent(COMBINED_MSG)
    years = resolve_ldl_authority_years(UID, COMBINED_MSG, intent)
    ldl = build_ldl_authority_system_block(UID, years) if years else ""
    ps = build_patient_state_evidence_slice(
        UID, COMBINED_MSG, question_type=QuestionType.COMBINED, has_wearable_user_snapshot=False,
    )

    print("\n[LDL_AUTHORITY block]\n")
    print(ldl or "(empty)")

    blob = (ldl or "") + (ps or "")
    print("\n[Claim vs Harness blob]")
    for token, label in [
        ("2026-04-30", "date"),
        ("2025-01-13", "date"),
        ("5.1", "TC? (also 空腹血糖 in PS)"),
        ("3.2", "LDL? (also 淋巴细胞 33.2 substring)"),
        ("3.3", "LDL? (also 嗜酸性粒细胞 in PS)"),
    ]:
        print(f"  {token} ({label}): in blob={token in blob}")

    print("\n[Ground truth lipid dates in DB]")
    dates = sorted({str(r["report_date"])[:10] for r in rows})
    print(" ", dates)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
