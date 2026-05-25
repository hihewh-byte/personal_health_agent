#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E2E: long supplement → combined question (model via argv or env)."""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

BASE = "http://127.0.0.1:8787"
MODEL = os.environ.get("PHA_E2E_MODEL", "qwen2.5:7b-instruct")
USER_ID = "default"

T1_SUPPLEMENT = """以下是我的补剂方案：时间 项目 具体内容 核心逻辑 上午 训练后（结束30分钟内） 训练后恢复 蛋白粉30g + 2根香蕉 + 5g肌酸 + B族（周2-3次） + 益生菌 快速补充糖原、肌肉蛋白合成、动力恢复 上午 10:30 抗炎组合 槲皮素 + 菠萝蛋白酶（2粒） 减轻训练炎症、增强血管弹性（可与训练后餐同服） 中午 12:30（午餐时） 脂溶性营养 + 药物 鱼油 + 卵磷脂 + D3+K2 + 蓝莓 + 200mg Q10 + 非布司他 + 他汀 随油脂吸收最好，固定他汀时间 晚上 19:00（晚餐） 晚餐主餐 300-400g 烤红薯（或等量复合碳水） + 蛋白 + 蔬菜 + Move Free（氨糖） + 姜黄素（可选） 稳定夜间血糖、降低凌晨皮质醇峰值、关节保护 睡前 30-60分钟（22:00前） 睡眠 & 心血管支持 镁 300-400mg（甘氨酸镁） 纳豆激酶（建议2000-4000 FU） 1根香蕉（可选，轻碳水） 南非醉茄（Ashwagandha，可选） 压低皮质醇、放松神经、改善早醒 + 夜间心血管保护"""

T2_COMBINED = (
    "根据我所有的检验报告中的血脂情况 ，请分析HRV与运动消耗对血脂有没有影响，"
    "然后给我更新的补剂方案建议"
)

GROUND_TRUTH = {
    "dates_ok": ["2023-12-15", "2025-12-07"],
    "dates_bad": ["2026-04-30", "2025-01-13"],
    "values_ok": ["5.62", "4.24", "4.05", "2.45", "1.02", "1.56", "0.59", "1.51"],
    "values_hallucination_pattern": ["5.1", "3.2", "3.3", "5.2"],
}


def _post_json(url: str, body: dict) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def _chat_stream(
    *,
    message: str,
    session_id: Optional[str],
) -> Tuple[str, str, List[str], float, int, Optional[str], Dict[str, Any], List[str]]:
    body = {"user_id": USER_ID, "message": message, "model": MODEL, "session_id": session_id}
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/api/chat",
        data=data,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
    )
    statuses: List[str] = []
    parts: List[str] = []
    sid = session_id
    numerics_audit: Dict[str, Any] = {}
    errors: List[str] = []
    t0 = time.perf_counter()
    token_chunks = 0
    with urllib.request.urlopen(req, timeout=600) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload:
                continue
            ev = json.loads(payload)
            et = ev.get("event")
            if et == "delta" and ev.get("delta"):
                parts.append(str(ev["delta"]))
                token_chunks += 1
            elif et == "status" and ev.get("message"):
                statuses.append(str(ev["message"]))
            elif et == "error":
                errors.append(str(ev.get("message") or "unknown error"))
            elif et == "done":
                sid = str(ev.get("session_id") or sid or "")
                numerics_audit = dict(ev.get("numerics_audit") or {})
                ans = (ev.get("answer") or {}).get("answer_text") or ""
                if ans and not parts:
                    parts.append(ans)
    elapsed = time.perf_counter() - t0
    text = "".join(parts)
    return text, sid or "", statuses, elapsed, token_chunks, sid, numerics_audit, errors


