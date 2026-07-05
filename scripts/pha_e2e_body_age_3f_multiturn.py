#!/usr/bin/env python3
"""Stage 3F body-age multi-turn E2E — API path (mirrors browser chat)."""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib import error, request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pha.e2e_combined_review_assertions import (
    assert_combined_review_sse_turn,
    harness_profile,
    is_combined_review_harness,
)

BASE = f"http://127.0.0.1:{os.environ.get('PHA_PORT', '8788')}"
HARNESS = Path(os.environ.get("PHA_HARNESS_REPORT_PATH", "/tmp/pha-e2e-harness.jsonl"))
MODEL = "qwen2.5:7b-instruct"
TIMEOUT = 300

MESSAGES = [
    "根据各项指标和数据，请判断身体年龄",
    "血脂怎么样",
    "HRV 怎么样",
    "最近步数",
    "为什么你说没有数据",
    "身体年龄多少岁",
    "用已有数据分析身体年龄",
    "请评估身体年龄",
]

EXPECT = {
    1: {"profile": "combined_review", "goal": "holistic_assessment"},
    2: {"profile_any": ("lab_cross_year", "clarify")},
    8: {"profile": "combined_review", "arbiter_reason_any": ("episodic_goal_continue", "goal_holistic_upgrade")},
    6: {"profile": "combined_review", "arbiter_reason_any": ("episodic_goal_continue", "goal_holistic_upgrade")},
    7: {"profile": "combined_review", "arbiter_reason_any": ("episodic_goal_continue", "goal_holistic_upgrade")},
}


@dataclass
class TurnResult:
    turn: int
    message: str
    duration_s: float = 0.0
    events: list[str] = field(default_factory=list)
    answer_preview: str = ""
    answer_chars: int = 0
    error: str = ""
    harness: dict[str, Any] = field(default_factory=dict)


def _harness_before() -> int:
    return sum(1 for _ in HARNESS.open(encoding="utf-8")) if HARNESS.is_file() else 0


def _read_new(since: int) -> list[dict[str, Any]]:
    if not HARNESS.is_file():
        return []
    out: list[dict[str, Any]] = []
    for i, line in enumerate(HARNESS.open(encoding="utf-8")):
        if i < since:
            continue
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def _create_session() -> str:
    req = request.Request(f"{BASE}/api/chat/sessions?user_id=default", method="POST")
    with request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())["id"]


