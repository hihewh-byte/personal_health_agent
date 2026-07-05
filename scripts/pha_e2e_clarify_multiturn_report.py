#!/usr/bin/env python3
"""Stage 3C-δ E2E — clarify SSE + chip follow-up (API capture for report)."""

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
    clarify_choice_id: str = ""
    events: list[str] = field(default_factory=list)
    clarify_payload: dict[str, Any] = field(default_factory=dict)
    answer_preview: str = ""
    error: str = ""
    duration_s: float = 0.0
    harness: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScenarioResult:
    name: str
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
    req = request.Request(f"{BASE}/api/chat/sessions?user_id=default", method="POST")
    with request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())["id"]


def _post_chat(
    session_id: str,
    message: str,
    *,
    clarify_choice_id: str = "",
) -> TurnResult:
    body_obj: dict[str, Any] = {
        "user_id": "default",
        "message": message,
        "model": MODEL,
        "session_id": session_id,
    }
    if clarify_choice_id:
        body_obj["clarify_choice_id"] = clarify_choice_id
    body = json.dumps(body_obj, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        f"{BASE}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    before = _harness_lines_before()
    t0 = time.time()
    turn = TurnResult(turn=0, message=message, clarify_choice_id=clarify_choice_id)
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
                        if et == "clarify":
                            turn.clarify_payload = ev
                        if et == "delta" and ev.get("delta"):
                            turn.answer_preview += str(ev.get("delta") or "")
                        if et == "done":
                            ans = ev.get("answer") or {}
                            if isinstance(ans, dict):
                                turn.answer_preview = str(
                                    ans.get("answer_text") or turn.answer_preview,
                                )
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


def _eval_clarify_flow(scen: ScenarioResult) -> None:
    if len(scen.turns) < 2:
        scen.passed = False
        scen.notes.append("FAIL need 2 turns")
        return
    r1, r2 = scen.turns[0], scen.turns[1]
    if r1.error:
        scen.passed = False
        scen.notes.append(f"FAIL R1 error: {r1.error}")
        return
    if "clarify" not in r1.events:
        scen.passed = False
        scen.notes.append(f"FAIL R1 missing clarify event: {r1.events}")
        return
    if "delta" in r1.events:
        scen.passed = False
        scen.notes.append("FAIL R1 should short-circuit LLM (no delta)")
    choices = r1.clarify_payload.get("choices") or []
    if len(choices) < 2:
        scen.passed = False
        scen.notes.append(f"FAIL R1 choices count: {len(choices)}")
    else:
        scen.notes.append(f"OK R1 clarify choices={len(choices)}")
    h1 = r1.harness
    prof1 = (h1.get("plan") or {}).get("profile")
    if prof1 == "clarify":
        scen.notes.append("OK R1 harness profile=clarify")
    elif h1:
        scen.notes.append(f"WARN R1 harness profile={prof1}")
    if r2.error:
        scen.passed = False
        scen.notes.append(f"FAIL R2 error: {r2.error}")
        return
    if "clarify" in r2.events:
        scen.passed = False
        scen.notes.append("FAIL R2 should not clarify again after chip")
    ts = (r2.harness.get("turnScope") or {})
    if ts.get("yearSource") == "explicit" or ts.get("labYears"):
        scen.notes.append(f"OK R2 turnScope labYears={ts.get('labYears')} yearSource={ts.get('yearSource')}")
    else:
        scen.notes.append(f"WARN R2 turnScope={ts}")
    if "done" not in r2.events:
        scen.passed = False
        scen.notes.append(f"FAIL R2 missing done: {r2.events}")
    prof2 = (r2.harness.get("plan") or {}).get("profile")
    if prof2 == "lab_cross_year":
        scen.notes.append("OK R2 harness profile=lab_cross_year")
    else:
        scen.passed = False
        scen.notes.append(f"FAIL R2 harness profile={prof2} (expected lab_cross_year)")


def main() -> int:
    if HARNESS_PATH.is_file():
        HARNESS_PATH.write_text("", encoding="utf-8")

    health = request.urlopen(f"{BASE}/health", timeout=10).read().decode()
    print("health:", health)

    sid = _create_session()
    scen = ScenarioResult(name="Cδ-多年血脂澄清→chip", session_id=sid)

    r1 = _post_chat(sid, "血脂怎么样")
    r1.turn = 1
    scen.turns.append(r1)

    choice_id = "2024"
    choices = r1.clarify_payload.get("choices") or []
    for ch in choices:
        if str(ch.get("id", "")).strip():
            choice_id = str(ch["id"])
            break
    label = next(
        (str(c.get("label") or choice_id) for c in choices if str(c.get("id")) == choice_id),
        f"{choice_id}年",
    )

    r2 = _post_chat(sid, label, clarify_choice_id=choice_id)
    r2.turn = 2
    scen.turns.append(r2)

    _eval_clarify_flow(scen)

    report = {
        "scenario": scen.name,
        "session_id": scen.session_id,
        "passed": scen.passed,
        "notes": scen.notes,
        "turns": [
            {
                "turn": t.turn,
                "message": t.message,
                "clarify_choice_id": t.clarify_choice_id,
                "events": t.events,
                "duration_s": t.duration_s,
                "error": t.error,
                "clarify_kind": t.clarify_payload.get("kind"),
                "choices_count": len(t.clarify_payload.get("choices") or []),
                "answer_preview": t.answer_preview,
                "harness_profile": (t.harness.get("plan") or {}).get("profile"),
                "turn_scope": t.harness.get("turnScope"),
            }
            for t in scen.turns
        ],
    }
    out_path = Path(__file__).resolve().parents[1] / "docs" / "stage3c-clarify-e2e-report-2026-06-10.md"
    lines = [
        "# Stage 3C-δ Clarify E2E Report (2026-06-10)",
        "",
        f"- **Scenario**: {scen.name}",
        f"- **Session**: `{scen.session_id}`",
        f"- **Result**: {'PASS' if scen.passed else 'FAIL'}",
        f"- **Flags**: `PHA_CLARIFY_TURNS=1`, `PHA_HEALTH_TURN_RESOLVER=1`",
        "",
        "## Notes",
        "",
    ]
    for n in scen.notes:
        lines.append(f"- {n}")
    lines.extend(["", "## Turns", "", "```json", json.dumps(report, ensure_ascii=False, indent=2), "```", ""])
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print("report:", out_path)
    print("PASS" if scen.passed else "FAIL", scen.name, "|", "; ".join(scen.notes))
    return 0 if scen.passed else 1


if __name__ == "__main__":
    sys.exit(main())
