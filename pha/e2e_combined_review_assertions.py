"""P2 — hard assertions for combined_review catalog SSE turns (E2E + offline selfcheck)."""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

COMBINED_REVIEW_PROFILE = "combined_review"

# Ollama wire-format / catalog tool-loop failures observed in Stage 3F E2E.
_OLLAMA_SSE_FAILURE_RE = re.compile(
    r"can't find closing|status code:\s*400|400\s+bad request|ollama.*\b400\b",
    re.I,
)


def harness_profile(harness: Mapping[str, Any] | None) -> str:
    return str(((harness or {}).get("plan") or {}).get("profile") or "")


def is_combined_review_harness(harness: Mapping[str, Any] | None) -> bool:
    return harness_profile(harness) == COMBINED_REVIEW_PROFILE


def _tool_names(harness: Mapping[str, Any]) -> list[str]:
    tools = harness.get("tools") or {}
    executed = tools.get("executed") or []
    out: list[str] = []
    for row in executed:
        if isinstance(row, dict):
            name = str(row.get("name") or row.get("tool") or "").strip()
            if name:
                out.append(name)
        elif row:
            out.append(str(row))
    return out


def assert_combined_review_sse_turn(
    *,
    turn: int,
    error: str,
    events: Sequence[str],
    answer_chars: int,
    harness: Mapping[str, Any] | None,
    min_answer_chars: int = 50,
) -> list[str]:
    """Return human-readable failure lines; empty list means PASS."""
    if not is_combined_review_harness(harness):
        return []

    fails: list[str] = []
    prefix = f"T{turn} combined_review"

    if error:
        fails.append(f"{prefix} SSE error: {error}")
    if error and _OLLAMA_SSE_FAILURE_RE.search(error):
        fails.append(f"{prefix} Ollama/catalog wire-format regression: {error[:200]}")

    event_set = {str(e) for e in events}
    if "error" in event_set:
        fails.append(f"{prefix} SSE stream contained error event")
    if "done" not in event_set:
        fails.append(f"{prefix} missing done event (events={sorted(event_set)})")
    if answer_chars < min_answer_chars:
        fails.append(f"{prefix} answer too short ({answer_chars} < {min_answer_chars} chars)")

    h = harness or {}
    runtime_mode = str(h.get("runtime_mode") or "")
    if runtime_mode != "catalog_tool_loop":
        fails.append(f"{prefix} runtime_mode={runtime_mode!r} want catalog_tool_loop")

    tools_allowed = list((h.get("plan") or {}).get("tools_allowed") or [])
    if "fetch_evidence_by_id" not in tools_allowed:
        fails.append(f"{prefix} plan.tools_allowed missing fetch_evidence_by_id: {tools_allowed}")

    executed = _tool_names(h)
    if "fetch_evidence_by_id" not in executed:
        fails.append(f"{prefix} tools.executed missing fetch_evidence_by_id: {executed}")

    t0_errs = list((h.get("tier0_integrity") or {}).get("errors") or [])
    if t0_errs:
        fails.append(f"{prefix} tier0_integrity.errors: {t0_errs}")

    return fails


__all__ = [
    "COMBINED_REVIEW_PROFILE",
    "assert_combined_review_sse_turn",
    "harness_profile",
    "is_combined_review_harness",
]
