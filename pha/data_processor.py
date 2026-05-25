"""Wearable data processing — sleep union aggregation (replaces naive SUM)."""

from __future__ import annotations

from pha.sleep_aggregator import (
    SleepSegment,
    compute_sleep_hours_union,
    make_sleep_sample_id,
)

__all__ = [
    "SleepSegment",
    "compute_sleep_hours_union",
    "make_sleep_sample_id",
]
