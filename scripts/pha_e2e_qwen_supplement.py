#!/usr/bin/env python3
"""E2E: long supplement manifest turn (context-only lane)."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

BASE = f"http://127.0.0.1:{os.environ.get('PHA_PORT', '8788')}"
MODEL = os.environ.get("PHA_E2E_MODEL", "qwen2.5:7b-instruct")
USER_ID = "default"
MSG = """以下是我的补剂方案，请帮我看看有没有问题：
上午 训练后 蛋白粉30g + 香蕉 + 5g肌酸 + B族 + 益生菌
中午 鱼油 + 卵磷脂 + D3+K2 + Q10 + 非布司他 + 他汀
晚上 烤红薯 + 蛋白 + 蔬菜 + Move Free + 姜黄素
睡前 镁300-400mg + 纳豆激酶 + 南非醉茄
"""


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
    harness: dict = {}
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
                harness = dict(ev.get("harness") or {})
                if ev.get("answer"):
                    parts = [str((ev["answer"] or {}).get("answer_text") or "")]
    elapsed = time.perf_counter() - t0
    text = "".join(parts)
    print(f"elapsed={elapsed:.1f}s")
    print("status:", statuses[:6])
    print("harness.profile:", (harness.get("plan") or {}).get("profile"))
    print("answer_len:", len(text))
    print("--- answer ---")
    print(text[:2000])

    failed = 0
    profile = (harness.get("plan") or {}).get("profile")
    if profile and profile != "supplement_manifest":
        print("FAIL: expected supplement_manifest profile, got", profile)
        failed += 1
    if not any(k in text for k in ("补剂", "肌酸", "鱼油", "他汀", "镁")):
        print("FAIL: answer missing supplement discussion")
        failed += 1
    if "HRV" in text and "Pearson" in text:
        print("FAIL: wearable dashboard leaked into supplement lane")
        failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
