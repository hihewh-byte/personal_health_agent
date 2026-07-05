"""SQLite persistence for PHA wearable daily summaries and indexed metric samples."""

from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from pha.date_parser import safe_parse_date, safe_parse_datetime
from pha.models import WearableDailySummary

logger = logging.getLogger(__name__)

from pha.sqlite_connection import (
    configure_sqlite_for_bulk_import,
    connect_pooled as _connect,
    ensure_schema,
    open_connection,
    register_schema_initializer,
    release_connection as _release_connection,
)

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = _PACKAGE_ROOT / "data"
DEFAULT_DB_PATH = DATA_DIR / "pha_storage.db"

_WEARABLE_DATA_BATCH = 5000
STREAM_COMMIT_EVERY = 10_000

METRIC_HEART_RATE = "heart_rate"

# metric_type values stored in wearable_data (timestamp = day-level sample, noon UTC-naive)
METRIC_STEPS = "steps"
METRIC_HRV = "hrv"
METRIC_SLEEP = "sleep"
METRIC_RHR = "rhr"
METRIC_AWAKE = "awake_duration"
METRIC_ACTIVE_ENERGY = "active_energy"
METRIC_SPO2 = "spo2"
METRIC_RESPIRATORY_RATE = "respiratory_rate"
METRIC_VO2MAX = "vo2max"
METRIC_WRIST_TEMP = "wrist_temp"

_WEARABLE_DAILY_EXTENSION_COLS = (
    "spo2_pct",
    "respiratory_rate_bpm",
    "vo2max_ml_kg_min",
    "wrist_temp_c",
    "sleep_deep_hours",
    "sleep_rem_hours",
    "workout_session_count",
    "workout_hr_min_bpm",
    "workout_hr_max_bpm",
)
_WEARABLE_DAILY_DATA_COLS = (
    "user_id",
    "day",
    "steps",
    "resting_heart_rate_bpm",
    "hrv_rmssd_ms",
    "sleep_hours",
    "awake_duration_hours",
    "sleep_start_time",
    "active_energy_kcal",
) + _WEARABLE_DAILY_EXTENSION_COLS


def _wearable_daily_upsert_sql() -> str:
    cols = ", ".join(_WEARABLE_DAILY_DATA_COLS)
    placeholders = ", ".join("?" for _ in _WEARABLE_DAILY_DATA_COLS)
    updates = ",\n                    ".join(
        f"{c}=excluded.{c}"
        for c in _WEARABLE_DAILY_DATA_COLS
        if c not in ("user_id", "day")
    )
    return f"""
                INSERT INTO wearable_daily (
                    {cols}, updated_at
                ) VALUES ({placeholders}, datetime('now'))
                ON CONFLICT(user_id, day) DO UPDATE SET
                    {updates},
                    updated_at=datetime('now')
                """


def get_db_path() -> Path:
    return DEFAULT_DB_PATH


def ensure_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def database_exists() -> bool:
    return get_db_path().is_file()


