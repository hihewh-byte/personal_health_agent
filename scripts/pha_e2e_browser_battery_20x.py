#!/usr/bin/env python3
"""20-session multi-turn E2E battery (API path mirrors browser app.js chat flow).

Each session is an independent conversation (≤20 turns). Results go to JSONL + markdown summary.

Modes:
  Fixed baseline:  python3 scripts/pha_e2e_browser_battery_20x.py
  Dynamic bank:    PHA_E2E_USE_QUESTION_BANK=1 PHA_E2E_BANK_SEED=<int> python3 ...

Run: PHA_PORT=8788 python3 scripts/pha_e2e_browser_battery_20x.py
"""

from __future__ import annotations

import json
import os
import random
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx

from pha.e2e_question_bank import resolve_bank_sessions, write_question_manifest

BASE = f"http://127.0.0.1:{os.environ.get('PHA_PORT', '8788')}"
ASSETS = Path(
    os.environ.get(
        "PHA_JUN11_ASSETS",
        "/Users/hwh/.cursor/projects/Users-hwh-Documents-myAgents/assets",
    ),
)
MODEL = "qwen2.5:7b-instruct"
USER_ID = "default"
TIMEOUT = 600.0
MAX_PER_SESSION = 20
REPORT_DIR = Path(os.environ.get("PHA_E2E_REPORT_DIR", "/tmp/pha-e2e-20x"))
FULL_TABLE_MARK = "根据您上传的 Apple Watch 截图"
FOCUS_MARK = "关于您关心的指标"
EN_FOCUS_MARK = "About the metrics you asked about"


def _metric_focused_answer(tr: TurnRecord) -> bool:
    mode = tr.compare_audit.get("fallback_mode")
    if mode == "metric_focus":
        return True
    ans = tr.answer
    return FOCUS_MARK in ans or EN_FOCUS_MARK in ans
WEAK_CAUTION_MARK = "关于您还需留意的事项"
_WEAK_CLOSE_MARKS = ("不客气", "好的，有需要再问我")
_EXERCISE_ADVICE_RE = re.compile(r"适合.*运动|明天.*运动|运动建议")

JUN11_METRICS = {
    "sleep_time_asleep": "6hr32min",
    "hrv_rmssd_ms": "34",
    "resting_heart_rate_bpm": "63",
    "workout_count_recent": "20",
    "workout_heart_rate_range_bpm": "68-116",
}


@dataclass
class TurnRecord:
    session_id: str
    session_no: int
    session_name: str
    turn: int
    message: str
    elapsed_s: float
    answer: str
    answer_len: int
    metrics: dict[str, str]
    harness_profile: str
    compare_audit: dict[str, Any]
    status_msgs: list[str]
    checks: list[str] = field(default_factory=list)
  # pass = no check failures
    passed: bool = True


@dataclass
class SessionSpec:
    name: str
    turns: list[tuple[str, bool]]  # (message, attach_6panel_on_first_only_if_true)
    checks: list[Callable[[TurnRecord, list[TurnRecord]], list[str]]] = field(default_factory=list)


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


def upload_all(client: httpx.Client) -> tuple[list[str], list[str]]:
    paths, names = [], []
    for p in sorted(ASSETS.glob("IMG_690*.png")):
        with p.open("rb") as fh:
            d = client.post(
                f"{BASE}/api/chat/attachments",
                data={"user_id": USER_ID},
                files={"file": (p.name, fh, "image/png")},
                timeout=120.0,
            ).json()
        paths.append(str(d["attachment_path"]))
        names.append(str(d.get("attachment_name") or p.name))
    return paths, names


