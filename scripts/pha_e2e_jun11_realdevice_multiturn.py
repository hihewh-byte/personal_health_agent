#!/usr/bin/env python3
"""Jun 11 real-device 6-screenshot multi-turn E2E (API, mirrors browser chat)."""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
TIMEOUT = 600.0
USER_ID = "default"

TURN1_MSG = (
    "附件是我今天的一些身体指标情况，需要说明的是上午有一个workout是阻力训练，"
    "我想知道明天是否适合运动，如果适合，请建议运动类型。"
)
FOLLOWUPS = [
    "血脂怎么样",
    "HRV 怎么样",
    "请核实今天的睡眠数据，睡眠时长明显不对的话请再次分析截图",
    "锻炼次数8次的数据是从哪里来的？",
    "能不能再次解析睡眠的截图的数据？需要我再次上传吗？",
    "最近步数",
]


@dataclass
class TurnResult:
    turn: int
    message: str
    elapsed_s: float = 0.0
    answer: str = ""
    metrics: dict[str, str] = field(default_factory=dict)
    harness_profile: str = ""
    compare_audit: dict[str, Any] = field(default_factory=dict)
    compare_rows: int = 0
    errors: list[str] = field(default_factory=list)
    status_msgs: list[str] = field(default_factory=list)


def parse_sse(raw: str) -> list[dict]:
    out: list[dict] = []
    for block in raw.split("\n\n"):
        for line in block.split("\n"):
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                out.append(json.loads(payload))
            except json.JSONDecodeError:
                pass
    return out


def upload(client: httpx.Client, path: Path) -> tuple[str, str]:
    with path.open("rb") as fh:
        r = client.post(
            f"{BASE}/api/chat/attachments",
            data={"user_id": USER_ID},
            files={"file": (path.name, fh, "image/png")},
            timeout=120.0,
        )
    r.raise_for_status()
    d = r.json()
    return str(d["attachment_path"]), str(d.get("attachment_name") or path.name)


def chat(
    client: httpx.Client,
    *,
    message: str,
    paths: list[str],
    names: list[str],
    session_id: str | None,
) -> TurnResult:
    body: dict[str, Any] = {
        "user_id": USER_ID,
        "message": message,
        "model": MODEL,
    }
    if session_id:
        body["session_id"] = session_id
    if paths:
        body["attachment_paths"] = paths
        body["attachment_names"] = names
        if len(paths) == 1:
            body["attachment_path"] = paths[0]
            body["attachment_name"] = names[0]

    t0 = time.time()
    with client.stream("POST", f"{BASE}/api/chat", json=body, timeout=TIMEOUT) as resp:
        resp.raise_for_status()
        raw = "".join(resp.iter_text())
    events = parse_sse(raw)
    done = next((e for e in events if e.get("event") == "done"), {})
    err = next((e for e in events if e.get("event") == "error"), None)
    tr = TurnResult(
        turn=0,
        message=message,
        elapsed_s=round(time.time() - t0, 1),
        answer=(done.get("answer") or {}).get("answer_text") or "",
    )
    if err:
        tr.errors.append(str(err.get("message") or err))
    ingest = done.get("ingest_payload") or {}
    tr.metrics = {
        str(m.get("metric_id")): str(m.get("value"))
        for m in (ingest.get("wearable_metrics") or [])
    }
    ct = ingest.get("wearable_compare_table_v1") or {}
    tr.compare_rows = len(ct.get("rows") or [])
    tr.compare_audit = done.get("compare_table_audit") or {}
    _h = done.get("harness") or {}
    tr.harness_profile = str((_h.get("plan") or {}).get("profile") or _h.get("profile") or "")
    tr.status_msgs = [
        str(e.get("message") or "")
        for e in events
        if e.get("event") == "status" and e.get("message")
    ]
    tr._session_id = str(done.get("session_id") or session_id or "")  # type: ignore[attr-defined]
    return tr


def assert_turn1(tr: TurnResult) -> list[str]:
    fails: list[str] = []
    want = {
        "sleep_time_asleep": "6hr32min",
        "hrv_rmssd_ms": "34",
        "resting_heart_rate_bpm": "63",
        "workout_count_recent": "20",
        "workout_heart_rate_range_bpm": "68-116",
    }
    for mid, val in want.items():
        got = tr.metrics.get(mid)
        if got != val:
            fails.append(f"T1 metric {mid}: want {val!r} got {got!r}")
    if "1小时55" in tr.answer or "1 hr 55" in tr.answer.lower():
        if "awake" not in tr.answer.lower() and "清醒" not in tr.answer:
            fails.append("T1 answer cites 1hr55 as sleep total")
    if "8 次" in tr.answer or "8次" in tr.answer:
        fails.append("T1 answer cites wrong workout count 8")
    return fails


def assert_correction_turn(tr: TurnResult, *, turn_no: int) -> list[str]:
    fails: list[str] = []
    if tr.metrics.get("sleep_time_asleep") and tr.metrics["sleep_time_asleep"] != "6hr32min":
        fails.append(f"T{turn_no} sleep remerge wrong: {tr.metrics.get('sleep_time_asleep')}")
    if "1小时55" in tr.answer and "6" not in tr.answer[:200]:
        fails.append(f"T{turn_no} still wrong sleep in answer")
    full_table_hits = tr.answer.count("根据您上传的 Apple Watch 截图")
    if full_table_hits > 1:
        fails.append(f"T{turn_no} repeated compare preamble x{full_table_hits}")
    return fails