class WearableDataBatchWriter:
    """
    Stream inserts into ``wearable_data`` with periodic commit.

    Never holds more than ``STREAM_COMMIT_EVERY`` rows in memory.
    """

    def __init__(self, user_id: str) -> None:
        self.user_id = user_id.strip() or "default"
        self._conn = open_connection(bulk_import=True)
        self._buffer: List[tuple[str, str, str, float, str]] = []
        self.total_written = 0
        self.total_ignored = 0

    def add_sample(
        self,
        metric_type: str,
        ts: datetime,
        value: float,
        *,
        sample_id: str,
    ) -> bool:
        """Insert sample; return False if duplicate (``INSERT OR IGNORE``)."""
        sid = (sample_id or "").strip() or f"{metric_type}|{ts.isoformat()}|{value}"
        self._buffer.append((self.user_id, metric_type, ts.isoformat(), float(value), sid))
        if len(self._buffer) >= STREAM_COMMIT_EVERY:
            self.flush()
        return True

    def flush(self) -> int:
        if not self._buffer:
            return 0
        n = len(self._buffer)
        before = self._conn.total_changes
        self._conn.executemany(
            """
            INSERT OR IGNORE INTO wearable_data
                (user_id, metric_type, timestamp, value, sample_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            self._buffer,
        )
        self._conn.commit()
        inserted = self._conn.total_changes - before
        ignored = n - inserted
        self.total_written += inserted
        self.total_ignored += ignored
        self._buffer.clear()
        return inserted

    def close(self) -> int:
        """Flush remaining buffer, close connection; return total rows inserted."""
        try:
            self.flush()
            return self.total_written
        finally:
            _release_connection(self._conn)


class SleepSegmentBatchWriter:
    """Persist raw sleep intervals for union re-aggregation."""

    def __init__(self, user_id: str) -> None:
        self.user_id = user_id.strip() or "default"
        self._conn = open_connection(bulk_import=True)
        self._buffer: List[tuple] = []
        self.total_written = 0

    def add_segment(
        self,
        day: date,
        start: datetime,
        end: datetime,
        *,
        source_name: str,
        sample_id: str,
        is_awake: bool = False,
    ) -> None:
        self._buffer.append(
            (
                self.user_id,
                day.isoformat(),
                start.isoformat(),
                end.isoformat(),
                source_name or "",
                sample_id,
                1 if is_awake else 0,
            ),
        )
        if len(self._buffer) >= STREAM_COMMIT_EVERY:
            self.flush()

    def flush(self) -> int:
        if not self._buffer:
            return 0
        n = len(self._buffer)
        before = self._conn.total_changes
        self._conn.executemany(
            """
            INSERT OR IGNORE INTO wearable_sleep_segments (
                user_id, day, start_time, end_time, source_name, sample_id, is_awake
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            self._buffer,
        )
        self._conn.commit()
        inserted = self._conn.total_changes - before
        self.total_written += inserted
        self._buffer.clear()
        return inserted

    def close(self) -> int:
        try:
            self.flush()
            return self.total_written
        finally:
            _release_connection(self._conn)


def clear_wearable_storage(user_id: Optional[str] = None) -> None:
    """Delete all wearable_daily + wearable_data rows before a full re-import."""
    from pha.workout_storage import init_workout_schema

    ensure_schema()
    init_workout_schema()
    conn = _connect()
    try:
        if user_id:
            uid = user_id.strip() or "default"
            conn.execute("DELETE FROM wearable_data WHERE user_id = ?", (uid,))
            conn.execute("DELETE FROM wearable_sleep_segments WHERE user_id = ?", (uid,))
            conn.execute("DELETE FROM wearable_daily WHERE user_id = ?", (uid,))
            conn.execute("DELETE FROM wearable_workout_sessions WHERE user_id = ?", (uid,))
        else:
            conn.execute("DELETE FROM wearable_data")
            conn.execute("DELETE FROM wearable_sleep_segments")
            conn.execute("DELETE FROM wearable_daily")
            conn.execute("DELETE FROM wearable_workout_sessions")
        conn.commit()
        logger.info("Cleared wearable storage for user_id=%s", user_id or "ALL")
    finally:
        _release_connection(conn)


def get_max_wearable_timestamp(user_id: str) -> Optional[datetime]:
    init_schema()
    uid = user_id.strip() or "default"
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT MAX(timestamp) AS ts FROM wearable_data WHERE user_id = ?",
            (uid,),
        ).fetchone()
        if not row or not row["ts"]:
            return None
        return safe_parse_datetime(row["ts"])
    finally:
        _release_connection(conn)


def count_wearable_samples(user_id: str) -> int:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM wearable_data WHERE user_id = ?",
            (user_id.strip() or "default",),
        ).fetchone()
        return int(row["c"]) if row else 0
    finally:
        _release_connection(conn)


def upsert_wearable_daily_batch(
    rows: Sequence[WearableDailySummary],
    *,
    batch_size: int = 500,
) -> int:
    if not rows:
        return 0
    conn = open_connection(bulk_import=True)
    try:
        tuples = [_model_to_tuple(r) for r in rows]
        upsert_sql = _wearable_daily_upsert_sql()
        for i in range(0, len(tuples), batch_size):
            conn.executemany(
                upsert_sql,
                tuples[i : i + batch_size],
            )
            conn.commit()
        return len(rows)
    finally:
        _release_connection(conn)


def _apply_schema_migrations(db: sqlite3.Connection) -> None:
    db.executescript(
        """
            CREATE TABLE IF NOT EXISTS wearable_daily (
                user_id TEXT NOT NULL,
                day TEXT NOT NULL,
                steps INTEGER,
                resting_heart_rate_bpm REAL,
                hrv_rmssd_ms REAL,
                sleep_hours REAL,
                awake_duration_hours REAL,
                sleep_start_time TEXT,
                active_energy_kcal REAL,
                spo2_pct REAL,
                respiratory_rate_bpm REAL,
                vo2max_ml_kg_min REAL,
                wrist_temp_c REAL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (user_id, day)
            );
            CREATE INDEX IF NOT EXISTS idx_wearable_user_day
                ON wearable_daily (user_id, day);

            CREATE TABLE IF NOT EXISTS wearable_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                metric_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                value REAL
            );
            CREATE INDEX IF NOT EXISTS idx_user_metric_time
                ON wearable_data (user_id, metric_type, timestamp);
        """,
    )
    db.commit()
    _migrate_wearable_schema(db)
    _migrate_import_sync_schema(db)
    from pha.workout_storage import init_workout_schema

    init_workout_schema(db)