def chat_turn(
    client: httpx.Client,
    *,
    message: str,
    session_id: str | None,
    paths: list[str] | None,
    names: list[str] | None,
) -> tuple[str, TurnRecord]:
    body: dict[str, Any] = {
        "user_id": USER_ID,
        "message": message,
        "model": MODEL,
    }
    if session_id:
        body["session_id"] = session_id
    if paths:
        body["attachment_paths"] = paths
        body["attachment_names"] = names or []
        if len(paths) == 1:
            body["attachment_path"] = paths[0]
            body["attachment_name"] = (names or [""])[0]

    t0 = time.time()
    with client.stream("POST", f"{BASE}/api/chat", json=body, timeout=TIMEOUT) as resp:
        resp.raise_for_status()
        raw = "".join(resp.iter_text())
    events = parse_sse(raw)
    done = next((e for e in events if e.get("event") == "done"), {})
    err = next((e for e in events if e.get("event") == "error"), None)
    answer = (done.get("answer") or {}).get("answer_text") or ""
    ingest = done.get("ingest_payload") or {}
    metrics = {
        str(m.get("metric_id")): str(m.get("value"))
        for m in (ingest.get("wearable_metrics") or [])
    }
    sid = str(done.get("session_id") or session_id or "")
    tr = TurnRecord(
        session_id=sid,
        session_no=0,
        session_name="",
        turn=0,
        message=message,
        elapsed_s=round(time.time() - t0, 1),
        answer=answer,
        answer_len=len(answer),
        metrics=metrics,
        harness_profile=str((done.get("harness") or {}).get("profile") or ""),
        compare_audit=done.get("compare_table_audit") or {},
        status_msgs=[
            str(e.get("message") or "")
            for e in events
            if e.get("event") == "status" and e.get("message")
        ],
    )
    if err:
        tr.checks.append(f"api_error:{err.get('message')}")
        tr.passed = False
    return sid, tr


# --- reusable check helpers ---

def only_turns(*turns: int):
    def wrap(fn: Callable[[TurnRecord, list[TurnRecord]], list[str]]):
        def check(tr: TurnRecord, prev: list[TurnRecord]) -> list[str]:
            if tr.turn not in turns:
                return []
            return fn(tr, prev)

        return check

    return wrap


def only_with_upload_metrics(fn: Callable[[TurnRecord, list[TurnRecord]], list[str]]):
    """T1 screenshot metrics only apply when this turn ingested wearable KPIs."""

    def check(tr: TurnRecord, prev: list[TurnRecord]) -> list[str]:
        if tr.turn != 1 or not tr.metrics:
            return []
        return fn(tr, prev)

    return check


def check_t1_jun11_metrics(tr: TurnRecord, _prev: list[TurnRecord]) -> list[str]:
    fails: list[str] = []
    for mid, want in JUN11_METRICS.items():
        got = tr.metrics.get(mid)
        if got != want:
            fails.append(f"metric_{mid}:want={want!r},got={got!r}")
    if re.search(r"8\s*次", tr.answer) and "20" not in tr.answer[:400]:
        fails.append("answer_cites_workout_8_not_20")
    if ("1小时55" in tr.answer or "1hr55" in tr.answer.lower()) and "清醒" not in tr.answer and "awake" not in tr.answer.lower():
        if "6" not in tr.answer[:250]:
            fails.append("answer_sleep_awake_confusion")
    return fails


def check_metric_focus(
    tr: TurnRecord,
    _prev: list[TurnRecord],
    *,
    forbidden: list[str],
    max_len: int = 900,
    expect_fast: bool = True,
) -> list[str]:
    fails: list[str] = []
    focused = _metric_focused_answer(tr)
    if not focused and FULL_TABLE_MARK in tr.answer:
        fails.append("full_compare_instead_of_focus")
    for w in forbidden:
        if w in tr.answer:
            fails.append(f"leaked_metric:{w}")
    if tr.answer_len > max_len:
        fails.append(f"answer_too_long:{tr.answer_len}")
    if expect_fast and tr.elapsed_s > 15 and not focused:
        fails.append(f"slow_non_focus:{tr.elapsed_s}s")
    return fails


