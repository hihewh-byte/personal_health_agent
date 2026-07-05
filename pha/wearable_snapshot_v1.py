"""WearableSnapshotLedgerV1 — Apple Health / Watch UI screenshot structured ledger."""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

from pha.date_parser import safe_parse_date
from pha.health_data import effective_query_reference_date

ParseConfidence = Literal["high", "medium", "low"]
PerceptionChannel = Literal["ocr_only", "ocr_plus_vision_validate", "vision_structured"]
ScreenType = Literal[
    "heart_rate",
    "spo2",
    "respiratory_rate",
    "sleep",
    "hrv",
    "workout",
    "unknown",
]

_SCREEN_TYPE_RULES: List[Tuple[ScreenType, re.Pattern[str]]] = [
    ("hrv", re.compile(r"variability|hrv|rmssd", re.I)),
    ("spo2", re.compile(r"blood\s+oxygen|血氧|spo2", re.I)),
    ("respiratory_rate", re.compile(r"respiratory|呼吸率", re.I)),
    ("sleep", re.compile(r"time\s+asleep|睡眠|@?\s*(?:deep|rem|awake)\b", re.I)),
    ("workout", re.compile(
        r"workouts?\s+highlights|heart\s+rate:\s*workout|recent\s+run|"
        r"beats per minute during your recent|during your last workout|"
        r"worked out on \d+ days|锻炼\s|functional strength",
        re.I,
    )),
    ("heart_rate", re.compile(r"heart\s+rate|心率|resting\s+rate", re.I)),
]

_DATE_HINT_RE = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\b"
    r"|\d{4}[-/]\d{1,2}[-/]\d{1,2}",
    re.I,
)

_HRV_PATTERNS: List[re.Pattern[str]] = [
    re.compile(r"(?:hrv|variability).*?(\d{1,3})\s*(?:ms|ins)", re.I | re.S),
    re.compile(r"average\s+(\d{1,3})\s*(?:ms|ins)", re.I),
]
_SPO2_PATTERNS: List[re.Pattern[str]] = [
    re.compile(r"(?:blood\s+oxygen|血氧|spo2).*?(\d{2,3})\s*%", re.I | re.S),
]
_SLEEP_ASLEEP_AFTER_LABEL_RE = re.compile(
    r"time\s+asleep\s*\n\s*(\d{1,2})\s*hr(?:\s*(\d{1,2})\s*min)?",
    re.I,
)
_SLEEP_ASLEEP_SAME_LINE_RE = re.compile(
    r"time\s+asleep\s+(\d{1,2})\s*hr(?:\s*(\d{1,2})\s*min)?",
    re.I,
)
_SLEEP_ASLEEP_BEFORE_LABEL_RE = re.compile(
    r"(\d{1,2})\s*hr(?:\s*(\d{1,2})\s*min)?[^\n]{0,32}time\s+asleep",
    re.I,
)
_SLEEP_CN_ASLEEP_RE = re.compile(
    r"睡眠(?:时长|时间)?\s*(\d{1,2})\s*小时(?:\s*(\d{1,2})\s*分)?",
    re.I,
)
_SLEEP_ASLEEP_AFTER_LABEL_LOOSE_RE = re.compile(
    r"time\s+asleep[\s\S]{0,220}?(\d{1,2})\s*(?:hr|nr|h)\s*,?\s*(\d{1,2})\s*min",
    re.I,
)
_SLEEP_ASLEEP_COMPACT_RE = re.compile(
    r"\b(\d{1,2})h[,.\s]+(\d{1,2})\s*min\b",
    re.I,
)
_AWAKE_CONTEXT_RE = re.compile(r"\bawake\b", re.I)
_TIME_IN_BED_RE = re.compile(r"time\s+in\s+bed", re.I)
_HEART_RATE_RANGE_RE = re.compile(r"(\d{2,3})\s*[–\-]\s*(\d{2,3})\s*bpm", re.I)
_RESTING_HR_RE = re.compile(
    r"(?:resting|静息)[^\d]{0,80}?(\d{2,3})\s*(?:bpm|beats\s*per\s*minute)",
    re.I | re.S,
)
_RESTING_HR_INVERTED_RE = re.compile(
    r"(\d{2,3})\s*(?:bpm|BPM)\b(?:[^\S\n]*\n)?[^\n]{0,80}?"
    r"(?:Resting\s+Rate|Resting(?:\s+Rate)?|静息)",
    re.I,
)
_WALKING_AVERAGE_RE = re.compile(r"walking\s+average|步行", re.I)
_RESPIRATORY_BPM_RE = re.compile(
    r"(\d{1,2}(?:\.\d)?)\s*(?:breaths/min|breaths\s*per\s*minute|次/分)",
    re.I,
)
_RESPIRATORY_RANGE_RE = re.compile(
    r"(\d{1,2}(?:\.\d)?)\s*[–\-]\s*(\d{1,2}(?:\.\d)?)\s*breaths",
    re.I,
)
_WORKOUT_KCAL_RE = re.compile(r"(\d{2,4})\s*kcal", re.I)
_WORKOUT_MIN_RE = re.compile(r"(\d{1,3})\s*min\b", re.I)
_WORKOUT_HR_RANGE_RE = re.compile(
    r"(?:heart\s+rate:\s*workout|during your (?:recent\s+run|last\s+workout)|"
    r"heart\s+rate\s+was).{0,120}?"
    r"(\d{2,3})\s*[–\-]\s*(\d{2,3})\s*(?:beats per minute|bpm)",
    re.I | re.S,
)
_WORKOUT_DAYS_4W_RE = re.compile(
    r"(?:worked\s+out|work\s*out)\s+on\s+(\d{1,3})\s+days?\s+in\s+the\s+last\s+4\s+weeks",
    re.I,
)
_WORKOUT_COUNT_RE = re.compile(r"(\d{1,3})\s+Workouts?\b", re.I)

