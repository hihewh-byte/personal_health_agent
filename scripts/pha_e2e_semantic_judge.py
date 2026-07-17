#!/usr/bin/env python3
"""Semantic professionalism judge for PHA E2E / stress JSONL turns (LLM-as-judge).

Uses a local Ollama model (default same as PHA chat) to score reply quality on
evidence grounding, clinical/wellness tone, locale, clarity, and non-diagnostic
boundary. Outputs JSONL + markdown; optional blend into rule-based quality report.

This is NOT medical QA — the judge scores communication quality against the
stated evidence in the turn, not clinical correctness vs a physician standard.

Run (after a stress JSONL exists):
  PYTHONPATH=. python3 scripts/pha_e2e_semantic_judge.py \\
    --jsonl reports/e2e/.../en/en_stress_50x_....jsonl --locale en \\
    --out-dir reports/e2e/.../semantic_en

Sample (recommended — full 800 turns is slow):
  PHA_SEMANTIC_MAX_TURNS=40 python3 scripts/pha_e2e_semantic_judge.py ...

Env:
  PHA_SEMANTIC_MODEL   judge model (default: PHA_E2E_MODEL or qwen2.5:7b-instruct)
  PHA_SEMANTIC_MAX_TURNS  cap turns judged (0 = all)
  PHA_SEMANTIC_MIN_ANSWER_LEN  skip short/weak replies (default 80)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pha.llm_provider import OllamaProvider

JUDGE_SYSTEM = """You are an independent QA reviewer for a personal wellness (NOT clinical) AI assistant.
Score ONLY communication quality of the assistant reply given the user message and any known metrics.
Do NOT invent medical facts. Do NOT treat the assistant as a doctor.

Return a single JSON object with these integer fields (0-100 each):
- evidence_grounding: Does the reply stick to numbers/facts that could come from user data / screenshots? Penalize invented precise values.
- professional_tone: Calm, precise, wellness-appropriate language; not hype, not alarmist, not slang-heavy.
- clarity_structure: Clear structure, readable, answers the user's question.
- non_diagnostic_boundary: Avoids diagnosis/treatment orders; educational framing when giving advice.
- locale_naturalness: Natural for the requested locale (en or zh); minimal wrong-language leakage.
- overall: Holistic professional quality for this turn.

Also include:
- flags: array of short string codes (e.g. "invented_number", "diagnosis_language", "locale_leak", "vague", "overlong", "good_citation")
- rationale: one short sentence (max 40 words) explaining the overall score.