def check_correction_sleep(tr: TurnRecord, _prev: list[TurnRecord]) -> list[str]:
    if "核实" not in tr.message and "重新" not in tr.message and "解析" not in tr.message:
        return []
    fails: list[str] = []
    if tr.metrics.get("sleep_time_asleep") and tr.metrics["sleep_time_asleep"] != "6hr32min":
        fails.append(f"sleep_remerge_wrong:{tr.metrics.get('sleep_time_asleep')}")
    if "6" not in tr.answer[:200] and "6hr" not in tr.answer.lower()[:200]:
        fails.append("correction_missing_6h_sleep")
    if tr.answer.count(FULL_TABLE_MARK) > 1:
        fails.append("repeated_full_table_preamble")
    return fails


def check_warehouse_hrv_composer(tr: TurnRecord, _prev: list[TurnRecord]) -> list[str]:
    """Pure warehouse HRV turn-1 should be fast manifest focus or fact_card-style short answer."""
    if tr.turn != 1:
        return []
    fails: list[str] = []
    if tr.harness_profile and "wearable" not in tr.harness_profile and tr.turn == 1:
        pass  # warehouse profile ok
    focused = (
        _metric_focused_answer(tr)
        or (tr.elapsed_s < 5 and tr.answer_len < 500)
    )
    if not focused and tr.elapsed_s > 20:
        fails.append(f"warehouse_hrv_slow_llm:{tr.elapsed_s}s,len={tr.answer_len}")
    if tr.answer_len > 1200 and FOCUS_MARK not in tr.answer:
        fails.append("warehouse_hrv_verbose")
    return fails


def check_deep_sleep_focus(tr: TurnRecord, _prev: list[TurnRecord]) -> list[str]:
    fails: list[str] = []
    if FOCUS_MARK not in tr.answer and "深睡" not in tr.answer:
        fails.append("deep_sleep_focus_missing")
    if tr.elapsed_s > 15:
        fails.append(f"deep_sleep_slow:{tr.elapsed_s}s")
    return fails


def check_episodic_delta_focus(tr: TurnRecord, _prev: list[TurnRecord]) -> list[str]:
    fails: list[str] = []
    if FOCUS_MARK not in tr.answer and "近 90 天" not in tr.answer:
        fails.append("delta_focus_missing")
    if tr.elapsed_s > 15:
        fails.append(f"delta_slow:{tr.elapsed_s}s")
    return fails


def check_exercise_advice_focus(tr: TurnRecord, _prev: list[TurnRecord]) -> list[str]:
    fails: list[str] = []
    if FULL_TABLE_MARK in tr.answer:
        fails.append("exercise_reintroduced_full_table")
    if "运动建议" not in tr.answer and "低至中等强度" not in tr.answer:
        if tr.elapsed_s > 15:
            fails.append(f"exercise_advice_slow:{tr.elapsed_s}s")
    return fails


def check_no_repeat_preamble(tr: TurnRecord, prev: list[TurnRecord]) -> list[str]:
    if len(prev) < 2:
        return []
    if _EXERCISE_ADVICE_RE.search(tr.message):
        return []
    count = tr.answer.count(FULL_TABLE_MARK)
    if count > 1:
        return [f"repeat_preamble_x{count}"]
    prior_had = any(FULL_TABLE_MARK in p.answer for p in prev)
    if prior_had and count == 1 and FOCUS_MARK not in tr.answer and tr.turn > 2:
        return ["reintroduced_full_table_on_followup"]
    return []


def check_weak_followup_skip(tr: TurnRecord, _prev: list[TurnRecord]) -> list[str]:
    """Weak / close follow-ups must skip full-table LLM re-dump."""
    fails: list[str] = []
    if FULL_TABLE_MARK in tr.answer:
        fails.append("weak_followup_full_table")
    if tr.elapsed_s > 10 and not any(m in tr.answer for m in _WEAK_CLOSE_MARKS + (WEAK_CAUTION_MARK,)):
        fails.append(f"weak_followup_slow:{tr.elapsed_s}s")
    return fails


