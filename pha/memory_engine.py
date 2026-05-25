"""Long-horizon memory engine: compress wearables and surface permanent milestones."""

from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Callable, Protocol, Sequence

from pha.models import HealthEvent, LongTermMilestone, WearableDailySummary

logger = logging.getLogger(__name__)


class MilestoneDatabasePort(Protocol):
    """Persistence port: production implementations query SQL/NoSQL here."""

    def fetch_milestone_events(self, user_id: str) -> Sequence[HealthEvent]:
        ...


def _mean_optional(values: list[float], *, metric_name: str, bucket_label: str) -> float | None:
    if not values:
        logger.warning(
            "Aggregation missing data: metric=%s bucket=%s reason=no_samples",
            metric_name,
            bucket_label,
        )
        return None
    return float(statistics.mean(values))


def compress_wearable_data(
    rows: Sequence[WearableDailySummary],
    *,
    reference_date: date | None = None,
    user_id: str | None = None,
) -> str:
    """
    Stratify infinite-length wearable streams into a bounded text artifact.

    Policy (relative to ``reference_date``):
    - Last 90 days: daily resolution.
    - Between 90 days and 1 year ago: daily resolution.
    - Older than 1 year up to and including 3 years: monthly means.
    - Older than 3 years: yearly means.
    """
    ref = reference_date or date.today()
    if not rows:
        logger.warning(
            "Aggregation missing data: compress_wearable_data received zero rows "
            "(user_id=%s, reference_date=%s)",
            user_id or "?",
            ref.isoformat(),
        )
        return (
            "=== Wearable trend compression ===\n"
            "No wearable rows were supplied; no trends were computed.\n"
        )

    resolved_user = user_id or next(iter(rows)).user_id
    inconsistent = {r.user_id for r in rows if r.user_id != resolved_user}
    if inconsistent:
        logger.warning(
            "Aggregation missing data: compress_wearable_data user_id mismatch "
            "expected=%s found=%s",
            resolved_user,
            inconsistent,
        )

    daily_recent: dict[date, list[WearableDailySummary]] = defaultdict(list)
    daily_mid: dict[date, list[WearableDailySummary]] = defaultdict(list)
    monthly: dict[tuple[int, int], list[WearableDailySummary]] = defaultdict(list)
    yearly: dict[int, list[WearableDailySummary]] = defaultdict(list)

    for row in rows:
        if row.day > ref:
            logger.warning(
                "Aggregation missing data: skipping future-dated wearable row "
                "day=%s ref=%s user_id=%s",
                row.day.isoformat(),
                ref.isoformat(),
                row.user_id,
            )
            continue

        age_days = (ref - row.day).days
        if age_days <= 90:
            daily_recent[row.day].append(row)
        elif age_days <= 365:
            daily_mid[row.day].append(row)
        elif age_days <= 365 * 3:
            monthly[(row.day.year, row.day.month)].append(row)
        else:
            yearly[row.day.year].append(row)

    lines: list[str] = [
        "=== Wearable trend compression ===",
        f"reference_date={ref.isoformat()} user_id={resolved_user}",
        "",
        "--- Daily resolution: last 90 days ---",
    ]
    lines.extend(_format_daily_buckets(sorted(daily_recent.items()), ref, max_age_days=90))

    lines.append("")
    lines.append("--- Daily resolution: 90d–1y ago ---")
    lines.extend(_format_daily_buckets(sorted(daily_mid.items()), ref, max_age_days=365))

    lines.append("")
    lines.append("--- Monthly means: >1y and ≤3y ---")
    lines.extend(_format_monthly_means(sorted(monthly.items())))

    lines.append("")
    lines.append("--- Yearly means: >3y ---")
    lines.extend(_format_yearly_means(sorted(yearly.items())))

    return "\n".join(lines) + "\n"


def _format_daily_buckets(
    buckets: list[tuple[date, list[WearableDailySummary]]],
    ref: date,
    *,
    max_age_days: int,
) -> list[str]:
    out: list[str] = []
    if not buckets:
        logger.warning(
            "Aggregation missing data: no daily buckets in age window "
            "(max_age_days=%s, reference_date=%s)",
            max_age_days,
            ref.isoformat(),
        )
        out.append("(no rows in this window)")
        return out

    for day, samples in buckets:
        age_days = (ref - day).days
        if age_days > max_age_days:
            continue
        line = _single_day_line(day, samples)
        out.append(line)
    if len(out) == 0:
        logger.warning(
            "Aggregation missing data: daily window produced zero lines "
            "(max_age_days=%s)",
            max_age_days,
        )
        out.append("(no rows in this window)")
    return out


def _single_day_line(day: date, samples: list[WearableDailySummary]) -> str:
    label = day.isoformat()
    if len(samples) > 1:
        logger.warning(
            "Aggregation missing data: duplicate wearable rows for same calendar day "
            "day=%s count=%s; values will be averaged",
            day.isoformat(),
            len(samples),
        )
    steps = _merge_int(samples, lambda s: s.steps, label, "steps")
    rhr = _merge_float(samples, lambda s: s.resting_heart_rate_bpm, label, "rhr_bpm")
    hrv = _merge_float(samples, lambda s: s.hrv_rmssd_ms, label, "hrv_rmssd_ms")
    sleep = _merge_float(samples, lambda s: s.sleep_hours, label, "sleep_hours")
    return (
        f"{label} | steps={_fmt_int(steps)} rhr_bpm={_fmt_float(rhr)} "
        f"hrv_rmssd_ms={_fmt_float(hrv)} sleep_h={_fmt_float(sleep)}"
    )


