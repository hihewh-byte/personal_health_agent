#!/usr/bin/env python3
"""Bilingual PHA live stress battery — 50 EN + 50 ZH multi-turn sessions.

Pre-generates random question-bank seeds, runs both batteries against a live PHA
server, scores reply quality, and optionally feeds failures into Loop harvest.

Prerequisites:
  - PHA server running: PYTHONPATH=. python -m pha.main  (default :8788)
  - Ollama with PHA_E2E_MODEL (default qwen2.5:7b-instruct)
  - Local assets: IMG_690*.png under PHA_JUN11_ASSETS (see EN stress script)
  - Prior ingested warehouse data recommended (lipids/wearables)

Quick start (subset smoke — 2 sessions each):
  PHA_BILINGUAL_SMOKE=1 python3 scripts/pha_bilingual_stress_battery.py

Full run (100 sessions, several hours):
  PHA_PORT=8788 python3 scripts/pha_bilingual_stress_battery.py

Outputs under reports/e2e/bilingual_stress_<timestamp>/:
  plan.json, en/*.jsonl, zh/*.jsonl, quality_report.md, loop_harvest/ (if failures)
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from pha_e2e_quality_score import write_quality_report  # noqa: E402
from pha_e2e_semantic_judge import run_judge  # noqa: E402

REPORT_ROOT = ROOT / "reports" / "e2e"
SMOKE = os.environ.get("PHA_BILINGUAL_SMOKE", "").strip().lower() in ("1", "true", "yes", "on")
MAX_SESSIONS = "2" if SMOKE else os.environ.get("PHA_E2E_MAX_SESSIONS", "50")
PORT = os.environ.get("PHA_PORT", "8788")
PYTHON = os.environ.get("PHA_PYTHON", sys.executable)
# Semantic LLM judge: on by default after batteries; set PHA_SEMANTIC_JUDGE=0 to skip
SEMANTIC_JUDGE = os.environ.get("PHA_SEMANTIC_JUDGE", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)
SEMANTIC_MAX = int(os.environ.get("PHA_SEMANTIC_MAX_TURNS") or ("12" if SMOKE else "40"))
SEMANTIC_MODEL = (
    os.environ.get("PHA_SEMANTIC_MODEL")
    or os.environ.get("PHA_E2E_MODEL")
    or "qwen2.5:7b-instruct"
)


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ensure_banks() -> None:
    for script in (
        "seed_e2e_question_bank_en_v1.py",
        "seed_e2e_question_bank_zh_50_v1.py",
    ):
        subprocess.run([PYTHON, str(SCRIPTS / script)], check=True, cwd=ROOT)


def write_plan(out_dir: Path, *, en_seed: int, zh_seed: int) -> Path:
    plan = {
        "generated_at": _ts(),
        "smoke": SMOKE,
        "port": PORT,
        "max_sessions_per_locale": int(MAX_SESSIONS),
        "en_seed": en_seed,
        "zh_seed": zh_seed,
        "en_bank": "rules/e2e_question_bank_en_v1.json",
        "zh_bank": "rules/e2e_question_bank_zh_50_v1.json",
        "assets_env": os.environ.get("PHA_JUN11_ASSETS", ""),
        "model": os.environ.get("PHA_E2E_MODEL", "qwen2.5:7b-instruct"),
        "dimensions": [
            "multi_turn_continuity (session_id reuse)",
            "memory_followup (weak thanks / metric focus checks)",
            "data_authenticity (jun11 metrics + warehouse lanes)",
            "locale_enforcement (en/zh reply ratio gates)",
            "quality_scoring (continuity/grounding/locale/professionalism/latency)",
            "loop_harvest (failures.jsonl compatible rows)",
        ],
        "commands": {
            "en": f"PHA_PORT={PORT} PHA_E2E_BANK_SEED={en_seed} PHA_E2E_MAX_SESSIONS={MAX_SESSIONS} "
            f"PHA_E2E_REPORT_DIR={out_dir / 'en'} python3 scripts/pha_e2e_en_stress_50x.py",
            "zh": f"PHA_PORT={PORT} PHA_E2E_BANK_SEED={zh_seed} PHA_E2E_MAX_SESSIONS={MAX_SESSIONS} "
            f"PHA_E2E_REPORT_DIR={out_dir / 'zh'} python3 scripts/pha_e2e_zh_stress_50x.py",
        },
    }
    path = out_dir / "plan.json"
    path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def run_battery(locale: str, seed: int, report_dir: Path) -> int:
    script = "pha_e2e_en_stress_50x.py" if locale == "en" else "pha_e2e_zh_stress_50x.py"
    env = os.environ.copy()
    env["PHA_PORT"] = PORT
    env["PHA_E2E_BANK_SEED"] = str(seed)
    env["PHA_E2E_MAX_SESSIONS"] = MAX_SESSIONS
    env["PHA_E2E_REPORT_DIR"] = str(report_dir)
    print(f"\n=== Running {locale.upper()} battery seed={seed} -> {report_dir} ===", flush=True)
    proc = subprocess.run([PYTHON, str(SCRIPTS / script)], cwd=ROOT, env=env)
    return int(proc.returncode)


def latest_jsonl(report_dir: Path, pattern: str) -> Path | None:
    if not report_dir.is_dir():
        return None
    files = sorted(report_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def run_loop_harvest(jsonl: Path, out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    candidates = out_dir / "candidates.jsonl"
    try:
        sys.path.insert(0, str(ROOT / "packages" / "harness_loop" / "src"))
        from harness_loop.harvest import harvest_file_to_path

        path, n_signals, n_rows = harvest_file_to_path(jsonl, candidates)
        return {
            "exit_code": "0",
            "signals": str(n_signals),
            "rows": str(n_rows),
            "candidates": str(path),
        }
    except Exception as exc:  # noqa: BLE001
        return {"exit_code": "1", "error": str(exc), "candidates": str(candidates)}


def main() -> int:
    ensure_banks()
    run_id = _ts()
    out_dir = Path(os.environ.get("PHA_BILINGUAL_REPORT_DIR", REPORT_ROOT / f"bilingual_stress_{run_id}"))
    out_dir.mkdir(parents=True, exist_ok=True)
    en_dir = out_dir / "en"
    zh_dir = out_dir / "zh"
    en_dir.mkdir(exist_ok=True)
    zh_dir.mkdir(exist_ok=True)

    en_seed = int(os.environ.get("PHA_E2E_EN_SEED") or random.randint(1, 2_000_000_000))
    zh_seed = int(os.environ.get("PHA_E2E_ZH_SEED") or random.randint(1, 2_000_000_000))
    plan_path = write_plan(out_dir, en_seed=en_seed, zh_seed=zh_seed)
    print("plan:", plan_path, flush=True)
    print(f"mode={'SMOKE' if SMOKE else 'FULL'} sessions_per_locale={MAX_SESSIONS}", flush=True)

    t0 = time.time()
    en_rc = run_battery("en", en_seed, en_dir)
    zh_rc = run_battery("zh", zh_seed, zh_dir)
    wall = round(time.time() - t0, 1)

    en_jsonl = latest_jsonl(en_dir, "*stress_50x*.jsonl")
    zh_jsonl = latest_jsonl(zh_dir, "*stress_50x*.jsonl")
    quality_path = write_quality_report(
        en_jsonl=en_jsonl,
        zh_jsonl=zh_jsonl,
        out_path=out_dir / "quality_report.md",
        meta={"en_seed": en_seed, "zh_seed": zh_seed, "wall_s": wall, "smoke": SMOKE},
    )

    loop_notes: dict[str, Any] = {}
    harvest_dir = out_dir / "loop_harvest"
    for label, path in (("en", en_jsonl), ("zh", zh_jsonl)):
        if path and path.is_file():
            loop_notes[label] = run_loop_harvest(path, harvest_dir / label)

    semantic_notes: dict[str, Any] = {}
    if SEMANTIC_JUDGE:
        for label, path, locale in (("en", en_jsonl, "en"), ("zh", zh_jsonl, "zh")):
            if not path or not path.is_file():
                continue
            print(f"\n=== Semantic professionalism judge ({locale}) ===", flush=True)
            try:
                semantic_notes[label] = run_judge(
                    path,
                    locale=locale,
                    out_dir=out_dir / "semantic" / label,
                    model=SEMANTIC_MODEL,
                    max_turns=SEMANTIC_MAX,
                    min_answer_len=int(os.environ.get("PHA_SEMANTIC_MIN_ANSWER_LEN") or "80"),
                )
            except Exception as exc:  # noqa: BLE001
                semantic_notes[label] = {"error": str(exc)}

    summary = {
        "run_id": run_id,
        "wall_s": wall,
        "en_exit": en_rc,
        "zh_exit": zh_rc,
        "en_jsonl": str(en_jsonl) if en_jsonl else "",
        "zh_jsonl": str(zh_jsonl) if zh_jsonl else "",
        "quality_report": str(quality_path),
        "loop_harvest": loop_notes,
        "semantic_judge": semantic_notes,
    }
    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("\n=== Bilingual stress complete ===", flush=True)
    print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)
    return 1 if en_rc or zh_rc else 0


if __name__ == "__main__":
    raise SystemExit(main())
