"""Sleep interval union + source priority (Watch > iPhone > other)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Sequence, Tuple


@dataclass(frozen=True)
class SleepSegment:
    start: datetime
    end: datetime
    source_name: str = ""
    sample_id: str = ""

    def duration_seconds(self) -> float:
        return max(0.0, (self.end - self.start).total_seconds())


def _source_priority(source_name: str) -> int:
    s = (source_name or "").lower()
    if "watch" in s:
        return 0
    if "iphone" in s or "phone" in s or "ios" in s:
        return 1
    return 2


def _merge_intervals(intervals: List[Tuple[datetime, datetime]]) -> List[Tuple[datetime, datetime]]:
    if not intervals:
        return []
    sorted_iv = sorted(intervals, key=lambda x: x[0])
    merged: List[Tuple[datetime, datetime]] = [sorted_iv[0]]
    for start, end in sorted_iv[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _subtract_interval(
    segment: Tuple[datetime, datetime],
    covered: List[Tuple[datetime, datetime]],
) -> List[Tuple[datetime, datetime]]:
    """Return parts of *segment* not covered by *covered* (merged union)."""
    start, end = segment
    if start >= end or not covered:
        return [(start, end)]
    pieces: List[Tuple[datetime, datetime]] = [(start, end)]
    for cov_start, cov_end in covered:
        next_pieces: List[Tuple[datetime, datetime]] = []
        for p_start, p_end in pieces:
            if p_end <= cov_start or p_start >= cov_end:
                next_pieces.append((p_start, p_end))
                continue
            if p_start < cov_start:
                next_pieces.append((p_start, cov_start))
            if p_end > cov_end:
                next_pieces.append((cov_end, p_end))
        pieces = next_pieces
        if not pieces:
            break
    return [(a, b) for a, b in pieces if b > a]


def compute_sleep_hours_union(segments: Sequence[SleepSegment]) -> Tuple[float, float]:
    """
    Union of asleep intervals with Watch priority over iPhone on overlaps.

    Returns (sleep_hours, awake_hours_placeholder) — awake tracked separately in importer.
    """
    if not segments:
        return 0.0, 0.0

    by_priority: dict[int, List[SleepSegment]] = {0: [], 1: [], 2: []}
    for seg in segments:
        if seg.end <= seg.start:
            continue
        pri = _source_priority(seg.source_name)
        by_priority[pri].append(seg)

    covered: List[Tuple[datetime, datetime]] = []
    accepted: List[Tuple[datetime, datetime]] = []

    for pri in (0, 1, 2):
        for seg in sorted(by_priority[pri], key=lambda s: s.start):
            interval = (seg.start, seg.end)
            uncovered = _subtract_interval(interval, covered)
            for part in uncovered:
                accepted.append(part)
            covered = _merge_intervals(covered + uncovered)

    union = _merge_intervals(accepted)
    total_seconds = sum((e - s).total_seconds() for s, e in union)
    return total_seconds / 3600.0, 0.0


def sleep_stage_kind_from_hk_value(value: str) -> str:
    """Classify HKCategoryTypeIdentifierSleepAnalysis value string."""
    v = (value or "").lower()
    if "awake" in v:
        return "awake"
    if "deep" in v:
        return "deep"
    if "rem" in v:
        return "rem"
    if "core" in v:
        return "core"
    if "asleep" in v and "inbed" not in v:
        return "asleep"
    return "unknown"


def sleep_stage_kind_from_sample_id(sample_id: str) -> str:
    """Parse stage from ``make_sleep_sample_id`` pipe-delimited id (value in 4th field)."""
    parts = (sample_id or "").split("|")
    if len(parts) < 4:
        return "unknown"
    return sleep_stage_kind_from_hk_value(parts[3])


def make_sleep_sample_id(
    *,
    record_type: str,
    start_raw: str,
    end_raw: str,
    value: str,
    source_name: str,
) -> str:
    return "|".join(
        [
            record_type,
            start_raw.strip(),
            end_raw.strip(),
            (value or "").strip(),
            (source_name or "").strip(),
        ],
    )