def _merge_int(
    samples: list[WearableDailySummary],
    getter: Callable[[WearableDailySummary], int | None],
    bucket_label: str,
    metric: str,
) -> int | None:
    vals = [v for v in (getter(s) for s in samples) if v is not None]
    if not vals:
        logger.warning(
            "Aggregation missing data: metric=%s bucket=%s reason=all_null",
            metric,
            bucket_label,
        )
        return None
    return int(round(statistics.mean(vals)))


def _merge_float(
    samples: list[WearableDailySummary],
    getter: Callable[[WearableDailySummary], float | None],
    bucket_label: str,
    metric: str,
) -> float | None:
    vals = [float(v) for v in (getter(s) for s in samples) if v is not None]
    if not vals:
        logger.warning(
            "Aggregation missing data: metric=%s bucket=%s reason=all_null",
            metric,
            bucket_label,
        )
        return None
    return float(statistics.mean(vals))


def _fmt_int(v: int | None) -> str:
    return "na" if v is None else str(v)


def _fmt_float(v: float | None) -> str:
    return "na" if v is None else f"{v:.2f}"


def _format_monthly_means(
    buckets: list[tuple[tuple[int, int], list[WearableDailySummary]]],
) -> list[str]:
    if not buckets:
        logger.warning(
            "Aggregation missing data: no monthly buckets for >1y–≤3y window",
        )
        return ["(no rows in this window)"]

    lines: list[str] = []
    for (year, month), samples in buckets:
        label = f"{year:04d}-{month:02d}"
        steps_vals = [float(s.steps) for s in samples if s.steps is not None]
        rhr_vals = [float(s.resting_heart_rate_bpm) for s in samples if s.resting_heart_rate_bpm is not None]
        hrv_vals = [float(s.hrv_rmssd_ms) for s in samples if s.hrv_rmssd_ms is not None]
        sleep_vals = [float(s.sleep_hours) for s in samples if s.sleep_hours is not None]

        steps_m = _mean_optional(steps_vals, metric_name="steps", bucket_label=label)
        rhr_m = _mean_optional(rhr_vals, metric_name="rhr_bpm", bucket_label=label)
        hrv_m = _mean_optional(hrv_vals, metric_name="hrv_rmssd_ms", bucket_label=label)
        sleep_m = _mean_optional(sleep_vals, metric_name="sleep_hours", bucket_label=label)

        lines.append(
            f"{label} | mean_steps={_fmt_float(steps_m)} mean_rhr_bpm={_fmt_float(rhr_m)} "
            f"mean_hrv_rmssd_ms={_fmt_float(hrv_m)} mean_sleep_h={_fmt_float(sleep_m)} "
            f"n_days={len(samples)}",
        )
    return lines


def _format_yearly_means(buckets: list[tuple[int, list[WearableDailySummary]]]) -> list[str]:
    if not buckets:
        logger.warning(
            "Aggregation missing data: no yearly buckets for >3y window",
        )
        return ["(no rows in this window)"]

    lines: list[str] = []
    for year, samples in buckets:
        label = f"{year:04d}"
        steps_vals = [float(s.steps) for s in samples if s.steps is not None]
        rhr_vals = [float(s.resting_heart_rate_bpm) for s in samples if s.resting_heart_rate_bpm is not None]
        hrv_vals = [float(s.hrv_rmssd_ms) for s in samples if s.hrv_rmssd_ms is not None]
        sleep_vals = [float(s.sleep_hours) for s in samples if s.sleep_hours is not None]

        steps_m = _mean_optional(steps_vals, metric_name="steps", bucket_label=label)
        rhr_m = _mean_optional(rhr_vals, metric_name="rhr_bpm", bucket_label=label)
        hrv_m = _mean_optional(hrv_vals, metric_name="hrv_rmssd_ms", bucket_label=label)
        sleep_m = _mean_optional(sleep_vals, metric_name="sleep_hours", bucket_label=label)

        lines.append(
            f"{label} | mean_steps={_fmt_float(steps_m)} mean_rhr_bpm={_fmt_float(rhr_m)} "
            f"mean_hrv_rmssd_ms={_fmt_float(hrv_m)} mean_sleep_h={_fmt_float(sleep_m)} "
            f"n_days={len(samples)}",
        )
    return lines


def get_permanent_milestones(
    user_id: str,
    *,
    repository: MilestoneDatabasePort,
) -> list[LongTermMilestone]:
    """
    Load every ``is_milestone`` health event for ``user_id`` and expose prompt-ready rows.

    ``repository`` is the database boundary; callers must supply a real persistence adapter.
    """
    raw = list(repository.fetch_milestone_events(user_id))
    if not raw:
        logger.warning(
            "Aggregation missing data: no milestone health events for user_id=%s",
            user_id,
        )

    milestones: list[LongTermMilestone] = []
    for event in sorted(raw, key=lambda e: e.occurred_at):
        if not event.is_milestone:
            logger.warning(
                "Aggregation missing data: repository returned non-milestone row "
                "event_id=%s user_id=%s; skipping",
                str(event.id),
                user_id,
            )
            continue
        milestones.append(LongTermMilestone.from_health_event(event))
    return milestones


@dataclass(frozen=True)
class UserContextBundle:
    """Structured bundle returned by ``HealthStore.get_user_context``."""

    user_id: str
    compressed_wearable_trends: str
    permanent_milestones: list[LongTermMilestone]

    def as_dict(self) -> dict[str, object]:
        return {
            "user_id": self.user_id,
            "compressed_wearable_trends": self.compressed_wearable_trends,
            "permanent_milestones": [m.model_dump(mode="python") for m in self.permanent_milestones],
        }