def build_check_from_spec(spec: dict[str, Any]) -> Callable[[TurnRecord, list[TurnRecord]], list[str]]:
    check_id = str(spec.get("id") or "")
    turns = spec.get("turns")
    forbidden = list(spec.get("forbidden") or [])
    max_len = int(spec.get("max_len") or 900)
    expect_fast = bool(spec.get("expect_fast", True))

    def _wrap(fn: Callable[[TurnRecord, list[TurnRecord]], list[str]]):
        if turns:
            return only_turns(*turns)(fn)
        return fn

    if check_id == "jun11_metrics":
        return only_with_upload_metrics(check_t1_jun11_metrics)
    if check_id == "no_repeat":
        return _wrap(check_no_repeat_preamble)
    if check_id == "warehouse_hrv":
        return check_warehouse_hrv_composer
    if check_id == "correction_sleep":
        return check_correction_sleep
    if check_id == "deep_sleep":
        return _wrap(check_deep_sleep_focus)
    if check_id == "episodic_delta":
        return _wrap(check_episodic_delta_focus)
    if check_id == "exercise_advice":
        return _wrap(check_exercise_advice_focus)
    if check_id == "weak_followup_skip":
        return _wrap(check_weak_followup_skip)
    if check_id == "metric_focus":
        return _wrap(
            lambda tr, prev: check_metric_focus(
                tr,
                prev,
                forbidden=forbidden,
                max_len=max_len,
                expect_fast=expect_fast,
            ),
        )
    return lambda _tr, _prev: []


def build_sessions_from_bank(seed: int | None = None) -> tuple[list[SessionSpec], dict[str, Any]]:
    resolved, manifest = resolve_bank_sessions(seed=seed)
    sessions: list[SessionSpec] = []
    for rs in resolved:
        turns = [(t.message, t.attach) for t in rs.turns]
        checks = [build_check_from_spec(c) for c in rs.checks]
        sessions.append(SessionSpec(name=rs.session_name, turns=turns, checks=checks))
    return sessions, manifest


