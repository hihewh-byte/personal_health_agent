#!/usr/bin/env python3
"""Export a thin harness.eval_set/v1 smoke golden from PHA question banks."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT_DEFAULT = ROOT / "evals" / "goldens" / "pha_smoke_v0.json"


def _load_bank(name: str) -> dict[str, Any]:
    return json.loads((ROOT / "rules" / name).read_text(encoding="utf-8"))


def _slot_text(bank: dict[str, Any], slot: str) -> str:
    pools = bank.get("variant_pools") or {}
    pool = pools.get(slot) or {}
    for key in ("formal", "colloquial"):
        vals = pool.get(key) or []
        if vals:
            return str(vals[0])
    raise KeyError(f"no text for slot {slot!r}")


def _find_set(bank: dict[str, Any], set_id: str) -> dict[str, Any]:
    for item in bank.get("sets") or []:
        if item.get("set_id") == set_id:
            return item
    raise KeyError(f"set_id not found: {set_id}")


def _case_from_set(
    *,
    bank_name: str,
    bank: dict[str, Any],
    set_id: str,
    turn_limit: int,
    case_id: str,
    tags: list[str],
    locale: str,
    extra_expects: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    s = _find_set(bank, set_id)
    turns_out: list[dict[str, Any]] = []
    for t in (s.get("turns") or [])[:turn_limit]:
        slot = str(t.get("slot") or "")
        turns_out.append(
            {
                "role": "user",
                "slot": slot,
                "attach": bool(t.get("attach")),
                "text": _slot_text(bank, slot),
            },
        )
    expects: list[dict[str, Any]] = [
        {"type": "non_empty_turn_text"},
        {"type": "min_turns", "n": len(turns_out)},
    ]
    if extra_expects:
        expects.extend(extra_expects)
    return {
        "id": case_id,
        "tags": tags,
        "locale": locale,
        "turns": turns_out,
        "expects": expects,
        "source": {
            "kind": "e2e_question_bank",
            "bank": bank_name,
            "set_id": set_id,
            "turn_limit": turn_limit,
        },
    }


def build_smoke_set() -> dict[str, Any]:
    en = _load_bank("e2e_question_bank_en_v1.json")
    zh = _load_bank("e2e_question_bank_v1.json")
    cases = [
        _case_from_set(
            bank_name="e2e_question_bank_en_v1.json",
            bank=en,
            set_id="EN07",
            turn_limit=1,
            case_id="EN07.t1.warehouse_hrv",
            tags=["bank", "en", "loop_a", "smoke"],
            locale="en",
        ),
        _case_from_set(
            bank_name="e2e_question_bank_en_v1.json",
            bank=en,
            set_id="EN08",
            turn_limit=2,
            case_id="EN08.t1-2.warehouse_steps",
            tags=["bank", "en", "loop_a", "alias", "smoke"],
            locale="en",
            extra_expects=[{"type": "tag_required", "tag": "alias"}],
        ),
        _case_from_set(
            bank_name="e2e_question_bank_v1.json",
            bank=zh,
            set_id="QS07",
            turn_limit=1,
            case_id="QS07.t1.warehouse_hrv",
            tags=["bank", "zh", "smoke"],
            locale="zh",
        ),
        {
            "id": "catalog.steps.duoshaobu",
            "tags": ["loop_a", "alias", "catalog", "smoke"],
            "locale": "zh",
            "turns": [
                {
                    "role": "user",
                    "slot": "steps",
                    "attach": False,
                    "text": "日均多少步",
                },
            ],
            "expects": [
                {"type": "non_empty_turn_text"},
                {"type": "catalog_alias", "metric": "steps", "alias": "多少步"},
                {"type": "live_non_empty_answer"},
            ],
            "source": {
                "kind": "human_curated",
                "note": "First R2 merged alias (PR #2); offline catalog gate",
            },
        },
        {
            "id": "locale.close.xiexie",
            "tags": ["locale", "skip_llm", "smoke"],
            "locale": "zh",
            "turns": [{"role": "user", "text": "谢谢", "attach": False}],
            "expects": [
                {"type": "non_empty_turn_text"},
                {"type": "live_locale", "locale": "zh"},
            ],
            "source": {
                "kind": "regression_fixture",
                "note": "Short CJK close token; live runner should expect zh ack",
            },
        },
        {
            "id": "3h.lane.structural",
            "tags": ["3h", "attachment", "smoke"],
            "locale": "any",
            "turns": [
                {
                    "role": "user",
                    "text": "帮我看看这些数据",
                    "attach": True,
                    "slot": "attach_open",
                },
            ],
            "expects": [
                {"type": "non_empty_turn_text"},
                {"type": "tag_required", "tag": "3h"},
                {"type": "live_non_empty_answer"},
            ],
            "source": {
                "kind": "stage3h_stress",
                "note": "Placeholder for live 3H attach turn; offline validates shape only",
            },
        },
    ]
    return {
        "schema": "harness.eval_set/v1",
        "id": "pha.smoke.v0",
        "domain": "pha",
        "version": "0.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "description": (
            "Thin smoke golden exported from EN/ZH banks + curated Loop A alias / locale / 3H placeholders. "
            "Offline expects only; live_* reserved for future runner."
        ),
        "cases": cases,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Export pha.smoke.v0 eval_set golden")
    ap.add_argument("--write", action="store_true", help="Write evals/goldens/pha_smoke_v0.json")
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    args = ap.parse_args()
    doc = build_smoke_set()
    # ASCII JSON (\uXXXX for CJK) keeps CI/log encoding boring.
    text = json.dumps(doc, ensure_ascii=True, indent=2) + "\n"
    if args.write:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"wrote {out} cases={len(doc['cases'])}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