def init_schema(conn: Optional[sqlite3.Connection] = None) -> None:
    if conn is not None:
        _apply_schema_migrations(conn)
        return
    ensure_schema()


def _migrate_wearable_schema(db: sqlite3.Connection) -> None:
    daily_cols = {row[1] for row in db.execute("PRAGMA table_info(wearable_daily)")}
    altered = False
    if "active_energy_kcal" not in daily_cols:
        db.execute("ALTER TABLE wearable_daily ADD COLUMN active_energy_kcal REAL")
        altered = True
    for col in _WEARABLE_DAILY_EXTENSION_COLS:
        if col not in daily_cols:
            db.execute(f"ALTER TABLE wearable_daily ADD COLUMN {col} REAL")
            altered = True
    if altered:
        db.commit()

    cols = {row[1] for row in db.execute("PRAGMA table_info(wearable_data)")}
    if "sample_id" not in cols:
        db.execute("ALTER TABLE wearable_data ADD COLUMN sample_id TEXT")
    db.execute(
        """
        UPDATE wearable_data
        SET sample_id = user_id || '|' || metric_type || '|' || timestamp || '|' || CAST(value AS TEXT)
        WHERE sample_id IS NULL OR sample_id = ''
        """,
    )
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS wearable_sleep_segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            day TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            source_name TEXT,
            sample_id TEXT NOT NULL,
            is_awake INTEGER NOT NULL DEFAULT 0
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_wearable_data_sample
            ON wearable_data (user_id, sample_id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_sleep_segment_sample
            ON wearable_sleep_segments (user_id, sample_id);
        CREATE INDEX IF NOT EXISTS idx_sleep_segment_user_day
            ON wearable_sleep_segments (user_id, day);
        """,
    )
    db.commit()


def _migrate_import_sync_schema(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS import_sync_state (
            user_id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'never',
            last_sync_at TEXT,
            last_record_time TEXT,
            records_seen INTEGER DEFAULT 0,
            days_written INTEGER DEFAULT 0,
            wearable_samples_written INTEGER DEFAULT 0,
            sleep_segments INTEGER DEFAULT 0,
            steps_samples INTEGER DEFAULT 0,
            message TEXT,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """,
    )
    db.commit()


