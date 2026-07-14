"""Portable harvest of failed turn JSONL (domain signal classifier injectable)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from harness_loop.candidates import emit_candidate, iter_jsonl, write_candidates

# (check_id) -> taxonomy signal string
CheckClassifyFn = Callable[[str], str]


def default_classify_check(check: str) -> str:
    """Domain-agnostic fallback: use raw check head as signal."""
    text = (check or "").strip()
    if not text:
        return "unknown"
    return text.split(":", 1)[0].strip() or "unknown"


def harvest_failed_turns_jsonl(
    path: Path | str,
    out: list[dict[str, Any]],
    *,
    classify_check: CheckClassifyFn | None = None,
) -> int:
    """Harvest rows with ``passed: false`` into candidate list.

    Accepts PHA E2E / harness.failure_event-shaped JSONL (superset).
    Does not write catalogs or apply patches.
    """
    classify = classify_check or default_classify_check
    count = 0
    src_path = Path(path)
    for row in iter_jsonl(src_path):
        if row.get("passed", True):
            continue
        msg = str(row.get("message") or row.get("user_message") or "").strip()
        if not msg:
            continue
        session = str(row.get("session_name") or row.get("session_id") or src_path.stem)
        turn = int(row.get("turn") or 0)
        lane = str(row.get("lane") or "")
        profile = str(row.get("harness_profile") or "")
        checks = [str(c) for c in (row.get("checks") or [])]
        if not checks and row.get("check_id"):
            checks = [str(row.get("check_id"))]
        if not checks and row.get("error_code"):
            checks = [str(row.get("error_code"))]
        emitted: set[tuple[str, str, str]] = set()
        for check in checks:
            signal = classify(check)
            source = f"e2e:{src_path.name}:{session}:T{turn}"
            key = (msg, signal, source)
            if key in emitted:
                continue
            emitted.add(key)
            if emit_candidate(
                out,
                message=msg,
                signal=signal,
                source=source,
                intent_family=lane or profile or "e2e",
                meta={
                    "session_name": session,
                    "turn": turn,
                    "check": check,
                    "lane": lane,
                    "harness_profile": profile,
                },
            ):
                count += 1
    return count


def harvest_file_to_path(
    e2e_jsonl: Path | str,
    out_path: Path | str,
    *,
    classify_check: CheckClassifyFn | None = None,
) -> tuple[Path, int, int]:
    """Harvest → write candidates JSONL. Returns (path, signal_count, row_count)."""
    rows: list[dict[str, Any]] = []
    n = harvest_failed_turns_jsonl(e2e_jsonl, rows, classify_check=classify_check)
    path = write_candidates(out_path, rows)
    return path, n, len(rows)


__all__ = [
    "CheckClassifyFn",
    "default_classify_check",
    "harvest_failed_turns_jsonl",
    "harvest_file_to_path",
]
