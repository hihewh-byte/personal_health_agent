"""Wearable registry HTTP API (Wave 3d C-20)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from pha.wearable_metric_probe import probe_wearable_metric_needs

router = APIRouter(prefix="/api/wearable", tags=["wearable"])


@router.get("/metric-probe")
def wearable_metric_probe(
    user_id: str = Query("default"),
    message: str = Query("", description="User utterance to infer Registry metric_ids"),
) -> dict:
    """Intent → Registry metrics → warehouse readiness (no LLM / no ad-hoc SQL)."""
    return probe_wearable_metric_needs(user_id, message)
