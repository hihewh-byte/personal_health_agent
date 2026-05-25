"""Parse explicit calendar date ranges from user chat messages (v2.2.1)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from pha.date_parser import safe_parse_date
from pha.health_data import effective_query_reference_date

_ISO_RANGE_RE = re.compile(
    r"(20\d{2}|19\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\s*(?:到|至|—|-|~|～)\s*"
    r"(20\d{2}|19\d{2})[-/.](\d{1,2})[-/.](\d{1,2})",
    re.I,
)
_CN_RANGE_RE = re.compile(
    r"(20\d{2}|19\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*"
    r"(?:到|至|—|-|~|～)\s*"
    r"(20\d{2}|19\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日",
    re.I,
)

_META_RANGE_QUESTION_RE = re.compile(
    r"日期范围|时间范围|精确日期|哪段时间|什么时候到|从哪天|到哪一天|数据区间",
    re.I,
)

_SNAPSHOT_SPAN_RE = re.compile(
    r"User Data Snapshot[^）)]*?"
    r"(\d{4}-\d{2}-\d{2})\s*[~～\-至到]+\s*(\d{4}-\d{2}-\d{2})",
    re.I,
)


@dataclass(frozen=True)
class ParsedDateRange:
    start: date
    end: date

    def iso_span(self) -> str:
        return f"{self.start.isoformat()}～{self.end.isoformat()}"


def _triplet_to_date(y: str, m: str, d: str) -> Optional[date]:
    try:
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def parse_user_date_range(text: str) -> Optional[ParsedDateRange]:
    """Extract inclusive [start, end] from explicit user calendar spans."""
    raw = (text or "").strip()
    if not raw:
        return None
    for pat in (_ISO_RANGE_RE, _CN_RANGE_RE):
        m = pat.search(raw)
        if not m:
            continue
        start = _triplet_to_date(m.group(1), m.group(2), m.group(3))
        end = _triplet_to_date(m.group(4), m.group(5), m.group(6))
        if start is None or end is None:
            continue
        if end < start:
            start, end = end, start
        ref = effective_query_reference_date()
        if end > ref:
            end = ref
        return ParsedDateRange(start=start, end=end)
    return None


def is_meta_date_range_question(text: str) -> bool:
    return bool(_META_RANGE_QUESTION_RE.search(text or ""))


def extract_snapshot_span_from_text(text: str) -> Optional[ParsedDateRange]:
    """Pull ``start~end`` from a prior ``User Data Snapshot`` line."""
    m = _SNAPSHOT_SPAN_RE.search(text or "")
    if not m:
        return None
    s = safe_parse_date(m.group(1))
    e = safe_parse_date(m.group(2))
    if s is None or e is None:
        return None
    if e < s:
        s, e = e, s
    return ParsedDateRange(start=s, end=e)


def default_wearable_window(
    user_message: str,
    *,
    reference: Optional[date] = None,
) -> ParsedDateRange:
    """Explicit user range wins; else rolling window from keywords."""
    explicit = parse_user_date_range(user_message)
    if explicit:
        return explicit
    ref = reference or effective_query_reference_date()
    text = user_message or ""
    days = 90
    if "一年" in text or "365" in text or "12个月" in text or "12 个月" in text:
        days = 365
    elif "6个月" in text or "半年" in text:
        days = 180
    elif re.search(r"30\s*天|一个月|1\s*个月", text) and "90" not in text:
        days = 30
    elif any(k in text for k in ("3个月", "三个月", "3 个月", "近三月", "最近3个月", "90天", "90 天")):
        days = 90
    start = ref - timedelta(days=max(1, days) - 1)
    return ParsedDateRange(start=start, end=ref)