def build_sessions() -> list[SessionSpec]:
    t1 = (
        "附件是我今天的一些身体指标情况，需要说明的是上午有一个workout是阻力训练，"
        "我想知道明天是否适合运动，如果适合，请建议运动类型。"
    )
    return [
        SessionSpec(
            "S01_jun11_baseline",
            [
                (t1, True),
                ("血脂怎么样", False),
                ("HRV 怎么样", False),
                ("请核实今天的睡眠数据", False),
                ("锻炼次数8次从哪来", False),
                ("最近步数", False),
            ],
            [
                only_with_upload_metrics(check_t1_jun11_metrics),
                only_turns(3)(
                    lambda tr, prev: check_metric_focus(
                        tr, prev, forbidden=["睡眠总时长", "呼吸率", "锻炼心率"],
                    ),
                ),
                only_turns(4)(check_correction_sleep),
                check_no_repeat_preamble,
            ],
        ),
        SessionSpec(
            "S02_exercise_only",
            [(t1, True), ("那后天呢", False), ("推荐低强度有氧吗", False)],
            [only_with_upload_metrics(check_t1_jun11_metrics)],
        ),
        SessionSpec(
            "S03_lipid_clarify",
            [
                (t1, True),
                ("血脂怎么样", False),
                ("2023年", False),
            ],
            [only_with_upload_metrics(check_t1_jun11_metrics)],
        ),
        SessionSpec(
            "S04_hrv_chain",
            [
                (t1, True),
                ("HRV 怎么样", False),
                ("HRV 正常吗", False),
                ("和上周比呢", False),
            ],
            [
                only_with_upload_metrics(check_t1_jun11_metrics),
                only_turns(2, 3)(
                    lambda tr, prev: check_metric_focus(
                        tr, prev, forbidden=["睡眠总时长", "步数"],
                    ),
                ),
                only_turns(4)(check_episodic_delta_focus),
            ],
        ),
        SessionSpec(
            "S05_sleep_correction",
            [
                (t1, True),
                ("睡眠时长多少", False),
                ("请核实今天的睡眠数据，明显不对请重新分析", False),
                ("深睡多久", False),
            ],
            [
                only_with_upload_metrics(check_t1_jun11_metrics),
                only_turns(3)(check_correction_sleep),
                only_turns(4)(check_deep_sleep_focus),
            ],
        ),
        SessionSpec(
            "S06_workout_origin",
            [
                (t1, True),
                ("锻炼次数8次从哪来", False),
                ("最近4周运动了几天", False),
            ],
            [only_with_upload_metrics(check_t1_jun11_metrics)],
        ),
        SessionSpec(
            "S07_warehouse_hrv",
            [
                ("我最近的 HRV 怎么样？", False),
                ("睡眠呢", False),
                ("步数呢", False),
            ],
            [check_warehouse_hrv_composer],
        ),
        SessionSpec(
            "S08_warehouse_steps",
            [
                ("最近步数", False),
                ("平均每天多少步", False),
            ],
            [],
        ),
        SessionSpec(
            "S09_respiratory_focus",
            [
                (t1, True),
                ("呼吸率怎么样", False),
                ("呼吸率正常吗", False),
            ],
            [
                only_with_upload_metrics(check_t1_jun11_metrics),
                only_turns(2, 3)(
                    lambda tr, prev: check_metric_focus(
                        tr, prev, forbidden=["HRV", "血脂"], max_len=1000, expect_fast=False
                    ),
                ),
            ],
        ),
        SessionSpec(
            "S10_resting_hr",
            [
                (t1, True),
                ("静息心率多少", False),
                ("心率范围呢", False),
            ],
            [only_with_upload_metrics(check_t1_jun11_metrics)],
        ),
        SessionSpec(
            "S11_spo2",
            [
                (t1, True),
                ("血氧怎么样", False),
            ],
            [only_with_upload_metrics(check_t1_jun11_metrics)],
        ),
        SessionSpec(
            "S12_remerge_no_reupload",
            [
                (t1, True),
                ("能不能再次解析睡眠的截图的数据？需要我再次上传吗？", False),
                ("请重新分析截图里的锻炼数据", False),
            ],
            [only_with_upload_metrics(check_t1_jun11_metrics), check_correction_sleep],
        ),
        SessionSpec(
            "S13_casual_drift",
            [
                (t1, True),
                ("谢谢", False),
                ("还有什么要注意的", False),
                ("好的", False),
            ],
            [only_with_upload_metrics(check_t1_jun11_metrics), check_no_repeat_preamble],
        ),
        SessionSpec(
            "S14_long_conversation",
            [
                (t1, True),
                ("HRV 怎么样", False),
                ("睡眠呢", False),
                ("步数呢", False),
                ("血脂怎么样", False),
                ("明天适合运动吗", False),
                ("静息心率", False),
                ("血氧", False),
                ("呼吸率", False),
            ],
            [
                only_with_upload_metrics(check_t1_jun11_metrics),
                only_turns(2, 3, 4, 5, 6, 7, 8, 9)(check_no_repeat_preamble),
                only_turns(6)(check_exercise_advice_focus),
            ],
        ),
        SessionSpec(
            "S15_warehouse_lipid",
            [
                ("血脂怎么样", False),
                ("2025年", False),
            ],
            [],
        ),
        SessionSpec(
            "S16_warehouse_then_upload",
            [
                ("最近步数", False),
                (t1, True),
                ("结合截图和数仓，HRV 怎么样", False),
            ],
            [only_with_upload_metrics(check_t1_jun11_metrics)],
        ),
        SessionSpec(
            "S17_heart_rate_generic",
            [
                (t1, True),
                ("心率怎么样", False),
            ],
            [only_with_upload_metrics(check_t1_jun11_metrics)],
        ),
        SessionSpec(
            "S18_running_advice",
            [
                (t1, True),
                ("明天能跑步吗", False),
                ("跑多久合适", False),
            ],
            [only_with_upload_metrics(check_t1_jun11_metrics)],
        ),
        SessionSpec(
            "S19_summary_request",
            [
                (t1, True),
                ("总结一下我的健康数据", False),
            ],
            [only_with_upload_metrics(check_t1_jun11_metrics)],
        ),
        SessionSpec(
            "S20_rapid_fire",
            [
                (t1, True),
                ("HRV", False),
                ("睡眠", False),
                ("步数", False),
                ("锻炼", False),
                ("血脂", False),
            ],
            [only_with_upload_metrics(check_t1_jun11_metrics), check_no_repeat_preamble],
        ),
    ]


