"""Apple Health HKWorkout persistence and 90d rollup (Wave 3d-δ-b)."""

from __future__ import annotations

import gc
import logging
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pha.date_parser import safe_parse_datetime
from pha.models import WearableDailySummary
from pha.sqlite_storage import (
    STREAM_COMMIT_EVERY,
    _connect,
    configure_sqlite_for_bulk_import,
    init_schema,
    load_wearable_rows,
    upsert_wearable_rows,
)

logger = logging.getLogger(__name__)

# Apple Watch highlights: "8 Workouts In the last 4 weeks"
WORKOUT_RECENT_WINDOW_DAYS = 28


@dataclass(frozen=True)
class WorkoutSessionRow:
    user_id: str
    day: date
    start_time: datetime
    end_time: datetime
    activity_type: str
    duration_sec: float
    hr_min_bpm: Optional[float]
    hr_max_bpm: Optional[float]
    energy_kcal: Optional[float]
    sample_id: str


def make_workout_sample_id(
    *,
    activity_type: str,
    start_raw: str,
    end_raw: str,
    source_name: str,
) -> str:
    return "|".join(
        [
            "HKWorkout",
            (activity_type or "").strip(),
            start_raw.strip(),
            end_raw.strip(),
            (source_name or "").strip(),
        ],
    )


def init_workout_schema(conn: Optional[sqlite3.Connection] = None) -> None:
    own = conn is None
    db = conn or _connect()
    try:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS wearable_workout_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                day TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                activity_type TEXT,
                duration_sec REAL,
                hr_min_bpm REAL,
                hr_max_bpm REAL,
                energy_kcal REAL,
                sample_id TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_workout_session_sample
                ON wearable_workout_sessions (user_id, sample_id);
            CREATE INDEX IF NOT EXISTS idx_workout_session_user_day
                ON wearable_workout_sessions (user_id, day);
            CREATE INDEX IF NOT EXISTS idx_workout_session_user_start
                ON wearable_workout_sessions (user_id, start_time);
            """,
        )
        db.commit()
    finally:
        if own:
            db.close()


class WorkoutSessionBatchWriter:
    def __init__(self, user_id: str) -> None:
        init_schema()
        init_workout_schema()
        self.user_id = (user_id or "default").strip() or "default"
        self._conn = _connect()
        configure_sqlite_for_bulk_import(self._conn)
        self._buffer: List[tuple] = []
        self.total_written = 0

    def add_session(self, session: WorkoutSessionRow) -> None:
        self._buffer.append(
            (
                session.user_id,
                session.day.isoformat(),
                session.start_time.isoformat(),
                session.end_time.isoformat(),
                session.activity_type or "",
                session.duration_sec,
                session.hr_min_bpm,
                session.hr_max_bpm,
                session.energy_kcal,
                session.sample_id,
            ),
        )
        if len(self._buffer) >= STREAM_COMMIT_EVERY:
            self.flush()

    def flush(self) -> int:
        if not self._buffer:
            return 0
        before = self._conn.total_changes
        self._conn.executemany(
            """
            INSERT OR IGNORE INTO wearable_workout_sessions (
                user_id, day, start_time, end_time, activity_type,
                duration_sec, hr_min_bpm, hr_max_bpm, energy_kcal, sample_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            self._buffer,
        )
        self._conn.commit()
        inserted = self._conn.total_changes - before
        self.total_written += inserted
        self._buffer.clear()
        gc.collect()
        return inserted

    def close(self) -> int:
        try:
            self.flush()
            return self.total_written
        finally:
            self._conn.close()


def clear_workout_sessions(user_id: Optional[str] = None) -> None:
    init_workout_schema()
    conn = _connect()
    try:
        if user_id:
            uid = user_id.strip() or "default"
            conn.execute("DELETE FROM wearable_workout_sessions WHERE user_id = ?", (uid,))
        else:
            conn.execute("DELETE FROM wearable_workout_sessions")
        conn.commit()
    finally:
        conn.close()


