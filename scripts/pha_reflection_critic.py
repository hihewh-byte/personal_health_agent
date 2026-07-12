#!/usr/bin/env python3
"""Loop Ring-R — deterministic Reflection Critic (observe + critique + propose hints).

Reads harvested ``slow_round_candidates.jsonl`` (and optional E2E JSONL) and emits:
  - ``reports/loop/reflection_{ts}.md``  human summary
  - ``reports/loop/proposals/reflection_{ts}.json``  structured critique

No auto-merge. No Python routing edits. Optional ``--llm-assist`` is reserved (not implemented).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pha.loop_failure_taxonomy import (  # noqa: E402
    allowed_proposal_layers,
    classify_e2e_check,
    classify_harvest_signal,
    is_auto_promote_eligible,
    taxonomy_rule,
    warehouse_llm_zh_heuristic,
)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def harvest_signals_from_e2e(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build critique rows from ``en_stress_50x`` TurnRecord JSONL."""
    out: list[dict[str, Any]] = []
    for row in rows:
        if row.get("passed", True):
            continue
        msg = str(row.get("message") or "").strip()
        checks = [str(c) for c in (row.get("checks") or [])]
        answer = str(row.get("answer") or "")
        session = str(row.get("session_name") or "")
        turn = int(row.get("turn") or 0)
        for check in checks:
            signal = classify_e2e_check(check)
            out.append(
                {
                    "message": msg,
                    "signal": signal,
                    "source": f"e2e:{session}:T{turn}",
                    "check": check,
                    "allowed_layers": sorted(allowed_proposal_layers(signal)),
                    "auto_promote": is_auto_promote_eligible(signal),
                    "meta": {
                        "session_name": session,
                        "turn": turn,
                        "harness_profile": row.get("harness_profile"),
                        "lane": row.get("lane"),
                    },
                },
            )
        if warehouse_llm_zh_heuristic(answer):
            out.append(
                {
                    "message": msg,
                    "signal": "warehouse_llm_zh",
                    "source": f"e2e:{session}:T{turn}",
                    "check": "warehouse_llm_zh_heuristic",
                    "allowed_layers": sorted(allowed_proposal_layers("warehouse_llm_zh")),
                    "auto_promote": False,
                    "meta": {"session_name": session, "turn": turn, "answer_head": answer[:240]},
                },
            )
    return out


