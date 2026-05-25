#!/usr/bin/env python3
"""E2E: 90d sleep + SpO2 wearable question (no lab)."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8787"
MODEL = os.environ.get("PHA_E2E_MODEL", "qwen2.5:7b-instruct")
USER_ID = "default"
MSG = "请分析最近90天我的睡眠时间的血氧数据是否正常"


def main() -> int:
    body = {"user_id": USER_ID, "message": MSG, "model": MODEL}
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/api/chat",
        data=data,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
    )
    parts: list[str] = []
    statuses: list[str] = []
    numerics_audit: dict = {}
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=600) as resp:
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            ev = json.loads(line[5:].strip())
            et = ev.get("event")
            if et == "delta" and ev.get("delta"):
                parts.append(str(ev["delta"]))
            elif et == "status" and ev.get("message"):
                statuses.append(str(ev["message"]))
            elif et == "error":
                print("ERROR:", ev.get("message"))
                return 1
            elif et == "done":
                numerics_audit = dict(ev.get("numerics_audit") or {})
                if ev.get("answer"):
                    parts = [str((ev["answer"] or {}).get("answer_text") or "")]
    elapsed = time.perf_counter() - t0
    text = "".join(parts)
    print(f"elapsed={elapsed:.1f}s")
    print("status:", statuses[:6])
    print("numerics_audit:", json.dumps(numerics_audit, ensure_ascii=False, indent=2))
    print("answer_len:", len(text))
    print("--- answer ---")
    print(text[:2000])

    failed = 0
    if "请" in text and ("提供" in text or "请您" in text) and "数据" in text:
        if not any(x in text for x in ("96", "95", "血氧", "睡眠", "8.")):
            print("FAIL: model soliciting data instead of citing DB")
            failed += 1
    if not any(k in text for k in ("血氧", "睡眠", "SpO2", "spo2", "%")):
        print("FAIL: answer missing sleep/spo2 discussion")
        failed += 1
    if "7日" in text and "90" not in text and "88" not in text:
        print("WARN: answer cites 7-day window without 90d context")
    if "没有提供" in text or "请您提供" in text:
        print("FAIL: model still soliciting raw data")
        failed += 1
  # wearable_only may not emit numerics_audit — optional
    if numerics_audit and not numerics_audit.get("passed", True):
        print("FAIL: numerics_audit", numerics_audit)
        failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