def assert_single_metric_focus(tr: TurnResult, *, turn_no: int, forbidden: list[str]) -> list[str]:
    fails: list[str] = []
    if tr.compare_audit.get("fallback_mode") == "metric_focus" or "关于您关心的指标" in tr.answer:
        pass
    elif "根据您上传的 Apple Watch 截图" in tr.answer and "关于您关心的指标" not in tr.answer:
        fails.append(f"T{turn_no} still full compare preamble")
    for word in forbidden:
        if word in tr.answer:
            fails.append(f"T{turn_no} mentions unrelated metric {word!r}")
    if len(tr.answer) > 900:
        fails.append(f"T{turn_no} answer too long ({len(tr.answer)} chars)")
    return fails


def turn_result_to_snapshot(tr: TurnResult, *, scenario: str) -> dict[str, Any]:
    return {
        "scenario": scenario,
        "message": tr.message,
        "session_id": getattr(tr, "_session_id", ""),
        "harness_profile": tr.harness_profile,
        "answer": tr.answer,
        "metrics": dict(tr.metrics),
        "compare_audit": dict(tr.compare_audit),
        "compare_rows": tr.compare_rows,
        "status_msgs": list(tr.status_msgs),
        "errors": list(tr.errors),
        "turn": tr.turn,
        "elapsed_s": tr.elapsed_s,
    }


def run_p1_real_scenarios(
    assets_dir: Path | None = None,
    *,
    verbose: bool = False,
) -> dict[str, Any]:
    """P1-e: E1 (6图) + E2 (同 session HRV) + E3 (新 session 空附件 HRV)."""
    assets = assets_dir or ASSETS
    imgs = sorted(assets.glob("IMG_690*.png"))
    if len(imgs) < 6:
        return {"ok": False, "error": f"missing IMG_690*.png in {assets}"}

    httpx.get(f"{BASE}/health", timeout=10.0).raise_for_status()
    e1_msg = TURN1_MSG
    e2_msg = "HRV 怎么样"
    e3_msg = "图片里是什么"

    out: dict[str, Any] = {"ok": True, "assets_dir": str(assets), "turns": {}}

    with httpx.Client() as client:
        paths, names = [], []
        for p in imgs:
            ap, an = upload(client, p)
            paths.append(ap)
            names.append(an)
            if verbose:
                print("uploaded", p.name)

        tr1 = chat(
            client,
            message=e1_msg,
            paths=paths,
            names=names,
            session_id=None,
        )
        tr1.turn = 1
        sid = getattr(tr1, "_session_id", "") or ""
        out["turns"]["E1"] = turn_result_to_snapshot(tr1, scenario="E1")
        t1_fails = assert_turn1(tr1)
        if t1_fails:
            out["ok"] = False
            out["e1_legacy_fails"] = t1_fails

        tr2 = chat(
            client,
            message=e2_msg,
            paths=[],
            names=[],
            session_id=sid,
        )
        tr2.turn = 2
        sid = getattr(tr2, "_session_id", sid) or sid
        out["turns"]["E2"] = turn_result_to_snapshot(tr2, scenario="E2")
        out["session_id"] = sid

        tr3 = chat(
            client,
            message=e3_msg,
            paths=[],
            names=[],
            session_id=None,
        )
        tr3.turn = 3
        out["turns"]["E3"] = turn_result_to_snapshot(tr3, scenario="E3")

        if verbose:
            for key in ("E1", "E2", "E3"):
                t = out["turns"][key]
                print(f"{key} profile={t['harness_profile']} metrics={list(t['metrics'].keys())}")

    return out


def main() -> int:
    imgs = sorted(ASSETS.glob("IMG_690*.png"))
    if len(imgs) < 6:
        print("FAIL missing IMG_690*.png in", ASSETS)
        return 1

    httpx.get(f"{BASE}/health", timeout=10.0).raise_for_status()
    results: list[TurnResult] = []
    all_fails: list[str] = []

    with httpx.Client() as client:
        paths, names = [], []
        for p in imgs:
            ap, an = upload(client, p)
            paths.append(ap)
            names.append(an)
            print("uploaded", p.name)

        sid: str | None = None
        for i, msg in enumerate([TURN1_MSG, *FOLLOWUPS], start=1):
            print(f"\n=== Turn {i}: {msg[:60]}... ===")
            tr = chat(
                client,
                message=msg,
                paths=paths if i == 1 else [],
                names=names if i == 1 else [],
                session_id=sid,
            )
            tr.turn = i
            sid = getattr(tr, "_session_id", sid) or sid
            results.append(tr)
            print(f"elapsed={tr.elapsed_s}s profile={tr.harness_profile} metrics={list(tr.metrics.keys())}")
            if tr.status_msgs:
                print("status:", tr.status_msgs[-1][:120])
            print("answer_head:", tr.answer[:280].replace("\n", " "))
            if i == 1:
                all_fails.extend(assert_turn1(tr))
            if i == 3:
                all_fails.extend(
                    assert_single_metric_focus(tr, turn_no=3, forbidden=["睡眠总时长", "呼吸率", "锻炼心率"]),
                )
            if i in (4, 5):
                all_fails.extend(assert_correction_turn(tr, turn_no=i))

    print("\n=== SUMMARY ===")
    for tr in results:
        print(f"T{tr.turn} {tr.elapsed_s}s audit_pass={tr.compare_audit.get('passed')} fallback={tr.compare_audit.get('fallback_mode')}")
    if all_fails:
        print("FAILURES:")
        for f in all_fails:
            print(" -", f)
        return 1
    print("PASS all", len(results), "turns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
