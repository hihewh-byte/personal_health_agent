#!/usr/bin/env python3
"""Stage 3C multi-turn E2E — API + harness JSONL capture for test report."""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib import error, request

BASE = "http://127.0.0.1:8788"
HARNESS_PATH = Path("/tmp/pha-e2e-harness.jsonl")
MODEL = "qwen2.5:7b-instruct"
TIMEOUT = 300


@dataclass
class TurnResult:
    turn: int
    message: str
    events: list[str] = field(default_factory=list)
    answer_preview: str = ""
    error: str = ""
    duration_s: float = 0.0
    harness: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScenarioResult:
    name: str
    rounds: int
    session_id: str
    turns: list[TurnResult] = field(default_factory=list)
    passed: bool = True
    notes: list[str] = field(default_factory=list)


def _harness_lines_before() -> int:
    if not HARNESS_PATH.is_file():
        return 0
    return sum(1 for _ in HARNESS_PATH.open(encoding="utf-8"))


def _read_new_harness_reports(since: int) -> list[dict[str, Any]]:
    if not HARNESS_PATH.is_file():
        return []
    out: list[dict[str, Any]] = []
    for i, line in enumerate(HARNESS_PATH.open(encoding="utf-8")):
        if i < since:
            continue
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _create_session() -> str:
    req = request.Request(
        f"{BASE}/api/chat/sessions?user_id=default",
        method="POST",
    )
    with request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())["id"]


