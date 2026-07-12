"""Loop B · L2 Eval — harvest CHB personalization gaps from slow-round / E2E rows."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any


def _generic_lifestyle_heuristic(answer: str, message: str) -> bool:
    ans = (answer or "").strip().lower()
    msg = (message or "").strip().lower()
    if len(ans) < 120:
        return False
    generic_markers = (
        "consult your doctor",
        "ask a clinician",
        "maintain a balanced diet",
        "regular exercise",
        "请咨询",
        "均衡饮食",
        "遵医嘱",
    )
    if not any(m in ans for m in generic_markers):
        return False
    personal_markers = ("ldl", "hrv", "lab_", "ref:", "health record", "mmol", "mmol/l")
    if any(p in ans for p in personal_markers):
        return False
    if re.search(r"\bsleep\b.*\b(hour|hr|mean|avg|duration)\b", ans):
        return False
    lifestyle_triggers = ("coffee", "supplement", "怎么办", "what should i")
    if any(t in msg for t in lifestyle_triggers):
        return True
    return "lifestyle" in msg or len(msg) < 40


def extract_chb_gap_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build CHB gap rows from harvest or E2E JSONL records."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        checks = [str(c) for c in (row.get("checks") or [])]
        signal = str(row.get("signal") or row.get("taxonomy_signal") or "").strip()
        answer = str(row.get("answer") or row.get("assistant_reply") or "")
        message = str(row.get("message") or row.get("user_message") or "")
        session = str(row.get("session_name") or row.get("session_id") or "")
        user_id = str(row.get("user_id") or "default").strip() or "default"
        turn = int(row.get("turn") or 0)

        gap_reason = ""
        if signal == "chb_personalization_gap":
            gap_reason = signal
        elif any(c.startswith("weak_followup") for c in checks):
            gap_reason = "weak_followup_heavy"
        elif _generic_lifestyle_heuristic(answer, message):
            gap_reason = "generic_lifestyle_answer"

        if not gap_reason:
            continue

        question = (
            f"Personalize lifestyle guidance for: {message[:120]}"
            if message
            else "Add CHB facts for recurring lifestyle follow-ups."
        )
        key = f"{user_id}:{question[:80]}"
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "schema": "pha.chb_gap_candidate/v1",
                "user_id": user_id,
                "question": question,
                "signal": gap_reason,
                "source_session": session,
                "source_turn": turn,
                "harvested_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    return out


def merge_gap_questions(existing: list[str], candidates: list[dict[str, Any]]) -> list[str]:
    merged = list(existing)
    for row in candidates:
        q = str(row.get("question") or "").strip()
        if q and q not in merged:
            merged.append(q)
    return merged


def write_gap_candidates(
    candidates: list[dict[str, Any]],
    *,
    user_id: str,
    report_root: str | Path,
) -> Path:
    from pathlib import Path as P

    root = P(report_root)
    uid = (user_id or "default").strip() or "default"
    out_dir = root / uid
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "gap_candidates.json"
    doc = {
        "schema": "pha.chb_gap_candidates/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "user_id": uid,
        "candidates": candidates,
        "open_questions": [str(c.get("question") or "") for c in candidates if c.get("question")],
    }
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_gap_open_questions(user_id: str, *, report_root: str | Path) -> list[str]:
    from pathlib import Path as P

    path = P(report_root) / ((user_id or "default").strip() or "default") / "gap_candidates.json"
    if not path.is_file():
        return []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return [str(q).strip() for q in (doc.get("open_questions") or []) if str(q).strip()]


__all__ = [
    "extract_chb_gap_candidates",
    "load_gap_open_questions",
    "merge_gap_questions",
    "write_gap_candidates",
]