_WEARABLE_REMERGE_USER_RE = re.compile(
    r"重新|再次|核实|不对|错误|明显错|解析.*不对|重新分析|重新上传|"
    r"再次解析|截图.*(?:不对|错误)|睡眠.*(?:不对|错误|核实)",
    re.I,
)

_METRIC_UNIT: Dict[str, str] = {
    "hrv_rmssd_ms": "ms",
    "spo2_percent": "%",
    "resting_heart_rate_bpm": "bpm",
    "heart_rate_range_bpm": "bpm",
    "respiratory_rate": "",
    "sleep_time_asleep": "hr",
    "sleep_deep": "hr",
    "sleep_rem": "hr",
    "workout_energy_kcal": "kcal",
    "workout_duration_min": "min",
    "workout_heart_rate_range_bpm": "bpm",
    "workout_count_recent": "sessions",
}


class WearableScreenV1(BaseModel):
    index: int = 0
    screen_type: ScreenType = "unknown"
    date_hint: str = ""
    ocr_excerpt: str = ""
    layout_region_types: List[str] = Field(default_factory=list)


class WearableMetricV1(BaseModel):
    metric_id: str
    value: str
    unit: str = ""
    sub_value: str = ""
    window: str = ""
    source_screen_index: int = 0
    source_line: str = ""


class WearableSnapshotLedgerV1(BaseModel):
    schema_version: str = "wearable_snapshot_v1"
    attachment_count: int = 1
    source_app_hint: str = "apple_health"
    screens: List[WearableScreenV1] = Field(default_factory=list)
    metrics: List[WearableMetricV1] = Field(default_factory=list)
    parse_confidence: ParseConfidence = "medium"
    reject_reasons: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    perception_channel: PerceptionChannel = "ocr_only"
    merge_trace: List[Dict[str, Any]] = Field(default_factory=list)
    ledger_markdown: str = ""

    def to_parsed_dict(self) -> Dict[str, Any]:
        return {
            "wearable_snapshot_v1": self.model_dump(mode="python"),
            "schema_version": self.schema_version,
            "document_family": "wearable",
            "document_type": "apple_watch",
            "attachment_count": self.attachment_count,
            "source_app_hint": self.source_app_hint,
            "screens": [s.model_dump(mode="python") for s in self.screens],
            "wearable_metrics": [m.model_dump(mode="python") for m in self.metrics],
            "metrics": [m.model_dump(mode="python") for m in self.metrics],
            "parse_confidence": self.parse_confidence,
            "reject_reasons": list(self.reject_reasons),
            "warnings": list(self.warnings),
            "perception_channel": self.perception_channel,
            "merge_trace": list(self.merge_trace),
            "label_ledger": self.ledger_markdown,
            "vision_summary": self.ledger_markdown,
            "ingredient_rows": [],
        }


def infer_screen_type(ocr_text: str) -> ScreenType:
    blob = ocr_text or ""
    for stype, pat in _SCREEN_TYPE_RULES:
        if pat.search(blob):
            return stype
    return "unknown"


def extract_date_hint(ocr_text: str) -> str:
    m = _DATE_HINT_RE.search(ocr_text or "")
    return m.group(0).strip() if m else ""


_EN_MONTH_ABBR: Dict[str, int] = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

