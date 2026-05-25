"""Dashboard hero stats for PHA console."""

from __future__ import annotations

import json
import time
from datetime import timedelta
from typing import Iterator

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from pha.build_marker import PHA_SERVER_BUILD
from pha.health_data import effective_query_reference_date
from pha.medical_alerts_engine import get_cached_alert_count, get_professional_medical_alerts
from pha.medical_storage import (
    get_health_report_asset,
    list_health_report_assets,
)
from pha.sqlite_storage import count_wearable_samples, get_max_wearable_timestamp, query_wearable_daily_range
from pha.sync_status import build_sync_status_payload

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

SLOW_PATH_STAGE_MESSAGES = (
    "🔬 正在读取本地 SQLite 数据库，动态对齐全量健康资产...",
    "🔗 正在提取体检日时间锚点，动态检索跨表穿戴设备 WASO 睡眠流水...",
    "🧠 顶级医学大模型医生正在进行全动态深度审阅、跨表推导代谢因果链...",
)


def _alerts_payload(uid: str, items: list) -> dict:
    return {
        "user_id": uid,
        "count": len(items),
        "items": items,
        "slow_path": True,
        "pha_build": PHA_SERVER_BUILD,
    }


@router.get("/sync-status")
def sync_status(user_id: str = Query("default")) -> dict:
    """Apple Health import / sync dashboard for the data drawer."""
    return build_sync_status_payload(user_id)


@router.get("/hero-stats")
def hero_stats(user_id: str = Query("default")) -> dict:
    uid = (user_id or "default").strip() or "default"
    ref = effective_query_reference_date()
    week_start = ref - timedelta(days=6)
    rows = query_wearable_daily_range(uid, week_start, ref)

    today_steps = None
    avg_hrv = None
    avg_sleep = None
    if rows:
        latest = rows[-1]
        today_steps = latest.steps
        hrv_vals = [float(r.hrv_rmssd_ms) for r in rows if r.hrv_rmssd_ms is not None]
        sleep_vals = [float(r.sleep_hours) for r in rows if r.sleep_hours is not None]
        if hrv_vals:
            avg_hrv = sum(hrv_vals) / len(hrv_vals)
        if sleep_vals:
            avg_sleep = sum(sleep_vals) / len(sleep_vals)

    # Hero card: cached LLM count only — never invoke 10–20s slow path on poll
    cached_n = get_cached_alert_count(uid)
    abnormal_n = cached_n if cached_n is not None else 0
    db_max = get_max_wearable_timestamp(uid)
    samples = count_wearable_samples(uid)

    return {
        "user_id": uid,
        "today_steps": today_steps,
        "avg_hrv_7d": round(avg_hrv, 1) if avg_hrv is not None else None,
        "avg_sleep_7d": round(avg_sleep, 2) if avg_sleep is not None else None,
        "medical_alerts": abnormal_n,
        "db_samples": samples,
        "db_max_timestamp": db_max.isoformat() if db_max else None,
    }


@router.get("/medical-alerts")
def medical_alerts(
    user_id: str = Query("default"),
    refresh: bool = Query(False, description="Bypass cache and re-run LLM clinical review"),
) -> dict:
    """LLM clinical review alerts (slow path, accuracy-first)."""
    uid = (user_id or "default").strip() or "default"
    ref = effective_query_reference_date()
    items = get_professional_medical_alerts(
        uid,
        ref,
        use_cache=not refresh,
        force_refresh=refresh,
    )
    return _alerts_payload(uid, items)


def _medical_alerts_sse(uid: str, *, refresh: bool) -> Iterator[str]:
    ref = effective_query_reference_date()
    yield f"data: {json.dumps({'event': 'stage', 'stage': 1, 'message': SLOW_PATH_STAGE_MESSAGES[0]}, ensure_ascii=False)}\n\n"
    time.sleep(0.05)
    yield f"data: {json.dumps({'event': 'stage', 'stage': 2, 'message': SLOW_PATH_STAGE_MESSAGES[1]}, ensure_ascii=False)}\n\n"
    items = get_professional_medical_alerts(
        uid,
        ref,
        use_cache=not refresh,
        force_refresh=refresh,
    )
    yield f"data: {json.dumps({'event': 'stage', 'stage': 3, 'message': SLOW_PATH_STAGE_MESSAGES[2]}, ensure_ascii=False)}\n\n"
    payload = _alerts_payload(uid, items)
    payload["event"] = "done"
    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.get("/medical-alerts/stream")
def medical_alerts_stream(
    user_id: str = Query("default"),
    refresh: bool = Query(False),
) -> StreamingResponse:
    """SSE staged progress for medical alert slow path (frontend UX)."""
    uid = (user_id or "default").strip() or "default"
    return StreamingResponse(
        _medical_alerts_sse(uid, refresh=refresh),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/health-assets")
def health_assets(user_id: str = Query("default")) -> dict:
    uid = (user_id or "default").strip() or "default"
    items = list_health_report_assets(uid)
    return {"user_id": uid, "count": len(items), "items": items}


@router.get("/health-assets/{asset_id}")
def health_asset_detail(asset_id: str, user_id: str = Query("default")) -> dict:
    uid = (user_id or "default").strip() or "default"
    if str(asset_id).startswith("legacy-"):
        return {
            "id": asset_id,
            "message": "该记录来自历史指标聚合，无 Vision 原始 JSON；请重新上传以归档完整 JSON。",
            "vision_raw": {},
        }
    try:
        aid = int(asset_id)
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="invalid asset id") from exc
    row = get_health_report_asset(aid, uid)
    if not row:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="asset not found")
    return row