def upsert_import_sync_state(
    user_id: str,
    *,
    status: str,
    last_sync_at: Optional[str] = None,
    last_record_time: Optional[str] = None,
    records_seen: int = 0,
    days_written: int = 0,
    wearable_samples_written: int = 0,
    message: str = "",
) -> None:
    init_schema()
    uid = (user_id or "default").strip() or "default"
    counts = get_wearable_record_counts(uid)
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO import_sync_state (
                user_id, status, last_sync_at, last_record_time,
                records_seen, days_written, wearable_samples_written,
                sleep_segments, steps_samples, message, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(user_id) DO UPDATE SET
                status = excluded.status,
                last_sync_at = excluded.last_sync_at,
                last_record_time = excluded.last_record_time,
                records_seen = excluded.records_seen,
                days_written = excluded.days_written,
                wearable_samples_written = excluded.wearable_samples_written,
                sleep_segments = excluded.sleep_segments,
                steps_samples = excluded.steps_samples,
                message = excluded.message,
                updated_at = datetime('now')
            """,
            (
                uid,
                status,
                last_sync_at,
                last_record_time,
                records_seen,
                days_written,
                wearable_samples_written,
                counts["sleep_segments"],
                counts["steps_samples"],
                message,
            ),
        )
        conn.commit()
    finally:
        _release_connection(conn)


def clear_import_sync_state(user_id: str) -> None:
    init_schema()
    uid = (user_id or "default").strip() or "default"
    conn = _connect()
    try:
        conn.execute("DELETE FROM import_sync_state WHERE user_id = ?", (uid,))
        conn.commit()
    finally:
        _release_connection(conn)


def get_import_sync_state(user_id: str) -> Optional[dict]:
    init_schema()
    uid = (user_id or "default").strip() or "default"
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM import_sync_state WHERE user_id = ?",
            (uid,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        _release_connection(conn)


def get_wearable_record_counts(user_id: str) -> dict:
    """Counts for sync status UI (sleep segments, steps samples, daily rows)."""
    init_schema()
    uid = (user_id or "default").strip() or "default"
    conn = _connect()
    try:
        sleep_seg = conn.execute(
            """
            SELECT COUNT(*) FROM wearable_sleep_segments
            WHERE user_id = ? AND is_awake = 0
            """,
            (uid,),
        ).fetchone()[0]
        steps = conn.execute(
            "SELECT COUNT(*) FROM wearable_data WHERE user_id = ? AND metric_type = ?",
            (uid, METRIC_STEPS),
        ).fetchone()[0]
        heart = conn.execute(
            "SELECT COUNT(*) FROM wearable_data WHERE user_id = ? AND metric_type = ?",
            (uid, METRIC_HEART_RATE),
        ).fetchone()[0]
        daily_days = conn.execute(
            "SELECT COUNT(*) FROM wearable_daily WHERE user_id = ?",
            (uid,),
        ).fetchone()[0]
        workout_sessions = 0
        try:
            workout_sessions = conn.execute(
                "SELECT COUNT(*) FROM wearable_workout_sessions WHERE user_id = ?",
                (uid,),
            ).fetchone()[0]
        except sqlite3.OperationalError:
            pass
        return {
            "sleep_segments": int(sleep_seg),
            "steps_samples": int(steps),
            "heart_rate_samples": int(heart),
            "daily_days": int(daily_days),
            "workout_sessions": int(workout_sessions),
        }
    finally:
        _release_connection(conn)


def dedupe_wearable_data(user_id: Optional[str] = None) -> tuple[int, int]:
    """
    Remove duplicate wearable samples. Returns (wearable_data_removed, sleep_segments_removed).
    """
    conn = _connect()
    try:
        if user_id:
            uid = user_id.strip() or "default"
            before_wd = conn.execute(
                "SELECT COUNT(*) FROM wearable_data WHERE user_id = ?",
                (uid,),
            ).fetchone()[0]
            conn.execute(
                """
                DELETE FROM wearable_data
                WHERE user_id = ? AND rowid NOT IN (
                    SELECT MIN(rowid) FROM wearable_data
                    WHERE user_id = ?
                    GROUP BY user_id, sample_id, timestamp, value
                )
                """,
                (uid, uid),
            )
            before_seg = conn.execute(
                "SELECT COUNT(*) FROM wearable_sleep_segments WHERE user_id = ?",
                (uid,),
            ).fetchone()[0]
            conn.execute(
                """
                DELETE FROM wearable_sleep_segments
                WHERE user_id = ? AND rowid NOT IN (
                    SELECT MIN(rowid) FROM wearable_sleep_segments
                    WHERE user_id = ?
                    GROUP BY user_id, sample_id, start_time, end_time
                )
                """,
                (uid, uid),
            )
        else:
            before_wd = conn.execute("SELECT COUNT(*) FROM wearable_data").fetchone()[0]
            conn.execute(
                """
                DELETE FROM wearable_data
                WHERE rowid NOT IN (
                    SELECT MIN(rowid) FROM wearable_data
                    GROUP BY user_id, sample_id, timestamp, value
                )
                """,
            )
            before_seg = conn.execute("SELECT COUNT(*) FROM wearable_sleep_segments").fetchone()[0]
            conn.execute(
                """
                DELETE FROM wearable_sleep_segments
                WHERE rowid NOT IN (
                    SELECT MIN(rowid) FROM wearable_sleep_segments
                    GROUP BY user_id, sample_id, start_time, end_time
                )
                """,
            )
        conn.commit()
        if user_id:
            uid = user_id.strip() or "default"
            after_wd = conn.execute(
                "SELECT COUNT(*) FROM wearable_data WHERE user_id = ?",
                (uid,),
            ).fetchone()[0]
            after_seg = conn.execute(
                "SELECT COUNT(*) FROM wearable_sleep_segments WHERE user_id = ?",
                (uid,),
            ).fetchone()[0]
        else:
            after_wd = conn.execute("SELECT COUNT(*) FROM wearable_data").fetchone()[0]
            after_seg = conn.execute("SELECT COUNT(*) FROM wearable_sleep_segments").fetchone()[0]
        return int(before_wd - after_wd), int(before_seg - after_seg)
    finally:
        _release_connection(conn)


def query_sleep_segments_for_day(user_id: str, day: date) -> List[dict]:
    init_schema()
    uid = user_id.strip() or "default"
    conn = _connect()
    try:
        cur = conn.execute(
            """
            SELECT start_time, end_time, source_name, sample_id, is_awake
            FROM wearable_sleep_segments
            WHERE user_id = ? AND day = ?
            """,
            (uid, day.isoformat()),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        _release_connection(conn)


def query_sleep_segments_in_range(
    user_id: str,
    start_date: date,
    end_date: date,
) -> List[dict]:
    """All sleep segments in ``[start_date, end_date]`` (inclusive)."""
    init_schema()
    uid = user_id.strip() or "default"
    if end_date < start_date:
        start_date, end_date = end_date, start_date
    conn = _connect()
    try:
        cur = conn.execute(
            """
            SELECT day, start_time, end_time, source_name, sample_id, is_awake
            FROM wearable_sleep_segments
            WHERE user_id = ? AND day >= ? AND day <= ?
            ORDER BY day, start_time
            """,
            (uid, start_date.isoformat(), end_date.isoformat()),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        _release_connection(conn)


def query_wearable_hr_samples_in_range(
    user_id: str,
    start_date: date,
    end_date: date,
) -> List[tuple[datetime, float]]:
    """Heart-rate samples from ``wearable_data`` index (may be sparse)."""
    init_schema()
    uid = user_id.strip() or "default"
    if end_date < start_date:
        start_date, end_date = end_date, start_date
    conn = _connect()
    try:
        cur = conn.execute(
            """
            SELECT timestamp, value FROM wearable_data
            WHERE user_id = ? AND metric_type = ?
              AND substr(timestamp, 1, 10) >= ? AND substr(timestamp, 1, 10) <= ?
            ORDER BY timestamp
            """,
            (uid, METRIC_HEART_RATE, start_date.isoformat(), end_date.isoformat()),
        )
        out: List[tuple[datetime, float]] = []
        for row in cur.fetchall():
            ts = safe_parse_datetime(row["timestamp"])
            if ts is None or row["value"] is None:
                continue
            out.append((ts, float(row["value"])))
        return out
    finally:
        _release_connection(conn)


def resolve_import_watermark(user_id: str) -> Optional[datetime]:
    """Watermark for export.zip delta sync: ``import_sync_state.last_record_time`` else DB max sample."""
    uid = (user_id or "default").strip() or "default"
    state = get_import_sync_state(uid)
    if state:
        raw = state.get("last_record_time")
        if raw:
            dt = safe_parse_datetime(str(raw))
            if dt is not None:
                return dt
    return get_max_wearable_timestamp(uid)


def rebuild_wearable_daily_for_days(user_id: str, days: Sequence[date]) -> int:
    """Re-aggregate ``wearable_daily`` for specific days from ``wearable_data`` + sleep segments."""
    from collections import defaultdict

    from pha.wearable_daily_aggregator import (
        WearableDayMetricAgg,
        accumulate_wearable_sample,
        build_wearable_daily_summary,
    )

    uid = (user_id or "default").strip() or "default"
    unique_days = sorted({d for d in days if d})
    if not unique_days:
        return 0

    seg_by_day: Dict[date, List[dict]] = defaultdict(list)
    for raw in query_sleep_segments_in_range(uid, unique_days[0], unique_days[-1]):
        d = safe_parse_date(str(raw.get("day") or ""))
        if d is None or d not in unique_days:
            continue
        seg_by_day[d].append(raw)

    rows: List[WearableDailySummary] = []
    conn = _connect()
    try:
        for d in unique_days:
            day_s = d.isoformat()
            metrics = WearableDayMetricAgg()
            cur = conn.execute(
                """
                SELECT metric_type, timestamp, value, sample_id
                FROM wearable_data
                WHERE user_id = ? AND substr(timestamp, 1, 10) = ?
                """,
                (uid, day_s),
            )
            for row in cur.fetchall():
                if row["value"] is None:
                    continue
                accumulate_wearable_sample(
                    str(row["metric_type"] or ""),
                    float(row["value"]),
                    str(row["sample_id"] or ""),
                    metrics,
                )
            rows.append(
                build_wearable_daily_summary(
                    uid,
                    d,
                    metrics=metrics,
                    segment_rows=seg_by_day.get(d, []),
                ),
            )
    finally:
        _release_connection(conn)

    if rows:
        upsert_wearable_daily_batch(rows)
        sync_wearable_data_from_daily(rows, user_id=uid)
    return len(rows)


def rebuild_daily_sleep_from_segments(user_id: str) -> int:
    """Recompute daily sleep union + deep/REM stage hours from stored segments (single connection)."""
    from collections import defaultdict

    from pha.wearable_daily_aggregator import build_wearable_daily_summary

    uid = (user_id or "default").strip() or "default"
    conn = _connect()
    try:
        seg_rows = conn.execute(
            """
            SELECT day, start_time, end_time, source_name, sample_id, is_awake
            FROM wearable_sleep_segments
            WHERE user_id = ?
            ORDER BY day, start_time
            """,
            (uid,),
        ).fetchall()
        if not seg_rows:
            return 0

        by_day: Dict[str, List[dict]] = defaultdict(list)
        for row in seg_rows:
            by_day[str(row["day"])].append(dict(row))

        daily_by_day: Dict[date, WearableDailySummary] = {}
        for row in conn.execute(
            "SELECT * FROM wearable_daily WHERE user_id = ?",
            (uid,),
        ).fetchall():
            model = _row_to_model(row)
            daily_by_day[model.day] = model
    finally:
        _release_connection(conn)

    updates: List[WearableDailySummary] = []
    for day_s in sorted(by_day.keys()):
        d = safe_parse_date(day_s) or date.today()
        row = daily_by_day.get(d) or WearableDailySummary(user_id=uid, day=d)
        updates.append(
            build_wearable_daily_summary(
                uid,
                d,
                existing=row,
                segment_rows=by_day[day_s],
                sleep_only=True,
            ),
        )

    if updates:
        upsert_wearable_daily_batch(updates)
        sync_wearable_data_from_daily(updates, user_id=uid)
    return len(updates)


def _row_to_model(row: sqlite3.Row) -> WearableDailySummary:
    sleep_start: Optional[datetime] = None
    raw_start = row["sleep_start_time"]
    if raw_start:
        sleep_start = safe_parse_datetime(raw_start)
        if sleep_start is None:
            logger.warning("Invalid sleep_start_time in DB: %r", raw_start)
    parsed_day = safe_parse_date(row["day"])
    if parsed_day is None:
        logger.warning("Invalid day in wearable_daily: %r", row["day"])
        parsed_day = date.today()
    def _opt_float(col: str) -> Optional[float]:
        if col not in row.keys():
            return None
        raw = row[col]
        return float(raw) if raw is not None else None

    return WearableDailySummary(
        user_id=row["user_id"],
        day=parsed_day,
        steps=row["steps"],
        resting_heart_rate_bpm=row["resting_heart_rate_bpm"],
        hrv_rmssd_ms=row["hrv_rmssd_ms"],
        sleep_hours=row["sleep_hours"],
        sleep_deep_hours=_opt_float("sleep_deep_hours"),
        sleep_rem_hours=_opt_float("sleep_rem_hours"),
        awake_duration_hours=row["awake_duration_hours"],
        sleep_start_time=sleep_start,
        active_energy_kcal=_opt_float("active_energy_kcal"),
        spo2_pct=_opt_float("spo2_pct"),
        respiratory_rate_bpm=_opt_float("respiratory_rate_bpm"),
        vo2max_ml_kg_min=_opt_float("vo2max_ml_kg_min"),
        wrist_temp_c=_opt_float("wrist_temp_c"),
    )


def _model_to_tuple(row: WearableDailySummary) -> tuple:
    sleep_start_s = (
        row.sleep_start_time.isoformat() if row.sleep_start_time is not None else None
    )
    return (
        row.user_id,
        row.day.isoformat(),
        row.steps,
        row.resting_heart_rate_bpm,
        row.hrv_rmssd_ms,
        row.sleep_hours,
        row.awake_duration_hours,
        sleep_start_s,
        row.active_energy_kcal,
        row.spo2_pct,
        row.respiratory_rate_bpm,
        row.vo2max_ml_kg_min,
        row.wrist_temp_c,
        row.sleep_deep_hours,
        row.sleep_rem_hours,
        row.workout_session_count,
        row.workout_hr_min_bpm,
        row.workout_hr_max_bpm,
    )


def _day_timestamp(d: date) -> str:
    return datetime.combine(d, time(12, 0, 0)).isoformat()


def _daily_rows_to_wearable_data_tuples(rows: Sequence[WearableDailySummary]) -> List[tuple]:
    out: List[tuple] = []
    for row in rows:
        uid = row.user_id
        ts = _day_timestamp(row.day)
        if row.steps is not None:
            out.append((uid, METRIC_STEPS, ts, float(row.steps)))
        if row.hrv_rmssd_ms is not None:
            out.append((uid, METRIC_HRV, ts, float(row.hrv_rmssd_ms)))
        if row.sleep_hours is not None:
            out.append((uid, METRIC_SLEEP, ts, float(row.sleep_hours)))
        if row.resting_heart_rate_bpm is not None:
            out.append((uid, METRIC_RHR, ts, float(row.resting_heart_rate_bpm)))
        if row.awake_duration_hours is not None:
            out.append((uid, METRIC_AWAKE, ts, float(row.awake_duration_hours)))
        if row.active_energy_kcal is not None:
            out.append((uid, METRIC_ACTIVE_ENERGY, ts, float(row.active_energy_kcal)))
        if row.spo2_pct is not None:
            out.append((uid, METRIC_SPO2, ts, float(row.spo2_pct)))
        if row.respiratory_rate_bpm is not None:
            out.append((uid, METRIC_RESPIRATORY_RATE, ts, float(row.respiratory_rate_bpm)))
        if row.vo2max_ml_kg_min is not None:
            out.append((uid, METRIC_VO2MAX, ts, float(row.vo2max_ml_kg_min)))
        if row.wrist_temp_c is not None:
            out.append((uid, METRIC_WRIST_TEMP, ts, float(row.wrist_temp_c)))
    return out


def sync_wearable_data_from_daily(
    rows: Sequence[WearableDailySummary],
    *,
    user_id: Optional[str] = None,
) -> int:
    """
    Mirror daily rollups into ``wearable_data`` for indexed range scans.

    Only replaces **noon daily-mirror rows** (per metric + ``_day_timestamp``).
    Granular intraday samples (e.g. ``heart_rate``) are never deleted.
    """
    if not rows:
        return 0
    init_schema()
    uid_filter = (user_id or rows[0].user_id).strip() or "default"
    scoped = [r for r in rows if r.user_id == uid_filter] if user_id else list(rows)
    if not scoped:
        return 0

    tuples = _daily_rows_to_wearable_data_tuples(scoped)
    if not tuples:
        return 0

    conn = _connect()
    try:
        mirror_keys = sorted({(uid, mt, ts) for uid, mt, ts, _val in tuples})
        for uid, mt, ts in mirror_keys:
            conn.execute(
                """
                DELETE FROM wearable_data
                WHERE user_id = ? AND metric_type = ? AND timestamp = ?
                """,
                (uid, mt, ts),
            )
        for i in range(0, len(tuples), _WEARABLE_DATA_BATCH):
            conn.executemany(
                """
                INSERT OR IGNORE INTO wearable_data
                    (user_id, metric_type, timestamp, value, sample_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (uid, mt, ts, val, f"{uid}|{mt}|{ts}|{val}")
                    for uid, mt, ts, val in tuples[i : i + _WEARABLE_DATA_BATCH]
                ],
            )
        conn.commit()
        return len(tuples)
    finally:
        _release_connection(conn)


