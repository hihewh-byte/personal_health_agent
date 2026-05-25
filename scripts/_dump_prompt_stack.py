# -*- coding: utf-8 -*-
"""One-off: dump Ollama message stack for supplement + follow-up (v2.2.5 as-is)."""
import json
import sys

from pha.agent_tools import FAST_PATH_SYSTEM_ADDENDUM, SNAPSHOT_MARKER
from pha.chat_background import build_user_background_block
from pha.chat_router import build_ldl_authority_system_block, prepare_chat_evidence_bundle
from pha.chat_service import (
    _build_supplemental_system_layers,
    _message_needs_lab_ledger,
    build_pha_chat_message_stack,
)
from pha.agent_tools import apply_health_heuristic_override
from pha.health_data import effective_query_reference_date
from pha.intent_gates import (
    QuestionType,
    classify_question_type,
    resolve_ldl_authority_years,
    should_inject_wearable_snapshot,
    user_message_needs_lab_dossier,
)
from pha.patient_state import build_patient_state_evidence_slice
from pha.temporal_router import parse_temporal_intent

SUPP = (
    "以下是我的补剂方案：时间 项目 具体内容 核心逻辑 上午 训练后（结束30分钟内） 训练后恢复 "
    "蛋白粉30g + 2根香蕉 + 5g肌酸 + B族（周2-3次） + 益生菌 快速补充糖原、肌肉蛋白合成、动力恢复 "
    "上午 10:30 抗炎组合 槲皮素 + 菠萝蛋白酶（2粒） 减轻训练炎症、增强血管弹性（可与训练后餐同服） "
    "中午 12:30（午餐时） 脂溶性营养 + 药物 鱼油 + 卵磷脂 + D3+K2 + 蓝莓 + 200mg Q10 + 非布司他 + 他汀 "
    "随油脂吸收最好，固定他汀时间 晚上 19:00（晚餐） 晚餐主餐 300-400g 烤红薯（或等量复合碳水） + 蛋白 + 蔬菜 "
    "+ Move Free（氨糖） + 姜黄素（可选） 稳定夜间血糖、降低凌晨皮质醇峰值、关节保护 "
    "睡前 30-60分钟（22:00前） 睡眠 & 心血管支持 镁 300-400mg（甘氨酸镁） 纳豆激酶（建议2000-4000 FU） "
    "1根香蕉（可选，轻碳水） 南非醉茄（Ashwagandha，可选） 压低皮质醇、放松神经、改善早醒 + 夜间心血管保护"
)

Q2 = (
    "根据我所有的检验报告中的血脂情况 ，请分析同时期HRV与运动消耗对血脂有没有影响，"
    "然后给我更新的补剂方案建议"
)


def build_stack(msg: str, history=None):
    uid = "default"
    history = history or []
    qtype = classify_question_type(msg)
    intent = parse_temporal_intent(msg)
    inject = should_inject_wearable_snapshot(msg, is_temporal_dynamic=False)
    ldl_years = (
        resolve_ldl_authority_years(uid, msg, intent)
        if qtype in (QuestionType.LAB, QuestionType.COMBINED)
        else []
    )
    ldl = build_ldl_authority_system_block(uid, ldl_years) if ldl_years else ""
    dossier = ""
    if user_message_needs_lab_dossier(msg) or qtype == QuestionType.COMBINED:
        dossier, *_ = prepare_chat_evidence_bundle(
            uid,
            msg,
            build_dossier=True,
            omit_ldl_fusion_blocks=qtype not in (QuestionType.LAB, QuestionType.COMBINED),
            compact_clinical_only=(qtype == QuestionType.COMBINED),
        )
    bg = build_user_background_block(uid, user_message=msg)
    supp, _ = _build_supplemental_system_layers(
        ldl_authority=ldl,
        audit_warn="",
        extra_system_context=bg,
        recalled_snippets="",
    )
    if dossier.strip():
        supp = f"{dossier.strip()}\n\n---\n\n{supp}".strip()
    if inject:
        aug, _, pre = apply_health_heuristic_override(msg, uid)
    else:
        aug, pre = msg, []
    patient = build_patient_state_evidence_slice(
        uid,
        msg,
        question_type=qtype,
        has_wearable_user_snapshot=bool(pre),
        reference_date=effective_query_reference_date(),
    )
    fast = SNAPSHOT_MARKER in aug and not _message_needs_lab_ledger(msg)
    if fast:
        supp = f"{supp}\n\n{FAST_PATH_SYSTEM_ADDENDUM}".strip()
    stack = build_pha_chat_message_stack(
        supplemental_system=supp,
        history_messages=history,
        patient_state=patient,
        current_user_message=aug,
    )
    return {
        "qtype": qtype.value,
        "inject_snapshot": inject,
        "fast_path": fast,
        "heuristic_tools": [p.get("tool") for p in pre],
        "augmented_has_snapshot": SNAPSHOT_MARKER in aug,
        "stack": stack,
    }


def main() -> None:
    for name, msg in [("round1_supplement", SUPP), ("round2_lipid", Q2)]:
        r = build_stack(msg)
        meta = {k: v for k, v in r.items() if k != "stack"}
        print("\n" + "=" * 70)
        print(name, json.dumps(meta, ensure_ascii=False))
        for i, m in enumerate(r["stack"]):
            c = m.get("content") or ""
            print(f"\n--- messages[{i}] role={m['role']} len={len(c)} ---")
            if m["role"] == "system":
                print(c[:1200])
                print("...(truncated for display)...")
                print(c[-500:])
            else:
                print(c[:3000])
                if len(c) > 3000:
                    print(f"... (+{len(c) - 3000} chars)")


if __name__ == "__main__":
    main()
