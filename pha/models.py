"""Core domain models — ledger structures for PHA 3.0."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class UserCalibration(BaseModel):
    """Latest user-fixed facts injected ahead of all other context."""

    user_id: str
    display_name: str = ""
    gender: str = ""
    age_years: Optional[int] = None
    allergies: str = ""
    core_conditions: str = Field(
        default="",
        description="Core chronic or major conditions the user considers medically defining.",
    )


class HealthEventType(str, Enum):
    """Canonical health timeline event categories."""

    SYMPTOM = "symptom"
    SURGERY = "surgery"
    DIAGNOSIS = "diagnosis"
    MEDICATION = "medication"
    LAB_REPORT = "lab_report"


class HealthEvent(BaseModel):
    """Single row in the append-only health event stream."""

    id: UUID = Field(default_factory=uuid4)
    user_id: str
    event_type: HealthEventType
    occurred_at: datetime
    title: str
    summary: str
    is_milestone: bool = False


class WearableDailySummary(BaseModel):
    """One day of aggregated wearable metrics (hot-path rollup row)."""

    user_id: str
    day: date
    steps: Optional[int] = None
    resting_heart_rate_bpm: Optional[float] = Field(
        default=None,
        description="Resting heart rate (RHR), beats per minute.",
    )
    hrv_rmssd_ms: Optional[float] = Field(
        default=None,
        description="Heart rate variability (HRV), RMSSD in milliseconds.",
    )
    sleep_hours: Optional[float] = None
    awake_duration_hours: Optional[float] = Field(
        default=None,
        description="Time spent awake during sleep window (hours), for fragmentation analysis.",
    )
    sleep_start_time: Optional[datetime] = Field(
        default=None,
        description="Earliest sleep segment start time that day.",
    )
    active_energy_kcal: Optional[float] = Field(
        default=None,
        description="Apple Health Active Energy Burned sum for the calendar day (kcal).",
    )
    spo2_pct: Optional[float] = Field(
        default=None,
        description="Blood oxygen saturation daily mean (%).",
    )
    respiratory_rate_bpm: Optional[float] = Field(
        default=None,
        description="Respiratory rate daily mean (breaths/min).",
    )
    vo2max_ml_kg_min: Optional[float] = Field(
        default=None,
        description="VO2 max daily mean (mL/kg/min).",
    )
    wrist_temp_c: Optional[float] = Field(
        default=None,
        description="Sleeping wrist / body temperature daily mean (°C).",
    )


class LongTermMilestone(BaseModel):
    """Derived record: major events permanently eligible for system prompt injection."""

    source_event_id: UUID
    user_id: str
    event_type: HealthEventType
    occurred_at: datetime
    title: str
    summary: str

    @classmethod
    def from_health_event(cls, event: HealthEvent) -> LongTermMilestone:
        if not event.is_milestone:
            msg = "LongTermMilestone requires HealthEvent.is_milestone=True"
            raise ValueError(msg)
        return cls(
            source_event_id=event.id,
            user_id=event.user_id,
            event_type=event.event_type,
            occurred_at=event.occurred_at,
            title=event.title,
            summary=event.summary,
        )


class AnnualHealthSummary(BaseModel):
    """Cross-year aggregate snapshot for trend surfaces and RAG analytics."""

    user_id: str
    year: int
    avg_hrv_rmssd_ms: Optional[float] = None
    rhr_trend_summary: str = Field(
        default="",
        description="Human-readable annual RHR direction / commentary.",
    )
    primary_health_keywords: List[str] = Field(default_factory=list)

    def model_dump_json_safe(self) -> dict[str, Any]:
        """Plain dict for persistence layers that are not Pydantic-native."""
        return self.model_dump(mode="python")
