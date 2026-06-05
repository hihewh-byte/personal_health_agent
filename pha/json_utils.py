"""Robust JSON extraction from LLM outputs (polite preambles, markdown fences, etc.)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

_UNQUOTED_VALUE_RE = re.compile(
    r'(:\s*)([^"\s\[\]{}][^,\}\]]*?)(\s*[,}\]])',
)


def sanitize_unquoted_json_values(text: str) -> str:
    """
    Quote bare tokens after ``:`` so ``9hr 11min`` / ``72 bpm`` become valid JSON strings.
    """
    s = text or ""

    def _repl(m: re.Match[str]) -> str:
        prefix, inner, suffix = m.group(1), m.group(2), m.group(3)
        val = (inner or "").strip()
        if not val:
            return m.group(0)
        low = val.lower()
        if low in ("true", "false", "null"):
            return m.group(0)
        if val[0] in "\"'{[":
            return m.group(0)
        if re.match(r"^[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?$", val):
            return m.group(0)
        escaped = val.replace("\\", "\\\\").replace('"', '\\"')
        return f'{prefix}"{escaped}"{suffix}'

    return _UNQUOTED_VALUE_RE.sub(_repl, s)


def extract_first_balanced_json_object(text: str) -> str | None:
    """
    Return substring from first ``{`` through its matching ``}``, respecting
    string literals so nested braces inside quotes do not confuse depth.
    """
    s = text or ""
    start = s.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return None


def extract_bracket_array_segment(text: str) -> Optional[str]:
    """Extract from first ``[`` through last ``]``, or tail from ``[`` if truncated."""
    s = text or ""
    start = s.find("[")
    if start < 0:
        return None
    end = s.rfind("]")
    if end > start:
        return s[start : end + 1]
    return s[start:]


def repair_truncated_brackets(segment: str) -> str:
    """
    Close unbalanced ``[`` / ``{`` when model output was cut off mid-stream.
    Arrays are closed before objects (e.g. ``{"results": [ {...} `` → ``]}``).
    """
    seg = (segment or "").strip()
    if not seg:
        return seg
    open_brackets = seg.count("[") - seg.count("]")
    open_braces = seg.count("{") - seg.count("}")
    if open_brackets < 0:
        open_brackets = 0
    if open_braces < 0:
        open_braces = 0
    return seg + ("]" * open_brackets) + ("}" * open_braces)


def _try_load_json(candidate: str) -> Any:
    """``json.loads`` with unquoted-value sanitization."""
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        cleaned = sanitize_unquoted_json_values(candidate)
        if cleaned != candidate:
            return json.loads(cleaned)
        raise


def _loads_json_candidate(candidate: str) -> Any:
    return _try_load_json(candidate)


def salvage_truncated_json(raw_output: str) -> Any:
    """
    Last-resort recovery: bracket slice, auto-close ``]`` / ``}``, wrap bare arrays as objects.
    """
    text = (raw_output or "").strip()
    if not text:
        raise ValueError("empty output")

    candidates: list[str] = []

    arr = extract_bracket_array_segment(text)
    if arr:
        candidates.append(arr)
        candidates.append(repair_truncated_brackets(arr))

    obj_start = text.find("{")
    if obj_start >= 0:
        tail = text[obj_start:]
        candidates.append(tail)
        candidates.append(repair_truncated_brackets(tail))

    balanced = extract_first_balanced_json_object(text)
    if balanced:
        candidates.append(balanced)
        candidates.append(repair_truncated_brackets(balanced))

    seen: set[str] = set()
    last_err: Optional[Exception] = None
    for cand in candidates:
        cand = cand.strip()
        if not cand or cand in seen:
            continue
        seen.add(cand)
        try:
            parsed = _try_load_json(cand)
            logger.info("JSON salvage succeeded on truncated/cut model output")
            return parsed
        except (json.JSONDecodeError, ValueError) as exc:
            last_err = exc
            continue

    if last_err:
        raise ValueError(f"salvage failed: {last_err}") from last_err
    raise ValueError("salvage failed: no candidate")


def safe_json_parse(raw_output: str) -> Any:
    """
    Force-extract the first JSON object or array from model text.

    Tries: fenced code block → balanced ``{...}`` → greedy match → truncated salvage.
    """
    text = (raw_output or "").strip()
    if not text:
        raise ValueError("No valid JSON found in model output")

    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()

    balanced = extract_first_balanced_json_object(text)
    if balanced:
        try:
            return _loads_json_candidate(balanced)
        except json.JSONDecodeError:
            try:
                return _loads_json_candidate(repair_truncated_brackets(balanced))
            except json.JSONDecodeError:
                pass

    match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
    if match:
        frag = match.group(0)
        for cand in (frag, repair_truncated_brackets(frag)):
            try:
                return _loads_json_candidate(cand)
            except json.JSONDecodeError:
                continue

    try:
        return salvage_truncated_json(raw_output)
    except ValueError:
        pass

    raise ValueError("No valid JSON found in model output")


def robust_json_cleaner(raw_output: str) -> dict[str, Any]:
    """Stage 3A alias — force-extract a JSON object from model prose/fences."""
    return safe_json_object(raw_output)


def safe_json_object(raw_output: str) -> dict[str, Any]:
    """Like :func:`safe_json_parse` but require a top-level object."""
    parsed = safe_json_parse(raw_output)
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, list):
        if parsed and isinstance(parsed[0], dict):
            return {"results": parsed}
        return {"results": parsed}
    raise ValueError("Model JSON is not an object")
