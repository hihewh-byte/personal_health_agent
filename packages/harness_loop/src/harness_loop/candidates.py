"""Portable harvested candidate rows (JSONL) — domain-agnostic helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator


def iter_jsonl(path: Path | str) -> Iterator[dict[str, Any]]:
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            yield row


def emit_candidate(
    out: list[dict[str, Any]],
    *,
    message: str,
    signal: str,
    source: str,
    suggested_metric: str | None = None,
    intent_family: str | None = None,
    meta: dict[str, Any] | None = None,
) -> bool:
    """Append a deduped candidate row. Returns True if appended."""
    msg = (message or "").strip()
    if not msg or len(msg) < 2:
        return False
    key = (msg, signal, source)
    for existing in out:
        if (existing.get("message"), existing.get("signal"), existing.get("source")) == key:
            return False
    out.append(
        {
            "harvested_at": datetime.now(timezone.utc).isoformat(),
            "message": msg,
            "signal": signal,
            "source": source,
            "suggested_metric": suggested_metric,
            "intent_family": intent_family or suggested_metric,
            "meta": meta or {},
        }
    )
    return True


def write_candidates(path: Path | str, rows: Iterable[dict[str, Any]]) -> Path:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return out_path


def load_candidates(path: Path | str) -> list[dict[str, Any]]:
    return list(iter_jsonl(path))


__all__ = [
    "iter_jsonl",
    "emit_candidate",
    "write_candidates",
    "load_candidates",
]