def count_workout_sessions_in_range(
    user_id: str,
    start: date,
    end: date,
) -> int:
    init_workout_schema()
    uid = (user_id or "default").strip() or "default"
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) AS c FROM wearable_workout_sessions
            WHERE user_id = ? AND day >= ? AND day <= ?
            """,
            (uid, start.isoformat(), end.isoformat()),
        ).fetchone()
        return int(row["c"] or 0) if row else 0
    finally:
        conn.close()


def query_workout_sessions_in_range(
    user_id: str,
    start: date,
    end: date,
) -> List[Dict[str, Any]]:
    init_workout_schema()
    uid = (user_id or "default").strip() or "default"
    conn = _connect()
    try:
        cur = conn.execute(
            """
            SELECT day, start_time, end_time, activity_type, duration_sec,
                   hr_min_bpm, hr_max_bpm, energy_kcal, sample_id
            FROM wearable_workout_sessions
            WHERE user_id = ? AND day >= ? AND day <= ?
            ORDER BY start_time
            """,
            (uid, start.isoformat(), end.isoformat()),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def rolling_28d_workout_counts(
    user_id: str,
    window_start: date,
    window_end: date,
) -> List[float]:
    """For each anchor day in [window_start, window_end], count sessions in prior 28 days."""
    init_workout_schema()
    uid = (user_id or "default").strip() or "default"
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT day FROM wearable_workout_sessions
            WHERE user_id = ? AND day >= ? AND day <= ?
            """,
            (
                uid,
                (window_start - timedelta(days=WORKOUT_RECENT_WINDOW_DAYS)).isoformat(),
                window_end.isoformat(),
            ),
        ).fetchall()
    finally:
        conn.close()

    by_day: Dict[date, int] = {}
    for row in rows:
        d = date.fromisoformat(str(row["day"]))
        by_day[d] = by_day.get(d, 0) + 1

    counts: List[float] = []
    d = window_start
    while d <= window_end:
        start = d - timedelta(days=WORKOUT_RECENT_WINDOW_DAYS - 1)
        total = sum(by_day.get(start + timedelta(days=i), 0) for i in range(WORKOUT_RECENT_WINDOW_DAYS))
        counts.append(float(total))
        d += timedelta(days=1)
    return counts


def baseline_workout_count_recent(
    user_id: str,
    *,
    reference_date: date,
    window_start: date,
    window_end: date,
) -> Optional[Tuple[float, float, float, str]]:
    """28d session count at reference_date; range from rolling 28d counts in 90d window."""
    uid = (user_id or "default").strip() or "default"
    last_start = reference_date - timedelta(days=WORKOUT_RECENT_WINDOW_DAYS - 1)
    current = float(count_workout_sessions_in_range(uid, last_start, reference_date))
    rolls = rolling_28d_workout_counts(uid, window_start, window_end)
    if rolls:
        return current, min(rolls), max(rolls), "sessions"
    if current > 0:
        return current, current, current, "sessions"
    return None


def baseline_workout_hr_range_90d(
    user_id: str,
    window_start: date,
    window_end: date,
) -> Optional[Tuple[float, float, float, str]]:
    sessions = query_workout_sessions_in_range(user_id, window_start, window_end)
    mins = [float(s["hr_min_bpm"]) for s in sessions if s.get("hr_min_bpm") is not None]
    maxs = [float(s["hr_max_bpm"]) for s in sessions if s.get("hr_max_bpm") is not None]
    if not mins or not maxs:
        return None
    wmin, wmax = min(mins), max(maxs)
    mid = (wmin + wmax) / 2.0
    return mid, wmin, wmax, "bpm"


def rebuild_workout_daily_rollup(user_id: str) -> int:
    """Aggregate sessions → wearable_daily workout_* columns."""
    init_workout_schema()
    uid = (user_id or "default").strip() or "default"
    conn = _connect()
    try:
        days = [
            date.fromisoformat(str(row[0]))
            for row in conn.execute(
                "SELECT DISTINCT day FROM wearable_workout_sessions WHERE user_id = ?",
                (uid,),
            ).fetchall()
        ]
    finally:
        conn.close()

    if not days:
        return 0

    rows = load_wearable_rows(uid)
    by_day = {r.day: r for r in rows}
    updated = 0

    for d in sorted(days):
        sessions = query_workout_sessions_in_range(uid, d, d)
        if not sessions:
            continue
        count = len(sessions)
        mins = [float(s["hr_min_bpm"]) for s in sessions if s.get("hr_min_bpm") is not None]
        maxs = [float(s["hr_max_bpm"]) for s in sessions if s.get("hr_max_bpm") is not None]
        row = by_day.get(d)
        if row is None:
            row = WearableDailySummary(user_id=uid, day=d)
            rows.append(row)
            by_day[d] = row
        row.workout_session_count = count
        row.workout_hr_min_bpm = min(mins) if mins else None
        row.workout_hr_max_bpm = max(maxs) if maxs else None
        updated += 1

    if rows:
        upsert_wearable_rows(rows, sync_index_from_daily=True)
    return updated


def baselines_for_workout_compare(
    user_id: str,
    *,
    reference_date: date,
    window_start: date,
    window_end: date,
) -> Dict[str, Tuple[float, float, float, str]]:
    out: Dict[str, Tuple[float, float, float, str]] = {}
    count_base = baseline_workout_count_recent(
        user_id,
        reference_date=reference_date,
        window_start=window_start,
        window_end=window_end,
    )
    if count_base:
        out["workout_count_recent"] = count_base
    hr_base = baseline_workout_hr_range_90d(user_id, window_start, window_end)
    if hr_base:
        out["workout_heart_rate_range_bpm"] = hr_base
    return out
