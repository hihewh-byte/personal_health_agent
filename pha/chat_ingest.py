"""Persist vision-parsed chat attachments into SQLite health ledger."""

from __future__ import annotations

import json
from datetime import date, datetime, time
from typing import Any, Dict, List, Optional

from pha.event_medical import rows_from_client_metrics, rows_from_client_narratives
from pha.data_audit import ldl_value_from_metrics_blob, record_ingest_ldl_trace
from pha.medical_storage import (
    upsert_health_narratives,
    upsert_medical_metrics,
    upsert_health_report_asset,
    query_ldl_metrics_for_calendar_years,
    sanitize_ldl_value,
)
from pha.chat_storage import get_message, update_message_ingested


def _parse_report_date(raw: str) -> date:
    text = (raw or "").strip()[:10]
    if len(text) >= 10:
        return date.fromisoformat(text[:10])
    return date.today()


def ingest_parsed_payload(
    *,
    user_id: str,
    report_date: str,
    hospital: str = "",
    source_filename: str = "",
    source_kind: str = "chat_ingest",
    metrics: List[Dict[str, Any]],
    narratives: List[Dict[str, Any]],
    vision_raw: Optional[Dict[str, Any]] = None,
    vision_model: str = "",
) -> Dict[str, Any]:
    uid = (user_id or "default").strip() or "default"
    d = _parse_report_date(report_date)
    src = (source_filename or "chat_ingest").strip()
    hosp = (hospital or "").strip()

    metrics_stored = 0
    narratives_stored = 0
    abnormal_count = 0

    if metrics:
        metric_rows = rows_from_client_metrics(
            metrics,
            user_id=uid,
            report_date=d,
            source_filename=src,
        )
        if metric_rows:
            metrics_stored = upsert_medical_metrics(metric_rows)
            abnormal_count = sum(1 for r in metric_rows if r.is_abnormal)
            parsed_ldl = ldl_value_from_metrics_blob(metrics)
            db_rows = query_ldl_metrics_for_calendar_years(uid, [d.year], security_inspect=False)
            record_ingest_ldl_trace(
                uid,
                d,
                raw_snippet=str(vision_raw or metrics)[:120],
                parsed_value=parsed_ldl,
                db_value=sanitize_ldl_value(db_rows[0].value) if db_rows else None,
                source_filename=src,
            )

    if narratives:
        narrative_rows = rows_from_client_narratives(
            narratives,
            user_id=uid,
            report_date=d,
            source_filename=src,
            hospital=hosp,
        )
        if narrative_rows:
            narratives_stored = upsert_health_narratives(narrative_rows)

    if metrics_stored or narratives_stored:
        upsert_health_report_asset(
            uid,
            d,
            source_filename=src,
            source_kind=(source_kind or "chat_ingest").strip() or "chat_ingest",
            vision_model=(vision_model or "").strip(),
            vision_raw=vision_raw or {"metrics": len(metrics), "narratives": len(narratives)},
        )

    return {
        "ok": True,
        "report_date": d.isoformat(),
        "metrics_stored": metrics_stored,
        "narratives_stored": narratives_stored,
        "abnormal_count": abnormal_count,
    }


def ingest_chat_message(
    message_id: int,
    *,
    user_id: str,
    metrics: Optional[List[Dict[str, Any]]] = None,
    narratives: Optional[List[Dict[str, Any]]] = None,
    report_date: Optional[str] = None,
    hospital: str = "",
) -> Dict[str, Any]:
    msg = get_message(message_id)
    if not msg:
        return {"ok": False, "error": "message not found"}

    payload: Dict[str, Any] = {}
    if msg.parsed_json:
        try:
            payload = json.loads(msg.parsed_json)
        except json.JSONDecodeError:
            payload = {}

    m = metrics if metrics is not None else payload.get("metrics") or []
    n = narratives if narratives is not None else payload.get("narratives") or []
    rd = report_date or payload.get("report_date") or datetime.utcnow().date().isoformat()
    hosp = hospital or payload.get("hospital") or ""
    src = msg.attachment_name or payload.get("source_filename") or "chat_attachment"

    result = ingest_parsed_payload(
        user_id=user_id,
        report_date=rd,
        hospital=hosp,
        source_filename=src,
        metrics=m,
        narratives=n,
        vision_raw=payload,
    )
    if result.get("ok"):
        update_message_ingested(message_id, ingested_at=datetime.utcnow().replace(microsecond=0).isoformat() + "Z")
    return result
