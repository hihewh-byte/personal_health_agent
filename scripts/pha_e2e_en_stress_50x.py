#!/usr/bin/env python3
"""50-session English multi-turn E2E stress battery (≥8 turns each).

Uses rules/e2e_question_bank_en_v1.json, forces response_locale=en, and exercises
wearable screenshots (IMG_690*), optional lab image (IMG_0313*), plus warehouse
queries against previously ingested PHA data.

Run:
  PHA_PORT=8788 python3 scripts/pha_e2e_en_stress_50x.py

Optional:
  PHA_E2E_BANK_SEED=<int>
  PHA_E2E_REPORT_DIR=/tmp/pha-e2e-en-50x
  PHA_E2E_SESSIONS=EN01,EN02   # subset filter
  PHA_E2E_MODEL=qwen2.5:7b-instruct
  PHA_E2E_MAX_SESSIONS=50
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

from pha.e2e_question_bank import load_bank, resolve_bank_sessions, write_question_manifest

BASE = f"http://127.0.0.1:{os.environ.get('PHA_PORT', '8788')}"
ASSETS = Path(
    os.environ.get(
        "PHA_JUN11_ASSETS",
        "/Users/hwh/.cursor/projects/Users-hwh-Documents-myAgents/assets",
    ),
)
ATTACH_DIR = ROOT / "storage" / "attachments" / "default"
BANK_PATH = ROOT / "rules" / "e2e_question_bank_en_v1.json"
MODEL = os.environ.get("PHA_E2E_MODEL", "qwen2.5:7b-instruct")
USER_ID = os.environ.get("PHA_E2E_USER_ID", "default")
TIMEOUT = float(os.environ.get("PHA_E2E_TIMEOUT", "600"))
MAX_PER_SESSION = 20
EXPECTED_SESSIONS = int(os.environ.get("PHA_E2E_MAX_SESSIONS", "50"))
REPORT_DIR = Path(os.environ.get("PHA_E2E_REPORT_DIR", "/tmp/pha-e2e-en-50x"))
RESPONSE_LOCALE = "en"

FULL_TABLE_MARK_ZH = "根据您上传的 Apple Watch 截图"
FULL_TABLE_MARK_EN = "Based on your uploaded Apple Watch"
FOCUS_MARK_ZH = "关于您关心的指标"
FOCUS_MARK_EN = "About the metric"
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

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
    attach_kind: str = ""
    checks: list[str] = field(default_factory=list)
    passed: bool = True


@dataclass
class SessionSpec:
    name: str
    turns: list[tuple[str, bool, str]]  # message, attach, attach_kind
    checks: list[Callable[[TurnRecord, list[TurnRecord]], list[str]]] = field(default_factory=list)
    lane: str = ""


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


def upload_files(client: httpx.Client, paths: list[Path]) -> tuple[list[str], list[str]]:
    stored: list[str] = []
    names: list[str] = []
    for p in paths:
        with p.open("rb") as fh:
            resp = client.post(
                f"{BASE}/api/chat/attachments",
                data={"user_id": USER_ID},
                files={"file": (p.name, fh, "image/png")},
                timeout=120.0,
            )
        resp.raise_for_status()
        data = resp.json()
        stored.append(str(data["attachment_path"]))
        names.append(str(data.get("attachment_name") or p.name))
    return stored, names


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
        "response_locale": RESPONSE_LOCALE,
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


def only_turns(*turns: int):
    def wrap(fn: Callable[[TurnRecord, list[TurnRecord]], list[str]]):
        def check(tr: TurnRecord, prev: list[TurnRecord]) -> list[str]:
            if tr.turn not in turns:
                return []
            return fn(tr, prev)

        return check

    return wrap


def only_with_upload_metrics(fn: Callable[[TurnRecord, list[TurnRecord]], list[str]]):
    def check(tr: TurnRecord, prev: list[TurnRecord]) -> list[str]:
        if tr.turn != 1 or not tr.metrics:
            # allow attach on later turns (lab_then_wearable)
            if not tr.metrics or tr.attach_kind != "wearable":
                return []
        return fn(tr, prev)

    return check


def check_no_empty(tr: TurnRecord, _prev: list[TurnRecord]) -> list[str]:
    if tr.answer_len < 8 and not any("api_error" in c for c in tr.checks):
        return ["empty_or_too_short_answer"]
    return []


def check_english_reply(tr: TurnRecord, _prev: list[TurnRecord]) -> list[str]:
    if not tr.answer:
        return []
    cjk = len(_CJK_RE.findall(tr.answer))
    ratio = cjk / max(len(tr.answer), 1)
    if ratio > 0.12:
        return [f"non_english_cjk_ratio:{ratio:.2f}"]
    return []


def check_jun11_metrics(tr: TurnRecord, _prev: list[TurnRecord]) -> list[str]:
    fails: list[str] = []
    for mid, want in JUN11_METRICS.items():
        got = tr.metrics.get(mid)
        if got != want:
            fails.append(f"metric_{mid}:want={want!r},got={got!r}")
    return fails


def check_correction_sleep(tr: TurnRecord, _prev: list[TurnRecord]) -> list[str]:
    msg = tr.message.lower()
    if "verify" not in msg and "re-check" not in msg and "re-parse" not in msg and "wrong" not in msg:
        return []
    fails: list[str] = []
    low = tr.answer.lower()
    if "6" not in tr.answer[:250] and "6hr" not in low[:250] and "6 hr" not in low[:250]:
        fails.append("correction_missing_6h_sleep_en")
    return fails


def check_warehouse_hrv(tr: TurnRecord, _prev: list[TurnRecord]) -> list[str]:
    if tr.turn != 1:
        return []
    fails: list[str] = []
    if tr.answer_len > 2500:
        fails.append(f"warehouse_hrv_verbose:{tr.answer_len}")
    return fails


def check_weak_followup_skip(tr: TurnRecord, _prev: list[TurnRecord]) -> list[str]:
    msg = tr.message.lower().strip()
    weak = {"thanks", "thank you.", "ok", "ok.", "got it", "understood", "understood.", "noted", "noted.", "yep", "cool, thanks"}
    if msg not in weak and "thanks" not in msg:
        return []
    fails: list[str] = []
    if FULL_TABLE_MARK_ZH in tr.answer or FULL_TABLE_MARK_EN in tr.answer:
        fails.append("weak_followup_full_table")
    if tr.elapsed_s > 45 and tr.answer_len > 1200:
        fails.append(f"weak_followup_heavy:{tr.elapsed_s}s,len={tr.answer_len}")
    return fails


def check_no_repeat(tr: TurnRecord, prev: list[TurnRecord]) -> list[str]:
    marks = (FULL_TABLE_MARK_ZH, FULL_TABLE_MARK_EN)
    count = sum(tr.answer.count(m) for m in marks)
    if count > 1:
        return [f"repeat_preamble_x{count}"]
    prior_had = any(any(m in p.answer for m in marks) for p in prev)
    if prior_had and count == 1 and tr.turn > 2:
        focused = FOCUS_MARK_ZH in tr.answer or FOCUS_MARK_EN in tr.answer
        if not focused:
            return ["reintroduced_full_table_on_followup"]
    return []


def check_lab_attach(tr: TurnRecord, _prev: list[TurnRecord]) -> list[str]:
    if tr.attach_kind != "lab":
        return []
    if tr.answer_len < 20:
        return ["lab_attach_empty_answer"]
    return []


def build_check_from_spec(spec: dict[str, Any]) -> Callable[[TurnRecord, list[TurnRecord]], list[str]]:
    check_id = str(spec.get("id") or "")
    turns = spec.get("turns")

    def _wrap(fn: Callable[[TurnRecord, list[TurnRecord]], list[str]]):
        if turns:
            return only_turns(*turns)(fn)
        return fn

    if check_id == "jun11_metrics":
        return only_with_upload_metrics(check_jun11_metrics)
    if check_id == "english_reply":
        return check_english_reply
    if check_id == "no_empty":
        return check_no_empty
    if check_id == "no_repeat":
        return _wrap(check_no_repeat)
    if check_id == "warehouse_hrv":
        return check_warehouse_hrv
    if check_id == "correction_sleep":
        return check_correction_sleep
    if check_id == "weak_followup_skip":
        return _wrap(check_weak_followup_skip)
    if check_id == "lab_attach":
        return check_lab_attach
    # soft-ignore Chinese-only check ids
    return lambda _tr, _prev: []


def attach_kind_for_slot(slot: str) -> str:
    if slot == "upload_lab_image":
        return "lab"
    if slot == "upload_exercise":
        return "wearable"
    return "wearable"


def build_sessions(seed: int) -> tuple[list[SessionSpec], dict[str, Any]]:
    bank = load_bank(BANK_PATH)
    resolved, manifest = resolve_bank_sessions(bank=bank, seed=seed)
    sessions: list[SessionSpec] = []
    for rs in resolved:
        turns: list[tuple[str, bool, str]] = []
        for t in rs.turns:
            kind = attach_kind_for_slot(t.slot) if t.attach else ""
            turns.append((t.message, t.attach, kind))
        checks = [build_check_from_spec(c) for c in rs.checks]
        sessions.append(SessionSpec(name=rs.session_name, turns=turns, checks=checks, lane=rs.lane))
    return sessions, manifest


def resolve_asset_bundles() -> dict[str, tuple[list[Path], str]]:
    wearable = sorted(ASSETS.glob("IMG_690*.png"))
    lab_candidates = sorted(ASSETS.glob("IMG_0313*"))
    if not lab_candidates:
        lab_candidates = sorted(ATTACH_DIR.glob("IMG_0313*"))
    if not lab_candidates:
        # fallback: any non-690 panel already in PHA attachments
        lab_candidates = sorted(ATTACH_DIR.glob("IMG_0313*")) or sorted(ATTACH_DIR.glob("*0313*"))
    return {
        "wearable": (wearable, "jun11_six_panel"),
        "lab": (lab_candidates[:1], "lab_image"),
    }


def run_session(
    client: httpx.Client,
    session_no: int,
    spec: SessionSpec,
    uploaded: dict[str, tuple[list[str], list[str]]],
) -> list[TurnRecord]:
    records: list[TurnRecord] = []
    sid: str | None = None
    for turn_i, (msg, attach, kind) in enumerate(spec.turns[:MAX_PER_SESSION], start=1):
        paths = names = None
        if attach:
            bundle = uploaded.get(kind or "wearable") or uploaded["wearable"]
            paths, names = bundle
        sid, tr = chat_turn(
            client,
            message=msg,
            session_id=sid,
            paths=paths,
            names=names,
        )
        tr.session_no = session_no
        tr.session_name = spec.name
        tr.turn = turn_i
        tr.attach_kind = kind if attach else ""
        for chk in spec.checks:
            fails = chk(tr, records)
            if fails:
                tr.checks.extend(fails)
                tr.passed = False
        # always enforce English + non-empty baseline
        for baseline in (check_english_reply, check_no_empty):
            fails = baseline(tr, records)
            for f in fails:
                if f not in tr.checks:
                    tr.checks.append(f)
                    tr.passed = False
        records.append(tr)
        print(
            f"[{spec.name} T{turn_i}] {tr.elapsed_s}s pass={tr.passed} "
            f"profile={tr.harness_profile} len={tr.answer_len} attach={tr.attach_kind or '-'}",
            flush=True,
        )
        if tr.checks:
            print("  checks:", tr.checks, flush=True)
        print("  head:", tr.answer[:160].replace("\n", " "), flush=True)
    return records


def write_reports(
    all_records: list[TurnRecord],
    sessions: list[SessionSpec],
    *,
    jsonl_path: Path,
    run_meta: dict[str, Any],
    manifest_path: Path | None,
    plan_path: Path,
) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    md_path = REPORT_DIR / f"en_stress_50x_{ts}.md"
    total_turns = len(all_records)
    failed_turns = [r for r in all_records if not r.passed]
    failed_sessions = sorted({r.session_name for r in failed_turns})
    slow_turns = [r for r in all_records if r.elapsed_s > 30]
    cjk_fails = [r for r in failed_turns if any("non_english" in c for c in r.checks)]
    api_fails = [r for r in failed_turns if any(c.startswith("api_error") for c in r.checks)]
    metric_fails = [r for r in failed_turns if any(c.startswith("metric_") for c in r.checks)]

    lane_stats: dict[str, dict[str, int]] = {}
    for spec in sessions:
        recs = [r for r in all_records if r.session_name == spec.name]
        lane_stats[spec.lane or spec.name] = {
            "turns": len(recs),
            "fails": sum(1 for r in recs if not r.passed),
            "max_s": int(max((r.elapsed_s for r in recs), default=0)),
        }

    lines = [
        "# PHA English Stress Battery — 50×≥8 Report",
        "",
        f"- **Time (UTC)**: {ts}",
        f"- **Endpoint**: `{BASE}`",
        f"- **Model**: `{MODEL}`",
        f"- **Locale**: `{RESPONSE_LOCALE}`",
        f"- **Bank**: `{BANK_PATH.name}` seed=`{run_meta.get('bank_seed')}`",
        f"- **Plan**: `{plan_path}`",
        f"- **Sessions**: {len(sessions)}",
        f"- **Total turns**: {total_turns}",
        f"- **Wall clock (s)**: {run_meta.get('wall_s')}",
        f"- **Failed turns**: {len(failed_turns)}",
        f"- **Failed sessions**: {len(failed_sessions)}",
        f"- **API errors**: {len(api_fails)}",
        f"- **Non-English fails**: {len(cjk_fails)}",
        f"- **Metric fails**: {len(metric_fails)}",
        "",
        "## Pass criteria",
        "",
        "- Every session ≥8 English turns against live PHA.",
        "- Materials: Jun11 wearable panels, optional lab image, warehouse lipids/wearables/prior samples.",
        "- Checks: non-empty answer, English (CJK ratio ≤12%), optional jun11 metric fidelity on wearable ingest.",
        "",
        "## Session summary",
        "",
        "| Session | Lane | Turns | Fail | Max s |",
        "|---------|------|-------|------|-------|",
    ]
    for spec in sessions:
        recs = [r for r in all_records if r.session_name == spec.name]
        fail_n = sum(1 for r in recs if not r.passed)
        max_el = max((r.elapsed_s for r in recs), default=0)
        lines.append(f"| {spec.name} | {spec.lane} | {len(recs)} | {fail_n} | {max_el}s |")

    lines.extend(["", "## Lane rollup", "", "| Lane | Turns | Fails | Max s |", "|------|-------|-------|-------|"])
    for lane, st in sorted(lane_stats.items()):
        lines.append(f"| {lane} | {st['turns']} | {st['fails']} | {st['max_s']}s |")

    lines.extend(["", "## Failure details", ""])
    if not failed_turns:
        lines.append("_No automated check failures._")
    else:
        for r in failed_turns[:80]:
            lines.append(f"- **{r.session_name} T{r.turn}** ({r.elapsed_s}s): `{r.message[:60]}`")
            for c in r.checks:
                lines.append(f"  - {c}")
        if len(failed_turns) > 80:
            lines.append(f"- … truncated {len(failed_turns) - 80} more failures")

    lines.extend(["", "## Slow turns (>30s, top 25)", ""])
    for r in sorted(slow_turns, key=lambda x: -x.elapsed_s)[:25]:
        lines.append(f"- {r.session_name} T{r.turn}: {r.elapsed_s}s — {r.message[:50]}")

    if manifest_path:
        lines.extend(["", "## Question manifest", "", f"See `{manifest_path}`", ""])

    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            f"- JSONL: `{jsonl_path}`",
            f"- Markdown: `{md_path}`",
            "",
        ],
    )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path


def write_plan(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "# PHA English Stress Plan — 50 sessions × ≥8 turns",
                "",
                "## Goals",
                "- Full-English multi-turn stress of live PHA (response_locale=en).",
                "- 50 independent sessions; each ≥8 turns.",
                "- Materials: IMG_690* wearable panels, IMG_0313 lab/report image if present,",
                "  warehouse lipids/wearables, and previously ingested PHA samples (PDF/lab via warehouse).",
                "",
                "## Matrix",
                "| Block | Sets | Focus |",
                "|-------|------|-------|",
                "| EN01–EN20 | 20 | English mirrors of classic upload/warehouse lanes |",
                "| EN21–EN35 | 15 | Warehouse tour, PDF/lab, body-age, supplements, rapid |",
                "| EN36–EN50 | 15 | Combined review, locale lock, mixed assets, finale |",
                "",
                "## Execution",
                "```bash",
                "python3 scripts/seed_e2e_question_bank_en_v1.py",
                "PHA_PORT=8788 PHA_E2E_BANK_SEED=20260711 \\",
                "  python3 scripts/pha_e2e_en_stress_50x.py",
                "```",
                "",
                "## Pass / Fail",
                "- Fail turn: API error, empty answer, CJK ratio >12%, wearable metric mismatch when ingest fires.",
                "- Session fail if any turn fails.",
                "",
            ],
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    if not BANK_PATH.is_file():
        print(f"FAIL missing bank {BANK_PATH}; run scripts/seed_e2e_question_bank_en_v1.py")
        return 1

    seed_raw = (os.environ.get("PHA_E2E_BANK_SEED") or "").strip()
    seed = int(seed_raw) if seed_raw else random.randint(0, 2**31 - 1)
    sessions, manifest = build_sessions(seed)
    filter_names = os.environ.get("PHA_E2E_SESSIONS", "").strip()
    if filter_names:
        want = [x.strip() for x in filter_names.split(",") if x.strip()]
        sessions = [
            s
            for s in sessions
            if any(s.name == w or s.name.startswith(f"{w}_") or s.name.startswith(w) for w in want)
        ]
    if not sessions:
        print("FAIL no sessions")
        return 1
    if not filter_names and len(sessions) != EXPECTED_SESSIONS:
        print(f"FAIL expected {EXPECTED_SESSIONS} sessions, got {len(sessions)}")
        return 1

    bundles = resolve_asset_bundles()
    wearable_paths = bundles["wearable"][0]
    if len(wearable_paths) < 6:
        print("FAIL missing IMG_690*.png in", ASSETS)
        return 1

    health = httpx.get(f"{BASE}/health", timeout=10.0).json()
    print("health:", health, flush=True)
    print(f"bank={BANK_PATH.name} seed={seed} sessions={len(sessions)} model={MODEL}", flush=True)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    plan_path = REPORT_DIR / f"plan_en_stress_50x_{ts}.md"
    write_plan(plan_path)
    jsonl_path = REPORT_DIR / f"en_stress_50x_{ts}.jsonl"
    manifest_path = write_question_manifest(manifest, REPORT_DIR)
    print("plan:", plan_path, flush=True)
    print("question_manifest:", manifest_path, flush=True)

    all_records: list[TurnRecord] = []
    t0 = time.time()
    with httpx.Client() as client:
        uploaded: dict[str, tuple[list[str], list[str]]] = {}
        w_paths, w_names = upload_files(client, wearable_paths)
        uploaded["wearable"] = (w_paths, w_names)
        print(f"uploaded wearable panels: {len(w_paths)}", flush=True)
        lab_files = bundles["lab"][0]
        if lab_files:
            l_paths, l_names = upload_files(client, lab_files)
            uploaded["lab"] = (l_paths, l_names)
            print(f"uploaded lab image: {l_names}", flush=True)
        else:
            uploaded["lab"] = uploaded["wearable"]
            print("WARN no lab image found; lab slots fall back to wearable panels", flush=True)

        for i, spec in enumerate(sessions, start=1):
            print(f"\n========== Session {i}/{len(sessions)}: {spec.name} ==========", flush=True)
            recs = run_session(client, i, spec, uploaded)
            all_records.extend(recs)
            with jsonl_path.open("a", encoding="utf-8") as fh:
                for r in recs:
                    fh.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")

    wall = round(time.time() - t0, 1)
    md_path = write_reports(
        all_records,
        sessions,
        jsonl_path=jsonl_path,
        run_meta={"bank_seed": seed, "wall_s": wall},
        manifest_path=manifest_path,
        plan_path=plan_path,
    )
    fail_n = sum(1 for r in all_records if not r.passed)
    print(
        f"\nDONE sessions={len(sessions)} turns={len(all_records)} fails={fail_n} wall={wall}s",
        flush=True,
    )
    print("jsonl:", jsonl_path, flush=True)
    print("md:", md_path, flush=True)
    return 1 if fail_n else 0


if __name__ == "__main__":
    raise SystemExit(main())
