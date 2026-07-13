#!/usr/bin/env python3
"""Export pha.alias_fuzz.v0 — offline Loop A reject corpus as harness.eval_set/v1."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DEFAULT = ROOT / "evals" / "goldens" / "pha_alias_fuzz_v0.json"

# (case_id, metric, alias, tags, note)
REJECT_CORPUS: list[tuple[str, str, str, list[str], str]] = [
    (
        "fuzz.reject.hrv.Query",
        "hrv",
        "Query",
        ["loop_a", "fuzz", "1e_d", "toxic"],
        "OCR UI chrome; rejected by gate_1e_d (human-vetoed toxic proposal class)",
    ),
    (
        "fuzz.reject.hrv.Cancel",
        "hrv",
        "Cancel",
        ["loop_a", "fuzz", "1e_d"],
        "UI chrome denylist",
    ),
    (
        "fuzz.reject.sleep.affective",
        "sleep",
        "睡得好吗",
        ["loop_a", "fuzz", "1e_a"],
        "Affective template blocked by 1E-a",
    ),
    (
        "fuzz.reject.sleep.time_anchor",
        "sleep",
        "昨晚睡多久",
        ["loop_a", "fuzz", "1e_a"],
        "Time anchor / peel → catalog-exists reject path",
    ),
    (
        "fuzz.reject.steps.aggregation",
        "steps",
        "日均多少步",
        ["loop_a", "fuzz", "1e_a"],
        "Aggregation modifier must not promote as raw catalog alias",
    ),
]


def build_fuzz_set() -> dict:
    cases = []
    for cid, metric, alias, tags, note in REJECT_CORPUS:
        cases.append(
            {
                "id": cid,
                "tags": tags,
                "locale": "any",
                "turns": [{"role": "user", "text": alias, "attach": False}],
                "expects": [
                    {"type": "non_empty_turn_text"},
                    {
                        "type": "alias_must_reject",
                        "metric": metric,
                        "alias": alias,
                    },
                ],
                "source": {"kind": "synthetic_fuzz", "note": note},
            }
        )
    # Positive control: curated R2 alias must remain in catalog.
    cases.append(
        {
            "id": "fuzz.control.steps.duoshaobu",
            "tags": ["loop_a", "fuzz", "control", "catalog"],
            "locale": "zh",
            "turns": [{"role": "user", "text": "多少步", "attach": False}],
            "expects": [
                {"type": "non_empty_turn_text"},
                {"type": "catalog_alias", "metric": "steps", "alias": "多少步"},
            ],
            "source": {
                "kind": "human_curated",
                "note": "Control: R2 merged alias must stay present",
            },
        }
    )
    return {
        "schema": "harness.eval_set/v1",
        "id": "pha.alias_fuzz.v0",
        "domain": "pha",
        "version": "0.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "description": (
            "Offline Loop A alias fuzz: toxic/OCR/UI junk + 1E-a templates must reject; "
            "curated steps←多少步 control must remain in catalog."
        ),
        "cases": cases,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Export pha.alias_fuzz.v0 eval_set golden")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    args = ap.parse_args()
    doc = build_fuzz_set()
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