def run_session(
    client: httpx.Client,
    session_no: int,
    spec: SessionSpec,
    paths: list[str],
    names: list[str],
) -> list[TurnRecord]:
    records: list[TurnRecord] = []
    sid: str | None = None
    for turn_i, (msg, attach) in enumerate(spec.turns[:MAX_PER_SESSION], start=1):
        sid, tr = chat_turn(
            client,
            message=msg,
            session_id=sid,
            paths=paths if attach else None,
            names=names if attach else None,
        )
        tr.session_no = session_no
        tr.session_name = spec.name
        tr.turn = turn_i
        for chk in spec.checks:
            fails = chk(tr, records)
            if fails:
                tr.checks.extend(fails)
                tr.passed = False
        records.append(tr)
        line = (
            f"[{spec.name} T{turn_i}] {tr.elapsed_s}s pass={tr.passed} "
            f"profile={tr.harness_profile} audit={tr.compare_audit.get('fallback_mode')} "
            f"len={tr.answer_len}"
        )
        print(line, flush=True)
        if tr.checks:
            print("  checks:", tr.checks, flush=True)
        print("  head:", tr.answer[:180].replace("\n", " "), flush=True)
    return records


def write_reports(
    all_records: list[TurnRecord],
    sessions: list[SessionSpec],
    *,
    jsonl_path: Path | None = None,
    run_meta: dict[str, Any] | None = None,
    manifest_path: Path | None = None,
) -> tuple[Path, Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if jsonl_path is None:
        jsonl_path = REPORT_DIR / f"battery_20x_{ts}.jsonl"
        with jsonl_path.open("w", encoding="utf-8") as fh:
            for r in all_records:
                fh.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")
    md_path = REPORT_DIR / f"battery_20x_{ts}.md"

    total_turns = len(all_records)
    failed_turns = [r for r in all_records if not r.passed]
    failed_sessions = sorted({r.session_name for r in failed_turns})
    slow_turns = [r for r in all_records if r.elapsed_s > 30]

    meta = run_meta or {}
    mode = str(meta.get("mode") or "fixed")
    lines = [
        f"# PHA 20-Session E2E Battery Report",
        f"",
        f"- **Time (UTC)**: {ts}",
        f"- **Mode**: `{mode}`",
        f"- **Endpoint**: `{BASE}`",
        f"- **Model**: `{MODEL}`",
    ]
    if mode == "question_bank":
        lines.append(f"- **Bank seed**: `{meta.get('bank_seed')}`")
        if manifest_path:
            lines.append(f"- **Question manifest**: `{manifest_path}`")
    lines.extend(
        [
            f"- **Sessions**: {len(sessions)}",
            f"- **Total turns**: {total_turns}",
            f"- **Failed turns**: {len(failed_turns)}",
            f"- **Failed sessions**: {len(failed_sessions)}",
            f"",
            f"## Session summary",
            f"",
            f"| Session | Turns | Fail turns | Max elapsed |",
            f"|---------|-------|------------|-------------|",
        ],
    )
    for spec in sessions:
        recs = [r for r in all_records if r.session_name == spec.name]
        fail_n = sum(1 for r in recs if not r.passed)
        max_el = max((r.elapsed_s for r in recs), default=0)
        lines.append(f"| {spec.name} | {len(recs)} | {fail_n} | {max_el}s |")

    if manifest_path and manifest_path.is_file():
        lines.extend(["", "## Question manifest", "", f"See `{manifest_path}`", ""])

    lines.extend(["", "## Failure details", ""])
    if not failed_turns:
        lines.append("_No automated check failures._")
    else:
        for r in failed_turns:
            lines.append(f"- **{r.session_name} T{r.turn}** ({r.elapsed_s}s): `{r.message[:50]}`")
            for c in r.checks:
                lines.append(f"  - {c}")

    lines.extend(["", "## Slow turns (>30s)", ""])
    for r in sorted(slow_turns, key=lambda x: -x.elapsed_s)[:15]:
        lines.append(f"- {r.session_name} T{r.turn}: {r.elapsed_s}s — {r.message[:40]}")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return jsonl_path, md_path


def main() -> int:
    use_bank = (os.environ.get("PHA_E2E_USE_QUESTION_BANK") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    manifest: dict[str, Any] = {}
    manifest_path: Path | None = None
    run_meta: dict[str, Any] = {"mode": "question_bank" if use_bank else "fixed"}

    if use_bank:
        seed_raw = (os.environ.get("PHA_E2E_BANK_SEED") or "").strip()
        seed = int(seed_raw) if seed_raw else random.randint(0, 2**31 - 1)
        run_meta["bank_seed"] = seed
        sessions, manifest = build_sessions_from_bank(seed=seed)
        print(f"question_bank: seed={seed} sets={len(sessions)}", flush=True)
    else:
        sessions = build_sessions()
    filter_names = os.environ.get("PHA_E2E_SESSIONS", "").strip()
    if filter_names:
        want = [x.strip() for x in filter_names.split(",") if x.strip()]
        sessions = [
            s
            for s in sessions
            if any(s.name == w or s.name.startswith(f"{w}_") for w in want)
        ]
    if not sessions:
        print("FAIL no sessions to run")
        return 1
    if not filter_names and len(sessions) != 20:
        print(f"FAIL expected 20 sessions, got {len(sessions)}")
        return 1

    imgs = sorted(ASSETS.glob("IMG_690*.png"))
    if len(imgs) < 6:
        print("FAIL missing IMG_690*.png in", ASSETS)
        return 1

    health = httpx.get(f"{BASE}/health", timeout=10.0).json()
    print("health:", health, flush=True)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    prefix = "battery_bank_20x" if use_bank else "battery_20x"
    jsonl_path = REPORT_DIR / f"{prefix}_{ts}.jsonl"

    if use_bank:
        manifest_path = write_question_manifest(manifest, REPORT_DIR)
        print("question_manifest:", manifest_path, flush=True)

    all_records: list[TurnRecord] = []
    t0 = time.time()
    with httpx.Client() as client:
        paths, names = upload_all(client)
        print(f"uploaded {len(paths)} images", flush=True)
        for i, spec in enumerate(sessions, start=1):
            print(f"\n========== Session {i}/20: {spec.name} ==========", flush=True)
            recs = run_session(client, i, spec, paths, names)
            all_records.extend(recs)
            with jsonl_path.open("a", encoding="utf-8") as fh:
                for r in recs:
                    fh.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")

    _, md_path = write_reports(
        all_records,
        sessions,
        jsonl_path=jsonl_path,
        run_meta=run_meta,
        manifest_path=manifest_path,
    )
    elapsed = round(time.time() - t0, 1)
    fail_n = sum(1 for r in all_records if not r.passed)
    print(f"\nDONE sessions={len(sessions)} turns={len(all_records)} fails={fail_n} wall={elapsed}s", flush=True)
    print("jsonl:", jsonl_path, flush=True)
    print("md:", md_path, flush=True)
    return 1 if fail_n else 0


if __name__ == "__main__":
    raise SystemExit(main())