Be strict on invented numbers and diagnostic language. Be fair on brief polite closings (they can score mid-high if appropriate).
"""


@dataclass
class SemanticScore:
    session_name: str
    turn: int
    locale: str
    message: str
    answer_head: str
    evidence_grounding: int
    professional_tone: int
    clarity_structure: int
    non_diagnostic_boundary: int
    locale_naturalness: int
    overall: int
    flags: list[str] = field(default_factory=list)
    rationale: str = ""
    judge_model: str = ""
    elapsed_s: float = 0.0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clamp_int(v: Any, default: int = 50) -> int:
    try:
        return max(0, min(100, int(v)))
    except (TypeError, ValueError):
        return default


def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return {}
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return {}


def select_turns(
    rows: list[dict[str, Any]],
    *,
    min_answer_len: int,
    max_turns: int,
) -> list[dict[str, Any]]:
    """Prefer substantive turns; keep at most one weak closer per session; then cap."""
    by_session: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = str(row.get("session_name") or "")
        by_session.setdefault(key, []).append(row)

    picked: list[dict[str, Any]] = []
    for _sid, turns in by_session.items():
        substantive = [r for r in turns if len(str(r.get("answer") or "")) >= min_answer_len]
        weak = [r for r in turns if len(str(r.get("answer") or "")) < min_answer_len]
        # Always include first substantive + last substantive if distinct
        if substantive:
            picked.append(substantive[0])
            mid = None
            if len(substantive) > 2:
                mid = substantive[len(substantive) // 2]
                picked.append(mid)
            if len(substantive) > 1 and substantive[-1] is not substantive[0]:
                if mid is None or substantive[-1] is not mid:
                    picked.append(substantive[-1])
        elif weak:
            picked.append(weak[0])

    # Deduplicate by (session, turn)
    seen: set[tuple[str, int]] = set()
    uniq: list[dict[str, Any]] = []
    for r in picked:
        key = (str(r.get("session_name") or ""), int(r.get("turn") or 0))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)

    if max_turns > 0 and len(uniq) > max_turns:
        # Stratified trim: keep order, take evenly spaced
        step = len(uniq) / max_turns
        uniq = [uniq[int(i * step)] for i in range(max_turns)]
    return uniq


def judge_turn(
    provider: OllamaProvider,
    row: dict[str, Any],
    *,
    locale: str,
) -> SemanticScore:
    message = str(row.get("message") or "")
    answer = str(row.get("answer") or "")
    metrics = row.get("metrics") or {}
    session = str(row.get("session_name") or "")
    turn = int(row.get("turn") or 0)
    payload = {
        "locale": locale,
        "user_message": message[:800],
        "assistant_reply": answer[:3500],
        "known_ingest_metrics": metrics,
        "harness_profile": row.get("harness_profile") or "",
        "automated_checks": row.get("checks") or [],
    }
    user = (
        f"Locale required: {locale}\n"
        f"Review this turn and return JSON only.\n\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )
    t0 = time.time()
    err = ""
    data: dict[str, Any] = {}
    try:
        raw = provider.chat_completion(
            system_prompt=JUDGE_SYSTEM,
            user_message=user,
            json_mode=True,
        )
        data = _extract_json(raw)
        if not data:
            err = "judge_json_parse_failed"
    except Exception as exc:  # noqa: BLE001
        err = f"judge_error:{type(exc).__name__}:{exc}"

    flags = data.get("flags") if isinstance(data.get("flags"), list) else []
    return SemanticScore(
        session_name=session,
        turn=turn,
        locale=locale,
        message=message[:120],
        answer_head=answer[:160].replace("\n", " "),
        evidence_grounding=_clamp_int(data.get("evidence_grounding"), 0 if err else 50),
        professional_tone=_clamp_int(data.get("professional_tone"), 0 if err else 50),
        clarity_structure=_clamp_int(data.get("clarity_structure"), 0 if err else 50),
        non_diagnostic_boundary=_clamp_int(data.get("non_diagnostic_boundary"), 0 if err else 50),
        locale_naturalness=_clamp_int(data.get("locale_naturalness"), 0 if err else 50),
        overall=_clamp_int(data.get("overall"), 0 if err else 50),
        flags=[str(f) for f in flags][:12],
        rationale=str(data.get("rationale") or "")[:200],
        judge_model=getattr(provider, "_model", "") or "",
        elapsed_s=round(time.time() - t0, 1),
        error=err,
    )


def summarize(scores: list[SemanticScore]) -> dict[str, Any]:
    if not scores:
        return {"turns": 0}
    ok = [s for s in scores if not s.error]
    pool = ok or scores

    def mean(attr: str) -> float:
        return round(sum(getattr(s, attr) for s in pool) / len(pool), 1)

    flag_counts: dict[str, int] = {}
    for s in scores:
        for f in s.flags:
            flag_counts[f] = flag_counts.get(f, 0) + 1
    return {
        "turns_judged": len(scores),
        "turns_ok": len(ok),
        "mean_overall": mean("overall"),
        "mean_evidence_grounding": mean("evidence_grounding"),
        "mean_professional_tone": mean("professional_tone"),
        "mean_clarity_structure": mean("clarity_structure"),
        "mean_non_diagnostic_boundary": mean("non_diagnostic_boundary"),
        "mean_locale_naturalness": mean("locale_naturalness"),
        "top_flags": sorted(flag_counts.items(), key=lambda x: -x[1])[:12],
        "judge_errors": sum(1 for s in scores if s.error),
    }


def write_report(scores: list[SemanticScore], summary: dict[str, Any], path: Path) -> None:
    lines = [
        "# Semantic Professionalism Judge Report",
        "",
        f"- Turns judged: {summary.get('turns_judged', 0)} (ok={summary.get('turns_ok', 0)}, errors={summary.get('judge_errors', 0)})",
        f"- Mean overall: **{summary.get('mean_overall', 0)}** / 100",
        f"- Evidence / Tone / Clarity / Non-diagnostic / Locale: "
        f"{summary.get('mean_evidence_grounding')} / {summary.get('mean_professional_tone')} / "
        f"{summary.get('mean_clarity_structure')} / {summary.get('mean_non_diagnostic_boundary')} / "
        f"{summary.get('mean_locale_naturalness')}",
        "",
        "## Top flags",
        "",
    ]
    for flag, n in summary.get("top_flags") or []:
        lines.append(f"- `{flag}` × {n}")
    if not summary.get("top_flags"):
        lines.append("- _none_")
    lines.extend(
        [
            "",
            "## Lowest 15 overall",
            "",
            "| Session | Turn | Overall | Evidence | Tone | Flags | Rationale |",
            "|---------|------|---------|----------|------|-------|-----------|",
        ],
    )
    for s in sorted(scores, key=lambda x: x.overall)[:15]:
        flags = ", ".join(s.flags[:3]) or (s.error or "-")
        rat = (s.rationale or "-").replace("|", "/")
        lines.append(
            f"| {s.session_name} | {s.turn} | {s.overall} | {s.evidence_grounding} | "
            f"{s.professional_tone} | {flags} | {rat} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_judge(
    jsonl: Path,
    *,
    locale: str,
    out_dir: Path,
    model: str,
    max_turns: int,
    min_answer_len: int,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    with jsonl.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    selected = select_turns(rows, min_answer_len=min_answer_len, max_turns=max_turns)
    provider = OllamaProvider(model=model)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_jsonl = out_dir / f"semantic_judge_{locale}.jsonl"
    scores: list[SemanticScore] = []
    print(
        f"semantic_judge locale={locale} selected={len(selected)}/{len(rows)} model={model}",
        flush=True,
    )
    with out_jsonl.open("w", encoding="utf-8") as fh:
        for i, row in enumerate(selected, start=1):
            sc = judge_turn(provider, row, locale=locale)
            scores.append(sc)
            fh.write(json.dumps(sc.to_dict(), ensure_ascii=False) + "\n")
            print(
                f"  [{i}/{len(selected)}] {sc.session_name} T{sc.turn} overall={sc.overall} "
                f"{sc.elapsed_s}s flags={sc.flags[:3]} err={sc.error or '-'}",
                flush=True,
            )
    summary = summarize(scores)
    summary_path = out_dir / f"semantic_summary_{locale}.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path = out_dir / f"semantic_report_{locale}.md"
    write_report(scores, summary, md_path)
    return {
        "locale": locale,
        "jsonl": str(out_jsonl),
        "summary": str(summary_path),
        "report": str(md_path),
        **summary,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Semantic professionalism judge for stress JSONL")
    ap.add_argument("--jsonl", required=True, type=Path)
    ap.add_argument("--locale", required=True, choices=("en", "zh"))
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument(
        "--model",
        default=os.environ.get("PHA_SEMANTIC_MODEL")
        or os.environ.get("PHA_E2E_MODEL")
        or "qwen2.5:7b-instruct",
    )
    ap.add_argument(
        "--max-turns",
        type=int,
        default=int(os.environ.get("PHA_SEMANTIC_MAX_TURNS") or "40"),
    )
    ap.add_argument(
        "--min-answer-len",
        type=int,
        default=int(os.environ.get("PHA_SEMANTIC_MIN_ANSWER_LEN") or "80"),
    )
    args = ap.parse_args()
    if not args.jsonl.is_file():
        print(f"FAIL missing jsonl {args.jsonl}")
        return 1
    out_dir = args.out_dir or (args.jsonl.parent / "semantic")
    result = run_judge(
        args.jsonl,
        locale=args.locale,
        out_dir=out_dir,
        model=args.model,
        max_turns=args.max_turns,
        min_answer_len=args.min_answer_len,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("judge_errors") else 0


if __name__ == "__main__":
    raise SystemExit(main())