def query_wearable_data_range(
    user_id: str,
    metric_type: str,
    start_date: date,
    end_date: date,
) -> List[tuple[date, float]]:
    """Indexed range query on ``wearable_data`` — returns (day, value) pairs."""
    init_schema()
    uid = user_id.strip() or "default"
    start_ts = _day_timestamp(start_date)[:10]
    end_ts = _day_timestamp(end_date)[:10]
    conn = _connect()
    try:
        cur = conn.execute(
            """
            SELECT timestamp, value FROM wearable_data
            WHERE user_id = ? AND metric_type = ?
              AND substr(timestamp, 1, 10) >= ? AND substr(timestamp, 1, 10) <= ?
            ORDER BY timestamp
            """,
            (uid, metric_type, start_ts, end_ts),
        )
        out: List[tuple[date, float]] = []
        for row in cur.fetchall():
            if row["value"] is None:
                continue
            day = safe_parse_date(row["timestamp"])
            if day is None:
                continue
            out.append((day, float(row["value"])))
        return out
    finally:
        _release_connection(conn)


def query_wearable_daily_range(
    user_id: str,
    start_date: date,
    end_date: date,
) -> List[WearableDailySummary]:
    """Indexed day-level query — O(log n) seek, not full table scan."""
    init_schema()
    uid = user_id.strip() or "default"
    if end_date < start_date:
        start_date, end_date = end_date, start_date
    conn = _connect()
    try:
        cur = conn.execute(
            """
            SELECT * FROM wearable_daily
            WHERE user_id = ? AND day >= ? AND day <= ?
            ORDER BY day
            """,
            (uid, start_date.isoformat(), end_date.isoformat()),
        )
        return [_row_to_model(r) for r in cur.fetchall()]
    finally:
        _release_connection(conn)


