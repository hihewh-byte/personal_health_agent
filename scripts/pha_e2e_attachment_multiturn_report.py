#!/usr/bin/env python3
"""Attachment episodic multi-turn E2E — upload label images + 10+ follow-up rounds."""

from __future__ import annotations

import json
import mimetypes
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import error, request

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8788"
HARNESS_PATH = Path(
    os.environ.get("PHA_HARNESS_REPORT_PATH", "/tmp/pha-e2e-harness.jsonl"),
)
REPORT_PATH = ROOT / "docs" / "stage3c-attachment-multiturn-e2e-report-2026-06-10.md"
MODEL = "qwen2.5:7b-instruct"
TIMEOUT = 600
USER_ID = "default"

# Desensitized supplement label pair already in server storage
DEFAULT_IMAGES = [
    ROOT / "storage/attachments/default/IMG_6800_8afc1e2e3c.png",
    ROOT / "storage/attachments/default/6801_393fe0bbb2.png",
]

FOLLOWUP_MESSAGES = [
  # R1 sent with attachments
    "能提高哪些指标？",
    "对血脂 LDL 有改善吗？",
    "我最近的 HRV 怎么样？",
    "睡眠呢，上个月",
    "和步数对比一下",
    "继续说说",
    "那去年化验呢",
    "刚才那张图片里写的成分是什么？",  # attachment recall probe
    "上传的附件说了什么信息？",  # attachment recall probe
    "好的知道了",
    "谢谢",
]


@dataclass
class TurnResult:
    turn: int
    message: str
    has_attachment: bool = False
    events: list[str] = field(default_factory=list)
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
    req = request.Request(
        f"{BASE}/api/chat/sessions?user_id={USER_ID}",
        method="POST",
    )
    with request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())["id"]


def _upload_attachment(path: Path) -> tuple[str, str]:
    if not path.is_file():
        raise FileNotFoundError(path)
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    boundary = f"----phaattach{int(time.time() * 1000)}"
    body = bytearray()
    for name, val in (("user_id", USER_ID),):
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(f"{val}\r\n".encode())
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'.encode(),
    )
    body.extend(f"Content-Type: {mime}\r\n\r\n".encode())
    body.extend(path.read_bytes())
    body.extend(f"\r\n--{boundary}--\r\n".encode())
    req = request.Request(
        f"{BASE}/api/chat/attachments",
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())
    return str(data["attachment_path"]), str(data.get("attachment_name") or path.name)


def _post_chat(
    session_id: str,
    message: str,
    *,
    attachment_paths: list[str] | None = None,
    attachment_names: list[str] | None = None,
) -> TurnResult:
    payload: dict[str, Any] = {
        "user_id": USER_ID,
        "message": message,
        "model": MODEL,
        "session_id": session_id,
    }
    if attachment_paths:
        payload["attachment_paths"] = attachment_paths
        payload["attachment_names"] = attachment_names or []
        if len(attachment_paths) == 1:
            payload["attachment_path"] = attachment_paths[0]
            payload["attachment_name"] = (attachment_names or [""])[0]
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        f"{BASE}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    before = _harness_lines_before()
    t0 = time.time()
    turn = TurnResult(turn=0, message=message, has_attachment=bool(attachment_paths))
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
                        pl = line[5:].strip()
                        if not pl:
                            continue
                        try:
                            ev = json.loads(pl)
                        except json.JSONDecodeError:
                            continue
                        et = str(ev.get("event") or "")
                        turn.events.append(et or "json")
                        if et == "delta" and ev.get("content"):
                            turn.answer_preview += str(ev.get("content") or "")
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
    turn.answer_preview = (turn.answer_preview or "")[:600]
    return turn


def _eval_turn(tr: TurnResult, scen: ScenarioResult) -> None:
    h = tr.harness
    if not h:
        scen.notes.append(f"WARN R{tr.turn} no harness")
        return
    plan = h.get("plan") or {}
    prof = plan.get("profile")
    forbidden = set(plan.get("forbidden") or [])
    ep = h.get("episodic") or {}
    ts = h.get("turnScope") or {}
    slots_built = h.get("slots_built") or {}
    tier1 = slots_built.get("tier1") or slots_built.get("tier_1") or {}
    recall_in_tier1 = "RECALL" in tier1 or "RECALL_FOCUS" in tier1

    if tr.error:
        scen.passed = False
        scen.notes.append(f"FAIL R{tr.turn} error: {tr.error}")
    if "done" not in tr.events and not tr.error:
        scen.passed = False
        scen.notes.append(f"FAIL R{tr.turn} missing done")

  # Constitutional: attachment profile must forbid RECALL slot in plan
    att_profiles = {"attachment_asset_qa", "attachment_episodic_bridge"}
    if prof in att_profiles:
        if "RECALL" not in forbidden:
            scen.passed = False
            scen.notes.append(f"FAIL R{tr.turn} RECALL not in plan.forbidden (profile={prof})")
        else:
            scen.notes.append(f"OK R{tr.turn} RECALL forbidden (profile={prof})")
        if recall_in_tier1:
            scen.passed = False
            scen.notes.append(f"FAIL R{tr.turn} RECALL injected in tier1 despite forbidden")
        # RECALL_FOCUS（定账锚点）与 forbidden RECALL 槽位不同，见 RFC H-A3

    if "图片" in tr.message or "附件" in tr.message:
        if recall_in_tier1 or ep.get("recallFocusInjected"):
            scen.passed = False
            scen.notes.append(f"FAIL R{tr.turn} attachment-recall phrase triggered RECALL injection")

    if tr.turn == 2 and prof not in att_profiles:
        scen.notes.append(f"WARN R2 expected attachment profile, got {prof}")


