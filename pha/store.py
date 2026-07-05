"""PHA persistence façade — singleton store and user context assembly."""

from __future__ import annotations

import logging
import sqlite3
from collections import defaultdict
from datetime import date, datetime
from typing import DefaultDict, Sequence

from pha.memory_engine import (
    MilestoneDatabasePort,
    UserContextBundle,
    compress_wearable_data,
    get_permanent_milestones,
)

from pha.sqlite_storage import (
    backfill_wearable_data_from_daily,
    database_exists,
    get_db_path,
    load_wearable_rows,
    upsert_wearable_rows,
    wipe_wearable_data,
)
from pha.structured_log import log_exception
from pha.trend_viz import build_trend_charts_json
from pha.models import HealthEvent, UserCalibration, WearableDailySummary

logger = logging.getLogger(__name__)


def _avg_optional(a: float | None, b: float | None) -> float | None:
    if a is None:
        return b
    if b is None:
        return a
    return (a + b) / 2.0


def _earliest_optional(a: datetime | None, b: datetime | None) -> datetime | None:
    if a is None:
        return b
    if b is None:
        return a
    return a if a <= b else b


def _sum_optional(a: float | None, b: float | None) -> float | None:
    if a is None:
        return b
    if b is None:
        return a
    return a + b


def _merge_wearable_same_day(a: WearableDailySummary, b: WearableDailySummary) -> WearableDailySummary:
    if a.user_id != b.user_id or a.day != b.day:
        msg = "merge_wearable_same_day requires matching user_id and day"
        raise ValueError(msg)
    steps: int | None
    if a.steps is not None and b.steps is not None:
        steps = int(max(a.steps, b.steps))
    elif a.steps is not None:
        steps = a.steps
    elif b.steps is not None:
        steps = b.steps
    else:
        steps = None
    return WearableDailySummary(
        user_id=a.user_id,
        day=a.day,
        steps=steps,
        resting_heart_rate_bpm=_avg_optional(a.resting_heart_rate_bpm, b.resting_heart_rate_bpm),
        hrv_rmssd_ms=_avg_optional(a.hrv_rmssd_ms, b.hrv_rmssd_ms),
        sleep_hours=_sum_optional(a.sleep_hours, b.sleep_hours),
        awake_duration_hours=_sum_optional(a.awake_duration_hours, b.awake_duration_hours),
        sleep_start_time=_earliest_optional(a.sleep_start_time, b.sleep_start_time),
        active_energy_kcal=_sum_optional(a.active_energy_kcal, b.active_energy_kcal),
        spo2_pct=_avg_optional(a.spo2_pct, b.spo2_pct),
        respiratory_rate_bpm=_avg_optional(a.respiratory_rate_bpm, b.respiratory_rate_bpm),
        vo2max_ml_kg_min=_avg_optional(a.vo2max_ml_kg_min, b.vo2max_ml_kg_min),
        wrist_temp_c=_avg_optional(a.wrist_temp_c, b.wrist_temp_c),
    )