def query_active_energy_daily_range(
    user_id: str,
    start_date: date,
    end_date: date,
) -> List[Dict[str, Any]]:
    """Daily sum of active energy (kcal) from ``wearable_data`` when present."""
    init_schema()
    uid = user_id.strip() or "default"
    if end_date < start_date:
        start_date, end_date = end_date, start_date
    conn = _connect()
    try:
        cur = conn.execute(
            """
            SELECT substr(timestamp, 1, 10) AS d, SUM(value) AS v
            FROM wearable_data
            WHERE user_id = ?
              AND metric_type IN (?, 'HKQuantityTypeIdentifierActiveEnergyBurned')
              AND substr(timestamp, 1, 10) >= ? AND substr(timestamp, 1, 10) <= ?
            GROUP BY d
            ORDER BY d
            """,
            (
                uid,
                METRIC_ACTIVE_ENERGY,
                start_date.isoformat(),
                end_date.isoformat(),
            ),
        )
        return [
            {"label": str(row["d"]), "value": float(row["v"])}
            for row in cur.fetchall()
            if row["v"] is not None
        ]
    finally:
        _release_connection(conn)


def upsert_wearable_rows(
    rows: Sequence[WearableDailySummary],
    *,
    sync_index_from_daily: bool = True,
) -> int:
    if not rows:
        return 0
    conn = _connect()
    try:
        conn.executemany(
            _wearable_daily_upsert_sql(),
            [_model_to_tuple(r) for r in rows],
        )
        conn.commit()
    finally:
        _release_connection(conn)

    if sync_index_from_daily:
        by_user: dict[str, list[WearableDailySummary]] = {}
        for row in rows:
            by_user.setdefault(row.user_id, []).append(row)
        for uid, user_rows in by_user.items():
            sync_wearable_data_from_daily(user_rows, user_id=uid)
    return len(rows)


