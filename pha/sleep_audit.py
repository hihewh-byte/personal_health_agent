"""Post-import sleep audit — log overlapping segments when daily sleep looks inflated."""

from __future__ import annotations

import logging
import statistics
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pha.date_parser import safe_parse_datetime
from pha.models import WearableDailySummary
from pha.sqlite_storage import query_sleep_segments_for_day

logger = logging.getLogger(__name__)

AVG_SLEEP_AUDIT_THRESHOLD_H = 12.0
DAY_SLEEP_AUDIT_THRESHOLD_H = 10.0


def _parse_dt(raw: str) -> Optional[datetime]:
    return safe_parse_datetime(raw)


def _overlap_seconds(a: Tuple[datetime, datetime], b: Tuple[datetime, datetime]) -> float:
    start = max(a[0], b[0])
    end = min(a[1], b[1])
    if end <= start:
        return 0.0
    return (end - start).total_seconds()


def _find_overlapping_pairs(
    segments: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    parsed: List[Tuple[datetime, datetime, Dict[str, Any]]] = []
    for seg in segments:
        if int(seg.get("is_awake") or 0):
            continue
        start = _parse_dt(seg.get("start_time", ""))
        end = _parse_dt(seg.get("end_time", ""))
        if start is None or end is None or end <= start:
            continue
        parsed.append((start, end, seg))

    pairs: List[Dict[str, Any]] = []
    for i in range(len(parsed)):
        for j in range(i + 1, len(parsed)):
            s1, e1, raw1 = parsed[i]
            s2, e2, raw2 = parsed[j]
            ov = _overlap_seconds((s1, e1), (s2, e2))
            if ov <= 0:
                continue
            pairs.append(
                {
                    "overlap_seconds": round(ov, 1),
                    "segment_a": {
                        "source": raw1.get("source_name"),
                        "start": raw1.get("start_time"),
                        "end": raw1.get("end_time"),
                        "sample_id": raw1.get("sample_id"),
                    },
                    "segment_b": {
                        "source": raw2.get("source_name"),
                        "start": raw2.get("start_time"),
                        "end": raw2.get("end_time"),
                        "sample_id": raw2.get("sample_id"),
                    },
                },
            )
    return pairs


def audit_sleep_after_import(
    user_id: str,
    rows: Sequence[WearableDailySummary],
    *,
    reference_date: Optional[date] = None,
    avg_threshold_h: float = AVG_SLEEP_AUDIT_THRESHOLD_H,
) -> None:
    """
    If recent average sleep exceeds *avg_threshold_h*, dump raw overlapping asleep
    segments to server logs for manual review of ``compute_sleep_hours_union``.
    """
    if not rows:
        return

    uid = (user_id or "default").strip() or "default"
    ref = reference_date or max(r.day for r in rows)
    window_start = ref - timedelta(days=6)
    recent = [r for r in rows if window_start <= r.day <= ref]
    sleep_vals = [float(r.sleep_hours) for r in recent if r.sleep_hours is not None]
    if len(sleep_vals) < 2:
        return

    avg_sleep = statistics.mean(sleep_vals)
    if avg_sleep <= avg_threshold_h:
        return

    logger.warning(
        "SLEEP AUDIT user=%s: 7d avg sleep=%.2fh > %.1fh — dumping overlapping segments",
        uid,
        avg_sleep,
        avg_threshold_h,
    )

    flagged_days = sorted(
        {r.day for r in recent if r.sleep_hours is not None and r.sleep_hours > DAY_SLEEP_AUDIT_THRESHOLD_H},
    )
    if not flagged_days:
        flagged_days = sorted({r.day for r in recent}, reverse=True)[:3]

    for day in flagged_days:
        raw_segs = query_sleep_segments_for_day(uid, day)
        row = next((r for r in recent if r.day == day), None)
        daily_h = row.sleep_hours if row else None
        overlaps = _find_overlapping_pairs(raw_segs)
        asleep_raw = [s for s in raw_segs if not int(s.get("is_awake") or 0)]
        logger.warning(
            "SLEEP AUDIT day=%s daily_sleep_hours=%s asleep_segments=%d overlap_pairs=%d",
            day.isoformat(),
            daily_h,
            len(asleep_raw),
            len(overlaps),
        )
        for seg in asleep_raw:
            logger.warning(
                "SLEEP AUDIT segment day=%s source=%r start=%s end=%s sample_id=%s",
                day.isoformat(),
                seg.get("source_name"),
                seg.get("start_time"),
                seg.get("end_time"),
                seg.get("sample_id"),
            )
        for pair in overlaps:
            logger.warning(
                "SLEEP AUDIT overlap day=%s overlap_s=%s A=%s B=%s",
                day.isoformat(),
                pair["overlap_seconds"],
                pair["segment_a"],
                pair["segment_b"],
            )