def _audit_answer(text: str) -> Dict[str, Any]:
    found_ok_dates = [d for d in GROUND_TRUTH["dates_ok"] if d in text]
    found_bad_dates = [d for d in GROUND_TRUTH["dates_bad"] if d in text]
    found_ok_vals = [v for v in GROUND_TRUTH["values_ok"] if v in text]
    found_halluc_vals = [v for v in GROUND_TRUTH["values_hallucination_pattern"] if v in text]
    asks_for_data = bool(
        re.search(r"请提供|是否有记录|能否提供|需要你提供|请上传", text, re.I),
    )
    hrv_nums = re.findall(r"HRV[^\d]{0,20}(\d+(?:\.\d+)?)", text, re.I)
    return {
        "found_ok_dates": found_ok_dates,
        "found_bad_dates": found_bad_dates,
        "found_ok_values": found_ok_vals,
        "found_suspicious_values": found_halluc_vals,
        "asks_user_for_data": asks_for_data,
        "hrv_number_mentions": hrv_nums[:5],
        "chars": len(text),
    }


def main() -> int:
    global MODEL
    if len(sys.argv) > 1 and sys.argv[1].strip():
        MODEL = sys.argv[1].strip()
    print(f"=== PHA E2E combined ===\nmodel={MODEL} base={BASE}\n")

    sess = _post_json(f"{BASE}/api/chat/sessions", {"user_id": USER_ID})
    session_id = str(sess.get("session_id") or sess.get("id") or "")
    print(f"session_id={session_id}\n")

    print("--- Turn 1: supplement ---")
    ans1, session_id, st1, t1, chunks1, _, _, _ = _chat_stream(message=T1_SUPPLEMENT, session_id=session_id)
    print(f"elapsed={t1:.1f}s chunks={chunks1} approx_tok_s={len(ans1)/max(t1,0.1):.0f} chars/s")
    print(f"status: {st1[-3:] if len(st1)>3 else st1}")
    print(f"answer_len={len(ans1)}\n")

    print("--- Turn 2: combined ---")
    ans2, session_id, st2, t2, chunks2, _, numerics_audit, errors = _chat_stream(
        message=T2_COMBINED,
        session_id=session_id,
    )
    cps = len(ans2) / max(t2, 0.1)
    print(f"elapsed={t2:.1f}s delta_events={chunks2} ~{cps:.0f} chars/s (SSE delta granularity)")
    print(f"status: {st2}")
    audit = _audit_answer(ans2)
    print("\n--- Audit (legacy heuristics) ---")
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    print("\n--- numerics_audit (C-layer) ---")
    print(json.dumps(numerics_audit, ensure_ascii=False, indent=2))

    print("\n=== FINAL COMBINED ANSWER (Turn 2) ===\n")
    print(ans2)
    print("\n=== END ===")

    failed = 0
    if errors:
        print("\nFAIL: SSE errors:", errors)
        failed += 1
    if len(ans2.strip()) < 50:
        print("\nFAIL: Turn2 answer too short or empty")
        failed += 1
    if not numerics_audit:
        print("\nFAIL: missing numerics_audit in done payload")
        failed += 1
    elif not numerics_audit.get("passed"):
        print("\nFAIL: numerics_audit violations:", numerics_audit.get("violations"))
        failed += 1
    if os.environ.get("PHA_NUMERICS_REQUIRE_CITATION", "0").strip() in ("1", "true", "yes"):
        if numerics_audit and not (
            numerics_audit.get("cited_dates") or numerics_audit.get("cited_lipid_values")
        ):
            print("\nFAIL: no ground-truth citation in numerics_audit")
            failed += 1
    if audit["found_bad_dates"]:
        print("\nFAIL: hallucinated dates:", audit["found_bad_dates"])
        failed += 1
    elif not audit["found_ok_dates"] and not audit["found_ok_values"]:
        print("\nWARN: no ground-truth dates/values cited (legacy)")
    if audit["asks_user_for_data"]:
        print("\nWARN: still asking user for data")

    return failed


if __name__ == "__main__":
    raise SystemExit(main())