def load_wearable_rows(
    user_id: Optional[str] = None,
    *,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit_days: Optional[int] = None,
    reference_date: Optional[date] = None,
) -> List[WearableDailySummary]:
    """
    Load wearable daily rows with optional range cap (for cold-start / charts).

    When ``limit_days`` is set with ``reference_date``, only the most recent window is loaded.
    """
    if not database_exists():
        logger.warning("SQLite DB not found at %s; cold start has no wearable rows", get_db_path())
        return []
    init_schema()

    if user_id and start_date and end_date:
        return query_wearable_daily_range(user_id, start_date, end_date)

    conn = _connect()
    try:
        params: list = []
        clauses: list[str] = []
        if user_id:
            clauses.append("user_id = ?")
            params.append(user_id.strip() or "default")
        if start_date:
            clauses.append("day >= ?")
            params.append(start_date.isoformat())
        if end_date:
            clauses.append("day <= ?")
            params.append(end_date.isoformat())

        if limit_days is not None and reference_date is not None:
            window_start = reference_date.toordinal() - max(1, limit_days) + 1
            start_d = date.fromordinal(window_start)
            clauses.append("day >= ?")
            params.append(start_d.isoformat())

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM wearable_daily {where} ORDER BY user_id, day"
        cur = conn.execute(sql, params)
        return [_row_to_model(r) for r in cur.fetchall()]
    finally:
        _release_connection(conn)