def _format_turn_line(tr: TurnResult) -> str:
    h = tr.harness
    plan = h.get("plan") or {}
    ts = h.get("turnScope") or {}
    ep = h.get("episodic") or {}
    att = f" attach" if tr.has_attachment else ""
    return (
        f"- R{tr.turn}{att} `{tr.message[:50]}` → "
        f"profile=`{plan.get('profile')}` "
        f"qaMode=`{ts.get('attachmentQaMode')}` "
        f"metricSrc=`{ts.get('metricSource')}` "
        f"bridge=`{ep.get('bridgeInjected')}` "
        f"forbidden_RECALL=`{'RECALL' in (plan.get('forbidden') or [])}` "
        f"({tr.duration_s}s)"
    )


def _write_report(scen: ScenarioResult) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "# Stage 3C 附件多轮追问 E2E 专项报告",
        "",
        f"> 时间：{now}",
        f"> 服务：`{BASE}`",
        f"> Flag：`PHA_EPISODIC_ALL_PROFILES=1` · `PHA_HEALTH_TURN_RESOLVER=1`",
        f"> 模型：`{MODEL}`",
        f"> Harness：`{HARNESS_PATH}`",
        "",
        "## 汇总",
        "",
        f"| 场景 | 轮数 | 结果 |",
        f"|------|------|------|",
        f"| {scen.name} | {len(scen.turns)} | {'PASS' if scen.passed else 'FAIL'} |",
        "",
        f"- session_id: `{scen.session_id}`",
        "",
        "### 关键观察",
        "",
    ]
    for n in scen.notes:
        lines.append(f"- {n}")
    lines.extend(["", "## 逐轮记录", ""])
    for tr in scen.turns:
        lines.append(_format_turn_line(tr))
        if tr.error:
            lines.append(f"  - ERROR: {tr.error}")
        if tr.answer_preview:
            lines.append(f"  - 答复摘要: {tr.answer_preview[:280]}…")
        lines.append("")
    lines.extend([
        "## 宪法红线（附件轨）",
        "",
        "| 检查项 | 期望 |",
        "|--------|------|",
        "| 附件 profile `plan.forbidden` 含 RECALL | 每轮 attachment_* profile |",
        "| tier1 不注入 RECALL / RECALL_FOCUS | 全轮 |",
        "| `recallFocusInjected` | false |",
        "| 追问轮 episodic focus 延续 | R2+ metricSource=focus 或 bridge |",
        "",
        "## 结论",
        "",
        f"专项 **{'PASS' if scen.passed else 'FAIL'}**（{len(scen.turns)} 轮，含 R1 双图上传）。",
        "",
    ])
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    if HARNESS_PATH.is_file():
        HARNESS_PATH.write_text("", encoding="utf-8")

    missing = [p for p in DEFAULT_IMAGES if not p.is_file()]
    if missing:
        print("FAIL: missing images:", *[str(p) for p in missing], sep="\n  ")
        return 1

    health = request.urlopen(f"{BASE}/health", timeout=10).read().decode()
    print("health:", health)

    sid = _create_session()
    scen = ScenarioResult(name="A1-补剂标签12轮追问", session_id=sid)

    paths: list[str] = []
    names: list[str] = []
    for img in DEFAULT_IMAGES:
        ap, an = _upload_attachment(img)
        paths.append(ap)
        names.append(an)
        print(f"uploaded {img.name} -> {an}")

    r1_msg = "我上传了补剂标签，这是什么？对我有什么帮助？"
    print(f"\n=== R1 (2 attachments) ===")
    t1 = _post_chat(sid, r1_msg, attachment_paths=paths, attachment_names=names)
    t1.turn = 1
    scen.turns.append(t1)
    _eval_turn(t1, scen)
    print(_format_turn_line(t1))

    for i, msg in enumerate(FOLLOWUP_MESSAGES, start=2):
        print(f"\n=== R{i} ===")
        tr = _post_chat(sid, msg)
        tr.turn = i
        scen.turns.append(tr)
        _eval_turn(tr, scen)
        print(_format_turn_line(tr))
        if tr.error:
            print("  ERROR:", tr.error)

    _write_report(scen)
    print(f"\nReport written: {REPORT_PATH}")
    print("RESULT:", "PASS" if scen.passed else "FAIL")
    return 0 if scen.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