def _post_chat(session_id: str, message: str) -> TurnResult:
    body = json.dumps(
        {
            "user_id": "default",
            "message": message,
            "model": MODEL,
            "session_id": session_id,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = request.Request(
        f"{BASE}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    before = _harness_lines_before()
    t0 = time.time()
    turn = TurnResult(turn=0, message=message)
    try:
        with request.urlopen(req, timeout=TIMEOUT) as resp:
            buf = ""
            for chunk in iter(lambda: resp.read(4096), b""):
                buf += chunk.decode("utf-8", errors="replace")
                while "\n\n" in buf:
                    block, buf = buf.split("\n\n", 1)
                    for line in block.split("\n"):
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if not payload:
                            continue
                        try:
                            ev = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        et = str(ev.get("event") or "")
                        turn.events.append(et or "json")
                        if et == "delta" and ev.get("content"):
                            turn.answer_preview += str(ev.get("content") or "")
                        if et == "done":
                            ans = ev.get("answer") or {}
                            if isinstance(ans, dict):
                                turn.answer_preview = str(ans.get("answer_text") or turn.answer_preview)
                        if et == "error":
                            turn.error = str(ev.get("message") or "error")
    except error.HTTPError as exc:
        turn.error = f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:400]}"
    except Exception as exc:
        turn.error = f"{type(exc).__name__}: {exc}"
    turn.duration_s = round(time.time() - t0, 1)
    reports = _read_new_harness_reports(before)
    for rep in reports:
        if rep.get("mode") == "turn_complete":
            turn.harness = rep
            break
    if not turn.harness and reports:
        turn.harness = reports[-1]
    turn.answer_preview = (turn.answer_preview or "")[:500]
    return turn


def _run_scenario(name: str, messages: list[str]) -> ScenarioResult:
    sid = _create_session()
    scen = ScenarioResult(name=name, rounds=len(messages), session_id=sid)
    for i, msg in enumerate(messages, start=1):
        tr = _post_chat(sid, msg)
        tr.turn = i
        scen.turns.append(tr)
        if tr.error:
            scen.passed = False
            scen.notes.append(f"R{i} error: {tr.error}")
        if "done" not in tr.events and not tr.error:
            scen.passed = False
            scen.notes.append(f"R{i} missing done event: {tr.events}")
    return scen


def _eval_wearable_focus(scen: ScenarioResult) -> None:
    if len(scen.turns) < 2:
        return
    h2 = scen.turns[1].harness
    ts = h2.get("turnScope") or {}
    if ts.get("metricSource") == "focus":
        scen.notes.append("OK R2 metricSource=focus")
    elif ts:
        scen.notes.append(f"WARN R2 metricSource={ts.get('metricSource')}")
    else:
        scen.notes.append("WARN R2 no turnScope in harness")
    ep = h2.get("episodic") or {}
    if ep.get("bridgeInjected"):
        scen.notes.append("OK R2 episodic.bridgeInjected=true")
    prof = (h2.get("plan") or {}).get("profile")
    if prof == "lifestyle" and "HRV" in scen.turns[0].message.upper():
        scen.passed = False
        scen.notes.append(f"FAIL R2 profile dropped to lifestyle ({prof})")


def _eval_casual(scen: ScenarioResult) -> None:
    prof = ((scen.turns[-1].harness.get("plan") or {}).get("profile") if scen.turns else None)
    if prof and prof != "casual" and scen.turns[0].message.strip() in ("你好", "您好"):
        scen.notes.append(f"INFO casual profile={prof}")


def main() -> int:
    if HARNESS_PATH.is_file():
        HARNESS_PATH.write_text("", encoding="utf-8")

    health = request.urlopen(f"{BASE}/health", timeout=10).read().decode()
    print("health:", health)

    scenarios = [
        (
            "S1-穿戴3轮(HRV→上个月→继续)",
            ["我最近的 HRV 怎么样？", "那上个月呢", "继续"],
        ),
        (
            "S2-穿戴5轮+随机",
            [
                "近90天睡眠怎么样",
                "步数呢",
                "那 HRV 呢",
                "继续说说",
                "好的知道了",
            ],
        ),
        (
            "S3-化验2轮",
            ["血脂怎么样", "每年的 LDL 呢"],
        ),
        (
            "S4-寒暄2轮",
            ["你好", "谢谢"],
        ),
        (
            "S6-混合6轮",
            [
                "帮我看看静息心率",
                "睡眠呢",
                "那上个月 HRV",
                "继续",
                "和去年比呢",
                "收到",
            ],
        ),
    ]

    results: list[ScenarioResult] = []
    for name, msgs in scenarios:
        print(f"\n=== {name} ({len(msgs)} rounds) ===")
        scen = _run_scenario(name, msgs)
        if "穿戴" in name or "HRV" in name:
            _eval_wearable_focus(scen)
        if "寒暄" in name:
            _eval_casual(scen)
        results.append(scen)
        for t in scen.turns:
            prof = (t.harness.get("plan") or {}).get("profile", "?")
            ts = t.harness.get("turnScope") or {}
            print(
                f"  R{t.turn} [{t.duration_s}s] profile={prof} "
                f"metricSrc={ts.get('metricSource','-')} "
                f"bridge={((t.harness.get('episodic') or {}).get('bridgeInjected'))} "
                f"ans={t.answer_preview[:80]!r}",
            )
            if t.error:
                print(f"    ERROR: {t.error}")

    report_path = Path(__file__).resolve().parents[1] / "docs" / "stage3c-multiturn-e2e-report-2026-06-10.md"
    lines = [
        "# Stage 3C 多轮对话真机 E2E 测试报告",
        "",
        f"> 时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"> 服务：`{BASE}` · build `pha-v2.3.32-full-import-only`",
        "> Flag：`PHA_EPISODIC_ALL_PROFILES=1` · `PHA_HEALTH_TURN_RESOLVER=1`",
        f"> 模型：`{MODEL}`",
        "",
        "## 汇总",
        "",
        "| 场景 | 轮数 | 结果 | 关键观察 |",
        "|------|------|------|----------|",
    ]
    ok = 0
    for s in results:
        status = "PASS" if s.passed else "FAIL"
        if s.passed:
            ok += 1
        key = "; ".join(s.notes[:3]) if s.notes else "—"
        lines.append(f"| {s.name} | {s.rounds} | {status} | {key} |")

    lines.extend(["", "## 分场景详情", ""])
    for s in results:
        lines.append(f"### {s.name}")
        lines.append(f"- session_id: `{s.session_id}`")
        lines.append(f"- 结果: **{'PASS' if s.passed else 'FAIL'}**")
        for n in s.notes:
            lines.append(f"- {n}")
        for t in s.turns:
            h = t.harness
            ts = h.get("turnScope") or {}
            lines.append(
                f"- R{t.turn} `{t.message}` → profile=`{(h.get('plan') or {}).get('profile')}` "
                f"turnScope.metricKeys={ts.get('metricKeys')} metricSource={ts.get('metricSource')} "
                f"episodic.bridge={((h.get('episodic') or {}).get('bridgeInjected'))} "
                f"({t.duration_s}s)",
            )
            if t.answer_preview:
                lines.append(f"  - 答复摘要: {t.answer_preview[:200]}")
        lines.append("")

    lines.append(f"## 结论\n\n自动化场景 **{ok}/{len(results)}** PASS。")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport written: {report_path}")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
