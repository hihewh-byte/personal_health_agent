#!/usr/bin/env python3
"""Generator for rules/e2e_question_bank_zh_50_v1.json — 50 Chinese sets × ≥8 turns.

Mirrors the EN 50× lane matrix; sets ZS01–ZS20 reuse the rich ZH v1 checks/turns;
ZS21–ZS50 follow EN stress lanes with chinese_reply checks.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from seed_e2e_question_bank_en_v1 import SETS_SPEC as EN_SETS_SPEC, pool  # noqa: E402
from seed_e2e_question_bank_v1 import POOLS as ZH_POOLS, SETS as ZH_SETS_20, chk, turn  # noqa: E402

OUT = ROOT / "rules" / "e2e_question_bank_zh_50_v1.json"

EXTRA_POOLS = {
    "upload_lab_image": pool(
        [
            "附件是之前存的化验单截图，帮我看血脂 LDL",
            "传张报告图，把胆固醇指标抠出来",
        ],
        [
            "附件为化验/报告截图，请解析血脂等指标。",
            "请分析附件报告图中的血脂与关键数值。",
        ],
    ),
    "supplement": pool(
        ["我库里有没有补剂相关记录？", "血脂和 HRV 差要不要补剂？"],
        ["请结合库内记录，说明是否有补剂相关事实可供引用。"],
    ),
    "body_age": pool(
        ["身体年龄/恢复年龄有信号吗？", "穿戴数据能看出恢复年龄吗？"],
        ["如有相关信号，请概括恢复年龄/身体年龄类穿戴指标。"],
    ),
    "disclaimer": pool(
        ["这不是医疗建议对吧？", "请保持科普口径别当诊断"],
        ["请保持科普、非诊断口径。", "确认本回复不构成医疗诊断。"],
    ),
    "chinese_only": pool(
        ["请全程用中文回复", "后面都用中文", "只用中文答"],
        ["请全程使用中文回复。", "后续回答请使用中文。"],
    ),
    "wearable_import": pool(
        ["我前面导入过穿戴数据，用数仓", "用已入库的穿戴样本"],
        ["请使用已导入的穿戴数仓数据。", "查询历史穿戴入库记录。"],
    ),
    "pdf_lab": pool(
        ["如果之前上传过化验 PDF，用那些血脂", "从以前 PDF 报告里取血脂"],
        ["请使用已入库 PDF/报告中的血脂数值（如有）。", "查询历史 PDF 化验入库记录。"],
    ),
}


def transform_checks(checks: list[dict]) -> list[dict]:
    out: list[dict] = []
    for raw in checks or []:
        row = copy.deepcopy(raw)
        cid = str(row.get("id") or "")
        if cid == "english_reply":
            row["id"] = "chinese_reply"
        out.append(row)
    if not out:
        out = [chk("jun11_metrics"), chk("chinese_reply"), chk("no_empty"), chk("no_repeat")]
    return out


def fix_turn_slots(turns: list[dict]) -> list[dict]:
    fixed: list[dict] = []
    for t in turns:
        row = copy.deepcopy(t)
        if row.get("slot") == "english_only":
            row["slot"] = "chinese_only"
        fixed.append(row)
    return fixed


def main() -> int:
    zh_by_legacy = {str(s.get("legacy_name") or ""): s for s in ZH_SETS_20}
    sets: list[dict] = []

    for i, en_spec in enumerate(EN_SETS_SPEC, start=1):
        legacy = str(en_spec.get("legacy_name") or "")
        if i <= 20 and legacy in zh_by_legacy:
            row = copy.deepcopy(zh_by_legacy[legacy])
        else:
            row = copy.deepcopy(en_spec)
            row["turns"] = fix_turn_slots(row.get("turns") or [])
            row["checks"] = transform_checks(row.get("checks") or [])
        row["set_id"] = f"ZS{i:02d}"
        n_turns = len(row.get("turns") or [])
        if n_turns < 8:
            raise SystemExit(f"{row['set_id']} has only {n_turns} turns")
        sets.append(row)

    pools = {**ZH_POOLS, **EXTRA_POOLS}
    bank = {
        "bank_version": "zh-50-1.0",
        "language": "zh",
        "colloquial_ratio_target": 0.7,
        "description": (
            "50 Chinese E2E stress sets; each ≥8 turns; wearable screenshots, "
            "warehouse lipids/wearables, prior lab images. Seed via PHA_E2E_BANK_SEED."
        ),
        "variant_pools": pools,
        "sets": sets,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(bank, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT} sets={len(sets)} pools={len(pools)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
