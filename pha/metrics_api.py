"""Dynamic metric catalog and cross-year trend series for PHA dashboard."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence

from fastapi import APIRouter, HTTPException, Query

from pha.health_data import effective_query_reference_date
from pha.metric_catalog_ui import build_metrics_catalog_payload
from pha.medical_storage import list_available_metrics_catalog, query_metric_timeseries
from pha.sqlite_storage import init_schema

router = APIRouter(prefix="/api/v1", tags=["metrics"])


@router.get("/available_metrics")
def available_metrics(user_id: str = Query("default")) -> dict[str, Any]:
    """``SELECT DISTINCT`` medical + wearable metrics for UI multi-select."""
    init_schema()
    uid = (user_id or "default").strip() or "default"
    medical = list_available_metrics_catalog(uid)
    payload = build_metrics_catalog_payload(medical)
    payload["user_id"] = uid
    payload["count"] = len(payload.get("metrics") or [])
    return payload


@router.get("/metric-trends")
def metric_trends(
    user_id: str = Query("default"),
    metrics: str = Query(..., description="Comma-separated metric ids, e.g. LDL,BASO#,steps"),
    years: float = Query(10.0, ge=0.5, le=30.0),
) -> dict[str, Any]:
    """Historical series per selected metric for dynamic Chart.js rendering."""
    init_schema()
    uid = (user_id or "default").strip() or "default"
    ref = effective_query_reference_date()
    start = ref - timedelta(days=int(years * 365))
    ids = [m.strip() for m in metrics.split(",") if m.strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="metrics query param required")
    series: Dict[str, Any] = {}
    for mid in ids[:24]:
        pts = query_metric_timeseries(uid, mid, start, ref)
        series[mid] = {
            "metric_id": mid,
            "points": [{"label": p["label"], "value": p["value"]} for p in pts],
            "count": len(pts),
        }
    return {
        "user_id": uid,
        "start_date": start.isoformat(),
        "end_date": ref.isoformat(),
        "series": series,
        "has_data": any(s.get("count", 0) > 0 for s in series.values()),
    }
