"""Persist vision extraction results from the event drawer into SQLite."""

from __future__ import annotations

import re
from datetime import date
from typing import Any, List, Optional, Sequence

from pha.data_sanitizer import parse_numeric_value
from pha.medical_storage import (
    HealthNarrativeRow,
    MedicalMetricRow,
    _metrics_preview_from_rows,
    _narrative_summary,
    normalize_and_enrich_row,
    upsert_health_narratives,
    upsert_medical_metrics,
    upsert_health_report_asset,
)
from pha.vision_engine import ReportExtraction, LabResultRow, NarrativeRow


def _parse_numeric_value(raw: str) -> Optional[float]:
    return parse_numeric_value(raw)


def extraction_to_metric_rows(
    extraction: ReportExtraction,
    *,
    user_id: str,
    report_date: date,
    source_filename: str = "",
) -> List[MedicalMetricRow]:
    uid = (user_id or "default").strip() or "default"
    rows: List[MedicalMetricRow] = []
    for r in extraction.results:
        if not isinstance(r, LabResultRow):
            continue
        name = (r.item or "").strip()
        if not name:
            continue
        val_s = (r.value or "").strip()
        unit = (r.unit or "").strip()
        ref = (r.ref or "").strip()
        num = _parse_numeric_value(val_s)
        if num is None and val_s and not unit:
            unit = val_s
        elif num is None and val_s and unit:
            unit = f"{val_s} {unit}".strip()
        row = normalize_and_enrich_row(
            uid,
            report_date,
            name,
            num,
            unit,
            ref,
            source_filename=source_filename,
        )
        if row is not None:
            rows.append(row)
    return rows


def persist_extraction_metrics(
    extraction: ReportExtraction,
    *,
    user_id: str,
    report_date: date,
    source_filename: str = "",
    vision_model: str = "",
    vision_raw: Optional[dict[str, Any]] = None,
) -> tuple[int, int, List[MedicalMetricRow]]:
    """Replace same-day metrics, insert rows, save asset archive. Returns (stored, abnormal_n, rows)."""
    uid = (user_id or "default").strip() or "default"
    rows = extraction_to_metric_rows(
        extraction,
        user_id=uid,
        report_date=report_date,
        source_filename=source_filename,
    )
    narrative_rows = extraction_to_narrative_rows(
        extraction,
        user_id=uid,
        report_date=report_date,
        source_filename=source_filename,
    )
    if rows:
        upsert_medical_metrics(rows)
    if narrative_rows:
        upsert_health_narratives(narrative_rows)
    raw = vision_raw if vision_raw is not None else extraction.model_dump(mode="python")
    upsert_health_report_asset(
        uid,
        report_date,
        source_filename=source_filename,
        source_kind="event_drawer",
        vision_model=vision_model,
        vision_raw=raw,
        metrics_preview=_metrics_preview_from_rows(rows),
    )
    abnormal_n = sum(1 for r in rows if r.is_abnormal)
    return len(rows), abnormal_n, rows


def extraction_to_narrative_rows(
    extraction: ReportExtraction,
    *,
    user_id: str,
    report_date: date,
    source_filename: str = "",
    hospital: str = "",
) -> List[HealthNarrativeRow]:
    uid = (user_id or "default").strip() or "default"
    hosp = (hospital or extraction.hospital or "").strip()
    out: List[HealthNarrativeRow] = []
    for n in extraction.narratives:
        if not isinstance(n, NarrativeRow):
            continue
        content = (n.content or "").strip()
        if not content:
            continue
        summary = (n.summary or "").strip() or _narrative_summary(content)
        out.append(
            HealthNarrativeRow(
                user_id=uid,
                report_date=report_date,
                hospital=hosp,
                category=(n.category or "").strip() or "未分类",
                content=content,
                summary=summary,
                source_filename=source_filename,
            ),
        )
    return out


def narratives_preview_dicts(
    narratives: Sequence[NarrativeRow],
    *,
    hospital: str = "",
) -> List[dict[str, Any]]:
    out: List[dict[str, Any]] = []
    for n in narratives:
        content = (n.content or "").strip()
        if not content:
            continue
        summary = (n.summary or "").strip() or _narrative_summary(content)
        out.append(
            {
                "category": (n.category or "").strip() or "未分类",
                "content": content,
                "summary": summary,
                "hospital": hospital,
            },
        )
    return out


def rows_from_client_narratives(
    narratives: Sequence[dict[str, Any]],
    *,
    user_id: str,
    report_date: date,
    source_filename: str = "",
    hospital: str = "",
) -> List[HealthNarrativeRow]:
    uid = (user_id or "default").strip() or "default"
    hosp = (hospital or "").strip()
    out: List[HealthNarrativeRow] = []
    for entry in narratives:
        if not isinstance(entry, dict):
            continue
        content = str(entry.get("content") or "").strip()
        if not content:
            continue
        category = str(entry.get("category") or "").strip() or "未分类"
        summary = str(entry.get("summary") or "").strip() or _narrative_summary(content)
        row_hosp = str(entry.get("hospital") or hosp).strip()
        out.append(
            HealthNarrativeRow(
                user_id=uid,
                report_date=report_date,
                hospital=row_hosp or hosp,
                category=category,
                content=content,
                summary=summary,
                source_filename=source_filename,
            ),
        )
    return out


def metrics_preview_dicts(rows: Sequence[MedicalMetricRow]) -> List[dict[str, Any]]:
    out: List[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "item": r.metric_name,
                "metric_name": r.metric_name,
                "metric_code": r.metric_code,
                "value": r.value,
                "value_text": f"{r.value:g}" if r.value is not None else "",
                "unit": r.unit,
                "ref": r.reference_range,
                "reference_range": r.reference_range,
                "is_abnormal": r.is_abnormal,
            }
        )
    return out


def rows_from_client_metrics(
    metrics: Sequence[dict[str, Any]],
    *,
    user_id: str,
    report_date: date,
    source_filename: str = "",
) -> List[MedicalMetricRow]:
    uid = (user_id or "default").strip() or "default"
    rows: List[MedicalMetricRow] = []
    for entry in metrics:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("item") or entry.get("metric_name") or "").strip()
        if not name:
            continue
        val_raw = entry.get("value")
        if val_raw is None or val_raw == "":
            val_raw = entry.get("value_text") or ""
        num: Optional[float] = None
        if isinstance(val_raw, (int, float)):
            num = float(val_raw)
        else:
            num = _parse_numeric_value(str(val_raw))
        unit = str(entry.get("unit") or "")
        ref = str(entry.get("ref") or entry.get("reference_range") or "")
        row = normalize_and_enrich_row(
            uid,
            report_date,
            name,
            num,
            unit,
            ref,
            source_filename=source_filename,
        )
        if row is not None:
            rows.append(row)
    return rows