def backfill_wearable_data_from_daily(user_id: Optional[str] = None) -> int:
    """One-time sync: populate ``wearable_data`` index from existing ``wearable_daily`` rows."""
    rows = load_wearable_rows(user_id)
    if not rows:
        return 0
    if user_id:
        return sync_wearable_data_from_daily(rows, user_id=user_id)
    total = 0
    by_user: dict[str, list[WearableDailySummary]] = {}
    for row in rows:
        by_user.setdefault(row.user_id, []).append(row)
    for uid, user_rows in by_user.items():
        total += sync_wearable_data_from_daily(user_rows, user_id=uid)
    return total


def wipe_wearable_data(user_id: Optional[str] = None) -> int:
    """Delete wearable rows from SQLite (all users if ``user_id`` is None). Returns rows removed."""
    if not database_exists():
        return 0
    clear_wearable_storage(user_id)
    return count_wearable_samples(user_id) if user_id else 0


def count_rows(user_id: Optional[str] = None) -> int:
    if not database_exists():
        return 0
    conn = _connect()
    try:
        if user_id:
            cur = conn.execute(
                "SELECT COUNT(*) AS c FROM wearable_daily WHERE user_id = ?",
                (user_id.strip() or "default",),
            )
        else:
            cur = conn.execute("SELECT COUNT(*) AS c FROM wearable_daily")
        row = cur.fetchone()
        return int(row["c"]) if row else 0
    finally:
        _release_connection(conn)


register_schema_initializer(_apply_schema_migrations)