def _post_chat(session_id: str, message: str) -> TurnResult:
    body = json.dumps(
        {"user_id": "default", "message": message, "model": MODEL, "session_id": session_id},
        ensure_ascii=False,
    ).encode()
    req = request.Request(
        f"{BASE}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    before = _harness_before()
    t0 = time.time()
    tr = TurnResult(turn=0, message=message)
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
                        tr.events.append(et)
                        if et == "delta" and ev.get("content"):
                            tr.answer_preview += str(ev["content"])
                        if et == "done":
                            ans = ev.get("answer") or {}
                            if isinstance(ans, dict):
                                tr.answer_preview = str(ans.get("answer_text") or tr.answer_preview)
                        if et == "error":
                            tr.error = str(ev.get("message") or "error")
    except error.HTTPError as exc:
        tr.error = f"HTTP {exc.code}"
    except Exception as exc:
        tr.error = f"{type(exc).__name__}: {exc}"
    tr.duration_s = round(time.time() - t0, 1)
    for rep in _read_new(before):
        if rep.get("mode") == "turn_complete":
            tr.harness = rep
    if not tr.harness:
        reps = _read_new(before)
        if reps:
            tr.harness = reps[-1]
    tr.answer_chars = len(tr.answer_preview or "")
    tr.answer_preview = (tr.answer_preview or "")[:300]
    return tr


def _profile(h: dict[str, Any]) -> str:
    return harness_profile(h)


def _eval(turns: list[TurnResult]) -> list[str]:
    fails: list[str] = []
    for t in turns:
        n = t.turn
        prof = _profile(t.harness)

        # P2: combined_review catalog lane must complete SSE without error.
        fails.extend(
            assert_combined_review_sse_turn(
                turn=n,
                error=t.error,
                events=t.events,
                answer_chars=t.answer_chars,
                harness=t.harness,
            ),
        )

        if n not in EXPECT:
            continue
        exp = EXPECT[n]
        if t.error and prof != "combined_review" and prof in (
            "clarify",
            "wearable_only",
            "lab_cross_year",
        ):
            # Non-combined lanes: route still auditable when LLM fails post-plan.
            pass
        elif t.error and prof != "combined_review":
            fails.append(f"T{n} error: {t.error}")
            continue
        if "profile" in exp and prof != exp["profile"]:
            fails.append(f"T{n} profile={prof!r} want {exp['profile']!r}")
        if "profile_any" in exp and prof not in exp["profile_any"]:
            fails.append(f"T{n} profile={prof!r} want one of {exp['profile_any']}")
        if "goal" in exp:
            got = str(t.harness.get("goalClass") or "")
            if got != exp["goal"]:
                fails.append(f"T{n} goalClass={got!r} want {exp['goal']!r}")
        if "arbiter_reason_any" in exp:
            reason = str((t.harness.get("arbiterDecision") or {}).get("reason") or "")
            if reason not in exp["arbiter_reason_any"]:
                fails.append(f"T{n} arbiter.reason={reason!r}")
    return fails


def main() -> int:
    if HARNESS.is_file():
        HARNESS.write_text("", encoding="utf-8")
    health = request.urlopen(f"{BASE}/health", timeout=10).read().decode()
    print("health:", health)
    sid = _create_session()
    print("session:", sid)
    turns: list[TurnResult] = []
    for i, msg in enumerate(MESSAGES, 1):
        print(f"\n--- T{i} --- {msg[:50]}")
        tr = _post_chat(sid, msg)
        tr.turn = i
        turns.append(tr)
        h = tr.harness
        print(
            f"  {tr.duration_s}s profile={_profile(h)} goal={h.get('goalClass')} "
            f"arbiter={(h.get('arbiterDecision') or {}).get('reason')} "
            f"manifest_n={len((h.get('numerics_manifest') or {}).get('entries') or [])}",
        )
        if tr.answer_preview:
            print(f"  ans: {tr.answer_preview[:120]!r}")
        if tr.error:
            print("  ERROR:", tr.error)
        if is_combined_review_harness(h):
            tools = (h.get("tools") or {}).get("executed") or []
            tool_names = [
                str(r.get("name") or r.get("tool") or "")
                for r in tools
                if isinstance(r, dict)
            ]
            print(
                f"  combined_review_sse: done={'done' in tr.events} "
                f"chars={tr.answer_chars} runtime={h.get('runtime_mode')} "
                f"tools={tool_names}",
            )
    fails = _eval(turns)
    out = ROOT / "docs" / "stage3f-body-age-e2e-report.md"
    lines = [
        "# Stage 3F Body-Age E2E Report",
        "",
        f"> session: `{sid}`",
        f"> harness: `{HARNESS}`",
        "",
        "| Turn | Message | Profile | goalClass | arbiter | manifest_n |",
        "|------|---------|---------|-----------|---------|------------|",
    ]
    for t in turns:
        h = t.harness
        lines.append(
            f"| T{t.turn} | {t.message[:24]} | {_profile(h)} | {h.get('goalClass','-')} | "
            f"{(h.get('arbiterDecision') or {}).get('reason','-')} | "
            f"{len((h.get('numerics_manifest') or {}).get('entries') or [])} |",
        )
    lines.append("")
    cr_turns = [t for t in turns if is_combined_review_harness(t.harness)]
    if cr_turns:
        lines.extend(
            [
                "## combined_review SSE 硬断言 (P2)",
                "",
                "| Turn | SSE error | done | answer_chars | runtime_mode | fetch_evidence |",
                "|------|-----------|------|--------------|--------------|----------------|",
            ],
        )
        for t in cr_turns:
            h = t.harness
            tools = (h.get("tools") or {}).get("executed") or []
            fetched = any(
                str(r.get("name") or r.get("tool") or "") == "fetch_evidence_by_id"
                for r in tools
                if isinstance(r, dict)
            )
            lines.append(
                f"| T{t.turn} | {'yes' if t.error else 'no'} | "
                f"{'yes' if 'done' in t.events else 'no'} | {t.answer_chars} | "
                f"{h.get('runtime_mode', '-')} | {'yes' if fetched else 'no'} |",
            )
        lines.append("")
    if fails:
        lines.append("## FAIL")
        for f in fails:
            lines.append(f"- {f}")
        out.write_text("\n".join(lines), encoding="utf-8")
        print("\nFAIL:", fails)
        return 1
    lines.append("## PASS")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nPASS all expectations; report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