def merge_critique_rows(
    candidates: list[dict[str, Any]],
    e2e_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for row in candidates:
        signal = classify_harvest_signal(str(row.get("signal") or ""))
        merged.append(
            {
                "message": row.get("message"),
                "signal": signal,
                "source": row.get("source"),
                "check": row.get("signal"),
                "allowed_layers": sorted(allowed_proposal_layers(signal)),
                "auto_promote": is_auto_promote_eligible(signal),
                "meta": row.get("meta") or {},
            },
        )
    merged.extend(harvest_signals_from_e2e(e2e_rows))
    return merged


def suggest_regression_sessions(critique: list[dict[str, Any]]) -> list[str]:
    """Map failed sessions to EN stress subset IDs for re-run hints."""
    sessions: set[str] = set()
    for row in critique:
        src = str(row.get("source") or "")
        if src.startswith("e2e:"):
            name = src.split(":", 1)[1].split(":T", 1)[0]
            if name.startswith("EN") and "_" in name:
                sessions.add(name.split("_", 1)[0])
    preferred = [
        "EN01",
        "EN07",
        "EN08",
        "EN15",
        "EN20",
        "EN39",
        "EN44",
        "EN48",
        "EN50",
    ]
    ordered = [s for s in preferred if s in sessions]
    ordered.extend(sorted(s for s in sessions if s not in ordered))
    return ordered[:10]


def build_reflection_doc(
    critique: list[dict[str, Any]],
    *,
    candidates_path: Path,
    e2e_path: Path | None,
) -> tuple[dict[str, Any], str]:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    by_signal: Counter[str] = Counter(str(r.get("signal") or "unknown") for r in critique)
    code_review = [r for r in critique if "code_review_required" in (r.get("allowed_layers") or [])]
    auto_rows = [r for r in critique if r.get("auto_promote")]
    regress = suggest_regression_sessions(critique)

    proposal = {
        "schema": "pha.loop_proposal/v2",
        "source": "reflection_critic",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stage": "ring-r-v0",
        "candidates_path": str(candidates_path),
        "e2e_jsonl_path": str(e2e_path) if e2e_path else None,
        "failure_taxonomy": dict(by_signal),
        "critique_count": len(critique),
        "accepted_catalog": [],
        "accepted_schema": [],
        "slot_candidates": [],
        "code_review_items": code_review[:50],
        "auto_promote_candidates": auto_rows[:20],
        "rejected": [],
        "suggested_regression": regress,
        "notes": (
            "Reflection-only artifact. Distiller may consume auto_promote_candidates; "
            "code_review_items must not enter catalog without human PR."
        ),
    }

    lines = [
        f"# Loop Reflection Report — {ts}",
        "",
        f"- Candidates: `{candidates_path}`",
        f"- E2E JSONL: `{e2e_path}`" if e2e_path else "- E2E JSONL: (none)",
        f"- Critique rows: **{len(critique)}**",
        "",
        "## Failure taxonomy",
        "",
    ]
    for sig, count in by_signal.most_common():
        rule = taxonomy_rule(sig)  # type: ignore[arg-type]
        lines.append(f"- **{sig}**: {count} — {rule.note}")
    lines.extend(["", "## Suggested EN regression subset", ""])
    if regress:
        lines.append(f"`PHA_E2E_SESSIONS={','.join(regress)}`")
    else:
        lines.append("(no EN session failures in input)")
    lines.extend(["", "## Code review required (top 10)", ""])
    for row in code_review[:10]:
        lines.append(
            f"- `{row.get('source')}` **{row.get('signal')}** — "
            f"{(row.get('message') or '')[:80]!r}",
        )
    lines.extend(["", "## Auto-promote eligible (top 10)", ""])
    for row in auto_rows[:10]:
        lines.append(
            f"- `{row.get('source')}` **{row.get('signal')}** — "
            f"{(row.get('message') or '')[:80]!r}",
        )
    return proposal, "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Loop Reflection Critic (Ring R, deterministic)")
    ap.add_argument(
        "--candidates",
        default=str(ROOT / "reports" / "loop" / "slow_round_candidates.jsonl"),
    )
    ap.add_argument("--e2e-jsonl", default="", help="Optional en_stress_50x JSONL")
    ap.add_argument(
        "--out-dir",
        default=str(ROOT / "reports" / "loop"),
    )
    args = ap.parse_args()

    candidates_path = Path(args.candidates)
    e2e_path = Path(args.e2e_jsonl) if args.e2e_jsonl else None
    candidates = _load_jsonl(candidates_path)
    e2e_rows = _load_jsonl(e2e_path) if e2e_path else []

    critique = merge_critique_rows(candidates, e2e_rows)
    proposal, md = build_reflection_doc(
        critique,
        candidates_path=candidates_path,
        e2e_path=e2e_path,
    )

    out_dir = Path(args.out_dir)
    proposal_dir = out_dir / "proposals"
    proposal_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    md_path = out_dir / f"reflection_{ts}.md"
    json_path = proposal_dir / f"reflection_{ts}.json"
    md_path.write_text(md, encoding="utf-8")
    json_path.write_text(json.dumps(proposal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("== reflection critic ==")
    print(f" candidates : {candidates_path} ({len(candidates)} rows)")
    print(f" e2e jsonl  : {e2e_path or '(none)'} ({len(e2e_rows)} rows)")
    print(f" critique   : {len(critique)} rows")
    print(f" taxonomy   : {dict(Counter(r['signal'] for r in critique))}")
    print(f" md         : {md_path}")
    print(f" proposal   : {json_path}")
    print(f" suggest EN : {','.join(proposal.get('suggested_regression') or [])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
