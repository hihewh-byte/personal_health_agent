#!/usr/bin/env python3
"""Rule-based quality scoring for PHA E2E / stress JSONL turn records.

Scores each turn 0–100 across continuity, data grounding, locale, professionalism,
and latency. No external LLM judge — deterministic heuristics for batch runs.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_LATIN_WORD_RE = re.compile(r"[A-Za-z]{4,}")
_NUMBER_RE = re.compile(r"\d")
_DISCLAIMER_ZH = ("非医疗", "不构成", "请咨询", "科普", "仅供参考", "不能替代")
_DISCLAIMER_EN = ("not medical advice", "not a diagnosis", "consult", "educational", "wellness")
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\u2600-\u27BF"
    "]",
    flags=re.UNICODE,
)


@dataclass
class TurnQuality:
    session_name: str
    turn: int
    locale: str
    passed_checks: bool
    total: float
    continuity: float
    grounding: float
    locale_fit: float
    professionalism: float
    latency: float
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clamp(x: float) -> float:
    return max(0.0, min(100.0, round(x, 1)))


def score_turn(row: dict[str, Any], *, locale: str, prev_rows: list[dict[str, Any]]) -> TurnQuality:
    answer = str(row.get("answer") or "")
    message = str(row.get("message") or "")
    elapsed = float(row.get("elapsed_s") or 0.0)
    passed = bool(row.get("passed", True))
    checks = [str(c) for c in (row.get("checks") or [])]
    session = str(row.get("session_name") or "")
    turn = int(row.get("turn") or 0)
    notes: list[str] = []

    # Continuity: same session_id across turns; weak followups should stay short
    continuity = 85.0
    sid = str(row.get("session_id") or "")
    if prev_rows and sid and any(str(p.get("session_id")) != sid for p in prev_rows if p.get("session_id")):
        continuity -= 25
        notes.append("session_id_changed")
    if turn > 1 and len(answer) > 1800 and any(w in message for w in ("谢谢", "好的", "thanks", "ok")):
        continuity -= 20
        notes.append("weak_followup_too_long")

    # Grounding: metrics on attach turns, numerics in warehouse/lab turns, harness profile present
    grounding = 70.0
    metrics = row.get("metrics") or {}
    if metrics:
        grounding += 15
    if row.get("harness_profile"):
        grounding += 5
    if _NUMBER_RE.search(answer) and any(k in message.lower() for k in ("hrv", "lipid", "sleep", "步", "血脂", "睡眠")):
        grounding += 10
    if any(c.startswith("metric_") for c in checks):
        grounding -= 35
        notes.append("metric_mismatch")
    if any("warehouse" in c for c in checks):
        grounding -= 15

    # Locale fit
    locale_fit = 80.0
    cjk = len(_CJK_RE.findall(answer))
    ratio = cjk / max(len(answer), 1)
    if locale == "zh":
        if answer and len(answer) >= 40 and ratio < 0.15:
            locale_fit -= 40
            notes.append("low_chinese_ratio")
        elif ratio >= 0.25:
            locale_fit += 10
    else:
        if ratio > 0.12:
            locale_fit -= 40
            notes.append("high_cjk_ratio")
        elif answer and ratio <= 0.05:
            locale_fit += 10

    # Professionalism: structure, disclaimer on advisory, low emoji spam
    professionalism = 75.0
    if len(answer) >= 80:
        professionalism += 5
    if "\n" in answer or "·" in answer or "- " in answer:
        professionalism += 5
    disc = _DISCLAIMER_ZH if locale == "zh" else _DISCLAIMER_EN
    if any(k in answer.lower() if locale == "en" else k in answer for k in disc):
        professionalism += 5
    emoji_n = len(_EMOJI_RE.findall(answer))
    if emoji_n > 3:
        professionalism -= 15
        notes.append("emoji_heavy")
    latin_words = len(_LATIN_WORD_RE.findall(answer))
    if locale == "zh" and latin_words > 8 and ratio > 0.2:
        professionalism -= 10
        notes.append("latin_leak")

    # Latency
    latency = 90.0
    if elapsed > 120:
        latency = 40.0
        notes.append("very_slow")
    elif elapsed > 60:
        latency = 60.0
        notes.append("slow")
    elif elapsed > 30:
        latency = 75.0

    if not passed:
        continuity = min(continuity, 50)
        grounding = min(grounding, 50)
        locale_fit = min(locale_fit, 50)

    total = _clamp(0.25 * continuity + 0.30 * grounding + 0.20 * locale_fit + 0.15 * professionalism + 0.10 * latency)
    return TurnQuality(
        session_name=session,
        turn=turn,
        locale=locale,
        passed_checks=passed,
        total=total,
        continuity=_clamp(continuity),
        grounding=_clamp(grounding),
        locale_fit=_clamp(locale_fit),
        professionalism=_clamp(professionalism),
        latency=_clamp(latency),
        notes=notes,
    )


def score_jsonl(path: Path, *, locale: str) -> list[TurnQuality]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    out: list[TurnQuality] = []
    by_session: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = str(row.get("session_name") or "")
        prev = list(by_session.get(key, []))
        out.append(score_turn(row, locale=locale, prev_rows=prev))
        by_session.setdefault(key, []).append(row)
    return out


def summarize_scores(scores: Iterable[TurnQuality]) -> dict[str, Any]:
    items = list(scores)
    if not items:
        return {"turns": 0}
    totals = [s.total for s in items]
    return {
        "turns": len(items),
        "mean_total": round(sum(totals) / len(totals), 1),
        "min_total": min(totals),
        "max_total": max(totals),
        "pass_rate_checks": round(sum(1 for s in items if s.passed_checks) / len(items), 3),
        "mean_continuity": round(sum(s.continuity for s in items) / len(items), 1),
        "mean_grounding": round(sum(s.grounding for s in items) / len(items), 1),
        "mean_locale_fit": round(sum(s.locale_fit for s in items) / len(items), 1),
        "mean_professionalism": round(sum(s.professionalism for s in items) / len(items), 1),
        "mean_latency": round(sum(s.latency for s in items) / len(items), 1),
    }


def write_quality_report(
    *,
    en_jsonl: Path | None,
    zh_jsonl: Path | None,
    out_path: Path,
    meta: dict[str, Any] | None = None,
) -> Path:
    sections: list[str] = [
        "# PHA Bilingual Stress — Quality Report",
        "",
        f"- Meta: `{json.dumps(meta or {}, ensure_ascii=False)}`",
        "",
    ]
    for label, path, locale in (
        ("English 50×", en_jsonl, "en"),
        ("Chinese 50×", zh_jsonl, "zh"),
    ):
        if not path or not path.is_file():
            sections.append(f"## {label}\n\n_Skipped — no JSONL at `{path}`_\n")
            continue
        scores = score_jsonl(path, locale=locale)
        summary = summarize_scores(scores)
        sections.extend(
            [
                f"## {label}",
                "",
                f"- JSONL: `{path}`",
                f"- Turns scored: {summary.get('turns', 0)}",
                f"- Mean quality total: **{summary.get('mean_total', 0)}** / 100",
                f"- Check pass rate: {summary.get('pass_rate_checks', 0)}",
                f"- Continuity / Grounding / Locale / Professionalism / Latency: "
                f"{summary.get('mean_continuity')} / {summary.get('mean_grounding')} / "
                f"{summary.get('mean_locale_fit')} / {summary.get('mean_professionalism')} / "
                f"{summary.get('mean_latency')}",
                "",
                "### Lowest 10 turns",
                "",
                "| Session | Turn | Total | Notes |",
                "|---------|------|-------|-------|",
            ],
        )
        for s in sorted(scores, key=lambda x: x.total)[:10]:
            note = ", ".join(s.notes[:3]) or "-"
            sections.append(f"| {s.session_name} | {s.turn} | {s.total} | {note} |")
        sections.append("")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(sections) + "\n", encoding="utf-8")
    return out_path
