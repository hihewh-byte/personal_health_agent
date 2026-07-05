#!/usr/bin/env python3
"""Multi-session wearable E2E battery (≤50 total turns, ≤20 per session)."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx

BASE = f"http://127.0.0.1:{os.environ.get('PHA_PORT', '8788')}"
ASSETS = Path(
    os.environ.get(
        "PHA_JUN11_ASSETS",
        "/Users/hwh/.cursor/projects/Users-hwh-Documents-myAgents/assets",
    ),
)
MODEL = "qwen2.5:7b-instruct"
MAX_TOTAL = int(os.environ.get("PHA_E2E_MAX_TURNS", "50"))
MAX_PER_SESSION = 20


def parse_sse(raw: str) -> list[dict]:
    out: list[dict] = []
    for block in raw.split("\n\n"):
        for line in block.split("\n"):
            if line.startswith("data:"):
                p = line[5:].strip()
                if p and p != "[DONE]":
                    try:
                        out.append(json.loads(p))
                    except json.JSONDecodeError:
                        pass
    return out


def chat(
    c: httpx.Client,
    msg: str,
    sid: str | None,
    *,
    paths: list[str] | None = None,
    names: list[str] | None = None,
) -> tuple[str, str, dict, list[str], float]:
    body: dict = {"user_id": "default", "message": msg, "model": MODEL}
    if sid:
        body["session_id"] = sid
    if paths:
        body["attachment_paths"] = paths
        body["attachment_names"] = names or []
    t0 = time.time()
    with c.stream("POST", f"{BASE}/api/chat", json=body, timeout=600) as r:
        raw = "".join(r.iter_text())
    done = next((e for e in parse_sse(raw) if e.get("event") == "done"), {})
    ingest = done.get("ingest_payload") or {}
    metrics = {m["metric_id"]: m["value"] for m in (ingest.get("wearable_metrics") or [])}
    ans = (done.get("answer") or {}).get("answer_text") or ""
    statuses = [e.get("message") or "" for e in parse_sse(raw) if e.get("event") == "status"]
    audit = done.get("compare_table_audit") or {}
    return (
        str(done.get("session_id") or sid or ""),
        ans,
        metrics,
        statuses,
        round(time.time() - t0, 1),
        audit,
    )


def upload_all(c: httpx.Client) -> tuple[list[str], list[str]]:
    paths, names = [], []
    for p in sorted(ASSETS.glob("IMG_690*.png")):
        with p.open("rb") as fh:
            d = c.post(
                f"{BASE}/api/chat/attachments",
                data={"user_id": "default"},
                files={"file": (p.name, fh, "image/png")},
                timeout=120,
            ).json()
        paths.append(d["attachment_path"])
        names.append(d.get("attachment_name", p.name))
    return paths, names


def main() -> int:
    httpx.get(f"{BASE}/health", timeout=10).raise_for_status()
    total = 0
    fails: list[str] = []

    scenarios = [
        (
            "screenshot_6panel",
            [
                (
                    "附件是我今天的身体指标，上午阻力训练，明天适合运动吗",
                    True,
                ),
                ("血脂怎么样", False),
                ("HRV 怎么样", False),
                ("请核实今天的睡眠数据", False),
                ("锻炼次数8次从哪来", False),
                ("最近步数", False),
            ],
        ),
        (
            "warehouse_hrv",
            [
                ("我最近的 HRV 怎么样？", False),
                ("睡眠呢", False),
            ],
        ),
    ]

    with httpx.Client() as c:
        paths, names = upload_all(c)
        for scen_name, turns in scenarios:
            sid: str | None = None
            for i, (msg, attach) in enumerate(turns, 1):
                if total >= MAX_TOTAL:
                    break
                total += 1
                if i > MAX_PER_SESSION:
                    break
                sid, ans, metrics, st, el, audit = chat(
                    c,
                    msg,
                    sid,
                    paths=paths if attach else None,
                    names=names if attach else None,
                )
                print(f"[{scen_name} T{i}] {el}s audit={audit.get('fallback_mode')}")
                print(" ", ans[:220].replace("\n", " "))
                if scen_name == "screenshot_6panel" and i == 1:
                    if metrics.get("sleep_time_asleep") != "6hr32min":
                        fails.append(f"{scen_name} T1 sleep {metrics.get('sleep_time_asleep')}")
                if msg.strip() == "HRV 怎么样":
                    if "睡眠总时长" in ans or "呼吸率" in ans:
                        fails.append(f"{scen_name} HRV focus leaked other metrics")
                    if "关于您关心的指标" not in ans and audit.get("fallback_mode") != "metric_focus":
                        if "34" not in ans:
                            fails.append(f"{scen_name} HRV missing 34")
                if "核实" in msg and "6" not in ans[:120]:
                    fails.append(f"{scen_name} sleep correction missing 6h")
            if total >= MAX_TOTAL:
                break

    print(f"\nTOTAL_TURNS={total}")
    if fails:
        print("FAIL:", fails)
        return 1
    print("PASS battery")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