class HealthStore(MilestoneDatabasePort):
    """
    Process-local ledger backing PHA 3.0 step-1.

    Swap internals for a real database while keeping ``fetch_milestone_events`` stable.
    """

    def __init__(self) -> None:
        self._events: DefaultDict[str, list[HealthEvent]] = defaultdict(list)
        self._wearable: DefaultDict[str, list[WearableDailySummary]] = defaultdict(list)
        self._calibration: dict[str, UserCalibration] = {}

    def append_health_event(self, event: HealthEvent) -> None:
        self._events[event.user_id].append(event)

    def append_wearable_day(self, row: WearableDailySummary) -> None:
        self._wearable[row.user_id].append(row)

    def import_wearable_rows(self, user_id: str, rows: list[WearableDailySummary]) -> None:
        """Merge daily wearable rows into the ledger keyed by ``day`` (sums / averages as appropriate)."""
        if not rows:
            return
        uid = user_id.strip() or "default"
        by_day: dict[date, WearableDailySummary] = {}
        for r in self._wearable.get(uid, []):
            if r.user_id != uid:
                logger.warning("import_wearable_rows skipping row with mismatched user_id=%s", r.user_id)
                continue
            prev = by_day.get(r.day)
            by_day[r.day] = r if prev is None else _merge_wearable_same_day(prev, r)
        for r in rows:
            if r.user_id != uid:
                logger.warning(
                    "import_wearable_rows skipping imported row user_id=%s expected=%s",
                    r.user_id,
                    uid,
                )
                continue
            prev = by_day.get(r.day)
            by_day[r.day] = r if prev is None else _merge_wearable_same_day(prev, r)
        merged_rows = sorted(by_day.values(), key=lambda r: r.day)
        self._wearable[uid] = merged_rows
        try:
            upsert_wearable_rows(merged_rows)
        except (sqlite3.Error, OSError) as exc:
            log_exception(logger, "store_persist_wearable_failed", exc, user_id=uid)

    def replace_wearable_rows_in_memory(
        self,
        user_id: str,
        rows: list[WearableDailySummary],
    ) -> None:
        """Set in-memory wearable ledger after SQLite daily upsert (import hot path)."""
        uid = user_id.strip() or "default"
        self._wearable[uid] = sorted(rows, key=lambda r: r.day)

    def clear_wearable_ledger(self, user_id: str | None = None) -> None:
        """Drop in-memory wearable rows and mirror delete in SQLite."""
        if user_id:
            uid = user_id.strip() or "default"
            self._wearable.pop(uid, None)
        else:
            self._wearable.clear()
        try:
            wipe_wearable_data(user_id)
        except (sqlite3.Error, OSError) as exc:
            log_exception(logger, "store_wipe_wearable_failed", exc, user_id=user_id)

    def hydrate_from_sqlite(self, *, max_days: int = 400) -> int:
        """
        Cold-start: load recent wearable rows only (bounded memory for multi-year exports).

        Full history remains in SQLite; ``get_health_data`` uses indexed range queries.
        """
        if not database_exists():
            logger.info("SQLite cold start: no database at %s", get_db_path())
            return 0
        from pha.health_data import effective_query_reference_date

        rows = load_wearable_rows(
            limit_days=max_days,
            reference_date=effective_query_reference_date(),
        )
        if not rows:
            return 0
        by_user: DefaultDict[str, dict[date, WearableDailySummary]] = defaultdict(dict)
        for row in rows:
            uid = row.user_id.strip() or "default"
            prev = by_user[uid].get(row.day)
            by_user[uid][row.day] = row if prev is None else _merge_wearable_same_day(prev, row)
        total = 0
        for uid, day_map in by_user.items():
            self._wearable[uid] = sorted(day_map.values(), key=lambda r: r.day)
            total += len(day_map)
        logger.info(
            "SQLite cold start: loaded %s day rows for %s user(s) from %s",
            total,
            len(by_user),
            get_db_path(),
        )
        return total

    def set_user_calibration(self, calibration: UserCalibration) -> None:
        self._calibration[calibration.user_id] = calibration

    def get_user_calibration(self, user_id: str) -> UserCalibration:
        existing = self._calibration.get(user_id)
        if existing is None:
            logger.warning(
                "Aggregation missing data: no UserCalibration stored for user_id=%s; "
                "using empty calibration shell",
                user_id,
            )
            return UserCalibration(user_id=user_id)
        return existing

    def list_recent_health_events(self, user_id: str, limit: int = 30) -> list[HealthEvent]:
        events = list(self._events.get(user_id, []))
        events.sort(key=lambda e: e.occurred_at, reverse=True)
        return events[:limit]

    def list_wearable_rows(self, user_id: str) -> list[WearableDailySummary]:
        return list(self._wearable.get(user_id, []))

    def fetch_milestone_events(self, user_id: str) -> Sequence[HealthEvent]:
        return [event for event in self._events.get(user_id, []) if event.is_milestone]

    def get_user_context(self, user_id: str) -> dict[str, object]:
        wearable_rows = self.list_wearable_rows(user_id)
        if not wearable_rows:
            logger.warning(
                "Aggregation missing data: wearable stream empty for user_id=%s",
                user_id,
            )

        compressed = compress_wearable_data(wearable_rows, user_id=user_id)
        trend_charts = build_trend_charts_json(wearable_rows, user_id)
        milestones = get_permanent_milestones(user_id, repository=self)
        bundle = UserContextBundle(
            user_id=user_id,
            compressed_wearable_trends=compressed,
            permanent_milestones=milestones,
        )
        out = bundle.as_dict()
        out["wearable_trend_charts"] = trend_charts
        return out


store = HealthStore()