_USER_CN_MD_RE = re.compile(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_USER_CN_MD_SHORT_RE = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_USER_CN_MD_HAO_RE = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*号")


def date_hint_to_date(hint: str, *, default_year: Optional[int] = None) -> Optional[date]:
    """Parse OCR ``May 30`` / ISO hints to calendar date (Wave 3d-ε+)."""
    raw = (hint or "").strip()
    if not raw:
        return None
    year = default_year or effective_query_reference_date().year
    m_en = re.match(r"([A-Za-z]{3,9})\s+(\d{1,2})\b", raw)
    if m_en:
        mon = _EN_MONTH_ABBR.get(m_en.group(1).lower()[:3])
        if mon is not None:
            try:
                return date(year, mon, int(m_en.group(2)))
            except ValueError:
                return None
    return safe_parse_date(raw)


def infer_snapshot_reference_date(
    *,
    user_message: str = "",
    screens: Optional[Sequence[Any]] = None,
    parsed_payload: Optional[Mapping[str, Any]] = None,
) -> Optional[date]:
    """
    Anchor 90d CompareTable to screenshot day (not server ``today``).

    Priority: explicit user CN date → max OCR screen date → None (caller uses today).
    """
    ref_cap = effective_query_reference_date()
    year = ref_cap.year
    candidates: List[date] = []

    msg = user_message or ""
    m_full = _USER_CN_MD_RE.search(msg)
    if m_full:
        d = safe_parse_date(f"{m_full.group(1)}-{int(m_full.group(2)):02d}-{int(m_full.group(3)):02d}")
        if d:
            candidates.append(d)
    for pat in (_USER_CN_MD_SHORT_RE, _USER_CN_MD_HAO_RE):
        m = pat.search(msg)
        if m:
            try:
                candidates.append(date(year, int(m.group(1)), int(m.group(2))))
            except ValueError:
                pass

    screen_list: List[Any] = list(screens or [])
    if parsed_payload and not screen_list:
        raw = parsed_payload.get("wearable_snapshot_v1") or {}
        if isinstance(raw, dict):
            screen_list = list(raw.get("screens") or [])

    for s in screen_list:
        hint = ""
        if hasattr(s, "date_hint"):
            hint = str(getattr(s, "date_hint") or "")
        elif isinstance(s, dict):
            hint = str(s.get("date_hint") or "")
        d = date_hint_to_date(hint, default_year=year)
        if d:
            candidates.append(d)

    if not candidates:
        return None
    anchor = max(candidates)
    if anchor > ref_cap:
        return ref_cap
    return anchor


def _format_hr_min_value(hr: str, minutes: str = "") -> Tuple[str, str]:
    mn = (minutes or "").strip()
    if mn:
        return f"{hr}hr{mn}min", f"{mn}min"
    return f"{hr}hr", ""


def user_requests_wearable_snapshot_remerge(user_message: str) -> bool:
    """Follow-up asks to re-check / re-parse prior wearable screenshots."""
    return bool(_WEARABLE_REMERGE_USER_RE.search(user_message or ""))


def normalize_wearable_ocr_text(text: str) -> str:
    """Shared Tesseract denoise for Apple Health UI screenshots (真机 OCR)."""
    raw = (text or "").strip()
    if not raw:
        return raw
    raw = re.sub(r"(\d)\s*/\s*", r"\g<1>7", raw)
    raw = raw.replace("/", "7")
    raw = re.sub(r"(\d{1,2})\s*nr\b", r"\1 hr", raw, flags=re.I)
    raw = re.sub(r"(\d{1,3})\s*ins\b", r"\1 ms", raw, flags=re.I)
    raw = re.sub(r"\bsem\b", "bpm", raw, flags=re.I)
    raw = re.sub(r"(\d{1,2})h[,.\s]+(\d{1,2})\s*min", r"\1 hr \2 min", raw, flags=re.I)
    return raw


def _sleep_line_context(blob: str, match: re.Match[str]) -> str:
    line_start = blob.rfind("\n", 0, match.start()) + 1
    line_end = blob.find("\n", match.end())
    if line_end == -1:
        line_end = len(blob)
    return blob[line_start:line_end]


def _sleep_asleep_match_is_valid(
    blob: str,
    match: re.Match[str],
    *,
    after_asleep_label: bool = False,
) -> bool:
    snippet = match.group(0) or ""
    line = _sleep_line_context(blob, match)
    if _AWAKE_CONTEXT_RE.search(line) or re.search(r"@\s*awake\b", line, re.I):
        return False
    if after_asleep_label or _SLEEP_ASLEEP_BEFORE_LABEL_RE.search(snippet):
        return True
    pre = blob[max(0, match.start() - 48) : match.start()]
    if _TIME_IN_BED_RE.search(pre) and _SLEEP_ASLEEP_BEFORE_LABEL_RE.search(snippet) is None:
        return False
    return True


def _extract_sleep_time_asleep(
    blob: str,
    *,
    source_screen_index: int = 0,
) -> Optional[WearableMetricV1]:
    """Hero KPI: TIME ASLEEP — never use Awake stage duration."""
    text = normalize_wearable_ocr_text(blob)
    if not text:
        return None
    for pat, after_label in (
        (_SLEEP_ASLEEP_AFTER_LABEL_RE, True),
        (_SLEEP_ASLEEP_SAME_LINE_RE, True),
        (_SLEEP_ASLEEP_BEFORE_LABEL_RE, False),
        (_SLEEP_ASLEEP_AFTER_LABEL_LOOSE_RE, True),
        (_SLEEP_CN_ASLEEP_RE, False),
    ):
        m = pat.search(text)
        if not m or not _sleep_asleep_match_is_valid(text, m, after_asleep_label=after_label):
            continue
        val, sub = _format_hr_min_value(m.group(1), m.group(2) or "")
        return _metric(
            "sleep_time_asleep",
            val,
            sub_value=sub,
            source_screen_index=source_screen_index,
            source_line=m.group(0).strip()[:160],
        )
    if re.search(r"time\s+asleep", text, re.I):
        m = _SLEEP_ASLEEP_COMPACT_RE.search(text)
        if m and _sleep_asleep_match_is_valid(text, m):
            val, sub = _format_hr_min_value(m.group(1), m.group(2) or "")
            return _metric(
                "sleep_time_asleep",
                val,
                sub_value=sub,
                source_screen_index=source_screen_index,
                source_line=m.group(0).strip()[:160],
            )
    return None


def _metric(
    metric_id: str,
    value: str,
    *,
    sub_value: str = "",
    source_screen_index: int = 0,
    source_line: str = "",
) -> WearableMetricV1:
    return WearableMetricV1(
        metric_id=metric_id,
        value=value,
        unit=_METRIC_UNIT.get(metric_id, ""),
        sub_value=sub_value,
        source_screen_index=source_screen_index,
        source_line=source_line[:160],
    )


def _extract_resting_hr(blob: str, *, source_screen_index: int) -> Optional[WearableMetricV1]:
    for m in _RESTING_HR_RE.finditer(blob):
        line_start = blob.rfind("\n", 0, m.start()) + 1
        line_end = blob.find("\n", m.end())
        if line_end == -1:
            line_end = len(blob)
        line = blob[line_start:line_end]
        if _WALKING_AVERAGE_RE.search(line):
            continue
        bpm = m.group(1)
        return _metric(
            "resting_heart_rate_bpm",
            bpm,
            source_screen_index=source_screen_index,
            source_line=m.group(0).strip(),
        )
    for m in _RESTING_HR_INVERTED_RE.finditer(blob):
        line_start = blob.rfind("\n", 0, m.start()) + 1
        line_end = blob.find("\n", m.end())
        if line_end == -1:
            line_end = len(blob)
        block = blob[line_start:line_end]
        if _WALKING_AVERAGE_RE.search(block):
            continue
        bpm = m.group(1)
        return _metric(
            "resting_heart_rate_bpm",
            bpm,
            source_screen_index=source_screen_index,
            source_line=m.group(0).strip(),
        )
    return None


def _extract_respiratory_rate(blob: str, *, source_screen_index: int) -> Optional[WearableMetricV1]:
    m = _RESPIRATORY_RANGE_RE.search(blob)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        if 8 <= lo <= 40 and 8 <= hi <= 40:
            val = f"{m.group(1)}-{m.group(2)}"
            return _metric(
                "respiratory_rate",
                val,
                source_screen_index=source_screen_index,
                source_line=m.group(0).strip(),
            )
    for m in _RESPIRATORY_BPM_RE.finditer(blob):
        line = m.group(0)
        if re.search(r"\d\s*M\b", line, re.I):
            continue
        try:
            val_f = float(m.group(1))
        except ValueError:
            continue
        if not (8 <= val_f <= 35):
            continue
        return _metric(
            "respiratory_rate",
            m.group(1),
            source_screen_index=source_screen_index,
            source_line=line.strip(),
        )
    return None


def _extract_sleep_stage(
    blob: str,
    stage_label: str,
    metric_id: str,
    *,
    source_screen_index: int,
) -> Optional[WearableMetricV1]:
    patterns = [
        re.compile(
            rf"(\d{{1,2}})\s*hr(?:\s*(\d{{1,2}})\s*min)?[^\n]{{0,24}}@\s*{stage_label}\b",
            re.I,
        ),
        re.compile(
            rf"(?:@\s*)?{stage_label}\b[\s\n]{{0,8}}"
            rf"(\d{{1,2}})\s*hr(?:\s*(\d{{1,2}})\s*min)?",
            re.I,
        ),
        re.compile(
            rf"(?:@\s*)?{stage_label}\b[\s\n]{{0,8}}"
            rf"(\d{{1,2}})hr(?:\s*(\d{{1,2}})\s*min)?",
            re.I,
        ),
    ]
    for pat in patterns:
        m = pat.search(blob)
        if not m:
            continue
        val, sub = _format_hr_min_value(m.group(1), m.group(2) or "")
        return _metric(
            metric_id,
            val,
            sub_value=sub,
            source_screen_index=source_screen_index,
            source_line=m.group(0).strip(),
        )
    return None


def _extract_workout_metrics(blob: str, *, source_screen_index: int) -> List[WearableMetricV1]:
    out: List[WearableMetricV1] = []
    m = _WORKOUT_HR_RANGE_RE.search(blob)
    if m:
        out.append(
            _metric(
                "workout_heart_rate_range_bpm",
                f"{m.group(1)}-{m.group(2)}",
                source_screen_index=source_screen_index,
                source_line=m.group(0).strip(),
            ),
        )
    m = _WORKOUT_DAYS_4W_RE.search(blob)
    if m:
        out.append(
            _metric(
                "workout_count_recent",
                m.group(1),
                source_screen_index=source_screen_index,
                source_line=m.group(0).strip(),
            ),
        )
    elif (m := _WORKOUT_COUNT_RE.search(blob)):
        out.append(
            _metric(
                "workout_count_recent",
                m.group(1),
                source_screen_index=source_screen_index,
                source_line=m.group(0).strip(),
            ),
        )
    m = _WORKOUT_KCAL_RE.search(blob)
    if m:
        out.append(
            _metric(
                "workout_energy_kcal",
                m.group(1),
                source_screen_index=source_screen_index,
                source_line=m.group(0).strip(),
            ),
        )
    m = _WORKOUT_MIN_RE.search(blob)
    if m:
        out.append(
            _metric(
                "workout_duration_min",
                m.group(1),
                source_screen_index=source_screen_index,
                source_line=m.group(0).strip(),
            ),
        )
    return out


def _metric_display_suffix(m: WearableMetricV1) -> str:
    val = str(m.value or "")
    sub = (m.sub_value or "").strip()
    if sub and sub not in val:
        return f" ({sub})"
    return ""


def extract_metrics_from_ocr(
    ocr_text: str,
    *,
    source_screen_index: int = 0,
) -> List[WearableMetricV1]:
    """Per-screen metric extraction via MetricCandidate IR (Wave 3d-perception-v1)."""
    from pha.wearable_metric_candidates import (
        candidate_merge_enabled,
        candidate_to_wearable_metric,
        extract_metric_candidates_from_ocr,
        merge_metric_candidates_global,
    )

    ocr_text = normalize_wearable_ocr_text(ocr_text)
    if not (ocr_text or "").strip():
        return []
    if not candidate_merge_enabled():
        return _extract_metrics_from_ocr_legacy(ocr_text, source_screen_index=source_screen_index)
    candidates = extract_metric_candidates_from_ocr(
        ocr_text,
        source_screen_index=source_screen_index,
    )
    winners = merge_metric_candidates_global(candidates)
    return [candidate_to_wearable_metric(c) for c in winners.values()]


def _extract_metrics_from_ocr_legacy(
    ocr_text: str,
    *,
    source_screen_index: int = 0,
) -> List[WearableMetricV1]:
    """Rollback path when ``PHA_WEARABLE_CANDIDATE_MERGE=0``."""
    blob = (ocr_text or "").strip()
    if not blob:
        return []
    screen_type = infer_screen_type(blob)
    found: List[WearableMetricV1] = []
    seen: set[str] = set()

    def _add(metric: Optional[WearableMetricV1]) -> None:
        if metric is None or metric.metric_id in seen:
            return
        found.append(metric)
        seen.add(metric.metric_id)

    for pat in _HRV_PATTERNS:
        m = pat.search(blob)
        if m:
            _add(
                _metric(
                    "hrv_rmssd_ms",
                    m.group(1),
                    source_screen_index=source_screen_index,
                    source_line=m.group(0).strip(),
                ),
            )
            break

    for pat in _SPO2_PATTERNS:
        m = pat.search(blob)
        if m:
            _add(
                _metric(
                    "spo2_percent",
                    m.group(1),
                    source_screen_index=source_screen_index,
                    source_line=m.group(0).strip(),
                ),
            )
            break

    if screen_type in ("heart_rate", "workout", "unknown") or re.search(
        r"resting|heart\s+rate|\bbpm\b",
        blob,
        re.I,
    ):
        _add(_extract_resting_hr(blob, source_screen_index=source_screen_index))
        m = _HEART_RATE_RANGE_RE.search(blob)
        if m:
            _add(
                _metric(
                    "heart_rate_range_bpm",
                    f"{m.group(1)}-{m.group(2)}",
                    sub_value=m.group(2),
                    source_screen_index=source_screen_index,
                    source_line=m.group(0).strip(),
                ),
            )

    if screen_type in ("respiratory_rate", "unknown"):
        _add(_extract_respiratory_rate(blob, source_screen_index=source_screen_index))

    if screen_type in ("sleep", "unknown"):
        _add(_extract_sleep_time_asleep(blob, source_screen_index=source_screen_index))
        _add(_extract_sleep_stage(blob, "Deep", "sleep_deep", source_screen_index=source_screen_index))
        _add(_extract_sleep_stage(blob, "REM", "sleep_rem", source_screen_index=source_screen_index))

    if screen_type == "workout" or re.search(
        r"heart\s+rate:\s*workout|workouts?\s+highlights|"
        r"during your (?:recent\s+run|last\s+workout)|worked out on \d+ days",
        blob,
        re.I,
    ):
        for wm in _extract_workout_metrics(blob, source_screen_index=source_screen_index):
            _add(wm)

    return found


def screen_from_part(part: Dict[str, Any], *, index: int) -> WearableScreenV1:
    ocr = str(part.get("ocr_text") or "").strip()
    layout_meta = part.get("layout_region_meta") or {}
    region_types = list(layout_meta.get("layout_region_types") or [])
    if not region_types:
        region_types = list(part.get("layout_hints") or [])[:6]
    return WearableScreenV1(
        index=index,
        screen_type=infer_screen_type(ocr),
        date_hint=extract_date_hint(ocr),
        ocr_excerpt=ocr[:2000],
        layout_region_types=[str(x) for x in region_types[:8]],
    )


def merge_wearable_parts(
    parts: List[Dict[str, Any]],
    *,
    perception_channel: PerceptionChannel = "ocr_only",
) -> WearableSnapshotLedgerV1:
    from pha.wearable_metric_candidates import (
        candidate_merge_enabled,
        candidate_to_wearable_metric,
        extract_metric_candidates_from_ocr,
        merge_metric_candidates_global,
    )

    screens: List[WearableScreenV1] = []
    trace: List[Dict[str, Any]] = []
    all_candidates = []

    for i, part in enumerate(parts):
        ocr = str(part.get("ocr_text") or "")
        screens.append(screen_from_part(part, index=i))
        if candidate_merge_enabled():
            cands = extract_metric_candidates_from_ocr(ocr, source_screen_index=i)
            all_candidates.extend(cands)
            trace.append(
                {
                    "index": i,
                    "screen_type": screens[-1].screen_type,
                    "metric_ids": [c.metric_id for c in cands],
                    "candidates": [c.model_dump(mode="python") for c in cands[:24]],
                },
            )
        else:
            per_screen = extract_metrics_from_ocr(ocr, source_screen_index=i)
            trace.append(
                {
                    "index": i,
                    "screen_type": screens[-1].screen_type,
                    "metric_ids": [x.metric_id for x in per_screen],
                },
            )

    if candidate_merge_enabled():
        winners = merge_metric_candidates_global(all_candidates)
        metrics = [candidate_to_wearable_metric(c) for c in winners.values()]
    else:
        metrics_by_id: Dict[str, WearableMetricV1] = {}
        for i, part in enumerate(parts):
            ocr = str(part.get("ocr_text") or "")
            for m in extract_metrics_from_ocr(ocr, source_screen_index=i):
                prev = metrics_by_id.get(m.metric_id)
                if prev is None or len(m.source_line) > len(prev.source_line):
                    metrics_by_id[m.metric_id] = m
        metrics = list(metrics_by_id.values())

    return WearableSnapshotLedgerV1(
        attachment_count=max(1, len(parts)),
        screens=screens,
        metrics=metrics,
        perception_channel=perception_channel,
        merge_trace=trace,
    )


def assess_wearable_confidence(
    ledger: WearableSnapshotLedgerV1,
    *,
    attachment_count: int,
    user_message: str = "",
) -> Tuple[ParseConfidence, List[str], List[str]]:
    from pha.wearable_harness import user_requests_wearable_comparison

    reasons: List[str] = []
    warnings: List[str] = []
    has_ocr = any((s.ocr_excerpt or "").strip() for s in ledger.screens)
    if not ledger.metrics and not has_ocr:
        reasons.append("gw1_no_metrics")
    elif not ledger.metrics and has_ocr:
        warnings.append("ocr_sparse")

    if user_requests_wearable_comparison(user_message) and len(ledger.metrics) < 1:
        reasons.append("gw2_compare_insufficient")

    if attachment_count >= 2:
        missing = sum(1 for s in ledger.screens if not (s.ocr_excerpt or "").strip())
        if missing > max(1, attachment_count // 2):
            reasons.append("gw3_screens_sparse")

    for m in ledger.metrics:
        if m.metric_id == "hrv_rmssd_ms":
            try:
                hrv_v = float(str(m.value).strip())
            except ValueError:
                warnings.append("hrv_snapshot_unparsed")
                break
            if hrv_v < 12:
                warnings.append("hrv_snapshot_low_confidence")
            break

    if reasons:
        conf: ParseConfidence = "low"
    elif len(ledger.metrics) >= 2:
        conf = "high"
    elif ledger.metrics:
        conf = "medium"
    else:
        conf = "medium" if has_ocr else "low"
    return conf, list(dict.fromkeys(reasons)), list(dict.fromkeys(warnings))


def build_wearable_ledger_markdown(ledger: WearableSnapshotLedgerV1) -> str:
    lines = [
        f"【穿戴截图定账 · {ledger.attachment_count} 张 · {ledger.source_app_hint} · 供核对】",
        "【90d 对比约束】个人 90 天对比数字以 WEARABLE_COMPARE_TABLE 为准；勿从宏观摘要抄 KPI 均值。",
    ]
    if ledger.metrics:
        for m in ledger.metrics[:32]:
            extra = _metric_display_suffix(m)
            src = f" ← 屏{m.source_screen_index} {m.source_line}" if m.source_line else ""
            lines.append(
                f"- {m.metric_id}: {m.value} {m.unit}{extra}".strip() + src,
            )
    else:
        lines.append("- （未能从 OCR 抠出结构化 KPI；可结合 WEARABLE_90D_SUMMARY 数仓对比）")
    for s in ledger.screens[:8]:
        if s.screen_type != "unknown":
            lines.append(f"- screen[{s.index}] type={s.screen_type} date={s.date_hint or '—'}")
    return "\n".join(lines)


def build_wearable_snapshot_tier0_block(parsed: Dict[str, Any]) -> str:
    md = (parsed.get("label_ledger") or parsed.get("vision_summary") or "").strip()
    raw = parsed.get("wearable_snapshot_v1")
    summary = ""
    if isinstance(raw, dict):
        metrics = raw.get("metrics") or []
        if metrics:
            summary = json.dumps(metrics[:24], ensure_ascii=False, indent=0)[:2400]
    parts = [p for p in (md, summary) if p]
    if not parts:
        return ""
    body = parts[0]
    if summary and summary not in body:
        body = f"{body}\n\n【结构化 metrics JSON】\n{summary}"
    return f"【穿戴截图定账 · Tier0】\n{body}"


def finalize_wearable_attachment(
    parsed: Dict[str, Any],
    *,
    attachment_count: int = 1,
    parts: Optional[List[Dict[str, Any]]] = None,
    perception_channel: PerceptionChannel = "ocr_only",
    user_message: str = "",
) -> Dict[str, Any]:
    from pha.perception_family import (
        LAB_FAMILY,
        SUPPLEMENT_FAMILY,
        UNKNOWN_FAMILY,
        WEARABLE_FAMILY,
        coerce_wearable_family,
        family_from_parsed,
        ocr_suggests_wearable_ui,
        parts_should_finalize_as_wearable,
    )

    parsed = dict(parsed)
    coerced_parts = [coerce_wearable_family(dict(p)) for p in parts] if parts else None

    if coerced_parts and len(coerced_parts) > 1:
        fams = {family_from_parsed(p) for p in coerced_parts}
        combined_ocr = str(parsed.get("ocr_text") or "").strip() or "\n".join(
            str(p.get("ocr_text") or "") for p in coerced_parts
        )
        batch_wearable = parts_should_finalize_as_wearable(coerced_parts)
        soft_mix = fams <= {WEARABLE_FAMILY, UNKNOWN_FAMILY}
        hard_mix = bool(
            fams
            & {
                SUPPLEMENT_FAMILY,
                LAB_FAMILY,
                "medication",
            },
        )

        if hard_mix and (WEARABLE_FAMILY in fams or batch_wearable):
            out = dict(parsed)
            out["document_family"] = "unknown"
            out["document_type"] = "other"
            out["ingredient_rows"] = []
            out["parse_confidence"] = "low"
            out["reject_reasons"] = ["merge_family_conflict"]
            out["warnings"] = [f"merge_family_conflict:{','.join(sorted(fams))}"]
            out["attachment_count"] = attachment_count
            return out

        if batch_wearable or (soft_mix and len(fams) > 1 and ocr_suggests_wearable_ui(combined_ocr)):
            parts = coerced_parts
            parsed["document_family"] = WEARABLE_FAMILY
            parsed["document_type"] = "apple_watch"
            if len(fams) > 1:
                coerced_warn = f"merge_family_coerced:{','.join(sorted(fams))}"
                parsed["warnings"] = list(dict.fromkeys(list(parsed.get("warnings") or []) + [coerced_warn]))
        elif len(fams) > 1:
            out = dict(parsed)
            out["document_family"] = "unknown"
            out["document_type"] = "other"
            out["ingredient_rows"] = []
            out["parse_confidence"] = "low"
            out["reject_reasons"] = ["merge_family_conflict"]
            out["warnings"] = [f"merge_family_conflict:{','.join(sorted(fams))}"]
            out["attachment_count"] = attachment_count
            return out
        elif fams != {WEARABLE_FAMILY}:
            parts = None
        else:
            parts = coerced_parts
    elif coerced_parts:
        parts = coerced_parts

    if parts and len(parts) >= 1:
        ledger = merge_wearable_parts(parts, perception_channel=perception_channel)
    else:
        ocr = str(parsed.get("ocr_text") or "")
        ledger = merge_wearable_parts(
            [{"ocr_text": ocr, "layout_region_meta": parsed.get("layout_region_meta")}],
            perception_channel=perception_channel,
        )
        ledger.attachment_count = max(1, attachment_count)

    conf, reasons, warns = assess_wearable_confidence(
        ledger,
        attachment_count=ledger.attachment_count,
        user_message=user_message,
    )
    ledger.parse_confidence = conf
    ledger.reject_reasons = reasons
    ledger.warnings = warns
    ledger.ledger_markdown = build_wearable_ledger_markdown(ledger)

    out = dict(parsed)
    out.update(ledger.to_parsed_dict())
    snap_ref = infer_snapshot_reference_date(
        user_message=user_message,
        screens=ledger.screens,
    )
    if snap_ref is not None:
        out["snapshot_reference_date"] = snap_ref.isoformat()
    return out


# Back-compat alias
finalize_wearable_parsed_payload = finalize_wearable_attachment


def remerge_wearable_parsed_payload(
    parsed: Mapping[str, Any],
    *,
    user_message: str = "",
) -> Dict[str, Any]:
    """Re-run OCR merge from stored screen excerpts (correction / follow-up turns)."""
    base = dict(parsed)
    ws = base.get("wearable_snapshot_v1") or {}
    screens = list(ws.get("screens") or []) if isinstance(ws, dict) else []
    parts: List[Dict[str, Any]] = []
    for sc in screens:
        if not isinstance(sc, dict):
            continue
        ocr = str(sc.get("ocr_excerpt") or "").strip()
        if ocr:
            parts.append({"ocr_text": ocr, "document_family": "wearable"})
    if not parts:
        combined = str(base.get("ocr_text") or "").strip()
        if combined:
            chunks = [c.strip() for c in re.split(r"\n\s*\n+", combined) if c.strip()]
            if len(chunks) >= 2:
                parts = [{"ocr_text": c, "document_family": "wearable"} for c in chunks]
            else:
                parts = [{"ocr_text": combined, "document_family": "wearable"}]
    if not parts:
        return base
    channel = str(base.get("perception_channel") or "ocr_only")
    return finalize_wearable_attachment(
        base,
        attachment_count=max(int(base.get("attachment_count") or 0), len(parts)),
        parts=parts,
        perception_channel=channel,  # type: ignore[arg-type]
        user_message=user_message,
    )


__all__ = [
    "WearableMetricV1",
    "WearableScreenV1",
    "WearableSnapshotLedgerV1",
    "assess_wearable_confidence",
    "build_wearable_ledger_markdown",
    "build_wearable_snapshot_tier0_block",
    "date_hint_to_date",
    "extract_metrics_from_ocr",
    "extract_date_hint",
    "finalize_wearable_attachment",
    "infer_snapshot_reference_date",
    "finalize_wearable_parsed_payload",
    "merge_wearable_parts",
    "normalize_wearable_ocr_text",
    "remerge_wearable_parsed_payload",
    "user_requests_wearable_snapshot_remerge",
]
